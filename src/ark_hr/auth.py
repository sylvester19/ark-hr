"""Microsoft 365 sign-in. Access is the Entra group, not a password."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from ark_hr.config import Settings

SESSION = "ark_hr_session"
SESSION_HOURS = 8


class AuthError(Exception):
    pass


def sign_session(settings: Settings, email: str, name: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email.lower(),
        "name": name,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=SESSION_HOURS)).timestamp()),
    }
    return jwt.encode(payload, settings.secret, algorithm="HS256")


def read_session(settings: Settings, token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthError("Sign in again.") from exc
    if payload.get("role") not in ("hr", "admin"):
        raise AuthError("You do not have access to ARK HR.")
    return payload


def login_url(settings: Settings, state: str) -> str:
    query = urlencode(
        {
            "client_id": settings.client_id,
            "response_type": "code",
            "redirect_uri": settings.redirect_uri,
            "response_mode": "query",
            "scope": "openid profile email",
            "state": state,
        }
    )
    return f"https://login.microsoftonline.com/{settings.tenant_id}/oauth2/v2.0/authorize?{query}"


def exchange_code(settings: Settings, code: str) -> dict[str, Any]:
    token_url = f"https://login.microsoftonline.com/{settings.tenant_id}/oauth2/v2.0/token"
    try:
        response = httpx.post(
            token_url,
            data={
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.redirect_uri,
                "scope": "openid profile email",
            },
            timeout=30,
        )
        response.raise_for_status()
        token = response.json()
        jwks = jwt.PyJWKClient(
            f"https://login.microsoftonline.com/{settings.tenant_id}/discovery/v2.0/keys"
        )
        signing_key = jwks.get_signing_key_from_jwt(token["id_token"]).key
        id_token = jwt.decode(
            token["id_token"],
            signing_key,
            algorithms=["RS256"],
            audience=settings.client_id,
        )
    except (httpx.HTTPError, KeyError, jwt.PyJWTError) as exc:
        raise AuthError("Microsoft sign-in did not complete.") from exc
    email = (
        id_token.get("preferred_username")
        or id_token.get("email")
        or id_token.get("upn")
        or ""
    ).lower()
    name = id_token.get("name") or email
    tenant = str(id_token.get("tid") or "")
    if settings.tenant_id and tenant and tenant != settings.tenant_id:
        raise AuthError("This Microsoft account is not in the Group Arkays tenant.")
    if "groups" in id_token:
        groups = [str(item) for item in id_token.get("groups") or []]
        role = _role(settings, groups)
        if not role:
            raise AuthError("Your account is not in an ARK HR group.")
    else:
        # ARK IMPEX core asks only for openid profile email, so the token
        # has no group list. A successful sign-in is the same door as core.
        role = "admin" if email in settings.admin_emails else "hr"
    if not email:
        raise AuthError("Microsoft did not return an email address.")
    return {"email": email, "name": name, "role": role}


def _role(settings: Settings, groups: list[str]) -> str | None:
    folded = {group.casefold() for group in groups}
    if settings.admins_group.casefold() in folded:
        return "admin"
    if settings.users_group.casefold() in folded:
        return "hr"
    return None
