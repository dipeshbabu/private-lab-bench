from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import numpy as np

from privatelabbench.privacy.dp import PrivacyConfig
from privatelabbench.reports.integrity import attach_integrity_metadata


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def build_report_payload(
    *,
    report_type: str,
    result: Mapping[str, Any] | Any,
    privacy_config: PrivacyConfig,
    extra: Mapping[str, Any] | None = None,
    config_snapshot: Mapping[str, Any] | None = None,
    signing_secret: str | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "0.2",
        "run_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_type": report_type,
        "privacy": privacy_config.report_metadata(),
        "result": _json_safe(result),
    }
    if config_snapshot:
        payload["config_snapshot"] = _json_safe(config_snapshot)
    if extra:
        payload["extra"] = _json_safe(extra)
    return attach_integrity_metadata(payload, signing_secret=signing_secret)


def write_json_report(
    output_path: str,
    *,
    report_type: str,
    result: Mapping[str, Any] | Any,
    privacy_config: PrivacyConfig,
    extra: Mapping[str, Any] | None = None,
    config_snapshot: Mapping[str, Any] | None = None,
    signing_secret: str | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_report_payload(
        report_type=report_type,
        result=result,
        privacy_config=privacy_config,
        extra=extra,
        config_snapshot=config_snapshot,
        signing_secret=signing_secret,
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
