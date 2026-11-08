"""Bounded, digest-pinned model data; no submitted module executes on the host."""

from __future__ import annotations

import binascii
import json
import re
import stat
import struct
import zipfile
from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath

from privatelabbench.sandbox import SandboxError, _json_object

MAX_PACKAGE_BYTES = 128 * 1024 * 1024
MAX_FILES = 128
MAX_DIRECTORY_BYTES = 64 * 1024
MANIFEST = "model-package.json"
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *[f"COM{i}" for i in range(1, 10)],
    *[f"LPT{i}" for i in range(1, 10)],
}


def _name(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise SandboxError("Invalid model-package member path")
    parts = value.split("/")
    if len(parts) > 16 or any(
        not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", part)
        or part.endswith(".")
        or part.split(".", 1)[0].upper() in _RESERVED
        for part in parts
    ):
        raise SandboxError("Use portable relative model-package paths")
    return value


def _directory(payload):
    # The small ZIP32 subset has an exact trailing EOCD, no ZIP64, comments,
    # split disks or compression. Bound the directory before ZipInfo allocation.
    if not payload.startswith(b"PK\x03\x04") or len(payload) < 22:
        raise SandboxError("Invalid model-package ZIP header")
    signature, disk, directory_disk, disk_entries, entries, size, offset, comment = (
        struct.unpack("<4s4H2LH", payload[-22:])
    )
    if (
        signature != b"PK\x05\x06"
        or disk
        or directory_disk
        or comment
        or disk_entries != entries
        or not 2 <= entries <= MAX_FILES + 1
        or not 0 < size <= MAX_DIRECTORY_BYTES
        or offset + size != len(payload) - 22
        # Prevent the standard reader from replacing these bounded ZIP32 fields
        # with an alternate ZIP64 directory before constructing ZipInfo objects.
        or payload[-42:-38] == b"PK\x06\x07"
    ):
        raise SandboxError("Unsupported or excessive model-package directory")
    return entries, offset


def _member(payload, info, directory_offset):
    name = _name(info.filename)
    if (
        info.is_dir()
        or info.orig_filename != info.filename
        or info.compress_type != zipfile.ZIP_STORED
        or info.compress_size != info.file_size
        or info.extra
        or info.comment
        or info.flag_bits & ~0x800
        or info.volume
        or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)
        or not 0 <= info.file_size <= MAX_PACKAGE_BYTES
        or not 0 <= info.header_offset <= directory_offset - 30
    ):
        raise SandboxError("Model packages permit only ordinary uncompressed files")
    header = payload[info.header_offset : info.header_offset + 30]
    (
        signature,
        version,
        flags,
        compression,
        _,
        _,
        crc,
        compressed,
        size,
        name_size,
        extra_size,
    ) = struct.unpack("<4s5H3L2H", header)
    start = info.header_offset + 30 + name_size
    end = start + size
    if (
        signature != b"PK\x03\x04"
        or not 10 <= version <= 20
        or flags != info.flag_bits
        or compression != zipfile.ZIP_STORED
        or crc != info.CRC
        or compressed != info.compress_size
        or size != info.file_size
        or extra_size
        or name_size != len(name)
        or end > directory_offset
        or payload[info.header_offset + 30 : start] != name.encode("ascii")
    ):
        raise SandboxError("Inconsistent model-package local member header")
    view = memoryview(payload)[start:end]
    if binascii.crc32(view) & 0xFFFFFFFF != crc:
        raise SandboxError("Model-package member checksum mismatch")
    return name, info.header_offset, start, end


@dataclass(frozen=True)
class ModelPackage:
    _payload: bytes = field(repr=False)
    _members: tuple = field(repr=False)
    entrypoint: str
    file_count: int

    def materialize(self, root: Path):
        """Write only checked regular files into a fresh private snapshot root."""
        for name, start, end in self._members:
            _name(name)
            if (
                type(start) is not int
                or type(end) is not int
                or not 0 <= start <= end <= len(self._payload)
            ):
                raise SandboxError("Invalid model-package snapshot bounds")
        root.mkdir(mode=0o700)
        directories = {root}
        for name, start, end in self._members:
            destination = root.joinpath(*PurePosixPath(name).parts)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            directories.update(destination.parents)
            with destination.open("xb") as handle:
                handle.write(memoryview(self._payload)[start:end])
            destination.chmod(0o444)
        # The host parent remains private; only the mounted model tree must be
        # traversable by the non-root guest. Never change host ancestor modes.
        for directory in directories:
            if directory == root or root in directory.parents:
                directory.chmod(0o555)


def read_model_package(payload: bytes, expected_sha256: str) -> ModelPackage:
    """Validate the immutable archive snapshot without extracting arbitrary paths."""
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_PACKAGE_BYTES:
        raise SandboxError("Model package exceeds its byte limit or is empty")
    if (
        not isinstance(expected_sha256, str)
        or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)
        or sha256(payload).hexdigest() != expected_sha256
    ):
        raise SandboxError("Model-package digest mismatch")
    try:
        entries, directory_offset = _directory(payload)
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            infos = archive.infolist()
        if len(infos) != entries:
            raise SandboxError("Model-package directory count mismatch")
        members = sorted(
            (_member(payload, info, directory_offset) for info in infos),
            key=lambda item: item[1],
        )
        position = 0
        names, folded, prefixes = {}, set(), {}
        for name, header, start, end in members:
            if header != position or name.casefold() in folded:
                raise SandboxError("Overlapping or duplicate model-package members")
            position = end
            folded.add(name.casefold())
            names[name] = (start, end)
            pieces = name.split("/")
            for depth in range(1, len(pieces) + 1):
                prefix = "/".join(pieces[:depth])
                old = prefixes.setdefault(prefix.casefold(), prefix)
                if old != prefix:
                    raise SandboxError("Case-ambiguous model-package paths")
        if position != directory_offset or MANIFEST not in names:
            raise SandboxError("Model package must contain its exact manifest")
        if any(
            str(parent) in names
            for name in names
            for parent in PurePosixPath(name).parents
            if str(parent) != "."
        ):
            raise SandboxError("Model-package file/directory path collision")
        start, end = names[MANIFEST]
        if end - start > 64 * 1024:
            raise SandboxError("Model-package manifest exceeds its byte limit")
        manifest = json.loads(payload[start:end], object_pairs_hook=_json_object)
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"schema_version", "entrypoint", "files"}
            or manifest["schema_version"] != "sandbox-model-package/v1"
        ):
            raise SandboxError("Invalid sandbox-model-package/v1 manifest")
        entrypoint = _name(manifest["entrypoint"])
        files = manifest["files"]
        if (
            not isinstance(files, dict)
            or not 1 <= len(files) <= MAX_FILES
            or set(files) != set(names) - {MANIFEST}
            or entrypoint not in files
            or not entrypoint.endswith(".py")
        ):
            raise SandboxError("Declare every model-package file and Python entrypoint")
        for name, digest in files.items():
            _name(name)
            start, end = names[name]
            if (
                not isinstance(digest, str)
                or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or sha256(memoryview(payload)[start:end]).hexdigest() != digest
            ):
                raise SandboxError("Model-package file digest mismatch")
        return ModelPackage(
            payload,
            tuple((name, start, end) for name, (start, end) in names.items()),
            entrypoint,
            len(files),
        )
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        NotImplementedError,
        ValueError,
        UnicodeError,
        RecursionError,
        struct.error,
    ) as exc:
        if isinstance(exc, SandboxError):
            raise
        raise SandboxError("Invalid model package") from exc
