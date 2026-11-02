"""Temperature 0. The runtime's JSON schema is enforced.

A Groq free-tier key translates in the cloud. Otherwise the app uses a private
Ollama server or the local Qwen file.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Protocol

import httpx

from ark_hr.ai_guard import assert_private_ai_url
from ark_hr.schema import CV_JSON_SCHEMA, normalise_cv

SYSTEM = """You convert one CV into English JSON for a fixed template.
Rules:
- Temperature is 0. Do not invent, guess, or summarise.
- Keep people, company, school, and place names exactly as written.
- Keep certification identifiers and driving-licence categories exactly as written.
- Translate job titles, descriptions, skills, and qualifications into English.
- If the CV is already English, copy the wording. Do not paraphrase.
- A sentence that is still in the source language is wrong, except for a person, company, school, or place name.
- Put anything that fits no field into "other".
- Never output a photo, date of birth, age, marital status, religion, nationality, or gender.
- Dates in experience use Month YYYY.
- Return only the JSON object.
"""


class ModelError(Exception):
    pass


class Translator(Protocol):
    def structure(self, source_text: str, language: str, repair: str = "") -> dict[str, Any]:
        ...

    def requirements(self, job_text: str) -> dict[str, list[str]]:
        ...

    def score_cv(self, checklist: dict[str, list[str]], public_cv: dict[str, Any]) -> dict[str, Any]:
        ...


DEFAULT_GGUF_NAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODELS = ("openai/gpt-oss-20b", "qwen/qwen3.8-27b", "openai/gpt-oss-120b")


def build_translator(settings) -> Translator:
    """Groq when a free key is set. Otherwise Ollama, then the local Qwen file."""
    if getattr(settings, "groq_api_key", ""):
        return GroqTranslator(settings.groq_api_key, _groq_models())
    if settings.model:
        return OllamaTranslator(settings.ai_base_url, settings.model, settings.ai_allowlist)
    if _ollama_ready(settings.ai_base_url):
        return OllamaTranslator(settings.ai_base_url, "qwen2.5:1.5b", settings.ai_allowlist)
    model_path = _gguf_path(settings)
    if model_path.is_file() and model_path.stat().st_size > 1_000_000:
        return LlamaCppTranslator(model_path)
    return UnavailableTranslator(
        "No open-source model is available. Set ARK_HR_MODEL to a private Ollama model, "
        f"or place {DEFAULT_GGUF_NAME} in the data/models folder."
    )


def _gguf_path(settings) -> Path:
    custom = os.environ.get("ARK_HR_GGUF", "").strip()
    if custom:
        return Path(custom)
    return settings.data_dir / "models" / DEFAULT_GGUF_NAME


def _ollama_ready(base_url: str) -> bool:
    try:
        assert_private_ai_url(base_url)
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=0.4)
        response.raise_for_status()
        names = [item.get("name", "") for item in response.json().get("models", [])]
    except Exception:
        return False
    return any(name.startswith("qwen2.5") for name in names)


def _groq_models() -> tuple[str, ...]:
    raw = os.environ.get("ARK_HR_GROQ_MODELS", "").strip()
    if not raw:
        return DEFAULT_GROQ_MODELS
    models = tuple(part.strip() for part in raw.split(",") if part.strip())
    return models or DEFAULT_GROQ_MODELS


class GroqTranslator:
    """Free Groq tier. CV text leaves Group Arkays. A rate limit tries the next free model."""

    def __init__(self, api_key: str, models: tuple[str, ...]) -> None:
        self._api_key = api_key
        self._models = models
        self.engine = f"groq:{models[0]}"

    def structure(self, source_text: str, language: str, repair: str = "") -> dict[str, Any]:
        note = f"\nFix these problems from the previous attempt:\n{repair}" if repair else ""
        prompt = f"Detected language: {language or 'unknown'}.\nSource CV:\n{source_text}{note}"
        return normalise_cv(self._json(SYSTEM, prompt))

    def requirements(self, job_text: str) -> dict[str, list[str]]:
        raw = self._json(
            "Turn the job description into a checklist of must-haves and nice-to-haves. "
            "Do not invent requirements that are not written. Return JSON with keys must and nice.",
            job_text,
        )
        from ark_hr.score import normalise_checklist

        return normalise_checklist(raw)

    def score_cv(self, checklist: dict[str, list[str]], public_cv: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "Score this CV against the checklist. Use only the CV JSON. "
            "For every item say met, partly, or not_met, and quote the CV line that proves it. "
            "Do not use name, age, gender, nationality, religion, or marital status. "
            "Return JSON with keys must, nice, strengths, and gaps.\n"
            f"Checklist:\n{json.dumps(checklist)}\nCV:\n{json.dumps(public_cv)}"
        )
        return self._json("You score CVs. Return JSON only.", prompt)

    def _json(self, system: str, user: str) -> dict[str, Any]:
        content = self._complete(system, user)
        try:
            return _parse_json_object(content)
        except json.JSONDecodeError as exc:
            raise ModelError("The translation model did not return JSON.") from exc

    def _complete(self, system: str, user: str) -> str:
        last_error = ModelError("The free translation service did not answer.")
        for model in self._models:
            for use_schema in (True, False):
                try:
                    content = self._post(model, system, user, use_schema)
                except ModelError as exc:
                    last_error = exc
                    if "rate limit" in str(exc) or "too long" in str(exc):
                        break
                    if use_schema:
                        continue
                    break
                if content.strip():
                    self.engine = f"groq:{model}"
                    return content
        raise last_error

    def _post(self, model: str, system: str, user: str, use_schema: bool) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "temperature": 0,
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if use_schema:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = httpx.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=90,
            )
        except httpx.HTTPError as exc:
            raise ModelError("The free translation service could not be reached.") from exc
        if response.status_code == 429:
            delay = response.headers.get("retry-after", "2")
            try:
                time.sleep(min(float(delay), 8))
            except ValueError:
                time.sleep(2)
            raise ModelError("The free translation service hit its rate limit.")
        if response.status_code == 413:
            raise ModelError("This CV is too long for the free translation limit.")
        if response.status_code >= 400:
            raise ModelError("The free translation service rejected this CV.")
        message = response.json()["choices"][0]["message"]
        return str(message.get("content") or "")


class UnavailableTranslator:
    """Lets the API start. Each CV is marked Failed until a local model is in place."""

    engine = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def structure(self, source_text: str, language: str, repair: str = "") -> dict[str, Any]:
        raise ModelError(self.reason)

    def requirements(self, job_text: str) -> dict[str, list[str]]:
        raise ModelError(self.reason)

    def score_cv(self, checklist: dict[str, list[str]], public_cv: dict[str, Any]) -> dict[str, Any]:
        raise ModelError(self.reason)


class LlamaCppTranslator:
    """Same prompts as Ollama, running in-process. Works on Windows and Linux with no extra service."""

    engine = "qwen2.5-1.5b-instruct"

    def __init__(self, model_path) -> None:
        self.model_path = model_path
        self._llm = None

    def structure(self, source_text: str, language: str, repair: str = "") -> dict[str, Any]:
        note = f"\nFix these problems from the previous attempt:\n{repair}" if repair else ""
        prompt = f"Detected language: {language or 'unknown'}.\nSource CV:\n{source_text}{note}"
        return normalise_cv(self._json(SYSTEM, prompt, CV_JSON_SCHEMA))

    def requirements(self, job_text: str) -> dict[str, list[str]]:
        schema = {
            "type": "object",
            "properties": {
                "must": {"type": "array", "items": {"type": "string"}},
                "nice": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["must", "nice"],
        }
        raw = self._json(
            "Turn the job description into a checklist of must-haves and nice-to-haves. "
            "Do not invent requirements that are not written. Return JSON.",
            job_text,
            schema,
        )
        from ark_hr.score import normalise_checklist

        return normalise_checklist(raw)

    def score_cv(self, checklist: dict[str, list[str]], public_cv: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "Score this CV against the checklist. Use only the CV JSON. "
            "For every item say met, partly, or not_met, and quote the CV line that proves it. "
            "Do not use name, age, gender, nationality, religion, or marital status.\n"
            f"Checklist:\n{json.dumps(checklist)}\nCV:\n{json.dumps(public_cv)}"
        )
        schema = {
            "type": "object",
            "properties": {
                "must": {"type": "array", "items": {"type": "object"}},
                "nice": {"type": "array", "items": {"type": "object"}},
                "strengths": {"type": "string"},
                "gaps": {"type": "string"},
            },
            "required": ["must", "nice", "strengths", "gaps"],
        }
        return self._json("You score CVs. Return JSON only.", prompt, schema)

    def _llm_client(self):
        if self._llm is None:
            try:
                from llama_cpp import Llama
            except ImportError as exc:
                raise ModelError(
                    "The Qwen model file is present, but llama-cpp-python is not installed."
                ) from exc
            threads = min(os.cpu_count() or 4, 8)
            self._llm = Llama(
                model_path=str(self.model_path),
                n_ctx=4096,
                n_threads=threads,
                n_gpu_layers=0,
                verbose=False,
            )
        return self._llm

    def _complete(self, system: str, user: str, response_format: dict[str, Any]) -> str:
        result = self._llm_client().create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            response_format=response_format,
        )
        return result["choices"][0]["message"]["content"]

    def _json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        content = ""
        last_error: Exception | None = None
        formats = (
            {"type": "json_object", "schema": schema},
            {"type": "json_object"},
        )
        for response_format in formats:
            try:
                content = self._complete(system, user, response_format)
                parsed = _parse_json_object(content)
                return parsed
            except ModelError:
                raise
            except Exception as exc:
                last_error = exc
        raise ModelError("The local translation model could not complete this CV.") from last_error


def _parse_json_object(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        fence = text.rfind("```")
        if fence >= 0:
            text = text[:fence]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ModelError("The translation model did not return a JSON object.")
    return parsed


class LocalTranslator:
    """Kept for tests of the older on-PC parser. The live path does not select it."""

    engine = "parser"

    def structure(self, source_text: str, language: str, repair: str = "") -> dict[str, Any]:
        from ark_hr.local_cv import local_translate, structure_cv

        codes = {
            "french": "fr",
            "english": "en",
            "arabic": "ar",
            "portuguese": "pt",
            "spanish": "es",
            "german": "de",
            "unknown": "und",
        }
        code = codes.get(language.casefold(), language.casefold()[:2] or "und")
        return structure_cv(source_text, code, local_translate)

    def requirements(self, job_text: str) -> dict[str, list[str]]:
        from ark_hr.local_cv import keyword_requirements

        return keyword_requirements(job_text)

    def score_cv(self, checklist: dict[str, list[str]], public_cv: dict[str, Any]) -> dict[str, Any]:
        from ark_hr.local_cv import keyword_score

        return keyword_score(checklist, public_cv)


class OllamaTranslator:
    def __init__(self, base_url: str, model: str, allowlist: tuple[str, ...] = ()) -> None:
        self.engine = f"ollama:{model}"
        assert_private_ai_url(base_url, allowlist)
        if not model:
            raise ModelError(
                "No open-source model has been selected yet. "
                "Benchmark 2–3 models on the test CVs and set ARK_HR_MODEL."
            )
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.allowlist = allowlist

    def structure(self, source_text: str, language: str, repair: str = "") -> dict[str, Any]:
        note = f"\nFix these problems from the previous attempt:\n{repair}" if repair else ""
        prompt = (
            f"Detected language: {language or 'unknown'}.\n"
            f"Source CV:\n{source_text}{note}"
        )
        return normalise_cv(self._json(SYSTEM, prompt, CV_JSON_SCHEMA))

    def requirements(self, job_text: str) -> dict[str, list[str]]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "must": {"type": "array", "items": {"type": "string"}},
                "nice": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["must", "nice"],
        }
        raw = self._json(
            "Turn the job description into a checklist of must-haves and nice-to-haves. "
            "Do not invent requirements that are not written. Return JSON.",
            job_text,
            schema,
        )
        from ark_hr.score import normalise_checklist

        return normalise_checklist(raw)

    def score_cv(self, checklist: dict[str, list[str]], public_cv: dict[str, Any]) -> dict[str, Any]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "must": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "item": {"type": "string"},
                            "result": {"type": "string", "enum": ["met", "partly", "not_met"]},
                            "evidence": {"type": "string"},
                        },
                        "required": ["item", "result", "evidence"],
                    },
                },
                "nice": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "item": {"type": "string"},
                            "result": {"type": "string", "enum": ["met", "partly", "not_met"]},
                            "evidence": {"type": "string"},
                        },
                        "required": ["item", "result", "evidence"],
                    },
                },
                "strengths": {"type": "string"},
                "gaps": {"type": "string"},
            },
            "required": ["must", "nice", "strengths", "gaps"],
        }
        prompt = (
            "Score this CV against the checklist. Use only the CV JSON. "
            "For every item say met, partly, or not_met, and quote the CV line that proves it. "
            "Do not use name, age, gender, nationality, religion, or marital status.\n"
            f"Checklist:\n{json.dumps(checklist)}\nCV:\n{json.dumps(public_cv)}"
        )
        return self._json("You score CVs. Return JSON only.", prompt, schema)

    def _json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "format": schema,
                    "options": {"temperature": 0},
                },
                timeout=180,
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            parsed = json.loads(content)
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            raise ModelError("The translation model is not reachable inside Group Arkays infrastructure.") from exc
        if not isinstance(parsed, dict):
            raise ModelError("The translation model did not return a JSON object.")
        return parsed
