"""Tasks CRUD."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from auth import get_current_user
from db import get_db, new_id, now_ts, rows_to_list, owns_project, build_update
from models import TaskCreate, TaskUpdate

router = APIRouter(prefix="/api")


def json_ok(data=None, status=200):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=status)


def json_err(error, status=400):
    return JSONResponse({"ok": False, "error": error}, status_code=status)


@router.get("/tasks")
def list_tasks(
    project_id: str,
    status: Optional[str] = Query(None),
    milestone_id: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user),
):
    db = get_db()
    try:
        if not project_id or not owns_project(db, user_id, project_id):
            return json_err("찾을 수 없습니다", 404)
        sql = "SELECT * FROM tasks WHERE project_id=?"
        params = [project_id]
        if status:
            sql += " AND status=?"
            params.append(status)
        if milestone_id:
            sql += " AND milestone_id=?"
            params.append(milestone_id)
        sql += " ORDER BY created_at"
        rows = db.execute(sql, params).fetchall()
        return json_ok(rows_to_list(rows))
    finally:
        db.close()


@router.post("/tasks")
def create_task(req: TaskCreate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        if not req.project_id or not owns_project(db, user_id, req.project_id):
            return json_err("찾을 수 없습니다", 404)
        tid = new_id()
        ts = now_ts()
        db.execute(
            "INSERT INTO tasks (id, project_id, channel_id, status, title, description, milestone_id, deadline, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (tid, req.project_id, req.channel_id, req.status,
             req.title, req.description, req.milestone_id, req.deadline, ts)
        )
        db.commit()
        row = db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.put("/tasks/{rid}")
def update_task(rid: str, req: TaskUpdate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        task = db.execute("SELECT * FROM tasks WHERE id=?", (rid,)).fetchone()
        if not task or not owns_project(db, user_id, task["project_id"]):
            return json_err("찾을 수 없습니다", 404)
        data = req.model_dump(exclude_none=True)
        sets, vals = build_update(data, ['status', 'title', 'description', 'milestone_id', 'deadline', 'channel_id'])
        if sets:
            vals.append(rid)
            db.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", vals)
            db.commit()
        row = db.execute("SELECT * FROM tasks WHERE id=?", (rid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.delete("/tasks/{rid}")
def delete_task(rid: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        task = db.execute("SELECT * FROM tasks WHERE id=?", (rid,)).fetchone()
        if not task or not owns_project(db, user_id, task["project_id"]):
            return json_err("찾을 수 없습니다", 404)
        db.execute("DELETE FROM tasks WHERE id=?", (rid,))
        db.commit()
        return json_ok()
    finally:
        db.close()
