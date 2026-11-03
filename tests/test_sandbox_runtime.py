"""Actual adversarial gVisor checks; required by the dedicated Linux CI job."""

import os
import subprocess
import time
from hashlib import sha256

import numpy as np
import pytest

from privatelabbench.sandbox import SandboxError, SandboxLimits, run_sandbox

pytestmark = pytest.mark.skipif(
    os.environ.get("PLB_SANDBOX_TESTS") != "1",
    reason="Dedicated Linux/gVisor integration job",
)


@pytest.fixture(scope="module")
def image():
    value = os.environ["PLB_SANDBOX_IMAGE"]
    assert value.startswith("sha256:")
    return value


def execute(image, code, *, limits=None):
    model = code.encode()
    return run_sandbox(
        model,
        [[1.0, 2.0], [3.0, 4.0]],
        model_sha256=sha256(model).hexdigest(),
        runtime_image=image,
        limits=limits or SandboxLimits(seconds=10, memory_mb=128),
    )


def test_real_inference_and_restrictions(image):
    code = """import json, os, resource, socket, sys
assert os.getuid() == 65534
assert resource.getrlimit(resource.RLIMIT_NPROC) == (64, 64)
assert not os.path.exists("/var/run/docker.sock")
assert "PLB_HOST_SECRET" not in os.environ
assert "CapEff:\\t0000000000000000" in open("/proc/self/status").read()
for path in ("/model.py", "/etc/escape", "/root/escape"):
    try:
        open(path, "w").write("escape")
    except OSError:
        pass
    else:
        raise AssertionError("filesystem restriction failed")
try:
    socket.create_connection(("1.1.1.1", 443), timeout=.5)
except OSError:
    pass
else:
    raise AssertionError("egress was allowed")
data = json.load(sys.stdin)
assert set(data) == {"features"}
print(json.dumps({"predictions": [sum(row) for row in data["features"]]}))
"""
    np.testing.assert_equal(execute(image, code), [3.0, 7.0])


@pytest.mark.parametrize(
    "code",
    [
        'import sys\nwhile True: sys.stdout.write("x" * 8192); sys.stdout.flush()',
        'import sys\nwhile True: sys.stderr.write("PRIVATE" * 8192); sys.stderr.flush()',
        "while True: pass",
        "import time\nx=bytearray(1024*1024*1024)\ntime.sleep(20)",
        'print(\'{"predictions":[1,2],"private":"leak"}\')',
    ],
)
def test_real_resource_and_output_attacks_are_rejected_and_cleaned(image, code):
    limits = SandboxLimits(seconds=3, memory_mb=64, output_bytes=4096)
    # An unavailable runtime or a policy too tight to start Python must not make
    # the negative security tests pass without executing their attack scripts.
    np.testing.assert_equal(
        execute(image, "print('{\"predictions\":[0,0]}')", limits=limits), [0, 0]
    )
    before = subprocess.check_output(
        [
            "docker",
            "--host",
            "unix:///var/run/docker.sock",
            "ps",
            "-aq",
            "--filter",
            "label=privatelabbench.sandbox",
        ]
    )
    started = time.monotonic()
    with pytest.raises(SandboxError) as caught:
        execute(image, code, limits=limits)
    assert "PRIVATE" not in str(caught.value) and "leak" not in str(caught.value)
    assert time.monotonic() - started < 30
    after = subprocess.check_output(
        [
            "docker",
            "--host",
            "unix:///var/run/docker.sock",
            "ps",
            "-aq",
            "--filter",
            "label=privatelabbench.sandbox",
        ]
    )
    assert after == before


def test_fork_limit_is_enforced(image):
    code = """import errno, json, os, time
children = []
failure = 0
try:
    for _ in range(100):
        pid = os.fork()
        if pid == 0:
            time.sleep(10)
            os._exit(0)
        children.append(pid)
except OSError as exc:
    failure = exc.errno
finally:
    for pid in children:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
print(json.dumps({"predictions":[len(children), failure]}))
"""
    result = execute(image, code, limits=SandboxLimits(seconds=10, memory_mb=512))
    assert result[0] < 64
    assert result[1] == 11  # EAGAIN: the per-user process limit was reached.


def test_large_stdin_is_completely_delivered(image):
    model = b'import json, sys\nrows=json.load(sys.stdin)["features"]\nprint(json.dumps({"predictions":[sum(row) for row in rows]}))\n'
    result = run_sandbox(
        model,
        np.ones((1024, 64)),
        model_sha256=sha256(model).hexdigest(),
        runtime_image=image,
        limits=SandboxLimits(seconds=10, memory_mb=256),
    )
    np.testing.assert_equal(result, np.full(1024, 64.0))


def test_ignored_large_stdin_cannot_block_timeout_cleanup(image):
    model = b"while True: pass\n"
    started = time.monotonic()
    with pytest.raises(SandboxError, match="wall-time"):
        run_sandbox(
            model,
            np.zeros((8000, 100)),
            model_sha256=sha256(model).hexdigest(),
            runtime_image=image,
            limits=SandboxLimits(seconds=3, memory_mb=128),
        )
    assert time.monotonic() - started < 30
    remaining = subprocess.check_output(
        [
            "docker",
            "--host",
            "unix:///var/run/docker.sock",
            "ps",
            "-aq",
            "--filter",
            "label=privatelabbench.sandbox",
        ]
    )
    assert not remaining.strip()
