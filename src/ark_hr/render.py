"""Fill the unbranded Word template. Empty sections are left out."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from docxtpl import DocxTemplate

from ark_hr.schema import flatten_cv

TEMPLATE_NAME = "cv_template.docx"


def template_path(data_dir: Path) -> Path:
    path = data_dir / TEMPLATE_NAME
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        build_template(path)
    return path


def build_template(path: Path) -> None:
    document = Document()
    section = document.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.left_margin = Mm(18)
    section.right_margin = Mm(18)
    section.top_margin = Mm(16)
    section.bottom_margin = Mm(16)
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
    _set_style_font(normal)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = footer.add_run(
        "Translated from {{ language }} by ARK HR – machine translation, verify before use."
    )
    run.font.name = "Calibri"
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")

    _line(document, "{{ full_name }}", size=18, bold=True)
    _line(document, "{{ target_title }}", size=12)
    _line(document, "{{ contact_line }}")
    _line(document, "{{ linkedin }}")
    _line(document, "{{ ocr_note }}", size=9)
    _block(
        document,
        "summary",
        "Professional summary",
        ["{{ summary }}"],
    )
    _block(
        document,
        "experience",
        "Work experience",
        [
            "{%p for role in experience %}",
            "{{ role.heading }}",
            "{{ role.meta }}",
            "{%p for bullet in role.bullets %}",
            "{{ bullet }}",
            "{%p endfor %}",
            "{%p endfor %}",
        ],
    )
    _block(
        document,
        "education",
        "Education",
        [
            "{%p for item in education %}",
            "{{ item.line }}",
            "{%p endfor %}",
        ],
    )
    _block(
        document,
        "skills",
        "Skills",
        [
            "{%p for group in skills %}",
            "{{ group.line }}",
            "{%p endfor %}",
        ],
    )
    _block(
        document,
        "languages",
        "Languages",
        [
            "{%p for item in languages %}",
            "{{ item.line }}",
            "{%p endfor %}",
        ],
    )
    _block(
        document,
        "certifications",
        "Certifications and licences",
        [
            "{%p for item in certifications %}",
            "{{ item.line }}",
            "{%p endfor %}",
        ],
    )
    _block(
        document,
        "other",
        "Other information",
        [
            "{%p for line in other %}",
            "{{ line }}",
            "{%p endfor %}",
        ],
    )
    document.save(path)


def _set_style_font(style) -> None:
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")


def _line(document: Document, text: str, size: int = 11, bold: bool = False) -> None:
    paragraph = document.add_paragraph()
    run = paragraph.add_run(text)
    run.font.name = "Calibri"
    run.font.size = Pt(size)
    run.bold = bold
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")


def _block(document: Document, flag: str, heading: str, body: list[str]) -> None:
    _line(document, "{%p if " + flag + " %}")
    _line(document, heading, size=13, bold=True)
    for line in body:
        _line(document, line)
    _line(document, "{%p endif %}")


def _join(*parts: str) -> str:
    return " · ".join(part for part in parts if part and part.strip())


def context_for(cv: dict[str, Any], language: str, ocr_used: bool) -> dict[str, Any]:
    contact = _join(cv.get("phone") or "", cv.get("email") or "", cv.get("location") or "")
    experience = []
    for role in cv.get("experience") or []:
        heading = _join(role.get("title") or "", role.get("employer") or "")
        dates = _join(role.get("start") or "", role.get("end") or "")
        meta = _join(role.get("location") or "", dates.replace(" · ", " – ") if False else "")
        # Dates use an en dash, as the brief asks for start–end.
        date_line = ""
        if role.get("start") or role.get("end"):
            date_line = f"{role.get('start') or ''} – {role.get('end') or ''}".strip(" –")
        meta = _join(role.get("location") or "", date_line)
        bullets = [f"• {bullet}" for bullet in role.get("bullets") or [] if bullet]
        if heading or meta or bullets:
            experience.append({"heading": heading, "meta": meta, "bullets": bullets})
    education = []
    for item in cv.get("education") or []:
        line = _join(
            item.get("qualification") or "",
            item.get("institution") or "",
            item.get("location") or "",
            item.get("year") or "",
        )
        if line:
            education.append({"line": line})
    skills = []
    for group in cv.get("skills") or []:
        items = ", ".join(group.get("items") or [])
        label = group.get("group") or ""
        line = f"{label}: {items}" if label and items else (items or label)
        if line:
            skills.append({"line": line})
    languages = []
    for item in cv.get("languages") or []:
        line = _join(item.get("language") or "", item.get("level") or "").replace(" · ", " – ")
        if item.get("language") and item.get("level"):
            line = f"{item['language']} – {item['level']}"
        if line:
            languages.append({"line": line})
    certifications = []
    for item in cv.get("certifications") or []:
        line = _join(item.get("name") or "", item.get("issuer") or "", item.get("year") or "")
        if line:
            certifications.append({"line": line})
    other = [line for line in cv.get("other") or [] if line]
    return {
        "full_name": cv.get("full_name") or "",
        "target_title": cv.get("target_title") or "",
        "contact_line": contact,
        "linkedin": cv.get("linkedin") or "",
        "ocr_note": "OCR used — please double-check this CV." if ocr_used else "",
        "language": language or "the original language",
        "summary": cv.get("summary") or "",
        "experience": experience,
        "education": education,
        "skills": skills,
        "languages": languages,
        "certifications": certifications,
        "other": other,
    }


def render_cv(cv: dict[str, Any], language: str, ocr_used: bool, data_dir: Path) -> bytes:
    template = DocxTemplate(str(template_path(data_dir)))
    template.render(context_for(cv, language, ocr_used))
    buffer = io.BytesIO()
    template.save(buffer)
    return buffer.getvalue()


def docx_text(data: bytes) -> str:
    document = Document(io.BytesIO(data))
    lines = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for section in document.sections:
        lines.extend(paragraph.text for paragraph in section.footer.paragraphs if paragraph.text.strip())
    return "\n".join(lines)


def output_has_body(cv: dict[str, Any]) -> bool:
    return bool(flatten_cv(cv).strip())
