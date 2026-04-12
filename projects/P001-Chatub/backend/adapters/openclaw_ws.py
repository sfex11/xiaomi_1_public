"""OpenClaw WebSocket RPC adapter — Protocol v3.

Persistent WebSocket client with RPC request/response matching,
chat streaming via async generators, and automatic reconnection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncIterator

import websockets
from websockets.exceptions import ConnectionClosed

log = logging.getLogger("adapters.openclaw_ws")

PROTOCOL = 3
CLIENT_ID = "chatub"
CLIENT_MODE = "cli"
ROLE = "operator"
SCOPES = ["operator.read", "operator.write", "operator.admin"]


# ── Helpers ──────────────────────────────────────────────────────────────

def _to_ws_url(url: str) -> str:
    """Convert HTTP URL to WebSocket URL with /ws path."""
    if url.startswith("https://"):
        base = "wss://" + url[8:]
    elif url.startswith("http://"):
        base = "ws://" + url[7:]
    elif not url.startswith(("ws://", "wss://")):
        base = "ws://" + url
    else:
        base = url
    return base.rstrip("/") + "/ws"


# ── Pending RPC ──────────────────────────────────────────────────────────

class _PendingRPC:
    __slots__ = ("future", "timer")

    def __init__(self, future: asyncio.Future, timer: asyncio.TimerHandle):
        self.future = future
        self.timer = timer


# ── Main Class ───────────────────────────────────────────────────────────

class OpenClawWSAdapter:
    """WebSocket RPC client for OpenClaw Gateway Protocol v3."""

    def __init__(self) -> None:
        self._ws: Any = None
        self._url: str = ""
        self._token: str = ""
        self._closed: bool = True
        self._connected: asyncio.Event = asyncio.Event()
        self._status: str = "disconnected"

        # RPC
        self._pending: dict[str, _PendingRPC] = {}
        self._rpc_timeout: float = 60.0

        # Connect handshake
        self._connect_request_id: str | None = None
        self._connect_future: asyncio.Future | None = None

        # Chat streams
        self._chat_streams: dict[str, _ChatStream] = {}

        # Reconnection
        self._backoff: float = 1.0
        self._recv_task: asyncio.Task | None = None
        self._tick_interval: float = 30.0
        self._last_tick: float = 0.0
        self._tick_task: asyncio.Task | None = None

    @property
    def status(self) -> str:
        return self._status

    def is_connected(self) -> bool:
        return self._status == "connected"

    # ── Connect / Disconnect ─────────────────────────────────────────

    async def connect(self, url: str, token: str, timeout: float = 15.0) -> None:
        """Connect to gateway and authenticate with Bearer token."""
        self._url = url
        self._token = token
        self._closed = False
        self._connected.clear()
        self._status = "connecting"

        loop = asyncio.get_running_loop()
        self._connect_future = loop.create_future()

        await self._start()

        try:
            await asyncio.wait_for(self._connect_future, timeout=timeout)
        except asyncio.TimeoutError:
            await self.disconnect()
            raise TimeoutError(f"Connection to {url} timed out after {timeout}s")

    async def disconnect(self) -> None:
        """Gracefully close the connection."""
        self._closed = True
        self._status = "disconnected"
        self._connected.clear()

        if self._tick_task and not self._tick_task.done():
            self._tick_task.cancel()
            self._tick_task = None

        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            self._recv_task = None

        # Reject all pending RPCs
        for req_id, p in list(self._pending.items()):
            p.timer.cancel()
            if not p.future.done():
                p.future.set_exception(ConnectionError("Gateway disconnected"))
        self._pending.clear()

        # Reject all chat streams
        for key, stream in list(self._chat_streams.items()):
            stream.cancel(ConnectionError("Gateway disconnected"))
        self._chat_streams.clear()

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    # ── RPC ──────────────────────────────────────────────────────────

    async def rpc(self, method: str, params: dict | None = None) -> Any:
        """Send RPC request and wait for response. 60s timeout."""
        if not self.is_connected():
            raise ConnectionError("Gateway not connected")

        req_id = str(uuid.uuid4())
        frame = {"type": "req", "id": req_id, "method": method, "params": params or {}}
        await self._ws.send(json.dumps(frame))

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        def _on_timeout() -> None:
            p = self._pending.pop(req_id, None)
            if p and not p.future.done():
                p.future.set_exception(TimeoutError(f"RPC timeout: {method}"))

        timer = loop.call_later(self._rpc_timeout, _on_timeout)
        self._pending[req_id] = _PendingRPC(future, timer)
        return await future

    # ── Convenience RPC methods ──────────────────────────────────────

    async def sessions_list(self) -> list[dict]:
        res = await self.rpc("sessions.list")
        return res.get("sessions", []) if isinstance(res, dict) else []

    async def sessions_get(self, session_key: str, limit: int | None = None) -> dict:
        params: dict[str, Any] = {"key": session_key}
        if limit is not None:
            params["limit"] = limit
        res = await self.rpc("sessions.get", params)
        return res if isinstance(res, dict) else {}

    async def agents_list(self) -> list[dict]:
        res = await self.rpc("agents.list")
        return res.get("agents", []) if isinstance(res, dict) else []

    async def agents_files_list(self, agent_id: str) -> list[dict]:
        res = await self.rpc("agents.files.list", {"agentId": agent_id})
        return res.get("files", []) if isinstance(res, dict) else []

    async def agents_files_get(self, agent_id: str, path: str) -> dict:
        res = await self.rpc("agents.files.get", {"agentId": agent_id, "name": path})
        return res if isinstance(res, dict) else {}

    async def health(self) -> dict:
        return await self.rpc("health")

    # ── Chat Streaming ───────────────────────────────────────────────

    async def chat_send(
        self,
        agent_id: str,
        session_key: str,
        message: str,
    ) -> AsyncIterator[dict]:
        """Send chat message and yield streaming deltas.

        Yields dicts:
            {"type": "delta", "text": "..."}
            {"type": "done", "text": "full response text"}
            {"type": "error", "error": "..."}
        """
        if not self.is_connected():
            raise ConnectionError("Gateway not connected")

        full_key = session_key if session_key.startswith("agent:") else f"agent:{agent_id}:{session_key}"
        idempotency_key = str(uuid.uuid4())

        req_id = str(uuid.uuid4())
        frame = {
            "type": "req", "id": req_id, "method": "chat.send",
            "params": {"sessionKey": full_key, "message": message, "idempotencyKey": idempotency_key},
        }
        await self._ws.send(json.dumps(frame))

        stream = _ChatStream(req_id, full_key)
        self._chat_streams[full_key] = stream

        try:
            async for event in stream:
                yield event
        finally:
            self._chat_streams.pop(full_key, None)

    # ── Internal: WebSocket lifecycle ────────────────────────────────

    async def _start(self) -> None:
        if self._closed:
            return
        try:
            ws_url = _to_ws_url(self._url)
            self._ws = await websockets.connect(
                ws_url,
                additional_headers={"Origin": "http://localhost:18789"},
                ping_interval=None,
            )
        except Exception as e:
            log.debug("WS connect failed: %s", e)
            if not self._closed:
                asyncio.get_running_loop().call_later(
                    self._backoff, lambda: asyncio.ensure_future(self._reconnect())
                )
            return

        # Start receive loop
        self._recv_task = asyncio.create_task(self._recv_loop())

        # Send connect handshake after brief delay (matches TS 750ms)
        await asyncio.sleep(0.3)
        await self._send_connect()

    async def _send_connect(self) -> None:
        if not self._ws:
            return
        req_id = str(uuid.uuid4())
        self._connect_request_id = req_id

        frame = {
            "type": "req", "id": req_id, "method": "connect",
            "params": {
                "minProtocol": PROTOCOL,
                "maxProtocol": PROTOCOL,
                "client": {"id": CLIENT_ID, "version": "1.0.0", "platform": "python", "mode": CLIENT_MODE},
                "role": ROLE,
                "scopes": SCOPES,
                "auth": {"token": self._token} if self._token else None,
            },
        }
        try:
            await self._ws.send(json.dumps(frame))
        except Exception as e:
            log.debug("Failed to send connect frame: %s", e)

    async def _recv_loop(self) -> None:
        try:
            async for raw in self._ws:
                self._handle_message(raw)
        except ConnectionClosed:
            pass
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.debug("recv error: %s", e)

        self._ws = None
        if not self._closed:
            self._status = "connecting"
            await self._reconnect()

    def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return

        msg_type = msg.get("type")

        # ── Events ───────────────────────────────────────────────
        if msg_type == "event":
            event = msg.get("event")

            if event == "tick":
                self._last_tick = asyncio.get_event_loop().time()
                return

            # Chat streaming: agent delta
            if event == "agent":
                payload = msg.get("payload", {})
                key = payload.get("sessionKey")
                stream = self._chat_streams.get(key) if key else None
                if stream and payload.get("stream") == "assistant":
                    data = payload.get("data", {})
                    delta = data.get("delta")
                    if delta:
                        stream.push_delta(delta)
                return

            # Chat final/error
            if event == "chat":
                payload = msg.get("payload", {})
                key = payload.get("sessionKey")
                stream = self._chat_streams.get(key) if key else None
                if not stream:
                    return
                state = payload.get("state")
                if state == "final":
                    text = stream.full_text
                    if not text and payload.get("message"):
                        content = payload["message"].get("content", [])
                        if isinstance(content, list):
                            text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
                    stream.push_done(text)
                elif state == "error":
                    error_msg = payload.get("error") or payload.get("errorMessage") or "Chat error"
                    stream.push_error(str(error_msg))
                return

            return

        # ── Responses ────────────────────────────────────────────
        if msg_type == "res":
            msg_id = msg.get("id")

            # Connect response
            if msg_id == self._connect_request_id:
                self._connect_request_id = None
                if msg.get("ok"):
                    self._backoff = 1.0
                    payload = msg.get("payload", {})
                    policy = payload.get("policy", {})
                    self._tick_interval = policy.get("tickIntervalMs", 30000) / 1000.0
                    self._last_tick = asyncio.get_event_loop().time()
                    self._start_tick_watch()
                    self._status = "connected"
                    self._connected.set()
                    if self._connect_future and not self._connect_future.done():
                        self._connect_future.set_result(None)
                    log.info("Connected to %s", self._url)
                else:
                    error = msg.get("error", "Connect failed")
                    if self._connect_future and not self._connect_future.done():
                        self._connect_future.set_exception(ConnectionError(str(error)))
                return

            # RPC response
            pending = self._pending.pop(msg_id, None) if msg_id else None
            if pending:
                pending.timer.cancel()
                if not pending.future.done():
                    if msg.get("ok"):
                        pending.future.set_result(msg.get("payload", {}))
                    else:
                        err = msg.get("error", {})
                        err_msg = err.get("error", str(err)) if isinstance(err, dict) else str(err)
                        pending.future.set_exception(RuntimeError(f"RPC error: {err_msg}"))

    # ── Reconnection ─────────────────────────────────────────────────

    async def _reconnect(self) -> None:
        if self._closed:
            return
        import random
        delay = self._backoff + random.random() * 0.5
        self._backoff = min(self._backoff * 2, 30.0)
        log.info("Reconnecting in %.1fs…", delay)
        await asyncio.sleep(delay)
        if not self._closed:
            await self._start()

    # ── Tick watchdog ────────────────────────────────────────────────

    def _start_tick_watch(self) -> None:
        if self._tick_task and not self._tick_task.done():
            self._tick_task.cancel()
        self._tick_task = asyncio.create_task(self._tick_watchdog())

    async def _tick_watchdog(self) -> None:
        interval = max(self._tick_interval, 1.0)
        try:
            while not self._closed and self.is_connected():
                await asyncio.sleep(interval)
                if self._last_tick and (asyncio.get_event_loop().time() - self._last_tick > interval * 2):
                    log.warning("Tick timeout — closing connection")
                    if self._ws:
                        await self._ws.close(4000, "tick timeout")
                    break
        except asyncio.CancelledError:
            pass


# ── Chat Stream (internal) ───────────────────────────────────────────────

class _ChatStream:
    """Internal async iterator for chat streaming events."""

    def __init__(self, request_id: str, session_key: str) -> None:
        self.request_id = request_id
        self.session_key = session_key
        self.full_text = ""
        self._queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._done = False

    def push_delta(self, delta: str) -> None:
        self.full_text += delta
        self._queue.put_nowait({"type": "delta", "text": delta})

    def push_done(self, text: str) -> None:
        if not self._done:
            self._done = True
            self._queue.put_nowait({"type": "done", "text": text or self.full_text})
            self._queue.put_nowait(None)  # sentinel

    def push_error(self, error: str) -> None:
        if not self._done:
            self._done = True
            self._queue.put_nowait({"type": "error", "error": error})
            self._queue.put_nowait(None)

    def cancel(self, exc: Exception) -> None:
        if not self._done:
            self._done = True
            self._queue.put_nowait({"type": "error", "error": str(exc)})
            self._queue.put_nowait(None)

    def __aiter__(self):
        return self

    async def __anext__(self) -> dict:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item
