"""Atomic local tables; public artifacts must use the release boundary separately."""

import os
import tempfile
from pathlib import Path


def resolve_input_path(value, *, config_path=None):
    """Prefer configuration-local inputs, retaining the legacy cwd fallback."""
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    relative = (
        Path(config_path).resolve().parent / candidate if config_path else candidate
    )
    if relative.exists():
        return relative
    cwd_relative = Path.cwd() / candidate
    return cwd_relative if cwd_relative.exists() else relative


def validate_output_paths(inputs, outputs):
    """Reject input/output and output/output aliases before modifying any file."""
    paths, files = set(), set()

    def identity(path):
        try:
            info = path.stat()
        except FileNotFoundError:
            return None
        return (info.st_dev, info.st_ino) if info.st_ino else None

    for value in inputs:
        if value is not None:
            path = Path(value).resolve()
            paths.add(path)
            item = identity(path)
            if item is not None:
                files.add(item)
    for value in outputs:
        path = Path(value).resolve()
        item = identity(path)
        if path in paths or item is not None and item in files:
            raise ValueError(
                "Output paths must be separate from every input and from one another"
            )
        paths.add(path)
        if item is not None:
            files.add(item)


def atomic_write_csv(path, frame):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=".plb-local-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            frame.to_csv(handle, index=False)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
