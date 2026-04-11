"""Gateway registry router — register/monitor remote OpenClaw Gateways."""

import json
import urllib.request
import urllib.error
import logging

from fastapi import APIRouter, Request
from db import get_db, new_id, now_ts, row_to_dict, rows_to_list

router = APIRouter(prefix="/api/gateways", tags=["gateways"])
log = logging.getLogger("gateways")

# Agent states: idle, working, speaking, tool_calling, error
AGENT_STATES = ("idle", "working", "speaking", "tool_calling", "error")


def _query_gateway(gw_url, gw_token, path="/"):
    """Call an OpenClaw Gateway API endpoint. Returns parsed JSON or None."""
    url = f"{gw_url.rstrip('/')}{path}"
    headers = {"Content-Type": "application/json"}
    if gw_token:
        headers["Authorization"] = f"Bearer {gw_token}"
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        resp = urllib.request.urlopen(req, timeout=3)
        return json.loads(resp.read())
    except Exception as e:
        log.warning("Gateway query failed: %s %s → %s", gw_url, path, e)
        return None


def _classify_agent_state(gw_url, gw_token, online):
    """Classify agent state into one of 5 states based on gateway activity."""
    if not online:
        return "error"

    # Try /api/sessions to detect active work
    sessions = _query_gateway(gw_url, gw_token, "/api/sessions")
    if sessions is None:
        return "idle"

    # Check session list for activity indicators
    active_sessions = []
    if isinstance(sessions, list):
        active_sessions = sessions
    elif isinstance(sessions, dict):
        active_sessions = sessions.get("data", sessions.get("sessions", []))

    if not active_sessions:
        return "idle"

    for sess in active_sessions:
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


def _health_check(gw):
    """Check if a gateway is reachable. Returns status dict with agent state."""
    gw_url = gw["url"]
    gw_token = gw["token"]
    result = {"online": False, "version": None, "agents": None, "state": "error"}

    # Try /v1/models as a lightweight health check
    data = _query_gateway(gw_url, gw_token, "/v1/models")
    if data is not None:
        result["online"] = True
        if isinstance(data, dict):
            result["version"] = data.get("object", "ok")

    result["state"] = _classify_agent_state(gw_url, gw_token, result["online"])
    return result


@router.post("/register")
async def register_gateway(request: Request):
    """Register a remote OpenClaw Gateway for monitoring."""
    body = await request.body()
    data = json.loads(body)

    name = data.get("name", "").strip()
    url = data.get("url", "").strip()
    token = data.get("token", "").strip()
    port = data.get("port", 18789)

    if not name or not url:
        return {"ok": False, "error": "name and url are required"}

    # Build full URL if port specified
    if port and ":" not in url.split("//")[-1]:
        url = f"{url.rstrip('/')}:{port}"

    db = get_db()
    try:
        # Check if already registered by name
        existing = db.execute("SELECT id FROM gateways WHERE name=?", (name,)).fetchone()
        if existing:
            gid = existing["id"]
            db.execute(
                "UPDATE gateways SET url=?, token=?, updated_at=? WHERE id=?",
                (url, token, now_ts(), gid)
            )
            log.info("Updated gateway: %s (%s)", name, url)
        else:
            gid = new_id()
            db.execute(
                "INSERT INTO gateways (id, name, url, token, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (gid, name, url, token, now_ts(), now_ts())
            )
            log.info("Registered gateway: %s (%s)", name, url)

        db.commit()

        # Run health check
        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gid,)).fetchone()
        health = _health_check(gw)

        return {"ok": True, "data": {"id": gid, "name": name, "url": url, "health": health}}
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


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
        rows = db.execute("SELECT id, name, url, created_at, updated_at FROM gateways ORDER BY name").fetchall()
        gateways = []
        for row in rows:
            gw = dict(row)
            # Get full record for health check (includes token)
            full = db.execute("SELECT * FROM gateways WHERE id=?", (row["id"],)).fetchone()
            health = _health_check(full)
            gw["health"] = health
            # Token usage stats for this gateway
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
        health = _health_check(gw)
        return {"ok": True, "data": {"id": gateway_id, "name": gw["name"], "health": health}}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.get("/{gateway_id}/agents")
async def get_gateway_agents(gateway_id: str):
    """Get agents list from a specific gateway."""
    db = get_db()
    try:
        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gateway_id,)).fetchone()
        if not gw:
            return {"ok": False, "error": "Gateway not found"}

        data = _query_gateway(gw["url"], gw["token"], "/v1/models")
        if data is None:
            return {"ok": False, "error": "Gateway unreachable"}

        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.get("/{gateway_id}/sessions")
async def get_gateway_sessions(gateway_id: str):
    """Get sessions list from a specific gateway."""
    db = get_db()
    try:
        gw = db.execute("SELECT * FROM gateways WHERE id=?", (gateway_id,)).fetchone()
        if not gw:
            return {"ok": False, "error": "Gateway not found"}

        data = _query_gateway(gw["url"], gw["token"], "/api/sessions")
        if data is None:
            data = _query_gateway(gw["url"], gw["token"], "/v1/models")
            if data is None:
                return {"ok": False, "error": "Gateway unreachable"}
            return {"ok": True, "data": {"note": "sessions endpoint not available", "status": "online"}}

        return {"ok": True, "data": data}
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

        data = _query_gateway(gw["url"], gw["token"], "/api/history?limit=" + str(limit))
        if data is not None:
            return {"ok": True, "data": data}

        data = _query_gateway(gw["url"], gw["token"], "/v1/models")
        if data is None:
            return {"ok": False, "error": "Gateway unreachable"}

        return {"ok": True, "data": {"note": "history endpoint not available", "models": data}}
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
