"""Linux/gVisor inference for untrusted Python scripts; outputs remain local."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from privatelabbench.core.local_io import atomic_write_csv, validate_output_paths
from privatelabbench.privacy.export import atomic_write_json

MAX_MODEL_BYTES = 8 * 1024 * 1024
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_VALUES = 1_000_000
DOCKER_HOST = "unix:///var/run/docker.sock"


class SandboxError(ValueError):
    """A local rejection; never includes submitted stdout/stderr or private rows."""


@dataclass(frozen=True)
class SandboxLimits:
    seconds: int = 30
    memory_mb: int = 512
    cpus: float = 1.0
    pids: int = 64
    output_bytes: int = 4 * 1024 * 1024
    scratch_mb: int = 16

    def __post_init__(self):
        for name, low, high in (
            ("seconds", 1, 300),
            ("memory_mb", 64, 4096),
            ("pids", 16, 256),
            ("output_bytes", 1024, 16 * 1024 * 1024),
            ("scratch_mb", 1, 64),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise SandboxError(f"Unsupported sandbox limit: {name}")
        if not math.isfinite(self.cpus) or not 0.1 <= self.cpus <= 4:
            raise SandboxError("Unsupported sandbox CPU limit")


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SandboxError("Duplicate sandbox JSON keys")
        result[key] = value
    return result


def _decode_predictions(content, *, rows, task_type):
    try:
        payload = json.loads(content, object_pairs_hook=_json_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise SandboxError(
            "Sandbox output is not the required prediction JSON"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {"predictions"}:
        raise SandboxError("Sandbox output must contain only predictions")
    values = payload["predictions"]
    if (
        not isinstance(values, list)
        or len(values) != rows
        or any(type(x) not in (int, float) for x in values)
    ):
        raise SandboxError("Sandbox must return one numeric prediction per row")
    try:
        predictions = np.asarray(values, dtype=float)
    except (ValueError, OverflowError) as exc:
        raise SandboxError(
            "Sandbox predictions are outside the numeric domain"
        ) from exc
    if not np.isfinite(predictions).all():
        raise SandboxError("Sandbox predictions must be finite")
    if task_type == "classification" and (
        np.any(predictions < 0) or np.any(predictions > 1)
    ):
        raise SandboxError("Sandbox classification requires probabilities in [0, 1]")
    return predictions


class _Docker:
    def __init__(self, config):
        executable = shutil.which("docker")
        if sys.platform != "linux" or executable is None:
            raise SandboxError(
                "Sandbox execution requires Linux, Docker, and gVisor runsc"
            )
        self.prefix = [executable, "--host", DOCKER_HOST, "--config", str(config)]
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("DOCKER_")}

    def command(self, *args, allow_failure=False):
        try:
            result = subprocess.run(
                [*self.prefix, *args],
                env=self.env,
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxError("Local Docker control operation failed") from exc
        if not allow_failure and result.returncode:
            raise SandboxError("Local Docker control operation rejected")
        if len(result.stdout) + len(result.stderr) > 1024 * 1024:
            raise SandboxError("Docker control response exceeds its limit")
        return result

    def json(self, *args):
        try:
            return json.loads(self.command(*args).stdout)
        except (ValueError, UnicodeError) as exc:
            raise SandboxError("Invalid local Docker control response") from exc


def _check_runtime(docker, image):
    info = docker.json("info", "--format", "{{json .}}")
    if info.get("OSType") != "linux" or "runsc" not in info.get("Runtimes", {}):
        raise SandboxError("gVisor runsc is required; no ordinary-container fallback")
    if not all(
        info.get(key) is True
        for key in (
            "MemoryLimit",
            "SwapLimit",
            "CpuCfsQuota",
            "PidsLimit",
        )
    ):
        raise SandboxError(
            "Docker must enforce memory, swap, CPU, and PID cgroup limits"
        )
    record = docker.json("image", "inspect", image)
    if (
        not isinstance(record, list)
        or len(record) != 1
        or record[0].get("Id") != image
        or record[0].get("Os") != "linux"
        or record[0].get("Config", {}).get("Volumes")
    ):
        raise SandboxError("Use a reviewed local Linux image ID without image volumes")


def _create_args(name, image, model_path, limits):
    return [
        "create",
        "--name",
        name,
        "--label",
        f"privatelabbench.sandbox={name}",
        "--runtime",
        "runsc",
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
        "--ipc",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--user",
        "65534:65534",
        "--pids-limit",
        str(limits.pids),
        "--memory",
        f"{limits.memory_mb}m",
        "--memory-swap",
        f"{limits.memory_mb}m",
        "--cpus",
        str(limits.cpus),
        "--ulimit",
        "nofile=64:64",
        "--ulimit",
        "core=0:0",
        "--ulimit",
        f"nproc={limits.pids}:{limits.pids}",
        "--ulimit",
        f"fsize={limits.scratch_mb * 1024 * 1024}",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={limits.scratch_mb}m,mode=1777",
        "--mount",
        f"type=bind,src={model_path},dst=/model.py,readonly",
        "--log-driver",
        "none",
        "--no-healthcheck",
        "--stop-timeout",
        "1",
        "--workdir",
        "/tmp",
        "--hostname",
        "plb-sandbox",
        "--interactive",
        "--entrypoint",
        "/usr/bin/env",
        image,
        "-i",
        "PATH=/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE=1",
        "/usr/local/bin/python",
        "-I",
        "-B",
        "/model.py",
    ]


def _start(docker, name, content, limits):
    """Bound both output streams and wall time even if stdin is never consumed."""
    process = subprocess.Popen(
        [*docker.prefix, "start", "--attach", "--interactive", name],
        env=docker.env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    overflow = threading.Event()
    lock = threading.Lock()
    total = 0
    stdout = bytearray()

    def read(stream, keep):
        nonlocal total
        try:
            while chunk := stream.read(8192):
                with lock:
                    total += len(chunk)
                    if total > limits.output_bytes:
                        overflow.set()
                        return
                    if keep:
                        stdout.extend(chunk)
        finally:
            stream.close()

    def write():
        try:
            remaining = memoryview(content)
            while remaining:
                sent = process.stdin.write(remaining)
                if not sent:
                    break
                remaining = remaining[sent:]
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    threads = [
        threading.Thread(target=read, args=(process.stdout, True), daemon=True),
        threading.Thread(target=read, args=(process.stderr, False), daemon=True),
        threading.Thread(target=write, daemon=True),
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + limits.seconds
    try:
        while process.poll() is None:
            if overflow.is_set() or time.monotonic() >= deadline:
                raise SandboxError("Sandbox exceeded its output or wall-time limit")
            time.sleep(0.02)
        for thread in threads:
            thread.join(timeout=1)
        if overflow.is_set() or any(thread.is_alive() for thread in threads):
            raise SandboxError("Sandbox output did not complete within its limits")
        if process.returncode:
            raise SandboxError(
                f"Sandbox model execution failed (exit {process.returncode}); untrusted logs withheld"
            )
        state = docker.json("inspect", "--format", "{{json .State}}", name)
        if (
            state.get("Status") != "exited"
            or state.get("ExitCode") != 0
            or state.get("OOMKilled")
        ):
            raise SandboxError("Sandbox model failed its runtime exit checks")
        return bytes(stdout)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=1)


def run_sandbox(
    model: bytes,
    features,
    *,
    model_sha256: str,
    runtime_image: str,
    task_type="regression",
    limits=None,
):
    """Execute a pinned script in gVisor; never execute or deserialize it on host.

    The operator reviews the runtime image and host. The script is untrusted.
    Predictions are a potential data-exfiltration channel and MUST remain local.
    """
    limits = limits or SandboxLimits()
    if not isinstance(limits, SandboxLimits):
        raise SandboxError("Explicit SandboxLimits required")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", runtime_image):
        raise SandboxError("An immutable local runtime image ID is required")
    if not isinstance(model, bytes) or not 0 < len(model) <= MAX_MODEL_BYTES:
        raise SandboxError("Model script exceeds its byte limit or is empty")
    if (
        not re.fullmatch(r"[0-9a-f]{64}", model_sha256)
        or sha256(model).hexdigest() != model_sha256
    ):
        raise SandboxError("Model script digest mismatch")
    if task_type not in {"regression", "classification"}:
        raise SandboxError("Declare regression or binary classification")
    matrix = np.asarray(features)
    if (
        matrix.ndim != 2
        or not all(matrix.shape)
        or matrix.size > MAX_VALUES
        or matrix.dtype.kind not in "iuf"
        or not np.isfinite(matrix).all()
    ):
        raise SandboxError("Sandbox requires a bounded finite numeric feature matrix")
    request = json.dumps({"features": matrix.tolist()}, allow_nan=False).encode()
    if len(request) > MAX_INPUT_BYTES:
        raise SandboxError("Sandbox input exceeds its byte limit")
    # A fresh host snapshot prevents source-file mutation and mount-directory leaks.
    # /tmp is deliberate: mount option separators in caller paths are never used.
    if sys.platform != "linux":
        raise SandboxError("Sandbox execution requires a Linux host")
    with tempfile.TemporaryDirectory(prefix="plb-sandbox-", dir="/tmp") as folder:
        root = Path(folder)
        script = root / "model.py"
        script.write_bytes(model)
        script.chmod(0o444)
        docker = _Docker(root / "docker-config")
        _check_runtime(docker, runtime_image)
        name = "plb-sandbox-" + uuid4().hex
        created = False
        try:
            container = docker.command(
                *_create_args(name, runtime_image, script, limits)
            )
            created = True
            if not re.fullmatch(rb"[0-9a-f]{64}\s*", container.stdout):
                raise SandboxError("Invalid sandbox container identity")
            content = _start(docker, name, request, limits)
            return _decode_predictions(content, rows=len(matrix), task_type=task_type)
        finally:
            # The random name is ours even if create times out after daemon acceptance.
            removed = docker.command("rm", "--force", name, allow_failure=True)
            if created and removed.returncode:
                raise SandboxError(
                    f"Sandbox cleanup failed; remove owned container {name}"
                )


def sandbox_command(args):
    """Local-only CLI with fresh output paths and no automatic public export."""
    try:
        model, data, output = map(Path, (args.model, args.data, args.output))
        provenance = output.with_suffix(".sandbox.json")
        validate_output_paths([model, data], [output, provenance])
        if output.exists() or provenance.exists():
            raise SandboxError("Choose fresh local prediction and provenance paths")

        def snapshot(path, maximum):
            with path.open("rb") as handle:
                content = handle.read(maximum + 1)
            if len(content) > maximum:
                raise SandboxError("Sandbox input exceeds its byte limit")
            return content

        if (
            len(set(args.feature)) != len(args.feature)
            or args.sample_id in args.feature
        ):
            raise SandboxError(
                "Feature roles must be unique and separate from sample IDs"
            )
        frame = pd.read_csv(
            BytesIO(snapshot(data, MAX_INPUT_BYTES)), dtype={args.sample_id: "string"}
        )
        if not {args.sample_id, *args.feature} <= set(frame) or frame.empty:
            raise SandboxError("Missing declared sample-ID/features or empty input")
        ids = frame[args.sample_id]
        if ids.isna().any() or ids.str.strip().eq("").any() or ids.duplicated().any():
            raise SandboxError("Sample IDs must be complete and unique")
        values = frame[args.feature].to_numpy()
        limits = SandboxLimits(seconds=args.seconds, memory_mb=args.memory_mb)
        predictions = run_sandbox(
            snapshot(model, MAX_MODEL_BYTES),
            values,
            model_sha256=args.model_sha256,
            runtime_image=args.runtime_image,
            task_type=args.task_type,
            limits=limits,
        )
        atomic_write_csv(
            output, pd.DataFrame({"sample_id": ids, "prediction": predictions})
        )
        atomic_write_json(
            provenance,
            {
                "schema_version": "sandbox-scoring-provenance/v1",
                "scope": "local",
                "isolation": "gvisor_runsc",
                "runtime_image": args.runtime_image,
                "model_sha256": args.model_sha256,
                "prediction_sha256": sha256(output.read_bytes()).hexdigest(),
                "task_type": args.task_type,
                "features": args.feature,
                "limits": asdict(limits),
                "network": "none",
                "n_samples": len(frame),
            },
        )
        print(f"Local sandbox predictions: {output}")
        print(
            "Predictions and provenance remain private; review aggregate release separately."
        )
        return 0
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
        print("Sandbox execution rejected; no untrusted logs are displayed.")
        return 2
