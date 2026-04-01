"""AI Bots CRUD."""

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from auth import get_current_user
from db import get_db, new_id, now_ts, rows_to_list, owns_project, build_update
from models import BotCreate, BotUpdate

router = APIRouter(prefix="/api")


def json_ok(data=None, status=200):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=status)


def json_err(error, status=400):
    return JSONResponse({"ok": False, "error": error}, status_code=status)


@router.get("/bots")
def list_bots(
    project_id: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user),
):
    db = get_db()
    try:
        if project_id:
            if not owns_project(db, user_id, project_id):
                return json_err("찾을 수 없습니다", 404)
            rows = db.execute(
                "SELECT * FROM ai_bots WHERE user_id=? AND (project_id=? OR project_id IS NULL) ORDER BY created_at",
                (user_id, project_id)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM ai_bots WHERE user_id=? ORDER BY created_at",
                (user_id,)
            ).fetchall()
        return json_ok(rows_to_list(rows))
    finally:
        db.close()


@router.post("/bots")
def create_bot(req: BotCreate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        if req.project_id and not owns_project(db, user_id, req.project_id):
            return json_err("찾을 수 없습니다", 404)
        bid = new_id()
        ts = now_ts()
        api_key = "agent_" + secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO ai_bots (id, user_id, project_id, name, role, avatar, system_prompt, is_active, api_key, permissions, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (bid, user_id, req.project_id, req.name, req.role,
             req.avatar, req.system_prompt,
             1 if req.is_active else 0, api_key, "read,write", ts)
        )
        db.commit()
        row = db.execute("SELECT * FROM ai_bots WHERE id=?", (bid,)).fetchone()
        data = dict(row)
        data["api_key"] = api_key
        return json_ok(data)
    finally:
        db.close()


@router.put("/bots/{rid}")
def update_bot(rid: str, req: BotUpdate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        bot = db.execute("SELECT * FROM ai_bots WHERE id=? AND user_id=?", (rid, user_id)).fetchone()
        if not bot:
            return json_err("찾을 수 없습니다", 404)
        data = req.model_dump(exclude_none=True)
        sets, vals = build_update(data, ['name', 'role', 'avatar', 'system_prompt', 'is_active', 'project_id'])
        if sets:
            vals.append(rid)
            db.execute(f"UPDATE ai_bots SET {', '.join(sets)} WHERE id=?", vals)
            db.commit()
        row = db.execute("SELECT * FROM ai_bots WHERE id=?", (rid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.post("/bots/{rid}/regenerate-key")
def regenerate_bot_key(rid: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        bot = db.execute("SELECT * FROM ai_bots WHERE id=? AND user_id=?", (rid, user_id)).fetchone()
        if not bot:
            return json_err("찾을 수 없습니다", 404)
        new_key = "agent_" + secrets.token_urlsafe(32)
        db.execute("UPDATE ai_bots SET api_key=? WHERE id=?", (new_key, rid))
        db.commit()
        return json_ok({"api_key": new_key})
    finally:
        db.close()


@router.delete("/bots/{rid}")
def delete_bot(rid: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        bot = db.execute("SELECT * FROM ai_bots WHERE id=? AND user_id=?", (rid, user_id)).fetchone()
        if not bot:
            return json_err("찾을 수 없습니다", 404)
        db.execute("DELETE FROM ai_bots WHERE id=?", (rid,))
        db.commit()
        return json_ok()
    finally:
        db.close()
