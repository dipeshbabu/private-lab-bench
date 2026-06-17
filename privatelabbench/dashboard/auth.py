from __future__ import annotations

import json
import os

try:
    from fastapi import Header, HTTPException, Query, Request, status
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Dashboard auth requires fastapi. Install with: pip install -e '.[api]'") from exc


DASHBOARD_API_KEY_ENV = "PRIVATELABBENCH_DASHBOARD_API_KEY"
DASHBOARD_API_KEYS_ENV = "PRIVATELABBENCH_DASHBOARD_API_KEYS"
DASHBOARD_TRUSTED_IDENTITY_HEADER_ENV = "PRIVATELABBENCH_DASHBOARD_TRUSTED_IDENTITY_HEADER"
DASHBOARD_ALLOWED_IDENTITY_DOMAINS_ENV = "PRIVATELABBENCH_DASHBOARD_ALLOWED_IDENTITY_DOMAINS"


def _dashboard_api_keys() -> dict[str, str]:
    raw = os.getenv(DASHBOARD_API_KEYS_ENV, "").strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"{DASHBOARD_API_KEYS_ENV} must be a JSON object mapping organization id to API key.")
    return {str(key): str(value) for key, value in payload.items()}


def _provided_key(x_api_key: str | None = None, api_key: str | None = None) -> str | None:
    return x_api_key or api_key


def _global_key_valid(provided: str | None) -> bool:
    expected = os.getenv(DASHBOARD_API_KEY_ENV)
    return bool(expected and provided == expected)


def _trusted_identity_valid(request: Request) -> bool:
    header_name = os.getenv(DASHBOARD_TRUSTED_IDENTITY_HEADER_ENV, "").strip()
    if not header_name:
        return False
    identity = request.headers.get(header_name, "").strip()
    if not identity:
        return False
    allowed_domains = {
        domain.strip().lower()
        for domain in os.getenv(DASHBOARD_ALLOWED_IDENTITY_DOMAINS_ENV, "").split(",")
        if domain.strip()
    }
    if not allowed_domains:
        return True
    if "@" not in identity:
        return False
    return identity.rsplit("@", 1)[1].lower() in allowed_domains


def require_dashboard_api_key_for_org(
    organization_id: str,
    *,
    x_api_key: str | None = None,
    api_key: str | None = None,
) -> None:
    provided = _provided_key(x_api_key=x_api_key, api_key=api_key)
    if _global_key_valid(provided):
        return
    org_keys = _dashboard_api_keys()
    if not org_keys:
        return
    expected = org_keys.get(organization_id)
    if not expected or provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dashboard API key for organization.")


def require_dashboard_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
    api_key: str | None = Query(default=None),
) -> None:
    if _trusted_identity_valid(request):
        return
    provided = _provided_key(x_api_key=x_api_key, api_key=api_key)
    expected = os.getenv(DASHBOARD_API_KEY_ENV)
    org_keys = _dashboard_api_keys()
    trusted_identity_configured = bool(os.getenv(DASHBOARD_TRUSTED_IDENTITY_HEADER_ENV, "").strip())
    if not expected and not org_keys and not trusted_identity_configured:
        return
    if expected and provided == expected:
        return
    if org_keys and provided in set(org_keys.values()):
        return
    if expected or org_keys or trusted_identity_configured:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing dashboard API key.")
