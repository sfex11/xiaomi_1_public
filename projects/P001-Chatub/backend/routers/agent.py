"""Agent API — endpoints for AI agents/bots to interact with the chat system."""

import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from auth import get_current_agent, make_agent_token
from db import get_db, new_id, now_ts, rows_to_list, row_to_dict, project_for_channel
from models import AgentAuthRequest, AgentMessageCreate
from routers.ws import manager

router = APIRouter(prefix="/api/agents")


def json_ok(data=None, status=200):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=status)


def json_err(error, status=400):
    return JSONResponse({"ok": False, "error": error}, status_code=status)


@router.post("/auth")
def agent_auth(req: AgentAuthRequest):
    """Authenticate an agent with its api_key, return bot info + token."""
    db = get_db()
    try:
        bot = db.execute(
            "SELECT * FROM ai_bots WHERE api_key=? AND is_active=1",
            (req.api_key,)
        ).fetchone()
        if not bot:
            return json_err("Invalid API key or inactive bot", 401)
        token = make_agent_token(bot["id"])
        data = {
            "bot_id": bot["id"],
            "name": bot["name"],
            "role": bot["role"],
            "avatar": bot["avatar"],
            "project_id": bot["project_id"],
            "permissions": bot["permissions"] or "read,write",
            "token": token,
        }
        return json_ok(data)
    finally:
        db.close()


@router.post("/{bot_id}/messages")
def agent_send_message(bot_id: str, req: AgentMessageCreate, auth_bot_id: str = Depends(get_current_agent)):
    """Agent posts a message to a channel."""
    if auth_bot_id != bot_id:
        return json_err("Token does not match bot_id", 403)

    db = get_db()
    try:
        bot = db.execute("SELECT * FROM ai_bots WHERE id=? AND is_active=1", (bot_id,)).fetchone()
        if not bot:
            return json_err("Bot not found or inactive", 404)

        perms = (bot["permissions"] or "read,write").split(",")
        if "write" not in perms:
            return json_err("Bot lacks write permission", 403)

        proj_id = project_for_channel(db, req.channel_id)
        if not proj_id:
            return json_err("Channel not found", 404)

        # Bot must belong to the same project or have no project constraint
        if bot["project_id"] and bot["project_id"] != proj_id:
            return json_err("Bot does not have access to this channel's project", 403)

        mid = new_id()
        ts = now_ts()
        db.execute(
            "INSERT INTO messages (id, channel_id, user_id, bot_id, text, image, reactions_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (mid, req.channel_id, None, bot_id, req.content, "", "{}", ts)
        )

        # If parent_id provided, create a thread reply
        if req.parent_id:
            parent = db.execute("SELECT id FROM messages WHERE id=?", (req.parent_id,)).fetchone()
            if parent:
                tid = new_id()
                db.execute(
                    "INSERT INTO threads (id, message_id, user_id, bot_id, text, created_at) VALUES (?,?,?,?,?,?)",
                    (tid, req.parent_id, None, bot_id, req.content, ts)
                )

        db.commit()

        row = db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        msg_data = dict(row)
        asyncio.ensure_future(manager.broadcast(req.channel_id, "message_created", msg_data))
        return json_ok(msg_data)
    finally:
        db.close()


@router.get("/{bot_id}/channels")
def agent_list_channels(bot_id: str, auth_bot_id: str = Depends(get_current_agent)):
    """List channels this agent can access."""
    if auth_bot_id != bot_id:
        return json_err("Token does not match bot_id", 403)

    db = get_db()
    try:
        bot = db.execute("SELECT * FROM ai_bots WHERE id=? AND is_active=1", (bot_id,)).fetchone()
        if not bot:
            return json_err("Bot not found or inactive", 404)

        perms = (bot["permissions"] or "read,write").split(",")
        if "read" not in perms:
            return json_err("Bot lacks read permission", 403)

        if bot["project_id"]:
            rows = db.execute(
                "SELECT * FROM channels WHERE project_id=? ORDER BY created_at",
                (bot["project_id"],)
            ).fetchall()
        else:
            # Bot with no project constraint: list all channels owned by the bot's user
            rows = db.execute(
                """SELECT c.* FROM channels c
                   JOIN projects p ON c.project_id = p.id
                   WHERE p.user_id=?
                   ORDER BY c.created_at""",
                (bot["user_id"],)
            ).fetchall()

        return json_ok(rows_to_list(rows))
    finally:
        db.close()


@router.get("/{bot_id}/profile")
def agent_profile(bot_id: str, auth_bot_id: str = Depends(get_current_agent)):
    """Get agent profile info."""
    if auth_bot_id != bot_id:
        return json_err("Token does not match bot_id", 403)

    db = get_db()
    try:
        bot = db.execute("SELECT * FROM ai_bots WHERE id=? AND is_active=1", (bot_id,)).fetchone()
        if not bot:
            return json_err("Bot not found or inactive", 404)

        data = {
            "bot_id": bot["id"],
            "name": bot["name"],
            "role": bot["role"],
            "avatar": bot["avatar"],
            "project_id": bot["project_id"],
            "permissions": bot["permissions"] or "read,write",
            "is_active": bool(bot["is_active"]),
            "created_at": bot["created_at"],
        }
        return json_ok(data)
    finally:
        db.close()
