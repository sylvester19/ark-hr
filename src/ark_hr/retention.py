"""Retention is a setting, not a hard-coded lifetime. Deleting removes the files."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ark_hr.db import Database
from ark_hr.storage import Storage


def delete_batches(db: Database, storage: Storage, batch_ids: list[str], actor: str) -> dict:
    file_count = 0
    removed = 0
    for batch_id in batch_ids:
        batch = db.batch(batch_id)
        if not batch:
            continue
        file_count += int(batch["file_count"])
        storage.delete_prefix(f"batches/{batch_id}")
        db.delete_batch(batch_id)
        removed += 1
    if removed:
        db.add_audit(actor, "delete", None if removed != 1 else batch_ids[0], file_count)
    return {"batches": removed, "files": file_count}


def older_than(days: int | None, before: str | None) -> str:
    if before:
        moment = datetime.fromisoformat(before)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.replace(microsecond=0).isoformat()
    if not days or days < 1:
        raise ValueError("Say how old the batches must be.")
    moment = datetime.now(timezone.utc) - timedelta(days=days)
    return moment.replace(microsecond=0).isoformat()
