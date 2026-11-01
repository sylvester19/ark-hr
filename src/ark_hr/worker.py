"""Background worker. Closing the browser does not stop it."""

from __future__ import annotations

import logging
import threading
import time

from ark_hr.db import utcnow
from ark_hr.pipeline import process_file, score_batch

log = logging.getLogger("ark_hr.worker")


def step(app) -> bool:
    job = app.state.db.claim_job()
    if not job:
        _purge_expired(app)
        return False
    try:
        if job["kind"] == "file":
            process_file(
                app.state.db,
                app.state.storage,
                app.state.translator,
                app.state.settings.data_dir,
                app.state.settings.phase,
                job["batch_id"],
                job["file_id"],
            )
            _notify_if_ready(app, job["batch_id"])
        elif job["kind"] == "score":
            score_batch(
                app.state.db,
                app.state.storage,
                app.state.translator,
                app.state.settings.data_dir,
                job["batch_id"],
            )
            _notify_if_ready(app, job["batch_id"])
    except Exception:
        log.warning("job %s failed", job["id"])
        if job.get("file_id"):
            app.state.db.set_file(job["file_id"], status="Failed", reason="This file could not be processed.")
    finally:
        app.state.db.finish_job(job["id"])
    return True


def _notify_if_ready(app, batch_id: str) -> None:
    batch = app.state.db.batch(batch_id)
    if not batch or batch["status"] != "done" or batch["email_sent"] or app.state.settings.phase < 2:
        return
    from ark_hr.mail import send_ready
    from ark_hr.storage import sign_download

    token = sign_download(app.state.settings.secret, batch_id, "*")
    link = f"{app.state.settings.public_url}/d/{token}"
    try:
        sent = send_ready(app.state.settings, batch["owner_email"], link)
    except Exception:
        log.info("batch-ready email skipped for batch %s", batch_id)
        sent = False
    if sent:
        app.state.db.set_batch(batch_id, email_sent=1)


def _purge_expired(app) -> None:
    now = utcnow()
    last = getattr(app.state, "last_purge", "")
    if last[:10] == now[:10]:
        return
    app.state.last_purge = now
    from ark_hr.retention import delete_batches

    delete_batches(app.state.db, app.state.storage, app.state.db.expired_batch_ids(now), "daily job")


def start_worker(app) -> None:
    app.state.db.requeue_running()

    def loop() -> None:
        while not getattr(app.state, "stop_worker", False):
            worked = False
            try:
                worked = step(app)
            except Exception:
                log.warning("worker step failed")
            from ark_hr.runtime_sync import sync_state

            sync_state(app, force=worked)
            if not worked:
                time.sleep(0.5)

    thread = threading.Thread(target=loop, name="ark-hr-worker", daemon=True)
    thread.start()
    app.state.worker = thread
