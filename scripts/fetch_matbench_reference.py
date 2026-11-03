"""Fetch the exact upstream reference package files, without its submissions archive."""

import argparse
import json
from pathlib import Path

import privatelabbench
from privatelabbench.integrations.matbench import REFERENCE_COMMIT, _download


def fetch(output):
    manifest = json.loads(
        (
            Path(privatelabbench.__file__).parent
            / "data/integrations/matbench-reference.json"
        ).read_text()
    )
    if manifest["commit"] != REFERENCE_COMMIT:
        raise ValueError("Reference manifest commit differs")
    output = Path(output).resolve()
    base = f"https://raw.githubusercontent.com/materialsproject/matbench/{REFERENCE_COMMIT}/"
    for record in manifest["files"]:
        relative = Path(record["path"])
        target = (output / relative).resolve()
        if (
            relative.is_absolute()
            or not target.is_relative_to(output)
            or record["url"] != base + record["path"]
        ):
            raise ValueError("Unexpected upstream reference path/URL")
        _download(target, record["url"], record["sha256"])
    print(f"Verified upstream Matbench reference source: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    fetch(parser.parse_args().output_dir)
