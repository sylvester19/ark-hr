"""Runtime settings. Production refuses anything that would send CV data outside Group Arkays."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BLOCKED_AI_HOSTS = (
    "openai.com",
    "openai.azure.com",
    "azure.openai",
    "googleapis.com",
    "generativelanguage.googleapis.com",
    "anthropic.com",
    "deepl.com",
    "api.deepl.com",
    "cohere.ai",
    "mistral.ai",
    "api.mistral.ai",
)


def _load_dotenv() -> None:
    path = Path(__file__).resolve().parents[2] / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _flag(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    env: str
    phase: int
    public_url: str
    api_url: str
    secret: str
    tenant_id: str
    client_id: str
    client_secret: str
    redirect_uri: str
    users_group: str
    admins_group: str
    local_email: str
    local_name: str
    local_role: str
    admin_emails: tuple[str, ...]
    model: str
    ai_base_url: str
    ai_allowlist: tuple[str, ...]
    storage: str
    azure_connection_string: str
    azure_container: str
    azure_region: str
    graph_sender: str
    data_dir: Path

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def microsoft_enabled(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret and self.redirect_uri)

    @property
    def local_login_enabled(self) -> bool:
        return not self.is_prod and bool(self.local_email)

    def validate_for_start(self) -> None:
        problems: list[str] = []
        if self.phase not in (1, 2):
            problems.append("ARK_HR_PHASE must be 1 or 2.")
        if len(self.secret) < 16:
            problems.append("ARK_HR_SECRET must be at least 16 characters.")
        if self.is_prod:
            if self.local_email:
                problems.append("Local sign-in is not allowed when ARK_HR_ENV=prod.")
            if not self.microsoft_enabled:
                problems.append("Microsoft 365 sign-in is required in production.")
            if self.storage != "azure":
                problems.append("Production storage must be Azure Blob (ARK_HR_STORAGE=azure).")
            if self.azure_region.lower() != "uaenorth":
                problems.append("CV files must stay in Azure UAE North.")
            if not self.azure_connection_string or not self.azure_container:
                problems.append("Azure Blob connection string and container are required in production.")
            if not self.model and not os.environ.get("ARK_HR_GGUF", "").strip():
                problems.append("Choose a benchmarked open-source model before production.")
        if self.ai_base_url:
            from ark_hr.ai_guard import assert_private_ai_url

            try:
                assert_private_ai_url(self.ai_base_url, self.ai_allowlist)
            except ValueError as exc:
                problems.append(str(exc))
        if problems:
            raise RuntimeError("ARK HR cannot start:\n- " + "\n- ".join(problems))


def load_settings() -> Settings:
    _load_dotenv()
    root = Path(__file__).resolve().parents[2]
    data = Path(_flag("ARK_HR_DATA_DIR") or (root / "data"))
    allow = tuple(part.strip().lower() for part in _flag("ARK_HR_AI_HOST_ALLOWLIST").split(",") if part.strip())
    phase_raw = _flag("ARK_HR_PHASE", "1") or "1"
    env = _flag("ARK_HR_ENV", "local").lower() or "local"
    local_default = "" if env == "prod" else "hr@grouparkays.com"
    settings = Settings(
        env=env,
        phase=int(phase_raw),
        public_url=_flag("ARK_HR_PUBLIC_URL", "http://localhost:3215").rstrip("/"),
        api_url=_flag("ARK_HR_API_URL", "http://localhost:3000").rstrip("/"),
        secret=_flag("JWT_SECRET") or _flag("ARK_HR_SECRET", "local-dev-secret-change-me"),
        tenant_id=_flag("ENTRA_TENANT_ID") or _flag("ARK_HR_AZURE_TENANT_ID"),
        client_id=_flag("ENTRA_CLIENT_ID") or _flag("ARK_HR_AZURE_CLIENT_ID"),
        client_secret=_flag("ENTRA_CLIENT_SECRET") or _flag("ARK_HR_AZURE_CLIENT_SECRET"),
        redirect_uri=_flag("AZURE_REDIRECT_URI") or _flag("ARK_HR_AZURE_REDIRECT_URI") or "http://localhost:3000/auth/callback",
        users_group=_flag("ARK_HR_USERS_GROUP", "ARK-HR-Users"),
        admins_group=_flag("ARK_HR_ADMINS_GROUP", "ARK-HR-Admins"),
        local_email=_flag("ARK_HR_LOCAL_EMAIL", local_default).lower(),
        local_name=_flag("ARK_HR_LOCAL_NAME", "HR user"),
        local_role=_flag("ARK_HR_LOCAL_ROLE", "hr").lower(),
        admin_emails=tuple(
            part.strip().lower()
            for part in _flag("ARK_HR_ADMIN_EMAILS").split(",")
            if part.strip()
        ),
        model=_flag("ARK_HR_MODEL"),
        ai_base_url=_flag("ARK_HR_AI_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
        ai_allowlist=allow,
        storage=_flag("ARK_HR_STORAGE", "local").lower() or "local",
        azure_connection_string=_flag("ARK_HR_AZURE_CONNECTION_STRING"),
        azure_container=_flag("ARK_HR_AZURE_CONTAINER", "ark-hr-cvs"),
        azure_region=_flag("ARK_HR_AZURE_REGION", "uaenorth").lower(),
        graph_sender=_flag("ARK_HR_GRAPH_SENDER"),
        data_dir=data,
    )
    return settings
