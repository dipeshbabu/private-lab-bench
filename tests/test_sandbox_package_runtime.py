"""Actual multi-file gVisor execution; enabled by the required Linux runtime job."""

import json
import os
import subprocess
import sys
from hashlib import sha256

import numpy as np
import pandas as pd
import pytest
from test_sandbox_package import package

from privatelabbench.sandbox import (
    SandboxError,
    SandboxLimits,
    run_sandbox_package,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("PLB_SANDBOX_TESTS") != "1",
    reason="Dedicated Linux/gVisor integration job",
)


@pytest.fixture(scope="module")
def image():
    value = os.environ["PLB_SANDBOX_IMAGE"]
    assert value.startswith("sha256:")
    return value


def bundle(code=None):
    return package(
        {
            "scripts/predict.py": (
                code
                or """import json, os, sys
from pathlib import Path
from helper import score
assert __name__ == '__main__'
assert os.getuid() == 65534 and 'PLB_HOST_SECRET' not in os.environ
assert not Path('/var/run/docker.sock').exists()
for path in ('/model/weights.json', '/model/helper.py', '/model/new-file', '/etc/new-file'):
    try:
        open(path, 'w').write('forbidden')
    except OSError:
        pass
    else:
        raise AssertionError('model tree must remain read-only')
rows = json.load(sys.stdin)
assert set(rows) == {'features'}
weights = json.loads((Path(__file__).parent.parent / 'weights.json').read_text())
print(json.dumps({'predictions': [score(row, weights) for row in rows['features']]}))
"""
            ).encode(),
            "helper.py": b"def score(row, weights): return sum(a*b for a,b in zip(row, weights))\n",
            "weights.json": b"[2,3]",
        },
        entrypoint="scripts/predict.py",
    )


def execute(image, model, limits=None):
    return run_sandbox_package(
        model,
        [[1.0, 2.0], [3.0, 4.0]],
        model_sha256=sha256(model).hexdigest(),
        runtime_image=image,
        limits=limits or SandboxLimits(seconds=10, memory_mb=128),
    )


def test_real_package_imports_weights_and_readonly_mount(image):
    np.testing.assert_equal(execute(image, bundle()), [8.0, 18.0])


@pytest.mark.parametrize(
    "code",
    [
        "while True: pass",
        "import sys\nwhile True: sys.stdout.write('private'*8192); sys.stdout.flush()",
        'print(\'{"predictions":[1,2],"private":"hidden"}\')',
    ],
)
def test_real_package_attacks_remain_bounded_and_owned_containers_are_removed(
    image, code
):
    limits = SandboxLimits(seconds=3, memory_mb=64, output_bytes=4096)
    np.testing.assert_equal(
        execute(image, bundle("print('{\"predictions\":[0,0]}')"), limits), [0, 0]
    )
    command = [
        "docker",
        "--host",
        "unix:///var/run/docker.sock",
        "ps",
        "-aq",
        "--filter",
        "label=privatelabbench.sandbox",
    ]
    before = subprocess.check_output(command)
    with pytest.raises(SandboxError) as caught:
        execute(image, bundle(code), limits)
    assert "private" not in str(caught.value)
    assert subprocess.check_output(command) == before


def test_real_package_cli_keeps_predictions_and_provenance_local(image, tmp_path):
    model = tmp_path / "model.zip"
    model.write_bytes(bundle())
    data = tmp_path / "private.csv"
    pd.DataFrame(
        {
            "sample_id": ["private-a", "private-b"],
            "x": [1, 3],
            "y": [2, 4],
            "target": [999, 999],
        }
    ).to_csv(data, index=False)
    output = tmp_path / "predictions.csv"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "privatelabbench",
            "sandbox-score",
            "--model-package",
            str(model),
            "--data",
            str(data),
            "--output",
            str(output),
            "--model-sha256",
            sha256(model.read_bytes()).hexdigest(),
            "--runtime-image",
            image,
            "--feature",
            "x",
            "--feature",
            "y",
            "--seconds",
            "10",
            "--memory-mb",
            "128",
            "--task-type",
            "regression",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert "Predictions and provenance remain private" in completed.stdout
    result = pd.read_csv(output)
    np.testing.assert_equal(result.prediction.to_numpy(), [8.0, 18.0])
    provenance = json.loads(output.with_suffix(".sandbox.json").read_text())
    assert (
        provenance["scope"] == "local"
        and provenance["model_format"] == "sandbox-model-package/v1"
    )
    assert not list(tmp_path.glob("*.shareable.json"))
