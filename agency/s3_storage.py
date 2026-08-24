from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from .storage import ObjectStore, sha256_file


class S3ObjectStore(ObjectStore):
    """S3-compatible object store (AWS S3 / MinIO / any S3 API endpoint).

    Requires optional dependency: pip install boto3
    Activated via env: AGENCY_STORAGE_BACKEND=s3 AGENCY_S3_ENDPOINT=... AGENCY_S3_BUCKET=...
    Credentials follow standard AWS resolution chain (env / config file / IAM role).
    """

    def __init__(self, bucket: str, endpoint_url: str | None = None, prefix: str = "agency/") -> None:
        import boto3  # optional dependency

        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/"
        client_kwargs: dict = {}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        self.client = boto3.client("s3", **client_kwargs)
        self._bucket_exists_or_create()

    def _bucket_exists_or_create(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)

    def _key(self, key: str) -> str:
        clean = key.lstrip("/")
        if ".." in clean.split("/"):
            raise ValueError("invalid storage key")
        return self.prefix + clean

    def put_bytes(self, key: str, data: bytes) -> str:
        self.client.upload_fileobj(io.BytesIO(data), self.bucket, self._key(key))
        return key

    def put_file(self, key: str, src: Path) -> str:
        self.client.upload_file(str(src), self.bucket, self._key(key))
        return key

    def get_bytes(self, key: str) -> bytes:
        buf = io.BytesIO()
        self.client.download_fileobj(self.bucket, self._key(key), buf)
        return buf.getvalue()

    def open(self, key: str) -> BinaryIO:
        return io.BytesIO(self.get_bytes(key))

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except Exception:
            return False

    def stat(self, key: str) -> dict:
        head = self.client.head_object(Bucket=self.bucket, Key=self._key(key))
        return {"size": head["ContentLength"], "etag": head.get("ETag", "").strip('"')}

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))

    def local_path(self, key: str) -> Path:
        raise NotImplementedError("S3ObjectStore has no local path; use open()/get_bytes()")

    def iter_prefix(self, prefix: str) -> Iterator[str]:
        response = self.client.list_objects_v2(Bucket=self.bucket, Prefix=self._key(prefix))
        for obj in response.get("Contents", []):
            full = obj["Key"]
            if full.startswith(self.prefix):
                yield full[len(self.prefix) :]

    def signed_url(self, key: str, expires_in: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": self._key(key)}, ExpiresIn=expires_in
        )


def create_store_from_settings(settings) -> ObjectStore:
    backend = getattr(settings, "storage_backend", "local")
    if backend == "s3":
        return S3ObjectStore(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint or None,
        )
    from .storage import LocalObjectStore

    return LocalObjectStore(settings.storage_dir)


__all__ = ["S3ObjectStore", "create_store_from_settings", "sha256_file"]
