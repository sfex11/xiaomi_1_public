"""Gateway registry router — register/monitor remote agent gateways.

CP6: All runtime-specific logic is delegated to AgentAdapter instances.
"""

import json
import asyncio
import logging
import time

from fastapi import APIRouter, Request
from db import get_db, new_id, now_ts, row_to_dict, rows_to_list
from crypto import encrypt, decrypt
from adapters import create_adapter, available_adapters, ProbeResult

router = APIRouter(prefix="/api/gateways", tags=["gateways"])
log = logging.getLogger("gateways")

# Agent states: idle, working, speaking, tool_calling, error
AGENT_STATES = ("idle", "working", "speaking", "tool_calling", "error")

# P1-1: Health check cache (25s TTL)
_health_cache: dict = {}  # {gateway_id: {"data": {...}, "ts": float}}
_HEALTH_CACHE_TTL = 25  # seconds — shorter than 30s polling interval


def _adapter_for(gw):
    """Return the correct adapter for a gateway row."""
    kind = gw["kind"] if "kind" in gw.keys() else "openclaw"
    return create_adapter(kind or "openclaw")


async def _health_check_async(gw):
    """Async health check via adapter. Returns legacy-compatible dict.
    Always populates _health_cache on success.
    CP13: includes pairing_status (connected/pairing-required/error/disconnected)."""
    adapter = _adapter_for(gw)
    url = gw["url"]
    token = decrypt(gw["token"] or "")
    hs = await adapter.health(url, token)

    # CP13: 4-level pairing status
    pairing_status = await adapter.get_pairing_status(url, token)

    result = {
        "online": hs.online,
        "version": hs.version,
        "agents": hs.agents,
        "state": hs.state,
        "pairing_status": pairing_status,
    }
    # P1-1: Store in cache
    _health_cache[gw["id"]] = {"data": result, "ts": time.monotonic()}
    return result


async def _health_cached(gw):
    """Return cached health if within TTL, otherwise do a live check."""
    gw_id = gw["id"]
    cached = _health_cache.get(gw_id)
    if cached and (time.monotonic() - cached["ts"]) < _HEALTH_CACHE_TTL:
        return cached["data"]
    return await _health_check_async(gw)


def _health_check(gw):
    """Sync wrapper for _health_check_async (used by ws.py health loop)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an async context — run in a new thread to avoid blocking
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(_health_check_async(gw))).result(timeout=15)
    else:
        return asyncio.run(_health_check_async(gw))


@router.post("/register")
async def register_gateway(request: Request):
    """Register a remote agent gateway for monitoring."""
    body = await request.body()
    data = json.loads(body)

    name = data.get("name", "").strip()
    url = data.get("url", "").strip()
    token = data.get("token", "").strip()
    port = data.get("port", 18789)
    kind = data.get("kind", "openclaw").strip()

    if not name or not url:
        return {"ok": False, "error": "name and url are required"}

    if port and ":" not in url.split("//")[-1]:
        url = f"{url.rstrip('/')}:{port}"

    db = get_db()
    try:
        existing = db.execute("SELECT id FROM gateways WHERE name=?", (name,)).fetchone()
        if existing:
            gid = existing["id"]
            db.execute(
                "UPDATE gateways SET url=?, token=?, kind=?, updated_at=? WHERE id=?",
                (url, encrypt(token), kind, now_ts(), gid)
            )
            log.info("Updated gateway: %s (%s) kind=%s", name, url, kind)
        else:
            gid = new_id()
            db.execute(
                "INSERT INTO gateways (id, name, url, token, kind, capabilities, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (gid, name, url, encrypt(token), kind, "{}", now_ts(), now_ts())
            )
            log.info("Registered gateway: %s (%s) kind=%s", name, url, kind)

        db.commit()

        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gid,)).fetchone()
        health = await _health_check_async(gw)

        return {"ok": True, "data": {"id": gid, "name": name, "url": url, "kind": kind, "health": health}}
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.post("/auto-detect")
async def auto_detect(request: Request):
    """Probe a URL, detect runtime kind + capabilities, return ProbeResult."""
    body = await request.body()
    data = json.loads(body)

    url = data.get("url", "").strip()
    token = data.get("token", "").strip()
    name = data.get("name", "").strip()

    if not url:
        return {"ok": False, "error": "url is required"}

    # Try each registered adapter until one succeeds
    for kind in available_adapters():
        adapter = create_adapter(kind)
        probe = await adapter.probe(url, token)
        encrypted_token = encrypt(token)

        # If name provided, auto-register after successful detection
        if name and probe.reachable:
            db = get_db()
            try:
                gid = new_id()
                cap_json = json.dumps(probe.capabilities or {})
                db.execute(
                    "INSERT INTO gateways (id,name,url,token,kind,capabilities,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (gid, name, url, encrypted_token, kind, cap_json, now_ts(), now_ts()),
                )
                db.commit()
                db.close()
                return json_ok({"detected": probe, "registered": True, "id": gid, "name": name})
            finally:
                db.close()

        return json_ok({"detected": probe, "encrypted_token": encrypted_token})
        if probe.reachable:
            return {
                "ok": True,
                "data": {
                    "kind": probe.kind,
                    "version": probe.version,
                    "agents": probe.agents,
                    "capabilities": probe.capabilities,
                    "error": None,
                },
            }

    # All adapters failed — return last probe result
    return {
        "ok": False,
        "error": probe.error or "UNSUPPORTED_API",
        "data": {
            "kind": "unknown",
            "capabilities": {},
            "error": probe.error or "UNSUPPORTED_API",
        },
    }


@router.get("/stats")
async def gateway_stats():
    """Aggregate daily/per-gateway token usage from chat_logs."""
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
        return {"ok": True, "data": [dict(r) for r in rows]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.get("/")
async def list_gateways():
    """List all registered gateways with health status and token stats."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, name, url, kind, capabilities, created_at, updated_at "
            "FROM gateways ORDER BY name"
        ).fetchall()

        # Fetch full rows for health checks
        full_rows = []
        for row in rows:
            full = db.execute("SELECT * FROM gateways WHERE id=?", (row["id"],)).fetchone()
            full_rows.append(full)

        # P1-1: Parallel health checks with cache (25s TTL) + 3s timeout
        async def _safe_health(gw):
            try:
                async with asyncio.timeout(3):
                    return await _health_cached(gw)
            except (asyncio.TimeoutError, Exception) as e:
                log.debug("health check timeout/error for %s: %s", gw["name"], e)
                return {"online": False, "version": None, "agents": [], "state": "error"}

        health_results = await asyncio.gather(*[_safe_health(fw) for fw in full_rows])

        gateways = []
        for row, health in zip(rows, health_results):
            gw = dict(row)
            gw["health"] = health

            # Parse capabilities JSON
            try:
                gw["capabilities"] = json.loads(gw.get("capabilities") or "{}")
            except (json.JSONDecodeError, TypeError):
                gw["capabilities"] = {}

            # Task 4: Auto-migrate empty capabilities from health check
            if health.get("online") and (not gw["capabilities"] or gw["capabilities"] == {}):
                adapter = _adapter_for(row)
                try:
                    probe = await adapter.probe(row["url"], decrypt(row["token"] or ""))
                    if probe.capabilities:
                        cap_json = json.dumps(probe.capabilities)
                        db.execute(
                            "UPDATE gateways SET capabilities=?, updated_at=? WHERE id=? AND (capabilities IS NULL OR capabilities='{}')",
                            (cap_json, now_ts(), row["id"])
                        )
                        db.commit()
                        gw["capabilities"] = probe.capabilities
                except Exception:
                    pass

            stats = db.execute(
                "SELECT SUM(tokens_prompt) AS prompt_tokens, "
                "SUM(tokens_completion) AS completion_tokens, "
                "COUNT(*) AS messages "
                "FROM chat_logs WHERE gateway_id=?",
                (row["id"],)
            ).fetchone()
            gw["stats"] = {
                "prompt_tokens": (stats["prompt_tokens"] or 0) if stats else 0,
                "completion_tokens": (stats["completion_tokens"] or 0) if stats else 0,
                "messages": (stats["messages"] or 0) if stats else 0,
            }
            gateways.append(gw)
        return {"ok": True, "data": gateways}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()



@router.post("/auto-detect")
async def auto_detect_gateway(request: Request):
    """Probe a gateway URL and detect runtime type + capabilities."""
    import asyncio
    body = await request.body()
    data = json.loads(body)

    name = data.get("name", "").strip()
    url = data.get("url", "").strip()
    token = data.get("token", "").strip()
    port = data.get("port", 18789)

    if not url:
        return {"ok": False, "error": "url is required", "error_code": "network_error"}

    # Build full URL
    if port and ":" not in url.split("//")[-1]:
        url = f"{url.rstrip('/')}:{port}"

    gw = {"url": url, "token": token, "name": name}

    capabilities = {"chat": False, "streaming": False, "tools": False, "sessions": False, "models": False}
    kind = "unknown"
    version = None
    models = []

    # 1. Try /v1/models (OpenAI-compatible)
    models_data = _query_gateway(gw, gw["token"], "/v1/models")
    if models_data is not None:
        capabilities["models"] = True
        capabilities["chat"] = True
        if isinstance(models_data, dict):
            models = models_data.get("data", [])
            if isinstance(models, list):
                capabilities["chat"] = True
                capabilities["streaming"] = True
                version = f"{len(models)} models"

    # 2. Try /api/sessions (OpenClaw-specific)
    sessions_data = _query_gateway(gw, gw["token"], "/api/sessions")
    if sessions_data is not None:
        capabilities["sessions"] = True
        capabilities["tools"] = True
        kind = "openclaw"
    elif models_data is not None:
        kind = "openai-compatible"

    # 3. Try streaming test
    if capabilities["chat"]:
        stream_url = f"{url.rstrip('/')}/v1/chat/completions"
        try:
            import urllib.request as ur
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            payload = json.dumps({
                "model": models[0]["id"] if models else "default",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 5,
                "stream": True
            }).encode()
            req = ur.Request(stream_url, data=payload, headers=headers, method="POST")
            resp = ur.urlopen(req, timeout=5)
            first_chunk = resp.read(200).decode()
            if "data:" in first_chunk:
                capabilities["streaming"] = True
        except Exception:
            pass

    # Determine final kind
    if kind == "unknown":
        if capabilities["chat"]:
            kind = "openai-compatible"
        else:
            return {"ok": False, "error": "지원되지 않는 엔드포인트", "error_code": "unsupported_api"}

    return {
        "ok": True,
        "data": {
            "kind": kind,
            "capabilities": capabilities,
            "version": version,
            "models": [{"id": m.get("id", ""), "name": m.get("id", "")} for m in models[:5]] if models else None
        }
    }


@router.delete("/{gateway_id}")
async def delete_gateway(gateway_id: str):
    """Remove a registered gateway."""
    db = get_db()
    try:
        row = db.execute("SELECT id FROM gateways WHERE id=?", (gateway_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "Gateway not found"}
        db.execute("DELETE FROM gateways WHERE id=?", (gateway_id,))
        db.commit()
        return {"ok": True, "data": {"deleted": gateway_id}}
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.post("/{gateway_id}/health")
async def check_health(gateway_id: str):
    """Force health check on a specific gateway."""
    db = get_db()
    try:
        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gateway_id,)).fetchone()
        if not gw:
            return {"ok": False, "error": "Gateway not found"}
        health = await _health_check_async(gw)
        return {"ok": True, "data": {"id": gateway_id, "name": gw["name"], "health": health}}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.get("/{gateway_id}/agents")
async def get_gateway_agents(gateway_id: str):
    """Get agents list from a specific gateway via adapter."""
    db = get_db()
    try:
        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gateway_id,)).fetchone()
        if not gw:
            return {"ok": False, "error": "Gateway not found"}

        adapter = _adapter_for(gw)
        if hasattr(adapter, 'list_agents'):
            agents = await adapter.list_agents(gw["url"], decrypt(gw["token"] or ""))
        else:
            agents = await adapter.list_models(gw["url"], decrypt(gw["token"] or ""))
        return {"ok": True, "data": {"agents": agents}}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.get("/{gateway_id}/sessions")
async def get_gateway_sessions(gateway_id: str):
    """Get sessions list from a specific gateway via adapter.
    P1-3: Reuse health cache to avoid redundant calls."""
    db = get_db()
    try:
        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gateway_id,)).fetchone()
        if not gw:
            return {"ok": False, "error": "Gateway not found"}

        # P1-3: If health cache has fresh data with state info, ensure gateway is online
        cached = _health_cache.get(gateway_id)
        if cached and (time.monotonic() - cached["ts"]) < _HEALTH_CACHE_TTL:
            if not cached["data"].get("online"):
                return {"ok": True, "data": {"note": "gateway offline (cached)", "status": "offline"}}

        adapter = _adapter_for(gw)
        sessions = await adapter.list_sessions(gw["url"], decrypt(gw["token"] or ""))
        if not sessions:
            return {"ok": True, "data": {"note": "sessions endpoint not available", "status": "online"}}
        return {"ok": True, "data": sessions}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.get("/{gateway_id}/sessions/{session_key}")
async def get_gateway_session(gateway_id: str, session_key: str):
    """Get a single session's messages from a specific gateway via adapter."""
    db = get_db()
    try:
        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gateway_id,)).fetchone()
        if not gw:
            return {"ok": False, "error": "Gateway not found"}

        adapter = _adapter_for(gw)
        if not hasattr(adapter, 'get_session'):
            return {"ok": False, "error": "Session detail not supported"}
        result = await adapter.get_session(gw["url"], decrypt(gw["token"] or ""), session_key)
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.get("/{gateway_id}/files")
async def get_gateway_files(gateway_id: str):
    """List available config files from a gateway."""
    db = get_db()
    try:
        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gateway_id,)).fetchone()
        if not gw:
            return {"ok": False, "error": "Gateway not found"}

        adapter = _adapter_for(gw)
        if not hasattr(adapter, 'list_files'):
            return {"ok": True, "data": []}
        files = await adapter.list_files(gw["url"], decrypt(gw["token"] or ""))
        return {"ok": True, "data": files}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.get("/{gateway_id}/files/{filename}")
async def get_gateway_file(gateway_id: str, filename: str):
    """Read a specific config file from a gateway."""
    db = get_db()
    try:
        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gateway_id,)).fetchone()
        if not gw:
            return {"ok": False, "error": "Gateway not found"}

        adapter = _adapter_for(gw)
        if not hasattr(adapter, 'get_file'):
            return {"ok": False, "error": "File access not supported"}
        result = await adapter.get_file(gw["url"], decrypt(gw["token"] or ""), filename)
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.put("/{gateway_id}/files/{filename}")
async def save_gateway_file(gateway_id: str, filename: str, request: Request):
    """Save content to a specific config file on a gateway."""
    body = await request.body()
    data = json.loads(body)
    content = data.get("content", "")

    db = get_db()
    try:
        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gateway_id,)).fetchone()
        if not gw:
            return {"ok": False, "error": "Gateway not found"}

        adapter = _adapter_for(gw)
        if not hasattr(adapter, 'save_file'):
            return {"ok": False, "error": "File write not supported for this gateway type"}
        result = await adapter.save_file(gw["url"], decrypt(gw["token"] or ""), filename, content)
        if result.get("ok"):
            return {"ok": True, "data": result}
        return {"ok": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.get("/{gateway_id}/history")
async def get_gateway_history(gateway_id: str, limit: int = 20):
    """Get chat history from a specific gateway."""
    db = get_db()
    try:
        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gateway_id,)).fetchone()
        if not gw:
            return {"ok": False, "error": "Gateway not found"}

        # History is not part of the adapter interface (OpenClaw-specific)
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                headers = {"Content-Type": "application/json"}
                raw_token = decrypt(gw["token"] or "")
                if raw_token:
                    headers["Authorization"] = f"Bearer {raw_token}"
                r = await c.get(f"{gw['url'].rstrip('/')}/api/history?limit={limit}", headers=headers)
                if r.status_code < 400:
                    return {"ok": True, "data": r.json()}
        except Exception:
            pass

        return {"ok": True, "data": {"note": "history endpoint not available"}}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.get("/chat-logs")
async def get_chat_logs(gateway_id: str = None, limit: int = 50):
    """Get chat logs from local DB, optionally filtered by gateway_id."""
    db = get_db()
    try:
        if gateway_id:
            rows = db.execute(
                "SELECT id, gateway_id, gateway_name, role, content, model, tokens_prompt, tokens_completion, created_at FROM chat_logs WHERE gateway_id=? ORDER BY created_at DESC LIMIT ?",
                (gateway_id, limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, gateway_id, gateway_name, role, content, model, tokens_prompt, tokens_completion, created_at FROM chat_logs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        logs = [dict(r) for r in rows]
        logs.reverse()
        return {"ok": True, "data": logs}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()
