import json
import os
import random
import stat
import struct
import subprocess
import sys
import warnings
import zipfile
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import jsonschema
import pytest

from privatelabbench import sandbox
from privatelabbench.sandbox_package import MANIFEST, read_model_package


def package(
    files=None,
    *,
    entrypoint="predict.py",
    change=None,
    compression=zipfile.ZIP_STORED,
    extra_entries=(),
):
    files = files or {
        "predict.py": b"raise RuntimeError('must not execute on host')",
        "weights/values.json": b"[2,3]",
    }
    manifest = {
        "schema_version": "sandbox-model-package/v1",
        "entrypoint": entrypoint,
        "files": {name: sha256(content).hexdigest() for name, content in files.items()},
    }
    if change:
        change(manifest)
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as archive:
        archive.writestr(MANIFEST, json.dumps(manifest))
        for name, content in files.items():
            archive.writestr(name, content)
        for name, content in extra_entries:
            archive.writestr(name, content)
    return stream.getvalue()


def read(content):
    return read_model_package(content, sha256(content).hexdigest())


def test_file_snapshot_bounds_and_regular_file_requirement(tmp_path):
    source = tmp_path / "model.zip"
    source.write_bytes(b"12345")
    assert sandbox._file_snapshot(source, 5) == b"12345"
    with pytest.raises(sandbox.SandboxError, match="byte limit"):
        sandbox._file_snapshot(source, 4)
    with pytest.raises((sandbox.SandboxError, OSError)):
        sandbox._file_snapshot(tmp_path, 5)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX special-file rejection")
def test_untrusted_fifo_is_rejected_without_waiting_for_a_writer(tmp_path):
    fifo = tmp_path / "model.pipe"
    os.mkfifo(fifo)
    code = "from pathlib import Path\nimport sys\nfrom privatelabbench.sandbox import _file_snapshot, SandboxError\ntry:\n _file_snapshot(Path(sys.argv[1]), 1024)\nexcept SandboxError:\n raise SystemExit(0)\nraise SystemExit(2)"
    result = subprocess.run(
        [sys.executable, "-c", code, str(fifo)], capture_output=True, timeout=30
    )
    assert result.returncode == 0


def test_unsupported_future_zip_version_and_small_mutation_corpus_are_controlled_rejections():
    content = bytearray(package())
    directory = struct.unpack("<4s4H2LH", content[-22:])[6]
    struct.pack_into("<H", content, directory + 6, 65535)
    with pytest.raises(sandbox.SandboxError):
        read(bytes(content))
    source = package()
    rng = random.Random(19)
    for _ in range(256):
        changed = bytearray(source)
        changed[rng.randrange(len(changed))] ^= rng.randint(1, 255)
        try:
            parsed = read(bytes(changed))
        except sandbox.SandboxError:
            continue
        assert parsed.file_count == 2 and parsed.entrypoint == "predict.py"


def test_manifest_matches_the_public_schema():
    with zipfile.ZipFile(BytesIO(package())) as archive:
        manifest = json.loads(archive.read(MANIFEST))
    schema = json.loads(
        Path(
            "privatelabbench/data/schemas/sandbox-model-package-v1.schema.json"
        ).read_text()
    )
    jsonschema.validate(manifest, schema)


def test_excessive_file_counts_and_duplicate_json_keys_are_rejected():
    too_many = {f"file-{i}.py": b"untrusted" for i in range(129)}
    with pytest.raises(sandbox.SandboxError):
        read(package(too_many, entrypoint="file-0.py"))
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            MANIFEST,
            b'{"schema_version":"sandbox-model-package/v1","schema_version":"duplicate","entrypoint":"predict.py","files":{}}',
        )
        archive.writestr("predict.py", b"untrusted")
    with pytest.raises(sandbox.SandboxError):
        read(stream.getvalue())


def test_package_is_validated_and_materialized_as_regular_readonly_data(tmp_path):
    content = package()
    prepared = read(content)
    assert prepared.entrypoint == "predict.py" and prepared.file_count == 2
    parent_mode = stat.S_IMODE(tmp_path.stat().st_mode)
    root = tmp_path / "model"
    prepared.materialize(root)
    assert (root / "weights/values.json").read_bytes() == b"[2,3]"
    assert b"must not execute on host" in (root / "predict.py").read_bytes()
    assert stat.S_IMODE(tmp_path.stat().st_mode) == parent_mode
    if os.name != "nt":
        assert stat.S_IMODE(root.stat().st_mode) == 0o555
        assert stat.S_IMODE((root / "predict.py").stat().st_mode) == 0o444
    for path in [root, *root.rglob("*")]:
        path.chmod(0o700 if path.is_dir() else 0o600)


@pytest.mark.parametrize(
    "name",
    [
        "../escape.py",
        "/absolute.py",
        "a/../../escape.py",
        "C:/model.py",
        "a\\model.py",
        "a//model.py",
        "a/./model.py",
        "NUL.py",
        "con/data.py",
        "a/model.py.",
        "a/space name.py",
        "a/secret\x00name.py",
        "/".join(["a"] * 17) + ".py",
    ],
)
def test_unsafe_or_nonportable_member_names_are_rejected(name):
    with pytest.raises(sandbox.SandboxError):
        read(package({name: b"untrusted"}, entrypoint=name))


@pytest.mark.parametrize(
    "files",
    [
        {"predict.py": b"a", "Predict.py": b"b"},
        {"a": b"x", "a/predict.py": b"x"},
        {"a/predict.py": b"x", "A/weights.json": b"x"},
    ],
)
def test_case_and_file_directory_collisions_are_rejected(files):
    with pytest.raises(sandbox.SandboxError):
        read(package(files, entrypoint=next(iter(files))))


@pytest.mark.parametrize(
    "damage",
    [
        "schema",
        "entrypoint",
        "extra_file",
        "missing_file",
        "digest",
        "digest_type",
        "unknown_key",
        "non_python",
    ],
)
def test_manifest_binds_every_file_and_the_entrypoint(damage):
    def change(manifest):
        if damage == "schema":
            manifest["schema_version"] = "unknown"
        elif damage == "entrypoint":
            manifest["entrypoint"] = "missing.py"
        elif damage == "extra_file":
            manifest["files"]["other.py"] = "a" * 64
        elif damage == "missing_file":
            manifest["files"].pop("weights/values.json")
        elif damage == "digest":
            manifest["files"]["predict.py"] = "a" * 64
        elif damage == "digest_type":
            manifest["files"]["predict.py"] = True
        elif damage == "unknown_key":
            manifest["shell"] = "untrusted"
        else:
            manifest["entrypoint"] = "weights/values.json"

    with pytest.raises(sandbox.SandboxError):
        read(package(change=change))


def test_compression_links_directories_duplicates_and_comments_are_rejected():
    with pytest.raises(sandbox.SandboxError):
        read(package(compression=zipfile.ZIP_DEFLATED))
    for mode in (stat.S_IFLNK, stat.S_IFDIR, stat.S_IFIFO):
        info = zipfile.ZipInfo("extra.py")
        info.create_system = 3
        info.external_attr = (mode | 0o777) << 16
        with pytest.raises(sandbox.SandboxError):
            read(package(extra_entries=[(info, b"target")]))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        duplicate = package(extra_entries=[("predict.py", b"duplicate")])
    with pytest.raises(sandbox.SandboxError):
        read(duplicate)
    stream = BytesIO(package())
    with zipfile.ZipFile(stream, "a") as archive:
        archive.comment = b"not-supported"
    with pytest.raises(sandbox.SandboxError):
        read(stream.getvalue())


@pytest.mark.parametrize(
    "index,value", [(1, 1), (2, 1), (3, 1), (4, 65535), (5, 65537), (6, 0), (7, 1)]
)
def test_directory_bounds_are_checked_before_general_zip_parsing(
    index, value, monkeypatch
):
    content = bytearray(package())
    end = list(struct.unpack("<4s4H2LH", content[-22:]))
    end[index] = value
    content[-22:] = struct.pack("<4s4H2LH", *end)

    def forbidden(*args, **kwargs):
        raise AssertionError("unbounded directory reached the ZIP reader")

    monkeypatch.setattr(zipfile, "ZipFile", forbidden)
    with pytest.raises(sandbox.SandboxError):
        read(bytes(content))


@pytest.mark.parametrize(
    "damage",
    ["encrypted", "compressed", "extra", "filename", "size", "crc", "zip64_locator"],
)
def test_inconsistent_local_headers_and_alternate_directories_fail_closed(damage):
    content = bytearray(package())
    directory = struct.unpack("<4s4H2LH", content[-22:])[6]
    if damage == "encrypted":
        struct.pack_into("<H", content, 6, 1)
        struct.pack_into("<H", content, directory + 8, 1)
    elif damage == "compressed":
        struct.pack_into("<H", content, 8, 8)
    elif damage == "extra":
        struct.pack_into("<H", content, 28, 1)
    elif damage == "filename":
        content[30] = ord("X")
    elif damage == "size":
        struct.pack_into("<L", content, 22, 1)
    elif damage == "crc":
        original = struct.unpack_from("<L", content, 14)[0] ^ 1
        struct.pack_into("<L", content, 14, original)
        struct.pack_into("<L", content, directory + 16, original)
    else:
        content[-42:-38] = b"PK\x06\x07"
    with pytest.raises(sandbox.SandboxError):
        read(bytes(content))


def test_digest_and_manifest_limits_prevent_execution_or_extraction(
    tmp_path, monkeypatch
):
    content = package()
    with pytest.raises(sandbox.SandboxError, match="digest"):
        read_model_package(content, "0" * 64)
    import privatelabbench.sandbox_package as module

    monkeypatch.setattr(module, "MAX_PACKAGE_BYTES", 32)
    with pytest.raises(sandbox.SandboxError, match="byte limit"):
        read(content)


def test_package_execution_uses_the_same_restricted_runtime_and_mount_contract(
    tmp_path,
):
    command = sandbox._create_args(
        "owned",
        "sha256:" + "a" * 64,
        tmp_path / "model",
        sandbox.SandboxLimits(),
        package_entrypoint="scripts/predict.py",
    )
    assert command.count("--mount") == 1
    assert (
        command[command.index("--mount") + 1]
        == f"type=bind,src={tmp_path / 'model'},dst=/model,readonly"
    )
    for flag, value in (
        ("--runtime", "runsc"),
        ("--network", "none"),
        ("--user", "65534:65534"),
        ("--cap-drop", "ALL"),
    ):
        assert command[command.index(flag) + 1] == value
    assert "-I" in command and "-B" in command
    assert command[-1] == "/model/scripts/predict.py"


def test_invalid_packages_never_start_docker_and_valid_ones_need_linux(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Host execution must not start")

    monkeypatch.setattr(sandbox, "_Docker", forbidden)
    with pytest.raises(sandbox.SandboxError):
        sandbox.run_sandbox_package(
            b"invalid",
            [[1.0]],
            model_sha256="0" * 64,
            runtime_image="sha256:" + "a" * 64,
        )
    monkeypatch.setattr(sandbox.sys, "platform", "win32")
    content = package()
    with pytest.raises(sandbox.SandboxError, match="Linux"):
        sandbox.run_sandbox_package(
            content,
            [[1.0]],
            model_sha256=sha256(content).hexdigest(),
            runtime_image="sha256:" + "a" * 64,
        )
