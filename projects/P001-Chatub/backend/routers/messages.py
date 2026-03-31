"""Messages CRUD."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from auth import get_current_user
from db import get_db, new_id, now_ts, rows_to_list, owns_project, project_for_channel
from models import MessageCreate, MessageUpdate

router = APIRouter(prefix="/api")


def json_ok(data=None, status=200):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=status)


def json_err(error, status=400):
    return JSONResponse({"ok": False, "error": error}, status_code=status)


@router.get("/messages")
def list_messages(
    channel_id: str,
    limit: int = Query(50),
    before: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user),
):
    if not channel_id:
        return json_err("channel_id 필요")
    db = get_db()
    try:
        proj_id = project_for_channel(db, channel_id)
        if not proj_id or not owns_project(db, user_id, proj_id):
            return json_err("찾을 수 없습니다", 404)
        if before:
            rows = db.execute(
                """SELECT m.*, COALESCE(u.display_name, b.name, '알 수 없음') as author_name
                   FROM messages m
                   LEFT JOIN users u ON m.user_id = u.id
                   LEFT JOIN ai_bots b ON m.bot_id = b.id
                   WHERE m.channel_id=? AND m.created_at<?
                   ORDER BY m.created_at DESC LIMIT ?""",
                (channel_id, int(before), limit)
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT m.*, COALESCE(u.display_name, b.name, '알 수 없음') as author_name
                   FROM messages m
                   LEFT JOIN users u ON m.user_id = u.id
                   LEFT JOIN ai_bots b ON m.bot_id = b.id
                   WHERE m.channel_id=?
                   ORDER BY m.created_at DESC LIMIT ?""",
                (channel_id, limit)
            ).fetchall()
        return json_ok(rows_to_list(rows))
    finally:
        db.close()


@router.post("/messages")
def create_message(req: MessageCreate, user_id: str = Depends(get_current_user)):
    if not req.channel_id:
        return json_err("channel_id 필요")
    db = get_db()
    try:
        proj_id = project_for_channel(db, req.channel_id)
        if not proj_id or not owns_project(db, user_id, proj_id):
            return json_err("찾을 수 없습니다", 404)
        mid = new_id()
        ts = now_ts()
        bot_id = req.bot_id
        db.execute(
            "INSERT INTO messages (id, channel_id, user_id, bot_id, text, image, reactions_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (mid, req.channel_id, user_id if not bot_id else None, bot_id, req.text, req.image, '{}', ts)
        )
        db.commit()
        row = db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.put("/messages/{rid}")
def update_message(rid: str, req: MessageUpdate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        msg = db.execute("SELECT * FROM messages WHERE id=?", (rid,)).fetchone()
        if not msg:
            return json_err("찾을 수 없습니다", 404)
        proj_id = project_for_channel(db, msg["channel_id"])
        if not proj_id or not owns_project(db, user_id, proj_id):
            return json_err("찾을 수 없습니다", 404)
        edited_at = now_ts()
        text = req.text if req.text is not None else msg['text']
        db.execute("UPDATE messages SET text=?, edited_at=? WHERE id=?", (text, edited_at, rid))
        db.commit()
        row = db.execute("SELECT * FROM messages WHERE id=?", (rid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.delete("/messages/{rid}")
def delete_message(rid: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        msg = db.execute("SELECT * FROM messages WHERE id=?", (rid,)).fetchone()
        if not msg:
            return json_err("찾을 수 없습니다", 404)
        proj_id = project_for_channel(db, msg["channel_id"])
        if not proj_id or not owns_project(db, user_id, proj_id):
            return json_err("찾을 수 없습니다", 404)
        db.execute("DELETE FROM threads WHERE message_id=?", (rid,))
        db.execute("DELETE FROM messages WHERE id=?", (rid,))
        db.commit()
        return json_ok()
    finally:
        db.close()
