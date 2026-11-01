"""English CV JSON. Fields the template must never carry are not in this schema."""

from __future__ import annotations

import re
from typing import Any

CV_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "full_name": {"type": "string"},
        "target_title": {"type": "string"},
        "phone": {"type": "string"},
        "email": {"type": "string"},
        "location": {"type": "string"},
        "linkedin": {"type": "string"},
        "summary": {"type": "string"},
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "employer": {"type": "string"},
                    "location": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "employer", "location", "start", "end", "bullets"],
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "qualification": {"type": "string"},
                    "institution": {"type": "string"},
                    "location": {"type": "string"},
                    "year": {"type": "string"},
                },
                "required": ["qualification", "institution", "location", "year"],
            },
        },
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "group": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["group", "items"],
            },
        },
        "languages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "language": {"type": "string"},
                    "level": {"type": "string"},
                },
                "required": ["language", "level"],
            },
        },
        "certifications": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "issuer": {"type": "string"},
                    "year": {"type": "string"},
                },
                "required": ["name", "issuer", "year"],
            },
        },
        "other": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "full_name",
        "target_title",
        "phone",
        "email",
        "location",
        "linkedin",
        "summary",
        "experience",
        "education",
        "skills",
        "languages",
        "certifications",
        "other",
    ],
}

SENSITIVE_LINE = (
    "date of birth",
    "birth date",
    "dob",
    "d.o.b",
    "né le",
    "nee le",
    "née le",
    "born on",
    "born in",
    "age",
    "âge",
    "years old",
    "marital",
    "married",
    "single",
    "divorced",
    "situation familiale",
    "religion",
    "nationality",
    "nationalité",
    "citoyenneté",
    "citizenship",
    "gender",
    "sexe",
    "photo",
)


def empty_cv() -> dict[str, Any]:
    return {
        "full_name": "",
        "target_title": "",
        "phone": "",
        "email": "",
        "location": "",
        "linkedin": "",
        "summary": "",
        "experience": [],
        "education": [],
        "skills": [],
        "languages": [],
        "certifications": [],
        "other": [],
    }


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _list_of_dicts(value: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return rows
    for item in value:
        if not isinstance(item, dict):
            continue
        row = {key: _text(item.get(key)) for key in keys if key != "bullets" and key != "items"}
        if "bullets" in keys:
            bullets = item.get("bullets")
            row["bullets"] = [_text(b) for b in bullets if _text(b)] if isinstance(bullets, list) else []
        if "items" in keys:
            items = item.get("items")
            row["items"] = [_text(b) for b in items if _text(b)] if isinstance(items, list) else []
        if any(row.get(key) for key in keys):
            rows.append(row)
    return rows


def _sensitive(line: str) -> bool:
    folded = line.casefold()
    for token in SENSITIVE_LINE:
        if len(token) <= 4:
            if re.search(rf"\b{re.escape(token)}\b", folded):
                return True
        elif token in folded:
            return True
    return False


def normalise_cv(raw: Any) -> dict[str, Any]:
    """Drop unknown fields and personal data the template must not carry."""
    source = raw if isinstance(raw, dict) else {}
    cv = empty_cv()
    for key in ("full_name", "target_title", "phone", "email", "location", "linkedin", "summary"):
        cv[key] = _text(source.get(key))
    cv["experience"] = _list_of_dicts(
        source.get("experience"),
        ("title", "employer", "location", "start", "end", "bullets"),
    )
    cv["education"] = _list_of_dicts(
        source.get("education"),
        ("qualification", "institution", "location", "year"),
    )
    cv["skills"] = _list_of_dicts(source.get("skills"), ("group", "items"))
    cv["languages"] = _list_of_dicts(source.get("languages"), ("language", "level"))
    cv["certifications"] = _list_of_dicts(
        source.get("certifications"),
        ("name", "issuer", "year"),
    )
    other = source.get("other")
    if isinstance(other, list):
        cv["other"] = [_text(item) for item in other if _text(item) and not _sensitive(_text(item))]
    if _sensitive(cv["summary"]):
        cv["summary"] = ""
    return cv


def public_cv_for_scoring(cv: dict[str, Any]) -> dict[str, Any]:
    """The scoring model never sees name or personal attributes."""
    hidden = {"full_name", "phone", "email", "linkedin"}
    payload = {key: value for key, value in cv.items() if key not in hidden}
    payload["other"] = [line for line in payload.get("other", []) if not _sensitive(line)]
    return payload


def flatten_cv(cv: dict[str, Any]) -> str:
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            if value.strip():
                parts.append(value.strip())
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(cv)
    return "\n".join(parts)
