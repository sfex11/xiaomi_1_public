"""Projects, milestones, and team members CRUD."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from auth import get_current_user
from db import get_db, new_id, now_ts, rows_to_list, owns_project, build_update
from models import (
    ProjectCreate, ProjectUpdate,
    MilestoneCreate, MilestoneUpdate,
    MemberCreate, MemberUpdate,
)

router = APIRouter(prefix="/api")


def json_ok(data=None, status=200):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=status)


def json_err(error, status=400):
    return JSONResponse({"ok": False, "error": error}, status_code=status)


# -- Projects --

@router.get("/projects")
def list_projects(user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM projects WHERE user_id=? ORDER BY created_at", (user_id,)).fetchall()
        return json_ok(rows_to_list(rows))
    finally:
        db.close()


@router.post("/projects")
def create_project(req: ProjectCreate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        pid = new_id()
        ts = now_ts()
        db.execute(
            "INSERT INTO projects (id, user_id, name, description, color, created_at) VALUES (?,?,?,?,?,?)",
            (pid, user_id, req.name, req.description, req.color, ts)
        )
        db.commit()
        row = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.put("/projects/{rid}")
def update_project(rid: str, req: ProjectUpdate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        if not owns_project(db, user_id, rid):
            return json_err("찾을 수 없습니다", 404)
        data = req.model_dump(exclude_none=True)
        sets, vals = build_update(data, ['name', 'description', 'color'])
        if sets:
            vals.append(rid)
            db.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", vals)
            db.commit()
        row = db.execute("SELECT * FROM projects WHERE id=?", (rid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.delete("/projects/{rid}")
def delete_project(rid: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        if not owns_project(db, user_id, rid):
            return json_err("찾을 수 없습니다", 404)
        ch_ids = [r["id"] for r in db.execute("SELECT id FROM channels WHERE project_id=?", (rid,)).fetchall()]
        for cid in ch_ids:
            msg_ids = [r["id"] for r in db.execute("SELECT id FROM messages WHERE channel_id=?", (cid,)).fetchall()]
            for mid in msg_ids:
                db.execute("DELETE FROM threads WHERE message_id=?", (mid,))
            db.execute("DELETE FROM messages WHERE channel_id=?", (cid,))
        db.execute("DELETE FROM channels WHERE project_id=?", (rid,))
        db.execute("DELETE FROM tasks WHERE project_id=?", (rid,))
        db.execute("DELETE FROM milestones WHERE project_id=?", (rid,))
        db.execute("DELETE FROM team_members WHERE project_id=?", (rid,))
        db.execute("DELETE FROM ai_bots WHERE project_id=?", (rid,))
        db.execute("DELETE FROM projects WHERE id=?", (rid,))
        db.commit()
        return json_ok()
    finally:
        db.close()


# -- Milestones --

@router.get("/milestones")
def list_milestones(project_id: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        if not project_id or not owns_project(db, user_id, project_id):
            return json_err("찾을 수 없습니다", 404)
        rows = db.execute("SELECT * FROM milestones WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
        return json_ok(rows_to_list(rows))
    finally:
        db.close()


@router.post("/milestones")
def create_milestone(req: MilestoneCreate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        if not req.project_id or not owns_project(db, user_id, req.project_id):
            return json_err("찾을 수 없습니다", 404)
        mid = new_id()
        ts = now_ts()
        db.execute(
            "INSERT INTO milestones (id, project_id, name, deadline, color, created_at) VALUES (?,?,?,?,?,?)",
            (mid, req.project_id, req.name, req.deadline, req.color, ts)
        )
        db.commit()
        row = db.execute("SELECT * FROM milestones WHERE id=?", (mid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.put("/milestones/{rid}")
def update_milestone(rid: str, req: MilestoneUpdate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        ms = db.execute("SELECT * FROM milestones WHERE id=?", (rid,)).fetchone()
        if not ms or not owns_project(db, user_id, ms["project_id"]):
            return json_err("찾을 수 없습니다", 404)
        data = req.model_dump(exclude_none=True)
        sets, vals = build_update(data, ['name', 'deadline', 'color'])
        if sets:
            vals.append(rid)
            db.execute(f"UPDATE milestones SET {', '.join(sets)} WHERE id=?", vals)
            db.commit()
        row = db.execute("SELECT * FROM milestones WHERE id=?", (rid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.delete("/milestones/{rid}")
def delete_milestone(rid: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        ms = db.execute("SELECT * FROM milestones WHERE id=?", (rid,)).fetchone()
        if not ms or not owns_project(db, user_id, ms["project_id"]):
            return json_err("찾을 수 없습니다", 404)
        db.execute("DELETE FROM milestones WHERE id=?", (rid,))
        db.commit()
        return json_ok()
    finally:
        db.close()


# -- Team Members --

@router.get("/members")
def list_members(project_id: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        if not project_id or not owns_project(db, user_id, project_id):
            return json_err("찾을 수 없습니다", 404)
        rows = db.execute("SELECT * FROM team_members WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
        return json_ok(rows_to_list(rows))
    finally:
        db.close()


@router.post("/members")
def create_member(req: MemberCreate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        if not req.project_id or not owns_project(db, user_id, req.project_id):
            return json_err("찾을 수 없습니다", 404)
        mid = new_id()
        ts = now_ts()
        db.execute(
            "INSERT INTO team_members (id, project_id, name, role, avatar_color, created_at) VALUES (?,?,?,?,?,?)",
            (mid, req.project_id, req.name, req.role, req.avatar_color, ts)
        )
        db.commit()
        row = db.execute("SELECT * FROM team_members WHERE id=?", (mid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.put("/members/{rid}")
def update_member(rid: str, req: MemberUpdate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        mem = db.execute("SELECT * FROM team_members WHERE id=?", (rid,)).fetchone()
        if not mem or not owns_project(db, user_id, mem["project_id"]):
            return json_err("찾을 수 없습니다", 404)
        data = req.model_dump(exclude_none=True)
        sets, vals = build_update(data, ['name', 'role', 'avatar_color'])
        if sets:
            vals.append(rid)
            db.execute(f"UPDATE team_members SET {', '.join(sets)} WHERE id=?", vals)
            db.commit()
        row = db.execute("SELECT * FROM team_members WHERE id=?", (rid,)).fetchone()
        return json_ok(dict(row))
    finally:
        db.close()


@router.delete("/members/{rid}")
def delete_member(rid: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        mem = db.execute("SELECT * FROM team_members WHERE id=?", (rid,)).fetchone()
        if not mem or not owns_project(db, user_id, mem["project_id"]):
            return json_err("찾을 수 없습니다", 404)
        db.execute("DELETE FROM team_members WHERE id=?", (rid,))
        db.commit()
        return json_ok()
    finally:
        db.close()
