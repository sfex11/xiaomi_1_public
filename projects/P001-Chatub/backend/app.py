"""Chatub Backend - FastAPI application assembly."""

import json
import urllib.request
import urllib.error
import asyncio
import httpx

from pathlib import Path

from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

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

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

_limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Chatub Backend")
app.state.limiter = _limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
@_limiter.limit("60/minute")
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


# -- OpenClaw Gateway chat proxy (via Adapter) --

import os
import logging

from adapters import create_adapter

GW_BASE_URL = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
GW_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "05f47308205c82c727a7db35a838a2a0df12c5df21576610")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [chat-proxy] %(message)s")
log = logging.getLogger("gateway-chat")


def _resolve_gateway(gateway_id):
    """Resolve gateway (url, token, name, id, kind) from DB or env defaults."""
    if not gateway_id:
        return GW_BASE_URL, GW_TOKEN, "default", "default", "openclaw"
    db = get_db()
    try:
        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gateway_id,)).fetchone()
        if not gw:
            return None, None, None, None, None
        kind = gw["kind"] if "kind" in gw.keys() else "openclaw"
        return gw["url"], gw["token"] or "", gw["name"], gw["id"], kind or "openclaw"
    finally:
        db.close()


def _log_chat(gw_id, gw_name, messages, assistant_content, model, usage):
    """Save user messages + assistant response to chat_logs."""
    try:
        db = get_db()
        try:
            for m in messages:
                db.execute(
                    "INSERT INTO chat_logs (id,gateway_id,gateway_name,role,content,created_at) VALUES (?,?,?,?,?,?)",
                    (new_id(), gw_id, gw_name, m.get("role", "user"), m.get("content", ""), now_ts()))
            db.execute(
                "INSERT INTO chat_logs (id,gateway_id,gateway_name,role,content,model,tokens_prompt,tokens_completion,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (new_id(), gw_id, gw_name, "assistant", assistant_content, model,
                 usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), now_ts()))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        log.warning("chat log save failed: %s", e)


@app.post("/api/gateway-chat")
@_limiter.limit("60/minute")
async def handle_gateway_chat(request: Request):
    """Proxy chat to any registered Gateway via Adapter.
    Supports multi-gateway: specify gateway_id to route to a specific gateway.
    Falls back to default (localhost) Gateway if no gateway_id provided.
    """
    body = await request.body()
    data = json.loads(body)
    gateway_id = data.pop("gateway_id", None)
    messages = data.get("messages", [])
    is_stream = data.get("stream", True)
    log.info("▶ request: messages=%d, gateway_id=%s, stream=%s", len(messages), gateway_id, is_stream)

    gw_url, gw_token, gw_name, gw_id, kind = _resolve_gateway(gateway_id)
    if gw_url is None:
        return JSONResponse({"ok": False, "error": f"Gateway {gateway_id} not found"}, status_code=404)

    adapter = create_adapter(kind)

    if is_stream:
        # SSE pass-through: build streaming response via adapter
        data["stream"] = True
        extra = {k: v for k, v in data.items() if k not in ("messages", "stream")}

        async def generate():
            full_content = ""
            model = ""
            usage = {}
            try:
                async for event in adapter._stream(gw_url.rstrip("/"), gw_token, {**data}):
                    if event["type"] == "chunk":
                        # Re-encode as SSE line for HTTP clients
                        sse = json.dumps({"choices": [{"delta": {"content": event["content"]}}]})
                        yield f"data: {sse}\n\n"
                        full_content += event["content"]
                    elif event["type"] == "done":
                        full_content = event["content"]
                        model = event.get("model", "")
                        usage = event.get("usage", {})
                        yield "data: [DONE]\n\n"
            except Exception as e:
                log.error("stream error: %s", e)
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            _log_chat(gw_id, gw_name or "", messages, full_content, model, usage)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    else:
        try:
            extra = {k: v for k, v in data.items() if k not in ("messages",)}
            resp = await adapter.send_message(gw_url, gw_token, messages, stream=False, **extra)
            _log_chat(gw_id, gw_name or "", messages, resp.content, resp.model, resp.usage)
            return JSONResponse(content=resp.raw, headers={"Cache-Control": "no-cache"})
        except httpx.HTTPStatusError as e:
            return JSONResponse(content={"error": str(e)}, status_code=e.response.status_code)
        except Exception as e:
            log.error("Exception: %s", e)
            return JSONResponse(content={"error": str(e)}, status_code=502)


# -- Broadcast chat to all online gateways (via Adapter) --

@app.post("/api/gateway-broadcast")
@_limiter.limit("30/minute")
async def handle_broadcast(request: Request):
    """Send message to all online gateways via Adapter, return all responses."""
    body = await request.body()
    data = json.loads(body)
    gateway_id = data.pop("gateway_id", None)
    broadcast = data.pop("broadcast", True)
    messages = data.get("messages", [])
    log.info("▶ broadcast: messages=%d, broadcast=%s, gateway_id=%s", len(messages), broadcast, gateway_id)

    db = get_db()
    try:
        if gateway_id:
            rows = db.execute("SELECT id, name, url, token, kind FROM gateways WHERE id=?", (gateway_id,)).fetchall()
        else:
            rows = db.execute("SELECT id, name, url, token, kind FROM gateways").fetchall()

        async def query_one(gw):
            gw_id, gw_name = gw["id"], gw["name"]
            gw_url, gw_token = gw["url"], gw["token"] or ""
            kind = gw["kind"] if "kind" in gw.keys() else "openclaw"
            adapter = create_adapter(kind or "openclaw")
            try:
                extra = {k: v for k, v in data.items() if k not in ("messages",)}
                resp = await adapter.send_message(gw_url, gw_token, messages, stream=False, **extra)
                _log_chat(gw_id, gw_name, messages, resp.content, resp.model, resp.usage)
                return {"name": gw_name, "id": gw_id, "ok": True,
                        "content": resp.content, "model": resp.model, "usage": resp.usage}
            except Exception as e:
                log.warning("broadcast to %s (%s) failed: %s", gw_name, gw_url, e)
                return {"name": gw_name, "id": gw_id, "ok": False, "error": str(e)}

        results = await asyncio.gather(*[query_one(row) for row in rows])
        result_list = list(results)

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


@app.get("/register")
async def serve_register():
    return FileResponse(STATIC_DIR / "register.html")

# -- Startup: init DB --

@app.on_event("startup")
def startup():
    init_db()
    print("Chatub backend (FastAPI) started")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8083)

