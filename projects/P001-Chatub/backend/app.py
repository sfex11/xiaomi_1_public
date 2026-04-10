"""Chatub Backend - FastAPI application assembly."""

import json
import urllib.request
import urllib.error
import asyncio
import httpx

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
from routers import gateways as gateways_router

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
app.include_router(gateways_router.router)


def json_ok(data=None, status=200):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=status)


def json_err(error, status=400):
    return JSONResponse({"ok": False, "error": error}, status_code=status)


# -- Chat proxy (OpenAI-compatible API relay) --
# The frontend calls the API directly from the browser.
# This endpoint exists as a CORS proxy fallback for environments
# where direct browser→API calls are blocked.

@app.post("/api/chat")
async def handle_chat(request: Request):
    body = await request.body()
    data = json.loads(body)

    api_base = (request.headers.get("X-API-Base-URL") or "https://api.openai.com/v1").rstrip("/")
    api_key = request.headers.get("X-API-Key") or ""
    is_stream = data.get("stream", False)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = urllib.request.Request(
            f"{api_base}/chat/completions",
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


# -- OpenClaw Gateway chat proxy (HTTP /v1/chat/completions) --

import os

GW_BASE_URL = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
GW_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "05f47308205c82c727a7db35a838a2a0df12c5df21576610")

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [chat-proxy] %(message)s")
log = logging.getLogger("gateway-chat")


@app.post("/api/gateway-chat")
async def handle_gateway_chat(request: Request):
    """Proxy chat to any registered Gateway /v1/chat/completions, return SSE stream.
    Supports multi-gateway: specify gateway_id to route to a specific gateway.
    Falls back to default (localhost) Gateway if no gateway_id provided.
    """
    body = await request.body()
    data = json.loads(body)
    gateway_id = data.pop("gateway_id", None)
    log.info("▶ request received: messages=%d, gateway_id=%s", len(data.get("messages", [])), gateway_id)

    # Resolve gateway URL and token
    gw_url = GW_BASE_URL
    gw_token = GW_TOKEN

    if gateway_id:
        from db import get_db
        db = get_db()
        try:
            gw = db.execute("SELECT url, token FROM gateways WHERE id=?", (gateway_id,)).fetchone()
            if gw:
                gw_url = gw["url"]
                gw_token = gw["token"] or ""
                log.info("▶ routing to gateway: %s (%s)", gateway_id, gw_url)
            else:
                return JSONResponse({"ok": False, "error": f"Gateway {gateway_id} not found"}, status_code=404)
        finally:
            db.close()

    headers = {"Content-Type": "application/json"}
    if gw_token:
        headers["Authorization"] = f"Bearer {gw_token}"
        log.info("▶ using token: ...%s", gw_token[-6:])
    else:
        log.info("▶ no token configured")

    is_stream = data.get("stream", True)
    if is_stream:
        data["stream"] = True

    target = f"{gw_url}/v1/chat/completions"
    log.info("▶ proxying to %s (stream=%s)", target, is_stream)

    try:
        req = urllib.request.Request(
            target,
            data=json.dumps(data).encode(),
            headers=headers,
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=120)
        log.info("▶ Gateway response: status=%d", resp.status)

        if is_stream:
            def generate():
                total_bytes = 0
                while True:
                    chunk = resp.read(1024)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    log.info("▶ chunk: %d bytes (total: %d)", len(chunk), total_bytes)
                    yield chunk
                log.info("▶ stream complete: %d total bytes", total_bytes)

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        else:
            result = resp.read()
            log.info("▶ Gateway response body: %s", result[:500])
            parsed = json.loads(result)

            # Log chat to DB
            try:
                from db import get_db, new_id, now_ts
                db = get_db()
                msgs = data.get("messages", [])
                for m in msgs:
                    db.execute(
                        "INSERT INTO chat_logs (id, gateway_id, gateway_name, role, content, created_at) VALUES (?,?,?,?,?,?)",
                        (new_id(), gateway_id or "default", "", m.get("role", "user"), m.get("content", ""), now_ts())
                    )
                # Log assistant response
                choices = parsed.get("choices", [])
                if choices:
                    aid = choices[0].get("message", {}).get("content", "")
                    usage = parsed.get("usage", {})
                    db.execute(
                        "INSERT INTO chat_logs (id, gateway_id, gateway_name, role, content, model, tokens_prompt, tokens_completion, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (new_id(), gateway_id or "default", "", "assistant", aid, parsed.get("model", ""), usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), now_ts())
                    )
                db.commit()
                db.close()
            except Exception as e:
                log.warning("▶ chat log save failed: %s", e)

            return JSONResponse(content=parsed,
                headers={"Cache-Control": "no-cache"},
            )

    except urllib.error.HTTPError as e:
        log.error("▶ HTTP error: %d %s", e.code, e.read()[:500])
        error_body = e.read()
        try:
            error_json = json.loads(error_body)
        except Exception:
            error_json = {"error": error_body.decode(errors="replace")}
        return JSONResponse(content=error_json, status_code=e.code)
    except Exception as e:
        log.error("▶ Exception: %s", str(e))
        return JSONResponse(content={"error": str(e)}, status_code=502)


# -- Broadcast chat to all online gateways --

@app.post("/api/gateway-broadcast")
async def handle_broadcast(request: Request):
    """Send message to all online gateways, return all responses."""
    body = await request.body()
    data = json.loads(body)
    gateway_id = data.pop("gateway_id", None)  # optional: specific gateway
    broadcast = data.pop("broadcast", True)
    log.info("▶ broadcast request: messages=%d, broadcast=%s, gateway_id=%s", len(data.get("messages", [])), broadcast, gateway_id)

    from db import get_db
    db = get_db()
    try:
        if gateway_id:
            rows = db.execute("SELECT id, name, url, token FROM gateways WHERE id=?", (gateway_id,)).fetchall()
        elif broadcast:
            rows = db.execute("SELECT id, name, url, token FROM gateways").fetchall()
        else:
            # Default: only online gateways
            rows = db.execute("SELECT id, name, url, token FROM gateways").fetchall()

        async def query_one(gw):
            gw_url, gw_token, gw_name, gw_id = gw["url"], gw["token"] or "", gw["name"], gw["id"]
            headers = {"Content-Type": "application/json"}
            if gw_token:
                headers["Authorization"] = f"Bearer {gw_token}"
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(f"{gw_url}/v1/chat/completions", json=data, headers=headers)
                    resp.raise_for_status()
                    parsed = resp.json()
                    content = parsed.get("choices", [{}])[0].get("message", {}).get("content", "")
                    usage = parsed.get("usage", {})
                    # Log to DB
                    for m in data.get("messages", []):
                        db.execute(
                            "INSERT INTO chat_logs (id,gateway_id,gateway_name,role,content,created_at) VALUES (?,?,?,?,?,?)",
                            (new_id(), gw_id, gw_name, m.get("role","user"), m.get("content",""), now_ts()))
                    db.execute(
                        "INSERT INTO chat_logs (id,gateway_id,gateway_name,role,content,model,tokens_prompt,tokens_completion,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (new_id(), gw_id, gw_name, "assistant", content, parsed.get("model",""), usage.get("prompt_tokens",0), usage.get("completion_tokens",0), now_ts()))
                    db.commit()
                    return {"name": gw_name, "id": gw_id, "ok": True, "content": content, "model": parsed.get("model",""), "usage": usage}
            except Exception as e:
                log.warning("▶ broadcast to %s (%s) failed: %s", gw_name, gw_url, e)
                return {"name": gw_name, "id": gw_id, "ok": False, "error": str(e)}

        results = await asyncio.gather(*[query_one(row) for row in rows])
        result_list = list(results)

        # Push broadcast results to /ws/status subscribers
        from routers.ws import status_manager
        await status_manager.push("broadcast", {"results": result_list})

        return json_ok(result_list)
    finally:
        db.close()


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

