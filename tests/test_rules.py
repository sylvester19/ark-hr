import io
import json
import zipfile
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from ark_hr.ai_guard import assert_private_ai_url
from ark_hr.config import Settings
from ark_hr.db import Database
from ark_hr.intake import IntakeError, collect
from ark_hr.names import english_name
from ark_hr.render import docx_text, render_cv
from ark_hr.schema import normalise_cv, public_cv_for_scoring
from ark_hr.score import score_percent
from ark_hr.storage import LocalStorage, read_download, sign_download
from ark_hr.verify import verify_cv

SOURCE = """Jean-Baptiste Mbarga
Responsable logistique
Téléphone: +237 699 123 456
Email: jb.mbarga@example.com
Douala, Cameroun
https://linkedin.com/in/jbmbarga

Profil
Responsable logistique avec 8 ans d'expérience au port.

Expérience
Responsable logistique — Port de Douala, Douala
Janvier 2018 – Présent
Gestion du dédouanement à Douala
Coordination des équipes de quai

Formation
Licence en logistique — Université de Douala, Douala, 2016

Compétences
Logistique portuaire
Dédouanement

Langues
Français — natif
Anglais — courant

Permis B — Préfecture du Wouri, 2014

Né le 12 mars 1985
Nationalité camerounaise
"""

GOOD = {
    "full_name": "Jean-Baptiste Mbarga",
    "target_title": "Logistics manager",
    "phone": "+237 699 123 456",
    "email": "jb.mbarga@example.com",
    "location": "Douala, Cameroun",
    "linkedin": "https://linkedin.com/in/jbmbarga",
    "summary": "Logistics manager with 8 years of experience at the port.",
    "experience": [
        {
            "title": "Logistics manager",
            "employer": "Port de Douala",
            "location": "Douala",
            "start": "January 2018",
            "end": "Present",
            "bullets": ["Managed customs clearance in Douala", "Coordinated quay teams"],
        }
    ],
    "education": [
        {
            "qualification": "Degree in logistics",
            "institution": "Université de Douala",
            "location": "Douala",
            "year": "2016",
        }
    ],
    "skills": [{"group": "Operations", "items": ["Port logistics", "Customs clearance"]}],
    "languages": [
        {"language": "French", "level": "native"},
        {"language": "English", "level": "fluent"},
    ],
    "certifications": [{"name": "Permis B", "issuer": "Préfecture du Wouri", "year": "2014"}],
    "other": [],
}


def test_verify_accepts_a_faithful_translation():
    result = verify_cv(SOURCE, normalise_cv(GOOD))
    assert result.ok, result.reason


def test_verify_flags_a_dropped_phone_and_a_translated_name():
    broken = json.loads(json.dumps(GOOD))
    broken["phone"] = ""
    broken["full_name"] = "Peter White"
    result = verify_cv(SOURCE, normalise_cv(broken))
    assert not result.ok
    assert any("phone number missing" in reason for reason in result.reasons)
    assert any("candidate name" in reason for reason in result.reasons)


def test_verify_flags_an_invented_year_and_a_changed_employer():
    broken = json.loads(json.dumps(GOOD))
    broken["experience"][0]["employer"] = "Port of Douala"
    broken["experience"][0]["end"] = "2024"
    result = verify_cv(SOURCE, normalise_cv(broken))
    assert any("employer was changed" in reason for reason in result.reasons)
    assert any("year added" in reason for reason in result.reasons)


def test_birth_year_is_not_required_in_the_english_cv():
    result = verify_cv(SOURCE, normalise_cv(GOOD))
    assert result.ok
    assert "1985" not in result.reason


def test_sensitive_fields_are_removed():
    raw = dict(GOOD)
    raw["other"] = ["Nationality: Cameroon", "Married"]
    cleaned = normalise_cv(raw)
    assert cleaned["other"] == []
    public = public_cv_for_scoring(cleaned)
    assert "full_name" not in public
    assert "phone" not in public


def test_score_weights_must_haves_at_70_percent():
    must = [{"result": "met"}, {"result": "met"}, {"result": "met"}, {"result": "met"}, {"result": "not_met"}]
    nice = [{"result": "not_met"}]
    # 4/5 = 0.8 at 70%, nice 0 at 30% → 56
    assert score_percent(must, nice) == 56


def test_zip_rejects_path_escape_and_skips_macos_junk():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../secret.txt", b"nope")
    with pytest.raises(IntakeError):
        collect([("batch.zip", buffer.getvalue())])

    buffer = io.BytesIO()
    document = io.BytesIO()
    Document().save(document)
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__MACOSX/._cv.docx", b"junk")
        archive.writestr("notes.txt", b"ignore")
        archive.writestr("cv.docx", document.getvalue())
        archive.writestr("copy.docx", document.getvalue())
    incoming = collect([("batch.zip", buffer.getvalue())])
    assert [item.name for item in incoming] == ["cv.docx"]


def test_duplicate_candidate_names_get_a_suffix():
    used: set[str] = set()
    first = english_name("Jean-Baptiste Mbarga", "a.docx", used)
    second = english_name("Jean-Baptiste Mbarga", "b.docx", used)
    assert first == "Jean-Baptiste Mbarga_EN.docx"
    assert second == "Jean-Baptiste Mbarga_2_EN.docx"


def test_paid_ai_hosts_are_refused():
    with pytest.raises(ValueError):
        assert_private_ai_url("https://api.openai.com/v1")
    with pytest.raises(ValueError):
        assert_private_ai_url("https://api.deepl.com")
    assert assert_private_ai_url("http://127.0.0.1:11434") == "127.0.0.1"


def test_download_link_expires(monkeypatch):
    token = sign_download("test-secret-value-ok", "batch", "*", now=1_000)
    assert read_download("test-secret-value-ok", token, now=1_000) == ("batch", "*")
    with pytest.raises(ValueError):
        read_download("test-secret-value-ok", token, now=1_000 + 16 * 60)


def test_template_omits_empty_sections_and_prints_the_footer(tmp_path: Path):
    cv = normalise_cv(GOOD)
    cv["skills"] = []
    cv["other"] = []
    data = render_cv(cv, "French", True, tmp_path)
    text = docx_text(data)
    assert "Jean-Baptiste Mbarga" in text
    assert "Port de Douala" in text
    assert "Skills" not in text
    assert "Other information" not in text
    assert "Translated from French by ARK HR – machine translation, verify before use." in text
    assert "OCR used" in text
    assert "1985" not in text
    assert "Nationalité" not in text


class FakeModel:
    def __init__(self, drop_phone: bool = False, always: bool = False):
        self.drop_phone = drop_phone
        self.always = always
        self.calls = 0

    def structure(self, source_text: str, language: str, repair: str = ""):
        self.calls += 1
        cv = json.loads(json.dumps(GOOD))
        if self.drop_phone and (self.always or self.calls == 1):
            cv["phone"] = ""
        return normalise_cv(cv)

    def requirements(self, job_text: str):
        return {"must": ["5 years logistics", "driving licence B"], "nice": ["French and English"]}

    def score_cv(self, checklist, public_cv):
        assert "full_name" not in public_cv
        return {
            "must": [
                {"item": "5 years logistics", "result": "met", "evidence": "8 years of experience"},
                {"item": "driving licence B", "result": "met", "evidence": "Permis B"},
            ],
            "nice": [{"item": "French and English", "result": "met", "evidence": "French – native"}],
            "strengths": "8 yrs port logistics",
            "gaps": "",
        }


def _settings(tmp_path: Path, phase: int = 1) -> Settings:
    return Settings(
        env="local",
        phase=phase,
        public_url="http://127.0.0.1:3215",
        api_url="http://127.0.0.1:3214",
        secret="test-secret-value-ok",
        tenant_id="",
        client_id="",
        client_secret="",
        redirect_uri="",
        users_group="ARK-HR-Users",
        admins_group="ARK-HR-Admins",
        local_email="hr@grouparkays.com",
        local_name="HR user",
        local_role="hr",
        admin_emails=(),
        model="",
        ai_base_url="http://127.0.0.1:11434",
        ai_allowlist=(),
        storage="local",
        azure_connection_string="",
        azure_container="ark-hr-cvs",
        azure_region="uaenorth",
        graph_sender="",
        groq_api_key="",
        data_dir=tmp_path,
    )


def _client(tmp_path: Path, model: FakeModel, phase: int = 1) -> TestClient:
    from ark_hr.api import create_app

    app = create_app(
        _settings(tmp_path, phase),
        database=Database(tmp_path / "ark-hr.sqlite"),
        storage=LocalStorage(tmp_path / "blobs"),
        translator=model,
        start=False,
    )
    client = TestClient(app)
    assert client.post("/auth/local").status_code == 200
    return client


def _docx_bytes(text: str) -> bytes:
    document = Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_batch_translates_and_a_bad_file_does_not_stop_it(tmp_path: Path):
    from ark_hr.worker import step

    client = _client(tmp_path, FakeModel())
    response = client.post(
        "/batches",
        files=[
            ("files", ("mbarga.docx", _docx_bytes(SOURCE), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
            ("files", ("broken.pdf", b"not a pdf", "application/pdf")),
        ],
        data={"name": "Batch 2026-10-27 14:30"},
    )
    assert response.status_code == 200, response.text
    batch_id = response.json()["id"]
    app = client.app
    while step(app):
        pass
    body = client.get(f"/batches/{batch_id}").json()
    by_name = {row["original_name"]: row for row in body["files"]}
    assert by_name["mbarga.docx"]["status"] == "Done"
    assert by_name["broken.pdf"]["status"] == "Failed"
    assert "could not" in by_name["broken.pdf"]["reason"].lower()
    link = client.post(f"/batches/{batch_id}/link").json()["url"]
    downloaded = client.get(link)
    assert downloaded.status_code == 200
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        names = archive.namelist()
    assert "English_CVs/Jean-Baptiste Mbarga_EN.docx" in names
    assert "Originals/mbarga.docx" in names
    assert "Originals/broken.pdf" in names
    assert any(name == "Needs_Review.txt" for name in names)


def test_a_failed_check_is_retried_once_then_flagged(tmp_path: Path):
    from ark_hr.worker import step

    model = FakeModel(drop_phone=True, always=True)
    client = _client(tmp_path, model)
    response = client.post(
        "/batches",
        files=[("files", ("mbarga.docx", _docx_bytes(SOURCE), "application/octet-stream"))],
        data={"name": "Retry"},
    )
    app = client.app
    while step(app):
        pass
    body = client.get(f"/batches/{response.json()['id']}").json()
    assert body["files"][0]["status"] == "Needs review"
    assert "phone number missing" in body["files"][0]["reason"]
    assert model.calls == 2
    link = client.post(f"/batches/{response.json()['id']}/files/{body['files'][0]['id']}/link").json()["url"]
    assert client.get(link).status_code == 200


def test_stranger_cannot_open_a_batch(tmp_path: Path):
    client = _client(tmp_path, FakeModel())
    created = client.post(
        "/batches",
        files=[("files", ("mbarga.docx", _docx_bytes(SOURCE), "application/octet-stream"))],
        data={"name": "Mine"},
    )
    other = TestClient(client.app)
    other.cookies.clear()
    assert other.get(f"/batches/{created.json()['id']}").status_code == 401
    assert client.get("/settings").status_code == 403


def test_a_retry_keeps_the_original_employer_and_school():
    from ark_hr.pipeline import _lock_facts

    source = "Jean-Baptiste Mbarga\nPort de Douala\nUniversité de Douala"
    previous = {
        "full_name": "Jean-Baptiste Mbarga",
        "summary": "Responsable logistique avec 8 ans d'expérience au port.",
        "experience": [{"employer": "Port de Douala", "title": "Responsable", "location": "Douala", "bullets": ["Gestion"]}],
        "education": [{"institution": "Université de Douala", "qualification": "Licence", "location": "Douala", "year": "2016"}],
    }
    current = {
        "full_name": "John Mbarga",
        "target_title": "Logistics Manager",
        "summary": "",
        "experience": [{"employer": "Port of Douala", "title": "Logistics Manager", "location": "Douala", "bullets": ["Customs clearance"]}],
        "education": [{"institution": "University of Douala", "qualification": "Bachelor of logistics", "location": "Douala", "year": "2016"}],
    }
    locked = _lock_facts(previous, current, source)
    assert locked["full_name"] == "Jean-Baptiste Mbarga"
    assert locked["experience"][0]["employer"] == "Port de Douala"
    assert locked["experience"][0]["title"] == "Logistics Manager"
    assert locked["education"][0]["institution"] == "Université de Douala"
    assert locked["summary"].startswith("Responsable")


def test_a_year_range_is_not_a_new_phone_number():
    from ark_hr.verify import _phone_keys

    assert _phone_keys("Licence 2014-2016, Douala") == set()
    assert "237699123456" in _phone_keys("Tel +237 699 123 456")


def test_groq_free_tier_translates_and_falls_over_when_limited(tmp_path: Path, monkeypatch):
    from ark_hr.translate import build_translator

    settings = Settings(**{**_settings(tmp_path).__dict__, "groq_api_key": "test-key"})
    import json as json_module

    calls: list[str] = []

    class Response:
        def __init__(self, status: int, content: str = "") -> None:
            self.status_code = status
            self.headers = {"retry-after": "0"}
            self._content = content

        def json(self) -> dict:
            return {"choices": [{"message": {"content": self._content}}]}

    def fake_post(url, headers, json, timeout):
        assert url.endswith("/chat/completions")
        assert headers["Authorization"] == "Bearer test-key"
        calls.append(json["model"])
        if json["model"] == "qwen/qwen3.8-27b":
            return Response(429)
        return Response(200, json_module.dumps(GOOD))

    monkeypatch.setattr("ark_hr.translate.httpx.post", fake_post)
    monkeypatch.setattr("ark_hr.translate.time.sleep", lambda _seconds: None)
    translator = build_translator(settings)
    cv = translator.structure(SOURCE, "french")
    assert calls[0] == "qwen/qwen3.8-27b"
    assert "openai/gpt-oss-120b" in calls
    assert cv["full_name"] == "Jean-Baptiste Mbarga"
    assert translator.engine == "groq:openai/gpt-oss-120b"


def test_missing_model_fails_the_file_instead_of_calling_a_public_api(tmp_path: Path, monkeypatch):
    from ark_hr.translate import ModelError, build_translator

    monkeypatch.delenv("ARK_HR_GGUF", raising=False)
    translator = build_translator(_settings(tmp_path))
    assert translator.engine == "unavailable"
    with pytest.raises(ModelError):
        translator.structure(SOURCE, "french")


def test_local_parser_keeps_the_facts_without_a_model():
    from ark_hr.local_cv import structure_cv

    cv = structure_cv(SOURCE, "fr", lambda text, code: text)
    result = verify_cv(SOURCE, cv)
    assert result.ok, result.reason
    assert cv["full_name"] == "Jean-Baptiste Mbarga"
    assert cv["experience"][0]["employer"] == "Port de Douala"
    assert "1985" not in str(cv)


def test_production_refuses_local_files_and_a_public_model():
    settings = _settings(Path("."))
    settings = Settings(**{**settings.__dict__, "env": "prod", "storage": "local"})
    with pytest.raises(RuntimeError):
        settings.validate_for_start()
