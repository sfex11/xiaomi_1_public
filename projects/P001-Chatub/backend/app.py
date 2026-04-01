"""Chatub Backend - FastAPI application assembly."""

import json
import urllib.request
import urllib.error

from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse

from db import init_db, get_db, new_id, now_ts
from auth import get_current_user
from routers import auth as auth_router
from routers import projects as projects_router
from routers import channels as channels_router
from routers import messages as messages_router
from routers import threads as threads_router
from routers import tasks as tasks_router
from routers import bots as bots_router
from routers import ws as ws_router
from routers import agent as agent_router

app = FastAPI(title="Chatub Backend")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router.router)
app.include_router(projects_router.router)
app.include_router(channels_router.router)
app.include_router(messages_router.router)
app.include_router(threads_router.router)
app.include_router(tasks_router.router)
app.include_router(bots_router.router)
app.include_router(ws_router.router)
app.include_router(agent_router.router)


def json_ok(data=None, status=200):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=status)


def json_err(error, status=400):
    return JSONResponse({"ok": False, "error": error}, status_code=status)


# -- Chat proxy (SSE streaming to Gateway) --

@app.post("/api/chat")
async def handle_chat(request: Request):
    body = await request.body()
    data = json.loads(body)

    gw_url = (request.headers.get("X-Gateway-URL") or "http://127.0.0.1:18789").rstrip("/")
    token = (
        request.headers.get("X-Gateway-Token")
        or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        or ""
    )
    is_stream = data.get("stream", False)

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(
            f"{gw_url}/v1/chat/completions",
            data=json.dumps(data).encode(),
            headers=headers,
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=120)

        if is_stream:
            def generate():
                while True:
                    chunk = resp.read(1024)
                    if not chunk:
                        break
                    yield chunk

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        else:
            result = resp.read()
            return JSONResponse(
                content=json.loads(result),
                headers={"Cache-Control": "no-cache"},
            )

    except urllib.error.HTTPError as e:
        error_body = e.read()
        try:
            error_json = json.loads(error_body)
        except Exception:
            error_json = {"error": error_body.decode(errors="replace")}
        return JSONResponse(content=error_json, status_code=e.code)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=502)


# -- Migration (localStorage -> DB) --

@app.post("/api/migrate")
async def handle_migrate(request: Request, user_id: str = Depends(get_current_user)):
    body = await request.body()
    data = json.loads(body)
    projects = data.get("projects", [])
    db = get_db()
    try:
        ts = now_ts()
        for proj in projects:
            pid = proj.get("id") or new_id()
            existing = db.execute("SELECT id FROM projects WHERE id=?", (pid,)).fetchone()
            if existing:
                continue
            db.execute(
                "INSERT INTO projects (id, user_id, name, description, color, created_at) VALUES (?,?,?,?,?,?)",
                (pid, user_id, proj.get("name", ""), proj.get("description", ""),
                 proj.get("color", "#6366f1"), proj.get("created_at", ts))
            )
            for ch in proj.get("channels", []):
                cid = ch.get("id") or new_id()
                db.execute(
                    "INSERT INTO channels (id, project_id, name, icon, color, created_at) VALUES (?,?,?,?,?,?)",
                    (cid, pid, ch.get("name", ""), ch.get("icon", "#"),
                     ch.get("color", "#6366f1"), ch.get("created_at", ts))
                )
                for msg in ch.get("messages", []):
                    mid = msg.get("id") or new_id()
                    db.execute(
                        "INSERT INTO messages (id, channel_id, user_id, bot_id, text, image, reactions_json, created_at, edited_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (mid, cid, msg.get("user_id") or user_id, msg.get("bot_id"),
                         msg.get("text", ""), msg.get("image", ""),
                         json.dumps(msg.get("reactions", {}), ensure_ascii=False),
                         msg.get("created_at", ts), msg.get("edited_at"))
                    )
                    for th in msg.get("threads", []):
                        tid = th.get("id") or new_id()
                        db.execute(
                            "INSERT INTO threads (id, message_id, user_id, bot_id, text, created_at) VALUES (?,?,?,?,?,?)",
                            (tid, mid, th.get("user_id") or user_id, th.get("bot_id"),
                             th.get("text", ""), th.get("created_at", ts))
                        )
            for task in proj.get("tasks", []):
                tid = task.get("id") or new_id()
                db.execute(
                    "INSERT INTO tasks (id, project_id, channel_id, status, title, description, milestone_id, deadline, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (tid, pid, task.get("channel_id"), task.get("status", "todo"),
                     task.get("title", ""), task.get("description", ""),
                     task.get("milestone_id"), task.get("deadline"), task.get("created_at", ts))
                )
            for ms in proj.get("milestones", []):
                msid = ms.get("id") or new_id()
                db.execute(
                    "INSERT INTO milestones (id, project_id, name, deadline, color, created_at) VALUES (?,?,?,?,?,?)",
                    (msid, pid, ms.get("name", ""), ms.get("deadline"),
                     ms.get("color", "#6366f1"), ms.get("created_at", ts))
                )
            for mem in proj.get("members", []):
                memid = mem.get("id") or new_id()
                db.execute(
                    "INSERT INTO team_members (id, project_id, name, role, avatar_color, created_at) VALUES (?,?,?,?,?,?)",
                    (memid, pid, mem.get("name", ""), mem.get("role", "멤버"),
                     mem.get("avatar_color", "#6366f1"), mem.get("created_at", ts))
                )
            for bot in proj.get("bots", []):
                botid = bot.get("id") or new_id()
                db.execute(
                    "INSERT INTO ai_bots (id, user_id, project_id, name, role, avatar, system_prompt, is_active, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (botid, user_id, pid, bot.get("name", ""), bot.get("role", ""),
                     bot.get("avatar", "🤖"), bot.get("system_prompt", ""),
                     1 if bot.get("is_active", True) else 0, bot.get("created_at", ts))
                )
        db.commit()
        return json_ok({"imported": len(projects)})
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


# -- Static file serving (index.html) --

STATIC_DIR = Path(__file__).resolve().parent.parent / "src"


@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


# -- Startup: init DB --

@app.on_event("startup")
def startup():
    init_db()
    print("Chatub backend (FastAPI) started")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8083)
