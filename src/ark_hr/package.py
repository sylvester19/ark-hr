"""One zip: English CVs, originals, and the optional review and ranking files."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font

from ark_hr.score import must_met_label, score_percent


def build_zip(entries: list[dict[str, Any]], ranking: list[dict[str, Any]] | None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        reviews: list[str] = []
        for entry in entries:
            archive.writestr(f"Originals/{entry['original_name']}", entry["original"])
            if entry.get("docx"):
                archive.writestr(f"English_CVs/{entry['output_name']}", entry["docx"])
            if entry.get("status") == "Needs review" and entry.get("reason"):
                reviews.append(f"{entry['output_name'] or entry['original_name']}: {entry['reason']}")
            if entry.get("status") == "Failed" and entry.get("reason"):
                reviews.append(f"{entry['original_name']}: {entry['reason']}")
        if reviews:
            archive.writestr("Needs_Review.txt", "\n".join(reviews) + "\n")
        if ranking:
            archive.writestr("Job_Match.xlsx", ranking_workbook(ranking))
    return buffer.getvalue()


def ranking_workbook(ranking: list[dict[str, Any]]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Job match"
    headers = [
        "Rank",
        "Candidate name",
        "Score (0-100)",
        "Must-haves met",
        "Strengths",
        "Gaps",
        "Phone / Email",
        "File",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in ranking:
        sheet.append(
            [
                row["rank"],
                row["name"],
                row["score"],
                row["must_label"],
                row["strengths"],
                row["gaps"],
                row["contact"],
                row["file"],
            ]
        )
        link = sheet.cell(sheet.max_row, 8)
        link.hyperlink = f"English_CVs/{row['file']}"
        link.font = Font(color="0563C1", underline="single")
    payload = io.BytesIO()
    book.save(payload)
    return payload.getvalue()


def rank_rows(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(scored, key=lambda row: (-(row["score"] if row["score"] is not None else -1), row["name"]))
    rows = []
    for index, row in enumerate(ordered, start=1):
        rows.append({**row, "rank": index})
    return rows


def score_from_model(raw: dict[str, Any]) -> tuple[int | None, str, str, str]:
    must = raw.get("must") if isinstance(raw.get("must"), list) else []
    nice = raw.get("nice") if isinstance(raw.get("nice"), list) else []
    return (
        score_percent(must, nice),
        must_met_label(must),
        str(raw.get("strengths") or ""),
        str(raw.get("gaps") or ""),
    )


def loads_checklist(raw: str | None) -> dict[str, list[str]] | None:
    if not raw:
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        return None
    return parsed
