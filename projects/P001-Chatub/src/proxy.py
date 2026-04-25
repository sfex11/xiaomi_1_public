#!/usr/bin/env python3
"""Chatub Backend - SQLite + Auth + CRUD APIs + Gateway SSE Proxy"""

import http.server
import json
import socketserver
import urllib.request
import urllib.error
import urllib.parse
import sys
import os
import sqlite3
import hashlib
import hmac
import uuid
import base64
import time
import mimetypes

PORT = 8083
DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DIR, 'chatub.db')
SECRET = os.urandom(32).hex()
TOKEN_EXPIRY = 604800  # 7 days


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        display_name TEXT NOT NULL,
        avatar_color TEXT DEFAULT '#6366f1',
        created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        color TEXT DEFAULT '#6366f1',
        created_at INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS channels (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        name TEXT NOT NULL,
        icon TEXT DEFAULT '#',
        color TEXT DEFAULT '#6366f1',
        created_at INTEGER NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        channel_id TEXT NOT NULL,
        user_id TEXT,
        bot_id TEXT,
        text TEXT DEFAULT '',
        image TEXT DEFAULT '',
        reactions_json TEXT DEFAULT '{}',
        created_at INTEGER NOT NULL,
        edited_at INTEGER,
        FOREIGN KEY (channel_id) REFERENCES channels(id)
    );
    CREATE TABLE IF NOT EXISTS threads (
        id TEXT PRIMARY KEY,
        message_id TEXT NOT NULL,
        user_id TEXT,
        bot_id TEXT,
        text TEXT DEFAULT '',
        created_at INTEGER NOT NULL,
        FOREIGN KEY (message_id) REFERENCES messages(id)
    );
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        channel_id TEXT,
        status TEXT DEFAULT 'todo',
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        milestone_id TEXT,
        deadline INTEGER,
        created_at INTEGER NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );
    CREATE TABLE IF NOT EXISTS milestones (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        name TEXT NOT NULL,
        deadline INTEGER,
        color TEXT DEFAULT '#6366f1',
        created_at INTEGER NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );
    CREATE TABLE IF NOT EXISTS team_members (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT DEFAULT '멤버',
        avatar_color TEXT DEFAULT '#6366f1',
        created_at INTEGER NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );
    CREATE TABLE IF NOT EXISTS ai_bots (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        project_id TEXT,
        name TEXT NOT NULL,
        role TEXT DEFAULT '',
        avatar TEXT DEFAULT '🤖',
        system_prompt TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS settings (
        user_id TEXT PRIMARY KEY,
        gateway_url TEXT DEFAULT '',
        gateway_token TEXT DEFAULT '',
        context_length INTEGER DEFAULT 20,
        theme TEXT DEFAULT 'dark',
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS gateways (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        token TEXT DEFAULT '',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        kind TEXT DEFAULT 'openclaw',
        capabilities TEXT DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS chat_logs (
        id TEXT PRIMARY KEY,
        gateway_id TEXT DEFAULT '',
        gateway_name TEXT DEFAULT '',
        role TEXT DEFAULT '',
        content TEXT DEFAULT '',
        model TEXT DEFAULT '',
        tokens_prompt INTEGER DEFAULT 0,
        tokens_completion INTEGER DEFAULT 0,
        created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_messages_bot ON messages(bot_id);
    CREATE INDEX IF NOT EXISTS idx_threads_message ON threads(message_id);
    CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id, status);
    CREATE INDEX IF NOT EXISTS idx_chat_logs_gateway ON chat_logs(gateway_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_gateways_name ON gateways(name);
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def make_token(user_id):
    ts = int(time.time())
    sig = hmac.new(SECRET.encode(), f"{user_id}:{ts}".encode(), hashlib.sha256).hexdigest()
    payload = json.dumps({"user_id": user_id, "ts": ts, "sig": sig})
    return base64.b64encode(payload.encode()).decode()


def verify_token(token):
    try:
        payload = json.loads(base64.b64decode(token))
        user_id = payload["user_id"]
        ts = payload["ts"]
        sig = payload["sig"]
        expected = hmac.new(SECRET.encode(), f"{user_id}:{ts}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(time.time()) - ts > TOKEN_EXPIRY:
            return None
        return user_id
    except Exception:
        return None


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def new_id():
    return uuid.uuid4().hex


def now_ts():
    return int(time.time() * 1000)


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class Handler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=DIR, **kw)

    # -- CORS & headers -----------------------------------------------------

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    # -- Response helpers ---------------------------------------------------

    def json_ok(self, data=None, status=200):
        body = {"ok": True}
        if data is not None:
            body["data"] = data
        self._send_json(status, body)

    def json_err(self, error, status=400):
        self._send_json(status, {"ok": False, "error": error})

    def _send_json(self, status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    # -- Auth helper --------------------------------------------------------

    def get_user_id(self):
        auth = self.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            token = auth[7:].strip()
            uid = verify_token(token)
            if uid:
                return uid
        return None

    def require_auth(self):
        uid = self.get_user_id()
        if not uid:
            self.json_err("로그인이 필요합니다", 401)
            return None
        return uid

    # -- Body / query helpers -----------------------------------------------

    def read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def parse_path(self):
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query)

    def qs_get(self, qs, key, default=None):
        vals = qs.get(key)
        if vals:
            return vals[0]
        return default

    # -- Ownership helpers --------------------------------------------------

    def _owns_project(self, db, user_id, project_id):
        row = db.execute("SELECT id FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
        return row is not None

    def _project_for_channel(self, db, channel_id):
        row = db.execute("SELECT project_id FROM channels WHERE id=?", (channel_id,)).fetchone()
        return row["project_id"] if row else None

    def _project_for_message(self, db, message_id):
        row = db.execute(
            "SELECT c.project_id FROM messages m JOIN channels c ON m.channel_id=c.id WHERE m.id=?",
            (message_id,)
        ).fetchone()
        return row["project_id"] if row else None

    # -- Routing ------------------------------------------------------------

    def _route(self, method):
        path, qs = self.parse_path()

        # Static files for non-API paths
        if not path.startswith('/api/'):
            if method == 'GET':
                return super().do_GET()
            self.send_response(405)
            self.end_headers()
            return

        try:
            # Auth
            if path == '/api/auth/register' and method == 'POST':
                return self.handle_register()
            if path == '/api/auth/login' and method == 'POST':
                return self.handle_login()
            if path == '/api/auth/me' and method == 'GET':
                return self.handle_me()

            # Chat proxy (no JWT)
            if path == '/api/chat' and method == 'POST':
                return self.handle_chat()

            # Migrate
            if path == '/api/migrate' and method == 'POST':
                return self.handle_migrate()

            # Settings
            if path == '/api/settings':
                if method == 'GET':
                    return self.handle_settings_get()
                if method == 'PUT':
                    return self.handle_settings_put()

            # CRUD resources
            resources = [
                ('/api/projects', self.h_projects),
                ('/api/channels', self.h_channels),
                ('/api/messages', self.h_messages),
                ('/api/threads', self.h_threads),
                ('/api/tasks', self.h_tasks),
                ('/api/milestones', self.h_milestones),
                ('/api/members', self.h_members),
                ('/api/bots', self.h_bots),
            ]

            for prefix, handler in resources:
                if path == prefix:
                    return handler(method, None, qs)
                if path.startswith(prefix + '/'):
                    rid = path[len(prefix) + 1:]
                    if rid:
                        return handler(method, rid, qs)

            # Gateways API
            if path == '/api/gateways' and method == 'GET':
                return self.h_gateways_list()
            if path == '/api/gateways/register' and method == 'POST':
                return self.h_gateways_register()
            if path == '/api/gateways/auto-detect' and method == 'POST':
                return self.h_gateways_auto_detect()
            if path == '/api/gateways/chat-logs' and method == 'GET':
                return self.h_gateways_chat_logs(qs)
            if path == '/api/gateway-broadcast' and method == 'POST':
                return self.h_gateway_broadcast()
            if path.startswith('/api/gateways/'):
                rid = path[len('/api/gateways/'):]
                if rid:
                    return self.h_gateways_detail(method, rid)

            self.json_err("찾을 수 없습니다", 404)

        except Exception as e:
            sys.stderr.write(f'[Chatub ERROR] {e}\n')
            import traceback
            traceback.print_exc(file=sys.stderr)
            self.json_err("서버 오류", 500)

    def do_GET(self):
        self._route('GET')

    def do_POST(self):
        self._route('POST')

    def do_PUT(self):
        self._route('PUT')

    def do_DELETE(self):
        self._route('DELETE')

    # -----------------------------------------------------------------------
    # Auth handlers
    # -----------------------------------------------------------------------

    def handle_register(self):
        data = self.read_json()
        username = (data.get('username') or '').strip()
        password = data.get('password') or ''
        display_name = (data.get('display_name') or username).strip()

        if not username or not password:
            return self.json_err("사용자명과 비밀번호를 입력하세요")

        db = get_db()
        try:
            existing = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            if existing:
                return self.json_err("이미 존재하는 사용자명")

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
            db.execute(
                "INSERT INTO settings (user_id) VALUES (?)",
                (user_id,)
            )

            db.commit()

            token = make_token(user_id)
            user = {"id": user_id, "username": username, "display_name": display_name, "avatar_color": "#6366f1"}
            self.json_ok({"token": token, "user": user})
        finally:
            db.close()

    def handle_login(self):
        data = self.read_json()
        username = (data.get('username') or '').strip()
        password = data.get('password') or ''

        db = get_db()
        try:
            row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            if not row or row["password_hash"] != hash_password(password):
                return self.json_err("사용자명 또는 비밀번호가 올바르지 않습니다")

            token = make_token(row["id"])
            user = {
                "id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "avatar_color": row["avatar_color"],
            }
            self.json_ok({"token": token, "user": user})
        finally:
            db.close()

    def handle_me(self):
        uid = self.get_user_id()
        if not uid:
            return self.json_err("로그인이 필요합니다", 401)
        db = get_db()
        try:
            row = db.execute("SELECT id, username, display_name, avatar_color FROM users WHERE id=?", (uid,)).fetchone()
            if not row:
                return self.json_err("로그인이 필요합니다", 401)
            self.json_ok({"user": dict(row)})
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # Settings
    # -----------------------------------------------------------------------

    def handle_settings_get(self):
        uid = self.require_auth()
        if not uid:
            return
        db = get_db()
        try:
            row = db.execute("SELECT * FROM settings WHERE user_id=?", (uid,)).fetchone()
            self.json_ok(dict(row) if row else {})
        finally:
            db.close()

    def handle_settings_put(self):
        uid = self.require_auth()
        if not uid:
            return
        data = self.read_json()
        db = get_db()
        try:
            allowed = ['gateway_url', 'gateway_token', 'context_length', 'theme']
            sets = []
            vals = []
            for k in allowed:
                if k in data:
                    sets.append(f"{k}=?")
                    vals.append(data[k])
            if sets:
                vals.append(uid)
                db.execute(f"UPDATE settings SET {', '.join(sets)} WHERE user_id=?", vals)
                db.commit()
            row = db.execute("SELECT * FROM settings WHERE user_id=?", (uid,)).fetchone()
            self.json_ok(dict(row) if row else {})
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # CRUD: Projects
    # -----------------------------------------------------------------------

    def h_projects(self, method, rid, qs):
        uid = self.require_auth()
        if not uid:
            return
        db = get_db()
        try:
            if method == 'GET' and not rid:
                rows = db.execute("SELECT * FROM projects WHERE user_id=? ORDER BY created_at", (uid,)).fetchall()
                return self.json_ok(rows_to_list(rows))

            if method == 'POST' and not rid:
                data = self.read_json()
                pid = new_id()
                ts = now_ts()
                db.execute(
                    "INSERT INTO projects (id, user_id, name, description, color, created_at) VALUES (?,?,?,?,?,?)",
                    (pid, uid, data.get('name', ''), data.get('description', ''), data.get('color', '#6366f1'), ts)
                )
                db.commit()
                row = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'PUT' and rid:
                if not self._owns_project(db, uid, rid):
                    return self.json_err("찾을 수 없습니다", 404)
                data = self.read_json()
                allowed = ['name', 'description', 'color']
                sets, vals = self._build_update(data, allowed)
                if sets:
                    vals.append(rid)
                    db.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", vals)
                    db.commit()
                row = db.execute("SELECT * FROM projects WHERE id=?", (rid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'DELETE' and rid:
                if not self._owns_project(db, uid, rid):
                    return self.json_err("찾을 수 없습니다", 404)
                # Delete all related data
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
                return self.json_ok()

            self.json_err("찾을 수 없습니다", 404)
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # CRUD: Channels
    # -----------------------------------------------------------------------

    def h_channels(self, method, rid, qs):
        uid = self.require_auth()
        if not uid:
            return
        db = get_db()
        try:
            if method == 'GET' and not rid:
                project_id = self.qs_get(qs, 'project_id')
                if not project_id or not self._owns_project(db, uid, project_id):
                    return self.json_err("찾을 수 없습니다", 404)
                rows = db.execute("SELECT * FROM channels WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
                return self.json_ok(rows_to_list(rows))

            if method == 'POST' and not rid:
                data = self.read_json()
                project_id = data.get('project_id')
                if not project_id or not self._owns_project(db, uid, project_id):
                    return self.json_err("찾을 수 없습니다", 404)
                cid = new_id()
                ts = now_ts()
                db.execute(
                    "INSERT INTO channels (id, project_id, name, icon, color, created_at) VALUES (?,?,?,?,?,?)",
                    (cid, project_id, data.get('name', ''), data.get('icon', '#'), data.get('color', '#6366f1'), ts)
                )
                db.commit()
                row = db.execute("SELECT * FROM channels WHERE id=?", (cid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'PUT' and rid:
                ch = db.execute("SELECT * FROM channels WHERE id=?", (rid,)).fetchone()
                if not ch or not self._owns_project(db, uid, ch["project_id"]):
                    return self.json_err("찾을 수 없습니다", 404)
                data = self.read_json()
                sets, vals = self._build_update(data, ['name', 'icon', 'color'])
                if sets:
                    vals.append(rid)
                    db.execute(f"UPDATE channels SET {', '.join(sets)} WHERE id=?", vals)
                    db.commit()
                row = db.execute("SELECT * FROM channels WHERE id=?", (rid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'DELETE' and rid:
                ch = db.execute("SELECT * FROM channels WHERE id=?", (rid,)).fetchone()
                if not ch or not self._owns_project(db, uid, ch["project_id"]):
                    return self.json_err("찾을 수 없습니다", 404)
                msg_ids = [r["id"] for r in db.execute("SELECT id FROM messages WHERE channel_id=?", (rid,)).fetchall()]
                for mid in msg_ids:
                    db.execute("DELETE FROM threads WHERE message_id=?", (mid,))
                db.execute("DELETE FROM messages WHERE channel_id=?", (rid,))
                db.execute("DELETE FROM channels WHERE id=?", (rid,))
                db.commit()
                return self.json_ok()

            self.json_err("찾을 수 없습니다", 404)
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # CRUD: Messages
    # -----------------------------------------------------------------------

    def h_messages(self, method, rid, qs):
        uid = self.require_auth()
        if not uid:
            return
        db = get_db()
        try:
            if method == 'GET' and not rid:
                channel_id = self.qs_get(qs, 'channel_id')
                if not channel_id:
                    return self.json_err("channel_id 필요")
                proj_id = self._project_for_channel(db, channel_id)
                if not proj_id or not self._owns_project(db, uid, proj_id):
                    return self.json_err("찾을 수 없습니다", 404)
                limit = int(self.qs_get(qs, 'limit', '50'))
                before = self.qs_get(qs, 'before')
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
                return self.json_ok(rows_to_list(rows))

            if method == 'POST' and not rid:
                data = self.read_json()
                channel_id = data.get('channel_id')
                if not channel_id:
                    return self.json_err("channel_id 필요")
                proj_id = self._project_for_channel(db, channel_id)
                if not proj_id or not self._owns_project(db, uid, proj_id):
                    return self.json_err("찾을 수 없습니다", 404)
                mid = new_id()
                ts = now_ts()
                bot_id = data.get('bot_id')
                db.execute(
                    "INSERT INTO messages (id, channel_id, user_id, bot_id, text, image, reactions_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (mid, channel_id, uid if not bot_id else None, bot_id, data.get('text', ''), data.get('image', ''), '{}', ts)
                )
                db.commit()
                row = db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'PUT' and rid:
                msg = db.execute("SELECT * FROM messages WHERE id=?", (rid,)).fetchone()
                if not msg:
                    return self.json_err("찾을 수 없습니다", 404)
                proj_id = self._project_for_channel(db, msg["channel_id"])
                if not proj_id or not self._owns_project(db, uid, proj_id):
                    return self.json_err("찾을 수 없습니다", 404)
                data = self.read_json()
                edited_at = now_ts()
                text = data.get('text', msg['text'])
                db.execute("UPDATE messages SET text=?, edited_at=? WHERE id=?", (text, edited_at, rid))
                db.commit()
                row = db.execute("SELECT * FROM messages WHERE id=?", (rid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'DELETE' and rid:
                msg = db.execute("SELECT * FROM messages WHERE id=?", (rid,)).fetchone()
                if not msg:
                    return self.json_err("찾을 수 없습니다", 404)
                proj_id = self._project_for_channel(db, msg["channel_id"])
                if not proj_id or not self._owns_project(db, uid, proj_id):
                    return self.json_err("찾을 수 없습니다", 404)
                db.execute("DELETE FROM threads WHERE message_id=?", (rid,))
                db.execute("DELETE FROM messages WHERE id=?", (rid,))
                db.commit()
                return self.json_ok()

            self.json_err("찾을 수 없습니다", 404)
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # CRUD: Threads
    # -----------------------------------------------------------------------

    def h_threads(self, method, rid, qs):
        uid = self.require_auth()
        if not uid:
            return
        db = get_db()
        try:
            if method == 'GET' and not rid:
                message_id = self.qs_get(qs, 'message_id')
                if not message_id:
                    return self.json_err("message_id 필요")
                proj_id = self._project_for_message(db, message_id)
                if not proj_id or not self._owns_project(db, uid, proj_id):
                    return self.json_err("찾을 수 없습니다", 404)
                rows = db.execute(
                    """SELECT t.*, COALESCE(u.display_name, b.name, '알 수 없음') as author_name
                       FROM threads t
                       LEFT JOIN users u ON t.user_id = u.id
                       LEFT JOIN ai_bots b ON t.bot_id = b.id
                       WHERE t.message_id=? ORDER BY t.created_at""",
                    (message_id,)
                ).fetchall()
                return self.json_ok(rows_to_list(rows))

            if method == 'POST' and not rid:
                data = self.read_json()
                message_id = data.get('message_id')
                if not message_id:
                    return self.json_err("message_id 필요")
                proj_id = self._project_for_message(db, message_id)
                if not proj_id or not self._owns_project(db, uid, proj_id):
                    return self.json_err("찾을 수 없습니다", 404)
                tid = new_id()
                ts = now_ts()
                bot_id = data.get('bot_id')
                db.execute(
                    "INSERT INTO threads (id, message_id, user_id, bot_id, text, created_at) VALUES (?,?,?,?,?,?)",
                    (tid, message_id, uid if not bot_id else None, bot_id, data.get('text', ''), ts)
                )
                db.commit()
                row = db.execute("SELECT * FROM threads WHERE id=?", (tid,)).fetchone()
                return self.json_ok(dict(row))

            self.json_err("찾을 수 없습니다", 404)
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # CRUD: Tasks
    # -----------------------------------------------------------------------

    def h_tasks(self, method, rid, qs):
        uid = self.require_auth()
        if not uid:
            return
        db = get_db()
        try:
            if method == 'GET' and not rid:
                project_id = self.qs_get(qs, 'project_id')
                if not project_id or not self._owns_project(db, uid, project_id):
                    return self.json_err("찾을 수 없습니다", 404)
                sql = "SELECT * FROM tasks WHERE project_id=?"
                params = [project_id]
                status = self.qs_get(qs, 'status')
                if status:
                    sql += " AND status=?"
                    params.append(status)
                milestone_id = self.qs_get(qs, 'milestone_id')
                if milestone_id:
                    sql += " AND milestone_id=?"
                    params.append(milestone_id)
                sql += " ORDER BY created_at"
                rows = db.execute(sql, params).fetchall()
                return self.json_ok(rows_to_list(rows))

            if method == 'POST' and not rid:
                data = self.read_json()
                project_id = data.get('project_id')
                if not project_id or not self._owns_project(db, uid, project_id):
                    return self.json_err("찾을 수 없습니다", 404)
                tid = new_id()
                ts = now_ts()
                db.execute(
                    "INSERT INTO tasks (id, project_id, channel_id, status, title, description, milestone_id, deadline, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (tid, project_id, data.get('channel_id'), data.get('status', 'todo'),
                     data.get('title', ''), data.get('description', ''),
                     data.get('milestone_id'), data.get('deadline'), ts)
                )
                db.commit()
                row = db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'PUT' and rid:
                task = db.execute("SELECT * FROM tasks WHERE id=?", (rid,)).fetchone()
                if not task or not self._owns_project(db, uid, task["project_id"]):
                    return self.json_err("찾을 수 없습니다", 404)
                data = self.read_json()
                allowed = ['status', 'title', 'description', 'milestone_id', 'deadline', 'channel_id']
                sets, vals = self._build_update(data, allowed)
                if sets:
                    vals.append(rid)
                    db.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", vals)
                    db.commit()
                row = db.execute("SELECT * FROM tasks WHERE id=?", (rid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'DELETE' and rid:
                task = db.execute("SELECT * FROM tasks WHERE id=?", (rid,)).fetchone()
                if not task or not self._owns_project(db, uid, task["project_id"]):
                    return self.json_err("찾을 수 없습니다", 404)
                db.execute("DELETE FROM tasks WHERE id=?", (rid,))
                db.commit()
                return self.json_ok()

            self.json_err("찾을 수 없습니다", 404)
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # CRUD: Milestones
    # -----------------------------------------------------------------------

    def h_milestones(self, method, rid, qs):
        uid = self.require_auth()
        if not uid:
            return
        db = get_db()
        try:
            if method == 'GET' and not rid:
                project_id = self.qs_get(qs, 'project_id')
                if not project_id or not self._owns_project(db, uid, project_id):
                    return self.json_err("찾을 수 없습니다", 404)
                rows = db.execute("SELECT * FROM milestones WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
                return self.json_ok(rows_to_list(rows))

            if method == 'POST' and not rid:
                data = self.read_json()
                project_id = data.get('project_id')
                if not project_id or not self._owns_project(db, uid, project_id):
                    return self.json_err("찾을 수 없습니다", 404)
                mid = new_id()
                ts = now_ts()
                db.execute(
                    "INSERT INTO milestones (id, project_id, name, deadline, color, created_at) VALUES (?,?,?,?,?,?)",
                    (mid, project_id, data.get('name', ''), data.get('deadline'), data.get('color', '#6366f1'), ts)
                )
                db.commit()
                row = db.execute("SELECT * FROM milestones WHERE id=?", (mid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'PUT' and rid:
                ms = db.execute("SELECT * FROM milestones WHERE id=?", (rid,)).fetchone()
                if not ms or not self._owns_project(db, uid, ms["project_id"]):
                    return self.json_err("찾을 수 없습니다", 404)
                data = self.read_json()
                sets, vals = self._build_update(data, ['name', 'deadline', 'color'])
                if sets:
                    vals.append(rid)
                    db.execute(f"UPDATE milestones SET {', '.join(sets)} WHERE id=?", vals)
                    db.commit()
                row = db.execute("SELECT * FROM milestones WHERE id=?", (rid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'DELETE' and rid:
                ms = db.execute("SELECT * FROM milestones WHERE id=?", (rid,)).fetchone()
                if not ms or not self._owns_project(db, uid, ms["project_id"]):
                    return self.json_err("찾을 수 없습니다", 404)
                db.execute("DELETE FROM milestones WHERE id=?", (rid,))
                db.commit()
                return self.json_ok()

            self.json_err("찾을 수 없습니다", 404)
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # CRUD: Team Members
    # -----------------------------------------------------------------------

    def h_members(self, method, rid, qs):
        uid = self.require_auth()
        if not uid:
            return
        db = get_db()
        try:
            if method == 'GET' and not rid:
                project_id = self.qs_get(qs, 'project_id')
                if not project_id or not self._owns_project(db, uid, project_id):
                    return self.json_err("찾을 수 없습니다", 404)
                rows = db.execute("SELECT * FROM team_members WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
                return self.json_ok(rows_to_list(rows))

            if method == 'POST' and not rid:
                data = self.read_json()
                project_id = data.get('project_id')
                if not project_id or not self._owns_project(db, uid, project_id):
                    return self.json_err("찾을 수 없습니다", 404)
                mid = new_id()
                ts = now_ts()
                db.execute(
                    "INSERT INTO team_members (id, project_id, name, role, avatar_color, created_at) VALUES (?,?,?,?,?,?)",
                    (mid, project_id, data.get('name', ''), data.get('role', '멤버'), data.get('avatar_color', '#6366f1'), ts)
                )
                db.commit()
                row = db.execute("SELECT * FROM team_members WHERE id=?", (mid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'PUT' and rid:
                mem = db.execute("SELECT * FROM team_members WHERE id=?", (rid,)).fetchone()
                if not mem or not self._owns_project(db, uid, mem["project_id"]):
                    return self.json_err("찾을 수 없습니다", 404)
                data = self.read_json()
                sets, vals = self._build_update(data, ['name', 'role', 'avatar_color'])
                if sets:
                    vals.append(rid)
                    db.execute(f"UPDATE team_members SET {', '.join(sets)} WHERE id=?", vals)
                    db.commit()
                row = db.execute("SELECT * FROM team_members WHERE id=?", (rid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'DELETE' and rid:
                mem = db.execute("SELECT * FROM team_members WHERE id=?", (rid,)).fetchone()
                if not mem or not self._owns_project(db, uid, mem["project_id"]):
                    return self.json_err("찾을 수 없습니다", 404)
                db.execute("DELETE FROM team_members WHERE id=?", (rid,))
                db.commit()
                return self.json_ok()

            self.json_err("찾을 수 없습니다", 404)
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # CRUD: AI Bots
    # -----------------------------------------------------------------------

    def h_bots(self, method, rid, qs):
        uid = self.require_auth()
        if not uid:
            return
        db = get_db()
        try:
            if method == 'GET' and not rid:
                project_id = self.qs_get(qs, 'project_id')
                if project_id:
                    if not self._owns_project(db, uid, project_id):
                        return self.json_err("찾을 수 없습니다", 404)
                    rows = db.execute(
                        "SELECT * FROM ai_bots WHERE user_id=? AND (project_id=? OR project_id IS NULL) ORDER BY created_at",
                        (uid, project_id)
                    ).fetchall()
                else:
                    rows = db.execute(
                        "SELECT * FROM ai_bots WHERE user_id=? ORDER BY created_at",
                        (uid,)
                    ).fetchall()
                return self.json_ok(rows_to_list(rows))

            if method == 'POST' and not rid:
                data = self.read_json()
                project_id = data.get('project_id')
                if project_id and not self._owns_project(db, uid, project_id):
                    return self.json_err("찾을 수 없습니다", 404)
                bid = new_id()
                ts = now_ts()
                db.execute(
                    "INSERT INTO ai_bots (id, user_id, project_id, name, role, avatar, system_prompt, is_active, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (bid, uid, project_id, data.get('name', ''), data.get('role', ''),
                     data.get('avatar', '🤖'), data.get('system_prompt', ''),
                     1 if data.get('is_active', True) else 0, ts)
                )
                db.commit()
                row = db.execute("SELECT * FROM ai_bots WHERE id=?", (bid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'PUT' and rid:
                bot = db.execute("SELECT * FROM ai_bots WHERE id=? AND user_id=?", (rid, uid)).fetchone()
                if not bot:
                    return self.json_err("찾을 수 없습니다", 404)
                data = self.read_json()
                allowed = ['name', 'role', 'avatar', 'system_prompt', 'is_active', 'project_id']
                sets, vals = self._build_update(data, allowed)
                if sets:
                    vals.append(rid)
                    db.execute(f"UPDATE ai_bots SET {', '.join(sets)} WHERE id=?", vals)
                    db.commit()
                row = db.execute("SELECT * FROM ai_bots WHERE id=?", (rid,)).fetchone()
                return self.json_ok(dict(row))

            if method == 'DELETE' and rid:
                bot = db.execute("SELECT * FROM ai_bots WHERE id=? AND user_id=?", (rid, uid)).fetchone()
                if not bot:
                    return self.json_err("찾을 수 없습니다", 404)
                db.execute("DELETE FROM ai_bots WHERE id=?", (rid,))
                db.commit()
                return self.json_ok()

            self.json_err("찾을 수 없습니다", 404)
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # Gateways API
    # -----------------------------------------------------------------------

    def h_gateways_list(self):
        """List all registered gateways with live status."""
        db = get_db()
        try:
            rows = db.execute("SELECT * FROM gateways ORDER BY name").fetchall()
            result = []
            for row in rows:
                gw = dict(row)
                gw['online'] = False
                gw['status'] = 'disconnected'
                gw['agents'] = []
                gw['version'] = None
                gw['pairing_status'] = 'disconnected'
                # Live health check
                gw['last_check'] = now_ts()
                try:
                    url = gw['url'].rstrip('/')
                    token = gw.get('token', '')
                    headers = {}
                    if token:
                        headers['Authorization'] = f'Bearer {token}'
                    req = urllib.request.Request(f'{url}/api/v1/health', headers=headers, method='GET')
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        health = json.loads(resp.read())
                        gw['online'] = True
                        gw['status'] = 'online'
                        gw['agents'] = health.get('agents', [])
                        gw['version'] = health.get('version', None)
                        gw['pairing_status'] = 'connected'
                except Exception:
                    pass
                gw['updated_at'] = now_ts()
                db.execute("UPDATE gateways SET updated_at=? WHERE id=?", (gw['updated_at'], gw['id']))
                result.append(gw)
            db.commit()
            return self.json_ok(result)
        finally:
            db.close()

    def h_gateways_register(self):
        """Register a new gateway."""
        uid = self.require_auth()
        if not uid:
            return
        data = self.read_json()
        name = (data.get('name') or '').strip()
        url = (data.get('url') or '').strip()
        token = (data.get('token') or '').strip()
        kind = (data.get('kind') or 'openclaw').strip()
        capabilities = (data.get('capabilities') or '{}').strip()
        if not name or not url:
            return self.json_err('name과 url이 필요합니다')
        db = get_db()
        try:
            gid = new_id()
            db.execute(
                "INSERT INTO gateways (id, name, url, token, kind, capabilities, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (gid, name, url, token, kind, capabilities, now_ts(), now_ts())
            )
            db.commit()
            row = db.execute("SELECT * FROM gateways WHERE id=?", (gid,)).fetchone()
            return self.json_ok(dict(row))
        finally:
            db.close()

    def h_gateways_auto_detect(self):
        """Auto-detect gateway at given URL."""
        data = self.read_json()
        url = (data.get('url') or '').strip()
        if not url:
            return self.json_err('url이 필요합니다')
        result = {'url': url, 'online': False, 'version': None, 'agents': []}
        try:
            url = url.rstrip('/')
            req = urllib.request.Request(f'{url}/api/v1/health', method='GET')
            with urllib.request.urlopen(req, timeout=5) as resp:
                health = json.loads(resp.read())
                result['online'] = True
                result['version'] = health.get('version')
                result['agents'] = health.get('agents', [])
        except Exception:
            pass
        return self.json_ok(result)

    def h_gateways_chat_logs(self, qs):
        """Get chat logs filtered by gateway_id."""
        gw_id = self.qs_get(qs, 'gateway_id')
        limit = int(self.qs_get(qs, 'limit', '50'))
        db = get_db()
        try:
            if gw_id:
                rows = db.execute(
                    "SELECT * FROM chat_logs WHERE gateway_id=? ORDER BY created_at DESC LIMIT ?",
                    (gw_id, limit)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM chat_logs ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return self.json_ok([dict(r) for r in rows])
        finally:
            db.close()

    def h_gateway_broadcast(self):
        """Broadcast message to all online gateways."""
        data = self.read_json()
        text = (data.get('text') or '').strip()
        if not text:
            return self.json_err('text가 필요합니다')
        db = get_db()
        try:
            gateways = db.execute("SELECT * FROM gateways").fetchall()
            results = []
            for gw in gateways:
                gw_dict = dict(gw)
                url = gw_dict['url'].rstrip('/')
                token = gw_dict.get('token', '')
                status = 'error'
                try:
                    headers = {'Content-Type': 'application/json'}
                    if token:
                        headers['Authorization'] = f'Bearer {token}'
                    payload = json.dumps({'message': text, 'stream': False}).encode()
                    req = urllib.request.Request(f'{url}/api/v1/chat', data=payload, headers=headers, method='POST')
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        resp_data = json.loads(resp.read())
                        # Log to chat_logs
                        db.execute(
                            "INSERT INTO chat_logs (id, gateway_id, gateway_name, role, content, created_at) VALUES (?,?,?,?,?,?)",
                            (new_id(), gw_dict['id'], gw_dict['name'], 'user', text, now_ts())
                        )
                        if 'response' in resp_data:
                            db.execute(
                                "INSERT INTO chat_logs (id, gateway_id, gateway_name, role, content, created_at) VALUES (?,?,?,?,?,?)",
                                (new_id(), gw_dict['id'], gw_dict['name'], 'assistant', resp_data['response'], now_ts())
                            )
                        status = 'ok'
                except Exception as e:
                    status = f'error: {str(e)[:100]}'
                results.append({'name': gw_dict['name'], 'status': status})
            db.commit()
            return self.json_ok({'sent': len(results), 'results': results})
        finally:
            db.close()

    def h_gateways_detail(self, method, rid):
        """Get or delete a single gateway by ID."""
        db = get_db()
        try:
            if method == 'GET':
                row = db.execute("SELECT * FROM gateways WHERE id=?", (rid,)).fetchone()
                if not row:
                    return self.json_err('찾을 수 없습니다', 404)
                return self.json_ok(dict(row))
            if method == 'DELETE':
                db.execute("DELETE FROM gateways WHERE id=?", (rid,))
                db.commit()
                return self.json_ok()
            self.json_err('허용되지 않는 메서드', 405)
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # Migration (localStorage -> DB)
    # -----------------------------------------------------------------------

    def handle_migrate(self):
        uid = self.require_auth()
        if not uid:
            return
        data = self.read_json()
        projects = data.get('projects', [])
        db = get_db()
        try:
            ts = now_ts()
            for proj in projects:
                pid = proj.get('id') or new_id()
                # Skip if project already exists
                existing = db.execute("SELECT id FROM projects WHERE id=?", (pid,)).fetchone()
                if existing:
                    continue
                db.execute(
                    "INSERT INTO projects (id, user_id, name, description, color, created_at) VALUES (?,?,?,?,?,?)",
                    (pid, uid, proj.get('name', ''), proj.get('description', ''),
                     proj.get('color', '#6366f1'), proj.get('created_at', ts))
                )
                # Channels
                for ch in proj.get('channels', []):
                    cid = ch.get('id') or new_id()
                    db.execute(
                        "INSERT INTO channels (id, project_id, name, icon, color, created_at) VALUES (?,?,?,?,?,?)",
                        (cid, pid, ch.get('name', ''), ch.get('icon', '#'),
                         ch.get('color', '#6366f1'), ch.get('created_at', ts))
                    )
                    # Messages
                    for msg in ch.get('messages', []):
                        mid = msg.get('id') or new_id()
                        db.execute(
                            "INSERT INTO messages (id, channel_id, user_id, bot_id, text, image, reactions_json, created_at, edited_at) VALUES (?,?,?,?,?,?,?,?,?)",
                            (mid, cid, msg.get('user_id') or uid, msg.get('bot_id'),
                             msg.get('text', ''), msg.get('image', ''),
                             json.dumps(msg.get('reactions', {}), ensure_ascii=False),
                             msg.get('created_at', ts), msg.get('edited_at'))
                        )
                        # Threads
                        for th in msg.get('threads', []):
                            tid = th.get('id') or new_id()
                            db.execute(
                                "INSERT INTO threads (id, message_id, user_id, bot_id, text, created_at) VALUES (?,?,?,?,?,?)",
                                (tid, mid, th.get('user_id') or uid, th.get('bot_id'),
                                 th.get('text', ''), th.get('created_at', ts))
                            )
                # Tasks
                for task in proj.get('tasks', []):
                    tid = task.get('id') or new_id()
                    db.execute(
                        "INSERT INTO tasks (id, project_id, channel_id, status, title, description, milestone_id, deadline, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (tid, pid, task.get('channel_id'), task.get('status', 'todo'),
                         task.get('title', ''), task.get('description', ''),
                         task.get('milestone_id'), task.get('deadline'), task.get('created_at', ts))
                    )
                # Milestones
                for ms in proj.get('milestones', []):
                    msid = ms.get('id') or new_id()
                    db.execute(
                        "INSERT INTO milestones (id, project_id, name, deadline, color, created_at) VALUES (?,?,?,?,?,?)",
                        (msid, pid, ms.get('name', ''), ms.get('deadline'),
                         ms.get('color', '#6366f1'), ms.get('created_at', ts))
                    )
                # Team members
                for mem in proj.get('members', []):
                    memid = mem.get('id') or new_id()
                    db.execute(
                        "INSERT INTO team_members (id, project_id, name, role, avatar_color, created_at) VALUES (?,?,?,?,?,?)",
                        (memid, pid, mem.get('name', ''), mem.get('role', '멤버'),
                         mem.get('avatar_color', '#6366f1'), mem.get('created_at', ts))
                    )
                # Bots
                for bot in proj.get('bots', []):
                    botid = bot.get('id') or new_id()
                    db.execute(
                        "INSERT INTO ai_bots (id, user_id, project_id, name, role, avatar, system_prompt, is_active, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (botid, uid, pid, bot.get('name', ''), bot.get('role', ''),
                         bot.get('avatar', '🤖'), bot.get('system_prompt', ''),
                         1 if bot.get('is_active', True) else 0, bot.get('created_at', ts))
                    )
            db.commit()
            self.json_ok({"imported": len(projects)})
        except Exception as e:
            db.rollback()
            raise
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # Chat proxy (SSE streaming to Gateway) - kept from original
    # -----------------------------------------------------------------------

    def handle_chat(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        data = json.loads(body)

        gw_url = (self.headers.get('X-Gateway-URL') or 'http://127.0.0.1:18789').rstrip('/')
        token = self.headers.get('X-Gateway-Token') or self.headers.get('Authorization', '').replace('Bearer ', '').strip() or ''
        is_stream = data.get('stream', False)

        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        try:
            req = urllib.request.Request(
                f'{gw_url}/v1/chat/completions',
                data=json.dumps(data).encode(),
                headers=headers,
                method='POST'
            )
            resp = urllib.request.urlopen(req, timeout=120)

            if is_stream:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                while True:
                    chunk = resp.read(1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            else:
                result = resp.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(result)

        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode())

    # -----------------------------------------------------------------------
    # Utility
    # -----------------------------------------------------------------------

    def _build_update(self, data, allowed):
        """Build SET clause parts from data dict, filtering to allowed keys."""
        sets = []
        vals = []
        for k in allowed:
            if k in data:
                sets.append(f"{k}=?")
                vals.append(data[k])
        return sets, vals

    def log_message(self, fmt, *args):
        try:
            sys.stderr.write(f'[Chatub] {args[0]} {args[1]} {args[2]}\n')
        except (IndexError, TypeError):
            sys.stderr.write(f'[Chatub] {fmt % args if args else fmt}\n')


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class ReuseServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == '__main__':
    init_db()
    print(f'Chatub backend on http://localhost:{PORT}')
    try:
        ReuseServer(('0.0.0.0', PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print('\nBye')
