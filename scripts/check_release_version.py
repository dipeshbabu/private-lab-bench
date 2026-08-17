from __future__ import annotations

import re
import sys
from pathlib import Path

import tomllib


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_release_version.py <tag-version>")
    tag_version = sys.argv[1].strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.-]+)?", tag_version):
        raise SystemExit(f"invalid release version from tag: {tag_version!r}")
    with Path("pyproject.toml").open("rb") as handle:
        project_version = str(tomllib.load(handle)["project"]["version"])
    init_text = Path("privatelabbench/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_text, re.MULTILINE)
    if not match:
        raise SystemExit("could not find __version__ in privatelabbench/__init__.py")
    module_version = match.group(1)
    if tag_version != project_version or tag_version != module_version:
        raise SystemExit(
            f"release version mismatch: tag={tag_version}, pyproject={project_version}, module={module_version}"
        )
    print(f"release version verified: {tag_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
