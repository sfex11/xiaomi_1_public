"""Token generation, validation, and password hashing."""

import hashlib
import hmac
import json
import base64
import time
import os

from fastapi import Header, HTTPException

SECRET = os.environ.get("CHATUB_SECRET", os.urandom(32).hex())
TOKEN_EXPIRY = 604800  # 7 days


def make_token(user_id: str) -> str:
    ts = int(time.time())
    sig = hmac.new(SECRET.encode(), f"{user_id}:{ts}".encode(), hashlib.sha256).hexdigest()
    payload = json.dumps({"user_id": user_id, "ts": ts, "sig": sig})
    return base64.b64encode(payload.encode()).decode()


def verify_token(token: str):
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


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def get_current_user(authorization: str = Header(default="")) -> str:
    """FastAPI dependency: extract and verify user_id from Authorization header."""
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        uid = verify_token(token)
        if uid:
            return uid
    raise HTTPException(status_code=401, detail="로그인이 필요합니다")


def get_optional_user(authorization: str = Header(default="")) -> str | None:
    """FastAPI dependency: extract user_id if present, None otherwise."""
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        return verify_token(token)
    return None
