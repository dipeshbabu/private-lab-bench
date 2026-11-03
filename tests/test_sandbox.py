import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from privatelabbench import sandbox


@pytest.mark.parametrize(
    "content",
    [
        b'{"predictions": [1, 2], "logs": "private"}',
        b'{"predictions": [1]}',
        b'{"predictions": [true, false]}',
        b'{"predictions": [NaN, 0]}',
        b'{"predictions": [1e999, 0]}',
        b'{"predictions": ["secret", 0]}',
        b'{"predictions": [[1], [2]]}',
        b'{"predictions": [1,2], "predictions": [3,4]}',
        b'PRIVATE_LOG\n{"predictions": [1,2]}',
        b"[]",
    ],
)
def test_untrusted_output_is_strict_and_never_echoed(content):
    with pytest.raises(sandbox.SandboxError) as caught:
        sandbox._decode_predictions(content, rows=2, task_type="regression")
    assert "private" not in str(caught.value).lower()


def test_binary_probabilities_and_exact_row_count():
    np.testing.assert_equal(
        sandbox._decode_predictions(
            b'{"predictions":[0.1,0.8]}', rows=2, task_type="classification"
        ),
        [0.1, 0.8],
    )
    with pytest.raises(sandbox.SandboxError, match="probabilities"):
        sandbox._decode_predictions(
            b'{"predictions":[-1,2]}', rows=2, task_type="classification"
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"seconds": 0},
        {"memory_mb": 100000},
        {"cpus": float("nan")},
        {"pids": True},
        {"scratch_mb": 100000},
        {"output_bytes": -1},
    ],
)
def test_resource_policy_rejects_invalid_limits(kwargs):
    with pytest.raises(sandbox.SandboxError):
        sandbox.SandboxLimits(**kwargs)


def test_container_command_has_no_host_input_directory_or_network(tmp_path):
    limits = sandbox.SandboxLimits()
    script = tmp_path / "model.py"
    command = sandbox._create_args("owned", "sha256:" + "a" * 64, script, limits)
    for flag, value in [
        ("--runtime", "runsc"),
        ("--network", "none"),
        ("--user", "65534:65534"),
        ("--cap-drop", "ALL"),
        ("--memory-swap", "512m"),
    ]:
        assert command[command.index(flag) + 1] == value
    assert "--read-only" in command and "--no-healthcheck" in command
    assert command.count("--mount") == 1
    assert (
        command[command.index("--mount") + 1]
        == f"type=bind,src={script},dst=/model.py,readonly"
    )
    assert command[-6:] == [
        "PATH=/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE=1",
        "/usr/local/bin/python",
        "-I",
        "-B",
        "/model.py",
    ]


def test_missing_gvisor_never_falls_back_to_runc():
    class Docker:
        def json(self, *args):
            return {"OSType": "linux", "Runtimes": {"runc": {}}}

    with pytest.raises(sandbox.SandboxError, match="no ordinary-container fallback"):
        sandbox._check_runtime(Docker(), "sha256:" + "a" * 64)


def test_mismatched_digest_rejects_before_creating_a_container(monkeypatch):
    monkeypatch.setattr(sandbox, "_Docker", lambda _: pytest.fail("Docker was reached"))
    with pytest.raises(sandbox.SandboxError, match="digest"):
        sandbox.run_sandbox(
            b"untrusted",
            [[1.0, 2.0]],
            model_sha256="0" * 64,
            runtime_image="sha256:" + "a" * 64,
        )


def test_cli_preserves_inputs_and_fresh_outputs(tmp_path, monkeypatch, capsys):
    data = tmp_path / "input.csv"
    data.write_text("sample_id,target,feature\n001,9,2\n002,8,3\n")
    model = tmp_path / "model.py"
    model.write_bytes(b"untrusted model is never executed here")
    args = SimpleNamespace(
        model=str(model),
        data=str(data),
        output=str(tmp_path / "out.csv"),
        feature=["feature"],
        sample_id="sample_id",
        seconds=5,
        memory_mb=128,
        model_sha256=sha256(model.read_bytes()).hexdigest(),
        runtime_image="sha256:" + "a" * 64,
        task_type="regression",
    )

    def run(model, features, **kwargs):
        np.testing.assert_equal(features, [[2], [3]])  # labels/IDs were not passed
        return np.array([0.2, 0.3])

    monkeypatch.setattr(sandbox, "run_sandbox", run)
    assert sandbox.sandbox_command(args) == 0
    original = Path(args.output).read_bytes()
    assert b"target" not in original and b"feature" not in original
    metadata = json.loads(Path(args.output).with_suffix(".sandbox.json").read_text())
    assert metadata["scope"] == "local" and metadata["isolation"] == "gvisor_runsc"
    assert "input_sha256" not in metadata
    assert sandbox.sandbox_command(args) == 2
    assert Path(args.output).read_bytes() == original
    args.output = str(data)
    assert sandbox.sandbox_command(args) == 2
    assert data.read_text().startswith("sample_id,target,feature")
    assert "untrusted model" not in capsys.readouterr().out
