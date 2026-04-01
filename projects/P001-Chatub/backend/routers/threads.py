"""Threads CRUD."""

import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from auth import get_current_user
from db import get_db, new_id, now_ts, rows_to_list, owns_project, project_for_message
from models import ThreadCreate
from routers.ws import manager

router = APIRouter(prefix="/api")


def json_ok(data=None, status=200):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=status)


def json_err(error, status=400):
    return JSONResponse({"ok": False, "error": error}, status_code=status)


@router.get("/threads")
def list_threads(message_id: str, user_id: str = Depends(get_current_user)):
    if not message_id:
        return json_err("message_id 필요")
    db = get_db()
    try:
        proj_id = project_for_message(db, message_id)
        if not proj_id or not owns_project(db, user_id, proj_id):
            return json_err("찾을 수 없습니다", 404)
        rows = db.execute(
            """SELECT t.*, COALESCE(u.display_name, b.name, '알 수 없음') as author_name
               FROM threads t
               LEFT JOIN users u ON t.user_id = u.id
               LEFT JOIN ai_bots b ON t.bot_id = b.id
               WHERE t.message_id=? ORDER BY t.created_at""",
            (message_id,)
        ).fetchall()
        return json_ok(rows_to_list(rows))
    finally:
        db.close()


@router.post("/threads")
def create_thread(req: ThreadCreate, user_id: str = Depends(get_current_user)):
    if not req.message_id:
        return json_err("message_id 필요")
    db = get_db()
    try:
        proj_id = project_for_message(db, req.message_id)
        if not proj_id or not owns_project(db, user_id, proj_id):
            return json_err("찾을 수 없습니다", 404)
        tid = new_id()
        ts = now_ts()
        bot_id = req.bot_id
        db.execute(
            "INSERT INTO threads (id, message_id, user_id, bot_id, text, created_at) VALUES (?,?,?,?,?,?)",
            (tid, req.message_id, user_id if not bot_id else None, bot_id, req.text, ts)
        )
        db.commit()
        row = db.execute("SELECT * FROM threads WHERE id=?", (tid,)).fetchone()
        thread_data = dict(row)
        # Find channel_id from the parent message for broadcasting
        parent = db.execute("SELECT channel_id FROM messages WHERE id=?", (req.message_id,)).fetchone()
        if parent:
            asyncio.ensure_future(manager.broadcast(parent["channel_id"], "thread_created", thread_data))
        return json_ok(thread_data)
    finally:
        db.close()
