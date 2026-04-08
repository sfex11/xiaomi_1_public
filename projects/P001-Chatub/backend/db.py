"""Database initialization and helpers."""

import sqlite3
import os
import uuid
import time
import json

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(DIR, 'chatub.db')


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def new_id() -> str:
    return uuid.uuid4().hex


def now_ts() -> int:
    return int(time.time() * 1000)


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    return [dict(r) for r in rows]


def owns_project(db, user_id, project_id) -> bool:
    row = db.execute("SELECT id FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
    return row is not None


def project_for_channel(db, channel_id):
    row = db.execute("SELECT project_id FROM channels WHERE id=?", (channel_id,)).fetchone()
    return row["project_id"] if row else None


def project_for_message(db, message_id):
    row = db.execute(
        "SELECT c.project_id FROM messages m JOIN channels c ON m.channel_id=c.id WHERE m.id=?",
        (message_id,)
    ).fetchone()
    return row["project_id"] if row else None


def build_update(data: dict, allowed: list):
    """Build SET clause parts from data dict, filtering to allowed keys."""
    sets = []
    vals = []
    for k in allowed:
        if k in data:
            sets.append(f"{k}=?")
            vals.append(data[k])
    return sets, vals


SCHEMA_SQL = """
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
"""


MIGRATIONS = [
    # Gateway registry table
    """
    CREATE TABLE IF NOT EXISTS gateways (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        url TEXT NOT NULL,
        token TEXT DEFAULT '',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    );
    """,
    # Chat monitoring log
    """
    CREATE TABLE IF NOT EXISTS chat_logs (
        id TEXT PRIMARY KEY,
        gateway_id TEXT NOT NULL,
        gateway_name TEXT DEFAULT '',
        role TEXT DEFAULT 'user',
        content TEXT DEFAULT '',
        model TEXT DEFAULT '',
        tokens_prompt INTEGER DEFAULT 0,
        tokens_completion INTEGER DEFAULT 0,
        created_at INTEGER NOT NULL
    );
    """,
    # Phase 3: Agent API columns on ai_bots
    """
    ALTER TABLE ai_bots ADD COLUMN api_key TEXT;
    """,
    """
    ALTER TABLE ai_bots ADD COLUMN webhook_url TEXT;
    """,
    """
    ALTER TABLE ai_bots ADD COLUMN permissions TEXT DEFAULT 'read,write';
    """,
]


def _run_migrations(conn):
    for sql in MIGRATIONS:
        try:
            conn.executescript(sql)
        except Exception:
            pass  # column already exists


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA_SQL)
    _run_migrations(conn)
    conn.commit()
    conn.close()
