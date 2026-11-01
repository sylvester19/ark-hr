"""One CV at a time. A failure in one file never stops the batch."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ark_hr.db import Database
from ark_hr.extract import ReadError, convert_doc, extract_docx, extract_pdf
from ark_hr.language import detect_language
from ark_hr.names import english_name, unique_original
from ark_hr.ocr import OcrError, ocr_image, ocr_pdf_pages
from ark_hr.package import build_zip, loads_checklist, rank_rows, score_from_model
from ark_hr.render import render_cv
from ark_hr.schema import normalise_cv, public_cv_for_scoring
from ark_hr.storage import Storage
from ark_hr.translate import ModelError, Translator
from ark_hr.verify import verify_cv

log = logging.getLogger("ark_hr.pipeline")

TERMINAL = {"Done", "Needs review", "Failed"}


def original_key(batch_id: str, file_id: str) -> str:
    return f"batches/{batch_id}/original/{file_id}"


def text_key(batch_id: str, file_id: str) -> str:
    return f"batches/{batch_id}/text/{file_id}.txt"


def json_key(batch_id: str, file_id: str) -> str:
    return f"batches/{batch_id}/json/{file_id}.json"


def docx_key(batch_id: str, file_id: str) -> str:
    return f"batches/{batch_id}/docx/{file_id}.docx"


def zip_key(batch_id: str) -> str:
    return f"batches/{batch_id}/result.zip"


def jd_key(batch_id: str) -> str:
    return f"batches/{batch_id}/job.txt"


def process_file(
    db: Database,
    storage: Storage,
    translator: Translator,
    data_dir: Path,
    phase: int,
    batch_id: str,
    file_id: str,
) -> None:
    row = db.file(file_id)
    if not row:
        return
    db.set_file(file_id, status="Reading", reason=None)
    try:
        raw = storage.get(original_key(batch_id, file_id))
        text, ocr_used = _read(raw, row["original_name"], phase)
    except (ReadError, OcrError) as exc:
        db.set_file(file_id, status="Failed", reason=str(exc), ocr_used=0)
        _maybe_finish(db, storage, translator, data_dir, phase, batch_id)
        return

    language, _code = detect_language(text)
    storage.put(text_key(batch_id, file_id), text.encode("utf-8"))
    db.set_file(file_id, status="Translating", detected_language=language, ocr_used=int(ocr_used))
    try:
        cv = translator.structure(text, language)
        result = verify_cv(text, cv)
        repair = _repair_note(result.reason, cv, language)
        if repair:
            revised = translator.structure(text, language, repair=repair)
            revised = _lock_facts(cv, revised, text)
            result = verify_cv(text, revised)
            leftover = _repair_note("", revised, language)
            if leftover and result.ok:
                result = verify_cv(text, revised)
                result = type(result)(False, [leftover])
            elif leftover and leftover not in result.reason:
                result = type(result)(False, [*result.reasons, leftover])
            cv = revised
    except ModelError as exc:
        db.set_file(file_id, status="Failed", reason=str(exc))
        _maybe_finish(db, storage, translator, data_dir, phase, batch_id)
        return

    db.set_file(file_id, status="Checking")
    status = "Done" if result.ok else "Needs review"
    storage.put(json_key(batch_id, file_id), json.dumps(cv).encode("utf-8"))
    try:
        docx = render_cv(cv, language, ocr_used, data_dir)
    except Exception:
        log.warning("template render failed for file %s", file_id)
        db.set_file(file_id, status="Failed", reason="The English CV could not be written.")
        _maybe_finish(db, storage, translator, data_dir, phase, batch_id)
        return
    storage.put(docx_key(batch_id, file_id), docx)
    db.set_file(file_id, status=status, reason=None if result.ok else result.reason)
    _maybe_finish(db, storage, translator, data_dir, phase, batch_id)


def _in_source(value: str, source: str) -> bool:
    return bool(value) and value.casefold() in source.casefold()


def _keep_named(old: str, new: str, source: str) -> str:
    if _in_source(new, source):
        return new
    if _in_source(old, source):
        return old
    return new or old


def _keep_text(old: str, new: str) -> str:
    return new.strip() if new and new.strip() else (old or "")


def _lock_rows(previous: list, current: list, source: str, named: tuple[str, ...], prose: tuple[str, ...]) -> list:
    locked: list = []
    count = max(len(previous), len(current))
    for index in range(count):
        old = previous[index] if index < len(previous) else {}
        new = current[index] if index < len(current) else {}
        row = dict(new or old)
        for key in named:
            row[key] = _keep_named(str(old.get(key) or ""), str(new.get(key) or ""), source)
        for key in prose:
            row[key] = _keep_text(str(old.get(key) or ""), str(new.get(key) or ""))
        if "bullets" in old or "bullets" in new:
            row["bullets"] = new.get("bullets") or old.get("bullets") or []
        if "items" in old or "items" in new:
            row["items"] = new.get("items") or old.get("items") or []
        locked.append(row)
    return locked


def _lock_facts(previous: dict, current: dict, source: str) -> dict:
    """A retry may translate a company or school name. Put the original spelling back."""
    locked = dict(current)
    for key in ("full_name", "phone", "email", "linkedin", "location"):
        locked[key] = _keep_named(str(previous.get(key) or ""), str(current.get(key) or ""), source)
    locked["target_title"] = _keep_text(str(previous.get("target_title") or ""), str(current.get("target_title") or ""))
    locked["summary"] = _keep_text(str(previous.get("summary") or ""), str(current.get("summary") or ""))
    locked["experience"] = _lock_rows(
        previous.get("experience") or [], current.get("experience") or [], source, ("employer", "location"), ("title",)
    )
    locked["education"] = _lock_rows(
        previous.get("education") or [],
        current.get("education") or [],
        source,
        ("institution", "location"),
        ("qualification",),
    )
    locked["certifications"] = _lock_rows(
        previous.get("certifications") or [],
        current.get("certifications") or [],
        source,
        ("name", "issuer"),
        (),
    )
    locked["skills"] = _lock_rows(previous.get("skills") or [], current.get("skills") or [], source, ("group",), ())
    locked["languages"] = _lock_rows(
        previous.get("languages") or [], current.get("languages") or [], source, (), ("language", "level")
    )
    return locked


def _repair_note(verify_reason: str, cv: dict, language: str) -> str:
    parts = [verify_reason] if verify_reason else []
    if language.casefold() not in {"english", "en"}:
        prose = " ".join(
            part
            for part in (
                cv.get("target_title") or "",
                cv.get("summary") or "",
                " ".join(
                    bullet
                    for job in cv.get("experience") or []
                    for bullet in (job.get("bullets") or [])
                ),
            )
            if part
        )
        if len(prose.split()) >= 6:
            detected, code = detect_language(prose)
            if code not in {"en", "und"} and detected.casefold() != "english":
                parts.append(
                    "Titles, summary, and bullets are still not English. "
                    "Translate them into English. Keep person, company, school, and place names unchanged."
                )
    return " ".join(parts)


def _read(data: bytes, name: str, phase: int) -> tuple[str, bool]:
    lower = name.lower()
    if lower.endswith(".docx"):
        return extract_docx(data), False
    if lower.endswith(".doc"):
        return extract_docx(convert_doc(data)), False
    if lower.endswith(".pdf"):
        text, needs_ocr = extract_pdf(data)
        if needs_ocr and not text.strip():
            return ocr_pdf_pages(data), True
        if needs_ocr and phase >= 2:
            try:
                scanned = ocr_pdf_pages(data)
                text = (text + "\n\n" + scanned).strip()
                return text, True
            except OcrError:
                return text, False
        return text, False
    if lower.endswith((".jpg", ".jpeg", ".png")):
        return ocr_image(data), True
    raise ReadError("This file type is not a CV the tool can read.")


def _maybe_finish(db, storage, translator, data_dir, phase, batch_id: str) -> None:
    files = db.files_for(batch_id)
    if any(row["status"] not in TERMINAL for row in files):
        db.set_batch(batch_id, status="running")
        return
    batch = db.batch(batch_id)
    if not batch:
        return
    if batch["scoring"] and not batch["checklist_confirmed"]:
        db.set_batch(batch_id, status="checklist")
        _write_zip(db, storage, data_dir, batch_id, ranking=None)
        return
    if batch["scoring"] and batch["checklist_confirmed"]:
        _score_batch(db, storage, translator, data_dir, batch_id)
        return
    _write_zip(db, storage, data_dir, batch_id, ranking=None)
    db.set_batch(batch_id, status="done", finished_at=_now())


def score_batch(db, storage, translator, data_dir, batch_id: str) -> None:
    _score_batch(db, storage, translator, data_dir, batch_id)


def _score_batch(db, storage, translator, data_dir, batch_id: str) -> None:
    batch = db.batch(batch_id)
    checklist = loads_checklist(batch.get("checklist_json") if batch else None) or {"must": [], "nice": []}
    scored: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for row in db.files_for(batch_id):
        if row["status"] not in ("Done", "Needs review"):
            continue
        try:
            cv = normalise_cv(json.loads(storage.get(json_key(batch_id, row["id"]))))
        except FileNotFoundError:
            continue
        output_name = row["output_name"] or english_name(cv.get("full_name") or "", row["original_name"], used_names)
        db.set_file(row["id"], output_name=output_name)
        try:
            raw = translator.score_cv(checklist, public_cv_for_scoring(cv))
        except ModelError:
            raw = {"must": [], "nice": [], "strengths": "", "gaps": "Scoring model was not reachable."}
        score, must_label, strengths, gaps = score_from_model(raw)
        db.set_file(row["id"], score=score, score_json=json.dumps(raw))
        contact = " · ".join(part for part in (cv.get("phone") or "", cv.get("email") or "") if part)
        scored.append(
            {
                "name": cv.get("full_name") or row["original_name"],
                "score": score,
                "must_label": must_label,
                "strengths": strengths,
                "gaps": gaps,
                "contact": contact,
                "file": output_name,
            }
        )
    ranking = rank_rows(scored)
    _write_zip(db, storage, data_dir, batch_id, ranking)
    db.set_batch(batch_id, status="done", finished_at=_now())


def _write_zip(db, storage, data_dir, batch_id: str, ranking: list[dict[str, Any]] | None) -> None:
    entries = []
    used_originals: set[str] = set()
    used_names: set[str] = set()
    for row in db.files_for(batch_id):
        original = storage.get(original_key(batch_id, row["id"]))
        original_name = unique_original(row["original_name"], used_originals)
        docx = None
        output_name = row["output_name"]
        if output_name:
            used_names.add(output_name.casefold())
        if row["status"] in ("Done", "Needs review"):
            try:
                cv = json.loads(storage.get(json_key(batch_id, row["id"])))
            except FileNotFoundError:
                cv = {}
            output_name = output_name or english_name(cv.get("full_name") or "", original_name, used_names)
            db.set_file(row["id"], output_name=output_name)
            try:
                docx = storage.get(docx_key(batch_id, row["id"]))
            except FileNotFoundError:
                docx = None
        entries.append(
            {
                "original_name": original_name,
                "original": original,
                "docx": docx,
                "output_name": output_name,
                "status": row["status"],
                "reason": row["reason"],
            }
        )
    storage.put(zip_key(batch_id), build_zip(entries, ranking))


def _now() -> str:
    from ark_hr.db import utcnow

    return utcnow()


def assign_output_names(db: Database, storage: Storage, batch_id: str) -> None:
    used: set[str] = set()
    for row in db.files_for(batch_id):
        if row["output_name"] or row["status"] not in ("Done", "Needs review"):
            if row["output_name"]:
                used.add(row["output_name"].casefold())
            continue
        try:
            cv = json.loads(storage.get(json_key(batch_id, row["id"])))
        except FileNotFoundError:
            cv = {}
        name = english_name(cv.get("full_name") or "", row["original_name"], used)
        db.set_file(row["id"], output_name=name)
