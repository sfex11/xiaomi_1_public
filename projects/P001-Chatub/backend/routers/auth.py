"""Auth routes: register, login, me, settings."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from auth import make_token, hash_password, get_current_user
from db import get_db, new_id, now_ts
from models import RegisterRequest, LoginRequest, SettingsUpdate

router = APIRouter(prefix="/api")


def json_ok(data=None, status=200):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=status)


def json_err(error, status=400):
    return JSONResponse({"ok": False, "error": error}, status_code=status)


@router.post("/auth/register")
def register(req: RegisterRequest):
    username = (req.username or "").strip()
    password = req.password or ""
    display_name = (req.display_name or username).strip()

    if not username or not password:
        return json_err("사용자명과 비밀번호를 입력하세요")

    db = get_db()
    try:
        existing = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            return json_err("이미 존재하는 사용자명")

        user_id = new_id()
        ts = now_ts()
        db.execute(
            "INSERT INTO users (id, username, password_hash, display_name, created_at) VALUES (?,?,?,?,?)",
            (user_id, username, hash_password(password), display_name, ts)
        )

        # Default project
        proj_id = new_id()
        db.execute(
            "INSERT INTO projects (id, user_id, name, description, color, created_at) VALUES (?,?,?,?,?,?)",
            (proj_id, user_id, "내 프로젝트", "", "#6366f1", ts)
        )

        # Default channel
        ch_id = new_id()
        db.execute(
            "INSERT INTO channels (id, project_id, name, icon, color, created_at) VALUES (?,?,?,?,?,?)",
            (ch_id, proj_id, "일반", "#", "#6366f1", ts)
        )

        # Default 3 bots
        bots = [
            ("PM-01", "Project Manager", "🧠"),
            ("Dev-01", "Developer", "💻"),
            ("UX-01", "UX Designer", "🎨"),
        ]
        for bname, brole, bavatar in bots:
            db.execute(
                "INSERT INTO ai_bots (id, user_id, project_id, name, role, avatar, system_prompt, is_active, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (new_id(), user_id, proj_id, bname, brole, bavatar, "", 1, ts)
            )

        # Default settings
        db.execute("INSERT INTO settings (user_id) VALUES (?)", (user_id,))

        db.commit()

        token = make_token(user_id)
        user = {"id": user_id, "username": username, "display_name": display_name, "avatar_color": "#6366f1"}
        return json_ok({"token": token, "user": user})
    finally:
        db.close()


@router.post("/auth/login")
def login(req: LoginRequest):
    username = (req.username or "").strip()
    password = req.password or ""

    db = get_db()
    try:
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not row or row["password_hash"] != hash_password(password):
            return json_err("사용자명 또는 비밀번호가 올바르지 않습니다")

        token = make_token(row["id"])
        user = {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "avatar_color": row["avatar_color"],
        }
        return json_ok({"token": token, "user": user})
    finally:
        db.close()


@router.get("/auth/me")
def me(user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        row = db.execute("SELECT id, username, display_name, avatar_color FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            return json_err("로그인이 필요합니다", 401)
        return json_ok({"user": dict(row)})
    finally:
        db.close()


@router.get("/settings")
def settings_get(user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM settings WHERE user_id=?", (user_id,)).fetchone()
        return json_ok(dict(row) if row else {})
    finally:
        db.close()


@router.put("/settings")
def settings_put(req: SettingsUpdate, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        data = req.model_dump(exclude_none=True)
        allowed = ['gateway_url', 'gateway_token', 'context_length', 'theme']
        sets = []
        vals = []
        for k in allowed:
            if k in data:
                sets.append(f"{k}=?")
                vals.append(data[k])
        if sets:
            vals.append(user_id)
            db.execute(f"UPDATE settings SET {', '.join(sets)} WHERE user_id=?", vals)
            db.commit()
        row = db.execute("SELECT * FROM settings WHERE user_id=?", (user_id,)).fetchone()
        return json_ok(dict(row) if row else {})
    finally:
        db.close()
