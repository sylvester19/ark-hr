"""Read the words out of a CV. Scans are left for OCR. .doc needs LibreOffice."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from docx import Document

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ReadError(Exception):
    pass


def extract_docx(data: bytes) -> str:
    try:
        document = Document(_stream(data))
    except Exception as exc:
        raise ReadError("This Word file could not be opened.") from exc
    parts: list[str] = []
    parts.extend(_paragraphs(document.paragraphs))
    for table in document.tables:
        for row in table.rows:
            cells = [" ".join(_paragraphs(cell.paragraphs)) for cell in row.cells]
            line = " | ".join(cell for cell in cells if cell)
            if line:
                parts.append(line)
    for section in document.sections:
        parts.extend(_paragraphs(section.header.paragraphs))
        parts.extend(_paragraphs(section.footer.paragraphs))
    parts.extend(_text_boxes(data))
    text = "\n".join(part for part in parts if part.strip())
    if not text.strip():
        raise ReadError("This Word file has no readable text.")
    return text


def _paragraphs(paragraphs) -> list[str]:
    lines = []
    for paragraph in paragraphs:
        line = paragraph.text.strip()
        if line:
            lines.append(line)
    return lines


def _stream(data: bytes):
    import io

    return io.BytesIO(data)


def _text_boxes(data: bytes) -> list[str]:
    lines: list[str] = []
    try:
        archive = zipfile.ZipFile(_stream(data))
    except zipfile.BadZipFile:
        return lines
    for name in archive.namelist():
        if not name.startswith("word/") or not name.endswith(".xml"):
            continue
        try:
            root = ElementTree.fromstring(archive.read(name))
        except ElementTree.ParseError:
            continue
        for box in root.iter(W + "txbxContent"):
            for node in box.iter(W + "t"):
                if node.text and node.text.strip():
                    lines.append(node.text.strip())
    return lines


def extract_pdf(data: bytes) -> tuple[str, bool]:
    """Return text and whether any page had no text layer (OCR still required)."""
    import pdfplumber

    try:
        pdf = pdfplumber.open(_stream(data))
    except Exception as exc:
        message = str(exc).casefold()
        if "password" in message or "encrypt" in message:
            raise ReadError("This file is password-protected.") from exc
        raise ReadError("This PDF could not be opened.") from exc
    pages: list[str] = []
    needs_ocr = False
    try:
        if getattr(pdf, "is_encrypted", False):
            raise ReadError("This file is password-protected.")
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())
            else:
                needs_ocr = True
    finally:
        pdf.close()
    return "\n\n".join(pages), needs_ocr


def convert_doc(data: bytes) -> bytes:
    """LibreOffice on every server. Word is the fallback only when it is installed."""
    soffice = shutil.which("soffice") or shutil.which("soffice.exe")
    if soffice:
        try:
            return _convert_with_libreoffice(data, soffice)
        except ReadError:
            if os_word_available():
                return _convert_with_word(data)
            raise
    if os_word_available():
        return _convert_with_word(data)
    raise ReadError("Install LibreOffice to convert .doc files. On Windows, Microsoft Word can do it instead.")


def os_word_available() -> bool:
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    return True


def _convert_with_word(data: bytes) -> bytes:
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise ReadError("Microsoft Word is not available to convert .doc files.") from exc
    pythoncom.CoInitialize()
    word = None
    try:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "cv.doc"
            target = Path(folder) / "cv.docx"
            source.write_bytes(data)
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            document = word.Documents.Open(str(source), False, True, False)
            # 16 is Word's XML document format (.docx).
            document.SaveAs(str(target), FileFormat=16)
            document.Close(False)
            if not target.exists():
                raise ReadError("This .doc file could not be converted.")
            return target.read_bytes()
    except ReadError:
        raise
    except Exception as exc:
        raise ReadError("This .doc file could not be converted.") from exc
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _convert_with_libreoffice(data: bytes, soffice: str) -> bytes:
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "cv.doc"
        source.write_bytes(data)
        try:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "docx", "--outdir", folder, str(source)],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ReadError("This .doc file could not be converted.") from exc
        output = Path(folder) / "cv.docx"
        if not output.exists():
            raise ReadError("This .doc file could not be converted.")
        return output.read_bytes()
