from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import run_linux_package_gate as producer

IMAGE_DIGEST = "sha256:" + "1" * 64
IMAGE_REFERENCE = f"python@{IMAGE_DIGEST}"
IMAGE_ID = "sha256:" + "2" * 64
ZERO_HASH = "0" * 64
EMPTY_HASH = hashlib.sha256(b"").hexdigest()


def _manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "target": {
            "implementation": "CPython",
            "python_version": "3.11.9",
            "machine": "x86_64",
            "platform": "linux-x86_64",
            "primary_wheel_tag": "cp311-cp311-manylinux_2_36_x86_64",
        },
        "files": {
            "runtime": [
                {
                    "path": "runtime/example-1.0-py3-none-any.whl",
                    "size": 10,
                    "sha256": "a" * 64,
                }
            ],
            "build_system": [
                {
                    "path": "build-system/wheel-1.0-py3-none-any.whl",
                    "size": 20,
                    "sha256": "b" * 64,
                }
            ],
            "artifacts": [
                {
                    "path": "artifacts/ai_auto_lrc-2.0.0a0.tar.gz",
                    "size": 30,
                    "sha256": "c" * 64,
                }
            ],
            "requirements": [
                {
                    "path": "runtime-requirements.txt",
                    "size": 40,
                    "sha256": "d" * 64,
                }
            ],
        },
    }


def _record(name: str, size: int, sha256: str) -> dict[str, object]:
    return {"name": name, "size": size, "sha256": sha256}


def _observation(manifest_bytes: bytes, run_id: str) -> dict[str, object]:
    summary = producer.summarize_wheelhouse_manifest(manifest_bytes)
    return {
        "schema": "ai-auto-lrc/linux-package-observation",
        "schema_version": 1,
        "run_id": run_id,
        "scope": {
            "os": "linux",
            "arch": "x86_64",
            "python_implementation": "CPython",
            "python_version": "3.11.9",
            "platform": "linux-x86_64",
        },
        "network": {
            "policy": "denied",
            "probe": "connect_ex",
            "blocked": True,
            "result_code": 101,
        },
        "wheelhouse": summary,
        "build": {
            "source": "sdist",
            "sdist": _record("ai_auto_lrc-2.0.0a0.tar.gz", 30, "c" * 64),
            "project_wheel": _record("ai_auto_lrc-2.0.0a0-py3-none-any.whl", 50, "e" * 64),
            "runtime_wheel_tags": ["py3-none-any"],
            "build_wheel_tags": ["py3-none-any"],
            "project_wheel_tags": ["py3-none-any"],
        },
        "installation": {
            "pip_check_exit_code": 0,
            "pip_check_stdout_sha256": EMPTY_HASH,
            "pip_check_stderr_sha256": EMPTY_HASH,
            "pth_before": [],
            "pth_after": [],
            "direct_imports": list(producer.DIRECT_IMPORTS),
            "installed_package_origin_scope": "site-packages",
            "installed_package": _record("t2l/__init__.py", 60, "f" * 64),
        },
        "cli": {
            "command_id": "installed-public-e2e-v1",
            "exit_code": 0,
            "stdout_sha256": producer.EXPECTED_CLI_STDOUT_SHA256,
            "stderr_sha256": EMPTY_HASH,
            "expected_stdout_sha256": producer.EXPECTED_CLI_STDOUT_SHA256,
        },
    }


@pytest.fixture
def producer_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    manifest_path = wheelhouse / "manifest.json"
    manifest_bytes = (json.dumps(_manifest(), sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_bytes)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    repository = tmp_path / "repo"
    verifier = repository / "scripts/verify_linux_offline_wheelhouse.py"
    verifier.parent.mkdir(parents=True)
    verifier.write_text("# verifier fixture\n", encoding="utf-8")
    for relative_path in producer.EVIDENCE_BUNDLE_FILES:
        source = repository / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            source.write_bytes(b"fixture")
    run_id = "20260905T120000000000Z-" + "3" * 32
    observation = _observation(manifest_bytes, run_id)
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        if command[:3] == ["docker", "image", "inspect"]:
            payload = [{"Id": IMAGE_ID, "RepoDigests": [IMAGE_REFERENCE], "RepoTags": ["python:tag"]}]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload).encode(), b"")
        if command[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(
                command,
                0,
                (json.dumps(observation, sort_keys=True) + "\n").encode(),
                b"",
            )
        raise AssertionError(command)

    monkeypatch.setattr(producer.shutil, "which", lambda name: "docker" if name == "docker" else None)
    monkeypatch.setattr(producer.subprocess, "run", fake_run)
    return {
        "wheelhouse": wheelhouse,
        "manifest_path": manifest_path,
        "manifest_bytes": manifest_bytes,
        "artifacts": artifacts,
        "repository": repository,
        "run_id": run_id,
        "observation": observation,
        "calls": calls,
    }


def _produce(case: dict[str, object], **overrides: object) -> dict[str, object]:
    arguments = {
        "wheelhouse": case["wheelhouse"],
        "artifact_root": case["artifacts"],
        "run_id": case["run_id"],
        "image_reference": IMAGE_REFERENCE,
        "repository_root": case["repository"],
    }
    arguments.update(overrides)
    return producer.produce_package_sidecars(**arguments)


def test_producer_writes_exact_schema_and_byte_identical_manifest_copy(producer_case):
    sidecar = _produce(producer_case)

    assert set(sidecar) == {
        "schema",
        "schema_version",
        "run_id",
        "layer",
        "scope",
        "image",
        "network",
        "wheelhouse",
        "build",
        "installation",
        "cli",
    }
    assert sidecar["schema"] == "ai-auto-lrc/package-platform"
    assert sidecar["schema_version"] == 1
    assert sidecar["layer"] == "package"
    assert sidecar["image"] == {
        "image_id": IMAGE_ID,
        "repo_digest": IMAGE_REFERENCE,
        "display_tag": "python:tag",
    }
    assert (Path(producer_case["artifacts"]) / "wheelhouse-manifest.json").read_bytes() == producer_case[
        "manifest_bytes"
    ]
    written = json.loads(
        (Path(producer_case["artifacts"]) / "package-platform.json").read_text(encoding="utf-8")
    )
    assert written == sidecar
    docker_run = producer_case["calls"][1]
    assert docker_run[docker_run.index("--network") + 1] == "none"
    assert "--read-only" in docker_run
    assert IMAGE_ID in docker_run
    assert IMAGE_REFERENCE not in docker_run
    mounts = [docker_run[index + 1] for index, value in enumerate(docker_run) if value == "-v"]
    assert all(not mount.startswith(os.fspath(producer_case["repository"])) for mount in mounts)


def test_producer_records_nonempty_cli_stderr_hash_without_reclassifying_success(
    producer_case,
):
    stderr_sha256 = hashlib.sha256(b"stable runtime warning\n").hexdigest()
    producer_case["observation"]["cli"]["stderr_sha256"] = stderr_sha256

    sidecar = _produce(producer_case)

    assert sidecar["cli"]["stderr_sha256"] == stderr_sha256


@pytest.mark.parametrize(
    "image_reference",
    ("python:3.11.9-slim-bookworm", "python@sha256:1234", "sha256:" + "1" * 64),
)
def test_producer_rejects_nonimmutable_image_reference_before_docker(
    producer_case,
    image_reference: str,
):
    with pytest.raises(producer.ProducerError, match="immutable image reference"):
        _produce(producer_case, image_reference=image_reference)

    assert producer_case["calls"] == []
    assert list(Path(producer_case["artifacts"]).iterdir()) == []


def test_producer_requires_inspected_image_id_and_exact_repo_digest(producer_case, monkeypatch):
    def bad_inspect(command, **kwargs):
        payload = [{"Id": "sha256:short", "RepoDigests": ["other@" + IMAGE_DIGEST]}]
        return subprocess.CompletedProcess(command, 0, json.dumps(payload).encode(), b"")

    monkeypatch.setattr(producer.subprocess, "run", bad_inspect)

    with pytest.raises(producer.ProducerError, match="image identity"):
        _produce(producer_case)

    assert list(Path(producer_case["artifacts"]).iterdir()) == []


def test_producer_binds_observation_to_capture_run_id(producer_case):
    producer_case["observation"]["run_id"] = "different-run"

    with pytest.raises(producer.ProducerError, match=r"observation\.run_id"):
        _produce(producer_case)

    assert list(Path(producer_case["artifacts"]).iterdir()) == []


def test_producer_rejects_unknown_observation_schema_field(producer_case):
    producer_case["observation"]["qualification"] = "qualified-release"

    with pytest.raises(producer.ProducerError, match="observation fields"):
        _produce(producer_case)


def test_producer_rejects_manifest_identity_race(producer_case, monkeypatch):
    original = producer._read_stable_manifest
    calls = 0

    def raced(path: Path):
        nonlocal calls
        calls += 1
        result = original(path)
        if calls == 1:
            Path(producer_case["manifest_path"]).write_bytes(b"{}\n")
        return result

    monkeypatch.setattr(producer, "_read_stable_manifest", raced)

    with pytest.raises(producer.ProducerError, match="manifest changed during container run"):
        _produce(producer_case)

    assert list(Path(producer_case["artifacts"]).iterdir()) == []


def test_atomic_publish_failure_leaves_no_formal_sidecar(producer_case, monkeypatch):
    real_replace = producer.os.replace
    replace_calls = 0

    def fail_second(source, destination):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("injected replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(producer.os, "replace", fail_second)

    with pytest.raises(producer.ProducerError, match="atomic sidecar publication failed"):
        _produce(producer_case)

    artifacts = Path(producer_case["artifacts"])
    assert not (artifacts / "package-platform.json").exists()
    assert not (artifacts / "wheelhouse-manifest.json").exists()
    assert not list(artifacts.glob(".*.tmp"))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("installed_package", _record("/private/tmp/t2l/__init__.py", 60, "f" * 64)),
        ("direct_imports", [*producer.DIRECT_IMPORTS, "Bearer secret-token"]),
    ),
)
def test_producer_rejects_absolute_paths_and_secret_material(
    producer_case,
    field: str,
    value: object,
):
    producer_case["observation"]["installation"][field] = value

    with pytest.raises(producer.ProducerError, match=r"observation\.installation"):
        _produce(producer_case)

    output = json.dumps(producer_case["observation"])
    assert output not in "".join(str(call) for call in producer_case["calls"])
