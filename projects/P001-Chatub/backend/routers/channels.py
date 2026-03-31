"""Channels CRUD."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from auth import get_current_user
from db import get_db, new_id, now_ts, rows_to_list, owns_project, build_update
from models import ChannelCreate, ChannelUpdate

router = APIRouter(prefix="/api")


def json_ok(data=None, status=200):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=status)


def json_err(error, status=400):
    return JSONResponse({"ok": False, "error": error}, status_code=status)


@router.get("/channels")
def list_channels(project_id: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        if not project_id or not owns_project(db, user_id, project_id):
            return json_err("찾을 수 없습니다", 404)
        rows = db.execute("SELECT * FROM channels WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
        return json_ok(rows_to_list(rows))
    finally:
        db.close()


@router.post("/channels")
def create_channel(req: ChannelCreate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        if not req.project_id or not owns_project(db, user_id, req.project_id):
            return json_err("찾을 수 없습니다", 404)
        cid = new_id()
        ts = now_ts()
        db.execute(
            "INSERT INTO channels (id, project_id, name, icon, color, created_at) VALUES (?,?,?,?,?,?)",
            (cid, req.project_id, req.name, req.icon, req.color, ts)
        )
        db.commit()
        row = db.execute("SELECT * FROM channels WHERE id=?", (cid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.put("/channels/{rid}")
def update_channel(rid: str, req: ChannelUpdate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        ch = db.execute("SELECT * FROM channels WHERE id=?", (rid,)).fetchone()
        if not ch or not owns_project(db, user_id, ch["project_id"]):
            return json_err("찾을 수 없습니다", 404)
        data = req.model_dump(exclude_none=True)
        sets, vals = build_update(data, ['name', 'icon', 'color'])
        if sets:
            vals.append(rid)
            db.execute(f"UPDATE channels SET {', '.join(sets)} WHERE id=?", vals)
            db.commit()
        row = db.execute("SELECT * FROM channels WHERE id=?", (rid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.delete("/channels/{rid}")
def delete_channel(rid: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        ch = db.execute("SELECT * FROM channels WHERE id=?", (rid,)).fetchone()
        if not ch or not owns_project(db, user_id, ch["project_id"]):
            return json_err("찾을 수 없습니다", 404)
        msg_ids = [r["id"] for r in db.execute("SELECT id FROM messages WHERE channel_id=?", (rid,)).fetchall()]
        for mid in msg_ids:
            db.execute("DELETE FROM threads WHERE message_id=?", (mid,))
        db.execute("DELETE FROM messages WHERE channel_id=?", (rid,))
        db.execute("DELETE FROM channels WHERE id=?", (rid,))
        db.commit()
        return json_ok()
    finally:
        db.close()
