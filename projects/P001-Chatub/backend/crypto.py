"""Simple token encryption for Chatub gateways.

Uses XOR-based encryption with a random key since cryptography (Fernet)
cannot be built on Termux. Not production-grade but prevents plaintext storage.
"""

import os
import base64
import json
from pathlib import Path

_KEY_FILE = Path(__file__).parent.parent / ".secret_key"


def _get_key() -> bytes:
    if _KEY_FILE.exists():
        return base64.b64decode(_KEY_FILE.read_text().strip())
    key = os.urandom(32)
    _KEY_FILE.write_text(base64.b64encode(key).decode())
    return key


_KEY = _get_key()


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    data = plaintext.encode("utf-8")
    xored = bytes(b ^ _KEY[i % len(_KEY)] for i, b in enumerate(data))
    return base64.b64encode(xored).decode("ascii")


def is_encrypted(value: str) -> bool:
    """Check if a value looks like our base64-encoded ciphertext."""
    if not value:
        return False
    try:
        decoded = base64.b64decode(value)
        return len(decoded) > 4  # plaintext tokens are usually shorter when b64-decoded fails
    except Exception:
        return False


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        data = base64.b64decode(ciphertext)
        xored = bytes(b ^ _KEY[i % len(_KEY)] for i, b in enumerate(data))
        return xored.decode("utf-8")
    except Exception:
        # Fallback: return as-is (might be unencrypted legacy token)
        return ciphertext
