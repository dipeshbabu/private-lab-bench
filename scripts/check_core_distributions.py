"""Install one built wheel and sdist in separate fresh environments and smoke each."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--constraints", type=Path, required=True)
    args = parser.parse_args()
    checkout = Path(__file__).resolve().parents[1]
    work = args.work_dir.resolve()
    if work.is_relative_to(checkout) or work.exists() and any(work.iterdir()):
        raise ValueError("Choose an empty work directory outside the checkout")
    dist = args.dist_dir.resolve()
    wheels, sources = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Build exactly one wheel and source archive")
    expected = re.search(
        r'__version__ = "([^"]+)"',
        (checkout / "privatelabbench/__init__.py").read_text(encoding="utf-8"),
    ).group(1)
    constraints = args.constraints.resolve()
    env = {**os.environ, "PYTHONUTF8": "1"}
    env.pop("PYTHONPATH", None)

    def run(command, *, cwd=work):
        subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True)

    work.mkdir(parents=True, exist_ok=True)
    summaries = {}
    for kind, artifact in [("wheel", wheels[0]), ("sdist", sources[0])]:
        environment = work / (kind + "-env")
        run([sys.executable, "-m", "venv", environment])
        python = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        run([python, "-m", "pip", "install", "--upgrade", "pip"])
        run([python, "-m", "pip", "install", "--constraint", constraints, artifact])
        run([python, "-m", "pip", "check"])
        smoke = work / (kind + "-smoke")
        smoke.mkdir()
        run(
            [
                python,
                checkout / "scripts/smoke_installed_core.py",
                "--expected-version",
                expected,
            ],
            cwd=smoke,
        )
        summary = json.loads((smoke / "smoke-summary.json").read_text(encoding="utf-8"))
        summary["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        summaries[kind] = summary
    (work / "compatibility-summary.json").write_text(
        json.dumps(summaries, indent=2) + "\n", encoding="utf-8"
    )
    print("Both installed distributions passed all core compatibility checks")


if __name__ == "__main__":
    main()
