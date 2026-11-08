import copy
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/check_release_readiness.py"
SPEC = importlib.util.spec_from_file_location("release_readiness", PATH)
readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readiness)


def record():
    return {
        "schema_version": "release-readiness/v1",
        "baseline_version": "0.1.6",
        "milestone": "0.1.7",
        "requirements": {
            name: {"status": "complete", "evidence": ["test-fixture-only"]}
            for name in readiness.REQUIREMENTS
        },
    }


@pytest.mark.parametrize(
    "version", ["0.1.7", "0.1.7rc1", "0.1.8", "1.0.0", "0.1.6.post1"]
)
@pytest.mark.parametrize("status", ["pending", "in_progress", "unavailable"])
def test_a_new_tag_or_later_version_cannot_bypass_an_incomplete_requirement(
    version, status
):
    value = record()
    value["requirements"]["independent_privacy_sandbox_audit"] = {
        "status": status,
        "evidence": [],
    }
    with pytest.raises(ValueError, match="Release hold"):
        readiness.verify_readiness(version, value)


@pytest.mark.parametrize("version", ["0.1.6", "0.1.5"])
def test_the_hold_does_not_retroactively_block_historical_release_reruns(version):
    value = record()
    value["requirements"]["gpu_runtime_validation"] = {
        "status": "unavailable",
        "evidence": [],
    }
    assert readiness.verify_readiness(version, value)["status"] == "historical_release"


def test_every_requirement_needs_evidence_before_readiness_can_pass():
    value = record()
    assert readiness.verify_readiness("0.1.7", value)["status"] == "ready"
    for name in readiness.REQUIREMENTS:
        invalid = copy.deepcopy(value)
        invalid["requirements"][name]["evidence"] = []
        with pytest.raises(ValueError, match="needs evidence"):
            readiness.verify_readiness("0.1.7", invalid)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "bad_status",
        "evidence_string",
        "empty_reference",
        "schema",
        "old_milestone",
        "unknown_field",
    ],
)
def test_malformed_or_incomplete_records_fail_closed(mutation):
    value = record()
    entries = value["requirements"]
    name = next(iter(entries))
    if mutation == "missing":
        entries.pop(name)
    elif mutation == "extra":
        entries["unknown"] = entries[name]
    elif mutation == "bad_status":
        entries[name]["status"] = "waived"
    elif mutation == "evidence_string":
        entries[name]["evidence"] = "not-a-list"
    elif mutation == "empty_reference":
        entries[name]["evidence"] = [" "]
    elif mutation == "schema":
        value["schema_version"] = "unknown"
    elif mutation == "old_milestone":
        value["milestone"] = "0.1.5"
    else:
        value["allow_release"] = True
    with pytest.raises(ValueError):
        readiness.verify_readiness("0.1.7", value)


def test_committed_record_keeps_v017_on_hold():
    path = PATH.parents[1] / "audit/release-readiness.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert (
        value["requirements"]["independent_privacy_sandbox_audit"]["status"]
        == "unavailable"
    )
    assert value["requirements"]["gpu_runtime_validation"]["status"] == "unavailable"
    with pytest.raises(ValueError, match="Release hold"):
        readiness.verify_readiness("0.1.7", value)
