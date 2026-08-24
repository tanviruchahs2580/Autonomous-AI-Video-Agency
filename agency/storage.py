from __future__ import annotations

import hashlib
import io
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO


class ObjectStore:
    def put_bytes(self, key: str, data: bytes) -> str: ...
    def put_file(self, key: str, src: Path) -> str: ...
    def get_bytes(self, key: str) -> bytes: ...
    def open(self, key: str) -> BinaryIO: ...
    def exists(self, key: str) -> bool: ...
    def stat(self, key: str) -> dict: ...
    def delete(self, key: str) -> None: ...
    def local_path(self, key: str) -> Path: ...
    def iter_prefix(self, prefix: str) -> Iterator[str]: ...


class LocalObjectStore(ObjectStore):
    def __init__(self, base_dir: Path | str) -> None:
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        candidate = (self.base / key).resolve()
        if not str(candidate).startswith(str(self.base)):
            raise ValueError("invalid storage key")
        return candidate

    def put_bytes(self, key: str, data: bytes) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return key

    def put_file(self, key: str, src: Path) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, path)
        return key

    def get_bytes(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def open(self, key: str) -> BinaryIO:
        return open(self._resolve(key), "rb")

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def stat(self, key: str) -> dict:
        path = self._resolve(key)
        if not path.exists():
            raise FileNotFoundError(key)
        return {"size": path.stat().st_size, "sha256": sha256_file(path)}

    def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

    def local_path(self, key: str) -> Path:
        return self._resolve(key)

    def iter_prefix(self, prefix: str) -> Iterator[str]:
        root = self._resolve(prefix)
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    yield p.relative_to(self.base).as_posix()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def temp_media_dir(prefix: str = "agency-") -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix=prefix)


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def human_size(n: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


__all__ = ["ObjectStore", "LocalObjectStore", "sha256_file", "sha256_bytes", "temp_media_dir", "ensure_parent", "human_size", "io"]
