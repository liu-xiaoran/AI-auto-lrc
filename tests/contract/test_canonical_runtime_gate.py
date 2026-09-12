from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import run_canonical_gate as producer

BASE_DIGEST = "python@sha256:" + "1" * 64
BASE_ID = "sha256:" + "2" * 64
BUILD_ID = "sha256:" + "3" * 64
SOURCE_SHA256 = "4" * 64
RUN_ID = "20260906T120000000000Z-" + "5" * 32


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture
def canonical_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    dockerfile = repo / "tests/golden/Dockerfile.canonical"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text(f"FROM {BASE_DIGEST}\n", encoding="utf-8")
    (repo / "uv.lock").write_text("lock\n", encoding="utf-8")
    profile = repo / "t2l/_assets/legacy_v1_manifest.json"
    checkpoint_records = {}
    for role in ("BDR", "Baseline", "MTL"):
        checkpoint = repo / f"checkpoints/checkpoint_{role}"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(role.encode())
        checkpoint_records[role] = {
            "relative_path": checkpoint.relative_to(repo).as_posix(),
            "size_bytes": checkpoint.stat().st_size,
            "sha256": _sha256(checkpoint),
        }
    _write_json(profile, {"profile_id": "legacy-v1", "checkpoints": checkpoint_records})
    fixture = repo / "tests/fixtures/audio/sine-440hz-250ms-mono-22050.json"
    _write_json(fixture, {"schema_version": 1, "file": "fixture.mp3"})
    profile_sha = _sha256(profile)
    fixture_sha = _sha256(fixture)
    lock_sha = _sha256(repo / "uv.lock")
    feature = repo / "tests/golden/legacy_v1_feature_manifest.json"
    _write_json(
        feature,
        {
            "oracle_id": "legacy-v1-feature-linux-x86_64-cpython310",
            "status": "canonical",
            "scope": "feature-only",
            "environment": {
                "base_image": BASE_DIGEST,
                "machine": "x86_64",
                "python_version": "3.10.21",
                "system": "Linux",
            },
            "provenance": {
                "profile_manifest_sha256": profile_sha,
                "uv_lock_sha256": lock_sha,
            },
        },
    )
    numeric = repo / "tests/golden/legacy_v1_numeric_manifest.json"
    _write_json(
        numeric,
        {
            "oracle_id": "legacy-v1-numeric-linux-x86_64-cpython310",
            "status": "canonical",
            "scope": "checkpoint-numeric-and-rendering",
            "environment": {
                "base_image": BASE_DIGEST,
                "machine": "x86_64",
                "python_version": "3.10.21",
                "system": "Linux",
            },
            "provenance": {
                "feature_oracle_sha256": _sha256(feature),
                "profile_manifest_sha256": profile_sha,
                "uv_lock_sha256": lock_sha,
            },
        },
    )
    public = repo / "tests/golden/legacy_v1_public_e2e_manifest.json"
    _write_json(
        public,
        {
            "oracle_id": "legacy-v1-real-mp3-public-api-installed-cli-linux-x86_64-cpython310",
            "status": "canonical",
            "scope": "real-decoder-public-api-installed-cli",
            "environment": {
                "base_image": BASE_DIGEST,
                "machine": "x86_64",
                "python_version": "3.10.21",
                "system": "Linux",
            },
            "provenance": {
                "fixture_metadata_sha256": fixture_sha,
                "profile_manifest_sha256": profile_sha,
                "uv_lock_sha256": lock_sha,
            },
        },
    )
    for relative, content in (
        ("scripts/run_canonical_gate.py", "producer\n"),
        ("tests/golden/canonical_capture_observer.py", "observer\n"),
        ("scripts/run_canonical_legacy_v1_golden.sh", "runner\n"),
        ("packaging/quality-gates.toml", "policy\n"),
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return repo


def _junit() -> bytes:
    return (
        b'<testsuites><testsuite><testcase classname="tests.golden.test_one" '
        b'name="test_ok"/></testsuite></testsuites>\n'
    )


def _observation(junit: bytes) -> dict[str, object]:
    return {
        "schema": "ai-auto-lrc/canonical-container-observation",
        "schema_version": 1,
        "run_id": RUN_ID,
        "scope": {
            "os": "linux",
            "arch": "x86_64",
            "platform": "linux-x86_64",
            "python_implementation": "CPython",
            "python_version": "3.10.21",
            "device": "cpu",
        },
        "runtime": {
            "network": {
                "policy": "denied",
                "probe": "connect_ex",
                "blocked": True,
                "result_code": 101,
            },
            "root_filesystem": {
                "policy": "read-only",
                "probe": "create",
                "blocked": True,
                "errno": 30,
            },
            "tmpfs": {
                "path": "/tmp",
                "writable": True,
                "options": "rw,noexec,nosuid,size=64m",
            },
            "cuda_available": False,
            "torch_cuda_version": None,
            "torch_intraop_threads": 1,
            "omp_num_threads": "1",
            "mkl_num_threads": "1",
            "pythonhashseed": "0",
            "harness_import_scope": "workspace-source-snapshot",
        },
        "installation": {
            "distribution_name": "ai-auto-lrc",
            "distribution_version": "2.0.0a0",
            "console_entry_point": "t2l.adapters.cli:main",
            "origin_scope": "site-packages",
            "installed_package": {
                "name": "t2l/__init__.py",
                "size": 12,
                "sha256": "6" * 64,
            },
        },
        "execution": {
            "command_id": "canonical-golden-verify-v1",
            "selectors": list(producer.CANONICAL_SELECTORS),
            "pytest_exit_code": 0,
            "input_junit_sha256": hashlib.sha256(junit).hexdigest(),
            "tests": 1,
            "skipped": 0,
            "failures_or_errors": 0,
        },
    }


def test_producer_publishes_exact_eleven_artifacts_with_build_identity(
    canonical_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    junit = _junit()
    calls: list[list[str]] = []

    monkeypatch.setattr(producer.shutil, "which", lambda name: "/usr/bin/docker")

    def fake_run(command, **kwargs):
        command = list(command)
        calls.append(command)
        if command[1:3] == ["image", "inspect"] and command[-1] == BASE_DIGEST:
            payload = [{"Id": BASE_ID, "RepoDigests": [BASE_DIGEST], "Os": "linux", "Architecture": "amd64"}]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload).encode(), b"")
        if command[1] == "build":
            iidfile = Path(command[command.index("--iidfile") + 1])
            iidfile.write_text(BUILD_ID + "\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if command[1:3] == ["image", "inspect"] and command[-1] == BUILD_ID:
            labels = {
                item.split("=", 1)[0]: item.split("=", 1)[1]
                for index, item in enumerate(calls[-2])
                if calls[-2][index - 1] == "--label"
            }
            payload = [{"Id": BUILD_ID, "RepoDigests": [], "Os": "linux", "Architecture": "amd64", "Config": {"Labels": labels}}]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload).encode(), b"")
        if command[1] == "create":
            return subprocess.CompletedProcess(command, 0, b"container-id\n", b"")
        if command[1] == "start":
            evidence_mount = next(
                item for item in calls[-2] if "target=/evidence" in item
            )
            output = Path(evidence_mount.split("source=", 1)[1].split(",", 1)[0])
            (output / "canonical.xml").write_bytes(junit)
            (output / "observation.json").write_text(
                json.dumps(_observation(junit)), encoding="utf-8"
            )
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if command[1] == "inspect":
            payload = [{"Image": BUILD_ID, "State": {"ExitCode": 0}, "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m"}}}]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload).encode(), b"")
        if command[1:3] == ["rm", "--force"]:
            return subprocess.CompletedProcess(command, 0, b"", b"")
        raise AssertionError(command)

    monkeypatch.setattr(producer.subprocess, "run", fake_run)

    sidecar = producer.produce_canonical_artifacts(
        artifact_root=artifact_root,
        run_id=RUN_ID,
        source_sha256=SOURCE_SHA256,
        repository_root=canonical_repo,
    )

    assert {path.name for path in artifact_root.iterdir()} == set(
        producer.FORMAL_ARTIFACTS
    )
    assert sidecar["image"]["base"] == {
        "repo_digest": BASE_DIGEST,
        "image_id": BASE_ID,
    }
    assert sidecar["image"]["build"]["image_id"] == BUILD_ID
    build_call = next(call for call in calls if call[1] == "build")
    assert "--iidfile" in build_call
    create_call = next(call for call in calls if call[1] == "create")
    assert BUILD_ID in create_call
    assert producer.IMAGE_TAG not in create_call
    assert create_call[create_call.index("--network") + 1] == "none"
    assert "--read-only" in create_call


def test_parser_rejects_mutable_base_image():
    with pytest.raises(producer.ProducerError, match="immutable FROM"):
        producer._parse_base_image(b"FROM python:3.10\n")


def test_observation_rejects_workspace_installed_origin():
    junit = _junit()
    observation = _observation(junit)
    observation["installation"]["origin_scope"] = "workspace"

    with pytest.raises(producer.ProducerError, match="site-packages"):
        producer._validate_observation(observation, run_id=RUN_ID, junit=junit)


def test_build_image_rejects_missing_identity_labels(
    canonical_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run(command, **kwargs):
        command = list(command)
        if command[1] == "build":
            Path(command[command.index("--iidfile") + 1]).write_text(
                BUILD_ID + "\n", encoding="utf-8"
            )
            return subprocess.CompletedProcess(command, 0, b"", b"")
        payload = [
            {
                "Id": BUILD_ID,
                "RepoDigests": [],
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {"Labels": {}},
            }
        ]
        return subprocess.CompletedProcess(command, 0, json.dumps(payload).encode(), b"")

    monkeypatch.setattr(producer.subprocess, "run", fake_run)

    with pytest.raises(producer.ProducerError, match="identity or labels"):
        producer._build_image(
            "/usr/bin/docker",
            canonical_repo,
            tmp_path,
            run_id=RUN_ID,
            source_sha256=SOURCE_SHA256,
            input_aggregate_sha256="7" * 64,
        )


def test_producer_rejects_input_identity_change_before_publish(
    canonical_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    junit = _junit()
    monkeypatch.setattr(producer.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(
        producer,
        "_inspect_base",
        lambda docker, digest: {"repo_digest": digest, "image_id": BASE_ID},
    )
    monkeypatch.setattr(
        producer,
        "_build_image",
        lambda *args, **kwargs: {
            "image_id": BUILD_ID,
            "display_tag": producer.IMAGE_TAG,
            "run_id": RUN_ID,
            "source_sha256": SOURCE_SHA256,
            "input_aggregate_sha256": kwargs["input_aggregate_sha256"],
        },
    )
    monkeypatch.setattr(
        producer,
        "_run_container",
        lambda *args, **kwargs: (_observation(junit), junit),
    )
    monkeypatch.setattr(producer, "_same_inputs", lambda before, after: False)

    with pytest.raises(producer.ProducerError, match="inputs changed"):
        producer.produce_canonical_artifacts(
            artifact_root=artifact_root,
            run_id=RUN_ID,
            source_sha256=SOURCE_SHA256,
            repository_root=canonical_repo,
        )

    assert not any((artifact_root / name).exists() for name in producer.FORMAL_ARTIFACTS)


def test_atomic_publish_failure_leaves_no_formal_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    real_replace = producer.os.replace
    calls = 0

    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected")
        return real_replace(source, destination)

    monkeypatch.setattr(producer.os, "replace", fail_second)

    with pytest.raises(producer.ProducerError, match="publication failed"):
        producer._atomic_publish(
            artifact_root,
            {name: name.encode() for name in producer.FORMAL_ARTIFACTS},
        )

    assert not any((artifact_root / name).exists() for name in producer.FORMAL_ARTIFACTS)
