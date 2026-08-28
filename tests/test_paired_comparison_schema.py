from __future__ import annotations

import json
from pathlib import Path

import privatelabbench


def test_paired_comparison_schema_is_bundled_and_versioned():
    package_root = Path(privatelabbench.__file__).resolve().parent
    schema_path = package_root / "data" / "schemas" / "paired-comparison-artifact-v1.schema.json"
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert payload["properties"]["schema_version"]["const"] == "paired-comparison-artifact/v1"
    assert payload["properties"]["shareable"]["properties"]["comparison_schema"]["const"] == "paired-comparison/v1"
