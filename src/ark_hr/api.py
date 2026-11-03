"""ARK HR HTTP API. CV text is never written to logs or error messages."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response

from ark_hr.auth import SESSION, AuthError, exchange_code, login_url, read_session, sign_session
from ark_hr.config import Settings, load_settings
from ark_hr.db import RETENTION_CHOICES, Database, retention_deadline, utcnow
from ark_hr.intake import IntakeError, collect
from ark_hr.pipeline import docx_key, jd_key, json_key, original_key, zip_key
from ark_hr.retention import delete_batches, older_than
from ark_hr.schema import normalise_cv
from ark_hr.score import normalise_checklist
from ark_hr.storage import Storage, build_storage, read_download, sign_download
from ark_hr.translate import ModelError
from ark_hr.worker import start_worker

log = logging.getLogger("ark_hr")
ZIP_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    storage: Storage | None = None,
    translator=None,
    start: bool = True,
) -> FastAPI:
    settings = settings or load_settings()
    settings.validate_for_start()
    _raise_upload_limits()
    app = FastAPI(title="ARK HR – Bulk CV Translation Tool", docs_url=None, redoc_url=None)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": _validation_message(exc)})

    @app.exception_handler(Exception)
    async def unexpected(_request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            raise exc
        log.warning("request failed: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Something went wrong. Try that again."})
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.storage = storage or build_storage(settings)
    if database is None and settings.storage == "azure":
        from ark_hr.runtime_sync import restore_database

        restore_database(app.state.storage, settings.data_dir / "ark-hr.sqlite")
    app.state.db = database or Database(settings.data_dir / "ark-hr.sqlite")
    app.state.translator = translator or _translator(settings)
    app.state.last_purge = ""
    if start:
        start_worker(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "engine": getattr(app.state.translator, "engine", "llm")}

    @app.get("/auth/config")
    def auth_config() -> dict[str, Any]:
        return {
            "microsoft": settings.microsoft_enabled,
            "local": settings.local_login_enabled,
            "phase": settings.phase,
            "title": "ARK HR – Bulk CV Translation Tool",
        }

    @app.get("/auth/login")
    def auth_login() -> dict[str, str]:
        if not settings.microsoft_enabled:
            raise HTTPException(status_code=400, detail="Microsoft sign-in is not configured.")
        state = sign_session(settings, "state@local", "state", "hr")
        return {"url": login_url(settings, state)}

    @app.get("/auth/callback")
    def auth_callback(code: str = "", state: str = "", error: str = "") -> RedirectResponse:
        if error or not code:
            return RedirectResponse(f"{settings.public_url}/login?error=access")
        try:
            read_session(settings, state)
        except AuthError:
            return RedirectResponse(f"{settings.public_url}/login?error=access")
        try:
            person = exchange_code(settings, code)
        except AuthError:
            return RedirectResponse(f"{settings.public_url}/login?error=access")
        response = RedirectResponse(settings.public_url + "/new")
        _set_cookie(response, settings, person["email"], person["name"], person["role"])
        return response

    @app.post("/auth/local")
    def auth_local() -> Response:
        if not settings.local_login_enabled:
            raise HTTPException(status_code=404, detail="Not found.")
        role = settings.local_role if settings.local_role in ("hr", "admin") else "hr"
        response = Response(content=json.dumps({"ok": True}), media_type="application/json")
        _set_cookie(response, settings, settings.local_email, settings.local_name, role)
        return response

    @app.post("/auth/logout")
    def logout() -> Response:
        response = Response(content=json.dumps({"ok": True}), media_type="application/json")
        response.delete_cookie(SESSION, path="/")
        return response

    @app.get("/auth/me")
    def me(request: Request) -> dict[str, Any]:
        user = _user(request)
        return {
            "email": user["sub"],
            "name": user.get("name") or user["sub"],
            "role": user["role"],
            "phase": settings.phase,
        }

    @app.post("/batches")
    async def create_batch(
        request: Request,
        files: list[UploadFile] = File(...),
        name: str = Form(""),
        score: str = Form("false"),
        job_text: str = Form(""),
        job_file: UploadFile | None = File(None),
    ) -> dict[str, Any]:
        user = _user(request)
        payloads: list[tuple[str, bytes]] = []
        for upload in files:
            payloads.append((upload.filename or "cv", await upload.read()))
        try:
            incoming = collect(payloads)
        except IntakeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            log.warning("upload failed: %s", type(exc).__name__)
            raise HTTPException(
                status_code=400,
                detail="Those files could not be read. Use a zip of Word, PDF, or image CVs under 200 MB.",
            ) from exc
        scoring = score.lower() == "true" and settings.phase >= 2
        jd = (job_text or "").strip()
        if job_file is not None and settings.phase >= 2:
            jd_bytes = await job_file.read()
            if len(jd_bytes) > 2 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="The job description is over 2 MB.")
            jd = _job_text(job_file.filename or "job.txt", jd_bytes) or jd
        current = app.state.db.settings()
        mode = current.get("retention_mode") or "forever"
        days = current.get("retention_days")
        batch_name = name.strip() or _default_batch_name()
        batch_id = app.state.db.create_batch(
            name=batch_name,
            owner_email=user["sub"],
            scoring=scoring and bool(jd),
            retention_mode=mode,
            retention_days=days,
            files=[(item.name, item.content_hash) for item in incoming],
        )
        rows = app.state.db.files_for(batch_id)
        by_name = {row["original_name"]: row for row in rows}
        for item in incoming:
            row = by_name.get(item.name)
            if row:
                app.state.storage.put(original_key(batch_id, row["id"]), item.data)
        if jd:
            app.state.storage.put(jd_key(batch_id), jd.encode("utf-8"))
            _prepare_checklist(app, batch_id, jd)
        app.state.db.add_audit(user["sub"], "upload", batch_id, len(incoming))
        from ark_hr.runtime_sync import sync_state

        sync_state(app, force=True)
        return batch_payload(app, batch_id)

    @app.get("/batches")
    def list_batches(request: Request) -> dict[str, Any]:
        user = _user(request)
        rows = app.state.db.list_batches(user["sub"], user["role"] == "admin")
        return {"batches": [_public_batch(app, row) for row in rows]}

    @app.get("/batches/{batch_id}")
    def get_batch(batch_id: str, request: Request) -> dict[str, Any]:
        _owned(request, batch_id)
        return batch_payload(app, batch_id)

    @app.delete("/batches/{batch_id}")
    def remove_batch(batch_id: str, request: Request) -> dict[str, Any]:
        user = _owned(request, batch_id)
        result = delete_batches(app.state.db, app.state.storage, [batch_id], user["sub"])
        return result

    @app.patch("/batches/{batch_id}/retention")
    async def patch_retention(batch_id: str, request: Request) -> dict[str, Any]:
        user = _admin(request)
        _require(app.state.db.batch(batch_id))
        body = await _json_body(request)
        mode, days = _retention_choice(str(body.get("choice") or "forever"), body.get("days"))
        created = app.state.db.batch(batch_id)["created_at"]
        app.state.db.set_batch(
            batch_id,
            retention_mode=mode,
            retention_days=days,
            retain_until=retention_deadline(created, mode, days),
        )
        app.state.db.add_audit(user["sub"], "retention", batch_id, None)
        return batch_payload(app, batch_id)

    @app.put("/batches/{batch_id}/checklist")
    async def put_checklist(batch_id: str, request: Request) -> dict[str, Any]:
        user = _owned(request, batch_id)
        if settings.phase < 2:
            raise HTTPException(status_code=404, detail="Job-match scoring is part of Phase 2.")
        body = await _json_body(request)
        checklist = normalise_checklist(body)
        confirmed = bool(body.get("confirm"))
        app.state.db.set_batch(
            batch_id,
            checklist_json=json.dumps(checklist),
            checklist_confirmed=int(confirmed),
        )
        if confirmed:
            app.state.db.enqueue(batch_id, "score")
        return batch_payload(app, batch_id)

    @app.post("/batches/{batch_id}/link")
    def batch_link(batch_id: str, request: Request) -> dict[str, Any]:
        user = _owned(request, batch_id)
        batch = app.state.db.batch(batch_id)
        app.state.db.add_audit(user["sub"], "download", batch_id, batch["file_count"] if batch else None)
        token = sign_download(settings.secret, batch_id, "*")
        return {"url": f"/d/{token}", "minutes": 15}

    @app.post("/batches/{batch_id}/files/{file_id}/link")
    def file_link(batch_id: str, file_id: str, request: Request) -> dict[str, Any]:
        user = _owned(request, batch_id)
        row = app.state.db.file(file_id)
        if not row or row["batch_id"] != batch_id:
            raise HTTPException(status_code=404, detail="That file is not in this batch.")
        app.state.db.add_audit(user["sub"], "download", batch_id, 1)
        token = sign_download(settings.secret, batch_id, file_id)
        return {"url": f"/d/{token}", "minutes": 15}

    @app.get("/d/{token}")
    def download(token: str) -> Response:
        try:
            batch_id, file_id = read_download(settings.secret, token)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        batch = app.state.db.batch(batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="This download is no longer available.")
        if file_id == "*":
            try:
                data = app.state.storage.get(zip_key(batch_id))
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail="The zip is not ready yet.") from exc
            filename = "ARK-HR_" + ZIP_NAME.sub("", batch["name"]).strip() + ".zip"
            media = "application/zip"
        else:
            row = app.state.db.file(file_id)
            if not row or not row.get("output_name"):
                raise HTTPException(status_code=404, detail="The English CV is not ready yet.")
            try:
                data = app.state.storage.get(docx_key(batch_id, file_id))
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail="The English CV is not ready yet.") from exc
            filename = row["output_name"]
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return Response(
            content=data,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/settings")
    def get_settings(request: Request) -> dict[str, Any]:
        _admin(request)
        current = app.state.db.settings()
        return {
            "retention_mode": current.get("retention_mode"),
            "retention_days": current.get("retention_days"),
            "choices": ["forever", "7", "30", "90", "180", "365", "custom"],
        }

    @app.put("/settings")
    async def put_settings(request: Request) -> dict[str, Any]:
        user = _admin(request)
        if settings.phase < 2:
            raise HTTPException(status_code=404, detail="Retention settings are part of Phase 2.")
        body = await _json_body(request)
        mode, days = _retention_choice(str(body.get("choice") or "forever"), body.get("days"))
        app.state.db.update_settings(mode, days, user["sub"])
        return {"ok": True, "retention_mode": mode, "retention_days": days}

    @app.post("/settings/purge")
    async def purge(request: Request) -> dict[str, Any]:
        user = _admin(request)
        if settings.phase < 2:
            raise HTTPException(status_code=404, detail="Bulk delete is part of Phase 2.")
        body = await _json_body(request)
        try:
            moment = older_than(body.get("days"), body.get("before"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ids = app.state.db.batches_older_than(moment)
        files = 0
        for batch_id in ids:
            batch = app.state.db.batch(batch_id)
            files += int(batch["file_count"]) if batch else 0
        if not body.get("confirm"):
            return {"batches": len(ids), "files": files, "confirm": False}
        return delete_batches(app.state.db, app.state.storage, ids, user["sub"])

    @app.get("/audit")
    def audit(request: Request) -> dict[str, Any]:
        _admin(request)
        if settings.phase < 2:
            raise HTTPException(status_code=404, detail="The audit log screen is part of Phase 2.")
        return {"rows": app.state.db.audit_rows()}

    return app


def _raise_upload_limits() -> None:
    """Starlette keeps a non-file form field in memory and rejects it past 1 MB.

    A multi-file upload whose part headers are damaged would otherwise fail
    before the 200 MB batch check can explain the problem.
    """
    from starlette.formparsers import MultiPartParser

    MultiPartParser.max_part_size = 210 * 1024 * 1024


def _validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    for item in errors:
        kind = str(item.get("type") or "")
        message = str(item.get("msg") or "")
        if kind == "json_invalid" or "json" in message.casefold():
            return "That request was not understood. Refresh the page and try again."
    if errors:
        message = str(errors[0].get("msg") or "").strip()
        if message:
            return message
    return "The request was not valid."


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="That request was not understood. Refresh the page and try again.",
        ) from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="That request was not understood. Refresh the page and try again.")
    return body


def _translator(settings: Settings):
    from ark_hr.translate import build_translator

    return build_translator(settings)


def _set_cookie(response: Response, settings: Settings, email: str, name: str, role: str) -> None:
    response.set_cookie(
        SESSION,
        sign_session(settings, email, name, role),
        httponly=True,
        samesite="lax",
        secure=settings.is_prod,
        path="/",
        max_age=8 * 60 * 60,
    )


def _user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in with Microsoft.")
    try:
        return read_session(request.app.state.settings, token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _admin(request: Request) -> dict[str, Any]:
    user = _user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only an ARK HR admin can do that.")
    return user


def _owned(request: Request, batch_id: str) -> dict[str, Any]:
    user = _user(request)
    batch = request.app.state.db.batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="That batch does not exist.")
    if user["role"] != "admin" and batch["owner_email"] != user["sub"]:
        raise HTTPException(status_code=404, detail="That batch does not exist.")
    return user


def _require(batch: dict | None) -> dict:
    if not batch:
        raise HTTPException(status_code=404, detail="That batch does not exist.")
    return batch


def _retention_choice(choice: str, custom_days: Any) -> tuple[str, int | None]:
    if choice == "custom":
        try:
            days = int(custom_days)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Enter a number of days.") from exc
        if days < 1 or days > 3650:
            raise HTTPException(status_code=400, detail="Retention must be between 1 and 3650 days.")
        return "days", days
    if choice == "forever":
        return "forever", None
    if choice not in RETENTION_CHOICES or RETENTION_CHOICES[choice] is None:
        raise HTTPException(status_code=400, detail="Choose a retention period from the list.")
    return "days", RETENTION_CHOICES[choice]


def _default_batch_name() -> str:
    return "Batch " + datetime.now().strftime("%Y-%m-%d %H:%M")


def _job_text(filename: str, data: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".txt"):
        return data.decode("utf-8", errors="replace")
    from ark_hr.extract import ReadError, extract_docx, extract_pdf

    try:
        if lower.endswith(".docx"):
            return extract_docx(data)
        if lower.endswith(".pdf"):
            text, _needs = extract_pdf(data)
            return text
    except ReadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return data.decode("utf-8", errors="replace")


def _prepare_checklist(app: FastAPI, batch_id: str, jd: str) -> None:
    try:
        checklist = app.state.translator.requirements(jd)
    except ModelError:
        checklist = {"must": [], "nice": []}
    app.state.db.set_batch(batch_id, checklist_json=json.dumps(checklist), checklist_confirmed=0)


def batch_payload(app: FastAPI, batch_id: str) -> dict[str, Any]:
    batch = _require(app.state.db.batch(batch_id))
    files = app.state.db.files_for(batch_id)
    return {**_public_batch(app, batch), "files": [_public_file(row) for row in files], "ranking": _ranking(app, batch_id, files)}


def _public_batch(app: FastAPI, batch: dict[str, Any]) -> dict[str, Any]:
    files = app.state.db.files_for(batch["id"])
    done = sum(1 for row in files if row["status"] in ("Done", "Needs review", "Failed"))
    checklist = None
    if batch.get("checklist_json"):
        checklist = json.loads(batch["checklist_json"])
    return {
        "id": batch["id"],
        "name": batch["name"],
        "owner_email": batch["owner_email"],
        "status": batch["status"],
        "file_count": batch["file_count"],
        "done_count": done,
        "scoring": bool(batch["scoring"]),
        "checklist": checklist,
        "checklist_confirmed": bool(batch["checklist_confirmed"]),
        "retention_mode": batch["retention_mode"],
        "retention_days": batch["retention_days"],
        "retain_until": batch["retain_until"],
        "created_at": batch["created_at"],
        "finished_at": batch["finished_at"],
        "eta_seconds": _eta(files),
    }


def _public_file(row: dict[str, Any]) -> dict[str, Any]:
    score_detail = None
    if row.get("score_json"):
        try:
            score_detail = json.loads(row["score_json"])
        except json.JSONDecodeError:
            score_detail = None
    return {
        "id": row["id"],
        "original_name": row["original_name"],
        "detected_language": row["detected_language"],
        "status": row["status"],
        "reason": row["reason"],
        "ocr_used": bool(row["ocr_used"]),
        "output_name": row["output_name"],
        "score": row["score"],
        "strengths": (score_detail or {}).get("strengths"),
        "gaps": (score_detail or {}).get("gaps"),
    }


def _ranking(app: FastAPI, batch_id: str, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in files:
        if row["score"] is None:
            continue
        name = row["output_name"] or row["original_name"]
        try:
            cv = normalise_cv(json.loads(app.state.storage.get(json_key(batch_id, row["id"]))))
            if cv.get("full_name"):
                name = cv["full_name"]
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        detail = {}
        if row.get("score_json"):
            try:
                detail = json.loads(row["score_json"])
            except json.JSONDecodeError:
                detail = {}
        from ark_hr.score import must_met_label

        rows.append(
            {
                "name": name,
                "score": row["score"],
                "must_label": must_met_label(detail.get("must") or []),
                "strengths": detail.get("strengths") or "",
                "gaps": detail.get("gaps") or "",
                "file": row["output_name"],
                "file_id": row["id"],
            }
        )
    rows.sort(key=lambda item: (-(item["score"] if item["score"] is not None else -1), item["name"]))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def _eta(files: list[dict[str, Any]]) -> int | None:
    finished = [row for row in files if row["status"] in ("Done", "Needs review", "Failed")]
    waiting = [row for row in files if row["status"] not in ("Done", "Needs review", "Failed")]
    if not finished or not waiting:
        return None
    durations = []
    for row in finished:
        try:
            start = datetime.fromisoformat(row["created_at"])
            end = datetime.fromisoformat(row["updated_at"])
            durations.append(max((end - start).total_seconds(), 1))
        except ValueError:
            continue
    if not durations:
        return None
    return int(sum(durations) / len(durations) * len(waiting))


def main() -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=3000, log_level="info")


if __name__ == "__main__":
    main()
