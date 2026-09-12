"""Reusable artifact and schema oracles for the S18 B3f-R2 contracts.

This module intentionally defines no ``test_*`` nodes.  The owning R2 tests call
these helpers so their existing node count remains stable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from scripts import verify_security_coverage as verifier
from tests.contract import test_security_coverage_gate as gate_contract

_TOOLCHAIN_FAILURE = ["EVIDENCE_TOOLCHAIN_BINDING_INVALID"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: object) -> None:
    gate_contract._write_json(path, value)


def _different_digest(value: object) -> str:
    candidate = "0" * 64
    return "1" * 64 if value == candidate else candidate


def _rebind_artifact(bundle: dict[str, Path], name: str) -> None:
    manifest = _read_json(bundle["run_manifest"])
    hashes = manifest["artifact_hashes"]
    assert isinstance(hashes, dict)
    hashes[f"{name}_sha256"] = _sha256(bundle[name])
    _write_json(bundle["run_manifest"], manifest)


def _assert_baseline_passes(bundle: dict[str, Path]) -> dict[str, object]:
    report, failures = gate_contract._verify(bundle)
    assert failures == []
    assert report["passed"] is True
    assert report["failures"] == []
    return report


def _assert_toolchain_only(bundle: dict[str, Path]) -> None:
    report, failures = gate_contract._verify(bundle)
    assert failures == _TOOLCHAIN_FAILURE
    assert report["passed"] is False
    assert report["failures"] == _TOOLCHAIN_FAILURE


def _assert_gate_failure(operation: Callable[[], object], expected: str) -> None:
    try:
        operation()
    except verifier.GateFailure as exc:
        assert str(exc) == expected
    else:
        raise AssertionError(f"expected GateFailure: {expected}")


def _replace_toml_key(source: str, section: str | None, key: str, replacement: str) -> str:
    lines = source.splitlines(keepends=True)
    current_section: str | None = None
    matches: list[int] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1]
        elif current_section == section and line.startswith(f"{key} = "):
            matches.append(index)
    assert len(matches) == 1, (section, key)
    lines[matches[0]] = replacement
    return "".join(lines)


def _toml_key_line(source: str, section: str | None, key: str) -> str:
    lines = source.splitlines(keepends=True)
    current_section: str | None = None
    matches: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1]
        elif current_section == section and line.startswith(f"{key} = "):
            matches.append(line)
    assert len(matches) == 1, (section, key)
    return matches[0]


def _remove_toml_section(source: str, section: str) -> str:
    lines = source.splitlines(keepends=True)
    header = f"[{section}]"
    starts = [index for index, line in enumerate(lines) if line.strip() == header]
    assert len(starts) == 1, section
    start = starts[0]
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].strip().startswith("[")
            and lines[index].strip().endswith("]")
        ),
        len(lines),
    )
    del lines[start:end]
    return "".join(lines)


def _toml_unknown_key(source: str, section: str, anchor: str) -> str:
    line = _toml_key_line(source, section, anchor)
    return _replace_toml_key(
        source,
        section,
        anchor,
        line + 'unexpected_contract_key = "not-authorized"\n',
    )


def _toml_duplicate_key(source: str, section: str | None, key: str) -> str:
    line = _toml_key_line(source, section, key)
    return _replace_toml_key(source, section, key, line + line)


def _duplicate_json_line(path: Path, key: str) -> None:
    lines = path.read_bytes().splitlines(keepends=True)
    prefix = f'  "{key}": '.encode()
    matches = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    assert len(matches) == 1
    lines.insert(matches[0], lines[matches[0]])
    path.write_bytes(b"".join(lines))


def assert_manifest_cross_bindings(tmp_path: Path) -> None:
    """Exercise full verification for every non-identity runtime reference."""

    tmp_path.mkdir()
    _assert_baseline_passes(gate_contract._make_bundle(tmp_path / "manifest-baseline"))

    raw_bundle = gate_contract._make_bundle(tmp_path / "manifest-raw-artifact")
    raw_bundle["plugin_identity"].write_bytes(
        raw_bundle["plugin_identity"].read_bytes() + b"\n"
    )
    environment = _read_json(raw_bundle["environment"])
    runtime_reference = environment["runtime_identity"]
    assert isinstance(runtime_reference, dict)
    runtime_reference["artifact_sha256"] = _sha256(raw_bundle["plugin_identity"])
    _write_json(raw_bundle["environment"], environment)
    _rebind_artifact(raw_bundle, "environment")
    _assert_toolchain_only(raw_bundle)

    manifest_semantic_bundle = gate_contract._make_bundle(
        tmp_path / "manifest-semantic-reference"
    )
    manifest = _read_json(manifest_semantic_bundle["run_manifest"])
    manifest["semantic_runtime_sha256"] = _different_digest(
        manifest["semantic_runtime_sha256"]
    )
    _write_json(manifest_semantic_bundle["run_manifest"], manifest)
    _assert_toolchain_only(manifest_semantic_bundle)

    environment_semantic_bundle = gate_contract._make_bundle(
        tmp_path / "environment-semantic-reference"
    )
    environment = _read_json(environment_semantic_bundle["environment"])
    runtime_reference = environment["runtime_identity"]
    assert isinstance(runtime_reference, dict)
    runtime_reference["semantic_runtime_sha256"] = _different_digest(
        runtime_reference["semantic_runtime_sha256"]
    )
    _write_json(environment_semantic_bundle["environment"], environment)
    _rebind_artifact(environment_semantic_bundle, "environment")
    _assert_toolchain_only(environment_semantic_bundle)

    environment_raw_bundle = gate_contract._make_bundle(
        tmp_path / "environment-raw-reference"
    )
    environment = _read_json(environment_raw_bundle["environment"])
    runtime_reference = environment["runtime_identity"]
    assert isinstance(runtime_reference, dict)
    runtime_reference["artifact_sha256"] = _different_digest(
        runtime_reference["artifact_sha256"]
    )
    _write_json(environment_raw_bundle["environment"], environment)
    _rebind_artifact(environment_raw_bundle, "environment")
    _assert_toolchain_only(environment_raw_bundle)


def assert_non_identity_artifact_versions(tmp_path: Path) -> None:
    """Reject old, float-equivalent, boolean, and boolean-integer schemas."""

    tmp_path.mkdir()
    _assert_baseline_passes(gate_contract._make_bundle(tmp_path / "version-baseline"))
    cases = (
        ("environment", "schema_version", 4, "environment.schema_version must be 5"),
        ("environment", "schema_version", 5.0, "environment.schema_version must be 5"),
        ("environment", "schema_version", True, "environment.schema_version must be 5"),
        ("environment", "attempt", True, "environment.attempt must be an integer >= 1"),
        ("command", "schema_version", 3, "command.schema_version must be 4"),
        ("command", "schema_version", 4.0, "command.schema_version must be 4"),
        ("command", "schema_version", True, "command.schema_version must be 4"),
        ("command", "attempt", True, "command.attempt must be an integer >= 1"),
        ("run_manifest", "schema_version", 4, "run_manifest.schema_version must be 5"),
        ("run_manifest", "schema_version", 5.0, "run_manifest.schema_version must be 5"),
        ("run_manifest", "schema_version", True, "run_manifest.schema_version must be 5"),
        (
            "run_manifest",
            "attempt",
            True,
            "run_manifest.attempt must be an integer >= 1",
        ),
    )
    for index, (artifact, field, value, expected) in enumerate(cases):
        bundle = gate_contract._make_bundle(tmp_path / f"version-{index:02d}-{artifact}")
        document = _read_json(bundle[artifact])
        document[field] = value
        _write_json(bundle[artifact], document)
        if artifact != "run_manifest":
            _rebind_artifact(bundle, artifact)
        _assert_gate_failure(lambda bundle=bundle: gate_contract._verify(bundle), expected)

    duplicate_cases = (
        ("environment", "environment contains duplicate keys"),
        ("command", "command contains duplicate keys"),
        ("run_manifest", "run_manifest contains duplicate keys"),
    )
    for artifact, expected in duplicate_cases:
        bundle = gate_contract._make_bundle(tmp_path / f"duplicate-{artifact}")
        _duplicate_json_line(bundle[artifact], "attempt")
        if artifact != "run_manifest":
            _rebind_artifact(bundle, artifact)
        _assert_gate_failure(lambda bundle=bundle: gate_contract._verify(bundle), expected)


def assert_policy_and_gate_exact_schema(tmp_path: Path) -> None:
    """Dynamically reject policy drift and assert the complete Gate v5 shape."""

    tmp_path.mkdir()
    policy = verifier.load_policy()
    assert policy["schema_version"] == 3
    policy_source = gate_contract.DEFAULT_POLICY.read_text(encoding="utf-8")
    policy_cases = (
        (
            "top-unknown",
            _replace_toml_key(
                policy_source,
                None,
                "schema_version",
                "schema_version = 3\nunexpected_contract_key = true\n",
            ),
            "policy has an invalid shape",
        ),
        (
            "top-missing",
            _replace_toml_key(policy_source, None, "schema_version", ""),
            "policy has an invalid shape",
        ),
        (
            "top-duplicate",
            _toml_duplicate_key(policy_source, None, "schema_version"),
            "security coverage policy cannot be parsed",
        ),
        (
            "top-current-float",
            _replace_toml_key(policy_source, None, "schema_version", "schema_version = 3.0\n"),
            "policy.schema_version must be 3",
        ),
        (
            "top-bool",
            _replace_toml_key(policy_source, None, "schema_version", "schema_version = true\n"),
            "policy.schema_version must be 3",
        ),
        (
            "thresholds-unknown",
            _toml_unknown_key(policy_source, "thresholds", "statement_line_percent"),
            "policy.thresholds has an invalid shape",
        ),
        (
            "thresholds-missing",
            _replace_toml_key(policy_source, "thresholds", "statement_line_percent", ""),
            "policy.thresholds has an invalid shape",
        ),
        (
            "thresholds-type",
            _replace_toml_key(
                policy_source,
                "thresholds",
                "statement_line_percent",
                'statement_line_percent = "80"\n',
            ),
            "policy.thresholds.statement_line_percent must be an integer >= 0",
        ),
        (
            "thresholds-duplicate",
            _toml_duplicate_key(policy_source, "thresholds", "statement_line_percent"),
            "security coverage policy cannot be parsed",
        ),
        (
            "limits-unknown",
            _toml_unknown_key(policy_source, "limits", "coverage_bytes"),
            "policy.limits has an invalid shape",
        ),
        (
            "limits-missing",
            _replace_toml_key(policy_source, "limits", "coverage_bytes", ""),
            "policy.limits has an invalid shape",
        ),
        (
            "limits-type",
            _replace_toml_key(
                policy_source, "limits", "coverage_bytes", 'coverage_bytes = "8388608"\n'
            ),
            "policy.limits.coverage_bytes must be an integer >= 1",
        ),
        (
            "limits-duplicate",
            _toml_duplicate_key(policy_source, "limits", "coverage_bytes"),
            "security coverage policy cannot be parsed",
        ),
        (
            "scripts-unknown-target",
            policy_source
            + '\n[scripts.unexpected]\nmodule = "x"\npath = "x.py"\ntest_file = "x.py"\n',
            "policy.scripts must contain only capture and retention",
        ),
        (
            "scripts-missing-target",
            _remove_toml_section(policy_source, "scripts.retention"),
            "policy.scripts must contain only capture and retention",
        ),
        (
            "scripts-type",
            _replace_toml_key(
                policy_source, "scripts.capture", "module", "module = 7\n"
            ),
            "policy.scripts.capture.module must be a nonempty printable string",
        ),
        (
            "scripts-duplicate",
            _toml_duplicate_key(policy_source, "scripts.capture", "module"),
            "security coverage policy cannot be parsed",
        ),
        (
            "runners-unknown-target",
            policy_source
            + '\n[runners.unexpected]\nsystem = "Other"\nmachines = ["other"]\n'
            'python_implementation = "CPython"\npython_major_minor = "3.11"\n',
            "policy.runners must contain only macos and linux",
        ),
        (
            "runners-missing-target",
            _remove_toml_section(policy_source, "runners.linux"),
            "policy.runners must contain only macos and linux",
        ),
        (
            "runners-type",
            _replace_toml_key(
                policy_source, "runners.macos", "machines", 'machines = "arm64"\n'
            ),
            "policy.runners.macos.machines is invalid",
        ),
        (
            "runners-duplicate",
            _toml_duplicate_key(policy_source, "runners.macos", "machines"),
            "security coverage policy cannot be parsed",
        ),
        (
            "runtime-unknown",
            _toml_unknown_key(policy_source, "runtime", "python_flags"),
            "policy.runtime has an invalid shape",
        ),
        (
            "runtime-missing",
            _replace_toml_key(policy_source, "runtime", "python_flags", ""),
            "policy.runtime has an invalid shape",
        ),
        (
            "runtime-type",
            _replace_toml_key(
                policy_source, "runtime", "python_flags", 'python_flags = "-I -S -B"\n'
            ),
            "policy.runtime is invalid",
        ),
        (
            "runtime-duplicate",
            _toml_duplicate_key(policy_source, "runtime", "python_flags"),
            "security coverage policy cannot be parsed",
        ),
        (
            "runtime-named-distributions-value",
            _replace_toml_key(
                policy_source,
                "runtime",
                "named_distributions",
                'named_distributions = ["coverage", "pluggy", "pytest"]\n',
            ),
            "policy.runtime is invalid",
        ),
        (
            "runtime-uv-flags-value",
            _replace_toml_key(
                policy_source,
                "runtime",
                "uv_run_flags",
                'uv_run_flags = ["--frozen", "--offline", "--no-sync"]\n',
            ),
            "policy.runtime is invalid",
        ),
        (
            "runtime-python-flags-value",
            _replace_toml_key(
                policy_source,
                "runtime",
                "python_flags",
                'python_flags = ["-S", "-I", "-B"]\n',
            ),
            "policy.runtime is invalid",
        ),
        (
            "required-entries-unknown",
            _toml_unknown_key(
                policy_source, "runtime.required_entries", "coverage"
            ),
            "policy.runtime is invalid",
        ),
        (
            "required-entries-missing",
            _replace_toml_key(
                policy_source, "runtime.required_entries", "coverage", ""
            ),
            "policy.runtime is invalid",
        ),
        (
            "required-entries-type",
            _replace_toml_key(
                policy_source,
                "runtime.required_entries",
                "coverage",
                'coverage = "coverage/__init__.py"\n',
            ),
            "policy.runtime is invalid",
        ),
        (
            "required-entries-duplicate",
            _toml_duplicate_key(policy_source, "runtime.required_entries", "coverage"),
            "security coverage policy cannot be parsed",
        ),
        (
            "required-entries-value",
            _replace_toml_key(
                policy_source,
                "runtime.required_entries",
                "coverage",
                'coverage = ["coverage/other.py"]\n',
            ),
            "policy.runtime is invalid",
        ),
        (
            "required-dependencies-unknown",
            _toml_unknown_key(
                policy_source, "runtime.required_dependencies", "pytest"
            ),
            "policy.runtime is invalid",
        ),
        (
            "required-dependencies-missing",
            _replace_toml_key(
                policy_source, "runtime.required_dependencies", "pytest", ""
            ),
            "policy.runtime is invalid",
        ),
        (
            "required-dependencies-type",
            _replace_toml_key(
                policy_source,
                "runtime.required_dependencies",
                "pytest",
                'pytest = "pluggy"\n',
            ),
            "policy.runtime is invalid",
        ),
        (
            "required-dependencies-duplicate",
            _toml_duplicate_key(
                policy_source, "runtime.required_dependencies", "pytest"
            ),
            "security coverage policy cannot be parsed",
        ),
        (
            "required-dependencies-value",
            _replace_toml_key(
                policy_source,
                "runtime.required_dependencies",
                "pytest-cov",
                'pytest-cov = ["coverage", "pytest"]\n',
            ),
            "policy.runtime is invalid",
        ),
    )
    for name, content, expected in policy_cases:
        path = tmp_path / f"policy-{name}.toml"
        path.write_text(content, encoding="utf-8")
        _assert_gate_failure(lambda path=path: verifier.load_policy(path), expected)

    report = _assert_baseline_passes(
        gate_contract._make_bundle(tmp_path / "gate-v5-baseline")
    )
    assert set(report) == {
        "schema_version",
        "gate",
        "target",
        "run_id",
        "runner",
        "attempt",
        "coverage",
        "junit",
        "pytest_events",
        "runtime_identity",
        "capabilities",
        "artifact_hashes",
        "passed",
        "failures",
    }
    assert report["schema_version"] == 5
    assert report["gate"] == "security-coverage"

    coverage = report["coverage"]
    assert isinstance(coverage, dict)
    assert set(coverage) == {
        "combined_percent",
        "statement_line_percent",
        "branch_percent",
        "counts",
        "critical_targets",
    }
    assert set(coverage["counts"]) == {
        "covered_lines",
        "statements",
        "covered_branches",
        "branches",
    }
    critical_targets = coverage["critical_targets"]
    assert isinstance(critical_targets, list) and critical_targets
    assert all(
        set(record)
        == {"symbol", "present", "line_percent", "branch_percent", "branches", "passed"}
        for record in critical_targets
    )

    junit = report["junit"]
    assert isinstance(junit, dict)
    assert set(junit) == {
        "testcases",
        "passed_testcases",
        "skipped_testcases",
        "failed_testcases",
        "required_total",
        "required_passed",
        "required_tests",
    }
    required_tests = junit["required_tests"]
    assert isinstance(required_tests, list) and required_tests
    assert all(
        set(record) == {"nodeid", "status", "capability", "semantic"}
        for record in required_tests
    )

    pytest_events = report["pytest_events"]
    assert isinstance(pytest_events, dict)
    assert set(pytest_events) == {"testcases", "xfail_marked", "wasxfail"}

    runtime = report["runtime_identity"]
    assert isinstance(runtime, dict)
    assert set(runtime) == {
        "status",
        "artifact_sha256",
        "schema_version",
        "provenance",
        "semantic_runtime_sha256",
        "runtime",
        "uv",
        "uv_lock_sha256",
        "distributions",
        "plugins",
    }
    assert runtime["status"] == "valid"
    assert runtime["schema_version"] == 2
    runtime_layout = runtime["runtime"]
    assert isinstance(runtime_layout, dict)
    assert set(runtime_layout) == {
        "implementation",
        "version",
        "system",
        "machine",
        "executable_sha256",
        "pyvenv_cfg_sha256",
        "isolated",
        "no_site",
        "dont_write_bytecode",
    }
    uv = runtime["uv"]
    assert isinstance(uv, dict)
    assert set(uv) == {"version", "sha256"}

    distributions = runtime["distributions"]
    assert isinstance(distributions, dict)
    expected_entries = policy["runtime"]["required_entries"]
    assert isinstance(expected_entries, dict)
    assert set(distributions) == set(expected_entries) == {
        "coverage",
        "pluggy",
        "pytest",
        "pytest-cov",
    }
    for name, distribution in distributions.items():
        assert isinstance(distribution, dict)
        assert set(distribution) == {
            "version",
            "metadata_sha256",
            "record_sha256",
            "lock_package_sha256",
            "required_entries",
        }
        entries = distribution["required_entries"]
        assert isinstance(entries, dict)
        assert set(entries) == set(expected_entries[name])
        assert all(set(entry) == {"sha256", "size"} for entry in entries.values())

    plugins = runtime["plugins"]
    assert isinstance(plugins, dict)
    assert set(plugins) == {"pytest_cov.plugin", "scripts.pytest_security_events"}
    assert all(
        set(plugin) == {"sha256", "distribution", "entry"}
        for plugin in plugins.values()
    )

    artifact_hashes = report["artifact_hashes"]
    assert isinstance(artifact_hashes, dict)
    assert set(artifact_hashes) == {
        "source_sha256",
        "test_sha256",
        "policy_sha256",
        "manifest_sha256",
        "runner_sha256",
        "verifier_sha256",
        "bootstrap_sha256",
        "pytest_config_sha256",
        "pytest_events_plugin_sha256",
        "uv_lock_sha256",
        "coverage_sha256",
        "junit_sha256",
        "pytest_events_sha256",
        "plugin_identity_sha256",
        "environment_sha256",
        "command_sha256",
    }
