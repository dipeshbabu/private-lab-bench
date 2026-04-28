from __future__ import annotations

import os

try:
    from fastapi import Header, HTTPException, status
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Dashboard auth requires fastapi. Install with: pip install -e '.[api]'") from exc


DASHBOARD_API_KEY_ENV = "PRIVATELABBENCH_DASHBOARD_API_KEY"


def require_dashboard_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv(DASHBOARD_API_KEY_ENV)
    if expected and x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing dashboard API key.")
