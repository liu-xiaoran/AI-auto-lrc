"""Self-tests for local coverage and evidence-layer release gates."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.verify_quality_gates import (
    DEFAULT_POLICY,
    changed_python_lines,
    coverage_gate_report,
    junit_gate_report,
    load_policy,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPOSITORY_ROOT / "scripts/verify_quality_gates.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _coverage_record(*, executed=(1,), missing=(), branch=True):
    statements = len(executed) + len(missing)
    return {
        "meta": {"branch_coverage": branch},
        "totals": {
            "covered_lines": len(executed),
            "num_statements": statements,
        },
        "files": {
            "t2l/example.py": {
                "executed_lines": list(executed),
                "missing_lines": list(missing),
                "functions": {},
            }
        },
    }


def _minimal_policy():
    return {
        "coverage": {
            "overall_line_percent": 80,
            "diff_line_percent": 90,
        },
        "critical_targets": [],
    }


def _write_junit(path: Path, classnames: list[str], *, skipped=()) -> None:
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    for index, classname in enumerate(classnames):
        case = ET.SubElement(
            suite,
            "testcase",
            classname=classname,
            name=f"test_{index}",
        )
        if index in skipped:
            ET.SubElement(case, "skipped", message="fixture unavailable")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _write_gate_policy(path: Path) -> None:
    path.write_text(
        """\
schema_version = 1
critical_targets = []

[coverage]
source_root = "t2l"
overall_line_percent = 80
diff_line_percent = 90
excluded_paths = []

[pytest_layers.portable]
allowed_classname_prefixes = ["tests.unit.", "tests.contract.", "tests.component."]
required_markers = ["component"]
zero_skip = true

[pytest_layers.package]
allowed_classname_prefixes = ["tests.package."]
required_markers = ["package"]
zero_skip = true

[pytest_layers.canonical]
allowed_classname_prefixes = ["tests.golden."]
required_markers = ["golden"]
zero_skip = true
""",
        encoding="utf-8",
    )


def _init_coverage_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "gate@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Gate Test"], cwd=repo, check=True)
    source = repo / "t2l"
    source.mkdir()
    (source / "example.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    (source / "example.py").write_text("value = 2\n", encoding="utf-8")


def test_quality_policy_locks_thresholds_critical_categories_and_layers():
    policy = load_policy()
    assert policy["coverage"] == {
        "source_root": "t2l",
        "overall_line_percent": 80,
        "diff_line_percent": 90,
        "excluded_paths": ["t2l/mtl/model.py", "t2l/mtl/utils.py"],
    }
    assert {target["category"] for target in policy["critical_targets"]} == {
        "cli-output",
        "strict-partial",
        "asset-validation",
        "atomic-output",
        "optional-dependency-error",
    }
    assert set(policy["pytest_layers"]) == {"portable", "package", "canonical"}
    assert all(layer["zero_skip"] for layer in policy["pytest_layers"].values())


def test_diff_gate_uses_executable_lines_and_rejects_below_ninety_percent():
    coverage = _coverage_record(executed=tuple(range(1, 10)), missing=(10,))
    report, failures = coverage_gate_report(
        coverage,
        {"t2l/example.py": set(range(1, 11))},
        _minimal_policy(),
    )

    assert report["diff_line"]["percent"] == 90.0
    assert failures == []

    coverage["files"]["t2l/example.py"]["executed_lines"] = list(range(1, 9))
    coverage["files"]["t2l/example.py"]["missing_lines"] = [9, 10]
    coverage["totals"]["covered_lines"] = 8
    report, failures = coverage_gate_report(
        coverage,
        {"t2l/example.py": set(range(1, 11))},
        _minimal_policy(),
    )
    assert report["diff_line"]["percent"] == 80.0
    assert any("below 90%" in failure for failure in failures)


def test_changed_lines_include_untracked_python_and_exclude_frozen_paths(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "gate@example.invalid"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Gate Test"], cwd=tmp_path, check=True)
    source = tmp_path / "t2l"
    (source / "mtl").mkdir(parents=True)
    (source / "tracked.py").write_text("old = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    (source / "tracked.py").write_text("old = 1\nnew = 2\n", encoding="utf-8")
    (source / "untracked.py").write_text("first = 1\nsecond = 2\n", encoding="utf-8")
    (source / "mtl/model.py").write_text("frozen = True\n", encoding="utf-8")

    changed = changed_python_lines(
        tmp_path,
        "HEAD",
        source_root="t2l",
        excluded_paths={"t2l/mtl/model.py"},
    )

    assert changed == {
        "t2l/tracked.py": {2},
        "t2l/untracked.py": {1, 2},
    }


def test_junit_gate_rejects_skips_and_cross_layer_evidence(tmp_path):
    policy = load_policy()
    valid = tmp_path / "valid.xml"
    _write_junit(valid, ["tests.unit.test_example", "tests.component.test_real"])
    report, failures = junit_gate_report(valid, "portable", policy)
    assert report["tests"] == 2
    assert failures == []

    invalid = tmp_path / "invalid.xml"
    _write_junit(
        invalid,
        ["tests.package.test_wheel", "tests.golden.test_oracle"],
        skipped={0},
    )
    report, failures = junit_gate_report(invalid, "package", policy)
    assert report["skipped"] == 1
    assert report["outside_layer"] == ["tests.golden.test_oracle::test_1"]
    assert any("skipped" in failure for failure in failures)
    assert any("another layer" in failure for failure in failures)


def test_junit_gate_recomputes_statistics_instead_of_trusting_suite_attributes(
    tmp_path,
):
    policy = load_policy()
    junit = tmp_path / "forged-totals.xml"
    root = ET.Element("testsuites", tests="999", failures="0")
    suite = ET.SubElement(
        root,
        "testsuite",
        tests="999",
        failures="0",
        skipped="0",
    )
    ET.SubElement(
        suite,
        "testcase",
        classname="tests.unit.test_example",
        name="test_real_case",
    )
    ET.ElementTree(root).write(junit, encoding="utf-8", xml_declaration=True)

    report, failures = junit_gate_report(junit, "portable", policy)

    assert failures == []
    assert report["tests"] == 1
    assert report["failures_or_errors"] == 0


def test_gate_scripts_are_executable_and_keep_layers_separate():
    runner = REPOSITORY_ROOT / "scripts/run_test_gate.sh"
    verifier = REPOSITORY_ROOT / "scripts/verify_quality_gates.py"
    canonical = REPOSITORY_ROOT / "scripts/run_canonical_legacy_v1_golden.sh"
    assert DEFAULT_POLICY == REPOSITORY_ROOT / "packaging/quality-gates.toml"
    assert runner.stat().st_mode & stat.S_IXUSR
    assert verifier.stat().st_mode & stat.S_IXUSR

    runner_text = runner.read_text(encoding="utf-8")
    assert "tests/unit tests/contract tests/component" in runner_text
    assert "tests/package -m package" in runner_text
    assert (
        'package_keyword="not test_pkg_013_pkg_014_pkg_015_cold_offline_sdist_build '
        'and not test_pkg_012_pkg_017_macos_cold_install_and_tags"' in runner_text
    )
    assert 'package_keyword="not test_pkg_019_linux_cold_install"' in runner_text
    assert "scripts/run_linux_package_gate.py" in runner_text
    assert "AI_AUTO_LRC_CANONICAL_EVIDENCE_DIR" in runner_text
    assert "--cov-branch" in runner_text
    assert "--base-ref" in runner_text
    assert "AI_AUTO_LRC_EVIDENCE_RUN_ID" in runner_text
    assert "--run-id" in runner_text

    canonical_text = canonical.read_text(encoding="utf-8")
    assert "tests/golden/test_legacy_v1_feature_golden.py" in canonical_text
    assert "--junitxml=/evidence/canonical.xml" in canonical_text


def test_portable_runner_forwards_capture_run_id_to_both_verifiers(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    invocation_log = tmp_path / "uv-invocations.txt"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_UV_LOG"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o700)
    environment = os.environ.copy()
    environment.update(
        {
            "AI_AUTO_LRC_EVIDENCE_RUN_ID": "capture-portable-001",
            "AI_AUTO_LRC_GATE_ARTIFACT_DIR": os.fspath(tmp_path / "artifacts"),
            "FAKE_UV_LOG": os.fspath(invocation_log),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
        }
    )

    result = subprocess.run(
        [os.fspath(REPOSITORY_ROOT / "scripts/run_test_gate.sh"), "portable", "HEAD"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    verifier_calls = [
        line
        for line in invocation_log.read_text(encoding="utf-8").splitlines()
        if "scripts/verify_quality_gates.py" in line
    ]
    assert len(verifier_calls) == 2
    assert all("--run-id capture-portable-001" in call for call in verifier_calls)


def test_package_runner_selects_linux_scope_and_invokes_sidecar_producer(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    invocation_log = tmp_path / "uv-invocations.txt"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_UV_LOG"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o700)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "AI_AUTO_LRC_EVIDENCE_RUN_ID": "package-run-001",
            "AI_AUTO_LRC_GATE_ARTIFACT_DIR": os.fspath(artifacts),
            "AI_AUTO_LRC_PACKAGE_IMAGE": f"python@sha256:{'1' * 64}",
            "AI_AUTO_LRC_PACKAGE_SCOPE": "linux-x86_64",
            "AI_AUTO_LRC_WHEELHOUSE": os.fspath(wheelhouse),
            "FAKE_UV_LOG": os.fspath(invocation_log),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
        }
    )

    result = subprocess.run(
        [os.fspath(REPOSITORY_ROOT / "scripts/run_test_gate.sh"), "package"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    invocations = invocation_log.read_text(encoding="utf-8").splitlines()
    assert len(invocations) == 3
    assert "tests/package -m package" in invocations[0]
    assert (
        "-k not test_pkg_013_pkg_014_pkg_015_cold_offline_sdist_build "
        "and not test_pkg_012_pkg_017_macos_cold_install_and_tags" in invocations[0]
    )
    assert "--layer package" in invocations[1]
    assert "--run-id package-run-001" in invocations[1]
    assert "scripts/run_linux_package_gate.py" in invocations[2]
    assert f"--wheelhouse {wheelhouse}" in invocations[2]
    assert "--run-id package-run-001" in invocations[2]
    assert f"--image python@sha256:{'1' * 64}" in invocations[2]


def test_verifier_cli_writes_machine_readable_failure_without_false_success(tmp_path):
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(
        json.dumps(_coverage_record(executed=(1,), missing=(2,), branch=False)),
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    environment = os.environ.copy()
    environment.pop("AI_AUTO_LRC_EVIDENCE_RUN_ID", None)
    result = subprocess.run(
        [
            os.fspath(Path(os.sys.executable)),
            os.fspath(GATE_SCRIPT),
            "coverage",
            "--coverage-json",
            os.fspath(coverage_path),
            "--base-ref",
            "HEAD",
            "--output",
            os.fspath(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert report["run_id"] is None
    assert report["input_coverage_sha256"] == _sha256(coverage_path)
    assert report["policy_sha256"] == _sha256(DEFAULT_POLICY)
    assert report["base_ref"] == "HEAD"
    assert "quality gate failed:" in result.stderr


def test_verifier_cli_binds_one_capture_run_to_junit_and_coverage(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_coverage_repo(repo)
    policy = tmp_path / "policy.toml"
    _write_gate_policy(policy)
    junit = tmp_path / "portable.xml"
    _write_junit(junit, ["tests.unit.test_example"])
    coverage = tmp_path / "coverage.json"
    coverage.write_text(json.dumps(_coverage_record()), encoding="utf-8")
    junit_output = tmp_path / "junit-gate.json"
    coverage_output = tmp_path / "coverage-gate.json"
    run_id = "portable-20260905-001"
    environment = os.environ.copy()
    environment["AI_AUTO_LRC_EVIDENCE_RUN_ID"] = run_id

    junit_result = subprocess.run(
        [
            os.fspath(Path(os.sys.executable)),
            os.fspath(GATE_SCRIPT),
            "--policy",
            os.fspath(policy),
            "junit",
            "--layer",
            "portable",
            "--junit-xml",
            os.fspath(junit),
            "--run-id",
            run_id,
            "--output",
            os.fspath(junit_output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    coverage_result = subprocess.run(
        [
            os.fspath(Path(os.sys.executable)),
            os.fspath(GATE_SCRIPT),
            "--policy",
            os.fspath(policy),
            "coverage",
            "--coverage-json",
            os.fspath(coverage),
            "--base-ref",
            "HEAD",
            "--repo-root",
            os.fspath(repo),
            "--run-id",
            run_id,
            "--output",
            os.fspath(coverage_output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert junit_result.returncode == 0, junit_result.stderr
    assert coverage_result.returncode == 0, coverage_result.stderr
    junit_report = json.loads(junit_output.read_text(encoding="utf-8"))
    coverage_report = json.loads(coverage_output.read_text(encoding="utf-8"))
    assert junit_report["run_id"] == coverage_report["run_id"] == run_id
    assert junit_report["input_junit_sha256"] == _sha256(junit)
    assert coverage_report["input_coverage_sha256"] == _sha256(coverage)
    assert junit_report["policy_sha256"] == coverage_report["policy_sha256"]
    assert coverage_report["base_ref"] == "HEAD"
    assert junit_report["tests"] == 1


def test_verifier_cli_junit_without_capture_run_uses_legacy_null(tmp_path):
    junit = tmp_path / "portable.xml"
    _write_junit(junit, ["tests.unit.test_example"])
    output = tmp_path / "gate.json"
    environment = os.environ.copy()
    environment.pop("AI_AUTO_LRC_EVIDENCE_RUN_ID", None)

    result = subprocess.run(
        [
            os.fspath(Path(os.sys.executable)),
            os.fspath(GATE_SCRIPT),
            "junit",
            "--layer",
            "portable",
            "--junit-xml",
            os.fspath(junit),
            "--output",
            os.fspath(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["run_id"] is None
    assert report["input_junit_sha256"] == _sha256(junit)
    assert report["policy_sha256"] == _sha256(DEFAULT_POLICY)


@pytest.mark.parametrize("source", ("environment", "cli"))
def test_verifier_cli_accepts_run_id_from_environment_or_cli(tmp_path, source):
    junit = tmp_path / "portable.xml"
    _write_junit(junit, ["tests.unit.test_example"])
    output = tmp_path / "gate.json"
    environment = os.environ.copy()
    environment.pop("AI_AUTO_LRC_EVIDENCE_RUN_ID", None)
    arguments = [
        os.fspath(Path(os.sys.executable)),
        os.fspath(GATE_SCRIPT),
        "junit",
        "--layer",
        "portable",
        "--junit-xml",
        os.fspath(junit),
        "--output",
        os.fspath(output),
    ]
    if source == "environment":
        environment["AI_AUTO_LRC_EVIDENCE_RUN_ID"] = "capture-run"
    else:
        arguments.extend(("--run-id", "capture-run"))

    result = subprocess.run(
        arguments,
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["run_id"] == "capture-run"


def test_verifier_cli_rejects_conflicting_environment_and_cli_run_ids(tmp_path):
    junit = tmp_path / "portable.xml"
    _write_junit(junit, ["tests.unit.test_example"])
    output = tmp_path / "gate.json"
    environment = os.environ.copy()
    environment["AI_AUTO_LRC_EVIDENCE_RUN_ID"] = "capture-run"

    result = subprocess.run(
        [
            os.fspath(Path(os.sys.executable)),
            os.fspath(GATE_SCRIPT),
            "junit",
            "--layer",
            "portable",
            "--junit-xml",
            os.fspath(junit),
            "--run-id",
            "forged-run",
            "--output",
            os.fspath(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "does not match" in result.stderr
    assert not output.exists()
