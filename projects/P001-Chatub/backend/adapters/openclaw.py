"""OpenClaw agent adapter — implements AgentAdapter for OpenClaw Gateway."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

import httpx

from adapters import (
    AgentAdapter,
    AgentResponse,
    HealthStatus,
    ProbeResult,
    register_adapter,
)

log = logging.getLogger("adapters.openclaw")

_TIMEOUT = httpx.Timeout(10, connect=5)
_STREAM_TIMEOUT = httpx.Timeout(120, connect=10)


def _headers(token: str) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@register_adapter("openclaw")
class OpenClawAdapter(AgentAdapter):
    """Adapter for the OpenClaw Gateway runtime."""

    kind = "openclaw"

    # ── probe ────────────────────────────────────────────────────────

    async def probe(self, url: str, token: str) -> ProbeResult:
        base = url.rstrip("/")
        caps: dict[str, bool] = {
            "chat": False,
            "streaming": False,
            "tools": False,
            "sessions": False,
        }
        agents: list[str] = []
        version: str | None = None

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                # 1) /v1/models — proves the runtime is alive
                r = await c.get(f"{base}/v1/models", headers=_headers(token))
                r.raise_for_status()
                data = r.json()
                models = data.get("data", []) if isinstance(data, dict) else []
                agents = [m.get("id", "") for m in models if isinstance(m, dict)]
                version = f"{len(agents)} models" if agents else "ok"
                caps["chat"] = True
                caps["streaming"] = True  # OpenClaw always supports SSE

                # 2) /tools/invoke sessions_list — optional feature
                try:
                    sr = await c.post(f"{base}/tools/invoke",
                                     json={"tool": "sessions_list", "action": "json", "args": {}},
                                     headers=_headers(token))
                    if sr.status_code < 400:
                        caps["sessions"] = True
                except Exception:
                    pass

                # 3) tools — heuristic: OpenClaw supports tools if /v1/models works
                caps["tools"] = True

        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            error = "AUTH_FAILED" if code in (401, 403) else f"HTTP {code}"
            return ProbeResult(reachable=False, kind=self.kind, error=error)
        except httpx.TimeoutException:
            return ProbeResult(reachable=False, kind=self.kind, error="TIMEOUT")
        except Exception as e:
            err = "NETWORK_ERROR" if "connect" in str(e).lower() else str(e)
            return ProbeResult(reachable=False, kind=self.kind, error=err)

        return ProbeResult(
            reachable=True,
            kind=self.kind,
            version=version,
            agents=agents,
            capabilities=caps,
        )

    # ── health ───────────────────────────────────────────────────────

    async def health(self, url: str, token: str) -> HealthStatus:
        base = url.rstrip("/")
        result = HealthStatus(online=False, state="error")

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(f"{base}/v1/models", headers=_headers(token))
                r.raise_for_status()
                data = r.json()
                result.online = True

                models = data.get("data", []) if isinstance(data, dict) else []
                if isinstance(models, list):
                    result.agents = [m.get("id", "") for m in models if isinstance(m, dict)]
                    result.version = f"{len(models)} models" if models else "ok"
                else:
                    result.version = "ok"

                # Classify state via /api/sessions
                result.state = await self._classify_state(c, base, token)
        except Exception as e:
            log.debug("health check failed for %s: %s", url, e)

        return result

    async def _classify_state(self, client: httpx.AsyncClient, base: str, token: str) -> str:
        try:
            payload = {"tool": "sessions_list", "action": "json", "args": {}}
            r = await client.post(f"{base}/tools/invoke", json=payload, headers=_headers(token))
            if r.status_code >= 400:
                return "idle"
            sessions = r.json()
        except Exception:
            return "idle"

        active: list = []
        if isinstance(sessions, list):
            active = sessions
        elif isinstance(sessions, dict):
            active = sessions.get("data", sessions.get("sessions", []))

        if not active:
            return "idle"

        for sess in active:
            if not isinstance(sess, dict):
                continue
            status = sess.get("status", "").lower()
            if "tool" in status:
                return "tool_calling"
            if status in ("generating", "speaking", "streaming"):
                return "speaking"
            if status in ("working", "processing", "running"):
                return "working"

        return "working"

    # ── send_message ─────────────────────────────────────────────────

    async def send_message(
        self,
        url: str,
        token: str,
        messages: list[dict],
        *,
        stream: bool = False,
        **kwargs,
    ) -> AgentResponse | AsyncIterator[dict]:
        base = url.rstrip("/")
        payload = {"messages": messages, **kwargs}

        if stream:
            payload["stream"] = True
            return self._stream(base, token, payload)

        # Non-streaming
        payload["stream"] = False
        async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as c:
            r = await c.post(
                f"{base}/v1/chat/completions",
                json=payload,
                headers=_headers(token),
            )
            r.raise_for_status()
            parsed = r.json()

        choices = parsed.get("choices", [])
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        usage = parsed.get("usage", {})
        return AgentResponse(
            content=content,
            model=parsed.get("model", ""),
            usage=usage,
            raw=parsed,
        )

    async def _stream(self, base: str, token: str, payload: dict) -> AsyncIterator[dict]:
        full_content = ""
        model = ""
        usage: dict = {}

        async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as c:
            async with c.stream(
                "POST",
                f"{base}/v1/chat/completions",
                json=payload,
                headers=_headers(token),
            ) as resp:
                resp.raise_for_status()
                buf = ""
                async for raw in resp.aiter_text():
                    buf += raw
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(data_str)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if not model:
                            model = chunk.get("model", "")
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                        if content:
                            full_content += content
                            yield {"type": "chunk", "content": content}

        yield {
            "type": "done",
            "content": full_content,
            "model": model,
            "usage": usage,
        }

    # ── list_models ──────────────────────────────────────────────────

    async def list_models(self, url: str, token: str) -> list[dict]:
        base = url.rstrip("/")
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.get(f"{base}/v1/models", headers=_headers(token))
            r.raise_for_status()
            data = r.json()
        if isinstance(data, dict):
            return data.get("data", [])
        return data if isinstance(data, list) else []

    # ── list_sessions ────────────────────────────────────────────────

    async def list_sessions(self, url: str, token: str) -> list[dict] | dict:
        """Fetch sessions: try GET /api/sessions first, fallback to POST /tools/invoke."""
        base = url.rstrip("/")

        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            # 1) Try GET /api/sessions (OpenClaw native endpoint)
            try:
                r = await c.get(f"{base}/api/sessions", headers=_headers(token))
                if r.status_code < 400:
                    data = r.json()
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict):
                        return data.get("sessions", data.get("data", data.get("result", [])))
            except Exception:
                pass

            # 2) Fallback: POST /tools/invoke sessions_list
            try:
                payload = {"tool": "sessions_list", "action": "json", "args": {}}
                r = await c.post(f"{base}/tools/invoke", json=payload, headers=_headers(token))
                if r.status_code < 400:
                    data = r.json()
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict):
                        return data.get("data", data.get("sessions", data.get("result", [])))
            except Exception:
                pass

        # 3) Both failed
        return {"sessions": [], "note": "sessions not available"}

    # ── get_session ─────────────────────────────────────────────

    async def get_session(self, url: str, token: str, session_key: str) -> dict:
        """Fetch a single session's messages by session key."""
        base = url.rstrip("/")

        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            # 1) Try GET /api/sessions/{session_key}
            try:
                r = await c.get(f"{base}/api/sessions/{session_key}", headers=_headers(token))
                if r.status_code < 400:
                    data = r.json()
                    if isinstance(data, dict):
                        return data
                    if isinstance(data, list):
                        return {"messages": data}
            except Exception:
                pass

            # 2) Fallback: POST /tools/invoke session_get
            try:
                payload = {"tool": "session_get", "action": "json", "args": {"session_id": session_key}}
                r = await c.post(f"{base}/tools/invoke", json=payload, headers=_headers(token))
                if r.status_code < 400:
                    data = r.json()
                    if isinstance(data, dict):
                        return data
                    if isinstance(data, list):
                        return {"messages": data}
            except Exception:
                pass

        return {"messages": [], "note": "session detail not available"}

    # ── list_agents ──────────────────────────────────────────────────

    async def list_agents(self, url: str, token: str) -> list[dict]:
        """Extract agent info from /api/sessions and health check data."""
        agents_map: dict[str, dict] = {}

        # Parallel fetch health + sessions (6.9s → 3s)
        hs_result, sessions = await asyncio.gather(
            self.health(url, token),
            self.list_sessions(url, token),
        )
        hs = hs_result
        for agent_id in (hs.agents or []):
            agents_map[agent_id] = {"id": agent_id, "source": "health"}
        session_list = sessions if isinstance(sessions, list) else []
        for sess in session_list:
            if not isinstance(sess, dict):
                continue
            # Try common fields for agent info
            agent_id = sess.get("agent_id") or sess.get("agent") or sess.get("model", "")
            if agent_id and agent_id not in agents_map:
                agents_map[agent_id] = {"id": agent_id, "source": "session"}
            # Enrich with session status
            if agent_id and agent_id in agents_map:
                agents_map[agent_id]["status"] = sess.get("status", "unknown")

        return list(agents_map.values())

    # ── list_files / get_file ──────────────────────────────────────

    GATEWAY_FILES = ["IDENTITY.md", "SOUL.md", "AGENTS.md", "TOOLS.md", "USER.md"]

    async def list_files(self, url: str, token: str) -> list[dict]:
        """Return list of known gateway config files with availability info.
        P1-2: All file checks run in parallel via asyncio.gather."""
        base = url.rstrip("/")

        async def _check_file(c: httpx.AsyncClient, fname: str) -> dict:
            try:
                r = await c.post(
                    f"{base}/tools/invoke",
                    json={"tool": "files_read", "action": "json", "args": {"path": fname}},
                    headers=_headers(token),
                )
                return {"name": fname, "exists": r.status_code < 400}
            except Exception:
                return {"name": fname, "exists": False}

        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            files = await asyncio.gather(*[_check_file(c, f) for f in self.GATEWAY_FILES])
        return list(files)

    async def get_file(self, url: str, token: str, filename: str) -> dict:
        """Read a single file's content from the gateway."""
        base = url.rstrip("/")
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(
                f"{base}/tools/invoke",
                json={"tool": "files_read", "action": "json", "args": {"path": filename}},
                headers=_headers(token),
            )
            if r.status_code >= 400:
                return {"name": filename, "content": None, "error": f"HTTP {r.status_code}"}
            data = r.json()
        content = data if isinstance(data, str) else data.get("content", data.get("result", str(data)))
        return {"name": filename, "content": content}

    async def save_file(self, url: str, token: str, filename: str, content: str) -> dict:
        """Write content to a file on the gateway via tools/invoke files_write."""
        base = url.rstrip("/")
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(
                f"{base}/tools/invoke",
                json={"tool": "files_write", "action": "json", "args": {"path": filename, "content": content}},
                headers=_headers(token),
            )
            if r.status_code >= 400:
                return {"ok": False, "error": f"HTTP {r.status_code}"}
            return {"ok": True, "name": filename}

    # ── get_capabilities ─────────────────────────────────────────────

    async def get_capabilities(self, url: str, token: str) -> dict[str, bool]:
        probe = await self.probe(url, token)
        return probe.capabilities

    # ── CP13: 4-level pairing status ────────────────────────────────

    async def get_pairing_status(self, url: str, token: str) -> str:
        """HTTP status code 기반 4단계 페어링 상태 분류.

        connected        — 2xx (health OK)
        pairing-required — 401/403 (토큰 없음 또는 인증 실패)
        error            — 5xx (서버 오류)
        disconnected     — 타임아웃/연결 불가
        """
        base = url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(f"{base}/v1/models", headers=_headers(token))
                if r.status_code < 300:
                    return "connected"
                if r.status_code in (401, 403):
                    return "pairing-required"
                if r.status_code >= 500:
                    return "error"
                return "error"
        except httpx.TimeoutException:
            return "disconnected"
        except Exception:
            return "disconnected"
