#!/usr/bin/env python3
"""Create and verify local, content-addressed test-gate evidence manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
LAYERS = {"portable", "canonical", "package", "release"}
QUALIFICATIONS = {
    "diagnostic",
    "implemented-unqualified",
    "qualified-canonical",
    "qualified-release",
}
JUNIT_PREFIXES = {
    "portable": ("tests.unit.", "tests.contract.", "tests.component."),
    "canonical": ("tests.golden.",),
    "package": ("tests.package.",),
    "release": ("tests.release.", "tests.system."),
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
NETWORK_POLICIES = {"network-denied", "network-not-controlled"}
RELEASE_ARTIFACTS = (
    "linux_evidence",
    "macos_evidence",
    "sbom",
    "attestation",
    "signature",
    "rollback_receipt",
)


class EvidenceError(RuntimeError):
    """Raised when evidence is missing, inconsistent, or unsafe."""


def _require(mapping: object, key: str, field: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise EvidenceError(f"{field}.{key} is required")
    return mapping[key]


def _require_object(mapping: object, key: str, field: str) -> dict[str, Any]:
    value = _require(mapping, key, field)
    if not isinstance(value, dict):
        raise EvidenceError(f"{field}.{key} must be an object")
    return value


def _canonical_relative_path(value: object, field: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise EvidenceError(f"{field} must be a canonical relative path")
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or not path.parts
        or path.as_posix() != value
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise EvidenceError(f"{field} must be a canonical relative path")
    return path


def _safe_regular_file(root: Path, relative: PurePosixPath, field: str) -> Path:
    current = root.resolve()
    for index, part in enumerate(relative.parts):
        current /= part
        try:
            file_stat = current.lstat()
        except FileNotFoundError as error:
            raise EvidenceError(f"{field} does not exist: {relative.as_posix()}") from error
        if stat.S_ISLNK(file_stat.st_mode):
            raise EvidenceError(f"{field} must not use a symlink: {relative.as_posix()}")
        if index < len(relative.parts) - 1:
            if not stat.S_ISDIR(file_stat.st_mode):
                raise EvidenceError(
                    f"{field} parent is not a directory: {relative.as_posix()}"
                )
        elif not stat.S_ISREG(file_stat.st_mode):
            raise EvidenceError(
                f"{field} is not a regular file: {relative.as_posix()}"
            )
    return current


def _read_stable(path: Path, field: str) -> bytes:
    before = path.lstat()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise EvidenceError(f"{field} could not be opened safely") from error
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise EvidenceError(f"{field} changed before hashing")
        content = stream.read()
        after = os.fstat(stream.fileno())
    try:
        current = path.lstat()
    except FileNotFoundError as error:
        raise EvidenceError(f"{field} changed while hashing") from error
    identity_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    identities = [
        tuple(getattr(value, name) for name in identity_fields)
        for value in (before, opened, after, current)
    ]
    if any(identity != identities[0] for identity in identities[1:]):
        raise EvidenceError(f"{field} changed while hashing")
    return content


def _verify_record(
    record: object,
    *,
    root: Path,
    field: str,
) -> tuple[Path, bytes]:
    if not isinstance(record, dict):
        raise EvidenceError(f"{field} must be an artifact record")
    for key in ("path", "sha256", "size"):
        _require(record, key, field)
    relative = _canonical_relative_path(record["path"], f"{field}.path")
    expected_hash = record["sha256"]
    expected_size = record["size"]
    if not isinstance(expected_hash, str) or SHA256.fullmatch(expected_hash) is None:
        raise EvidenceError(f"{field}.sha256 must be a lowercase SHA-256")
    if (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size < 0
    ):
        raise EvidenceError(f"{field}.size must be a non-negative integer")
    path = _safe_regular_file(root, relative, field)
    content = _read_stable(path, field)
    if len(content) != expected_size:
        raise EvidenceError(f"{field} size mismatch")
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise EvidenceError(f"{field} hash mismatch")
    return path, content


def _make_record(root: Path, relative_path: str, field: str) -> dict[str, object]:
    relative = _canonical_relative_path(relative_path, field)
    path = _safe_regular_file(root, relative, field)
    content = _read_stable(path, field)
    return {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
    }


def _git(repo_root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise EvidenceError(message or f"git {' '.join(arguments)} failed")
    return result.stdout


def _source_state(repo_root: Path) -> dict[str, object]:
    repo_root = repo_root.resolve()
    head = _git(repo_root, "rev-parse", "HEAD").decode().strip()
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise EvidenceError("source.head must be a 40-character commit")
    status = _git(
        repo_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    digest = hashlib.sha256()
    digest.update(_git(repo_root, "diff", "--binary", "--no-ext-diff", "HEAD", "--"))
    untracked = _git(
        repo_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
    )
    for raw_path in sorted(path for path in untracked.split(b"\0") if path):
        relative_text = os.fsdecode(raw_path)
        relative = _canonical_relative_path(relative_text, "source.untracked.path")
        path = _safe_regular_file(repo_root, relative, "source.untracked")
        content = _read_stable(path, "source.untracked")
        digest.update(b"\0untracked\0")
        digest.update(raw_path)
        digest.update(b"\0")
        digest.update(str(len(content)).encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
    return {
        "head": head,
        "dirty": bool(status),
        "diff_sha256": digest.hexdigest(),
    }


def _environment(
    network_policy: str,
    container_image_digest: str | None,
) -> dict[str, str | None]:
    if network_policy not in NETWORK_POLICIES:
        raise EvidenceError(
            "environment.network_policy must be network-denied or "
            "network-not-controlled"
        )
    return {
        "os": platform.system(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "network_policy": network_policy,
        "container_image_digest": container_image_digest,
    }


def _junit_summary(content: bytes, layer: str) -> dict[str, int]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise EvidenceError(f"artifacts.junit is not valid XML: {error}") from error
    cases = root.findall(".//testcase")
    if not cases:
        raise EvidenceError("artifacts.junit contains no test cases")
    prefixes = JUNIT_PREFIXES[layer]
    outside = [
        f"{case.get('classname')}::{case.get('name')}"
        for case in cases
        if not (case.get("classname") or "").startswith(prefixes)
    ]
    if outside:
        raise EvidenceError(
            f"artifacts.junit contains tests from another layer: {outside[:5]!r}"
        )
    skipped = sum(case.find("skipped") is not None for case in cases)
    failed = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    return {
        "passed": len(cases) - skipped - failed - errors,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
    }


def _validate_release(
    release: object,
    *,
    evidence_root: Path,
    source: dict[str, Any],
) -> None:
    if not isinstance(release, dict):
        raise EvidenceError("release is required")
    tag = _require(release, "tag", "release")
    if not isinstance(tag, str) or not tag.strip():
        raise EvidenceError("release.tag must be non-empty")
    for name in RELEASE_ARTIFACTS:
        _require(release, name, "release")
    child_documents = {}
    for name in RELEASE_ARTIFACTS:
        _path, content = _verify_record(
            release[name],
            root=evidence_root,
            field=f"release.{name}",
        )
        if name.endswith("_evidence"):
            try:
                child_documents[name] = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise EvidenceError(f"release.{name} must be JSON") from error
    expected_platforms = {
        "linux_evidence": ("Linux", "x86_64"),
        "macos_evidence": ("Darwin", "arm64"),
    }
    for name, (expected_os, expected_arch) in expected_platforms.items():
        child = child_documents[name]
        child_claim = _require_object(child, "claim", f"release.{name}")
        if child_claim.get("layer") != "package":
            raise EvidenceError(f"release.{name} must reference package evidence")
        child_source = _require_object(child, "source", f"release.{name}")
        if child_source.get("head") != source["head"]:
            raise EvidenceError(f"release.{name} source head mismatch")
        child_environment = _require_object(child, "environment", f"release.{name}")
        if (
            child_environment.get("os") != expected_os
            or child_environment.get("arch") != expected_arch
        ):
            raise EvidenceError(
                f"release.{name} must be {expected_os}/{expected_arch} evidence"
            )


def _validate_document(
    document: object,
    *,
    repo_root: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise EvidenceError("manifest must be a JSON object")
    if _require(document, "schema_version", "manifest") != SCHEMA_VERSION:
        raise EvidenceError("schema_version must be 1")
    claim = _require_object(document, "claim", "manifest")
    layer = _require(claim, "layer", "claim")
    if layer not in LAYERS:
        raise EvidenceError(f"unknown claim.layer: {layer!r}")
    spec_ids = _require(claim, "spec_ids", "claim")
    if not isinstance(spec_ids, list) or not all(isinstance(item, str) for item in spec_ids):
        raise EvidenceError("claim.spec_ids must be a string array")

    source = _require_object(document, "source", "manifest")
    for key in ("head", "dirty", "diff_sha256"):
        _require(source, key, "source")
    if not isinstance(source["dirty"], bool):
        raise EvidenceError("source.dirty must be boolean")
    if not isinstance(source["head"], str) or re.fullmatch(r"[0-9a-f]{40}", source["head"]) is None:
        raise EvidenceError("source.head must be a 40-character commit")
    if not isinstance(source["diff_sha256"], str) or SHA256.fullmatch(source["diff_sha256"]) is None:
        raise EvidenceError("source.diff_sha256 must be a lowercase SHA-256")
    if source != _source_state(repo_root):
        raise EvidenceError("source state does not match the current repository")

    environment = _require_object(document, "environment", "manifest")
    for key in ("os", "arch", "python", "python_implementation", "network_policy"):
        value = _require(environment, key, "environment")
        if not isinstance(value, str) or not value.strip():
            raise EvidenceError(f"environment.{key} must be non-empty")
    image_digest = _require(environment, "container_image_digest", "environment")
    if image_digest is not None and (
        not isinstance(image_digest, str)
        or IMAGE_DIGEST.fullmatch(image_digest) is None
    ):
        raise EvidenceError(
            "environment.container_image_digest must be a sha256 image digest"
        )
    expected_environment = _environment(environment["network_policy"], image_digest)
    if environment != expected_environment:
        raise EvidenceError("environment does not match the current verifier")

    inputs = _require_object(document, "inputs", "manifest")
    _verify_record(inputs.get("lock"), root=repo_root, field="inputs.lock")
    profile = _require(inputs, "profile_manifest", "inputs")
    oracles = _require(inputs, "oracles", "inputs")
    if not isinstance(oracles, list):
        raise EvidenceError("inputs.oracles must be an array")
    if layer in {"canonical", "package", "release"}:
        _verify_record(profile, root=repo_root, field="inputs.profile_manifest")
    elif profile is not None:
        raise EvidenceError("portable inputs.profile_manifest must be null")
    if layer in {"canonical", "release"} and not oracles:
        raise EvidenceError(f"{layer} inputs.oracles must not be empty")
    for index, oracle in enumerate(oracles):
        _verify_record(oracle, root=repo_root, field=f"inputs.oracles[{index}]")

    qualification = _require_object(document, "qualification", "manifest")
    level = _require(qualification, "level", "qualification")
    if level not in QUALIFICATIONS:
        raise EvidenceError(f"unknown qualification.level: {level!r}")
    if level in {"qualified-canonical", "qualified-release"}:
        raise EvidenceError(
            f"schema_version 1 cannot produce {level}; "
            "a capture-bound container receipt is required"
        )

    package = document.get("package")
    if layer == "package":
        package = _require_object(document, "package", "manifest")
        wheelhouse = _require(package, "wheelhouse_manifest", "package")
        _verify_record(
            wheelhouse,
            root=evidence_root,
            field="package.wheelhouse_manifest",
        )
        if image_digest is None:
            raise EvidenceError(
                "environment.container_image_digest must be a sha256 image digest"
            )
    elif package is not None:
        raise EvidenceError("package is only valid for package evidence")

    artifacts = _require_object(document, "artifacts", "manifest")
    _junit_path, junit_content = _verify_record(
        artifacts.get("junit"),
        root=evidence_root,
        field="artifacts.junit",
    )
    _gate_path, gate_content = _verify_record(
        artifacts.get("gate_json"),
        root=evidence_root,
        field="artifacts.gate_json",
    )
    junit = _junit_summary(junit_content, layer)
    try:
        gate = json.loads(gate_content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError("artifacts.gate_json must be JSON") from error
    if not isinstance(gate, dict) or gate.get("layer") != layer:
        raise EvidenceError("artifacts.gate_json contains results from another layer")
    if gate.get("schema_version") != 1 or gate.get("gate") != "pytest-layer":
        raise EvidenceError("artifacts.gate_json is not a pytest-layer gate report")
    if not isinstance(gate.get("passed"), bool):
        raise EvidenceError("artifacts.gate_json.passed must be boolean")
    if gate.get("input_junit_sha256") != artifacts["junit"]["sha256"]:
        raise EvidenceError(
            "artifacts.gate_json.input_junit_sha256 does not bind artifacts.junit"
        )
    expected_gate_counts = {
        "tests": sum(junit.values()),
        "skipped": junit["skipped"],
        "failures_or_errors": junit["failed"] + junit["errors"],
    }
    for key, expected in expected_gate_counts.items():
        if gate.get(key) != expected:
            raise EvidenceError(
                f"artifacts.gate_json.{key} does not match artifacts.junit"
            )
    expected_gate_passed = (
        junit["failed"] == 0 and junit["errors"] == 0 and junit["skipped"] == 0
    )
    if gate["passed"] is not expected_gate_passed:
        raise EvidenceError(
            "artifacts.gate_json.passed does not match artifacts.junit"
        )

    run = _require_object(document, "run", "manifest")
    for key in (
        "command_id",
        "selectors",
        "started_at_utc",
        "duration_seconds",
        "exit_code",
        "passed",
        "failed",
        "errors",
        "skipped",
    ):
        _require(run, key, "run")
    if not isinstance(run["command_id"], str) or not run["command_id"].strip():
        raise EvidenceError("run.command_id must be non-empty")
    if not isinstance(run["selectors"], list) or not all(
        isinstance(item, str) for item in run["selectors"]
    ):
        raise EvidenceError("run.selectors must be a string array")
    if not isinstance(run["started_at_utc"], str) or not run["started_at_utc"].endswith("Z"):
        raise EvidenceError("run.started_at_utc must be a UTC timestamp")
    try:
        datetime.fromisoformat(run["started_at_utc"].removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise EvidenceError("run.started_at_utc must be a UTC timestamp") from error
    if (
        not isinstance(run["duration_seconds"], (int, float))
        or isinstance(run["duration_seconds"], bool)
        or run["duration_seconds"] < 0
    ):
        raise EvidenceError("run.duration_seconds must be non-negative")
    for key in ("exit_code", "passed", "failed", "errors", "skipped"):
        if not isinstance(run[key], int) or isinstance(run[key], bool) or run[key] < 0:
            raise EvidenceError(f"run.{key} must be a non-negative integer")
    for key, expected in junit.items():
        if run[key] != expected:
            raise EvidenceError(f"run.{key} does not match artifacts.junit")
    if level != "diagnostic" and (
        run["exit_code"] != 0
        or any(run[key] for key in ("failed", "errors", "skipped"))
        or gate["passed"] is not True
    ):
        raise EvidenceError("qualifying evidence requires a passing zero-skip gate")
    return document


def verify_manifest(manifest_path: Path, *, repo_root: Path) -> dict[str, Any]:
    manifest_path = manifest_path.absolute()
    if manifest_path.is_symlink():
        raise EvidenceError("evidence manifest must not be a symlink")
    if not manifest_path.is_file():
        raise EvidenceError("evidence manifest does not exist")
    content = _read_stable(manifest_path, "manifest")
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError("manifest must be valid UTF-8 JSON") from error
    return _validate_document(
        document,
        repo_root=repo_root.resolve(),
        evidence_root=manifest_path.parent,
    )


def create_manifest(
    *,
    output: Path,
    repo_root: Path,
    evidence_root: Path,
    layer: str,
    network_policy: str,
    junit: str,
    gate_json: str,
    lock: str,
    profile_manifest: str | None,
    oracles: tuple[str, ...],
    command_id: str,
    selectors: tuple[str, ...],
    started_at_utc: str,
    duration_seconds: float,
    exit_code: int,
    qualification: str,
    spec_ids: tuple[str, ...],
    container_image_digest: str | None,
    wheelhouse_manifest: str | None,
    release: dict[str, str] | None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    evidence_root = evidence_root.resolve()
    output = output.resolve(strict=False)
    try:
        output.relative_to(evidence_root)
    except ValueError as error:
        raise EvidenceError("output must be inside evidence_root") from error
    if output.exists() or output.is_symlink():
        raise EvidenceError(f"refusing to replace existing output: {output}")

    junit_record = _make_record(evidence_root, junit, "artifacts.junit")
    _junit_path, junit_content = _verify_record(
        junit_record,
        root=evidence_root,
        field="artifacts.junit",
    )
    summary = _junit_summary(junit_content, layer)
    inputs = {
        "lock": _make_record(repo_root, lock, "inputs.lock"),
        "profile_manifest": (
            None
            if profile_manifest is None
            else _make_record(
                repo_root,
                profile_manifest,
                "inputs.profile_manifest",
            )
        ),
        "oracles": [
            _make_record(repo_root, oracle, f"inputs.oracles[{index}]")
            for index, oracle in enumerate(oracles)
        ],
    }
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "claim": {"layer": layer, "spec_ids": list(spec_ids)},
        "source": _source_state(repo_root),
        "environment": _environment(network_policy, container_image_digest),
        "inputs": inputs,
        "run": {
            "command_id": command_id,
            "selectors": list(selectors),
            "started_at_utc": started_at_utc,
            "duration_seconds": duration_seconds,
            "exit_code": exit_code,
            **summary,
        },
        "artifacts": {
            "junit": junit_record,
            "gate_json": _make_record(
                evidence_root,
                gate_json,
                "artifacts.gate_json",
            ),
        },
        "qualification": {"level": qualification},
    }
    if layer == "package":
        package = {}
        if wheelhouse_manifest is not None:
            package["wheelhouse_manifest"] = _make_record(
                evidence_root,
                wheelhouse_manifest,
                "package.wheelhouse_manifest",
            )
        document["package"] = package
    if release is not None:
        document["release"] = {
            "tag": release["tag"],
            **{
                name: _make_record(
                    evidence_root,
                    release[name],
                    f"release.{name}",
                )
                for name in RELEASE_ARTIFACTS
                if name in release
            },
        }
    _validate_document(document, repo_root=repo_root, evidence_root=evidence_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise EvidenceError(f"refusing to replace existing temporary output: {temporary}")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return document


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--repo-root", type=Path, required=True)
    create.add_argument("--evidence-root", type=Path, required=True)
    create.add_argument("--output", required=True)
    create.add_argument("--layer", choices=sorted(LAYERS), required=True)
    create.add_argument("--network-policy", required=True)
    create.add_argument("--junit", required=True)
    create.add_argument("--gate-json", required=True)
    create.add_argument("--lock", default="uv.lock")
    create.add_argument("--profile-manifest")
    create.add_argument("--oracle", action="append", default=[])
    create.add_argument("--command-id", required=True)
    create.add_argument("--selector", action="append", default=[])
    create.add_argument("--started-at-utc", required=True)
    create.add_argument("--duration-seconds", type=float, required=True)
    create.add_argument("--exit-code", type=int, required=True)
    create.add_argument("--qualification", choices=sorted(QUALIFICATIONS), required=True)
    create.add_argument("--spec-id", action="append", default=[])
    create.add_argument("--container-image-digest")
    create.add_argument("--wheelhouse-manifest")
    create.add_argument("--release-tag")
    for name in RELEASE_ARTIFACTS:
        create.add_argument(f"--{name.replace('_', '-')}")

    verify = subparsers.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--repo-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "verify":
            document = verify_manifest(arguments.manifest, repo_root=arguments.repo_root)
        else:
            evidence_root = arguments.evidence_root.resolve()
            output_relative = _canonical_relative_path(arguments.output, "output")
            release_values = {
                "tag": arguments.release_tag,
                **{name: getattr(arguments, name) for name in RELEASE_ARTIFACTS},
            }
            release = (
                None
                if all(value is None for value in release_values.values())
                else {key: value for key, value in release_values.items() if value is not None}
            )
            document = create_manifest(
                output=evidence_root.joinpath(*output_relative.parts),
                repo_root=arguments.repo_root,
                evidence_root=evidence_root,
                layer=arguments.layer,
                network_policy=arguments.network_policy,
                junit=arguments.junit,
                gate_json=arguments.gate_json,
                lock=arguments.lock,
                profile_manifest=arguments.profile_manifest,
                oracles=tuple(arguments.oracle),
                command_id=arguments.command_id,
                selectors=tuple(arguments.selector),
                started_at_utc=arguments.started_at_utc,
                duration_seconds=arguments.duration_seconds,
                exit_code=arguments.exit_code,
                qualification=arguments.qualification,
                spec_ids=tuple(arguments.spec_id),
                container_image_digest=arguments.container_image_digest,
                wheelhouse_manifest=arguments.wheelhouse_manifest,
                release=release,
            )
    except (EvidenceError, OSError, ValueError, KeyError) as error:
        sys.stderr.write(f"evidence verification failed: {error}\n")
        return 1
    sys.stdout.write(
        json.dumps(
            {
                "valid": True,
                "layer": document["claim"]["layer"],
                "qualification": document["qualification"]["level"],
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
