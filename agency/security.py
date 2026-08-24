from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import re
import socket
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_UPLOAD_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".mp3", ".wav", ".m4a", ".png", ".jpg", ".jpeg", ".srt", ".vtt", ".ass", ".json"}
MAGIC_SIGNATURES: list[tuple[str, bytes]] = [
    ("mp4", b"ftyp"),
    ("webm/mkv", b"\x1a\x45\xdf\xa3"),
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("jpeg", b"\xff\xd8\xff"),
    ("wav", b"RIFF"),
    ("mp3", b"ID3"),
]

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"read", "write", "approve", "admin"},
    "editor": {"read", "write"},
    "approver": {"read", "approve"},
    "viewer": {"read"},
}


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_api_key(provided: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(provided), stored_hash)


def generate_api_key() -> str:
    return "agy_" + os.urandom(24).hex()


def safe_join(base: Path, *parts: str | Path) -> Path:
    base_resolved = base.resolve()
    candidate = (base_resolved / Path(*parts)).resolve()
    if not str(candidate).startswith(str(base_resolved)):
        raise ValueError("path traversal detected")
    return candidate


def validate_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValueError(f"extension {ext!r} not allowed")
    return ext


def sniff_kind(head: bytes) -> str | None:
    for kind, sig in MAGIC_SIGNATURES:
        if kind == "mp4":
            if head.find(sig) != -1:
                return kind
        elif head.startswith(sig):
            return kind
    return None


def validate_upload(path: Path, declared_ext: str, max_bytes: int) -> dict:
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("empty file")
    if size > max_bytes:
        raise ValueError("file exceeds maximum allowed size")
    with open(path, "rb") as fh:
        head = fh.read(64)
    kind = sniff_kind(head)
    media_exts = {".mp4", ".mov", ".webm", ".mkv", ".mp3", ".wav", ".m4a", ".png", ".jpg", ".jpeg"}
    if declared_ext in media_exts and kind is None:
        raise ValueError("file content does not match a known safe media signature")
    return {"size": size, "sniffed_kind": kind}


def sanitize_text(text_value: str, max_len: int = 20000) -> str:
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text_value)
    return cleaned[:max_len]


def assert_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("only http(s) URLs are allowed")
    host = parsed.hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise ValueError(f"cannot resolve host: {host}") from exc
    for info in infos:
        addr = info[4][0]
        ip = ipaddress.ip_address(addr)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"requests to private addresses are blocked: {addr}")


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._windows: dict[str, tuple[int, float]] = {}

    def allow(self, key: str) -> bool:
        import time

        now = time.monotonic()
        count, window_start = self._windows.get(key, (0, now))
        if now - window_start >= 60.0:
            count, window_start = 0, now
        if count >= self.per_minute:
            self._windows[key] = (count, window_start)
            return False
        self._windows[key] = (count + 1, window_start)
        return True


def write_private_temp(data: bytes, suffix: str) -> Path:
    fd, path = tempfile.mkstemp(suffix=suffix)
    tmp = Path(path)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    return tmp
