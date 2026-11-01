"""Output file names. The original file name is the fallback. Duplicates get _2, _3."""

from __future__ import annotations

import re

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_stem(value: str) -> str:
    cleaned = INVALID.sub(" ", value).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80] or "CV"


def english_name(candidate: str, fallback: str, used: set[str]) -> str:
    stem = safe_stem(candidate) if candidate.strip() else safe_stem(Path_stem(fallback))
    name = f"{stem}_EN.docx"
    if name.casefold() not in used:
        used.add(name.casefold())
        return name
    number = 2
    while True:
        candidate_name = f"{stem}_{number}_EN.docx"
        if candidate_name.casefold() not in used:
            used.add(candidate_name.casefold())
            return candidate_name
        number += 1


def Path_stem(filename: str) -> str:
    base = filename.replace("\\", "/").split("/")[-1]
    dot = base.rfind(".")
    return base[:dot] if dot > 0 else base


def unique_original(filename: str, used: set[str]) -> str:
    base = filename.replace("\\", "/").split("/")[-1]
    if base.casefold() not in used:
        used.add(base.casefold())
        return base
    stem = Path_stem(base)
    ext = base[len(stem):]
    number = 2
    while True:
        candidate = f"{stem}_{number}{ext}"
        if candidate.casefold() not in used:
            used.add(candidate.casefold())
            return candidate
        number += 1
