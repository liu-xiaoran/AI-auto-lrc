#!/usr/bin/env python3
"""Build and run the capture-bound canonical image, then publish its evidence."""

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
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
IMAGE_TAG = "ai-auto-lrc-legacy-v1-golden:cpython310-linux-x86_64"
RUNTIME_SCHEMA = "ai-auto-lrc/canonical-runtime"
OBSERVATION_SCHEMA = "ai-auto-lrc/canonical-container-observation"
SCHEMA_VERSION = 1
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_REFERENCE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PYTHON_310 = re.compile(r"^3\.10\.[0-9]+(?:[A-Za-z0-9.+-]*)?$")
CANONICAL_SELECTORS = (
    "tests/golden/test_legacy_v1_feature_golden.py",
    "tests/golden/test_legacy_v1_numeric_golden.py",
    "tests/golden/test_legacy_v1_public_e2e_golden.py",
)
FORMAL_SOURCE_FILES = {
    "canonical-Dockerfile": "tests/golden/Dockerfile.canonical",
    "canonical-feature-oracle.json": "tests/golden/legacy_v1_feature_manifest.json",
    "canonical-numeric-oracle.json": "tests/golden/legacy_v1_numeric_manifest.json",
    "canonical-public-e2e-oracle.json": "tests/golden/legacy_v1_public_e2e_manifest.json",
    "canonical-profile-manifest.json": "t2l/_assets/legacy_v1_manifest.json",
    "canonical-fixture-metadata.json": "tests/fixtures/audio/sine-440hz-250ms-mono-22050.json",
    "canonical-producer.py": "scripts/run_canonical_gate.py",
    "canonical-observer.py": "tests/golden/canonical_capture_observer.py",
    "canonical-runner.sh": "scripts/run_canonical_legacy_v1_golden.sh",
}
FORMAL_ARTIFACTS = (
    "canonical.xml",
    "canonical-runtime.json",
    *FORMAL_SOURCE_FILES,
)
ORACLE_SPECS = {
    "feature": (
        "canonical-feature-oracle.json",
        "legacy-v1-feature-linux-x86_64-cpython310",
        "feature-only",
    ),
    "numeric": (
        "canonical-numeric-oracle.json",
        "legacy-v1-numeric-linux-x86_64-cpython310",
        "checkpoint-numeric-and-rendering",
    ),
    "public-e2e": (
        "canonical-public-e2e-oracle.json",
        "legacy-v1-real-mp3-public-api-installed-cli-linux-x86_64-cpython310",
        "real-decoder-public-api-installed-cli",
    ),
}
LABEL_RUN_ID = "org.ai-auto-lrc.canonical.run-id"
LABEL_SOURCE = "org.ai-auto-lrc.canonical.source-sha256"
LABEL_INPUT = "org.ai-auto-lrc.canonical.input-aggregate-sha256"


class ProducerError(RuntimeError):
    """Raised when canonical evidence cannot be proven or safely published."""


@dataclass(frozen=True, slots=True)
class StableFile:
    content: bytes | None
    size: int
    sha256: str
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


def _stable_file(path: Path, *, retain_bytes: bool) -> StableFile:
    try:
        before = path.lstat()
    except FileNotFoundError as error:
        raise ProducerError(f"required canonical input is missing: {path.name}") from error
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ProducerError(f"canonical input must be a regular non-symlink: {path.name}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    digest = hashlib.sha256()
    chunks: list[bytes] | None = [] if retain_bytes else None
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ProducerError(f"canonical input could not be opened safely: {path.name}") from error
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _identity(opened) != _identity(before):
            raise ProducerError(f"canonical input changed before reading: {path.name}")
        total = 0
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            total += len(chunk)
            if chunks is not None:
                chunks.append(chunk)
        after = os.fstat(stream.fileno())
    try:
        current = path.lstat()
    except FileNotFoundError as error:
        raise ProducerError(f"canonical input changed while reading: {path.name}") from error
    if any(_identity(item) != _identity(before) for item in (opened, after, current)):
        raise ProducerError(f"canonical input changed while reading: {path.name}")
    if total != before.st_size:
        raise ProducerError(f"canonical input changed size while reading: {path.name}")
    return StableFile(
        None if chunks is None else b"".join(chunks),
        total,
        digest.hexdigest(),
        _identity(before),
    )


def _strict_json(content: bytes, field: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ProducerError(f"{field} contains duplicate keys")
            value[key] = item
        return value

    try:
        value = json.loads(content, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProducerError(f"{field} must be UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ProducerError(f"{field} must be an object")
    return value


def _compact_hash(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _exact(value: object, keys: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ProducerError(f"{field} fields do not match schema v1")
    return value


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ProducerError(f"{field} must be lowercase SHA-256")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ProducerError(f"{field} must be an integer >= {minimum}")
    return value


def _relative(value: object, field: str) -> str:
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


def _record(name: str, stable: StableFile) -> dict[str, object]:
    _relative(name, "artifact name")
    return {"name": name, "size": stable.size, "sha256": stable.sha256}


def _parse_base_image(dockerfile: bytes) -> str:
    try:
        text = dockerfile.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProducerError("canonical Dockerfile must be UTF-8") from error
    images = []
    for line in text.splitlines():
        match = re.match(r"^\s*FROM\s+([^\s]+)(?:\s+AS\s+[^\s]+)?\s*$", line, re.IGNORECASE)
        if match:
            images.append(match.group(1))
    if len(images) != 1 or IMAGE_REFERENCE.fullmatch(images[0]) is None:
        raise ProducerError("canonical Dockerfile must contain one immutable FROM")
    return images[0]


def _capture_inputs(repository_root: Path) -> tuple[dict[str, StableFile], dict[str, StableFile]]:
    formal = {
        name: _stable_file(repository_root / relative, retain_bytes=True)
        for name, relative in FORMAL_SOURCE_FILES.items()
    }
    profile = _strict_json(
        formal["canonical-profile-manifest.json"].content or b"",
        "profile manifest",
    )
    checkpoint_specs = profile.get("checkpoints")
    if not isinstance(checkpoint_specs, dict) or set(checkpoint_specs) != {
        "Baseline",
        "MTL",
        "BDR",
    }:
        raise ProducerError("profile checkpoint roles are incomplete")
    checkpoints: dict[str, StableFile] = {}
    for role in sorted(checkpoint_specs):
        specification = checkpoint_specs[role]
        if not isinstance(specification, dict):
            raise ProducerError(f"checkpoint {role} specification is invalid")
        relative = _relative(specification.get("relative_path"), f"checkpoint {role} path")
        stable = _stable_file(repository_root / relative, retain_bytes=False)
        if stable.size != specification.get("size_bytes") or stable.sha256 != specification.get(
            "sha256"
        ):
            raise ProducerError(f"checkpoint {role} does not match profile manifest")
        checkpoints[role] = stable
    extras = {
        "uv.lock": _stable_file(repository_root / "uv.lock", retain_bytes=True),
        "quality-gates.toml": _stable_file(
            repository_root / "packaging/quality-gates.toml",
            retain_bytes=True,
        ),
    }
    return formal, {**checkpoints, **extras}


def _oracle_records(formal: dict[str, StableFile], base_digest: str) -> list[dict[str, object]]:
    records = []
    documents: dict[str, dict[str, Any]] = {}
    for role, (name, oracle_id, scope) in ORACLE_SPECS.items():
        stable = formal[name]
        document = _strict_json(stable.content or b"", f"{role} oracle")
        documents[role] = document
        if (
            document.get("oracle_id") != oracle_id
            or document.get("status") != "canonical"
            or document.get("scope") != scope
        ):
            raise ProducerError(f"{role} oracle identity is invalid")
        environment = document.get("environment")
        if not isinstance(environment, dict) or (
            environment.get("base_image") != base_digest
            or environment.get("system") != "Linux"
            or environment.get("machine") != "x86_64"
            or not isinstance(environment.get("python_version"), str)
            or PYTHON_310.fullmatch(environment["python_version"]) is None
        ):
            raise ProducerError(f"{role} oracle environment is invalid")
        records.append(
            {
                "role": role,
                **_record(name, stable),
                "oracle_id": oracle_id,
                "status": "canonical",
                "scope": scope,
            }
        )
    feature_hash = formal[ORACLE_SPECS["feature"][0]].sha256
    if documents["numeric"].get("provenance", {}).get("feature_oracle_sha256") != feature_hash:
        raise ProducerError("numeric oracle does not bind the feature oracle")
    return sorted(records, key=lambda record: str(record["role"]))


def _input_records(
    formal: dict[str, StableFile],
    extras: dict[str, StableFile],
    base_digest: str,
) -> dict[str, object]:
    oracles = _oracle_records(formal, base_digest)
    profile = _record(
        "canonical-profile-manifest.json",
        formal["canonical-profile-manifest.json"],
    )
    fixture = _record(
        "canonical-fixture-metadata.json",
        formal["canonical-fixture-metadata.json"],
    )
    lock_sha = extras["uv.lock"].sha256
    for role, (name, _oracle_id, _scope) in ORACLE_SPECS.items():
        document = _strict_json(formal[name].content or b"", f"{role} oracle")
        provenance = document.get("provenance")
        if not isinstance(provenance, dict):
            raise ProducerError(f"{role} oracle provenance is invalid")
        if provenance.get("profile_manifest_sha256") != profile["sha256"]:
            raise ProducerError(f"{role} oracle profile hash is invalid")
        if provenance.get("uv_lock_sha256") != lock_sha:
            raise ProducerError(f"{role} oracle uv.lock hash is invalid")
    public = _strict_json(
        formal[ORACLE_SPECS["public-e2e"][0]].content or b"",
        "public-e2e oracle",
    )
    if public["provenance"].get("fixture_metadata_sha256") != fixture["sha256"]:
        raise ProducerError("public-e2e oracle fixture metadata hash is invalid")
    profile_document = _strict_json(
        formal["canonical-profile-manifest.json"].content or b"",
        "profile manifest",
    )
    checkpoints = []
    for role in sorted(("Baseline", "MTL", "BDR")):
        specification = profile_document["checkpoints"][role]
        checkpoints.append(
            {
                "role": role,
                "path": specification["relative_path"],
                "size": extras[role].size,
                "sha256": extras[role].sha256,
            }
        )
    oracle_aggregate = _compact_hash(oracles)
    inputs: dict[str, object] = {
        "dockerfile": _record("canonical-Dockerfile", formal["canonical-Dockerfile"]),
        "oracles": oracles,
        "profile_manifest": profile,
        "fixture_metadata": fixture,
        "checkpoints": checkpoints,
        "uv_lock_sha256": lock_sha,
        "oracle_aggregate_sha256": oracle_aggregate,
    }
    inputs["input_aggregate_sha256"] = _compact_hash(inputs)
    return inputs


def _docker_json(docker: str, arguments: list[str], field: str) -> dict[str, Any]:
    result = subprocess.run(
        [docker, *arguments], check=False, capture_output=True, timeout=60
    )
    if result.returncode != 0:
        raise ProducerError(f"{field} failed")
    try:
        payload = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProducerError(f"{field} returned invalid JSON") from error
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ProducerError(f"{field} returned an invalid object")
    return payload[0]


def _inspect_base(docker: str, base_digest: str) -> dict[str, str]:
    image = _docker_json(docker, ["image", "inspect", base_digest], "base image inspect")
    if (
        not isinstance(image.get("Id"), str)
        or IMAGE_ID.fullmatch(image["Id"]) is None
        or base_digest not in image.get("RepoDigests", [])
        or image.get("Os") != "linux"
        or image.get("Architecture") != "amd64"
    ):
        raise ProducerError("base image identity is invalid")
    return {"repo_digest": base_digest, "image_id": image["Id"]}


def _build_image(
    docker: str,
    repository_root: Path,
    temporary_root: Path,
    *,
    run_id: str,
    source_sha256: str,
    input_aggregate_sha256: str,
) -> dict[str, str]:
    iidfile = temporary_root / "canonical-image.iid"
    labels = {
        LABEL_RUN_ID: run_id,
        LABEL_SOURCE: source_sha256,
        LABEL_INPUT: input_aggregate_sha256,
    }
    command = [
        docker,
        "build",
        "--platform",
        "linux/amd64",
        "--file",
        os.fspath(repository_root / "tests/golden/Dockerfile.canonical"),
        "--tag",
        IMAGE_TAG,
        "--iidfile",
        os.fspath(iidfile),
    ]
    for name, value in labels.items():
        command.extend(("--label", f"{name}={value}"))
    command.append(os.fspath(repository_root))
    result = subprocess.run(command, check=False, capture_output=True, timeout=1800)
    if result.returncode != 0:
        raise ProducerError("canonical image build failed")
    try:
        image_id = iidfile.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as error:
        raise ProducerError("canonical build did not produce a valid iidfile") from error
    if IMAGE_ID.fullmatch(image_id) is None:
        raise ProducerError("canonical build iidfile is invalid")
    image = _docker_json(docker, ["image", "inspect", image_id], "build image inspect")
    actual_labels = image.get("Config", {}).get("Labels")
    if (
        image.get("Id") != image_id
        or image.get("Os") != "linux"
        or image.get("Architecture") != "amd64"
        or not isinstance(actual_labels, dict)
        or any(actual_labels.get(name) != value for name, value in labels.items())
    ):
        raise ProducerError("canonical build image identity or labels are invalid")
    return {
        "image_id": image_id,
        "display_tag": IMAGE_TAG,
        "run_id": run_id,
        "source_sha256": source_sha256,
        "input_aggregate_sha256": input_aggregate_sha256,
    }


def _junit_summary(content: bytes) -> dict[str, int]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise ProducerError("canonical JUnit is invalid") from error
    cases = root.findall(".//testcase")
    if not cases or any(
        not (case.get("classname") or "").startswith("tests.golden.") for case in cases
    ):
        raise ProducerError("canonical JUnit is empty or contains another layer")
    return {
        "tests": len(cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
        "failures_or_errors": sum(
            case.find("failure") is not None or case.find("error") is not None
            for case in cases
        ),
    }


def _validate_observation(
    value: object,
    *,
    run_id: str,
    junit: bytes,
) -> dict[str, Any]:
    observation = _exact(
        value,
        {"schema", "schema_version", "run_id", "scope", "runtime", "installation", "execution"},
        "observation",
    )
    if (
        observation["schema"] != OBSERVATION_SCHEMA
        or observation["schema_version"] != 1
        or observation["run_id"] != run_id
    ):
        raise ProducerError("observation identity is invalid")
    scope = _exact(
        observation["scope"],
        {"os", "arch", "platform", "python_implementation", "python_version", "device"},
        "observation.scope",
    )
    if scope != {
        "os": "linux",
        "arch": "x86_64",
        "platform": "linux-x86_64",
        "python_implementation": "CPython",
        "python_version": scope.get("python_version"),
        "device": "cpu",
    } or not isinstance(scope["python_version"], str) or PYTHON_310.fullmatch(
        scope["python_version"]
    ) is None:
        raise ProducerError("observation scope is not canonical Linux CPython 3.10 CPU")
    runtime = _exact(
        observation["runtime"],
        {
            "network",
            "root_filesystem",
            "tmpfs",
            "cuda_available",
            "torch_cuda_version",
            "torch_intraop_threads",
            "omp_num_threads",
            "mkl_num_threads",
            "pythonhashseed",
            "harness_import_scope",
        },
        "observation.runtime",
    )
    network = _exact(runtime["network"], {"policy", "probe", "blocked", "result_code"}, "network")
    if (
        network["policy"] != "denied"
        or network["probe"] != "connect_ex"
        or network["blocked"] is not True
        or _integer(network["result_code"], "network.result_code", minimum=1) < 1
    ):
        raise ProducerError("network denial observation is invalid")
    rootfs = _exact(
        runtime["root_filesystem"], {"policy", "probe", "blocked", "errno"}, "root filesystem"
    )
    if rootfs != {"policy": "read-only", "probe": "create", "blocked": True, "errno": 30}:
        raise ProducerError("root filesystem observation is invalid")
    tmpfs = _exact(runtime["tmpfs"], {"path", "writable", "options"}, "tmpfs")
    if tmpfs != {"path": "/tmp", "writable": True, "options": "rw,noexec,nosuid,size=64m"}:
        raise ProducerError("tmpfs observation is invalid")
    if (
        runtime["cuda_available"] is not False
        or runtime["torch_cuda_version"] is not None
        or runtime["torch_intraop_threads"] != 1
        or runtime["omp_num_threads"] != "1"
        or runtime["mkl_num_threads"] != "1"
        or runtime["pythonhashseed"] != "0"
        or runtime["harness_import_scope"] != "workspace-source-snapshot"
    ):
        raise ProducerError("canonical runtime controls are invalid")
    installation = _exact(
        observation["installation"],
        {"distribution_name", "distribution_version", "console_entry_point", "origin_scope", "installed_package"},
        "observation.installation",
    )
    if (
        installation["distribution_name"] != "ai-auto-lrc"
        or installation["distribution_version"] != "2.0.0a0"
        or installation["console_entry_point"] != "t2l.adapters.cli:main"
        or installation["origin_scope"] != "site-packages"
    ):
        raise ProducerError("installed distribution must resolve from site-packages")
    package = _exact(installation["installed_package"], {"name", "size", "sha256"}, "installed package")
    _relative(package["name"], "installed package name")
    if package["name"] != "t2l/__init__.py":
        raise ProducerError("installed package must be t2l/__init__.py")
    _integer(package["size"], "installed package size", minimum=1)
    _hash(package["sha256"], "installed package sha256")
    execution = _exact(
        observation["execution"],
        {"command_id", "selectors", "pytest_exit_code", "input_junit_sha256", "tests", "skipped", "failures_or_errors"},
        "observation.execution",
    )
    summary = _junit_summary(junit)
    expected_execution = {
        "command_id": "canonical-golden-verify-v1",
        "selectors": list(CANONICAL_SELECTORS),
        "pytest_exit_code": 0,
        "input_junit_sha256": hashlib.sha256(junit).hexdigest(),
        **summary,
    }
    if execution != expected_execution or summary["skipped"] or summary["failures_or_errors"]:
        raise ProducerError("canonical execution does not match green JUnit")
    return {"scope": scope, "runtime": runtime, "installation": installation, "execution": execution}


def _run_container(
    docker: str,
    *,
    repository_root: Path,
    build_image_id: str,
    run_id: str,
    output_root: Path,
) -> tuple[dict[str, Any], bytes]:
    checkpoint_mount = (
        f"type=bind,source={repository_root / 'checkpoints'},"
        "target=/workspace/checkpoints,readonly"
    )
    evidence_mount = f"type=bind,source={output_root},target=/evidence"
    command = [
        docker,
        "create",
        "--platform",
        "linux/amd64",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--mount",
        checkpoint_mount,
        "--mount",
        evidence_mount,
        "--workdir",
        "/workspace",
        "--entrypoint",
        "/workspace/.venv/bin/python",
        build_image_id,
        "/workspace/tests/golden/canonical_capture_observer.py",
        "--output",
        "/evidence/observation.json",
        "--junit",
        "/evidence/canonical.xml",
        "--run-id",
        run_id,
    ]
    created = subprocess.run(command, check=False, capture_output=True, timeout=60)
    if created.returncode != 0:
        raise ProducerError("canonical container create failed")
    try:
        container_id = created.stdout.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise ProducerError("canonical container ID is invalid") from error
    if not container_id or any(character.isspace() for character in container_id):
        raise ProducerError("canonical container ID is invalid")
    try:
        started = subprocess.run(
            [docker, "start", "--attach", container_id],
            check=False,
            capture_output=True,
            timeout=1800,
        )
        sys.stdout.buffer.write(started.stdout)
        sys.stderr.buffer.write(started.stderr)
        container = _docker_json(docker, ["inspect", container_id], "container inspect")
        host = container.get("HostConfig")
        if (
            container.get("Image") != build_image_id
            or container.get("State", {}).get("ExitCode") != 0
            or not isinstance(host, dict)
            or host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or host.get("Tmpfs", {}).get("/tmp") != "rw,noexec,nosuid,size=64m"
        ):
            raise ProducerError("canonical container runtime configuration is invalid")
        if started.returncode != 0:
            raise ProducerError("canonical observer or pytest failed")
        junit_stable = _stable_file(output_root / "canonical.xml", retain_bytes=True)
        observation_stable = _stable_file(output_root / "observation.json", retain_bytes=True)
        junit = junit_stable.content or b""
        observation = _strict_json(observation_stable.content or b"", "container observation")
        return observation, junit
    finally:
        subprocess.run(
            [docker, "rm", "--force", container_id],
            check=False,
            capture_output=True,
            timeout=60,
        )


def _write_exclusive(path: Path, content: bytes) -> None:
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


def _atomic_publish(artifact_root: Path, files: dict[str, bytes]) -> None:
    if set(files) != set(FORMAL_ARTIFACTS):
        raise ProducerError("canonical artifact publication set is incomplete")
    finals = {name: artifact_root / name for name in files}
    if any(path.exists() or path.is_symlink() for path in finals.values()):
        raise ProducerError("refusing to replace canonical artifacts")
    suffix = f".{os.getpid()}.{uuid.uuid4().hex}.tmp"
    temporary = {name: artifact_root / f".{name}{suffix}" for name in files}
    published: list[Path] = []
    try:
        for name, content in files.items():
            _write_exclusive(temporary[name], content)
        order = [name for name in FORMAL_ARTIFACTS if name != "canonical-runtime.json"]
        order.append("canonical-runtime.json")
        for name in order:
            os.replace(temporary[name], finals[name])
            published.append(finals[name])
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
        raise ProducerError("canonical artifact publication failed") from error


def _same_inputs(
    before: tuple[dict[str, StableFile], dict[str, StableFile]],
    after: tuple[dict[str, StableFile], dict[str, StableFile]],
) -> bool:
    return before == after


def produce_canonical_artifacts(
    *,
    artifact_root: Path,
    run_id: str,
    source_sha256: str,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    """Produce the eleven canonical artifacts that precede the quality gate."""

    if RUN_ID.fullmatch(run_id) is None:
        raise ProducerError("run_id is invalid")
    _hash(source_sha256, "source_sha256")
    repository_root = repository_root.resolve(strict=True)
    artifact_root = artifact_root.resolve(strict=True)
    if not repository_root.is_dir() or not artifact_root.is_dir():
        raise ProducerError("repository and artifact roots must be directories")
    docker = shutil.which("docker")
    if docker is None:
        raise ProducerError("docker is required")
    before = _capture_inputs(repository_root)
    formal, extras = before
    dockerfile = formal["canonical-Dockerfile"].content or b""
    base_digest = _parse_base_image(dockerfile)
    inputs = _input_records(formal, extras, base_digest)
    base_image = _inspect_base(docker, base_digest)
    with tempfile.TemporaryDirectory(prefix="ai-auto-lrc-canonical-") as temporary:
        temporary_root = Path(temporary)
        output_root = temporary_root / "output"
        output_root.mkdir(mode=0o700)
        build_image = _build_image(
            docker,
            repository_root,
            temporary_root,
            run_id=run_id,
            source_sha256=source_sha256,
            input_aggregate_sha256=inputs["input_aggregate_sha256"],
        )
        raw_observation, junit = _run_container(
            docker,
            repository_root=repository_root,
            build_image_id=build_image["image_id"],
            run_id=run_id,
            output_root=output_root,
        )
        validated = _validate_observation(raw_observation, run_id=run_id, junit=junit)
    after = _capture_inputs(repository_root)
    if not _same_inputs(before, after):
        raise ProducerError("canonical inputs changed during build or execution")
    sidecar: dict[str, object] = {
        "schema": RUNTIME_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "layer": "canonical",
        "scope": validated["scope"],
        "image": {"base": base_image, "build": build_image},
        "inputs": inputs,
        "runtime": validated["runtime"],
        "installation": validated["installation"],
        "execution": validated["execution"],
        "provenance": {
            "scope": "canonical-functional-not-release",
            "producer_sha256": formal["canonical-producer.py"].sha256,
            "observer_sha256": formal["canonical-observer.py"].sha256,
            "runner_sha256": formal["canonical-runner.sh"].sha256,
            "policy_sha256": extras["quality-gates.toml"].sha256,
            "source_sha256": source_sha256,
            "input_aggregate_sha256": inputs["input_aggregate_sha256"],
        },
    }
    sidecar_bytes = (json.dumps(sidecar, indent=2, sort_keys=True) + "\n").encode("utf-8")
    files = {
        "canonical.xml": junit,
        "canonical-runtime.json": sidecar_bytes,
        **{
            name: stable.content or b""
            for name, stable in formal.items()
        },
    }
    _atomic_publish(artifact_root, files)
    return sidecar


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--repo-root", type=Path, default=REPOSITORY_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        produce_canonical_artifacts(
            artifact_root=arguments.artifact_root,
            run_id=arguments.run_id,
            source_sha256=arguments.source_sha256,
            repository_root=arguments.repo_root,
        )
    except (ProducerError, OSError, ValueError) as error:
        sys.stderr.write(f"canonical evidence failed: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
