"""Batch-ready email. The message never contains CV text."""

from __future__ import annotations

import logging

import httpx

from ark_hr.config import Settings

log = logging.getLogger("ark_hr.mail")


def send_ready(settings: Settings, recipient: str, link: str) -> bool:
    if settings.phase < 2 or not settings.graph_sender or not settings.microsoft_enabled:
        log.info("batch-ready email skipped")
        return False
    token = _graph_token(settings)
    if not token:
        log.info("batch-ready email skipped")
        return False
    message = {
        "message": {
            "subject": "Your batch is ready",
            "body": {
                "contentType": "Text",
                "content": f"Your batch is ready.\n{link}\n",
            },
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        }
    }
    response = httpx.post(
        f"https://graph.microsoft.com/v1.0/users/{settings.graph_sender}/sendMail",
        headers={"Authorization": f"Bearer {token}"},
        json=message,
        timeout=30,
    )
    response.raise_for_status()
    return True


def _graph_token(settings: Settings) -> str:
    try:
        response = httpx.post(
            f"https://login.microsoftonline.com/{settings.tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("access_token") or ""
    except httpx.HTTPError:
        return ""
