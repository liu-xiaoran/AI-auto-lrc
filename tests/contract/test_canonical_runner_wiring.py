from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUN_TEST_GATE = REPOSITORY_ROOT / "scripts/run_test_gate.sh"
RUN_CANONICAL = REPOSITORY_ROOT / "scripts/run_canonical_legacy_v1_golden.sh"
SOURCE_SHA256 = "1" * 64


def _fake_tools(tmp_path: Path) -> tuple[Path, Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    invocation_log = tmp_path / "invocations.txt"

    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/bin/sh
set -eu
printf 'uv %s\\n' "$*" >> "$FAKE_INVOCATION_LOG"
case "$*" in
  *scripts/run_canonical_gate.py*) exit "${FAKE_PRODUCER_RC:-0}" ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o700)

    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/bin/sh
set -eu
printf 'docker %s\\n' "$*" >> "$FAKE_INVOCATION_LOG"
exit 0
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o700)
    return fake_bin, invocation_log, fake_uv


def _environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_bin, invocation_log, _fake_uv = _fake_tools(tmp_path)
    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_INVOCATION_LOG": os.fspath(invocation_log),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
        }
    )
    return environment, invocation_log


def test_capture_bound_canonical_runs_producer_before_junit_gate(tmp_path: Path):
    environment, invocation_log = _environment(tmp_path)
    artifacts = tmp_path / "artifacts"
    environment.update(
        {
            "AI_AUTO_LRC_EVIDENCE_RUN_ID": "canonical-run-001",
            "AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256": SOURCE_SHA256,
            "AI_AUTO_LRC_GATE_ARTIFACT_DIR": os.fspath(artifacts),
        }
    )

    result = subprocess.run(
        [os.fspath(RUN_TEST_GATE), "canonical"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    calls = invocation_log.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 2
    assert "scripts/run_canonical_gate.py" in calls[0]
    assert f"--artifact-root {artifacts}" in calls[0]
    assert "--run-id canonical-run-001" in calls[0]
    assert f"--source-sha256 {SOURCE_SHA256}" in calls[0]
    assert f"--repo-root {REPOSITORY_ROOT}" in calls[0]
    assert "scripts/verify_quality_gates.py junit" in calls[1]
    assert "--layer canonical" in calls[1]
    assert f"--junit-xml {artifacts / 'canonical.xml'}" in calls[1]
    assert f"--output {artifacts / 'canonical-gate.json'}" in calls[1]
    assert "--run-id canonical-run-001" in calls[1]
    assert not any(call.startswith("docker ") for call in calls)


def test_capture_bound_canonical_preserves_producer_failure(tmp_path: Path):
    environment, invocation_log = _environment(tmp_path)
    environment.update(
        {
            "AI_AUTO_LRC_EVIDENCE_RUN_ID": "canonical-run-failed",
            "AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256": SOURCE_SHA256,
            "AI_AUTO_LRC_GATE_ARTIFACT_DIR": os.fspath(tmp_path / "artifacts"),
            "FAKE_PRODUCER_RC": "23",
        }
    )

    result = subprocess.run(
        [os.fspath(RUN_TEST_GATE), "canonical"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 23
    calls = invocation_log.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1
    assert "scripts/run_canonical_gate.py" in calls[0]
    assert "scripts/verify_quality_gates.py" not in calls[0]


def test_capture_bound_canonical_requires_source_binding(tmp_path: Path):
    environment, invocation_log = _environment(tmp_path)
    environment.update(
        {
            "AI_AUTO_LRC_EVIDENCE_RUN_ID": "canonical-run-no-source",
            "AI_AUTO_LRC_GATE_ARTIFACT_DIR": os.fspath(tmp_path / "artifacts"),
        }
    )
    environment.pop("AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256", None)

    result = subprocess.run(
        [os.fspath(RUN_TEST_GATE), "canonical"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 70
    assert "AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256 is required" in result.stderr
    assert not invocation_log.exists()


def test_non_capture_verify_keeps_legacy_docker_path(tmp_path: Path):
    environment, invocation_log = _environment(tmp_path)
    environment.pop("AI_AUTO_LRC_EVIDENCE_RUN_ID", None)
    environment.pop("AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256", None)
    environment.pop("AI_AUTO_LRC_CANONICAL_EVIDENCE_DIR", None)

    result = subprocess.run(
        [os.fspath(RUN_CANONICAL), "verify"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    calls = invocation_log.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 2
    assert calls[0].startswith("docker build ")
    assert calls[1].startswith("docker run ")
    assert not any("run_canonical_gate.py" in call for call in calls)


@pytest.mark.parametrize(
    ("mode", "entrypoint"),
    (
        ("candidate", "generate_legacy_v1_feature_golden.py"),
        ("numeric-candidate", "generate_legacy_v1_numeric_golden.py"),
        ("public-e2e-candidate", "generate_legacy_v1_public_e2e_golden.py"),
    ),
)
def test_candidate_modes_ignore_capture_binding_and_keep_legacy_path(
    tmp_path: Path,
    mode: str,
    entrypoint: str,
):
    environment, invocation_log = _environment(tmp_path)
    environment.update(
        {
            "AI_AUTO_LRC_EVIDENCE_RUN_ID": "must-not-switch-candidate-mode",
            "AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256": SOURCE_SHA256,
        }
    )

    result = subprocess.run(
        [os.fspath(RUN_CANONICAL), mode],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    calls = invocation_log.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 2
    assert calls[0].startswith("docker build ")
    assert calls[1].startswith("docker run ")
    assert entrypoint in calls[1]
    assert not any("run_canonical_gate.py" in call for call in calls)


def test_shell_runner_scripts_are_syntax_valid_and_executable():
    for script in (RUN_CANONICAL, RUN_TEST_GATE):
        result = subprocess.run(
            ["bash", "-n", os.fspath(script)],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert script.stat().st_mode & stat.S_IXUSR
