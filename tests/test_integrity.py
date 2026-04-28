import json

from privatelabbench.privacy.dp import PrivacyConfig
from privatelabbench.reports.integrity import verify_report
from privatelabbench.reports.json import write_json_report


def test_json_report_has_integrity_metadata(tmp_path):
    path = tmp_path / "report.json"
    write_json_report(
        str(path),
        report_type="unit_test",
        result={"metric": 1.0},
        privacy_config=PrivacyConfig(mode="none"),
        config_snapshot={"project": "demo"},
    )
    payload = json.loads(path.read_text())
    assert payload["schema_version"] == "0.2"
    assert "integrity" in payload
    assert "payload_sha256" in payload["integrity"]
    assert payload["config_snapshot"]["project"] == "demo"
    assert verify_report(str(path))["valid"] is True


def test_signed_report_verification(tmp_path):
    path = tmp_path / "signed_report.json"
    write_json_report(
        str(path),
        report_type="unit_test",
        result={"metric": 1.0},
        privacy_config=PrivacyConfig(mode="none"),
        signing_secret="secret",
    )
    assert verify_report(str(path), signing_secret="secret")["valid"] is True
    assert verify_report(str(path), signing_secret="wrong")["valid"] is False


def test_tampered_report_fails_verification(tmp_path):
    path = tmp_path / "report.json"
    write_json_report(
        str(path),
        report_type="unit_test",
        result={"metric": 1.0},
        privacy_config=PrivacyConfig(mode="none"),
    )
    payload = json.loads(path.read_text())
    payload["result"]["metric"] = 999
    path.write_text(json.dumps(payload, indent=2))
    assert verify_report(str(path))["valid"] is False
