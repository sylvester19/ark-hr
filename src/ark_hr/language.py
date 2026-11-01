"""Open-source language detection. English CVs skip translation but still use the template."""

from __future__ import annotations

_DETECTOR = None


def detect_language(text: str) -> tuple[str, str]:
    """Return (english name, iso code)."""
    sample = text.strip()
    if not sample:
        return "Unknown", "und"
    detector = _detector()
    if detector is None:
        return "Unknown", "und"
    language = detector.detect_language_of(sample)
    if language is None:
        return "Unknown", "und"
    return language.name.capitalize(), language.iso_code_639_1.name.lower()


def _detector():
    global _DETECTOR
    if _DETECTOR is False:
        return None
    if _DETECTOR is not None:
        return _DETECTOR
    try:
        from lingua import Language, LanguageDetectorBuilder

        _DETECTOR = LanguageDetectorBuilder.from_languages(
            Language.ENGLISH,
            Language.FRENCH,
            Language.ARABIC,
            Language.PORTUGUESE,
            Language.SPANISH,
            Language.GERMAN,
        ).build()
    except Exception:
        _DETECTOR = False
        return None
    return _DETECTOR
