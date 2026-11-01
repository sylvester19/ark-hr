"""Keep the database and the scale signal alive across a scale-to-zero restart."""

from __future__ import annotations

import logging
import os
import time

log = logging.getLogger("ark_hr.sync")

META_KEY = "meta/ark-hr.sqlite"


def restore_database(storage, path) -> None:
    try:
        data = storage.get(META_KEY)
    except Exception:
        return
    if not data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def sync_state(app, *, force: bool = False) -> None:
    settings = app.state.settings
    if settings.storage != "azure":
        return
    now = time.time()
    if not force and now - getattr(app.state, "last_sync", 0) < 5:
        return
    app.state.last_sync = now
    try:
        app.state.storage.put(META_KEY, app.state.db.snapshot_bytes())
    except Exception:
        log.warning("could not store the batch database")
    queue = os.environ.get("ARK_HR_QUEUE", "").strip()
    if not queue:
        return
    try:
        from ark_hr.scale_queue import ScaleQueue

        holder = ScaleQueue(settings.azure_connection_string, queue)
        if app.state.db.has_open_jobs():
            holder.hold()
        else:
            holder.release()
    except Exception:
        log.warning("could not update the scale queue")
