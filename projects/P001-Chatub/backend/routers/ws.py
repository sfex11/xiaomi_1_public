"""WebSocket real-time chat + status monitoring for channels.

# ─── Reconnection guide (exponential backoff) ───────────────────────
# Clients SHOULD implement exponential backoff when reconnecting to
# /ws/status or /ws/rpc after an unexpected disconnect:
#
#   MAX_ATTEMPTS = 20
#   BASE         = 1          # seconds
#   MAX_DELAY    = 30         # seconds
#
#   attempt = 0
#   while attempt < MAX_ATTEMPTS:
#       delay = min(BASE * (2 ** attempt), MAX_DELAY)
#       sleep(delay + random(0, delay * 0.1))   # jitter
#       try:
#           ws = connect(url)
#           attempt = 0                          # reset on success
#       except:
#           attempt += 1
#
# This avoids thundering-herd reconnect storms when the server restarts.
# ─────────────────────────────────────────────────────────────────────
"""

import json
import asyncio
import logging
from typing import Dict, List, Set

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from auth import verify_token
from crypto import decrypt
from db import get_db, new_id, now_ts, owns_project, project_for_channel

router = APIRouter()
log = logging.getLogger("ws")


# ---------------------------------------------------------------------------
# Channel chat WebSocket manager (existing)
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages WebSocket connections per channel."""

    def __init__(self):
        # channel_id -> list of (websocket, user_id)
        self.active: Dict[str, List[tuple]] = {}

    async def connect(self, channel_id: str, ws: WebSocket, user_id: str):
        await ws.accept()
        self.active.setdefault(channel_id, []).append((ws, user_id))

    def disconnect(self, channel_id: str, ws: WebSocket):
        conns = self.active.get(channel_id, [])
        self.active[channel_id] = [(w, u) for w, u in conns if w is not ws]
        if not self.active[channel_id]:
            del self.active[channel_id]

    async def broadcast(self, channel_id: str, event: str, data: dict):
        """Send a JSON event to all connections in a channel."""
        payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
        conns = self.active.get(channel_id, [])
        dead = []
        for ws, uid in conns:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        if dead:
            self.active[channel_id] = [(w, u) for w, u in conns if w not in dead]


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Status WebSocket manager — /ws/status subscribers
# ---------------------------------------------------------------------------

class StatusManager:
    """Manages /ws/status subscribers and periodic health-push."""

    def __init__(self):
        self.clients: Set[WebSocket] = set()
        self._task: asyncio.Task | None = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)
        log.info("status ws connected (%d total)", len(self.clients))
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._health_loop())

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)
        log.info("status ws disconnected (%d remaining)", len(self.clients))

    async def push(self, event_type: str, data):
        """Push a JSON event to all status subscribers."""
        if not self.clients:
            return
        payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        dead = []
        for ws in self.clients:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def _health_loop(self):
        """Every 10 seconds, query all gateways and push status via adapter."""
        from routers.gateways import _health_check_async
        while self.clients:
            try:
                db = get_db()
                try:
                    rows = db.execute(
                        "SELECT * FROM gateways ORDER BY name"
                    ).fetchall()
                finally:
                    db.close()

                statuses = []
                for row in rows:
                    health = await _health_check_async(row)
                    statuses.append({
                        "id": row["id"],
                        "name": row["name"],
                        "online": health["online"],
                        "state": health["state"],
                        "version": health.get("version"),
                    })

                await self.push("status", statuses)
            except Exception as e:
                log.warning("status health loop error: %s", e)

            await asyncio.sleep(10)


status_manager = StatusManager()


@router.websocket("/ws/channels/{channel_id}")
async def ws_channel(channel_id: str, ws: WebSocket, token: str = Query("")):
    # Authenticate
    user_id = verify_token(token)
    if not user_id:
        await ws.close(code=4001, reason="Unauthorized")
        return

    # Verify channel access
    db = get_db()
    try:
        proj_id = project_for_channel(db, channel_id)
        if not proj_id or not owns_project(db, user_id, proj_id):
            await ws.close(code=4003, reason="Forbidden")
            return
    finally:
        db.close()

    await manager.connect(channel_id, ws, user_id)
    try:
        while True:
            # Keep connection alive; ignore client messages for now
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(channel_id, ws)


@router.websocket("/ws/status")
async def ws_status(ws: WebSocket):
    """Real-time gateway status subscription.
    Pushes {"type":"status","data":[...]} every 10 seconds.
    Also receives broadcast results via {"type":"broadcast","data":{...}}.
    """
    await status_manager.connect(ws)
    try:
        while True:
            # Keep connection alive; ignore client messages
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        status_manager.disconnect(ws)


# ---------------------------------------------------------------------------
# RPC WebSocket — /ws/rpc
# Request:  {"method":"agents.list","id":"req-1","params":{}}
# Response: {"id":"req-1","data":[...]}  or  {"id":"req-1","error":"..."}
# ---------------------------------------------------------------------------

_RPC_TIMEOUT = 10  # seconds

# Method registry — each entry is an async callable(params) -> data
_RPC_METHODS: Dict[str, object] = {}


def _register_rpc_methods():
    """Populate the RPC method table (called once at module load)."""
    from routers.gateways import _health_check_async

    async def agents_list(params):
        """Return all gateways with health + agent state via adapter."""
        db = get_db()
        try:
            rows = db.execute(
                "SELECT * FROM gateways ORDER BY name"
            ).fetchall()
            result = []
            for row in rows:
                health = await _health_check_async(row)
                result.append({
                    "id": row["id"],
                    "name": row["name"],
                    "online": health["online"],
                    "state": health["state"],
                    "version": health.get("version"),
                })
            return result
        finally:
            db.close()

    async def gateways_stats(params):
        """Return token usage stats (daily/per-gateway)."""
        db = get_db()
        try:
            rows = db.execute(
                "SELECT gateway_id, gateway_name, "
                "date(created_at, 'unixepoch') AS day, "
                "SUM(tokens_prompt) AS prompt_tokens, "
                "SUM(tokens_completion) AS completion_tokens, "
                "COUNT(*) AS messages "
                "FROM chat_logs "
                "GROUP BY gateway_id, day ORDER BY day DESC LIMIT 200"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            db.close()

    _RPC_METHODS["agents.list"] = agents_list
    _RPC_METHODS["gateways.stats"] = gateways_stats


_register_rpc_methods()


@router.websocket("/ws/rpc")
async def ws_rpc(ws: WebSocket):
    """JSON-RPC-style WebSocket endpoint.

    Send: {"method":"agents.list","id":"req-1"}
    Recv: {"id":"req-1","data":[...]}
    Timeout: 10 seconds per request.
    """
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await ws.send_text(json.dumps(
                    {"id": None, "error": "invalid JSON"}, ensure_ascii=False))
                continue

            req_id = msg.get("id")
            method = msg.get("method", "")
            params = msg.get("params", {})

            handler = _RPC_METHODS.get(method)
            if handler is None:
                await ws.send_text(json.dumps(
                    {"id": req_id, "error": f"unknown method: {method}"}, ensure_ascii=False))
                continue

            try:
                data = await asyncio.wait_for(handler(params), timeout=_RPC_TIMEOUT)
                await ws.send_text(json.dumps(
                    {"id": req_id, "data": data}, ensure_ascii=False))
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps(
                    {"id": req_id, "error": "timeout"}, ensure_ascii=False))
            except Exception as e:
                log.warning("rpc %s error: %s", method, e)
                await ws.send_text(json.dumps(
                    {"id": req_id, "error": str(e)}, ensure_ascii=False))
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Streaming chat relay — /ws/chat
# SSE → WebSocket: Gateway streaming responses relayed in real-time
# ---------------------------------------------------------------------------

async def _stream_one_gateway(ws: WebSocket, gw_id: str, gw_name: str,
                              gw_url: str, gw_token: str, kind: str,
                              payload: dict):
    """Stream from a Gateway via Adapter and relay chunks over WebSocket.

    Sends:
      {"type":"chat.chunk","gateway_id":"...","content":"..."}
      {"type":"chat.done","gateway_id":"...","full":"전체응답"}
    Returns (gw_id, gw_name, full_content, model, usage) or raises.
    """
    from adapters import create_adapter

    adapter = create_adapter(kind or "openclaw")
    messages = payload.get("messages", [])
    extra = {k: v for k, v in payload.items() if k not in ("messages", "stream")}

    full_content = ""
    model = ""
    usage = {}

    async for event in adapter._stream(gw_url.rstrip("/"), gw_token, {**payload, "stream": True}):
        if event["type"] == "chunk":
            full_content += event["content"]
            await ws.send_text(json.dumps({
                "type": "chat.chunk",
                "gateway_id": gw_id,
                "content": event["content"],
            }, ensure_ascii=False))
        elif event["type"] == "done":
            full_content = event["content"]
            model = event.get("model", "")
            usage = event.get("usage", {})

    await ws.send_text(json.dumps({
        "type": "chat.done",
        "gateway_id": gw_id,
        "full": full_content,
    }, ensure_ascii=False))

    return gw_id, gw_name, full_content, model, usage


def _save_chat_log(gw_id: str, gw_name: str, messages: list,
                   assistant_content: str, model: str, usage: dict):
    """Save user messages + assistant response to chat_logs."""
    try:
        db = get_db()
        try:
            for m in messages:
                db.execute(
                    "INSERT INTO chat_logs (id,gateway_id,gateway_name,role,content,created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (new_id(), gw_id, gw_name, m.get("role", "user"),
                     m.get("content", ""), now_ts()))
            db.execute(
                "INSERT INTO chat_logs (id,gateway_id,gateway_name,role,content,model,"
                "tokens_prompt,tokens_completion,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (new_id(), gw_id, gw_name, "assistant", assistant_content, model,
                 usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), now_ts()))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        log.warning("chat log save failed for %s: %s", gw_id, e)


@router.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    """Streaming chat relay: SSE → WebSocket.

    Client sends:
      Single:    {"messages":[...],"gateway_id":"xxx","stream":true}
      Broadcast: {"messages":[...],"broadcast":true,"stream":true}

    Server pushes:
      {"type":"chat.chunk","gateway_id":"xxx","content":"..."}
      {"type":"chat.done","gateway_id":"xxx","full":"전체응답"}
      {"type":"chat.error","gateway_id":"xxx","error":"..."}
    """
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await ws.send_text(json.dumps(
                    {"type": "chat.error", "gateway_id": "", "error": "invalid JSON"},
                    ensure_ascii=False))
                continue

            messages = msg.get("messages", [])
            gateway_id = msg.get("gateway_id")
            broadcast = msg.get("broadcast", False)

            if not messages:
                await ws.send_text(json.dumps(
                    {"type": "chat.error", "gateway_id": "", "error": "messages required"},
                    ensure_ascii=False))
                continue

            db = get_db()
            try:
                if gateway_id:
                    rows = db.execute(
                        "SELECT id, name, url, token, kind FROM gateways WHERE id=?",
                        (gateway_id,)).fetchall()
                    if not rows:
                        await ws.send_text(json.dumps(
                            {"type": "chat.error", "gateway_id": gateway_id,
                             "error": f"Gateway {gateway_id} not found"},
                            ensure_ascii=False))
                        continue
                elif broadcast:
                    rows = db.execute(
                        "SELECT id, name, url, token, kind FROM gateways").fetchall()
                    if not rows:
                        await ws.send_text(json.dumps(
                            {"type": "chat.error", "gateway_id": "",
                             "error": "No gateways registered"},
                            ensure_ascii=False))
                        continue
                else:
                    await ws.send_text(json.dumps(
                        {"type": "chat.error", "gateway_id": "",
                         "error": "gateway_id or broadcast required"},
                        ensure_ascii=False))
                    continue
            finally:
                db.close()

            payload = {k: v for k, v in msg.items()
                       if k not in ("gateway_id", "broadcast", "stream")}

            async def _relay(gw):
                gid, gname = gw["id"], gw["name"]
                kind = gw["kind"] if "kind" in gw.keys() else "openclaw"
                try:
                    result = await _stream_one_gateway(
                        ws, gid, gname, gw["url"], decrypt(gw["token"] or ""),
                        kind or "openclaw", payload)
                    _save_chat_log(gid, gname, messages,
                                   result[2], result[3], result[4])
                except httpx.HTTPStatusError as e:
                    log.warning("stream to %s failed: HTTP %d", gname, e.response.status_code)
                    await ws.send_text(json.dumps({
                        "type": "chat.error", "gateway_id": gid,
                        "error": f"HTTP {e.response.status_code}",
                    }, ensure_ascii=False))
                except Exception as e:
                    log.warning("stream to %s failed: %s", gname, e)
                    await ws.send_text(json.dumps({
                        "type": "chat.error", "gateway_id": gid,
                        "error": str(e),
                    }, ensure_ascii=False))

            await asyncio.gather(*[_relay(row) for row in rows])

    except WebSocketDisconnect:
        pass
