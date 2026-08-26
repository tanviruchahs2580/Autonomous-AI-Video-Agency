from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

_SECRET_KEY = None


def _key() -> str:
    global _SECRET_KEY
    if _SECRET_KEY is None:
        from ..config import get_settings
        _SECRET_KEY = get_settings().api_key + "|jwt-signing"
    return _SECRET_KEY


def make_token(payload: dict, expires_s: int = 86400) -> str:
    body = dict(payload)
    body["exp"] = int(time.time()) + expires_s
    raw = json.dumps(body, sort_keys=True).encode()
    sig = hmac.new(_key().encode(), raw, hashlib.sha256).hexdigest()
    import base64
    return base64.urlsafe_b64encode(raw).decode() + "." + sig


def verify_token(token: str) -> dict | None:
    import base64
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        raw = base64.urlsafe_b64decode(parts[0])
        expected = hmac.new(_key().encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, parts[1]):
            return None
        data: dict[str, Any] = json.loads(raw)
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def hash_password(password: str) -> str:
    salt = __import__("os").urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False
