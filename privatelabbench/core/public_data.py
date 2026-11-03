"""Atomic, digest-checked downloads for explicitly requested public reference assets."""

from hashlib import sha256
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def download_verified(path, url, expected, *, max_bytes=128 * 1024 * 1024):
    address = urlsplit(url)
    if (
        address.scheme != "https"
        or not address.hostname
        or address.username
        or address.password
        or not re.fullmatch(r"[a-f0-9]{64}", str(expected))
    ):
        raise ValueError(
            "Public reference downloads require HTTPS and an exact SHA-256"
        )
    path = Path(path)
    if path.exists():
        if sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(
                "Cached public asset differs from its pinned digest; choose a fresh cache"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with urlopen(
            Request(url, headers={"User-Agent": "PrivateLabBench-reference-assets"}),
            timeout=60,
        ) as response:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".plb-reference-", delete=False
            ) as handle:
                temporary = Path(handle.name)
                digest = sha256()
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("Reference asset exceeds the download limit")
                    digest.update(chunk)
                    handle.write(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("Downloaded reference asset failed its pinned digest")
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
