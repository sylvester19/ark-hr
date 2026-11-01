"""Automatic check. No model is used here. A failure is shown to HR word for word."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ark_hr.schema import flatten_cv

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
URL_RE = re.compile(r"https?://[^\s<>)\]]+", re.I)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
NUMBER_RE = re.compile(r"\d{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s()./\-]{6,}\d")
DOB_LINE_RE = re.compile(
    r"(date of birth|birth date|\bdob\b|d\.o\.b|né le|nee le|née le|born on|born in|\bâge\b|\bage\b)",
    re.I,
)


@dataclass
class VerifyResult:
    ok: bool
    reasons: list[str]

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)


def _emails(text: str) -> set[str]:
    return {match.group(0).casefold() for match in EMAIL_RE.finditer(text)}


def _urls(text: str) -> set[str]:
    found: set[str] = set()
    for match in URL_RE.finditer(text):
        found.add(match.group(0).rstrip(".,;").casefold())
    return found


def _years(text: str) -> set[str]:
    return set(YEAR_RE.findall(text))


def _numbers(text: str) -> set[str]:
    return set(NUMBER_RE.findall(text))


def _phone_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for match in PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) >= 8 and not _year_run(digits):
            keys.add(digits)
    return keys


def _year_run(digits: str) -> bool:
    """2014-2016 is two years, not a phone number."""
    if len(digits) % 4:
        return False
    return all(digits[index : index + 4].startswith(("19", "20")) for index in range(0, len(digits), 4))


def _optional_birth_years(source: str) -> set[str]:
    """A birth year is omitted on purpose. A year that also appears on a career line stays required."""
    optional: set[str] = set()
    required_elsewhere: set[str] = set()
    for line in source.splitlines():
        years = set(YEAR_RE.findall(line))
        if not years:
            continue
        if DOB_LINE_RE.search(line):
            optional |= years
        else:
            required_elsewhere |= years
    return optional - required_elsewhere


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _in_source(value: str, source_folded: str) -> bool:
    folded = re.sub(r"\s+", " ", value).strip().casefold()
    return bool(folded) and folded in source_folded


def verify_cv(source_text: str, cv: dict[str, Any]) -> VerifyResult:
    reasons: list[str] = []
    output = flatten_cv(cv)
    source_folded = re.sub(r"\s+", " ", source_text).strip().casefold()

    name = re.sub(r"\s+", " ", str(cv.get("full_name") or "")).strip()
    if not name:
        reasons.append("candidate name was not found")
    elif name.casefold() not in source_folded:
        reasons.append("candidate name does not match the original")

    source_emails = _emails(source_text)
    output_emails = _emails(output)
    for email in sorted(source_emails - output_emails):
        reasons.append(f"email missing in English version: {email}")
    for email in sorted(output_emails - source_emails):
        reasons.append(f"email added that is not in the original: {email}")

    source_phones = _phone_keys(source_text)
    output_digits = re.sub(r"\D", "", output)
    source_digits = re.sub(r"\D", "", source_text)
    for phone in sorted(source_phones):
        if phone not in output_digits:
            reasons.append(f"phone number missing in English version: {phone}")
    for phone in sorted(_phone_keys(output)):
        if phone not in source_digits:
            reasons.append(f"phone number added that is not in the original: {phone}")

    source_urls = _urls(source_text)
    output_urls = _urls(output)
    for url in sorted(source_urls - output_urls):
        reasons.append(f"URL missing in English version: {url}")
    for url in sorted(output_urls - source_urls):
        reasons.append(f"URL added that is not in the original: {url}")

    optional_years = _optional_birth_years(source_text)
    source_years = _years(source_text) - optional_years
    output_years = _years(output)
    for year in sorted(source_years - output_years):
        reasons.append(f"year missing in English version: {year}")
    for year in sorted(output_years - _years(source_text)):
        reasons.append(f"year added that is not in the original: {year}")

    for number in sorted(_numbers(output) - _numbers(source_text)):
        if number not in _years(output):
            reasons.append(f"number added that is not in the original: {number}")

    for row in cv.get("experience") or []:
        employer = str(row.get("employer") or "").strip()
        if employer and not _in_source(employer, source_folded):
            reasons.append(f"employer was changed: {employer}")
    for row in cv.get("education") or []:
        school = str(row.get("institution") or "").strip()
        if school and not _in_source(school, source_folded):
            reasons.append(f"school name was changed: {school}")
    for row in cv.get("certifications") or []:
        issuer = str(row.get("issuer") or "").strip()
        if issuer and not _in_source(issuer, source_folded):
            reasons.append(f"issuer was changed: {issuer}")
    for place in _places(cv):
        if not _in_source(place, source_folded):
            reasons.append(f"place name was changed: {place}")

    source_words = _word_count(source_text)
    output_words = _word_count(output)
    if source_words >= 20:
        ratio = output_words / source_words
        if ratio < 0.6 or ratio > 1.6:
            reasons.append(
                "output length is outside 0.6–1.6× the original "
                f"({output_words} words from {source_words})"
            )

    # De-duplicate repeated phone messages.
    unique: list[str] = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    return VerifyResult(ok=not unique, reasons=unique)


def _places(cv: dict[str, Any]) -> list[str]:
    found: list[str] = []
    header = str(cv.get("location") or "").strip()
    if header:
        found.extend(_place_parts(header))
    for row in cv.get("experience") or []:
        found.extend(_place_parts(str(row.get("location") or "")))
    for row in cv.get("education") or []:
        found.extend(_place_parts(str(row.get("location") or "")))
    return found


def _place_parts(value: str) -> list[str]:
    parts = [part.strip() for part in value.split(",")]
    return [part for part in parts if len(part) >= 3]
