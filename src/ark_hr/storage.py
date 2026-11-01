"""Private file store. Downloads are short-lived links, not public container URLs."""

from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path

from ark_hr.config import Settings

LINK_SECONDS = 15 * 60


class Storage:
    def put(self, key: str, data: bytes) -> None:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def delete_prefix(self, prefix: str) -> None:
        raise NotImplementedError


def _safe_key(key: str) -> Path:
    parts = Path(key).parts
    if not parts or any(part in ("..", "") for part in parts):
        raise ValueError("Invalid storage key.")
    return Path(*parts)


class LocalStorage(Storage):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / _safe_key(key)

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def delete_prefix(self, prefix: str) -> None:
        folder = self._path(prefix)
        if not folder.exists():
            return
        if folder.is_file():
            folder.unlink()
            return
        for child in sorted(folder.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        folder.rmdir()


class AzureBlobStorage(Storage):
    """Private container in UAE North. The connection string is never logged."""

    def __init__(self, connection_string: str, container: str) -> None:
        from azure.storage.blob import BlobServiceClient

        self._client = BlobServiceClient.from_connection_string(connection_string)
        self._container = self._client.get_container_client(container)
        # create_container() with no public access keeps the container private.
        if not self._container.exists():
            self._container.create_container()

    def put(self, key: str, data: bytes) -> None:
        self._container.upload_blob(key, data, overwrite=True)

    def get(self, key: str) -> bytes:
        return self._container.download_blob(key).readall()

    def delete(self, key: str) -> None:
        self._container.delete_blob(key)

    def delete_prefix(self, prefix: str) -> None:
        for blob in self._container.list_blobs(name_starts_with=prefix):
            self._container.delete_blob(blob.name)


def build_storage(settings: Settings) -> Storage:
    if settings.storage == "azure":
        return AzureBlobStorage(settings.azure_connection_string, settings.azure_container)
    return LocalStorage(settings.data_dir / "blobs")


def sign_download(secret: str, batch_id: str, file_id: str, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + LINK_SECONDS)
    payload = f"{batch_id}|{file_id}|{expires}"
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}|{digest}"


def read_download(secret: str, token: str, now: float | None = None) -> tuple[str, str]:
    parts = token.split("|")
    if len(parts) != 4:
        raise ValueError("This download link is not valid.")
    batch_id, file_id, expires, digest = parts
    payload = f"{batch_id}|{file_id}|{expires}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, digest):
        raise ValueError("This download link is not valid.")
    if int(expires) < int(now if now is not None else time.time()):
        raise ValueError("This download link has expired.")
    return batch_id, file_id
