"""CV text may be sent only to a model hosted inside Group Arkays."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from ark_hr.config import BLOCKED_AI_HOSTS


def assert_private_ai_url(url: str, allowlist: tuple[str, ...] = ()) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("The AI runtime URL is not a valid http(s) address.")
    host = parsed.hostname.lower().rstrip(".")
    for blocked in BLOCKED_AI_HOSTS:
        if host == blocked or host.endswith("." + blocked) or blocked in host:
            raise ValueError(
                "CV data cannot be sent to a third-party AI service. "
                "Use a self-hosted open-source model."
            )
    if host in allowlist or any(host == item or host.endswith("." + item) for item in allowlist):
        return host
    if host in ("localhost", "host.docker.internal") or host.endswith(".internal"):
        return host
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError(
            f"The AI host '{host}' is not a private Group Arkays address. "
            "Add it to ARK_HR_AI_HOST_ALLOWLIST only if it is inside Group Arkays."
        ) from exc
    if not (ip.is_private or ip.is_loopback):
        raise ValueError("The AI host must be a private or loopback address.")
    return host
