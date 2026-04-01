"""WebSocket real-time chat for channels."""

import json
from typing import Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from auth import verify_token
from db import get_db, owns_project, project_for_channel

router = APIRouter()


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
