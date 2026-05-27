from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from typing import Any

from privatelabbench import __version__


CODE_REVISION_ENV = "PRIVATELABBENCH_CODE_REVISION"
RUNNER_IMAGE_DIGEST_ENV = "PRIVATELABBENCH_RUNNER_IMAGE_DIGEST"
ATTESTATION_ID_ENV = "PRIVATELABBENCH_ATTESTATION_ID"


def collect_runner_attestation() -> dict[str, Any]:
    """Collect a privacy-preserving runner provenance claim.

    This intentionally avoids hostnames, usernames, local paths, and environment
    dumps. Operators can inject immutable build metadata through environment
    variables when running managed or containerized runners.
    """

    claim: dict[str, Any] = {
        "schema_version": "runner-attestation/v0.1",
        "package": {"name": "private-lab-bench", "version": __version__},
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "major": sys.version_info.major,
            "minor": sys.version_info.minor,
            "micro": sys.version_info.micro,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
    }
    code_revision = os.getenv(CODE_REVISION_ENV)
    if code_revision:
        claim["code_revision"] = code_revision
    image_digest = os.getenv(RUNNER_IMAGE_DIGEST_ENV)
    if image_digest:
        claim["runner_image_digest"] = image_digest

    canonical = json.dumps(claim, sort_keys=True, separators=(",", ":"))
    claim["attestation_id"] = os.getenv(ATTESTATION_ID_ENV) or hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return claim
