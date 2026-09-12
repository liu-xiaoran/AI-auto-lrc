from __future__ import annotations

import copy
import errno
import inspect
import json
import os
import signal
import stat
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts import capture_test_gate

_DELETE = object()
_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_PACKAGE_IMPORTS = [
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
]


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_runner(path: Path) -> None:
    path.write_text(
        """#!/bin/sh
set -eu
layer="$1"
artifact_root="$AI_AUTO_LRC_GATE_ARTIFACT_DIR"
mkdir -p "$artifact_root"
case "$layer" in
  portable)
    printf '<testsuites><testsuite><testcase classname="tests.unit.test_fake" name="test_ok"/></testsuite></testsuites>\n' > "$artifact_root/portable.xml"
    printf '{"meta":{"branch_coverage":true}}\n' > "$artifact_root/coverage.json"
    junit_sha=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$artifact_root/portable.xml")
    coverage_sha=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$artifact_root/coverage.json")
    printf '{"schema_version":1,"gate":"pytest-layer","layer":"portable","passed":true,"tests":1,"skipped":0,"failures_or_errors":0,"run_id":"%s","input_junit_sha256":"%s","policy_sha256":"%s"}\n' "$AI_AUTO_LRC_EVIDENCE_RUN_ID" "$junit_sha" "$AI_AUTO_LRC_EVIDENCE_POLICY_SHA256" > "$artifact_root/portable-gate.json"
    printf '{"schema_version":1,"gate":"coverage","passed":true,"run_id":"%s","input_coverage_sha256":"%s","policy_sha256":"%s","base_ref":"%s"}\n' "$AI_AUTO_LRC_EVIDENCE_RUN_ID" "$coverage_sha" "$AI_AUTO_LRC_EVIDENCE_POLICY_SHA256" "$AI_AUTO_LRC_EVIDENCE_BASE_REF" > "$artifact_root/coverage-gate.json"
    ;;
  package)
    printf '<testsuites><testsuite><testcase classname="tests.package.test_fake" name="test_ok"/></testsuite></testsuites>\n' > "$artifact_root/package.xml"
    printf '{"layer":"package","passed":true}\n' > "$artifact_root/package-gate.json"
    printf '{"image_digest":"sha256:%064d"}\n' 0 > "$artifact_root/package-platform.json"
    printf '{"schema_version":1}\n' > "$artifact_root/wheelhouse-manifest.json"
    ;;
  canonical)
    printf '<testsuites><testsuite><testcase classname="tests.golden.test_fake" name="test_ok"/></testsuite></testsuites>\n' > "$artifact_root/canonical.xml"
    printf '{"layer":"canonical","passed":true}\n' > "$artifact_root/canonical-gate.json"
    printf '{"image_id":"sha256:%064d"}\n' 0 > "$artifact_root/canonical-runtime.json"
    ;;
esac
printf 'stdout\\377bytes\n'
printf 'stderr\\376bytes\n' >&2
if [ -n "${FAKE_MUTATE_PATH:-}" ]; then
  printf 'changed\n' >> "$FAKE_MUTATE_PATH"
fi
exit "${FAKE_GATE_RC:-0}"
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


@pytest.fixture
def capture_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "capture@example.invalid")
    _git(repo, "config", "user.name", "Capture Test")
    (repo / "uv.lock").write_text("lock\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
    policy = repo / "packaging/quality-gates.toml"
    policy.parent.mkdir()
    policy.write_text("schema_version = 1\n", encoding="utf-8")
    _write_runner(scripts / "run_test_gate.sh")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    retention = tmp_path / "retention"
    retention.mkdir()
    return repo, retention


def _receipt(result: capture_test_gate.CaptureResult) -> dict[str, object]:
    assert result.run_directory is not None
    return json.loads((result.run_directory / "receipt.json").read_text(encoding="utf-8"))


def _rewrite_sealed_receipt(
    run_directory: Path,
    document: dict[str, object],
) -> None:
    receipt_path = run_directory / "receipt.json"
    marker_path = run_directory / "SEALED"
    receipt_bytes = capture_test_gate._json_bytes(document)
    run_directory.chmod(0o700)
    receipt_path.chmod(0o600)
    marker_path.chmod(0o600)
    receipt_path.write_bytes(receipt_bytes)
    marker_path.write_bytes(
        capture_test_gate._json_bytes(
            {
                "run_id": document["run_id"],
                "receipt_sha256": capture_test_gate._sha256(receipt_bytes),
            }
        )
    )
    receipt_path.chmod(0o400)
    marker_path.chmod(0o400)
    run_directory.chmod(0o500)


def _package_manifest() -> dict[str, object]:
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
            "requirements": [
                {
                    "path": "runtime-requirements.txt",
                    "size": 4,
                    "sha256": "d" * 64,
                }
            ],
            "runtime": [
                {
                    "path": "runtime/example-1.0-py2.py3-none-any.whl",
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
        },
    }


def _package_aggregate(manifest: dict[str, object]) -> str:
    flattened = [
        {"group": group, **record}
        for group, records in manifest["files"].items()
        for record in records
    ]
    flattened.sort(key=lambda record: (record["group"], record["path"]))
    content = json.dumps(flattened, separators=(",", ":"), sort_keys=True).encode()
    return capture_test_gate._sha256(content)


def _change_path(document: dict[str, object], path: str, value: object) -> None:
    parts = path.split(".")
    target = document
    for part in parts[:-1]:
        target = target[part]
    if value is _DELETE:
        del target[parts[-1]]
    else:
        target[parts[-1]] = value


def _write_valid_package_artifacts(
    artifact_root: Path,
    *,
    run_id: str,
    policy_sha256: str,
    mutation: tuple[str, str, object] | None = None,
) -> None:
    junit = (
        b'<testsuites><testsuite><testcase classname="tests.package.test_fake" '
        b'name="test_ok"/></testsuite></testsuites>\n'
    )
    manifest = _package_manifest()
    manifest_bytes = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    sidecar = {
        "schema": "ai-auto-lrc/package-platform",
        "schema_version": 1,
        "run_id": run_id,
        "layer": "package",
        "scope": {
            "os": "linux",
            "arch": "x86_64",
            "python_implementation": "CPython",
            "python_version": "3.11.9",
            "platform": "linux-x86_64",
        },
        "image": {
            "image_id": "sha256:" + "1" * 64,
            "repo_digest": "python@sha256:" + "2" * 64,
            "display_tag": "python:3.11.9-slim-bookworm",
        },
        "network": {
            "policy": "denied",
            "probe": "connect_ex",
            "blocked": True,
            "result_code": 101,
        },
        "wheelhouse": {
            "manifest_path": "wheelhouse-manifest.json",
            "manifest_sha256": capture_test_gate._sha256(manifest_bytes),
            "runtime_wheel_count": 1,
            "build_wheel_count": 1,
            "artifact_count": 1,
            "aggregate_sha256": _package_aggregate(manifest),
        },
        "build": {
            "source": "sdist",
            "sdist": {
                "name": "ai_auto_lrc-2.0.0a0.tar.gz",
                "size": 30,
                "sha256": "c" * 64,
            },
            "project_wheel": {
                "name": "ai_auto_lrc-2.0.0a0-py3-none-any.whl",
                "size": 50,
                "sha256": "e" * 64,
            },
            "runtime_wheel_tags": ["py2-none-any", "py3-none-any"],
            "build_wheel_tags": ["py3-none-any"],
            "project_wheel_tags": ["py3-none-any"],
        },
        "installation": {
            "pip_check_exit_code": 0,
            "pip_check_stdout_sha256": _EMPTY_SHA256,
            "pip_check_stderr_sha256": _EMPTY_SHA256,
            "pth_before": [
                {
                    "name": "lib/python3.11/site-packages/distutils-precedence.pth",
                    "size": 8,
                    "sha256": "f" * 64,
                }
            ],
            "pth_after": [
                {
                    "name": "lib/python3.11/site-packages/distutils-precedence.pth",
                    "size": 8,
                    "sha256": "f" * 64,
                }
            ],
            "direct_imports": list(_PACKAGE_IMPORTS),
            "installed_package_origin_scope": "site-packages",
            "installed_package": {
                "name": "t2l/__init__.py",
                "size": 60,
                "sha256": "9" * 64,
            },
        },
        "cli": {
            "command_id": "installed-public-e2e-v1",
            "exit_code": 0,
            "stdout_sha256": "8" * 64,
            "stderr_sha256": _EMPTY_SHA256,
            "expected_stdout_sha256": "8" * 64,
        },
    }
    gate = {
        "schema_version": 1,
        "gate": "pytest-layer",
        "layer": "package",
        "required_markers": ["package"],
        "passed": True,
        "tests": 1,
        "skipped": 0,
        "failures_or_errors": 0,
        "outside_layer": [],
        "failures": [],
        "run_id": run_id,
        "input_junit_sha256": capture_test_gate._sha256(junit),
        "policy_sha256": policy_sha256,
    }
    if mutation is not None:
        target_name, path, value = mutation
        if target_name == "junit":
            assert path == "content" and isinstance(value, bytes)
            junit = value
        else:
            target = {"sidecar": sidecar, "manifest": manifest, "gate": gate}[
                target_name
            ]
            _change_path(target, path, value)
            manifest_bytes = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "package.xml").write_bytes(junit)
    (artifact_root / "package-gate.json").write_text(
        json.dumps(gate, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifact_root / "package-platform.json").write_text(
        json.dumps(sidecar, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifact_root / "wheelhouse-manifest.json").write_bytes(manifest_bytes)


def _capture_package_fixture(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    mutation: tuple[str, str, object] | None = None,
) -> capture_test_gate.CaptureResult:
    repo, retention = capture_repo

    def fake_gate_process(
        _command,
        *,
        cwd,
        environment,
        stdout,
        stderr,
    ):
        del cwd, stdout, stderr
        _write_valid_package_artifacts(
            Path(environment["AI_AUTO_LRC_GATE_ARTIFACT_DIR"]),
            run_id=environment["AI_AUTO_LRC_EVIDENCE_RUN_ID"],
            policy_sha256=environment["AI_AUTO_LRC_EVIDENCE_POLICY_SHA256"],
            mutation=mutation,
        )
        return 0, None

    monkeypatch.setattr(capture_test_gate, "_run_gate_process", fake_gate_process)
    return capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="package",
        base_ref="HEAD",
    )


def _named_bytes_record(name: str, content: bytes) -> dict[str, object]:
    return {
        "name": name,
        "size": len(content),
        "sha256": capture_test_gate._sha256(content),
    }


def _canonical_aggregate(value: object) -> str:
    content = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return capture_test_gate._sha256(content)


def _canonical_fixture(
    run_id: str,
    policy_sha256: str,
    source_sha256: str,
    uv_lock_sha256: str,
):
    base_digest = "python@sha256:" + "1" * 64
    checkpoint_hashes = {
        "Baseline": "a" * 64,
        "MTL": "b" * 64,
        "BDR": "c" * 64,
    }
    profile = {
        "schema_version": 1,
        "checkpoints": {
            role: {
                "relative_path": f"checkpoints/checkpoint_{role}",
                "size_bytes": index + 10,
                "sha256": checkpoint_hashes[role],
            }
            for index, role in enumerate(("Baseline", "MTL", "BDR"))
        },
    }
    fixture = {
        "schema_version": 1,
        "file": "sine.mp3",
        "size_bytes": 12,
        "sha256": "d" * 64,
    }
    profile_bytes = (json.dumps(profile, sort_keys=True) + "\n").encode()
    fixture_bytes = (json.dumps(fixture, sort_keys=True) + "\n").encode()
    common_environment = {
        "base_image": base_digest,
        "system": "Linux",
        "machine": "x86_64",
        "python_version": "3.10.21",
    }
    feature = {
        "schema_version": 1,
        "status": "canonical",
        "oracle_id": "legacy-v1-feature-linux-x86_64-cpython310",
        "scope": "feature-only",
        "environment": common_environment,
        "provenance": {
            "profile_manifest_sha256": capture_test_gate._sha256(profile_bytes),
            "uv_lock_sha256": uv_lock_sha256,
        },
    }
    feature_bytes = (json.dumps(feature, sort_keys=True) + "\n").encode()
    routes = {
        "Baseline": {
            "checkpoint_sha256": checkpoint_hashes["Baseline"],
            "boundary_checkpoint_sha256": None,
        },
        "Baseline_BDR": {
            "checkpoint_sha256": checkpoint_hashes["Baseline"],
            "boundary_checkpoint_sha256": checkpoint_hashes["BDR"],
        },
        "MTL": {
            "checkpoint_sha256": checkpoint_hashes["MTL"],
            "boundary_checkpoint_sha256": None,
        },
        "MTL_BDR": {
            "checkpoint_sha256": checkpoint_hashes["MTL"],
            "boundary_checkpoint_sha256": checkpoint_hashes["BDR"],
        },
    }
    numeric = {
        "schema_version": 1,
        "status": "canonical",
        "oracle_id": "legacy-v1-numeric-linux-x86_64-cpython310",
        "scope": "checkpoint-numeric-and-rendering",
        "environment": common_environment,
        "routes": routes,
        "provenance": {
            "provenance_scope": (
                "canonical functional evidence; not clean release provenance"
            ),
            "feature_oracle_sha256": capture_test_gate._sha256(feature_bytes),
            "profile_manifest_sha256": capture_test_gate._sha256(profile_bytes),
            "uv_lock_sha256": uv_lock_sha256,
        },
    }
    public_e2e = {
        "schema_version": 1,
        "status": "canonical",
        "oracle_id": (
            "legacy-v1-real-mp3-public-api-installed-cli-linux-x86_64-cpython310"
        ),
        "scope": "real-decoder-public-api-installed-cli",
        "environment": common_environment,
        "routes": routes,
        "distribution": {
            "name": "ai-auto-lrc",
            "version": "2.0.0a0",
            "console_entry_point": "t2l.adapters.cli:main",
        },
        "provenance": {
            "provenance_scope": (
                "canonical functional evidence; not clean release provenance"
            ),
            "profile_manifest_sha256": capture_test_gate._sha256(profile_bytes),
            "uv_lock_sha256": uv_lock_sha256,
            "fixture_metadata_sha256": capture_test_gate._sha256(fixture_bytes),
        },
    }
    oracle_documents = {
        "feature": feature,
        "numeric": numeric,
        "public-e2e": public_e2e,
    }
    oracle_names = {
        "feature": "canonical-feature-oracle.json",
        "numeric": "canonical-numeric-oracle.json",
        "public-e2e": "canonical-public-e2e-oracle.json",
    }
    artifacts = {
        oracle_names[role]: (json.dumps(document, sort_keys=True) + "\n").encode()
        for role, document in oracle_documents.items()
    }
    artifacts.update(
        {
            "canonical-Dockerfile": f"FROM {base_digest}\n".encode(),
            "canonical-profile-manifest.json": profile_bytes,
            "canonical-fixture-metadata.json": fixture_bytes,
            "canonical-producer.py": b"# producer\n",
            "canonical-observer.py": b"# observer\n",
            "canonical-runner.sh": b"#!/bin/sh\n# runner\n",
        }
    )
    oracle_records = [
        {
            "role": role,
            **_named_bytes_record(oracle_names[role], artifacts[oracle_names[role]]),
            "oracle_id": oracle_documents[role]["oracle_id"],
            "status": "canonical",
            "scope": oracle_documents[role]["scope"],
        }
        for role in ("feature", "numeric", "public-e2e")
    ]
    checkpoint_records = [
        {
            "role": role,
            "path": profile["checkpoints"][role]["relative_path"],
            "size": profile["checkpoints"][role]["size_bytes"],
            "sha256": profile["checkpoints"][role]["sha256"],
        }
        for role in ("BDR", "Baseline", "MTL")
    ]
    oracle_aggregate = _canonical_aggregate(oracle_records)
    inputs_basis = {
        "dockerfile": _named_bytes_record(
            "canonical-Dockerfile", artifacts["canonical-Dockerfile"]
        ),
        "oracles": oracle_records,
        "profile_manifest": _named_bytes_record(
            "canonical-profile-manifest.json",
            artifacts["canonical-profile-manifest.json"],
        ),
        "fixture_metadata": _named_bytes_record(
            "canonical-fixture-metadata.json",
            artifacts["canonical-fixture-metadata.json"],
        ),
        "checkpoints": checkpoint_records,
        "uv_lock_sha256": uv_lock_sha256,
        "oracle_aggregate_sha256": oracle_aggregate,
    }
    input_aggregate = _canonical_aggregate(inputs_basis)
    sidecar = {
        "schema": "ai-auto-lrc/canonical-runtime",
        "schema_version": 1,
        "run_id": run_id,
        "layer": "canonical",
        "scope": {
            "os": "linux",
            "arch": "x86_64",
            "platform": "linux-x86_64",
            "python_implementation": "CPython",
            "python_version": "3.10.21",
            "device": "cpu",
        },
        "image": {
            "base": {"repo_digest": base_digest, "image_id": "sha256:" + "2" * 64},
            "build": {
                "image_id": "sha256:" + "3" * 64,
                "display_tag": "ai-auto-lrc-canonical:display-only",
                "run_id": run_id,
                "source_sha256": source_sha256,
                "input_aggregate_sha256": input_aggregate,
            },
        },
        "inputs": {**inputs_basis, "input_aggregate_sha256": input_aggregate},
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
                "size": 20,
                "sha256": "f" * 64,
            },
        },
        "execution": {
            "command_id": "canonical-golden-verify-v1",
            "selectors": list(capture_test_gate.SELECTORS["canonical"]),
            "pytest_exit_code": 0,
            "input_junit_sha256": "0" * 64,
            "tests": 1,
            "skipped": 0,
            "failures_or_errors": 0,
        },
        "provenance": {
            "scope": "canonical-functional-not-release",
            "producer_sha256": capture_test_gate._sha256(
                artifacts["canonical-producer.py"]
            ),
            "observer_sha256": capture_test_gate._sha256(
                artifacts["canonical-observer.py"]
            ),
            "runner_sha256": capture_test_gate._sha256(
                artifacts["canonical-runner.sh"]
            ),
            "policy_sha256": policy_sha256,
            "source_sha256": source_sha256,
            "input_aggregate_sha256": input_aggregate,
        },
    }
    return sidecar, artifacts


def _write_valid_canonical_artifacts(
    artifact_root: Path,
    *,
    run_id: str,
    policy_sha256: str,
    source_sha256: str,
    uv_lock_sha256: str,
    mutation: tuple[str, str, object] | None = None,
) -> None:
    junit = (
        b'<testsuites><testcase classname="tests.golden.test_fake" name="test_ok"/>'
        b"</testsuites>\n"
    )
    sidecar, artifacts = _canonical_fixture(
        run_id,
        policy_sha256,
        source_sha256,
        uv_lock_sha256,
    )
    sidecar["execution"]["input_junit_sha256"] = capture_test_gate._sha256(junit)
    gate = {
        "schema_version": 1,
        "gate": "pytest-layer",
        "layer": "canonical",
        "required_markers": ["golden"],
        "tests": 1,
        "skipped": 0,
        "failures_or_errors": 0,
        "outside_layer": [],
        "passed": True,
        "failures": [],
        "run_id": run_id,
        "input_junit_sha256": capture_test_gate._sha256(junit),
        "policy_sha256": policy_sha256,
    }
    if mutation is not None:
        target_name, path, value = mutation
        if target_name == "sidecar":
            _change_path(sidecar, path, value)
        elif target_name == "gate":
            _change_path(gate, path, value)
        elif target_name == "artifact":
            artifacts[path] = value
        else:
            raise AssertionError(target_name)
    artifact_root.mkdir(parents=True, exist_ok=True)
    for name, content in artifacts.items():
        (artifact_root / name).write_bytes(content)
    (artifact_root / "canonical-runtime.json").write_text(
        json.dumps(sidecar, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifact_root / "canonical.xml").write_bytes(junit)
    (artifact_root / "canonical-gate.json").write_text(
        json.dumps(gate, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _capture_canonical_fixture(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    mutation: tuple[str, str, object] | None = None,
) -> capture_test_gate.CaptureResult:
    repo, retention = capture_repo

    def fake_gate_process(_command, *, cwd, environment, stdout, stderr):
        del stdout, stderr
        assert environment["AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256"]
        _write_valid_canonical_artifacts(
            Path(environment["AI_AUTO_LRC_GATE_ARTIFACT_DIR"]),
            run_id=environment["AI_AUTO_LRC_EVIDENCE_RUN_ID"],
            policy_sha256=environment["AI_AUTO_LRC_EVIDENCE_POLICY_SHA256"],
            source_sha256=environment["AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256"],
            uv_lock_sha256=capture_test_gate.sha256_file(cwd / "uv.lock"),
            mutation=mutation,
        )
        return 0, None

    monkeypatch.setattr(capture_test_gate, "_run_gate_process", fake_gate_process)
    return capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="canonical",
        base_ref="HEAD",
    )


def test_complete_package_sidecar_closes_linux_package_layer(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
):
    result = _capture_package_fixture(capture_repo, monkeypatch)

    assert result.exit_code == 0
    assert result.sealed is True
    document = _receipt(result)
    assert document["claim"] == {"layer": "package", "spec_ids": []}
    assert document["verification"] == {"passed": True, "reason_codes": []}
    assert document["qualification"] == {
        "level": "implemented-unqualified",
        "derived": True,
    }
    capture_test_gate.verify_receipt(
        result.run_directory / "receipt.json",
        mode="archived-integrity",
    )


def test_package_binding_accepts_real_quality_gate_shape(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
):
    result = _capture_package_fixture(capture_repo, monkeypatch)

    assert result.exit_code == 0
    assert result.run_directory is not None
    gate = json.loads(
        (result.run_directory / "artifacts/package/package-gate.json").read_text(
            encoding="utf-8"
        )
    )
    assert gate["required_markers"] == ["package"]
    assert gate["outside_layer"] == []
    assert gate["failures"] == []
    assert _receipt(result)["verification"] == {"passed": True, "reason_codes": []}


@pytest.mark.parametrize(
    "mutation",
    (
        ("sidecar", "cli", _DELETE),
        ("sidecar", "qualification", "qualified-release"),
        ("sidecar", "schema_version", "1"),
        ("sidecar", "layer", "portable"),
        ("sidecar", "run_id", "different-run"),
        ("sidecar", "scope.os", "darwin"),
        ("sidecar", "scope.arch", "arm64"),
        ("sidecar", "scope.python_version", "3.11"),
        ("sidecar", "scope.unknown", "claim"),
        ("sidecar", "image.image_id", _DELETE),
        ("sidecar", "image.repo_digest", _DELETE),
        ("sidecar", "image.repo_digest", "sha256:" + "2" * 64),
        ("sidecar", "image.image_id", "sha256:1234"),
        ("sidecar", "network.blocked", False),
        ("sidecar", "network.result_code", 0),
        ("sidecar", "network.probe", _DELETE),
        ("sidecar", "wheelhouse.manifest_sha256", "0" * 64),
        ("sidecar", "wheelhouse.runtime_wheel_count", 2),
        ("sidecar", "wheelhouse.build_wheel_count", 2),
        ("sidecar", "wheelhouse.artifact_count", 2),
        ("sidecar", "wheelhouse.aggregate_sha256", "0" * 64),
        ("manifest", "target.machine", "arm64"),
        ("manifest", "files.runtime", []),
        ("sidecar", "build.source", "wheel"),
        ("sidecar", "build.sdist.name", "other.tar.gz"),
        ("sidecar", "build.project_wheel.name", "project.tar.gz"),
        ("sidecar", "build.runtime_wheel_tags", ["py3-none-any", "py3-none-any"]),
        ("sidecar", "build.build_wheel_tags", ["cp311-cp311-macosx_11_0_arm64"]),
        ("sidecar", "build.project_wheel_tags", ["not-a-wheel-tag"]),
        ("sidecar", "installation.pip_check_exit_code", 1),
        ("sidecar", "installation.pth_after", []),
        (
            "sidecar",
            "installation.pth_before",
            [{"name": "/tmp/escape.pth", "size": 1, "sha256": "f" * 64}],
        ),
        ("sidecar", "installation.direct_imports", _PACKAGE_IMPORTS[:-1]),
        (
            "sidecar",
            "installation.direct_imports",
            [*_PACKAGE_IMPORTS, _PACKAGE_IMPORTS[-1]],
        ),
        ("sidecar", "installation.installed_package_origin_scope", "checkout"),
        ("sidecar", "installation.installed_package.name", "other/__init__.py"),
        ("sidecar", "cli.command_id", "raw-argv"),
        ("sidecar", "cli.exit_code", 1),
        ("sidecar", "cli.stdout_sha256", "7" * 64),
        ("sidecar", "cli.stderr_sha256", "short"),
    ),
    ids=(
        "top-level-missing",
        "top-level-unknown",
        "top-level-wrong-type",
        "cross-layer",
        "cross-run",
        "scope-os",
        "scope-arch",
        "incomplete-python-version",
        "unknown-scope-field",
        "image-id-missing",
        "repo-digest-missing",
        "repo-digest-missing-name",
        "short-image-digest",
        "network-not-blocked",
        "network-success-code",
        "network-probe-missing",
        "manifest-copy-hash",
        "runtime-count",
        "build-count",
        "artifact-count",
        "wheelhouse-aggregate",
        "manifest-target",
        "manifest-copy-content",
        "not-sdist-build",
        "sdist-binding",
        "project-wheel-suffix",
        "duplicate-tags",
        "incompatible-tags",
        "malformed-tag",
        "pip-check-failed",
        "pth-changed",
        "absolute-pth-path",
        "missing-import",
        "duplicate-import",
        "checkout-origin",
        "wrong-installed-package",
        "cli-command",
        "cli-exit",
        "cli-stdout-binding",
        "cli-hash-format",
    ),
)
def test_package_sidecar_semantic_mutations_are_diagnostic(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    mutation: tuple[str, str, object],
):
    result = _capture_package_fixture(capture_repo, monkeypatch, mutation)

    assert result.exit_code == capture_test_gate.CAPTURE_ERROR_EXIT
    assert result.sealed is True
    document = _receipt(result)
    assert document["qualification"]["level"] == "diagnostic"
    assert document["verification"]["reason_codes"] == [
        "RUN_ARTIFACT_BINDING_INVALID"
    ]


@pytest.mark.parametrize(
    "mutation",
    (
        ("gate", "run_id", "different-run"),
        ("gate", "policy_sha256", "0" * 64),
        ("gate", "input_junit_sha256", "0" * 64),
        ("gate", "passed", False),
        ("gate", "tests", 2),
        ("gate", "required_markers", []),
        ("gate", "required_markers", ["portable"]),
        ("gate", "outside_layer", ["tests.unit.test_wrong::test_bad"]),
        ("gate", "failures", ["package gate failed"]),
    ),
    ids=(
        "gate-run",
        "gate-policy",
        "gate-junit",
        "gate-passed",
        "gate-count",
        "required-markers-missing",
        "required-markers-wrong-layer",
        "outside-layer",
        "reported-failure",
    ),
)
def test_package_gate_must_bind_same_run_junit_and_policy(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    mutation: tuple[str, str, object],
):
    result = _capture_package_fixture(capture_repo, monkeypatch, mutation)

    assert result.exit_code == capture_test_gate.CAPTURE_ERROR_EXIT
    document = _receipt(result)
    assert "RUN_ARTIFACT_BINDING_INVALID" in document["verification"]["reason_codes"]


@pytest.mark.parametrize(
    ("junit", "expected_reason"),
    (
        (
            b'<testsuites><testcase classname="tests.unit.test_wrong" name="bad"/>'
            b"</testsuites>",
            "ARTIFACT_LAYER_MISMATCH",
        ),
        (
            b'<testsuites><testcase classname="tests.package.test_fake" name="skip">'
            b"<skipped/></testcase></testsuites>",
            "REQUIRED_TEST_SKIPPED",
        ),
        (
            b'<testsuites><testcase classname="tests.package.test_fake" name="fail">'
            b"<failure/></testcase></testsuites>",
            "JUNIT_FAILURE_OR_ERROR",
        ),
        (b"<testsuites/>", "JUNIT_INVALID_OR_EMPTY"),
    ),
    ids=("cross-layer", "skip", "failure", "empty"),
)
def test_package_junit_must_be_nonempty_green_and_package_scoped(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    junit: bytes,
    expected_reason: str,
):
    result = _capture_package_fixture(
        capture_repo,
        monkeypatch,
        ("junit", "content", junit),
    )

    assert result.exit_code == capture_test_gate.CAPTURE_ERROR_EXIT
    document = _receipt(result)
    assert expected_reason in document["verification"]["reason_codes"]


def test_complete_canonical_closure_is_implemented_unqualified(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
):
    result = _capture_canonical_fixture(capture_repo, monkeypatch)

    assert result.exit_code == 0
    assert result.sealed is True
    document = _receipt(result)
    assert document["claim"] == {"layer": "canonical", "spec_ids": []}
    assert document["verification"] == {"passed": True, "reason_codes": []}
    assert document["qualification"] == {
        "level": "implemented-unqualified",
        "derived": True,
    }
    capture_test_gate.verify_receipt(
        result.run_directory / "receipt.json",
        mode="archived-integrity",
    )


@pytest.mark.parametrize(
    "mutation",
    (
        ("sidecar", "qualification", "qualified-canonical"),
        ("sidecar", "run_id", "old-run"),
        ("sidecar", "scope.arch", "arm64"),
        ("sidecar", "scope.python_version", "3.11.9"),
        ("sidecar", "image.base.repo_digest", "python:3.10"),
        ("sidecar", "image.base.image_id", "sha256:short"),
        ("sidecar", "image.build.image_id", "sha256:short"),
        ("sidecar", "image.build.run_id", "old-run"),
        ("sidecar", "image.build.source_sha256", "0" * 64),
        ("sidecar", "inputs.oracle_aggregate_sha256", "0" * 64),
        ("sidecar", "inputs.input_aggregate_sha256", "0" * 64),
        ("sidecar", "runtime.network.blocked", False),
        ("sidecar", "runtime.network.result_code", 0),
        ("sidecar", "runtime.root_filesystem.blocked", False),
        ("sidecar", "runtime.root_filesystem.errno", 0),
        ("sidecar", "runtime.tmpfs.writable", False),
        ("sidecar", "runtime.cuda_available", True),
        ("sidecar", "runtime.torch_intraop_threads", 2),
        ("sidecar", "runtime.harness_import_scope", "site-packages"),
        ("sidecar", "installation.origin_scope", "workspace"),
        ("sidecar", "installation.installed_package.name", "workspace/t2l.py"),
        ("sidecar", "execution.command_id", "candidate"),
        ("sidecar", "execution.selectors", ["tests/golden"]),
        ("sidecar", "execution.pytest_exit_code", 1),
        ("sidecar", "provenance.scope", "clean-release"),
        ("sidecar", "provenance.policy_sha256", "0" * 64),
        ("sidecar", "provenance.source_sha256", "0" * 64),
        ("sidecar", "provenance.producer_sha256", "short"),
    ),
    ids=(
        "self-qualified",
        "cross-run",
        "scope-arch",
        "scope-python",
        "base-tag-only",
        "base-image-short",
        "build-image-short",
        "build-run",
        "build-source",
        "oracle-aggregate",
        "input-aggregate",
        "network-not-blocked",
        "network-result-zero",
        "rootfs-not-blocked",
        "rootfs-wrong-errno",
        "tmpfs-not-writable",
        "cuda-enabled",
        "threads",
        "harness-origin",
        "installed-origin",
        "installed-path",
        "execution-command",
        "execution-selectors",
        "execution-exit",
        "release-provenance",
        "policy-binding",
        "source-binding",
        "producer-hash-format",
    ),
)
def test_canonical_sidecar_semantic_mutations_are_diagnostic(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    mutation: tuple[str, str, object],
):
    result = _capture_canonical_fixture(capture_repo, monkeypatch, mutation)

    assert result.exit_code == capture_test_gate.CAPTURE_ERROR_EXIT
    document = _receipt(result)
    assert document["qualification"]["level"] == "diagnostic"
    assert document["verification"]["reason_codes"] == [
        "RUN_ARTIFACT_BINDING_INVALID"
    ]


@pytest.mark.parametrize(
    "mutation",
    (
        ("artifact", "canonical-feature-oracle.json", b"{}\n"),
        ("artifact", "canonical-numeric-oracle.json", b"{}\n"),
        ("artifact", "canonical-public-e2e-oracle.json", b"{}\n"),
        ("artifact", "canonical-Dockerfile", b"FROM python:3.10\n"),
        ("artifact", "canonical-profile-manifest.json", b"{}\n"),
        ("artifact", "canonical-fixture-metadata.json", b"{}\n"),
        ("artifact", "canonical-producer.py", b"# changed producer\n"),
        ("artifact", "canonical-observer.py", b"# changed observer\n"),
        ("artifact", "canonical-runner.sh", b"# changed runner\n"),
    ),
    ids=(
        "feature-oracle",
        "numeric-oracle",
        "public-e2e-oracle",
        "dockerfile",
        "profile",
        "fixture",
        "producer",
        "observer",
        "runner",
    ),
)
def test_canonical_formal_input_tampering_is_diagnostic(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    mutation: tuple[str, str, object],
):
    result = _capture_canonical_fixture(capture_repo, monkeypatch, mutation)

    assert result.exit_code == capture_test_gate.CAPTURE_ERROR_EXIT
    document = _receipt(result)
    assert document["verification"]["reason_codes"] == [
        "RUN_ARTIFACT_BINDING_INVALID"
    ]


@pytest.mark.parametrize(
    "mutation",
    (
        ("gate", "run_id", "old-run"),
        ("gate", "policy_sha256", "0" * 64),
        ("gate", "input_junit_sha256", "0" * 64),
        ("gate", "required_markers", []),
        ("gate", "outside_layer", ["tests.package.test_wrong::test_bad"]),
        ("gate", "failures", ["failed"]),
        ("gate", "tests", 2),
    ),
    ids=("run", "policy", "junit", "markers", "outside", "failures", "count"),
)
def test_canonical_gate_must_bind_junit_policy_and_run(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    mutation: tuple[str, str, object],
):
    result = _capture_canonical_fixture(capture_repo, monkeypatch, mutation)

    assert result.exit_code == capture_test_gate.CAPTURE_ERROR_EXIT
    document = _receipt(result)
    assert document["verification"]["reason_codes"] == [
        "RUN_ARTIFACT_BINDING_INVALID"
    ]


@pytest.mark.parametrize("layer", ("portable", "package", "canonical"))
def test_capture_launches_gate_in_an_exclusive_run_directory(
    capture_repo: tuple[Path, Path],
    layer: str,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, retention = capture_repo
    stale = retention / "stale"
    stale.mkdir()
    (stale / "portable.xml").write_text("old", encoding="utf-8")
    monkeypatch.setenv("AI_AUTO_LRC_GATE_ARTIFACT_DIR", os.fspath(stale))

    first = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer=layer,
        base_ref="HEAD",
    )
    second = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer=layer,
        base_ref="HEAD",
    )

    expected_exit = 0 if layer == "portable" else capture_test_gate.CAPTURE_ERROR_EXIT
    assert first.exit_code == second.exit_code == expected_exit
    assert first.run_directory != second.run_directory
    assert first.run_directory is not None
    assert not first.run_directory.name.startswith(".incomplete-")
    assert (stale / "portable.xml").read_text(encoding="utf-8") == "old"
    document = _receipt(first)
    assert document["claim"] == {"layer": layer, "spec_ids": []}
    expected_qualification = "implemented-unqualified" if layer == "portable" else "diagnostic"
    assert document["qualification"] == {
        "level": expected_qualification,
        "derived": True,
    }
    assert document["run"]["gate_started"] is True
    assert document["run"]["raw_returncode"] == 0
    assert document["source"]["stable_during_run"] is True
    expected_reasons = {
        "portable": [],
        "package": ["RUN_ARTIFACT_BINDING_INVALID"],
        "canonical": ["REQUIRED_ARTIFACT_MISSING"],
    }[layer]
    assert document["verification"] == {
        "passed": not expected_reasons,
        "reason_codes": expected_reasons,
    }


@pytest.mark.parametrize("gate_rc", (1, 5, 70, 130))
def test_gate_failure_is_sealed_diagnostic_and_preserves_gate_exit_code(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    gate_rc: int,
):
    repo, retention = capture_repo
    monkeypatch.setenv("FAKE_GATE_RC", str(gate_rc))

    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )

    assert result.exit_code == gate_rc
    document = _receipt(result)
    assert document["run"]["raw_returncode"] == gate_rc
    assert document["run"]["normalized_exit_code"] == gate_rc
    assert document["qualification"]["level"] == "diagnostic"
    assert "GATE_EXIT_NONZERO" in document["verification"]["reason_codes"]


def test_source_change_after_gate_forces_capture_error(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
):
    repo, retention = capture_repo
    monkeypatch.setenv("FAKE_MUTATE_PATH", os.fspath(repo / "tracked.txt"))

    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )

    assert result.exit_code == capture_test_gate.CAPTURE_ERROR_EXIT
    document = _receipt(result)
    assert document["source"]["stable_during_run"] is False
    assert document["qualification"]["level"] == "diagnostic"
    assert "SOURCE_CHANGED_DURING_RUN" in document["verification"]["reason_codes"]


def test_missing_layer_artifact_after_green_gate_is_diagnostic(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo
    runner = repo / "scripts/run_test_gate.sh"
    runner.write_text(
        "#!/bin/sh\nmkdir -p \"$AI_AUTO_LRC_GATE_ARTIFACT_DIR\"\nexit 0\n",
        encoding="utf-8",
    )
    runner.chmod(0o755)

    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="package",
        base_ref="HEAD",
    )

    assert result.exit_code == capture_test_gate.CAPTURE_ERROR_EXIT
    document = _receipt(result)
    assert document["qualification"]["level"] == "diagnostic"
    assert document["missing_artifacts"] == [
        "package-gate.json",
        "package-platform.json",
        "package.xml",
        "wheelhouse-manifest.json",
    ]
    assert "REQUIRED_ARTIFACT_MISSING" in document["verification"]["reason_codes"]


def test_missing_package_sidecars_preserve_nonzero_gate_exit(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo
    runner = repo / "scripts/run_test_gate.sh"
    runner.write_text(
        "#!/bin/sh\nmkdir -p \"$AI_AUTO_LRC_GATE_ARTIFACT_DIR\"\nexit 5\n",
        encoding="utf-8",
    )
    runner.chmod(0o755)

    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="package",
        base_ref="HEAD",
    )

    assert result.exit_code == 5
    document = _receipt(result)
    assert document["run"]["raw_returncode"] == 5
    assert document["missing_artifacts"] == list(
        capture_test_gate.ARTIFACT_CLOSURES["package"]
    )
    assert not list((result.run_directory / "artifacts/package").iterdir())
    assert {
        "GATE_EXIT_NONZERO",
        "REQUIRED_ARTIFACT_MISSING",
    } <= set(document["verification"]["reason_codes"])


def test_verify_rejects_forged_package_closure_reason_after_complete_binding(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
):
    result = _capture_package_fixture(capture_repo, monkeypatch)
    assert result.run_directory is not None
    root = result.run_directory
    receipt_path = root / "receipt.json"
    marker_path = root / "SEALED"
    document = json.loads(receipt_path.read_text(encoding="utf-8"))
    document["verification"] = {
        "passed": False,
        "reason_codes": ["LAYER_CLOSURE_UNIMPLEMENTED"],
    }
    document["qualification"]["level"] = "diagnostic"
    document["run"]["capture_exit_code"] = capture_test_gate.CAPTURE_ERROR_EXIT
    receipt_bytes = capture_test_gate._json_bytes(document)
    root.chmod(0o700)
    receipt_path.chmod(0o600)
    marker_path.chmod(0o600)
    receipt_path.write_bytes(receipt_bytes)
    marker_path.write_bytes(
        capture_test_gate._json_bytes(
            {
                "run_id": document["run_id"],
                "receipt_sha256": capture_test_gate._sha256(receipt_bytes),
            }
        )
    )
    receipt_path.chmod(0o400)
    marker_path.chmod(0o400)
    root.chmod(0o500)

    with pytest.raises(capture_test_gate.CaptureError, match="closure is implemented"):
        capture_test_gate.verify_receipt(receipt_path, mode="archived-integrity")


def test_verify_rejects_forged_canonical_closure_reason_after_complete_binding(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
):
    result = _capture_canonical_fixture(capture_repo, monkeypatch)
    assert result.run_directory is not None
    root = result.run_directory
    receipt_path = root / "receipt.json"
    marker_path = root / "SEALED"
    document = json.loads(receipt_path.read_text(encoding="utf-8"))
    document["verification"] = {
        "passed": False,
        "reason_codes": ["LAYER_CLOSURE_UNIMPLEMENTED"],
    }
    document["qualification"]["level"] = "diagnostic"
    document["run"]["capture_exit_code"] = capture_test_gate.CAPTURE_ERROR_EXIT
    receipt_bytes = capture_test_gate._json_bytes(document)
    root.chmod(0o700)
    receipt_path.chmod(0o600)
    marker_path.chmod(0o600)
    receipt_path.write_bytes(receipt_bytes)
    marker_path.write_bytes(
        capture_test_gate._json_bytes(
            {
                "run_id": document["run_id"],
                "receipt_sha256": capture_test_gate._sha256(receipt_bytes),
            }
        )
    )
    receipt_path.chmod(0o400)
    marker_path.chmod(0o400)
    root.chmod(0o500)

    with pytest.raises(capture_test_gate.CaptureError, match="closure is implemented"):
        capture_test_gate.verify_receipt(receipt_path, mode="archived-integrity")


def test_binary_logs_are_retained_without_entering_receipt_text(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo

    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )

    assert result.run_directory is not None
    assert (result.run_directory / "logs/stdout.bin").read_bytes() == b"stdout\xffbytes\n"
    assert (result.run_directory / "logs/stderr.bin").read_bytes() == b"stderr\xfebytes\n"
    receipt_bytes = (result.run_directory / "receipt.json").read_bytes()
    assert b"receipt.json" not in receipt_bytes
    document = _receipt(result)
    marker = json.loads((result.run_directory / "SEALED").read_text(encoding="utf-8"))
    assert marker["run_id"] == document["run_id"]
    assert marker["receipt_sha256"] == capture_test_gate.sha256_file(
        result.run_directory / "receipt.json"
    )
    assert set(document["logs"]) == {"stdout", "stderr"}


def test_retention_root_inside_repo_is_rejected_before_gate_starts(
    capture_repo: tuple[Path, Path],
):
    repo, _retention = capture_repo
    invalid = repo / "evidence"
    invalid.mkdir()

    with pytest.raises(capture_test_gate.CaptureError, match="outside repository"):
        capture_test_gate.capture_gate(
            repo_root=repo,
            retention_root=invalid,
            layer="portable",
            base_ref="HEAD",
        )

    assert list(invalid.iterdir()) == []


def test_verify_rejects_self_asserted_high_qualification(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    receipt = result.run_directory / "receipt.json"
    document = json.loads(receipt.read_text(encoding="utf-8"))
    document["qualification"]["level"] = "qualified-release"
    receipt.chmod(0o600)
    receipt.write_text(json.dumps(document), encoding="utf-8")
    receipt.chmod(0o400)

    with pytest.raises(capture_test_gate.CaptureError, match="schema_version 1"):
        capture_test_gate.verify_receipt(receipt, mode="archived-integrity")


def test_verify_requires_valid_sealed_completion_marker(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    marker = result.run_directory / "SEALED"
    marker.chmod(0o600)
    marker.write_text("{}\n", encoding="utf-8")

    with pytest.raises(capture_test_gate.CaptureError, match="SEALED"):
        capture_test_gate.verify_receipt(
            result.run_directory / "receipt.json",
            mode="archived-integrity",
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "staged",
        "unstaged",
        "deleted",
        "renamed",
        "mode",
        "untracked-binary",
        "untracked-symlink",
    ),
)
def test_source_identity_binds_git_and_untracked_states(
    capture_repo: tuple[Path, Path],
    mutation: str,
):
    repo, _retention = capture_repo
    baseline, _patch, _status, _snapshots = capture_test_gate._source_material(repo)

    if mutation == "staged":
        (repo / "tracked.txt").write_text("staged\n", encoding="utf-8")
        _git(repo, "add", "tracked.txt")
    elif mutation == "unstaged":
        (repo / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
    elif mutation == "deleted":
        (repo / "tracked.txt").unlink()
    elif mutation == "renamed":
        _git(repo, "mv", "tracked.txt", "renamed.txt")
    elif mutation == "mode":
        (repo / "tracked.txt").chmod(0o755)
    elif mutation == "untracked-binary":
        (repo / "binary.dat").write_bytes(b"\x00\xff\x10")
    else:
        (repo / "link").symlink_to("tracked.txt")

    changed, _patch, _status, _snapshots = capture_test_gate._source_material(repo)

    assert changed["aggregate_sha256"] != baseline["aggregate_sha256"]


def test_special_untracked_file_is_nonblocking_and_forces_diagnostic(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo
    os.mkfifo(repo / "untracked.fifo")

    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )

    assert result.exit_code == capture_test_gate.CAPTURE_ERROR_EXIT
    document = _receipt(result)
    assert document["qualification"]["level"] == "diagnostic"
    assert "SOURCE_SNAPSHOT_UNSAFE" in document["verification"]["reason_codes"]


def test_concurrent_captures_use_disjoint_sealed_directories(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo

    def run_capture() -> capture_test_gate.CaptureResult:
        return capture_test_gate.capture_gate(
            repo_root=repo,
            retention_root=retention,
            layer="portable",
            base_ref="HEAD",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: run_capture(), range(2)))

    assert [result.exit_code for result in results] == [0, 0]
    assert results[0].run_directory != results[1].run_directory
    assert all(result.sealed for result in results)


def test_extra_layer_artifact_prevents_qualification(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo
    runner = repo / "scripts/run_test_gate.sh"
    runner_text = runner.read_text(encoding="utf-8")
    runner.write_text(
        runner_text.replace(
            'exit "${FAKE_GATE_RC:-0}"',
            'printf unexpected > "$AI_AUTO_LRC_GATE_ARTIFACT_DIR/extra.txt"\n'
            'exit "${FAKE_GATE_RC:-0}"',
        ),
        encoding="utf-8",
    )

    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )

    assert result.exit_code == capture_test_gate.CAPTURE_ERROR_EXIT
    document = _receipt(result)
    assert "ARTIFACT_LAYER_MISMATCH" in document["verification"]["reason_codes"]
    assert document["qualification"]["level"] == "diagnostic"


@pytest.mark.parametrize("gate_rc, expected", ((0, 70), (5, 5)))
def test_finalizer_failure_never_masks_gate_result(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    gate_rc: int,
    expected: int,
):
    repo, retention = capture_repo
    monkeypatch.setenv("FAKE_GATE_RC", str(gate_rc))

    def fail_seal(_staging: Path, _sealed: Path) -> None:
        raise OSError("injected seal failure")

    monkeypatch.setattr(capture_test_gate, "_seal_run", fail_seal)
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )

    assert result.exit_code == expected
    assert result.sealed is False
    assert result.run_directory is not None
    assert result.run_directory.name.startswith(".incomplete-")
    assert (result.run_directory / "capture-failure.json").is_file()


def test_archived_integrity_rejects_tampered_untracked_snapshot(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo
    (repo / "untracked.bin").write_bytes(b"original")
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    archived = result.run_directory / "source/before/untracked/untracked.bin"
    archived.chmod(0o600)
    archived.write_bytes(b"tampered")
    archived.chmod(0o400)

    with pytest.raises(capture_test_gate.CaptureError, match="snapshot mismatch"):
        capture_test_gate.verify_receipt(
            result.run_directory / "receipt.json",
            mode="archived-integrity",
        )


def test_verify_receipt_at_stays_on_open_run_after_parent_swap(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    run_directory = result.run_directory
    displaced = retention / f"{run_directory.name}.displaced"
    run_fd = os.open(run_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        run_directory.rename(displaced)
        run_directory.mkdir()
        os.mkfifo(run_directory / "receipt.json")
        run_directory.chmod(0o500)

        document = capture_test_gate.verify_receipt_at(
            run_fd,
            "receipt.json",
            "archived-integrity",
        )

        assert document["run_id"] == run_directory.name
    finally:
        os.close(run_fd)
        if run_directory.exists():
            run_directory.chmod(0o700)
            (run_directory / "receipt.json").unlink()
            run_directory.rmdir()
        if displaced.exists():
            displaced.rename(run_directory)


@pytest.mark.parametrize("replacement", ("symlink", "fifo"))
def test_verify_receipt_at_rejects_nonregular_sealed_file_without_blocking(
    capture_repo: tuple[Path, Path],
    replacement: str,
):
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    marker = result.run_directory / "SEALED"
    result.run_directory.chmod(0o700)
    marker.chmod(0o600)
    marker.unlink()
    if replacement == "symlink":
        marker.symlink_to("receipt.json")
    else:
        os.mkfifo(marker)
    result.run_directory.chmod(0o500)
    run_fd = os.open(result.run_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        script = (
            "from scripts import capture_test_gate as gate\n"
            f"fd = {run_fd}\n"
            "try:\n"
            "    gate.verify_receipt_at(fd, 'receipt.json', 'archived-integrity')\n"
            "except gate.CaptureError:\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(2)\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(capture_test_gate.__file__).resolve().parents[1],
            check=False,
            pass_fds=(run_fd,),
            timeout=2,
        )
    finally:
        os.close(run_fd)

    assert completed.returncode == 0


def test_current_source_verification_uses_open_repository_anchor(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    displaced = repo.with_name("repo.displaced")
    run_fd = os.open(result.run_directory, os.O_RDONLY | os.O_DIRECTORY)
    repo_fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY)
    try:
        repo.rename(displaced)
        repo.mkdir()

        document = capture_test_gate.verify_receipt_at(
            run_fd,
            "receipt.json",
            "current-source",
            repo_fd,
        )

        assert document["qualification"]["level"] == "implemented-unqualified"
    finally:
        os.close(repo_fd)
        os.close(run_fd)
        if repo.exists():
            repo.rmdir()
        if displaced.exists():
            displaced.rename(repo)


def test_current_source_verification_rejects_later_checkout_drift(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    (repo / "tracked.txt").write_text("later drift\n", encoding="utf-8")

    with pytest.raises(capture_test_gate.CaptureError, match="current source"):
        capture_test_gate.verify_receipt(
            result.run_directory / "receipt.json",
            mode="current-source",
            repo_root=repo,
        )


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        (
            "archived-integrity",
            {
                "valid": True,
                "mode": "archived-integrity",
                "effective_qualification": "diagnostic-historical-integrity",
            },
        ),
        (
            "current-source",
            {
                "valid": True,
                "mode": "current-source",
                "effective_qualification": "diagnostic-current-source-observation",
                "transactional": False,
                "aba_excluded": False,
                "observation_model": "sequential-double-observation",
            },
        ),
    ),
    ids=("archived-integrity", "current-source"),
)
def test_s15_verify_cli_reports_effective_observation_semantics(
    capture_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    mode: str,
    expected: dict[str, object],
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    assert _receipt(result)["qualification"] == {
        "level": "implemented-unqualified",
        "derived": True,
    }
    arguments = [
        "verify",
        "--receipt",
        os.fspath(result.run_directory / "receipt.json"),
        "--mode",
        mode,
    ]
    if mode == "current-source":
        arguments.extend(("--repo-root", os.fspath(repo)))

    assert capture_test_gate.main(arguments) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == expected


@pytest.mark.parametrize(
    "value",
    (_DELETE, "transactional-snapshot"),
    ids=("missing", "tampered"),
)
def test_s15_verify_receipt_at_rejects_invalid_source_observation_limit(
    capture_repo: tuple[Path, Path],
    value: object,
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    document = _receipt(result)
    assert document["source"]["observation_limit"] == (
        "before-and-after identity; transient restored changes may be unobserved"
    )
    _change_path(document, "source.observation_limit", value)
    _rewrite_sealed_receipt(result.run_directory, document)
    run_fd = os.open(result.run_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(
            capture_test_gate.CaptureError,
            match=r"source\.observation_limit",
        ):
            capture_test_gate.verify_receipt_at(
                run_fd,
                "receipt.json",
                "archived-integrity",
            )
    finally:
        os.close(run_fd)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("transactional", True),
        ("aba_excluded", True),
        ("qualification", "release"),
    ),
)
def test_s17_verify_receipt_at_rejects_unknown_source_claims(
    capture_repo: tuple[Path, Path],
    field: str,
    value: object,
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    document = _receipt(result)
    document["source"][field] = value
    _rewrite_sealed_receipt(result.run_directory, document)
    run_fd = os.open(result.run_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(
            capture_test_gate.CaptureError,
            match=r"source has an invalid shape",
        ):
            capture_test_gate.verify_receipt_at(
                run_fd,
                "receipt.json",
                "archived-integrity",
            )
    finally:
        os.close(run_fd)


def test_s15_current_source_rejects_different_sequential_observations(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    run_fd = os.open(result.run_directory, os.O_RDONLY | os.O_DIRECTORY)
    repo_fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY)
    try:
        first = capture_test_gate._source_material_at(repo_fd)
        drift = repo / "s15-observation-drift.txt"
        drift.write_text("transient\n", encoding="utf-8")
        second = capture_test_gate._source_material_at(repo_fd)
        drift.unlink()
        assert first["aggregate_sha256"] != second["aggregate_sha256"]
        observations = [first, second]
        calls: list[int] = []

        def observe(descriptor: int) -> dict[str, object]:
            calls.append(descriptor)
            return copy.deepcopy(observations[len(calls) - 1])

        monkeypatch.setattr(capture_test_gate, "_source_material_at", observe)
        with pytest.raises(capture_test_gate.CaptureError) as raised:
            capture_test_gate.verify_receipt_at(
                run_fd,
                "receipt.json",
                "current-source",
                repo_fd,
            )
        assert str(raised.value) == "CURRENT_SOURCE_OBSERVATION_UNSTABLE"
        assert calls == [repo_fd, repo_fd]
    finally:
        os.close(repo_fd)
        os.close(run_fd)


def test_s15_current_source_accepts_equal_sequential_observations(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    run_fd = os.open(result.run_directory, os.O_RDONLY | os.O_DIRECTORY)
    repo_fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY)
    try:
        observation = capture_test_gate._source_material_at(repo_fd)
        calls: list[int] = []

        def observe(descriptor: int) -> dict[str, object]:
            calls.append(descriptor)
            return copy.deepcopy(observation)

        monkeypatch.setattr(capture_test_gate, "_source_material_at", observe)
        document = capture_test_gate.verify_receipt_at(
            run_fd,
            "receipt.json",
            "current-source",
            repo_fd,
        )
        assert document["run_id"] == result.run_directory.name
        assert calls == [repo_fd, repo_fd]
    finally:
        os.close(repo_fd)
        os.close(run_fd)


def test_s15_verify_receipt_at_public_signature_is_stable() -> None:
    signature = inspect.signature(capture_test_gate.verify_receipt_at)
    assert str(signature) == (
        "(run_fd: 'int', receipt_name: 'str', mode: 'str', "
        "repo_root_fd: 'int | None' = None) -> 'dict[str, Any]'"
    )


def test_sigterm_is_forwarded_and_sealed_as_diagnostic(
    capture_repo: tuple[Path, Path],
):
    repo, retention = capture_repo
    runner = repo / "scripts/run_test_gate.sh"
    runner.write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
    runner.chmod(0o755)
    script = Path(capture_test_gate.__file__).resolve()
    process = subprocess.Popen(
        [
            sys.executable,
            os.fspath(script),
            "run",
            "--layer",
            "portable",
            "--base-ref",
            "HEAD",
            "--retention-root",
            os.fspath(retention),
            "--repo-root",
            os.fspath(repo),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        incomplete = list(retention.glob(".incomplete-*"))
        if incomplete and (incomplete[0] / "logs/stdout.bin").exists():
            time.sleep(0.1)
            break
        time.sleep(0.02)
    else:
        process.kill()
        raise AssertionError("capture did not start its gate")

    process.send_signal(signal.SIGTERM)
    stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 128 + signal.SIGTERM, stderr
    run_directory = Path(stdout.strip())
    document = json.loads((run_directory / "receipt.json").read_text(encoding="utf-8"))
    assert document["run"]["raw_returncode"] == -signal.SIGTERM
    assert document["run"]["signal"] == signal.SIGTERM
    assert "GATE_TERMINATED_BY_SIGNAL" in document["verification"]["reason_codes"]
    assert document["qualification"]["level"] == "diagnostic"


def _private_closure(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o500 if path.is_dir() else 0o400)
    root.chmod(0o500)


def _changed_stat(value: os.stat_result, *, index: int, replacement: int) -> os.stat_result:
    fields = list(value)
    fields[index] = replacement
    return os.stat_result(fields)


def test_s18_formal_receipt_hardlink_is_rejected(
    capture_repo: tuple[Path, Path],
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    receipt = result.run_directory / "receipt.json"
    alias = result.run_directory / "receipt.alias"
    result.run_directory.chmod(0o700)
    os.link(receipt, alias)
    result.run_directory.chmod(0o500)

    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"receipt must have link count 1",
    ):
        capture_test_gate.verify_receipt(receipt, mode="archived-integrity")

    assert receipt.stat().st_nlink == 2
    assert alias.samefile(receipt)


def test_s18_formal_receipt_overwide_mode_is_rejected(
    capture_repo: tuple[Path, Path],
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    receipt = result.run_directory / "receipt.json"
    receipt.chmod(0o440)

    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"receipt must use mode 0400",
    ):
        capture_test_gate.verify_receipt(receipt, mode="archived-integrity")

    assert receipt.stat().st_mode & 0o777 == 0o440


def test_s18_formal_receipt_wrong_owner_stat_is_rejected(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    receipt = result.run_directory / "receipt.json"
    receipt_inode = receipt.stat().st_ino
    real_fstat = os.fstat

    def wrong_owner(descriptor: int) -> os.stat_result:
        observed = real_fstat(descriptor)
        if observed.st_ino == receipt_inode and stat.S_ISREG(observed.st_mode):
            return _changed_stat(
                observed,
                index=4,
                replacement=os.geteuid() + 1,
            )
        return observed

    monkeypatch.setattr(capture_test_gate.os, "fstat", wrong_owner)
    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"receipt owner is invalid",
    ):
        capture_test_gate.verify_receipt(receipt, mode="archived-integrity")


def test_s18_formal_run_root_requires_exact_private_mode(
    capture_repo: tuple[Path, Path],
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    result.run_directory.chmod(0o550)

    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"sealed run root must use mode 0500",
    ):
        capture_test_gate.verify_receipt(
            result.run_directory / "receipt.json",
            mode="archived-integrity",
        )


def test_s18_formal_child_directory_requires_exact_private_mode(
    capture_repo: tuple[Path, Path],
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    source = result.run_directory / "source"
    source.chmod(0o550)

    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"sealed run directory must use mode 0500: source",
    ):
        capture_test_gate.verify_receipt(
            result.run_directory / "receipt.json",
            mode="archived-integrity",
        )


@pytest.mark.parametrize(
    ("limit", "succeeds"),
    ((6, True), (5, False)),
    ids=("exact-byte-limit", "byte-limit-plus-one"),
)
def test_s18_receipt_reader_enforces_cumulative_byte_limit_before_extra_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
    succeeds: bool,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir()
    (root / "first.bin").write_bytes(b"abc")
    (root / "second.bin").write_bytes(b"def")
    _private_closure(root)
    before = {
        path.name: (path.stat().st_size, path.stat().st_mode, path.stat().st_mtime_ns)
        for path in root.iterdir()
    }
    monkeypatch.setattr(
        capture_test_gate,
        "MAX_RECEIPT_CLOSURE_BYTES",
        limit,
        raising=False,
    )
    real_read = os.read
    bytes_observed = 0

    def bounded_read(descriptor: int, count: int) -> bytes:
        nonlocal bytes_observed
        content = real_read(descriptor, count)
        bytes_observed += len(content)
        return content

    monkeypatch.setattr(capture_test_gate.os, "read", bounded_read)
    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io:
            assert receipt_io.read("first.bin", "first") == b"abc"
            if succeeds:
                assert receipt_io.read("second.bin", "second") == b"def"
            else:
                with pytest.raises(
                    capture_test_gate.CaptureError,
                    match=r"sealed run closure byte limit exceeded",
                ):
                    receipt_io.read("second.bin", "second")
    finally:
        os.close(run_fd)

    assert bytes_observed <= limit + (0 if succeeds else 1)
    assert before == {
        path.name: (path.stat().st_size, path.stat().st_mode, path.stat().st_mtime_ns)
        for path in root.iterdir()
    }


@pytest.mark.parametrize(
    ("limit", "succeeds"),
    ((2, True), (1, False)),
    ids=("exact-entry-limit", "entry-limit-plus-one"),
)
def test_s18_file_closure_enforces_entry_limit_incrementally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
    succeeds: bool,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir()
    (root / "a").write_bytes(b"")
    (root / "b").write_bytes(b"")
    _private_closure(root)
    monkeypatch.setattr(
        capture_test_gate,
        "MAX_RECEIPT_CLOSURE_ENTRIES",
        limit,
        raising=False,
    )
    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io:
            if succeeds:
                assert receipt_io.file_closure() == {"a", "b"}
            else:
                with pytest.raises(
                    capture_test_gate.CaptureError,
                    match=r"sealed run closure entry limit exceeded",
                ):
                    receipt_io.file_closure()
    finally:
        os.close(run_fd)


@pytest.mark.parametrize("delta", (0, -1), ids=("exact-metadata-limit", "cap-plus-one"))
def test_s18_file_closure_enforces_metadata_limit_incrementally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    delta: int,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir()
    (root / "a").write_bytes(b"")
    _private_closure(root)
    metadata_cost = capture_test_gate.CLOSURE_ENTRY_METADATA_OVERHEAD + len(b"a")
    monkeypatch.setattr(
        capture_test_gate,
        "MAX_RECEIPT_CLOSURE_METADATA_BYTES",
        metadata_cost + delta,
        raising=False,
    )
    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io:
            if delta == 0:
                assert receipt_io.file_closure() == {"a"}
            else:
                with pytest.raises(
                    capture_test_gate.CaptureError,
                    match=r"sealed run closure metadata limit exceeded",
                ):
                    receipt_io.file_closure()
    finally:
        os.close(run_fd)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        (("logs", []), "logs must contain stdout and stderr"),
        (("inputs", []), "inputs has an invalid shape"),
        (("inputs.runner", None), "inputs.runner is required"),
        (("claim", []), "claim has an invalid shape"),
        (("claim.spec_ids", [1]), "claim.spec_ids must be a string array"),
        (("claim.layer", "unknown"), "claim.layer is invalid"),
        (("artifacts", []), "artifacts must be an object"),
        (
            ("artifacts.unknown", {"path": "SEALED", "size": 0, "sha256": "0" * 64}),
            "artifacts contain a cross-layer or unknown file",
        ),
        (("missing_artifacts", ["unknown"]), "missing_artifacts does not match"),
        (("verification", []), "verification has an invalid shape"),
        (
            ("verification.reason_codes", ["FORGED"]),
            "verification reason codes are inconsistent",
        ),
        (("run", []), "run must be an object"),
        (("run.command_id", "wrong"), "run command identity is invalid"),
        (("run.gate_started", "yes"), "run.gate_started must be boolean"),
        (("run.raw_returncode", True), "run.raw_returncode must be an integer or null"),
        (("run.normalized_exit_code", 9), "run.normalized_exit_code is inconsistent"),
        (("run.signal", 0), "run.signal must be a positive integer or null"),
        (("run.capture_exit_code", 9), "run.capture_exit_code is inconsistent"),
        (("run.exception", "/private/tmp/secret"), "run.exception must not contain"),
        (("qualification.level", "diagnostic"), "qualification does not match"),
    ),
    ids=(
        "logs-shape",
        "inputs-shape",
        "runner-required",
        "claim-shape",
        "spec-ids",
        "layer",
        "artifacts-shape",
        "cross-layer-artifact",
        "missing-closure",
        "verification-shape",
        "reason-code-consistency",
        "run-shape",
        "command-identity",
        "gate-started",
        "raw-returncode",
        "normalized-returncode",
        "signal",
        "capture-exit",
        "exception-redaction",
        "qualification-derived",
    ),
)
def test_s18_receipt_schema_mutations_fail_closed(
    capture_repo: tuple[Path, Path],
    mutation: tuple[str, object],
    expected: str,
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    document = _receipt(result)
    path, value = mutation
    if path == "artifacts.unknown":
        document["artifacts"]["unknown"] = value
    else:
        _change_path(document, path, value)
    _rewrite_sealed_receipt(result.run_directory, document)

    with pytest.raises(capture_test_gate.CaptureError, match=expected):
        capture_test_gate.verify_receipt(
            result.run_directory / "receipt.json",
            mode="archived-integrity",
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (None, "must be a canonical relative path"),
        ("", "must be a canonical relative path"),
        ("/absolute", "must be a canonical relative path"),
        (r"windows\\path", "must be a canonical relative path"),
        ("parent/../escape", "must be a canonical relative path"),
        ("not-canonical//path", "must be a canonical relative path"),
    ),
)
def test_s18_canonical_relative_paths_fail_closed(value: object, expected: str) -> None:
    with pytest.raises(capture_test_gate.CaptureError, match=expected):
        capture_test_gate._canonical_relative(value, "candidate")


def test_s18_verify_cli_failure_uses_stderr_only_and_stable_exit(
    tmp_path: Path,
) -> None:
    missing_receipt = tmp_path / "missing" / "receipt.json"
    completed = subprocess.run(
        [
            sys.executable,
            os.fspath(Path(capture_test_gate.__file__).resolve()),
            "verify",
            "--receipt",
            os.fspath(missing_receipt),
            "--mode",
            "archived-integrity",
        ],
        cwd=Path(capture_test_gate.__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr.startswith("evidence receipt verification failed: ")
    assert "Traceback" not in completed.stderr


def test_s18_receipt_io_rejects_closed_and_nondirectory_fds(tmp_path: Path) -> None:
    closed_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    os.close(closed_fd)
    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"run_fd is not a valid open directory",
    ):
        capture_test_gate._DirFdReceiptIO(closed_fd)

    leaf = tmp_path / "leaf"
    leaf.write_bytes(b"")
    leaf.chmod(0o400)
    leaf_fd = os.open(leaf, os.O_RDONLY)
    try:
        with pytest.raises(
            capture_test_gate.CaptureError,
            match=r"run_fd must refer to a directory",
        ):
            capture_test_gate._DirFdReceiptIO(leaf_fd)
    finally:
        os.close(leaf_fd)


@pytest.mark.parametrize("missing_flag", ("O_NOFOLLOW", "O_DIRECTORY"))
def test_s18_receipt_io_requires_safe_directory_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_flag: str,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir(mode=0o500)
    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.delattr(capture_test_gate.os, missing_flag)
    try:
        with pytest.raises(
            capture_test_gate.CaptureError,
            match=r"directory-relative safe verification is unsupported",
        ):
            capture_test_gate._DirFdReceiptIO(run_fd)
    finally:
        os.close(run_fd)


@pytest.mark.parametrize(
    ("kind", "relative", "expected"),
    (
        ("missing-leaf", "missing", "missing is missing"),
        ("missing-parent", "absent/leaf", "nested is missing"),
        ("regular-parent", "regular/leaf", "nested is missing"),
        ("symlink-parent", "link/leaf", "nested is missing"),
        ("directory-leaf", "directory", "leaf must be a regular non-symlink file"),
        ("symlink-leaf", "leaf-link", "leaf could not be opened safely"),
    ),
)
def test_s18_receipt_io_rejects_unsafe_or_missing_paths(
    tmp_path: Path,
    kind: str,
    relative: str,
    expected: str,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir()
    if kind == "regular-parent":
        (root / "regular").write_bytes(b"not a directory")
    elif kind == "symlink-parent":
        (root / "target").mkdir()
        (root / "link").symlink_to("target")
    elif kind == "directory-leaf":
        (root / "directory").mkdir()
    elif kind == "symlink-leaf":
        (root / "target").write_bytes(b"target")
        (root / "leaf-link").symlink_to("target")
    _private_closure(root)
    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io:
            field = "nested" if "/" in relative else "leaf"
            if kind == "missing-leaf":
                field = "missing"
            with pytest.raises(capture_test_gate.CaptureError, match=expected):
                receipt_io.read(relative, field)
    finally:
        os.close(run_fd)


def test_s18_walk_receipt_closure_accepts_stable_nested_tree(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sealed"
    nested = root / "child"
    nested.mkdir(parents=True)
    (nested / "record").write_bytes(b"record")
    _private_closure(root)

    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io:
            assert receipt_io.file_closure() == {"child/record"}
    finally:
        os.close(run_fd)


def test_s18_walk_receipt_closure_maps_root_fstat_error_without_closing_owner_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir(mode=0o500)
    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    real_fstat = os.fstat

    def fail_root_fstat(descriptor: int) -> os.stat_result:
        if descriptor == run_fd:
            raise OSError(errno.EIO, "injected root fstat failure")
        return real_fstat(descriptor)

    monkeypatch.setattr(capture_test_gate.os, "fstat", fail_root_fstat)
    try:
        with pytest.raises(
            capture_test_gate.CaptureError,
            match=r"sealed run closure could not be read safely",
        ):
            capture_test_gate._walk_receipt_closure(
                run_fd,
                None,
                state=capture_test_gate._ReceiptClosureState(files=set()),
                max_entries=capture_test_gate.MAX_RECEIPT_CLOSURE_ENTRIES,
                max_metadata_bytes=(
                    capture_test_gate.MAX_RECEIPT_CLOSURE_METADATA_BYTES
                ),
                entry_metadata_overhead=(
                    capture_test_gate.CLOSURE_ENTRY_METADATA_OVERHEAD
                ),
                directory_flags=lambda: os.O_RDONLY | os.O_DIRECTORY,
                validate_directory=lambda _value, _relative: None,
                validate_file=lambda _value, _relative: None,
            )
        assert real_fstat(run_fd).st_ino == root.stat().st_ino
    finally:
        os.close(run_fd)


@pytest.mark.parametrize(
    ("kind", "expected"),
    (
        ("symlink", "sealed run contains a symlink: unsafe"),
        ("fifo", "sealed run contains a special file: unsafe"),
    ),
)
def test_s18_file_closure_rejects_symlink_and_special_nodes(
    tmp_path: Path,
    kind: str,
    expected: str,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir()
    if kind == "symlink":
        (root / "unsafe").symlink_to("missing")
    else:
        os.mkfifo(root / "unsafe")
    root.chmod(0o500)
    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io,
            pytest.raises(capture_test_gate.CaptureError, match=expected),
        ):
            receipt_io.file_closure()
    finally:
        os.close(run_fd)


def test_s18_file_closure_wraps_os_errors_without_mutating_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir(mode=0o500)
    before = root.stat()
    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)

    def fail_scandir(_descriptor: int):
        raise PermissionError("injected")

    monkeypatch.setattr(capture_test_gate.os, "scandir", fail_scandir)
    try:
        with (
            capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io,
            pytest.raises(
                capture_test_gate.CaptureError,
                match=r"sealed run closure could not be read safely",
            ),
        ):
            receipt_io.file_closure()
    finally:
        os.close(run_fd)
    after = root.stat()
    assert (after.st_ino, after.st_mode, after.st_mtime_ns) == (
        before.st_ino,
        before.st_mode,
        before.st_mtime_ns,
    )


@pytest.mark.parametrize(
    "mutation",
    ("opened-identity", "link-identity", "entry-added", "directory-identity"),
)
def test_s18_walk_receipt_closure_rejects_traversal_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir()
    if mutation in {"opened-identity", "link-identity"}:
        child = root / "child"
        child.mkdir()
        (child / "record").write_bytes(b"record")
    else:
        (root / "record").write_bytes(b"record")
    _private_closure(root)

    if mutation == "opened-identity":
        real_fstat = os.fstat
        child_inode = (root / "child").stat().st_ino

        def changed_child_fstat(descriptor: int) -> os.stat_result:
            observed = real_fstat(descriptor)
            if observed.st_ino == child_inode:
                return _changed_stat(
                    observed,
                    index=1,
                    replacement=observed.st_ino + 1,
                )
            return observed

        monkeypatch.setattr(capture_test_gate.os, "fstat", changed_child_fstat)
    elif mutation == "link-identity":
        real_stat = os.stat

        def changed_child_stat(path, *args, **kwargs) -> os.stat_result:
            observed = real_stat(path, *args, **kwargs)
            if path == "child" and kwargs.get("dir_fd") is not None:
                return _changed_stat(
                    observed,
                    index=1,
                    replacement=observed.st_ino + 1,
                )
            return observed

        monkeypatch.setattr(capture_test_gate.os, "stat", changed_child_stat)
    elif mutation == "entry-added":
        real_scandir = os.scandir
        scans = 0

        def growing_scandir(descriptor: int):
            nonlocal scans
            scans += 1
            if scans == 2:
                root.chmod(0o700)
                (root / "late").write_bytes(b"late")
                (root / "late").chmod(0o400)
                root.chmod(0o500)
            return real_scandir(descriptor)

        monkeypatch.setattr(capture_test_gate.os, "scandir", growing_scandir)
    else:
        real_fstat = os.fstat
        root_inode = root.stat().st_ino
        root_observations = 0

        def changed_root_fstat(descriptor: int) -> os.stat_result:
            nonlocal root_observations
            observed = real_fstat(descriptor)
            if observed.st_ino == root_inode:
                root_observations += 1
                if root_observations >= 3:
                    return _changed_stat(
                        observed,
                        index=8,
                        replacement=int(observed.st_mtime) + 2,
                    )
            return observed

        monkeypatch.setattr(capture_test_gate.os, "fstat", changed_root_fstat)

    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io,
            pytest.raises(
                capture_test_gate.CaptureError,
                match=r"sealed run changed during closure traversal",
            ),
        ):
            receipt_io.file_closure()
    finally:
        os.close(run_fd)


@pytest.mark.parametrize(
    ("kind", "expected"),
    (
        ("missing", "candidate is missing"),
        ("directory", "candidate must be a regular non-symlink file"),
        ("symlink", "candidate must be a regular non-symlink file"),
        ("open-error", "candidate could not be opened safely"),
        ("changed-before", "candidate changed before capture"),
        ("changed-during", "candidate changed during capture"),
        ("removed-during", "candidate changed during capture"),
    ),
)
def test_s18_stable_regular_reader_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    expected: str,
) -> None:
    candidate = tmp_path / "candidate"
    if kind == "directory":
        candidate.mkdir()
    elif kind == "symlink":
        (tmp_path / "target").write_bytes(b"target")
        candidate.symlink_to("target")
    elif kind != "missing":
        candidate.write_bytes(b"content")

    if kind == "open-error":
        real_open = os.open

        def fail_open(path, flags, *args, **kwargs):
            if path == candidate:
                raise PermissionError("injected")
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(capture_test_gate.os, "open", fail_open)
    elif kind in {"changed-before", "changed-during"}:
        real_fstat = os.fstat
        calls = 0
        inode = candidate.stat().st_ino

        def changed_fstat(descriptor: int) -> os.stat_result:
            nonlocal calls
            observed = real_fstat(descriptor)
            if observed.st_ino == inode:
                calls += 1
                if kind == "changed-before" or calls > 1:
                    return _changed_stat(
                        observed,
                        index=8,
                        replacement=int(observed.st_mtime) + 2,
                    )
            return observed

        monkeypatch.setattr(capture_test_gate.os, "fstat", changed_fstat)
    elif kind == "removed-during":
        real_lstat = Path.lstat
        calls = 0

        def disappearing_lstat(path: Path) -> os.stat_result:
            nonlocal calls
            if path == candidate:
                calls += 1
                if calls > 1:
                    raise FileNotFoundError(path)
            return real_lstat(path)

        monkeypatch.setattr(Path, "lstat", disappearing_lstat)

    with pytest.raises(capture_test_gate.CaptureError, match=expected):
        capture_test_gate._read_stable_regular(candidate, "candidate")


@pytest.mark.parametrize(
    ("kind", "relative", "expected"),
    (
        ("missing", "missing", "record is missing"),
        ("symlink", "link", "record must not use a symlink"),
        ("parent-file", "parent/leaf", "record parent must be a directory"),
        ("leaf-directory", "directory", "record must be a regular file"),
    ),
)
def test_s18_safe_run_file_rejects_path_substitution(
    tmp_path: Path,
    kind: str,
    relative: str,
    expected: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    if kind == "symlink":
        (root / "target").write_bytes(b"target")
        (root / "link").symlink_to("target")
    elif kind == "parent-file":
        (root / "parent").write_bytes(b"parent")
    elif kind == "leaf-directory":
        (root / "directory").mkdir()
    with pytest.raises(capture_test_gate.CaptureError, match=expected):
        capture_test_gate._safe_run_file(root, relative, "record")


@pytest.mark.parametrize(
    ("record", "expected"),
    (
        (None, "record must be a file record"),
        ({}, "record must contain path, sha256, and size"),
        ({"path": "data", "size": 4, "sha256": None}, "lowercase SHA-256"),
        ({"path": "data", "size": 4, "sha256": "A" * 64}, "lowercase SHA-256"),
        ({"path": "data", "size": True, "sha256": "0" * 64}, "non-negative integer"),
        ({"path": "data", "size": -1, "sha256": "0" * 64}, "non-negative integer"),
        ({"path": "data", "size": 5, "sha256": "0" * 64}, "size mismatch"),
        ({"path": "data", "size": 4, "sha256": "0" * 64}, "hash mismatch"),
    ),
)
def test_s18_file_record_schema_and_content_fail_closed(
    tmp_path: Path,
    record: object,
    expected: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "data").write_bytes(b"data")
    with pytest.raises(capture_test_gate.CaptureError, match=expected):
        capture_test_gate._verify_record(root, record, "record")


@pytest.mark.parametrize(
    ("content", "expected"),
    (
        (b"\xff", "must be valid UTF-8 JSON"),
        (b"{", "must be valid UTF-8 JSON"),
        (b"[]", "must be an object"),
        (b'{"a":1,"a":2}', "contains a duplicate field"),
    ),
)
def test_s18_strict_json_rejects_ambiguous_or_malformed_input(
    content: bytes,
    expected: str,
) -> None:
    with pytest.raises(capture_test_gate.CaptureError, match=expected):
        capture_test_gate._strict_json_object(content, "document")


@pytest.mark.parametrize(
    ("value", "keys", "optional", "expected"),
    (
        ([], {"a"}, None, "must be an object"),
        ({}, {"a"}, None, "has an invalid shape"),
        ({"a": 1, "unknown": 2}, {"a"}, None, "has an invalid shape"),
    ),
)
def test_s18_exact_object_schema_rejects_wrong_shapes(
    value: object,
    keys: set[str],
    optional: set[str] | None,
    expected: str,
) -> None:
    with pytest.raises(capture_test_gate.CaptureError, match=expected):
        capture_test_gate._exact_object(
            value,
            keys,
            "document",
            optional=optional,
        )


def test_s18_main_run_success_and_failures_are_channel_separated(
    capture_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, retention = capture_repo
    exit_code = capture_test_gate.main(
        [
            "run",
            "--layer",
            "portable",
            "--retention-root",
            os.fspath(retention),
            "--repo-root",
            os.fspath(repo),
        ]
    )
    success = capsys.readouterr()
    assert exit_code == 0
    assert success.err == ""
    assert Path(success.out.strip()).is_dir()

    invalid_retention = repo / "inside"
    invalid_retention.mkdir()
    exit_code = capture_test_gate.main(
        [
            "run",
            "--layer",
            "portable",
            "--retention-root",
            os.fspath(invalid_retention),
            "--repo-root",
            os.fspath(repo),
        ]
    )
    failure = capsys.readouterr()
    assert exit_code == capture_test_gate.CAPTURE_ERROR_EXIT
    assert failure.out == ""
    assert failure.err.startswith("evidence capture failed: ")

    exit_code = capture_test_gate.main(
        [
            "verify",
            "--receipt",
            os.fspath(retention / "missing" / "receipt.json"),
            "--mode",
            "archived-integrity",
        ]
    )
    failure = capsys.readouterr()
    assert exit_code == 1
    assert failure.out == ""
    assert failure.err.startswith("evidence receipt verification failed: ")


@pytest.mark.parametrize(
    ("wrong_owner", "mode", "expected"),
    (
        (True, 0o500, "sealed run directory owner is invalid: child"),
        (False, 0o550, "sealed run directory must use mode 0500: child"),
    ),
    ids=("wrong-owner", "overwide-mode"),
)
def test_s18_receipt_read_validates_parent_directory_before_leaf_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wrong_owner: bool,
    mode: int,
    expected: str,
) -> None:
    root = tmp_path / "sealed"
    child = root / "child"
    child.mkdir(parents=True)
    leaf = child / "leaf"
    leaf.write_bytes(b"secret")
    _private_closure(root)
    child.chmod(mode)
    child_inode = child.stat().st_ino
    real_fstat = os.fstat
    bytes_read = 0
    real_read = os.read

    def owner_fixture(descriptor: int) -> os.stat_result:
        observed = real_fstat(descriptor)
        if wrong_owner and observed.st_ino == child_inode:
            return _changed_stat(
                observed,
                index=4,
                replacement=os.geteuid() + 1,
            )
        return observed

    def track_read(descriptor: int, count: int) -> bytes:
        nonlocal bytes_read
        content = real_read(descriptor, count)
        bytes_read += len(content)
        return content

    monkeypatch.setattr(capture_test_gate.os, "fstat", owner_fixture)
    monkeypatch.setattr(capture_test_gate.os, "read", track_read)
    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io,
            pytest.raises(capture_test_gate.CaptureError, match=expected),
        ):
            receipt_io.read("child/leaf", "leaf")
    finally:
        os.close(run_fd)
    assert bytes_read == 0


@pytest.mark.parametrize(
    ("change", "expected"),
    (
        ("removed", "leaf changed during verification"),
        ("identity", "leaf changed during verification"),
        ("link-count", "leaf must have link count 1"),
    ),
)
def test_s18_receipt_read_rejects_leaf_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    expected: str,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir()
    leaf = root / "leaf"
    leaf.write_bytes(b"data")
    _private_closure(root)
    real_stat = os.stat

    def changed_stat(path, *args, **kwargs):
        if path == "leaf" and kwargs.get("dir_fd") is not None:
            if change == "removed":
                raise FileNotFoundError(path)
            observed = real_stat(path, *args, **kwargs)
            if change == "identity":
                return _changed_stat(
                    observed,
                    index=8,
                    replacement=int(observed.st_mtime) + 2,
                )
            return _changed_stat(observed, index=3, replacement=2)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(capture_test_gate.os, "stat", changed_stat)
    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io,
            pytest.raises(capture_test_gate.CaptureError, match=expected),
        ):
            receipt_io.read("leaf", "leaf")
    finally:
        os.close(run_fd)


def _rewrite_source_summary(
    run_directory: Path,
    document: dict[str, object],
    summary: object,
) -> None:
    record = document["source"]["before"]
    summary_path = run_directory / record["path"]
    content = json.dumps(summary, sort_keys=True).encode()
    summary_path.chmod(0o600)
    summary_path.write_bytes(content)
    summary_path.chmod(0o400)
    record["size"] = len(content)
    record["sha256"] = capture_test_gate._sha256(content)
    _rewrite_sealed_receipt(run_directory, document)


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    (
        ("__document__", [], "source.before must be an object"),
        ("head", None, "source.before.head must be a 40-character commit"),
        ("safe", "yes", "source.before.safe must be boolean"),
        ("patch_sha256", "0" * 64, "source.before.patch_sha256 mismatch"),
        ("status_sha256", "0" * 64, "source.before.status_sha256 mismatch"),
        ("dirty", False, "source.before.dirty mismatch"),
        ("untracked", {}, "source.before.untracked must be an array"),
        ("untracked.0", None, r"source.before.untracked\[0\] must be an object"),
        ("untracked.0.mode", True, r"untracked\[0\].mode must be an integer"),
        ("untracked.0.kind", "unknown", r"untracked\[0\].kind is invalid"),
        ("untracked.0.size", 99, r"untracked\[0\] archived snapshot mismatch"),
        ("aggregate_sha256", "0" * 64, "source.before.aggregate_sha256 mismatch"),
    ),
    ids=(
        "summary-shape",
        "head",
        "safe",
        "patch-hash",
        "status-hash",
        "dirty",
        "ledger-shape",
        "ledger-entry-shape",
        "ledger-mode",
        "ledger-kind",
        "snapshot-binding",
        "aggregate",
    ),
)
def test_s18_source_summary_mutations_fail_closed(
    capture_repo: tuple[Path, Path],
    path: str,
    value: object,
    expected: str,
) -> None:
    repo, retention = capture_repo
    (repo / "untracked.bin").write_bytes(b"content")
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    document = _receipt(result)
    summary_path = result.run_directory / document["source"]["before"]["path"]
    summary: object = json.loads(summary_path.read_text(encoding="utf-8"))
    if path == "__document__":
        summary = value
    elif path == "untracked.0":
        summary["untracked"][0] = value
    elif path.startswith("untracked.0."):
        summary["untracked"][0][path.rsplit(".", 1)[1]] = value
    else:
        _change_path(summary, path, value)
    _rewrite_source_summary(result.run_directory, document, summary)

    with pytest.raises(capture_test_gate.CaptureError, match=expected):
        capture_test_gate.verify_receipt(
            result.run_directory / "receipt.json",
            mode="archived-integrity",
        )


def test_s18_source_summary_rejects_invalid_symlink_target(
    capture_repo: tuple[Path, Path],
) -> None:
    repo, retention = capture_repo
    (repo / "untracked-link").symlink_to("tracked.txt")
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    document = _receipt(result)
    summary_path = result.run_directory / document["source"]["before"]["path"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["untracked"][0]["target_base64"] = "!invalid!"
    _rewrite_source_summary(result.run_directory, document, summary)

    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"untracked\[0\].target_base64 is invalid",
    ):
        capture_test_gate.verify_receipt(
            result.run_directory / "receipt.json",
            mode="archived-integrity",
        )


def test_s18_verifier_rejects_invalid_mode_name_and_missing_source_anchor(
    capture_repo: tuple[Path, Path],
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    receipt = result.run_directory / "receipt.json"
    with pytest.raises(capture_test_gate.CaptureError, match=r"mode must be"):
        capture_test_gate.verify_receipt(receipt, mode="future-mode")
    with pytest.raises(capture_test_gate.CaptureError, match=r"repo_root is required"):
        capture_test_gate.verify_receipt(receipt, mode="current-source")

    run_fd = os.open(result.run_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(capture_test_gate.CaptureError, match=r"must be receipt.json"):
            capture_test_gate.verify_receipt_at(
                run_fd,
                "nested/receipt.json",
                "archived-integrity",
            )
        with pytest.raises(capture_test_gate.CaptureError, match=r"repo_root_fd is required"):
            capture_test_gate.verify_receipt_at(
                run_fd,
                "receipt.json",
                "current-source",
            )
    finally:
        os.close(run_fd)


@pytest.mark.parametrize(
    ("document", "expected"),
    (
        ([], "receipt must be a JSON object"),
        ({}, "receipt schema_version 1 is required"),
    ),
)
def test_s18_verifier_rejects_nonreceipt_json_documents(
    capture_repo: tuple[Path, Path],
    document: object,
    expected: str,
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    receipt = result.run_directory / "receipt.json"
    receipt.chmod(0o600)
    receipt.write_text(json.dumps(document), encoding="utf-8")
    receipt.chmod(0o400)
    with pytest.raises(capture_test_gate.CaptureError, match=expected):
        capture_test_gate.verify_receipt(receipt, mode="archived-integrity")


def test_s18_verifier_rejects_non_json_receipt(
    capture_repo: tuple[Path, Path],
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    receipt = result.run_directory / "receipt.json"
    receipt.chmod(0o600)
    receipt.write_bytes(b"not-json")
    receipt.chmod(0o400)
    with pytest.raises(capture_test_gate.CaptureError, match=r"valid UTF-8 JSON"):
        capture_test_gate.verify_receipt(receipt, mode="archived-integrity")


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    (
        ("run_id", "bad/id", "run_id is invalid"),
        ("run_id", "different-valid-run", "sealed run directory must match run_id"),
        ("qualification", [], "schema_version 1 forbids"),
    ),
)
def test_s18_verifier_rejects_invalid_receipt_identity(
    capture_repo: tuple[Path, Path],
    path: str,
    value: object,
    expected: str,
) -> None:
    repo, retention = capture_repo
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )
    assert result.run_directory is not None
    document = _receipt(result)
    _change_path(document, path, value)
    _rewrite_sealed_receipt(result.run_directory, document)
    with pytest.raises(capture_test_gate.CaptureError, match=expected):
        capture_test_gate.verify_receipt(
            result.run_directory / "receipt.json",
            mode="archived-integrity",
        )


@pytest.mark.parametrize(
    ("repo_kind", "retention_kind", "layer", "expected"),
    (
        ("missing", "directory", "portable", "repo_root does not exist"),
        ("directory", "directory", "unknown", "unknown layer"),
        ("directory", "file", "portable", "must be directories"),
    ),
)
def test_s18_preflight_fails_before_creating_run_directory(
    tmp_path: Path,
    repo_kind: str,
    retention_kind: str,
    layer: str,
    expected: str,
) -> None:
    repo = tmp_path / "repo"
    retention = tmp_path / "retention"
    if repo_kind == "directory":
        repo.mkdir()
    if retention_kind == "directory":
        retention.mkdir()
    else:
        retention.write_bytes(b"not a directory")
    with pytest.raises(capture_test_gate.CaptureError, match=expected):
        capture_test_gate._preflight(repo, retention, layer)


def test_s18_snapshot_artifacts_rejects_nondirectory_and_symlinked_artifact(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    artifact_root = run_root / "artifacts"
    artifact_root.write_bytes(b"not a directory")
    records, missing, reasons = capture_test_gate._snapshot_artifacts(
        run_root,
        artifact_root,
        "portable",
    )
    assert records == {}
    assert missing == sorted(capture_test_gate.ARTIFACT_CLOSURES["portable"])
    assert reasons == ["ARTIFACT_LAYER_MISMATCH"]

    artifact_root.unlink()
    artifact_root.mkdir()
    (artifact_root / "portable.xml").symlink_to("missing")
    records, missing, reasons = capture_test_gate._snapshot_artifacts(
        run_root,
        artifact_root,
        "portable",
    )
    assert records == {}
    assert "portable.xml" not in missing
    assert "ARTIFACT_CHANGED_DURING_CAPTURE" in reasons
    assert "REQUIRED_ARTIFACT_MISSING" in reasons


def test_s18_git_and_source_head_failures_are_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(capture_test_gate.CaptureError, match=r"not a git repository"):
        capture_test_gate._git(tmp_path, "rev-parse", "HEAD")

    monkeypatch.setattr(capture_test_gate, "_git", lambda *_args, **_kwargs: b"bad\n")
    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"source.head must be a 40-character commit",
    ):
        capture_test_gate._source_material(tmp_path)


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        ("opened-not-directory", "leaf parent changed during verification"),
        ("opened-identity", "leaf parent changed during verification"),
        ("open-error", "leaf could not be opened safely"),
    ),
)
def test_s18_open_parent_rejects_opened_type_identity_and_os_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected: str,
) -> None:
    root = tmp_path / "sealed"
    child = root / "child"
    child.mkdir(parents=True)
    (child / "leaf").write_bytes(b"data")
    _private_closure(root)
    child_inode = child.stat().st_ino
    real_fstat = os.fstat
    real_open = os.open

    def changed_fstat(descriptor: int) -> os.stat_result:
        observed = real_fstat(descriptor)
        if observed.st_ino != child_inode or failure == "open-error":
            return observed
        if failure == "opened-not-directory":
            return _changed_stat(
                observed,
                index=0,
                replacement=stat.S_IFREG | 0o400,
            )
        return _changed_stat(
            observed,
            index=8,
            replacement=int(observed.st_mtime) + 2,
        )

    def fail_open(path, flags, *args, **kwargs):
        if failure == "open-error" and path == "child":
            raise PermissionError("injected")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(capture_test_gate.os, "fstat", changed_fstat)
    monkeypatch.setattr(capture_test_gate.os, "open", fail_open)
    run_fd = real_open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io,
            pytest.raises(capture_test_gate.CaptureError, match=expected),
        ):
            receipt_io.read("child/leaf", "leaf")
    finally:
        os.close(run_fd)


def test_s18_open_parent_closes_child_fd_when_fstat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sealed"
    child = root / "child"
    child.mkdir(parents=True)
    (child / "leaf").write_bytes(b"data")
    _private_closure(root)
    real_open = os.open
    real_fstat = os.fstat
    child_fd: int | None = None

    def record_open(path, flags, *args, **kwargs) -> int:
        nonlocal child_fd
        descriptor = real_open(path, flags, *args, **kwargs)
        if path == "child" and kwargs.get("dir_fd") is not None:
            child_fd = descriptor
        return descriptor

    def fail_child_fstat(descriptor: int) -> os.stat_result:
        if descriptor == child_fd:
            raise OSError(errno.EIO, "injected child fstat failure")
        return real_fstat(descriptor)

    monkeypatch.setattr(capture_test_gate.os, "open", record_open)
    monkeypatch.setattr(capture_test_gate.os, "fstat", fail_child_fstat)
    run_fd = real_open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io,
            pytest.raises(
                capture_test_gate.CaptureError,
                match=r"leaf could not be opened safely",
            ),
        ):
            receipt_io.read("child/leaf", "leaf")
        assert child_fd is not None
        with pytest.raises(OSError) as raised:
            real_fstat(child_fd)
        assert raised.value.errno == errno.EBADF
    finally:
        os.close(run_fd)


def test_s18_open_directory_anchor_rejects_real_symlink_ancestor(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real"
    target = real_parent / "target"
    target.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"anchor could not be opened safely",
    ):
        capture_test_gate._open_directory_anchor(alias / "target", "anchor")


def test_s18_open_directory_anchor_closes_leaf_fd_when_fstat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    real_open = os.open
    real_fstat = os.fstat
    leaf_fd: int | None = None

    def record_open(path, flags, *args, **kwargs) -> int:
        nonlocal leaf_fd
        descriptor = real_open(path, flags, *args, **kwargs)
        if path == anchor or (
            path == anchor.name and kwargs.get("dir_fd") is not None
        ):
            leaf_fd = descriptor
        return descriptor

    def fail_leaf_fstat(descriptor: int) -> os.stat_result:
        if descriptor == leaf_fd:
            raise OSError(errno.EIO, "injected anchor fstat failure")
        return real_fstat(descriptor)

    monkeypatch.setattr(capture_test_gate.os, "open", record_open)
    monkeypatch.setattr(capture_test_gate.os, "fstat", fail_leaf_fstat)
    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"anchor could not be opened safely",
    ):
        capture_test_gate._open_directory_anchor(anchor, "anchor")
    assert leaf_fd is not None
    with pytest.raises(OSError) as raised:
        real_fstat(leaf_fd)
    assert raised.value.errno == errno.EBADF


def test_s18_receipt_read_rejects_short_os_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir()
    (root / "leaf").write_bytes(b"data")
    _private_closure(root)
    reads = iter((b"dat", b""))
    monkeypatch.setattr(capture_test_gate.os, "read", lambda _fd, _count: next(reads))
    run_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            capture_test_gate._DirFdReceiptIO(run_fd) as receipt_io,
            pytest.raises(
                capture_test_gate.CaptureError,
                match=r"leaf changed size during verification",
            ),
        ):
            receipt_io.read("leaf", "leaf")
    finally:
        os.close(run_fd)


def test_s18_stable_reader_is_safe_without_nofollow_constant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.write_bytes(b"data")
    monkeypatch.delattr(capture_test_gate.os, "O_NOFOLLOW")

    assert capture_test_gate._read_stable_regular(candidate, "candidate") == b"data"


def test_s18_stable_reader_rejects_short_stream_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.write_bytes(b"data")
    real_fdopen = os.fdopen

    class ShortReader:
        def __init__(self, descriptor: int) -> None:
            self._stream = real_fdopen(descriptor, "rb")

        def __enter__(self):
            self._stream.__enter__()
            return self

        def __exit__(self, *exc: object) -> None:
            self._stream.__exit__(*exc)

        def fileno(self) -> int:
            return self._stream.fileno()

        def read(self) -> bytes:
            return self._stream.read()[:-1]

    monkeypatch.setattr(
        capture_test_gate.os,
        "fdopen",
        lambda descriptor, _mode: ShortReader(descriptor),
    )
    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"candidate changed size during capture",
    ):
        capture_test_gate._read_stable_regular(candidate, "candidate")


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        (None, (capture_test_gate.CAPTURE_ERROR_EXIT, None)),
        (-signal.SIGTERM, (128 + signal.SIGTERM, signal.SIGTERM)),
        (5, (5, None)),
    ),
)
def test_s18_returncode_normalization_is_total(
    raw: int | None,
    expected: tuple[int, int | None],
) -> None:
    assert capture_test_gate._normalize_returncode(raw) == expected


def test_s18_seal_rejects_symlink_without_publishing(tmp_path: Path) -> None:
    staging = tmp_path / ".incomplete-run"
    sealed = tmp_path / "run"
    staging.mkdir()
    (staging / "unsafe").symlink_to("missing")

    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"run directory must not contain symlinks",
    ):
        capture_test_gate._seal_run(staging, sealed)

    assert staging.is_dir()
    assert not sealed.exists()


def test_s18_seal_never_replaces_existing_target(tmp_path: Path) -> None:
    staging = tmp_path / ".incomplete-run"
    sealed = tmp_path / "run"
    staging.mkdir()
    (staging / "data").write_bytes(b"candidate")
    sealed.write_bytes(b"existing")
    before = sealed.stat()

    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"refusing to replace an existing sealed run",
    ):
        capture_test_gate._seal_run(staging, sealed)

    after = sealed.stat()
    assert sealed.read_bytes() == b"existing"
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert staging.is_dir()


def test_s18_explicit_gate_signal_is_reflected_by_finalizer(
    capture_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, retention = capture_repo

    def signalled_gate(*_args, **_kwargs) -> tuple[int, int]:
        return -signal.SIGTERM, signal.SIGTERM

    monkeypatch.setattr(capture_test_gate, "_run_gate_process", signalled_gate)
    result = capture_test_gate.capture_gate(
        repo_root=repo,
        retention_root=retention,
        layer="portable",
        base_ref="HEAD",
    )

    assert result.exit_code == 128 + signal.SIGTERM
    assert result.sealed is True
    document = _receipt(result)
    assert document["run"]["signal"] == signal.SIGTERM
    assert "GATE_TERMINATED_BY_SIGNAL" in document["verification"]["reason_codes"]


def test_s18_main_does_not_invent_run_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        capture_test_gate,
        "capture_gate",
        lambda **_kwargs: capture_test_gate.CaptureResult(7, None, False),
    )

    exit_code = capture_test_gate.main(
        [
            "run",
            "--layer",
            "portable",
            "--retention-root",
            os.fspath(tmp_path),
            "--repo-root",
            os.fspath(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 7
    assert captured.out == ""
    assert captured.err == ""


def _fake_source_git(_root: Path, *arguments: str, **_kwargs) -> bytes:
    if arguments[:2] == ("rev-parse", "HEAD"):
        return b"a" * 40 + b"\n"
    if arguments[0] == "diff":
        return b""
    if arguments[0] == "status":
        return b"?? unsafe\0"
    if arguments[0] == "ls-files":
        return b"unsafe\0"
    raise AssertionError(arguments)


def test_s18_source_material_records_git_reported_special_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    os.mkfifo(tmp_path / "unsafe")
    monkeypatch.setattr(capture_test_gate, "_git", _fake_source_git)

    summary, patch, status_bytes, snapshots = capture_test_gate._source_material(tmp_path)

    assert patch == b""
    assert status_bytes == b"?? unsafe\0"
    assert snapshots == []
    assert summary["safe"] is False
    assert summary["untracked"] == [
        {
            "path": "unsafe",
            "mode": stat.S_IMODE((tmp_path / "unsafe").lstat().st_mode),
            "kind": "special",
            "size": 0,
            "sha256": None,
        }
    ]


def test_s18_source_material_rejects_symlink_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsafe = tmp_path / "unsafe"
    unsafe.symlink_to("target")
    monkeypatch.setattr(capture_test_gate, "_git", _fake_source_git)
    real_lstat = Path.lstat
    observations = 0

    def drifting_lstat(path: Path) -> os.stat_result:
        nonlocal observations
        observed = real_lstat(path)
        if path == unsafe:
            observations += 1
            if observations > 1:
                return _changed_stat(
                    observed,
                    index=8,
                    replacement=int(observed.st_mtime) + 2,
                )
        return observed

    monkeypatch.setattr(Path, "lstat", drifting_lstat)
    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"source untracked symlink changed during capture",
    ):
        capture_test_gate._source_material(tmp_path)


def test_s18_source_summary_reads_archived_snapshot_without_callback(
    capture_repo: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    repo, _retention = capture_repo
    (repo / "untracked.bin").write_bytes(b"content")
    run_root = tmp_path / "run"
    run_root.mkdir()
    summary, _record = capture_test_gate._capture_source(repo, run_root, "before")

    verified = capture_test_gate._verify_source_summary(run_root, "before", summary)

    assert verified["aggregate_sha256"] == summary["aggregate_sha256"]
    assert verified["untracked"][0]["kind"] == "regular"


def test_s18_source_summary_rejects_symlink_target_mismatch(
    capture_repo: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    repo, _retention = capture_repo
    (repo / "untracked-link").symlink_to("tracked.txt")
    run_root = tmp_path / "run"
    run_root.mkdir()
    summary, _record = capture_test_gate._capture_source(repo, run_root, "before")
    summary["untracked"][0]["size"] += 1

    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"source.before.untracked\[0\] symlink target mismatch",
    ):
        capture_test_gate._verify_source_summary(run_root, "before", summary)


def test_s18_source_summary_rejects_duplicate_ledger_paths(
    capture_repo: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    repo, _retention = capture_repo
    (repo / "untracked.bin").write_bytes(b"content")
    run_root = tmp_path / "run"
    run_root.mkdir()
    summary, _record = capture_test_gate._capture_source(repo, run_root, "before")
    summary["untracked"].append(copy.deepcopy(summary["untracked"][0]))

    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"source.before.untracked must be sorted and unique",
    ):
        capture_test_gate._verify_source_summary(run_root, "before", summary)


def test_s18_source_material_at_rejects_invalid_and_nondirectory_fd(
    tmp_path: Path,
) -> None:
    closed_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    os.close(closed_fd)
    with pytest.raises(
        capture_test_gate.CaptureError,
        match=r"repo_root_fd is not a valid open directory",
    ):
        capture_test_gate._source_material_at(closed_fd)

    leaf = tmp_path / "leaf"
    leaf.write_bytes(b"data")
    leaf_fd = os.open(leaf, os.O_RDONLY)
    try:
        with pytest.raises(
            capture_test_gate.CaptureError,
            match=r"repo_root_fd must refer to a directory",
        ):
            capture_test_gate._source_material_at(leaf_fd)
    finally:
        os.close(leaf_fd)


@pytest.mark.parametrize("drift", ("descriptor", "anchor"))
def test_s18_source_material_at_rejects_anchor_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    repo_fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY)
    real_fstat = os.fstat
    repo_inode = repo.stat().st_ino
    observations = 0

    monkeypatch.setattr(
        capture_test_gate,
        "_fd_anchor_path",
        lambda _descriptor, _field: other if drift == "anchor" else repo,
    )
    monkeypatch.setattr(
        capture_test_gate,
        "_source_material",
        lambda *_args, **_kwargs: ({"aggregate_sha256": "0" * 64}, b"", b"", []),
    )

    def drifting_fstat(descriptor: int) -> os.stat_result:
        nonlocal observations
        observed = real_fstat(descriptor)
        if drift == "descriptor" and observed.st_ino == repo_inode:
            observations += 1
            if observations > 1:
                return _changed_stat(
                    observed,
                    index=0,
                    replacement=observed.st_mode ^ stat.S_IXOTH,
                )
        return observed

    monkeypatch.setattr(capture_test_gate.os, "fstat", drifting_fstat)
    try:
        with pytest.raises(
            capture_test_gate.CaptureError,
            match=r"repo_root_fd anchor changed during verification",
        ):
            capture_test_gate._source_material_at(repo_fd)
    finally:
        os.close(repo_fd)
