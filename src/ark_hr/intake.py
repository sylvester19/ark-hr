"""Safe unzip. One bad entry is skipped. A zip bomb or a path escape is rejected."""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass

ALLOWED = {".docx", ".doc", ".pdf", ".jpg", ".jpeg", ".png"}
MAX_FILES = 100
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_UNCOMPRESSED = 500 * 1024 * 1024


@dataclass
class Incoming:
    name: str
    data: bytes
    content_hash: str


class IntakeError(Exception):
    pass


def _extension(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot >= 0 else ""


def _safe_name(name: str) -> str:
    cleaned = name.replace("\\", "/").strip()
    if not cleaned or cleaned.endswith("/"):
        raise IntakeError("The upload contains an empty file name.")
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise IntakeError("The upload contains a path that leaves the batch folder.")
    base = parts[-1]
    if base.startswith(".") or base.startswith("~$"):
        raise IntakeError("skip-hidden")
    if "__MACOSX" in parts or base == "Thumbs.db" or base.lower() == "desktop.ini":
        raise IntakeError("skip-hidden")
    if _extension(base) not in ALLOWED:
        raise IntakeError("skip-type")
    return base


def _accept(name: str, data: bytes, seen: set[str], names: set[str], accepted: list[Incoming]) -> None:
    from ark_hr.names import unique_original

    try:
        safe = _safe_name(name)
    except IntakeError as exc:
        if str(exc) in ("skip-hidden", "skip-type"):
            return
        raise
    digest = hashlib.sha256(data).hexdigest()
    if digest in seen:
        return
    seen.add(digest)
    accepted.append(Incoming(name=unique_original(safe, names), data=data, content_hash=digest))


def collect(files: list[tuple[str, bytes]]) -> list[Incoming]:
    total = sum(len(data) for _, data in files)
    if total > MAX_UPLOAD_BYTES:
        raise IntakeError("This batch is over the 200 MB limit.")
    if total == 0:
        raise IntakeError("Add at least one CV.")

    accepted: list[Incoming] = []
    seen: set[str] = set()
    names: set[str] = set()
    for name, data in files:
        if name.lower().endswith(".zip") and not name.lower().endswith(".docx"):
            _unzip(data, seen, names, accepted)
            continue
        _accept(name, data, seen, names, accepted)

    if not accepted:
        raise IntakeError("None of the files are Word, PDF, or image CVs.")
    if len(accepted) > MAX_FILES:
        raise IntakeError("A batch can hold at most 100 CVs.")
    return accepted


def _unzip(data: bytes, seen: set[str], names: set[str], accepted: list[Incoming]) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise IntakeError("The zip file could not be opened.") from exc
    uncompressed = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        if info.file_size > MAX_UNCOMPRESSED:
            raise IntakeError("The unzipped batch is over the 500 MB limit.")
        try:
            payload = archive.read(info)
        except RuntimeError as exc:
            raise IntakeError("The zip file could not be read.") from exc
        uncompressed += len(payload)
        if uncompressed > MAX_UNCOMPRESSED:
            raise IntakeError("The unzipped batch is over the 500 MB limit.")
        _accept(info.filename, payload, seen, names, accepted)
        if len(accepted) > MAX_FILES:
            raise IntakeError("A batch can hold at most 100 CVs.")
