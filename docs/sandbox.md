# Sandboxed model execution

`plb sandbox-score` runs an untrusted Python inference script inside gVisor's
`runsc` runtime on a Linux Docker host. This is separate from the trusted
in-process `plb score` interface. It is available in the development source and
will ship in the next feature release.

## Operator setup

The lab operator must maintain a Linux host, a local Docker Engine at
`/var/run/docker.sock`, and a reviewed gVisor installation. Follow the official
[gVisor installation](https://gvisor.dev/docs/user_guide/install/) and
[Docker setup](https://gvisor.dev/docs/user_guide/quick_start/docker/) guides.
Use a dedicated evaluation host for adversarial submissions. The operator,
Docker daemon, gVisor installation, and runtime image are trusted components.
The submitted script is untrusted.

Review an image containing `/usr/bin/env` and `/usr/local/bin/python`, plus any
needed model libraries. Pull or build it explicitly before evaluation, inspect
its contents, and record its immutable local image ID:

```sh
docker image inspect your-reviewed-runtime --format '{{.Id}}'
```

The executor accepts that `sha256:...` image ID, never a mutable tag, submitted
image, image build instruction, registry URL, or extra Docker flags. Images with
declared volumes are rejected. It does not pull images automatically. Windows,
remote daemons, missing gVisor, and missing resource controllers are rejected;
there is no fallback to ordinary containers or host Python execution.

## Script contract

The script receives one JSON object on stdin with an ordered `features` numeric
matrix. Sample IDs, targets, other CSV columns, host paths, credentials, and host
environment variables are not passed. It must print exactly one JSON object:

```python
import json
import sys

rows = json.load(sys.stdin)["features"]
print(json.dumps({"predictions": [sum(row) for row in rows]}))
```

Return one finite number per row, in input order. Binary classification requires
positive-class probabilities in `[0, 1]`. Extra fields, duplicate keys, extra log
text on stdout, nonfinite values, and missing predictions are rejected. Stderr is
discarded and shares the output byte cap; untrusted logs never appear in CLI
errors or shareable artifacts.

```sh
sha256sum submitted-model.py
plb sandbox-score --model submitted-model.py --model-sha256 MODEL_SHA256 \
  --runtime-image sha256:REVIEWED_IMAGE_ID --data local-input.csv \
  --feature feature_a --feature feature_b --task-type regression \
  --seconds 30 --memory-mb 512 --output outputs/sandbox-predictions.csv
```

Choose fresh prediction/provenance paths. The selected script is read into a
bounded snapshot, verified against its digest, and mounted as one read-only file.
It is never imported or deserialized by the host. The current contract supports
CPU Python scripts up to 8 MiB, which may embed model parameters. Large multi-file
checkpoints, accelerators, participant container images, and remote services are
outside this first executor.

## Enforced controls

Every run requests gVisor, a non-root UID, no Linux capabilities, no new
privileges, no network, no IPC sharing, a read-only root filesystem, and only the
script mount. Scratch space is a size-limited, non-executable tmpfs. Docker
memory/swap/CPU/PID limits and process/file descriptor/file-size limits constrain
resource use. A wall-time/output watchdog terminates execution and removes only
the uniquely named container created for that run. Cleanup failure is an error.

The default limits are 30 seconds, 512 MiB memory with swap disabled, one CPU,
64 processes, 16 MiB scratch space, and 4 MiB combined stdout/stderr. Numeric
input is limited to one million values and 64 MiB of encoded JSON. Public API
callers can choose bounded `SandboxLimits`; the CLI exposes time and memory.

Dedicated Linux CI installs a checksum-pinned gVisor release and tests real
inference, filesystem writes, network denial, host-environment isolation, output
flooding, timeouts, memory exhaustion, fork limits, and container cleanup. This
is regression evidence, not an independent security audit or proof against all
kernel/runtime vulnerabilities.

## Keep predictions private

The prediction CSV and `.sandbox.json` provenance are **local-only**. A malicious
model can encode feature values in valid numeric predictions, errors, timing, or
other observable behavior. Sandboxing restricts host access and direct egress;
it does not make arbitrary model outputs safe to disclose or guarantee absence
of covert channels.

The command never publishes a receipt or returns results to a model submitter.
Evaluate approved local predictions using the normal prediction-table workflow,
then review aggregate disclosure separately. Existing `owner_only` hidden
benchmark provenance remains restricted to the reviewed trusted scorer; sandbox
results do not silently gain that approval. Never treat an ordinary signed
receipt as remote attestation of this execution environment.
