"""The verify CLI rejects bad input without hiding verifier programming errors."""

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from privatelabbench import cli
from privatelabbench.reports.integrity import attach_integrity_metadata

ROOT = Path(__file__).resolve().parents[1]


def _args(path, *, json_output=True, **kwargs):
    flags = ["verify", str(path)]
    if json_output:
        flags.append("--json")
    for name, value in kwargs.items():
        flags.extend(["--" + name.replace("_", "-"), value])
    return cli.build_parser().parse_args(flags)


def _input(tmp_path, kind):
    source = tmp_path / "artifact.json"
    if kind == "directory":
        source.mkdir()
    elif kind == "malformed":
        source.write_text('{"integrity":', encoding="utf-8")
    elif kind == "encoding":
        source.write_bytes(b'{"value":"\xff"}')
    elif kind != "missing":
        raise AssertionError(kind)
    return source


def _run_cli(source, *, json_output=True, subcommand="verify", **kwargs):
    command = [sys.executable, "-m", "privatelabbench.cli", subcommand, str(source)]
    if json_output:
        command.append("--json")
    for name, value in kwargs.items():
        command.extend(["--" + name.replace("_", "-"), value])
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONNOUSERSITE="1")
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("missing", "unreadable_artifact"),
        ("directory", "unreadable_artifact"),
        ("malformed", "invalid_artifact_json"),
        ("encoding", "invalid_artifact_encoding"),
    ],
)
def test_verify_api_rejects_invalid_input(tmp_path, capsys, kind, reason):
    source = _input(tmp_path, kind)
    assert cli.verify_any_command(_args(source)) == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["valid"] is False
    assert result["reason"] == reason
    assert isinstance(result["error"], str) and result["error"]
    assert result["path"] == str(source)
    assert captured.err == ""


@pytest.mark.parametrize("json_output", [True, False])
@pytest.mark.parametrize("kind", ["missing", "directory", "malformed", "encoding"])
def test_verify_actual_cli_rejects_invalid_input(tmp_path, kind, json_output):
    result = _run_cli(_input(tmp_path, kind), json_output=json_output)
    assert result.returncode == 1
    assert result.stderr == ""
    assert "Traceback" not in result.stdout
    if json_output:
        payload = json.loads(result.stdout)
        assert payload["valid"] is False
        assert payload["error"]
    else:
        assert "Hash valid: False" in result.stdout
        assert "Error: " in result.stdout


@pytest.mark.parametrize("json_output", [True, False])
def test_verify_api_handles_permission_denied(
    tmp_path, capsys, monkeypatch, json_output
):
    source = tmp_path / "private.json"

    def denied(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "read_text", denied)
    assert cli.verify_any_command(_args(source, json_output=json_output)) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    if json_output:
        result = json.loads(captured.out)
        assert result["reason"] == "unreadable_artifact"
        assert result["valid"] is False
        assert "Permission denied" in result["error"]
    else:
        assert "Permission denied" in captured.out


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file-sharing denial")
def test_verify_actual_cli_handles_unreadable_input(tmp_path):
    from ctypes import wintypes

    source = tmp_path / "locked.json"
    source.write_text("{}", encoding="utf-8")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(source), 0x80000000, 0, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    try:
        result = _run_cli(source)
    finally:
        assert kernel.CloseHandle(handle)
    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["reason"] == "unreadable_artifact"
    assert payload["valid"] is False and payload["error"]


@pytest.mark.parametrize(
    ("schema", "verifier"),
    [
        ("evaluation-receipt/v1", "verify_receipt"),
        ("run-manifest/v0.1", "verify_run_manifest"),
        ("report/v1", "verify_report"),
    ],
)
def test_verify_handles_read_failures_during_dispatch(
    tmp_path, capsys, monkeypatch, schema, verifier
):
    source = tmp_path / "changed.json"
    source.write_text(json.dumps({"schema_version": schema}), encoding="utf-8")

    def disappeared(*args, **kwargs):
        raise FileNotFoundError(2, "No such file", str(source))

    monkeypatch.setattr(cli, verifier, disappeared)
    assert cli.verify_any_command(_args(source)) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "unreadable_artifact"


def test_verify_does_not_catch_programming_errors(tmp_path, monkeypatch):
    source = tmp_path / "report.json"
    source.write_text("{}", encoding="utf-8")

    def broken(*args, **kwargs):
        raise TypeError("verifier programming error")

    monkeypatch.setattr(cli, "verify_report", broken)
    with pytest.raises(TypeError, match="verifier programming error"):
        cli.verify_any_command(_args(source))


def test_verify_cli_preserves_success_tamper_and_hmac_results(tmp_path):
    source = tmp_path / "signed.json"
    payload = attach_integrity_metadata({"metric": 0.75}, signing_secret="test-secret")
    source.write_text(json.dumps(payload), encoding="utf-8")
    valid = _run_cli(source, signing_secret="test-secret")
    assert valid.returncode == 0
    assert json.loads(valid.stdout)["signature_valid"] is True
    wrong = _run_cli(source, signing_secret="wrong-secret")
    assert wrong.returncode == 1
    assert json.loads(wrong.stdout)["reason"] == "signature_check_failed"
    payload["metric"] = 0.1
    source.write_text(json.dumps(payload), encoding="utf-8")
    tampered = _run_cli(source, signing_secret="test-secret")
    assert tampered.returncode == 1
    assert json.loads(tampered.stdout)["reason"] == "hash_check_failed"
    assert not valid.stderr and not wrong.stderr and not tampered.stderr


def test_verify_invalid_utf8_trust_store_fails_without_traceback(tmp_path, capsys):
    source = tmp_path / "unsigned.json"
    source.write_text(json.dumps(attach_integrity_metadata({})), encoding="utf-8")
    trust = tmp_path / "trust.yaml"
    trust.write_bytes(b"\xff")
    args = _args(source, trust_store=str(trust))
    args.require_trusted_signer = True
    assert cli.verify_any_command(args) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["valid"] is False
    assert captured.err == ""


def test_verifier_imports_from_this_checkout():
    assert Path(cli.__file__).resolve() == ROOT / "privatelabbench" / "cli.py"


@pytest.mark.parametrize("subcommand", ["verify-report", "verify-manifest"])
@pytest.mark.parametrize("kind", ["missing", "directory", "malformed", "encoding"])
def test_legacy_verify_actual_cli_rejects_invalid_input(tmp_path, subcommand, kind):
    result = _run_cli(_input(tmp_path, kind), subcommand=subcommand, json_output=False)
    assert result.returncode == 1
    assert result.stderr == ""
    assert "Traceback" not in result.stdout
    assert "Valid: False" in result.stdout
    assert "Error: " in result.stdout


@pytest.mark.parametrize("subcommand", ["verify-report", "verify-manifest"])
@pytest.mark.parametrize("payload", [{}, {"integrity": []}, [], None])
def test_legacy_verify_actual_cli_handles_sparse_or_wrong_shape(
    tmp_path, subcommand, payload
):
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    result = _run_cli(source, subcommand=subcommand, json_output=False)
    assert result.returncode == 1
    assert result.stderr == ""
    assert "Traceback" not in result.stdout
    assert "Valid: False" in result.stdout
    reason = (
        "missing_integrity_metadata"
        if isinstance(payload, dict)
        else "invalid_artifact_shape"
    )
    assert f"Reason: {reason}" in result.stdout


@pytest.mark.parametrize("payload", [[], None, "text", 42])
def test_generic_verify_rejects_non_object_json(tmp_path, capsys, payload):
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    assert cli.verify_any_command(_args(source)) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["reason"] == "invalid_artifact_shape"
    assert result["valid"] is False and result["error"]


@pytest.mark.parametrize("subcommand", ["verify", "verify-manifest"])
@pytest.mark.parametrize(
    "fields", [{"run": []}, {"artifacts": {}}, {"artifacts": [None]}]
)
def test_manifest_json_shape_is_validated_at_cli_boundary(
    tmp_path, capsys, subcommand, fields
):
    source = tmp_path / "manifest.json"
    source.write_text(
        json.dumps({"schema_version": "run-manifest/v0.1", **fields}), encoding="utf-8"
    )
    args = cli.build_parser().parse_args([subcommand, str(source)])
    command = (
        cli.verify_any_command
        if subcommand == "verify"
        else cli.verify_manifest_command
    )
    assert command(args) == 1
    captured = capsys.readouterr()
    assert "Reason: invalid_artifact_shape" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("subcommand", ["verify-report", "verify-manifest"])
@pytest.mark.parametrize("exception", [TypeError, KeyError, AttributeError])
def test_legacy_verify_does_not_swallow_programming_errors(
    tmp_path, monkeypatch, subcommand, exception
):
    source = tmp_path / "valid-shape.json"
    source.write_text("{}", encoding="utf-8")

    def broken(*args, **kwargs):
        raise exception("programming error")

    verifier = (
        "verify_report" if subcommand == "verify-report" else "verify_run_manifest"
    )
    command = (
        cli.verify_report_command
        if subcommand == "verify-report"
        else cli.verify_manifest_command
    )
    monkeypatch.setattr(cli, verifier, broken)
    args = cli.build_parser().parse_args([subcommand, str(source)])
    with pytest.raises(exception, match="programming error"):
        command(args)


@pytest.mark.parametrize("subcommand", ["verify-report", "verify-manifest"])
def test_legacy_verify_preserves_success_output_and_signatures(tmp_path, subcommand):
    source = tmp_path / "signed.json"
    manifest = subcommand == "verify-manifest"
    data = (
        {"run": {"run_id": "test-run"}, "artifacts": []}
        if manifest
        else {"metric": 0.75}
    )
    payload = attach_integrity_metadata(data, signing_secret="test-secret")
    source.write_text(json.dumps(payload), encoding="utf-8")
    valid = _run_cli(
        source, subcommand=subcommand, json_output=False, signing_secret="test-secret"
    )
    prefix = (
        f"PrivateLabBench manifest verification\nManifest: {source}\nValid: True\nReason: ok\n"
        "Run ID: test-run\nManifest hash valid: True\nArtifact hashes valid: True\nReport integrity valid: True\n"
        if manifest
        else f"PrivateLabBench report verification\nReport: {source}\nValid: True\nReason: ok\nHash valid: True\n"
    )
    assert valid.returncode == 0 and valid.stderr == ""
    assert (
        valid.stdout
        == prefix
        + f"Signature valid: True\nPayload SHA256: {payload['integrity']['payload_sha256']}\n"
    )
    wrong = _run_cli(
        source, subcommand=subcommand, json_output=False, signing_secret="wrong-secret"
    )
    assert wrong.returncode == 1 and wrong.stderr == ""
    assert "Signature valid: False" in wrong.stdout
    if manifest:
        payload["run"]["run_id"] = "changed"
    else:
        payload["metric"] = 0.1
    source.write_text(json.dumps(payload), encoding="utf-8")
    tampered = _run_cli(
        source, subcommand=subcommand, json_output=False, signing_secret="test-secret"
    )
    assert tampered.returncode == 1 and tampered.stderr == ""
    assert (
        "manifest_hash_check_failed" if manifest else "hash_check_failed"
    ) in tampered.stdout


@pytest.mark.parametrize("verifier", [cli.verify_report, cli.verify_run_manifest])
@pytest.mark.parametrize(
    ("kind", "exception"),
    [
        ("missing", OSError),
        ("malformed", json.JSONDecodeError),
        ("encoding", UnicodeDecodeError),
    ],
)
def test_direct_low_level_verifier_input_exceptions_are_unchanged(
    tmp_path, verifier, kind, exception
):
    with pytest.raises(exception):
        verifier(_input(tmp_path, kind))
