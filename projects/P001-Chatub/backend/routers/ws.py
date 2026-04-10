"""WebSocket real-time chat + status monitoring for channels."""

import json
import asyncio
import logging
from typing import Dict, List, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from auth import verify_token
from db import get_db, owns_project, project_for_channel

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
        """Every 10 seconds, query all gateways and push status."""
        from routers.gateways import _health_check
        while self.clients:
            try:
                db = get_db()
                try:
                    rows = db.execute(
                        "SELECT id, name, url, token FROM gateways ORDER BY name"
                    ).fetchall()
                finally:
                    db.close()

                statuses = []
                for row in rows:
                    health = _health_check(row)
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
