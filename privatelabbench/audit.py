from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


def write_audit_event(path: str, *, event_type: str, payload: Mapping[str, Any]) -> Path:
    audit_path = Path(path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "event_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "payload": payload,
    }
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return audit_path
