"""OCR for scans and phone photos. The CV is marked so HR can double-check it."""

from __future__ import annotations

import io
import os
import shutil


class OcrError(Exception):
    pass


def _tesseract_text(image) -> str:
    import pytesseract

    windows_exe = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if not shutil.which("tesseract") and os.path.isfile(windows_exe):
        pytesseract.pytesseract.tesseract_cmd = windows_exe
    elif not shutil.which("tesseract") and not os.path.isfile(getattr(pytesseract.pytesseract, "tesseract_cmd", "")):
        return ""
    for lang in ("fra+eng+ara+por", "fra+eng", "eng"):
        try:
            text = pytesseract.image_to_string(image, lang=lang)
        except Exception:
            continue
        if text and text.strip():
            return text.strip()
    return ""


def ocr_image(data: bytes) -> str:
    # Tesseract is the same engine on Windows, Linux, and the server image.
    try:
        from PIL import Image
    except ImportError as exc:
        raise OcrError("OCR libraries are not installed on this server.") from exc
    try:
        image = Image.open(io.BytesIO(data))
    except Exception as exc:
        raise OcrError("OCR could not read this image.") from exc
    try:
        text = _tesseract_text(image)
    except ImportError as exc:
        raise OcrError("OCR libraries are not installed on this server.") from exc
    if text:
        return text
    windows_text = _windows_ocr(data)
    if windows_text:
        return windows_text
    raise OcrError("This image could not be read. Install Tesseract with French, English, Arabic, and Portuguese.")


def _windows_ocr(data: bytes) -> str:
    """Use the OCR engine built into Windows. No Tesseract install."""
    try:
        import asyncio

        import winocr
        from PIL import Image
    except ImportError:
        return ""
    image = Image.open(io.BytesIO(data))
    for language in ("fr-FR", "en-US", "ar-SA", "pt-PT", "pt-BR"):
        try:
            result = asyncio.run(winocr.recognize_pil(image, language))
        except Exception:
            continue
        text = getattr(result, "text", None) or str(result or "")
        if text.strip():
            return text.strip()
    return ""


def ocr_pdf_pages(data: bytes) -> str:
    """Rasterise a scanned PDF and read it with Windows OCR."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise OcrError("This scanned PDF could not be rendered.") from exc
    parts: list[str] = []
    try:
        document = pdfium.PdfDocument(data)
        for page in document:
            image = page.render(scale=2).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            try:
                text = ocr_image(buffer.getvalue())
            except OcrError:
                text = ""
            if text.strip():
                parts.append(text.strip())
    except OcrError:
        raise
    except Exception as exc:
        raise OcrError("This scanned PDF could not be read.") from exc
    if not parts:
        raise OcrError("OCR found no text in this PDF.")
    return "\n\n".join(parts)
