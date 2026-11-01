"""Batch records. Candidate CV text is stored as files, not in this database."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  retention_mode TEXT NOT NULL DEFAULT 'forever',
  retention_days INTEGER,
  updated_at TEXT,
  updated_by TEXT
);
CREATE TABLE IF NOT EXISTS batches (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  owner_email TEXT NOT NULL,
  status TEXT NOT NULL,
  file_count INTEGER NOT NULL,
  scoring INTEGER NOT NULL DEFAULT 0,
  checklist_json TEXT,
  checklist_confirmed INTEGER NOT NULL DEFAULT 0,
  retention_mode TEXT NOT NULL,
  retention_days INTEGER,
  retain_until TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  email_sent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL,
  original_name TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  detected_language TEXT,
  status TEXT NOT NULL,
  reason TEXT,
  ocr_used INTEGER NOT NULL DEFAULT 0,
  output_name TEXT,
  score INTEGER,
  score_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL,
  file_id TEXT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  batch_id TEXT,
  file_count INTEGER
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO settings (id, retention_mode, updated_at) VALUES (1, 'forever', ?)",
            (utcnow(),),
        )
        self._conn.commit()

    def _one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def settings(self) -> dict[str, Any]:
        return self._one("SELECT * FROM settings WHERE id = 1") or {}

    def update_settings(self, mode: str, days: int | None, actor: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE settings SET retention_mode = ?, retention_days = ?, updated_at = ?, updated_by = ? WHERE id = 1",
                (mode, days, utcnow(), actor),
            )
            self._conn.commit()

    def add_audit(self, actor: str, action: str, batch_id: str | None, file_count: int | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit (at, actor, action, batch_id, file_count) VALUES (?, ?, ?, ?, ?)",
                (utcnow(), actor, action, batch_id, file_count),
            )
            self._conn.commit()

    def audit_rows(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM audit ORDER BY id DESC LIMIT 500")

    def create_batch(
        self,
        *,
        name: str,
        owner_email: str,
        scoring: bool,
        retention_mode: str,
        retention_days: int | None,
        files: list[tuple[str, str]],
    ) -> str:
        batch_id = new_id()
        now = utcnow()
        retain_until = retention_deadline(now, retention_mode, retention_days)
        with self._lock:
            self._conn.execute(
                """INSERT INTO batches
                   (id, name, owner_email, status, file_count, scoring, retention_mode, retention_days, retain_until, created_at)
                   VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)""",
                (batch_id, name, owner_email, len(files), int(scoring), retention_mode, retention_days, retain_until, now),
            )
            for original_name, content_hash in files:
                file_id = new_id()
                self._conn.execute(
                    """INSERT INTO files
                       (id, batch_id, original_name, content_hash, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'Queued', ?, ?)""",
                    (file_id, batch_id, original_name, content_hash, now, now),
                )
                self._conn.execute(
                    "INSERT INTO jobs (batch_id, file_id, kind, status, created_at) VALUES (?, ?, 'file', 'queued', ?)",
                    (batch_id, file_id, now),
                )
            self._conn.commit()
        return batch_id

    def batch(self, batch_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM batches WHERE id = ?", (batch_id,))

    def files_for(self, batch_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM files WHERE batch_id = ? ORDER BY original_name",
            (batch_id,),
        )

    def file(self, file_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM files WHERE id = ?", (file_id,))

    def list_batches(self, email: str, admin: bool) -> list[dict[str, Any]]:
        if admin:
            return self._all("SELECT * FROM batches ORDER BY created_at DESC")
        return self._all(
            "SELECT * FROM batches WHERE owner_email = ? ORDER BY created_at DESC",
            (email,),
        )

    def set_file(self, file_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utcnow()
        keys = ", ".join(f"{key} = ?" for key in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE files SET {keys} WHERE id = ?",
                (*fields.values(), file_id),
            )
            self._conn.commit()

    def set_batch(self, batch_id: str, **fields: Any) -> None:
        if not fields:
            return
        keys = ", ".join(f"{key} = ?" for key in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE batches SET {keys} WHERE id = ?",
                (*fields.values(), batch_id),
            )
            self._conn.commit()

    def claim_job(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            self._conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (row["id"],))
            self._conn.commit()
            return dict(row)

    def finish_job(self, job_id: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (job_id,))
            self._conn.commit()

    def has_open_jobs(self) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM jobs WHERE status IN ('queued', 'running') LIMIT 1"
        ).fetchone()
        return row is not None

    def snapshot_bytes(self) -> bytes:
        import tempfile

        handle, name = tempfile.mkstemp(suffix=".sqlite")
        os_close = __import__("os").close
        os_close(handle)
        dest_path = Path(name)
        with self._lock:
            dest = sqlite3.connect(dest_path)
            try:
                self._conn.backup(dest)
            finally:
                dest.close()
        try:
            return dest_path.read_bytes()
        finally:
            dest_path.unlink(missing_ok=True)

    def requeue_running(self) -> None:
        with self._lock:
            self._conn.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'")
            self._conn.commit()

    def enqueue(self, batch_id: str, kind: str, file_id: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (batch_id, file_id, kind, status, created_at) VALUES (?, ?, ?, 'queued', ?)",
                (batch_id, file_id, kind, utcnow()),
            )
            self._conn.commit()

    def delete_batch(self, batch_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM jobs WHERE batch_id = ?", (batch_id,))
            self._conn.execute("DELETE FROM files WHERE batch_id = ?", (batch_id,))
            self._conn.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
            self._conn.commit()

    def expired_batch_ids(self, now: str | None = None) -> list[str]:
        moment = now or utcnow()
        rows = self._all(
            "SELECT id FROM batches WHERE retain_until IS NOT NULL AND retain_until <= ?",
            (moment,),
        )
        return [row["id"] for row in rows]

    def batches_older_than(self, moment: str) -> list[str]:
        rows = self._all("SELECT id FROM batches WHERE created_at <= ?", (moment,))
        return [row["id"] for row in rows]


def retention_deadline(created_at: str, mode: str, days: int | None) -> str | None:
    if mode == "forever" or not days:
        return None
    start = datetime.fromisoformat(created_at)
    return (start + timedelta(days=days)).replace(microsecond=0).isoformat()


RETENTION_CHOICES = {
    "forever": None,
    "7": 7,
    "30": 30,
    "90": 90,
    "180": 180,
    "365": 365,
}
