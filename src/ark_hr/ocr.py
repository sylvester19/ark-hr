"""OCR for scans and phone photos. The CV is marked so HR can double-check it."""

from __future__ import annotations

import io
import shutil


class OcrError(Exception):
    pass


def ocr_image(data: bytes) -> str:
    # Tesseract is the same engine on Windows, Linux, and the server image.
    if shutil.which("tesseract"):
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise OcrError("OCR libraries are not installed on this server.") from exc
        try:
            image = Image.open(io.BytesIO(data))
            text = pytesseract.image_to_string(image, lang="fra+eng+ara+por")
        except Exception as exc:
            raise OcrError("OCR could not read this image.") from exc
        if text.strip():
            return text.strip()
    windows_text = _windows_ocr(data)
    if windows_text:
        return windows_text
    raise OcrError("This image could not be read. Install Tesseract with French, English, Arabic, and Portuguese.")
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise OcrError("OCR libraries are not installed on this server.") from exc
    try:
        image = Image.open(io.BytesIO(data))
        text = pytesseract.image_to_string(image, lang="fra+eng+ara+por")
    except Exception as exc:
        raise OcrError("OCR could not read this image.") from exc
    if not text.strip():
        raise OcrError("OCR found no text in this image.")
    return text


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
