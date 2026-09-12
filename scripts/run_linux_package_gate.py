#!/usr/bin/env python3
"""Produce capture-bound Linux package observations without copying a wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ai-auto-lrc/package-platform"
OBSERVATION_SCHEMA = "ai-auto-lrc/linux-package-observation"
SCHEMA_VERSION = 1
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_REFERENCE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
WHEEL_TAG = re.compile(r"^[A-Za-z0-9_.]+-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+$")
EXPECTED_CLI_STDOUT_SHA256 = hashlib.sha256(b"[00:00.034]hello\n").hexdigest()
DIRECT_IMPORTS = (
    "audioread",
    "chardet",
    "cyrtranslit",
    "fasttext",
    "g2p_en",
    "julius",
    "kroman",
    "librosa",
    "nltk",
    "numpy",
    "pykakasi",
    "pypinyin",
    "soundfile",
    "t2l",
    "torch",
    "torchaudio",
)
OBSERVATION_KEYS = {
    "schema",
    "schema_version",
    "run_id",
    "scope",
    "network",
    "wheelhouse",
    "build",
    "installation",
    "cli",
}
EVIDENCE_BUNDLE_FILES = (
    "scripts/verify_linux_offline_wheelhouse.py",
    "lid.176.ftz",
    "checkpoints/checkpoint_MTL",
    "assets/nltk_data/taggers/averaged_perceptron_tagger.zip",
    "assets/nltk_data/corpora/cmudict.zip",
    "tests/fixtures/audio/sine-440hz-250ms-mono-22050.mp3",
)


class ProducerError(RuntimeError):
    """Raised when package evidence is incomplete, inconsistent, or unsafe."""


@dataclass(frozen=True, slots=True)
class StableManifest:
    content: bytes
    identity: tuple[int, int, int, int, int, int]


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_stable_manifest(path: Path) -> StableManifest:
    """Read manifest bytes while binding path and descriptor identity."""

    try:
        before = path.lstat()
    except FileNotFoundError as error:
        raise ProducerError("wheelhouse manifest is missing") from error
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ProducerError("wheelhouse manifest must be a regular non-symlink file")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ProducerError("wheelhouse manifest could not be opened safely") from error
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _identity(opened) != _identity(before):
            raise ProducerError("wheelhouse manifest changed before reading")
        content = stream.read()
        after = os.fstat(stream.fileno())
    try:
        current = path.lstat()
    except FileNotFoundError as error:
        raise ProducerError("wheelhouse manifest changed while reading") from error
    if any(_identity(item) != _identity(before) for item in (opened, after, current)):
        raise ProducerError("wheelhouse manifest changed while reading")
    if len(content) != before.st_size:
        raise ProducerError("wheelhouse manifest changed size while reading")
    return StableManifest(content, _identity(before))


def _canonical_relative(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ProducerError(f"{field} must be a canonical relative path")
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ProducerError(f"{field} must be a canonical relative path")
    return value


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ProducerError(f"{field} must be a lowercase SHA-256")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProducerError(f"{field} must be a non-negative integer")
    return value


def _exact_object(value: object, keys: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ProducerError(f"{field} fields do not match schema v1")
    return value


def _manifest_document(content: bytes) -> dict[str, Any]:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProducerError("wheelhouse manifest must be valid UTF-8 JSON") from error
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ProducerError("wheelhouse manifest schema_version must be 1")
    target = document.get("target")
    if not isinstance(target, dict):
        raise ProducerError("wheelhouse manifest target must be an object")
    files = document.get("files")
    if not isinstance(files, dict):
        raise ProducerError("wheelhouse manifest files must be an object")
    for required in ("runtime", "build_system", "artifacts"):
        if not isinstance(files.get(required), list):
            raise ProducerError(f"wheelhouse manifest files.{required} must be an array")
    return document


def summarize_wheelhouse_manifest(content: bytes) -> dict[str, object]:
    """Recompute the count and canonical file-record aggregate."""

    document = _manifest_document(content)
    flattened: list[dict[str, object]] = []
    for group, records in document["files"].items():
        if not isinstance(group, str) or not isinstance(records, list):
            raise ProducerError("wheelhouse manifest file groups are invalid")
        for index, raw in enumerate(records):
            field = f"wheelhouse manifest files.{group}[{index}]"
            record = _exact_object(raw, {"path", "size", "sha256"}, field)
            flattened.append(
                {
                    "group": group,
                    "path": _canonical_relative(record["path"], f"{field}.path"),
                    "size": _nonnegative_int(record["size"], f"{field}.size"),
                    "sha256": _hash(record["sha256"], f"{field}.sha256"),
                }
            )
    flattened.sort(key=lambda item: (str(item["group"]), str(item["path"])))
    aggregate_bytes = json.dumps(
        flattened,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    files = document["files"]
    return {
        "manifest_sha256": hashlib.sha256(content).hexdigest(),
        "runtime_wheel_count": len(files["runtime"]),
        "build_wheel_count": len(files["build_system"]),
        "artifact_count": len(files["artifacts"]),
        "aggregate_sha256": hashlib.sha256(aggregate_bytes).hexdigest(),
    }


def _artifact_record(value: object, field: str) -> dict[str, object]:
    record = _exact_object(value, {"name", "size", "sha256"}, field)
    return {
        "name": _canonical_relative(record["name"], f"{field}.name"),
        "size": _nonnegative_int(record["size"], f"{field}.size"),
        "sha256": _hash(record["sha256"], f"{field}.sha256"),
    }


def _tag_list(value: object, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(tag, str) and WHEEL_TAG.fullmatch(tag) for tag in value)
        or value != sorted(set(value))
    ):
        raise ProducerError(f"{field} must be a sorted unique wheel-tag array")
    return value


def _reject_sensitive_strings(value: object, field: str = "observation") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or any(
                marker in key.lower()
                for marker in ("token", "secret", "password", "credential", "api_key")
            ):
                raise ProducerError(f"{field} contains forbidden secret material")
            _reject_sensitive_strings(item, f"{field}.{key}")
    elif isinstance(value, list):
        for item in value:
            _reject_sensitive_strings(item, field)
    elif isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in ("bearer ", "token=", "password=", "api_key=")):
            raise ProducerError(f"{field} contains forbidden secret material")


def _validate_observation(
    raw: object,
    *,
    run_id: str,
    manifest_bytes: bytes,
) -> dict[str, Any]:
    observation = _exact_object(raw, OBSERVATION_KEYS, "observation")
    _reject_sensitive_strings(observation)
    if observation["schema"] != OBSERVATION_SCHEMA or observation["schema_version"] != 1:
        raise ProducerError("observation schema does not match version 1")
    if observation["run_id"] != run_id:
        raise ProducerError("observation.run_id does not match capture run")

    scope = _exact_object(
        observation["scope"],
        {"os", "arch", "python_implementation", "python_version", "platform"},
        "observation.scope",
    )
    expected_scope = {
        "os": "linux",
        "arch": "x86_64",
        "python_implementation": "CPython",
        "python_version": "3.11.9",
        "platform": "linux-x86_64",
    }
    manifest = _manifest_document(manifest_bytes)
    target = manifest["target"]
    target_scope = {
        "os": "linux",
        "arch": target.get("machine"),
        "python_implementation": target.get("implementation"),
        "python_version": target.get("python_version"),
        "platform": target.get("platform"),
    }
    if scope != expected_scope or scope != target_scope:
        raise ProducerError("observation.scope does not match Linux wheelhouse target")

    network = _exact_object(
        observation["network"],
        {"policy", "probe", "blocked", "result_code"},
        "observation.network",
    )
    if (
        network["policy"] != "denied"
        or network["probe"] != "connect_ex"
        or network["blocked"] is not True
        or not isinstance(network["result_code"], int)
        or isinstance(network["result_code"], bool)
        or network["result_code"] == 0
    ):
        raise ProducerError("observation.network does not prove runtime denial")

    expected_wheelhouse = summarize_wheelhouse_manifest(manifest_bytes)
    wheelhouse = _exact_object(
        observation["wheelhouse"],
        set(expected_wheelhouse),
        "observation.wheelhouse",
    )
    if wheelhouse != expected_wheelhouse:
        raise ProducerError("observation.wheelhouse does not match manifest bytes")

    build = _exact_object(
        observation["build"],
        {
            "source",
            "sdist",
            "project_wheel",
            "runtime_wheel_tags",
            "build_wheel_tags",
            "project_wheel_tags",
        },
        "observation.build",
    )
    if build["source"] != "sdist":
        raise ProducerError("observation.build.source must be sdist")
    sdist = _artifact_record(build["sdist"], "observation.build.sdist")
    project_wheel = _artifact_record(
        build["project_wheel"],
        "observation.build.project_wheel",
    )
    if "/" in sdist["name"] or "/" in project_wheel["name"]:
        raise ProducerError("observation.build records must use basenames")
    manifest_sdists = [
        {
            "name": PurePosixPath(record["path"]).name,
            "size": record["size"],
            "sha256": record["sha256"],
        }
        for record in manifest["files"]["artifacts"]
    ]
    if len(manifest_sdists) != 1 or sdist != manifest_sdists[0]:
        raise ProducerError("observation.build.sdist does not match manifest")
    validated_build = {
        "source": "sdist",
        "sdist": sdist,
        "project_wheel": project_wheel,
        "runtime_wheel_tags": _tag_list(
            build["runtime_wheel_tags"], "observation.build.runtime_wheel_tags"
        ),
        "build_wheel_tags": _tag_list(
            build["build_wheel_tags"], "observation.build.build_wheel_tags"
        ),
        "project_wheel_tags": _tag_list(
            build["project_wheel_tags"], "observation.build.project_wheel_tags"
        ),
    }

    installation = _exact_object(
        observation["installation"],
        {
            "pip_check_exit_code",
            "pip_check_stdout_sha256",
            "pip_check_stderr_sha256",
            "pth_before",
            "pth_after",
            "direct_imports",
            "installed_package_origin_scope",
            "installed_package",
        },
        "observation.installation",
    )
    if installation["pip_check_exit_code"] != 0:
        raise ProducerError("observation.installation.pip_check_exit_code must be zero")
    _hash(
        installation["pip_check_stdout_sha256"],
        "observation.installation.pip_check_stdout_sha256",
    )
    _hash(
        installation["pip_check_stderr_sha256"],
        "observation.installation.pip_check_stderr_sha256",
    )
    if not isinstance(installation["pth_before"], list) or not isinstance(
        installation["pth_after"], list
    ):
        raise ProducerError("observation.installation pth snapshots must be arrays")
    pth_before = [
        _artifact_record(record, f"observation.installation.pth_before[{index}]")
        for index, record in enumerate(installation["pth_before"])
    ]
    pth_after = [
        _artifact_record(record, f"observation.installation.pth_after[{index}]")
        for index, record in enumerate(installation["pth_after"])
    ]
    if pth_before != sorted(pth_before, key=lambda item: str(item["name"])):
        raise ProducerError("observation.installation.pth_before must be sorted")
    if pth_after != pth_before:
        raise ProducerError("observation.installation pth snapshots must be equal")
    imports = installation["direct_imports"]
    if imports != list(DIRECT_IMPORTS):
        raise ProducerError("observation.installation.direct_imports is not closed")
    if installation["installed_package_origin_scope"] != "site-packages":
        raise ProducerError(
            "observation.installation.installed_package_origin_scope must be site-packages"
        )
    installed = _artifact_record(
        installation["installed_package"],
        "observation.installation.installed_package",
    )
    if not str(installed["name"]).startswith("t2l/"):
        raise ProducerError("observation.installation.installed_package is outside site-packages")
    validated_installation = {
        "pip_check_exit_code": 0,
        "pip_check_stdout_sha256": installation["pip_check_stdout_sha256"],
        "pip_check_stderr_sha256": installation["pip_check_stderr_sha256"],
        "pth_before": pth_before,
        "pth_after": pth_after,
        "direct_imports": imports,
        "installed_package_origin_scope": "site-packages",
        "installed_package": installed,
    }

    cli = _exact_object(
        observation["cli"],
        {"command_id", "exit_code", "stdout_sha256", "stderr_sha256", "expected_stdout_sha256"},
        "observation.cli",
    )
    if (
        cli["command_id"] != "installed-public-e2e-v1"
        or cli["exit_code"] != 0
        or cli["stdout_sha256"] != EXPECTED_CLI_STDOUT_SHA256
        or cli["expected_stdout_sha256"] != EXPECTED_CLI_STDOUT_SHA256
    ):
        raise ProducerError("observation.cli does not match installed public smoke")
    _hash(cli["stderr_sha256"], "observation.cli.stderr_sha256")

    return {
        "scope": scope,
        "network": network,
        "wheelhouse": expected_wheelhouse,
        "build": validated_build,
        "installation": validated_installation,
        "cli": cli,
    }


def _inspect_image(docker: str, image_reference: str) -> dict[str, str]:
    result = subprocess.run(
        [docker, "image", "inspect", image_reference],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise ProducerError("docker image inspect failed")
    try:
        payload = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProducerError("docker image inspect returned invalid JSON") from error
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ProducerError("docker image inspect returned invalid image identity")
    image = payload[0]
    image_id = image.get("Id")
    repo_digests = image.get("RepoDigests")
    if (
        not isinstance(image_id, str)
        or IMAGE_ID.fullmatch(image_id) is None
        or not isinstance(repo_digests, list)
        or image_reference not in repo_digests
    ):
        raise ProducerError("docker image identity is not immutable or complete")
    output = {"image_id": image_id, "repo_digest": image_reference}
    repo_tags = image.get("RepoTags")
    if isinstance(repo_tags, list) and repo_tags and isinstance(repo_tags[0], str):
        output["display_tag"] = repo_tags[0]
    _reject_sensitive_strings(output, "image")
    return output


def _run_verifier(
    docker: str,
    *,
    image_id: str,
    wheelhouse: Path,
    evidence_bundle: Path,
    run_id: str,
) -> object:
    command = [
        docker,
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,size=4g",
        "-e",
        f"AI_AUTO_LRC_EVIDENCE_RUN_ID={run_id}",
        "-v",
        f"{wheelhouse}:/wheelhouse:ro",
        "-v",
        f"{evidence_bundle}:/evidence-source:ro",
        "-w",
        "/tmp",
        image_id,
        "python",
        "-I",
        "/evidence-source/scripts/verify_linux_offline_wheelhouse.py",
        "/wheelhouse",
        "/evidence-source",
    ]
    result = subprocess.run(command, check=False, capture_output=True, timeout=900)
    if result.returncode != 0:
        raise ProducerError("Linux package verifier failed")
    if result.stderr.strip():
        raise ProducerError("Linux package verifier wrote unexpected stderr")
    try:
        return json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProducerError("Linux package verifier returned invalid JSON") from error


def _write_temp(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _materialize_evidence_bundle(repository_root: Path, bundle: Path) -> None:
    for relative_path in EVIDENCE_BUNDLE_FILES:
        source = repository_root / relative_path
        stable = _read_stable_manifest(source)
        destination = bundle / relative_path
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _write_temp(destination, stable.content)
    for path in sorted(bundle.rglob("*"), reverse=True):
        path.chmod(0o500 if path.is_dir() else 0o400)
    bundle.chmod(0o500)


def _atomic_publish(artifact_root: Path, files: dict[str, bytes]) -> None:
    final_paths = {name: artifact_root / name for name in files}
    if any(path.exists() or path.is_symlink() for path in final_paths.values()):
        raise ProducerError("refusing to replace an existing package sidecar")
    suffix = f".{os.getpid()}.{uuid.uuid4().hex}.tmp"
    temporary = {name: artifact_root / f".{name}{suffix}" for name in files}
    published: list[Path] = []
    try:
        for name, content in files.items():
            _write_temp(temporary[name], content)
        for name in ("wheelhouse-manifest.json", "package-platform.json"):
            os.replace(temporary[name], final_paths[name])
            published.append(final_paths[name])
        descriptor = os.open(artifact_root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        for path in published:
            path.unlink(missing_ok=True)
        for path in temporary.values():
            path.unlink(missing_ok=True)
        raise ProducerError("atomic sidecar publication failed") from error


def _real_directory(path: Path, field: str) -> Path:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            item_stat = current.lstat()
        except FileNotFoundError as error:
            raise ProducerError(f"{field} must be an existing real directory") from error
        if stat.S_ISLNK(item_stat.st_mode):
            raise ProducerError(f"{field} must not use a symlink")
    resolved = absolute.resolve(strict=True)
    if not resolved.is_dir():
        raise ProducerError(f"{field} must be an existing real directory")
    return resolved


def produce_package_sidecars(
    *,
    wheelhouse: Path,
    artifact_root: Path,
    run_id: str,
    image_reference: str,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    """Run the Linux verifier and atomically publish two validated sidecars."""

    if RUN_ID.fullmatch(run_id) is None:
        raise ProducerError("run_id is invalid")
    if IMAGE_REFERENCE.fullmatch(image_reference) is None:
        raise ProducerError("image must be an immutable image reference")
    wheelhouse = _real_directory(wheelhouse, "wheelhouse")
    artifact_root = _real_directory(artifact_root, "artifact-root")
    repository_root = _real_directory(repository_root, "repository-root")
    docker = shutil.which("docker")
    if docker is None:
        raise ProducerError("docker is required")

    manifest_path = wheelhouse / "manifest.json"
    before = _read_stable_manifest(manifest_path)
    summary = summarize_wheelhouse_manifest(before.content)
    image = _inspect_image(docker, image_reference)
    with tempfile.TemporaryDirectory(prefix="ai-auto-lrc-package-evidence-") as temporary:
        evidence_bundle = Path(temporary) / "bundle"
        evidence_bundle.mkdir(mode=0o700)
        _materialize_evidence_bundle(repository_root, evidence_bundle)
        raw_observation = _run_verifier(
            docker,
            image_id=image["image_id"],
            wheelhouse=wheelhouse,
            evidence_bundle=evidence_bundle,
            run_id=run_id,
        )
    after = _read_stable_manifest(manifest_path)
    if before != after:
        raise ProducerError("wheelhouse manifest changed during container run")
    validated = _validate_observation(
        raw_observation,
        run_id=run_id,
        manifest_bytes=before.content,
    )
    sidecar = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "layer": "package",
        "scope": validated["scope"],
        "image": image,
        "network": validated["network"],
        "wheelhouse": {"manifest_path": "wheelhouse-manifest.json", **summary},
        "build": validated["build"],
        "installation": validated["installation"],
        "cli": validated["cli"],
    }
    sidecar_bytes = (json.dumps(sidecar, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_publish(
        artifact_root,
        {
            "wheelhouse-manifest.json": before.content,
            "package-platform.json": sidecar_bytes,
        },
    )
    return sidecar


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--image", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        produce_package_sidecars(
            wheelhouse=arguments.wheelhouse,
            artifact_root=arguments.artifact_root,
            run_id=arguments.run_id,
            image_reference=arguments.image,
        )
    except (ProducerError, OSError, ValueError) as error:
        sys.stderr.write(f"Linux package evidence failed: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
