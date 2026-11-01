"""Structure a CV on this PC. Prose is translated locally. Names and contacts are copied."""

from __future__ import annotations

import re
from typing import Any, Callable

from ark_hr.schema import empty_cv, normalise_cv
from ark_hr.verify import EMAIL_RE, PHONE_RE, URL_RE

HEADINGS = {
    "profil": "summary",
    "profile": "summary",
    "professional summary": "summary",
    "summary": "summary",
    "a propos": "summary",
    "à propos": "summary",
    "experience": "experience",
    "expérience": "experience",
    "expérience professionnelle": "experience",
    "work experience": "experience",
    "parcours professionnel": "experience",
    "formation": "education",
    "education": "education",
    "études": "education",
    "etudes": "education",
    "compétences": "skills",
    "competences": "skills",
    "skills": "skills",
    "langues": "languages",
    "languages": "languages",
    "certifications": "certs",
    "certifications and licences": "certs",
    "licences": "certs",
    "permis": "certs",
}

MONTHS = {
    "janvier": "January",
    "février": "February",
    "fevrier": "February",
    "mars": "March",
    "avril": "April",
    "mai": "May",
    "juin": "June",
    "juillet": "July",
    "août": "August",
    "aout": "August",
    "septembre": "September",
    "octobre": "October",
    "novembre": "November",
    "décembre": "December",
    "decembre": "December",
    "janeiro": "January",
    "fevereiro": "February",
    "março": "March",
    "marco": "March",
    "abril": "April",
    "maio": "May",
    "junho": "June",
    "julho": "July",
    "agosto": "August",
    "setembro": "September",
    "outubro": "October",
    "novembro": "November",
    "dezembro": "December",
    "enero": "January",
    "febrero": "February",
    "marzo": "March",
    "mayo": "May",
    "junio": "June",
    "julio": "July",
    "agosto": "August",
    "septiembre": "September",
    "octubre": "October",
    "noviembre": "November",
    "diciembre": "December",
    "januar": "January",
    "februar": "February",
    "märz": "March",
    "marz": "March",
    "juni": "June",
    "juli": "July",
    "oktober": "October",
    "dezember": "December",
    "présent": "Present",
    "present": "Present",
    "aujourd'hui": "Present",
    "actuel": "Present",
    "current": "Present",
    "now": "Present",
}

LEVELS = {
    "natif": "native",
    "native": "native",
    "maternelle": "native",
    "courant": "fluent",
    "courante": "fluent",
    "fluent": "fluent",
    "bilingue": "bilingual",
    "intermédiaire": "intermediate",
    "intermediaire": "intermediate",
    "débutant": "beginner",
    "debutant": "beginner",
    "notions": "basic",
    "básico": "basic",
    "basico": "basic",
    "avançado": "advanced",
    "avancado": "advanced",
}


def structure_cv(source_text: str, language_code: str, translate: Callable[[str, str], str]) -> dict[str, Any]:
    lines = [line.strip() for line in source_text.splitlines()]
    sections = _sections(lines)
    cv = empty_cv()
    header = sections.get("header", [])
    cv["full_name"] = _name(header)
    cv["email"] = _first(EMAIL_RE, source_text)
    cv["phone"] = _first(PHONE_RE, source_text)
    cv["linkedin"] = _first(URL_RE, source_text).rstrip(".,;")
    cv["location"] = _location(header)
    cv["target_title"] = _translate(_title(header, cv), language_code, translate)
    cv["summary"] = _translate(" ".join(sections.get("summary", [])), language_code, translate)
    cv["experience"] = [_role(block, language_code, translate) for block in _blocks(sections.get("experience", []))]
    cv["education"] = [_school(line, language_code, translate) for line in sections.get("education", []) if line]
    cv["skills"] = _skills(sections.get("skills", []), language_code, translate)
    cv["languages"] = [_language(line, language_code, translate) for line in sections.get("languages", []) if line]
    cv["certifications"] = [_certificate(line) for line in sections.get("certs", []) if line]
    cv["other"] = [
        _translate(line, language_code, translate)
        for line in sections.get("other", [])
        if line and not _contact_line(line)
    ]
    cv["experience"] = [row for row in cv["experience"] if any(row.values())]
    cv["education"] = [row for row in cv["education"] if any(row.values())]
    cv["languages"] = [row for row in cv["languages"] if row.get("language")]
    cv["certifications"] = [row for row in cv["certifications"] if row.get("name") or row.get("issuer")]
    return normalise_cv(cv)


def _sections(lines: list[str]) -> dict[str, list[str]]:
    current = "header"
    grouped: dict[str, list[str]] = {current: []}
    for raw in lines:
        key = HEADINGS.get(raw.casefold().strip(" :"))
        if key:
            current = key
            grouped.setdefault(current, [])
            continue
        if not raw or _personal(raw):
            continue
        if re.match(r"permis\b", raw, re.I):
            grouped.setdefault("certs", []).append(raw)
            continue
        grouped.setdefault(current, []).append(raw)
    return grouped


def _name(header: list[str]) -> str:
    for line in header:
        if _contact_line(line):
            continue
        if HEADINGS.get(line.casefold()):
            continue
        return line
    return ""


def _title(header: list[str], cv: dict[str, Any]) -> str:
    seen_name = False
    for line in header:
        if line == cv["full_name"]:
            seen_name = True
            continue
        if not seen_name or _contact_line(line) or line == cv["location"]:
            continue
        return line
    return ""


def _location(header: list[str]) -> str:
    for line in header:
        if "," in line and not _contact_line(line) and not any(char.isdigit() for char in line[:4]):
            return line
    return ""


def _personal(line: str) -> bool:
    folded = line.casefold()
    markers = (
        "date of birth",
        "né le",
        "nee le",
        "née le",
        "born on",
        "born in",
        "nationalit",
        "religion",
        "marital",
        "situation familiale",
        "married",
        "âge",
    )
    return any(marker in folded for marker in markers)


def _contact_line(line: str) -> bool:
    folded = line.casefold()
    return bool(EMAIL_RE.search(line) or PHONE_RE.search(line) or URL_RE.search(line) or folded.startswith(("téléphone", "telephone", "email", "e-mail", "tel", "mobile")))


def _first(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(0).strip() if match else ""


def _blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if current and _looks_like_new_role(line):
            blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _looks_like_new_role(line: str) -> bool:
    return "—" in line or " - " in line or " – " in line


def _role(block: list[str], language_code: str, translate: Callable[[str, str], str]) -> dict[str, Any]:
    title = ""
    employer = ""
    location = ""
    start = ""
    end = ""
    bullets: list[str] = []
    for index, line in enumerate(block):
        if index == 0 and _looks_like_new_role(line):
            title, employer, location = _split_role(line)
            continue
        if not start and _looks_like_dates(line):
            start, end = _split_dates(line)
            continue
        bullets.append(_translate(line, language_code, translate))
    return {
        "title": _translate(title, language_code, translate),
        "employer": employer,
        "location": location,
        "start": _dates_to_english(start),
        "end": _dates_to_english(end),
        "bullets": [bullet for bullet in bullets if bullet],
    }


def _split_role(line: str) -> tuple[str, str, str]:
    parts = re.split(r"\s+[—–-]\s+", line, maxsplit=1)
    title = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""
    if "," in rest:
        employer, location = rest.split(",", 1)
        return title, employer.strip(), location.strip()
    return title, rest, ""


def _looks_like_dates(line: str) -> bool:
    folded = line.casefold()
    return bool(re.search(r"\b(?:19|20)\d{2}\b", line)) and any(token in folded for token in ("–", "—", "-", "to", "au", "présent", "present"))


def _split_dates(line: str) -> tuple[str, str]:
    parts = re.split(r"\s+[–—-]\s+|\s+\bto\b\s+|\s+\bau\b\s+", line, maxsplit=1)
    if len(parts) == 1:
        return parts[0].strip(), ""
    return parts[0].strip(), parts[1].strip()


def _dates_to_english(value: str) -> str:
    words = []
    for word in value.split():
        words.append(MONTHS.get(word.casefold().strip(".,"), word))
    return " ".join(words)


def _school(line: str, language_code: str, translate: Callable[[str, str], str]) -> dict[str, str]:
    year = ""
    year_match = re.search(r"\b(?:19|20)\d{2}\b", line)
    if year_match:
        year = year_match.group(0)
        line = (line[: year_match.start()] + line[year_match.end() :]).strip(" ,.-")
    parts = re.split(r"\s+[—–-]\s+", line, maxsplit=1)
    qualification = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""
    institution, location = rest, ""
    if "," in rest:
        institution, location = [piece.strip() for piece in rest.split(",", 1)]
    return {
        "qualification": _translate(qualification, language_code, translate),
        "institution": institution,
        "location": location,
        "year": year,
    }


def _skills(lines: list[str], language_code: str, translate: Callable[[str, str], str]) -> list[dict[str, Any]]:
    items = [_translate(line, language_code, translate) for line in lines if line]
    if not items:
        return []
    return [{"group": "", "items": items}]


def _language(line: str, language_code: str, translate: Callable[[str, str], str]) -> dict[str, str]:
    parts = re.split(r"\s+[—–:-]\s+", line, maxsplit=1)
    name = parts[0].strip()
    level = parts[1].strip() if len(parts) > 1 else ""
    mapped = LEVELS.get(level.casefold(), "")
    return {
        "language": _translate(name, language_code, translate),
        "level": mapped or _translate(level, language_code, translate),
    }


def _certificate(line: str) -> dict[str, str]:
    year = ""
    year_match = re.search(r"\b(?:19|20)\d{2}\b", line)
    if year_match:
        year = year_match.group(0)
        line = (line[: year_match.start()] + line[year_match.end() :]).strip(" ,.-")
    parts = re.split(r"\s+[—–-]\s+", line, maxsplit=1)
    return {"name": parts[0].strip(), "issuer": parts[1].strip() if len(parts) > 1 else "", "year": year}


def _translate(text: str, language_code: str, translate: Callable[[str, str], str]) -> str:
    cleaned = text.strip()
    if not cleaned or language_code in ("en", "und", ""):
        return cleaned
    masked, tokens = _mask(cleaned)
    translated = translate(masked, language_code).strip() or cleaned
    for placeholder, token in tokens:
        translated = translated.replace(placeholder, token)
    return translated


def _mask(text: str) -> tuple[str, list[tuple[str, str]]]:
    tokens: list[tuple[str, str]] = []

    def swap(match: re.Match[str]) -> str:
        placeholder = f"__KEEP{len(tokens)}__"
        tokens.append((placeholder, match.group(0)))
        return placeholder

    masked = EMAIL_RE.sub(swap, text)
    masked = URL_RE.sub(swap, masked)
    masked = PHONE_RE.sub(swap, masked)
    return masked, tokens


def local_translate(text: str, language_code: str) -> str:
    """Argos Translate, installed on this PC. No text is sent to a cloud API."""
    try:
        import argostranslate.translate
    except ImportError:
        return text
    try:
        return argostranslate.translate.translate(text, language_code, "en")
    except Exception:
        return text


def keyword_requirements(job_text: str) -> dict[str, list[str]]:
    must: list[str] = []
    nice: list[str] = []
    for line in job_text.splitlines():
        cleaned = line.strip(" -\t•")
        if not cleaned:
            continue
        folded = cleaned.casefold()
        if any(word in folded for word in ("must", "required", "exigé", "exige", "obligatoire")):
            must.append(cleaned)
        else:
            nice.append(cleaned)
    if not must and nice:
        must, nice = nice[:3], nice[3:]
    return {"must": must[:8], "nice": nice[:8]}


def keyword_score(checklist: dict[str, list[str]], public_cv: dict[str, Any]) -> dict[str, Any]:
    from ark_hr.schema import flatten_cv

    haystack = flatten_cv(public_cv).casefold()

    def judge(item: str) -> dict[str, str]:
        words = [word for word in re.findall(r"[a-zA-ZÀ-ÿ0-9+]{4,}", item.casefold())]
        if not words:
            return {"item": item, "result": "not_met", "evidence": ""}
        hits = [word for word in words if word in haystack]
        if len(hits) == len(words):
            result = "met"
        elif hits:
            result = "partly"
        else:
            result = "not_met"
        return {"item": item, "result": result, "evidence": ", ".join(hits[:4])}

    must = [judge(item) for item in checklist.get("must", [])]
    nice = [judge(item) for item in checklist.get("nice", [])]
    strengths = "; ".join(row["evidence"] for row in must + nice if row["result"] == "met" and row["evidence"])
    gaps = "; ".join(row["item"] for row in must if row["result"] == "not_met")
    return {"must": must, "nice": nice, "strengths": strengths, "gaps": gaps}
