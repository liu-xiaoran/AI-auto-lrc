#!/usr/bin/env python3
"""Read-only verifier for isolated S18 security coverage evidence."""

from __future__ import annotations

import argparse
import ast
import base64
import csv
import email.parser
import hashlib
import io
import json
import os
import re
import stat
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from email import policy as email_policy
from email.errors import MessageDefect
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - project qualification uses 3.11
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = REPOSITORY_ROOT / "packaging/security-coverage-policy.toml"
DEFAULT_MANIFEST = REPOSITORY_ROOT / "packaging/security-coverage-manifest.json"
RUNNER_PATH = REPOSITORY_ROOT / "scripts/run_security_coverage.sh"
VERIFIER_PATH = REPOSITORY_ROOT / "scripts/verify_security_coverage.py"
PYTEST_CONFIG_PATH = REPOSITORY_ROOT / "pyproject.toml"
PYTEST_EVENTS_PLUGIN_PATH = REPOSITORY_ROOT / "scripts/pytest_security_events.py"
BOOTSTRAP_PATH = REPOSITORY_ROOT / "scripts/security_pytest_bootstrap.py"
UV_LOCK_PATH = REPOSITORY_ROOT / "uv.lock"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[A-Za-z0-9._+-]*)?$")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$")
RUNTIME_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
RUNTIME_DIST_INFO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.dist-info$")
RUNTIME_SHA256_URLSAFE = re.compile(r"^[A-Za-z0-9_-]{43}$")
RUNTIME_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)$")
RUNTIME_PEP503_RUN = re.compile(r"[-_.]+")
RUNTIME_PYTHON_VERSION = re.compile(r"^([0-9]+)\.([0-9]+)(?:\.([0-9]+))?$")
RUNTIME_PYVENV_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
RUNTIME_DISTRIBUTIONS = ("coverage", "pluggy", "pytest", "pytest-cov")
RUNTIME_PLUGINS = ("pytest_cov.plugin", "scripts.pytest_security_events")
RUNTIME_REQUIRED_ENTRIES = {
    "coverage": ("coverage/__init__.py",),
    "pluggy": ("pluggy/__init__.py",),
    "pytest": ("pytest/__init__.py",),
    "pytest-cov": ("pytest_cov/__init__.py", "pytest_cov/plugin.py"),
}
RUNTIME_REQUIRED_DEPENDENCIES = {
    "coverage": (),
    "pluggy": (),
    "pytest": ("pluggy",),
    "pytest-cov": ("coverage", "pluggy", "pytest"),
}
EXPECTED_CATEGORIES = {
    "S18-CAP-01": "anchored-sealed-read",
    "S18-CAP-02": "stable-external-read",
    "S18-CAP-03": "source-observation",
    "S18-CAP-04": "capture-isolation",
    "S18-CAP-05": "subprocess-signal",
    "S18-CAP-06": "portable-binding",
    "S18-CAP-07": "package-closure",
    "S18-CAP-08": "canonical-closure",
    "S18-CAP-09": "receipt-finalize-verify",
    "S18-CAP-10": "config-trust-anchor",
    "S18-CAP-11": "bounded-scan",
    "S18-CAP-12": "no-replace-publication",
    "S18-CAP-13": "locking-concurrency",
    "S18-CAP-14": "crash-ledger-recovery",
    "S18-CAP-15": "cli-redaction",
    "S18-CAP-16": "qualification-provenance",
    "S18-CAP-17": "capture-closure-budget",
}


class GateFailure(RuntimeError):
    """Raised for malformed, ambiguous, or unsafe qualification input."""


class _InvalidJUnitNodeId(ValueError):
    """Raised when a JUnit testcase cannot name the frozen target exactly."""


def _canonical_junit_name(name: str) -> bool:
    if any(ord(char) < 32 or ord(char) == 127 for char in name) or "::" in name:
        return False
    parameter_start = name.find("[")
    function_name = name if parameter_start == -1 else name[:parameter_start]
    if re.fullmatch(r"test_[A-Za-z0-9_]+", function_name) is None:
        return False
    if parameter_start == -1:
        return "]" not in name
    parameter = name[parameter_start:]
    depth = 0
    for index, char in enumerate(parameter):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if depth < 0 or (depth == 0 and index != len(parameter) - 1):
            return False
    return depth == 0 and parameter.endswith("]")


def _exact(value: object, keys: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise GateFailure(f"{field} has an invalid shape")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GateFailure(f"{field} must be an integer >= {minimum}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateFailure(f"{field} must be a number")
    result = float(value)
    if not 0.0 <= result <= 100.0:
        raise GateFailure(f"{field} must be between 0 and 100")
    return result


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        raise GateFailure(f"{field} must be a nonempty printable string")
    return value


def _relative_path(value: object, field: str) -> str:
    text = _nonempty(value, field)
    path = PurePosixPath(text)
    if path.is_absolute() or text != path.as_posix() or ".." in path.parts:
        raise GateFailure(f"{field} must be a canonical repository-relative path")
    return text


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        stat.S_IFMT(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _read_bounded(path: Path, limit: int, field: str) -> bytes:
    """Read one owned, single-link regular file without following its leaf."""

    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1:
            raise GateFailure(f"{field} is not an owned single-link regular file")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if _identity(before) != _identity(opened):
                raise GateFailure(f"{field} identity changed before open")
            chunks: list[bytes] = []
            length = 0
            while True:
                chunk = os.read(descriptor, min(65536, limit + 1 - length))
                if not chunk:
                    break
                chunks.append(chunk)
                length += len(chunk)
                if length > limit:
                    raise GateFailure(f"{field} exceeds its byte limit")
            after = os.fstat(descriptor)
            if _identity(opened) != _identity(after):
                raise GateFailure(f"{field} identity changed during read")
        finally:
            os.close(descriptor)
    except GateFailure:
        raise
    except (OSError, ValueError) as exc:
        raise GateFailure(f"{field} cannot be read safely") from exc
    return b"".join(chunks)


def _read_runtime_identity_artifact(path: Path, limit: int) -> tuple[bytes | None, bool]:
    """Read the owned sidecar once and bind its mode to the same open file."""

    raw: bytes | None = None
    mode_valid = False
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1:
            return None, False
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            opened = os.fstat(descriptor)
            if _identity(before) != _identity(opened) or before.st_mode != opened.st_mode:
                return None, False
            chunks: list[bytes] = []
            length = 0
            while True:
                chunk = os.read(descriptor, min(65536, limit + 1 - length))
                if not chunk:
                    break
                chunks.append(chunk)
                length += len(chunk)
                if length > limit:
                    return None, False
            after = os.fstat(descriptor)
            raw = b"".join(chunks)
            mode_valid = (
                _identity(opened) == _identity(after)
                and opened.st_mode == after.st_mode
                and stat.S_IMODE(opened.st_mode) == 0o600
            )
        finally:
            os.close(descriptor)
        try:
            final = path.lstat()
            if _identity(before) != _identity(final) or before.st_mode != final.st_mode:
                mode_valid = False
        except OSError:
            mode_valid = False
    except (OSError, ValueError):
        return None, False
    return raw, mode_valid


def _strict_json(content: bytes, field: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise GateFailure(f"{field} contains duplicate keys")
            result[key] = value
        return result

    def constant(_value: str) -> None:
        raise GateFailure(f"{field} contains a non-finite number")

    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=constant,
        )
    except GateFailure:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateFailure(f"{field} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise GateFailure(f"{field} must be a JSON object")
    return value


def _parse_policy(content: bytes) -> dict[str, Any]:
    try:
        policy = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise GateFailure("security coverage policy cannot be parsed") from exc
    policy = _exact(
        policy,
        {"schema_version", "thresholds", "limits", "scripts", "runners", "runtime"},
        "policy",
    )
    if type(policy["schema_version"]) is not int or policy["schema_version"] != 3:
        raise GateFailure("policy.schema_version must be 3")
    thresholds = _exact(
        policy["thresholds"],
        {
            "coverage_combined_percent",
            "statement_line_percent",
            "branch_percent",
            "critical_line_percent",
            "critical_branch_percent",
            "zero_required_skip",
        },
        "policy.thresholds",
    )
    for key in (
        "coverage_combined_percent",
        "statement_line_percent",
        "branch_percent",
        "critical_line_percent",
        "critical_branch_percent",
    ):
        number = _integer(thresholds[key], f"policy.thresholds.{key}")
        if number > 100:
            raise GateFailure(f"policy.thresholds.{key} must not exceed 100")
    if thresholds["zero_required_skip"] is not True:
        raise GateFailure("policy.thresholds.zero_required_skip must be true")
    limits = _exact(
        policy["limits"],
        {
            "coverage_bytes",
            "junit_bytes",
            "pytest_events_bytes",
            "pytest_events_nodeid_bytes",
            "plugin_identity_bytes",
            "runtime_metadata_bytes",
            "runtime_record_bytes",
            "runtime_required_entry_bytes",
            "runtime_pyvenv_cfg_bytes",
            "environment_bytes",
            "command_bytes",
            "run_manifest_bytes",
            "capabilities",
            "targets_per_capability",
            "symbols_per_target",
            "requirements_per_target",
            "testcases",
        },
        "policy.limits",
    )
    for key, value in limits.items():
        _integer(value, f"policy.limits.{key}", minimum=1)
    frozen_pytest_events_limits = {
        "testcases": 4096,
        "pytest_events_nodeid_bytes": 4096,
        "pytest_events_bytes": 8388608,
    }
    for key, expected in frozen_pytest_events_limits.items():
        if limits[key] != expected:
            raise GateFailure(f"policy.limits.{key} must be {expected}")
    frozen_runtime_limits = {
        "plugin_identity_bytes": 4 * 1024 * 1024,
        "runtime_metadata_bytes": 256 * 1024,
        "runtime_record_bytes": 256 * 1024,
        "runtime_required_entry_bytes": 1024 * 1024,
        "runtime_pyvenv_cfg_bytes": 16 * 1024,
    }
    for key, expected in frozen_runtime_limits.items():
        if limits[key] != expected:
            raise GateFailure(f"policy.limits.{key} must be {expected}")
    scripts = policy["scripts"]
    if not isinstance(scripts, dict) or set(scripts) != {"capture", "retention"}:
        raise GateFailure("policy.scripts must contain only capture and retention")
    expected_scripts = {
        "capture": (
            "scripts.capture_test_gate",
            "scripts/capture_test_gate.py",
            "tests/contract/test_evidence_capture.py",
        ),
        "retention": (
            "scripts.manage_evidence_retention",
            "scripts/manage_evidence_retention.py",
            "tests/contract/test_evidence_retention.py",
        ),
    }
    for name, expected in expected_scripts.items():
        record = _exact(scripts[name], {"module", "path", "test_file"}, f"policy.scripts.{name}")
        actual = (
            _nonempty(record["module"], f"policy.scripts.{name}.module"),
            _relative_path(record["path"], f"policy.scripts.{name}.path"),
            _relative_path(record["test_file"], f"policy.scripts.{name}.test_file"),
        )
        if actual != expected:
            raise GateFailure(f"policy.scripts.{name} does not name the frozen target")
    runners = policy["runners"]
    if not isinstance(runners, dict) or set(runners) != {"macos", "linux"}:
        raise GateFailure("policy.runners must contain only macos and linux")
    expected_systems = {"macos": "Darwin", "linux": "Linux"}
    for name, value in runners.items():
        record = _exact(
            value,
            {"system", "machines", "python_implementation", "python_major_minor"},
            f"policy.runners.{name}",
        )
        if record["system"] != expected_systems[name]:
            raise GateFailure(f"policy.runners.{name}.system is invalid")
        machines = record["machines"]
        if (
            not isinstance(machines, list)
            or not machines
            or any(not isinstance(item, str) or not item for item in machines)
            or len(machines) != len(set(machines))
        ):
            raise GateFailure(f"policy.runners.{name}.machines is invalid")
        if record["python_implementation"] != "CPython" or record["python_major_minor"] != "3.11":
            raise GateFailure(f"policy.runners.{name} Python contract is invalid")
    runtime = _exact(
        policy["runtime"],
        {
            "provenance",
            "named_distributions",
            "python_flags",
            "uv_run_flags",
            "required_entries",
            "required_dependencies",
        },
        "policy.runtime",
    )
    expected_runtime = {
        "provenance": "installed-record-consistent",
        "named_distributions": ["coverage", "pluggy", "pytest", "pytest-cov"],
        "python_flags": ["-I", "-S", "-B"],
        "uv_run_flags": ["--offline", "--frozen", "--no-sync"],
        "required_entries": {
            "coverage": ["coverage/__init__.py"],
            "pluggy": ["pluggy/__init__.py"],
            "pytest": ["pytest/__init__.py"],
            "pytest-cov": ["pytest_cov/__init__.py", "pytest_cov/plugin.py"],
        },
        "required_dependencies": {
            "pytest": ["pluggy"],
            "pytest-cov": ["coverage", "pluggy", "pytest"],
        },
    }
    if runtime != expected_runtime:
        raise GateFailure("policy.runtime is invalid")
    return policy


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    return _parse_policy(_read_bounded(path, 1024 * 1024, "policy"))


class _SymbolCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.symbols: set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.symbols.add(".".join([*self.stack, node.name]))

    visit_AsyncFunctionDef = visit_FunctionDef


def _source_symbols(content: bytes, *, filename: str) -> set[str]:
    try:
        tree = ast.parse(content.decode("utf-8"), filename=filename)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise GateFailure("declared source cannot be inspected") from exc
    collector = _SymbolCollector()
    collector.visit(tree)
    return collector.symbols


def _frozen_source_material(
    policy: dict[str, Any],
    *,
    binding_failures: list[str] | None = None,
) -> tuple[dict[str, bytes], dict[str, set[str]]]:
    contents: dict[str, bytes] = {}
    symbols: dict[str, set[str]] = {}
    for name, record in policy["scripts"].items():
        path = REPOSITORY_ROOT / record["path"]
        frozen = _read_bounded(path, 16 * 1024 * 1024, f"{name} source")
        contents[name] = frozen
        try:
            symbols[name] = _source_symbols(frozen, filename=str(path))
        except GateFailure:
            if binding_failures is None:
                raise
            binding_failures.append("EVIDENCE_BINDING_INVALID")
            symbols[name] = set()
    return contents, symbols


def _parse_manifest(
    content: bytes,
    *,
    policy: dict[str, Any],
    source_symbols: dict[str, set[str]],
    binding_failures: list[str] | None = None,
) -> dict[str, Any]:
    manifest = _exact(
        _strict_json(content, "manifest"),
        {
            "schema_version",
            "criticality_policy",
            "capabilities",
            "platform_exclusions",
        },
        "manifest",
    )
    if manifest["schema_version"] != 1:
        raise GateFailure("manifest.schema_version must be 1")
    criticality = _exact(
        manifest["criticality_policy"],
        {"critical", "noncritical", "thresholds_unchanged"},
        "manifest.criticality_policy",
    )
    if criticality != {
        "critical": "atomic_fail_closed_enforcement_seams_require_100_percent_line_and_branch",
        "noncritical": "orchestration_and_diagnostic_aggregators_use_global_80_percent_and_required_success_fail_nodeids",
        "thresholds_unchanged": True,
    }:
        raise GateFailure("manifest.criticality_policy is invalid")
    capabilities = manifest["capabilities"]
    if not isinstance(capabilities, list) or len(capabilities) > policy["limits"]["capabilities"]:
        raise GateFailure("manifest.capabilities is invalid")
    if len(capabilities) != len(EXPECTED_CATEGORIES):
        raise GateFailure("manifest must declare every frozen S18 capability")
    seen_ids: set[str] = set()
    seen_categories: set[str] = set()
    seen_requirements: set[tuple[str, str]] = set()
    declared_targets: set[str] = set()
    for capability_index, value in enumerate(capabilities):
        field = f"manifest.capabilities[{capability_index}]"
        capability = _exact(value, {"id", "category", "description", "targets"}, field)
        capability_id = _nonempty(capability["id"], field + ".id")
        category = _nonempty(capability["category"], field + ".category")
        _nonempty(capability["description"], field + ".description")
        if capability_id in seen_ids or category in seen_categories:
            raise GateFailure("manifest capability IDs and categories must be unique")
        if EXPECTED_CATEGORIES.get(capability_id) != category:
            raise GateFailure("manifest contains an unknown capability or category")
        seen_ids.add(capability_id)
        seen_categories.add(category)
        targets = capability["targets"]
        if (
            not isinstance(targets, list)
            or not targets
            or len(targets) > policy["limits"]["targets_per_capability"]
        ):
            raise GateFailure(f"{field}.targets is invalid")
        local_targets: set[str] = set()
        for target_index, target_value in enumerate(targets):
            target_field = f"{field}.targets[{target_index}]"
            target_record = _exact(
                target_value, {"script", "symbols", "requirements"}, target_field
            )
            script_name = target_record["script"]
            if script_name not in policy["scripts"] or script_name in local_targets:
                raise GateFailure(f"{target_field}.script is invalid or duplicated")
            local_targets.add(script_name)
            declared_targets.add(script_name)
            symbols = target_record["symbols"]
            if (
                not isinstance(symbols, list)
                or len(symbols) > policy["limits"]["symbols_per_target"]
            ):
                raise GateFailure(f"{target_field}.symbols is invalid")
            local_symbols: set[str] = set()
            for symbol_index, symbol_value in enumerate(symbols):
                symbol = _exact(
                    symbol_value,
                    {"name", "critical_line", "critical_branch"},
                    f"{target_field}.symbols[{symbol_index}]",
                )
                name = _nonempty(symbol["name"], target_field + ".symbol.name")
                if name in local_symbols:
                    raise GateFailure(f"{target_field} contains a duplicate or unknown symbol")
                if name not in source_symbols[script_name]:
                    if binding_failures is None:
                        raise GateFailure(
                            f"{target_field} contains a duplicate or unknown symbol"
                        )
                    binding_failures.append("EVIDENCE_BINDING_INVALID")
                if not isinstance(symbol["critical_line"], bool) or not isinstance(
                    symbol["critical_branch"], bool
                ):
                    raise GateFailure(f"{target_field} symbol critical flags must be booleans")
                local_symbols.add(name)
            requirements = target_record["requirements"]
            if (
                not isinstance(requirements, list)
                or not requirements
                or len(requirements) > policy["limits"]["requirements_per_target"]
            ):
                raise GateFailure(f"{target_field}.requirements is invalid")
            semantics: set[str] = set()
            runner_semantics: dict[str, set[str]] = {}
            for requirement_index, requirement_value in enumerate(requirements):
                requirement_field = f"{target_field}.requirements[{requirement_index}]"
                requirement = _exact(
                    requirement_value,
                    {"nodeid", "runner", "semantic", "expected_outcomes"},
                    requirement_field,
                )
                nodeid = _nonempty(requirement["nodeid"], requirement_field + ".nodeid")
                expected_prefix = policy["scripts"][script_name]["test_file"] + "::test_"
                if requirement["runner"] not in policy["runners"]:
                    raise GateFailure(f"{requirement_field}.runner is unknown")
                requirement_key = (requirement["runner"], nodeid)
                if not nodeid.startswith(expected_prefix) or requirement_key in seen_requirements:
                    raise GateFailure(
                        "manifest runner/nodeid pairs must be unique and target-scoped"
                    )
                seen_requirements.add(requirement_key)
                if requirement["semantic"] not in {"success", "fail_closed"}:
                    raise GateFailure(f"{requirement_field}.semantic is invalid")
                semantics.add(requirement["semantic"])
                runner_semantics.setdefault(requirement["runner"], set()).add(
                    requirement["semantic"]
                )
                outcomes = requirement["expected_outcomes"]
                if (
                    not isinstance(outcomes, list)
                    or not outcomes
                    or any(not isinstance(item, str) or not item for item in outcomes)
                    or len(outcomes) != len(set(outcomes))
                ):
                    raise GateFailure(f"{requirement_field}.expected_outcomes is invalid")
            if semantics != {"success", "fail_closed"}:
                raise GateFailure(f"{target_field} must map success and fail_closed semantics")
            if any(
                mapped_semantics != {"success", "fail_closed"}
                for mapped_semantics in runner_semantics.values()
            ):
                raise GateFailure("MANIFEST_RUNNER_SEMANTICS_INCOMPLETE")
    if declared_targets != set(policy["scripts"]):
        raise GateFailure("manifest does not cover both security scripts")
    exclusions = manifest["platform_exclusions"]
    if not isinstance(exclusions, list):
        raise GateFailure("manifest.platform_exclusions is invalid")
    seen_exclusions: set[tuple[str, str, str]] = set()
    for index, value in enumerate(exclusions):
        field = f"manifest.platform_exclusions[{index}]"
        exclusion = _exact(value, {"script", "runner", "nodeid", "reason"}, field)
        script_name = exclusion["script"]
        runner = exclusion["runner"]
        nodeid = _nonempty(exclusion["nodeid"], field + ".nodeid")
        _nonempty(exclusion["reason"], field + ".reason")
        if script_name not in policy["scripts"] or runner not in policy["runners"]:
            raise GateFailure(f"{field} scope is invalid")
        if not nodeid.startswith(policy["scripts"][script_name]["test_file"] + "::test_"):
            raise GateFailure(f"{field}.nodeid is not target-scoped")
        key = (script_name, runner, nodeid)
        if key in seen_exclusions or (runner, nodeid) in seen_requirements:
            raise GateFailure(f"{field} is duplicated or applicable to its own runner")
        if not any(
            declared_runner != runner and declared_nodeid == nodeid
            for declared_runner, declared_nodeid in seen_requirements
        ):
            raise GateFailure(f"{field} does not name another-runner requirement")
        seen_exclusions.add(key)
    return manifest


def load_manifest(
    path: Path = DEFAULT_MANIFEST,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = load_policy() if policy is None else policy
    content = _read_bounded(path, 4 * 1024 * 1024, "manifest")
    _source_contents, source_symbols = _frozen_source_material(policy)
    return _parse_manifest(content, policy=policy, source_symbols=source_symbols)


def _summary(value: object, field: str) -> tuple[int, int, int, int]:
    record = _exact(
        value,
        {
            "covered_lines",
            "num_statements",
            "percent_covered",
            "percent_covered_display",
            "missing_lines",
            "excluded_lines",
            "percent_statements_covered",
            "percent_statements_covered_display",
            "num_branches",
            "num_partial_branches",
            "covered_branches",
            "missing_branches",
            "percent_branches_covered",
            "percent_branches_covered_display",
        },
        field,
    )
    covered_lines = _integer(record["covered_lines"], field + ".covered_lines")
    statements = _integer(record["num_statements"], field + ".num_statements")
    covered_branches = _integer(record["covered_branches"], field + ".covered_branches")
    branches = _integer(record["num_branches"], field + ".num_branches")
    if covered_lines > statements or covered_branches > branches:
        raise GateFailure(f"{field} covered count exceeds total")
    for key in (
        "missing_lines",
        "excluded_lines",
        "num_partial_branches",
        "missing_branches",
    ):
        _integer(record[key], f"{field}.{key}")
    for key in (
        "percent_covered",
        "percent_statements_covered",
        "percent_branches_covered",
    ):
        _number(record[key], f"{field}.{key}")
    for key in (
        "percent_covered_display",
        "percent_statements_covered_display",
        "percent_branches_covered_display",
    ):
        _nonempty(record[key], f"{field}.{key}")
    return covered_lines, statements, covered_branches, branches


def _percent(covered: int, total: int) -> float:
    return 100.0 if total == 0 else covered * 100.0 / total


def _critical_for(manifest: dict[str, Any], target: str) -> dict[str, dict[str, bool]]:
    result: dict[str, dict[str, bool]] = {}
    for capability in manifest["capabilities"]:
        for target_record in capability["targets"]:
            if target_record["script"] != target:
                continue
            for symbol in target_record["symbols"]:
                if not symbol["critical_line"] and not symbol["critical_branch"]:
                    continue
                existing = result.setdefault(
                    symbol["name"], {"critical_line": False, "critical_branch": False}
                )
                existing["critical_line"] |= symbol["critical_line"]
                existing["critical_branch"] |= symbol["critical_branch"]
    return result


def _coverage_report(
    coverage: dict[str, Any],
    *,
    target: str,
    policy: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    coverage = _exact(coverage, {"meta", "files", "totals"}, "coverage")
    meta = _exact(
        coverage["meta"],
        {"format", "version", "timestamp", "branch_coverage", "show_contexts"},
        "coverage.meta",
    )
    if meta["branch_coverage"] is not True:
        failures.append("BRANCH_COVERAGE_REQUIRED")
    if not isinstance(meta["format"], int) or not isinstance(meta["version"], str):
        raise GateFailure("coverage.meta version fields are invalid")
    files = coverage["files"]
    expected_path = policy["scripts"][target]["path"]
    if not isinstance(files, dict) or set(files) != {expected_path}:
        failures.append("SOURCE_SET_INVALID")
        if expected_path not in files:
            return {
                "combined_percent": 0.0,
                "statement_line_percent": 0.0,
                "branch_percent": 0.0,
                "critical_targets": [],
            }, failures
    source = files[expected_path]
    if not isinstance(source, dict):
        raise GateFailure("coverage source record must be an object")
    required_source_keys = {
        "executed_lines",
        "summary",
        "missing_lines",
        "excluded_lines",
        "executed_branches",
        "missing_branches",
        "functions",
        "classes",
    }
    source = _exact(source, required_source_keys, "coverage.files.target")
    file_counts = _summary(source["summary"], "coverage.files.target.summary")
    total_counts = _summary(coverage["totals"], "coverage.totals")
    if file_counts != total_counts:
        failures.append("COVERAGE_TOTALS_INVALID")
    covered_lines, statements, covered_branches, branches = file_counts
    line_percent = _percent(covered_lines, statements)
    branch_percent = _percent(covered_branches, branches)
    combined_percent = _percent(covered_lines + covered_branches, statements + branches)
    thresholds = policy["thresholds"]
    if combined_percent < thresholds["coverage_combined_percent"]:
        failures.append("COMBINED_COVERAGE_BELOW_THRESHOLD")
    if line_percent < thresholds["statement_line_percent"]:
        failures.append("LINE_COVERAGE_BELOW_THRESHOLD")
    if branch_percent < thresholds["branch_percent"]:
        failures.append("BRANCH_COVERAGE_BELOW_THRESHOLD")
    functions = source["functions"]
    if not isinstance(functions, dict):
        raise GateFailure("coverage.functions must be an object")
    critical_results: list[dict[str, Any]] = []
    for symbol, requirements in sorted(_critical_for(manifest, target).items()):
        record = functions.get(symbol)
        if not isinstance(record, dict) or "summary" not in record:
            failures.append("CRITICAL_TARGET_UNCOVERED")
            critical_results.append({"symbol": symbol, "present": False})
            continue
        symbol_counts = _summary(record["summary"], f"coverage.functions.{symbol}.summary")
        symbol_lines, symbol_statements, symbol_branches_covered, symbol_branches = symbol_counts
        symbol_line_percent = _percent(symbol_lines, symbol_statements)
        symbol_branch_percent = _percent(symbol_branches_covered, symbol_branches)
        passed = (
            not requirements["critical_line"]
            or symbol_line_percent >= thresholds["critical_line_percent"]
        ) and (
            not requirements["critical_branch"]
            or symbol_branch_percent >= thresholds["critical_branch_percent"]
        )
        if not passed:
            failures.append("CRITICAL_TARGET_UNCOVERED")
        critical_results.append(
            {
                "symbol": symbol,
                "present": True,
                "line_percent": symbol_line_percent,
                "branch_percent": symbol_branch_percent,
                "branches": symbol_branches,
                "passed": passed,
            }
        )
    return {
        "combined_percent": combined_percent,
        "statement_line_percent": line_percent,
        "branch_percent": branch_percent,
        "counts": {
            "covered_lines": covered_lines,
            "statements": statements,
            "covered_branches": covered_branches,
            "branches": branches,
        },
        "critical_targets": critical_results,
    }, failures


def _nodeid(case: ET.Element, *, test_file: str) -> str:
    classname = case.get("classname")
    name = case.get("name")
    expected_classname = PurePosixPath(test_file).with_suffix("").as_posix().replace(
        "/", "."
    )
    if (
        classname != expected_classname
        or not name
        or not _canonical_junit_name(name)
    ):
        raise _InvalidJUnitNodeId
    return f"{test_file}::{name}"


def _junit_cases(
    content: bytes,
    limit: int,
    *,
    test_file: str,
) -> tuple[dict[str, str], dict[str, str], int]:
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise GateFailure("JUnit declarations are forbidden")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise GateFailure("JUnit is not valid XML") from exc
    cases = root.findall(".//testcase")
    if len(cases) > limit:
        raise GateFailure("JUnit testcase limit exceeded")
    result: dict[str, str] = {}
    skip_reasons: dict[str, str] = {}
    invalid_nodeids = 0
    for case in cases:
        try:
            nodeid = _nodeid(case, test_file=test_file)
        except _InvalidJUnitNodeId:
            invalid_nodeids += 1
            continue
        if nodeid in result:
            raise GateFailure("JUnit contains duplicate testcase nodeids")
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        if failure is not None:
            status = "failure"
        elif error is not None:
            status = "error"
        elif skipped is not None and skipped.get("type") == "pytest.xfail":
            status = "xfail"
        elif skipped is not None:
            status = "skipped"
            skip_reasons[nodeid] = skipped.get("message", "")
        else:
            status = "passed"
        result[nodeid] = status
    return result, skip_reasons, invalid_nodeids


def _platform_exclusions(
    manifest: dict[str, Any], *, target: str, runner: str
) -> dict[str, str]:
    return {
        record["nodeid"]: record["reason"]
        for record in manifest["platform_exclusions"]
        if record["script"] == target and record["runner"] == runner
    }


def _requirements_for(
    manifest: dict[str, Any], target: str, runner: str
) -> tuple[dict[str, dict[str, Any]], dict[str, str], set[str]]:
    requirements: dict[str, dict[str, Any]] = {}
    categories: dict[str, str] = {}
    other_runner_nodeids: set[str] = set()
    for capability in manifest["capabilities"]:
        for target_record in capability["targets"]:
            if target_record["script"] != target:
                continue
            for requirement in target_record["requirements"]:
                nodeid = requirement["nodeid"]
                if requirement["runner"] == runner:
                    requirements[nodeid] = requirement
                    categories[nodeid] = capability["id"]
                else:
                    other_runner_nodeids.add(nodeid)
    return requirements, categories, other_runner_nodeids


def _junit_report(
    content: bytes,
    *,
    target: str,
    runner: str,
    policy: dict[str, Any],
    manifest: dict[str, Any],
    xfail_nodeids: set[str],
    invalid_event_nodeids: set[str],
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    cases, skip_reasons, invalid_nodeids = _junit_cases(
        content,
        policy["limits"]["testcases"],
        test_file=policy["scripts"][target]["test_file"],
    )
    applicable, categories, other_runner_nodeids = _requirements_for(manifest, target, runner)
    if invalid_nodeids:
        return {
            "testcases": len(cases) + invalid_nodeids,
            "passed_testcases": 0,
            "skipped_testcases": 0,
            "failed_testcases": 0,
            "required_total": len(applicable),
            "required_passed": 0,
            "required_tests": [],
        }, ["JUNIT_NODEID_INVALID"]
    allowed_exclusions = _platform_exclusions(manifest, target=target, runner=runner)
    cases = {
        nodeid: (
            "xfail"
            if nodeid in xfail_nodeids or status == "xfail"
            else "invalid"
            if nodeid in invalid_event_nodeids
            else status
        )
        for nodeid, status in cases.items()
    }
    status_codes = {
        "skipped": "REQUIRED_TEST_SKIPPED",
        "xfail": "REQUIRED_TEST_XFAILED",
        "failure": "REQUIRED_TEST_FAILED",
        "error": "REQUIRED_TEST_ERROR",
    }
    required_results: list[dict[str, str]] = []
    passed = 0
    for nodeid, requirement in sorted(applicable.items()):
        status = cases.get(nodeid, "missing")
        if status == "missing":
            failures.append("REQUIRED_TEST_MISSING")
        elif status == "invalid":
            pass
        elif status != "passed":
            failures.append(status_codes[status])
        else:
            passed += 1
        required_results.append(
            {
                "nodeid": nodeid,
                "status": status,
                "capability": categories[nodeid],
                "semantic": requirement["semantic"],
            }
        )
    for nodeid, status in cases.items():
        if status in {"failure", "error"} and nodeid not in applicable:
            failures.append("JUNIT_CONTAINS_FAILURE")
        if status in {"skipped", "xfail"} and nodeid not in applicable:
            declared_other_runner = nodeid in other_runner_nodeids
            exact_platform_exclusion = (
                status == "skipped"
                and declared_other_runner
                and allowed_exclusions.get(nodeid) == skip_reasons.get(nodeid)
            )
            if not exact_platform_exclusion:
                failures.append("UNEXPECTED_TEST_SKIP")
    return {
        "testcases": len(cases),
        "passed_testcases": sum(status == "passed" for status in cases.values()),
        "skipped_testcases": sum(status in {"skipped", "xfail"} for status in cases.values()),
        "failed_testcases": sum(
            status in {"failure", "error", "invalid"} for status in cases.values()
        ),
        "required_total": len(applicable),
        "required_passed": passed,
        "required_tests": required_results,
    }, failures


def _pytest_configuration_failures(content: bytes) -> list[str]:
    try:
        value = tomllib.loads(content.decode("utf-8"))
        pytest_options = value["tool"]["pytest"]["ini_options"]
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
        return ["RUNNER_CONFIGURATION_INVALID"]
    if not isinstance(pytest_options, dict) or set(pytest_options) != {
        "addopts",
        "markers",
        "testpaths",
        "xfail_strict",
    }:
        return ["RUNNER_CONFIGURATION_INVALID"]
    if (
        pytest_options["addopts"] != "-ra --strict-config --strict-markers"
        or pytest_options["xfail_strict"] is not True
        or pytest_options["testpaths"] != ["tests"]
        or pytest_options["markers"]
        != [
            "component: requires local component assets or codecs",
            "golden: requires the pinned canonical oracle environment",
            "package: builds or inspects an installed distribution",
            "system: requires POSIX process, signal, and filesystem semantics",
        ]
    ):
        return ["RUNNER_CONFIGURATION_INVALID"]
    return []


def _event_junit_status(case: dict[str, Any]) -> str:
    phases = case["phases"]
    setup = phases["setup"]
    call = phases["call"]
    teardown = phases["teardown"]
    if setup is None or teardown is None or teardown["outcome"] == "skipped":
        raise GateFailure("pytest_events phase lifecycle is invalid")
    any_wasxfail = any(
        phase is not None and phase["wasxfail"] for phase in phases.values()
    )
    if setup["outcome"] == "failed":
        if call is not None or teardown["outcome"] != "passed":
            raise GateFailure("pytest_events phase lifecycle is invalid")
        return "error"
    if setup["outcome"] == "skipped":
        if call is not None or teardown["outcome"] != "passed":
            raise GateFailure("pytest_events phase lifecycle is invalid")
        return "xfail" if any_wasxfail else "skipped"
    if call is None:
        raise GateFailure("pytest_events phase lifecycle is invalid")
    if call["outcome"] == "failed":
        if teardown["outcome"] != "passed":
            raise GateFailure("pytest_events phase lifecycle is invalid")
        return "failure"
    if call["outcome"] == "skipped":
        if teardown["outcome"] != "passed":
            raise GateFailure("pytest_events phase lifecycle is invalid")
        return "xfail" if any_wasxfail else "skipped"
    if teardown["outcome"] == "failed":
        return "error"
    return "passed"


def _pytest_events_report(
    content: bytes,
    *,
    run_id: str,
    target: str,
    runner: str,
    attempt: int,
    test_file: str,
    junit_cases: dict[str, str] | None,
    limits: dict[str, int],
) -> tuple[dict[str, Any], set[str], set[str], list[str]]:
    empty_report = {
        "testcases": 0,
        "xfail_marked": 0,
        "wasxfail": 0,
    }
    try:
        value = _strict_json(content, "pytest_events")
        record = _exact(
            value,
            {
                "schema_version",
                "run_id",
                "target",
                "runner",
                "attempt",
                "test_file",
                "limits",
                "cases",
            },
            "pytest_events",
        )
        if isinstance(record["schema_version"], bool) or record["schema_version"] != 3:
            raise GateFailure("pytest_events.schema_version must be 3")
        if (
            not isinstance(record["run_id"], str)
            or not RUN_ID.fullmatch(record["run_id"])
            or not isinstance(record["target"], str)
            or not isinstance(record["runner"], str)
            or isinstance(record["attempt"], bool)
            or not isinstance(record["attempt"], int)
            or record["attempt"] < 1
            or not isinstance(record["test_file"], str)
            or record["run_id"] != run_id
            or record["target"] != target
            or record["runner"] != runner
            or record["attempt"] != attempt
            or record["test_file"] != test_file
        ):
            raise GateFailure("pytest_events scope is invalid")
        event_limits = _exact(
            record["limits"],
            {"testcases", "pytest_events_nodeid_bytes", "pytest_events_bytes"},
            "pytest_events.limits",
        )
        expected_limits = {
            name: limits[name]
            for name in ("testcases", "pytest_events_nodeid_bytes", "pytest_events_bytes")
        }
        if event_limits != expected_limits or len(content) > limits["pytest_events_bytes"]:
            raise GateFailure("pytest_events limits are invalid")
        cases = record["cases"]
        if not isinstance(cases, list) or len(cases) > limits["testcases"]:
            raise GateFailure("pytest_events cases are invalid")
        parsed: dict[str, dict[str, Any]] = {}
        ordered_nodeids: list[str] = []
        for index, value_case in enumerate(cases):
            case = _exact(
                value_case,
                {"nodeid", "xfail_marked", "phases"},
                f"pytest_events.cases[{index}]",
            )
            nodeid = case["nodeid"]
            prefix = test_file + "::"
            if (
                not isinstance(nodeid, str)
                or not nodeid.startswith(prefix)
                or not _canonical_junit_name(nodeid.removeprefix(prefix))
                or len(nodeid.encode("utf-8", "strict"))
                > limits["pytest_events_nodeid_bytes"]
                or nodeid in parsed
                or not isinstance(case["xfail_marked"], bool)
            ):
                raise GateFailure("pytest_events case is invalid")
            phases = _exact(
                case["phases"],
                {"setup", "call", "teardown"},
                f"pytest_events.cases[{index}].phases",
            )
            for phase_name, phase_value in phases.items():
                if phase_value is None:
                    continue
                phase = _exact(
                    phase_value,
                    {"outcome", "wasxfail"},
                    f"pytest_events.cases[{index}].phases.{phase_name}",
                )
                if (
                    phase["outcome"] not in {"passed", "failed", "skipped"}
                    or not isinstance(phase["wasxfail"], bool)
                ):
                    raise GateFailure("pytest_events phase is invalid")
            _event_junit_status(case)
            parsed[nodeid] = case
            ordered_nodeids.append(nodeid)
        if ordered_nodeids != sorted(ordered_nodeids):
            raise GateFailure("pytest_events cases are not canonical")
        if junit_cases is not None and set(parsed) != set(junit_cases):
            raise GateFailure("pytest_events and JUnit cases differ")
        canonical = (
            json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8", "strict")
        if content != canonical:
            raise GateFailure("pytest_events bytes are not canonical")
    except (GateFailure, KeyError, TypeError, UnicodeEncodeError):
        invalid_nodeids = set(junit_cases) if junit_cases is not None else set()
        return empty_report, set(), invalid_nodeids, ["PYTEST_EVENTS_INVALID"]
    xfail_nodeids = {
        nodeid
        for nodeid, case in parsed.items()
        if case["xfail_marked"]
        or any(
            phase is not None and phase["wasxfail"]
            for phase in case["phases"].values()
        )
    }
    invalid_nodeids = {
        nodeid
        for nodeid, case in parsed.items()
        if junit_cases is not None
        and _event_junit_status(case) != junit_cases[nodeid]
    }
    failures = ["PYTEST_EVENTS_INVALID"] if invalid_nodeids else []
    report = {
        "testcases": len(parsed),
        "xfail_marked": sum(bool(case["xfail_marked"]) for case in parsed.values()),
        "wasxfail": sum(
            any(
                phase is not None and phase["wasxfail"]
                for phase in case["phases"].values()
            )
            for case in parsed.values()
        ),
    }
    return report, xfail_nodeids, invalid_nodeids, failures


def _runtime_invalid_summary(artifact_sha256: str | None) -> dict[str, Any]:
    return {
        "status": "invalid",
        "artifact_sha256": artifact_sha256,
        "schema_version": None,
        "provenance": None,
        "semantic_runtime_sha256": None,
        "runtime": None,
        "uv": None,
        "uv_lock_sha256": None,
        "distributions": {},
        "plugins": {},
    }


def _runtime_canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise GateFailure("runtime identity contains a non-JSON value") from exc


def _runtime_base64(value: object, field: str) -> bytes:
    if not isinstance(value, str):
        raise GateFailure(f"{field} is not Base64 text")
    try:
        raw = value.encode("ascii")
        decoded = base64.b64decode(raw, validate=True)
    except (UnicodeEncodeError, ValueError, TypeError) as exc:
        raise GateFailure(f"{field} is not canonical Base64") from exc
    if base64.b64encode(decoded) != raw:
        raise GateFailure(f"{field} is not canonical Base64")
    return decoded


def _runtime_record_digest(value: object) -> str:
    if not isinstance(value, str) or RUNTIME_SHA256_URLSAFE.fullmatch(value) is None:
        raise GateFailure("runtime RECORD digest is invalid")
    try:
        decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise GateFailure("runtime RECORD digest is invalid") from exc
    if (
        len(decoded) != 32
        or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value
    ):
        raise GateFailure("runtime RECORD digest is invalid")
    return decoded.hex()


def _runtime_decimal(value: object, field: str, maximum: int = 2**63 - 1) -> int:
    if not isinstance(value, str) or RUNTIME_DECIMAL.fullmatch(value) is None:
        raise GateFailure(f"{field} is invalid")
    if len(value) > len(str(maximum)) or (
        len(value) == len(str(maximum)) and value > str(maximum)
    ):
        raise GateFailure(f"{field} is invalid")
    return int(value)


def _runtime_pep503(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise GateFailure("runtime package name is invalid")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise GateFailure("runtime package name is invalid") from exc
    normalized = RUNTIME_PEP503_RUN.sub("-", value).lower()
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized) is None:
        raise GateFailure("runtime package name is invalid")
    return normalized


def _runtime_path(value: object, field: str, *, leaf: bool) -> Path:
    if not isinstance(value, str) or "\x00" in value:
        raise GateFailure(f"{field} path is invalid")
    path = Path(value)
    if not path.is_absolute() or path != Path(os.path.normpath(value)):
        raise GateFailure(f"{field} path is invalid")
    if leaf and not path.name:
        raise GateFailure(f"{field} path is not a file leaf")
    return path


def _runtime_stable_read(
    path: Path,
    limit: int,
    field: str,
    *,
    single_link: bool = True,
) -> bytes:
    """Read a captured live endpoint without imposing evidence-artifact ownership."""

    try:
        if path.resolve(strict=True) != path:
            raise GateFailure(f"{field} path is not canonical")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or (single_link and before.st_nlink != 1):
            raise GateFailure(f"{field} is not a single-link regular file")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            opened = os.fstat(descriptor)
            if _identity(before) != _identity(opened):
                raise GateFailure(f"{field} identity changed before open")
            chunks: list[bytes] = []
            length = 0
            while True:
                chunk = os.read(descriptor, min(65536, limit + 1 - length))
                if not chunk:
                    break
                chunks.append(chunk)
                length += len(chunk)
                if length > limit:
                    raise GateFailure(f"{field} exceeds its byte limit")
            if _identity(opened) != _identity(os.fstat(descriptor)):
                raise GateFailure(f"{field} identity changed during read")
        finally:
            os.close(descriptor)
        if _identity(before) != _identity(path.lstat()):
            raise GateFailure(f"{field} pathname changed during read")
    except GateFailure:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise GateFailure(f"{field} cannot be read safely") from exc
    return b"".join(chunks)


def _runtime_executable_target(alias: Path) -> Path:
    current = alias
    seen: set[tuple[int, int]] = set()
    for _hop in range(17):
        try:
            parent = current.parent.resolve(strict=True)
            if parent != current.parent:
                raise GateFailure("runtime executable parent is not canonical")
            value = current.lstat()
        except GateFailure:
            raise
        except (OSError, RuntimeError) as exc:
            raise GateFailure("runtime executable chain is invalid") from exc
        if not stat.S_ISLNK(value.st_mode):
            if _hop > 16 or not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
                raise GateFailure("runtime executable target is invalid")
            if current.resolve(strict=True) != current:
                raise GateFailure("runtime executable target is not canonical")
            return current
        identity = (value.st_dev, value.st_ino)
        if identity in seen or _hop == 16:
            raise GateFailure("runtime executable symlink chain is invalid")
        seen.add(identity)
        target = os.readlink(current)
        if not target or any(ord(char) < 32 or ord(char) == 127 for char in target):
            raise GateFailure("runtime executable symlink target is invalid")
        following = Path(target)
        if not following.is_absolute():
            following = current.parent / following
        current = Path(os.path.normpath(os.fspath(following)))
    raise GateFailure("runtime executable symlink chain is invalid")


def _runtime_executable_snapshot(alias: Path) -> tuple[tuple[object, ...], ...]:
    current = alias
    seen: set[tuple[int, int]] = set()
    result: list[tuple[object, ...]] = []
    for hop in range(17):
        try:
            if current.parent.resolve(strict=True) != current.parent:
                raise GateFailure("runtime executable parent is not canonical")
            value = current.lstat()
        except GateFailure:
            raise
        except (OSError, RuntimeError) as exc:
            raise GateFailure("runtime executable chain is invalid") from exc
        target: str | None = None
        if stat.S_ISLNK(value.st_mode):
            if hop == 16 or (value.st_dev, value.st_ino) in seen:
                raise GateFailure("runtime executable symlink chain is invalid")
            seen.add((value.st_dev, value.st_ino))
            target = os.readlink(current)
            if not target or any(ord(char) < 32 or ord(char) == 127 for char in target):
                raise GateFailure("runtime executable symlink target is invalid")
        result.append((os.fspath(current), _identity(value), target))
        if target is None:
            return tuple(result)
        following = Path(target)
        if not following.is_absolute():
            following = current.parent / following
        current = Path(os.path.normpath(os.fspath(following)))
    raise GateFailure("runtime executable symlink chain is invalid")


def _runtime_pyvenv(content: bytes) -> dict[str, str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateFailure("runtime pyvenv.cfg is not UTF-8") from exc
    if "\x00" in text:
        raise GateFailure("runtime pyvenv.cfg contains NUL")
    values: dict[str, str] = {}
    for line in text.splitlines():
        if " = " not in line:
            raise GateFailure("runtime pyvenv.cfg entry is invalid")
        key, item = line.split(" = ", 1)
        if RUNTIME_PYVENV_KEY.fullmatch(key) is None or not item or key in values:
            raise GateFailure("runtime pyvenv.cfg entry is invalid")
        values[key] = item
    version_keys = [key for key in ("version", "version_info") if key in values]
    if (
        values.get("include-system-site-packages") != "false"
        or not values.get("home")
        or len(version_keys) != 1
    ):
        raise GateFailure("runtime pyvenv.cfg authority is invalid")
    return values


def _runtime_metadata(content: bytes) -> tuple[str, str]:
    try:
        text = content.decode("utf-8")
        if "\x00" in text:
            raise GateFailure("runtime METADATA contains NUL")
        message = email.parser.Parser(policy=email_policy.strict).parsestr(text)
        names = message.get_all("Name", [])
        versions = message.get_all("Version", [])
    except GateFailure:
        raise
    except (UnicodeDecodeError, ValueError, MessageDefect) as exc:
        raise GateFailure("runtime METADATA is invalid") from exc
    if (
        message.defects
        or len(names) != 1
        or len(versions) != 1
        or not isinstance(names[0], str)
        or not isinstance(versions[0], str)
        or not names[0]
        or not versions[0]
        or names[0].strip() != names[0]
        or versions[0].strip() != versions[0]
    ):
        raise GateFailure("runtime METADATA identity is invalid")
    return names[0], versions[0]


def _runtime_required_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and "\x00" not in value
        and "\\" not in value
        and not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _runtime_record(
    content: bytes, *, dist_info: str, required: tuple[str, ...]
) -> list[dict[str, object]]:
    try:
        text = content.decode("utf-8")
        if "\x00" in text:
            raise GateFailure("runtime RECORD contains NUL")
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except GateFailure:
        raise
    except (UnicodeDecodeError, csv.Error, TypeError) as exc:
        raise GateFailure("runtime RECORD is invalid") from exc
    if not rows:
        raise GateFailure("runtime RECORD is empty")
    seen: set[str] = set()
    found: set[str] = set()
    self_path = f"{dist_info}/RECORD"
    self_count = 0
    result: list[dict[str, object]] = []
    for row in rows:
        if len(row) != 3:
            raise GateFailure("runtime RECORD row is invalid")
        path_text, digest_text, size_text = row
        if not path_text or path_text in seen or "\x00" in path_text or "\\" in path_text:
            raise GateFailure("runtime RECORD path is invalid")
        seen.add(path_text)
        if path_text == self_path:
            if digest_text or size_text:
                raise GateFailure("runtime RECORD self row is invalid")
            self_count += 1
            result.append({"kind": "self", "path": path_text, "sha256": None, "size": None})
            continue
        if not digest_text.startswith("sha256="):
            raise GateFailure("runtime RECORD hash is invalid")
        digest = _runtime_record_digest(digest_text.removeprefix("sha256="))
        size = _runtime_decimal(size_text, "runtime RECORD size")
        path = PurePosixPath(path_text)
        if path.is_absolute() or path.as_posix() != path_text:
            raise GateFailure("runtime RECORD path is not canonical")
        if path_text in required:
            if not _runtime_required_path(path_text):
                raise GateFailure("runtime required RECORD path is unsafe")
            kind = "required"
            found.add(path_text)
        elif ".." in path.parts:
            kind = "opaque"
        elif _runtime_required_path(path_text):
            kind = "entry"
        else:
            raise GateFailure("runtime RECORD path is not canonical")
        result.append({"kind": kind, "path": path_text, "sha256": digest, "size": size})
    if self_count != 1 or found != set(required):
        raise GateFailure("runtime RECORD closure is incomplete")
    return result


def _runtime_lock_packages(content: bytes) -> dict[str, dict[str, Any]]:
    try:
        value = tomllib.loads(content.decode("utf-8"))
        packages = value["package"]
    except (UnicodeDecodeError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise GateFailure("runtime uv.lock is invalid") from exc
    if not isinstance(packages, list):
        raise GateFailure("runtime uv.lock package list is invalid")
    result: dict[str, dict[str, Any]] = {}
    for name in RUNTIME_DISTRIBUTIONS:
        matches = [
            package
            for package in packages
            if isinstance(package, dict)
            and isinstance(package.get("name"), str)
            and _runtime_pep503(package["name"]) == name
        ]
        if len(matches) != 1:
            raise GateFailure("runtime uv.lock package resolution is not unique")
        result[name] = matches[0]
    return result


def _runtime_distribution_version_fact(
    record: dict[str, Any],
    *,
    name: str,
    site_packages: Path,
    policy: dict[str, Any],
    uv_lock_content: bytes,
    captured_entry_bytes: dict[Path, bytes],
) -> dict[str, Any] | None:
    """Return one version only after that distribution independently validates."""

    try:
        distributions = _exact(
            record["distributions"], set(RUNTIME_DISTRIBUTIONS), "runtime distributions"
        )
        pair = _exact(distributions[name], {"installed", "lock"}, f"{name} distribution")
        installed = _exact(
            pair["installed"],
            {"name", "version", "dist_info", "metadata_bytes", "metadata_size", "metadata_sha256", "record_bytes", "record_size", "record_sha256", "record_rows", "required_entries"},
            f"{name} installed",
        )
        lock = _exact(
            pair["lock"],
            {"name", "version", "exact_package_object", "canonical_package_bytes", "lock_package_sha256", "lock_file_sha256", "required_dependencies"},
            f"{name} lock",
        )
        version = installed["version"]
        dist_info = installed["dist_info"]
        if (
            installed["name"] != name
            or not isinstance(version, str)
            or len(version) > 128
            or VERSION.fullmatch(version) is None
            or not isinstance(dist_info, str)
            or RUNTIME_DIST_INFO.fullmatch(dist_info) is None
        ):
            raise GateFailure("runtime distribution identity is invalid")
        stem_name, separator, stem_version = dist_info.removesuffix(".dist-info").rpartition("-")
        if not separator or _runtime_pep503(stem_name) != name or stem_version != version:
            raise GateFailure("runtime dist-info identity is invalid")
        candidates = []
        for child in site_packages.iterdir():
            if RUNTIME_DIST_INFO.fullmatch(child.name) is None:
                continue
            candidate_name, candidate_separator, _candidate_version = child.name.removesuffix(".dist-info").rpartition("-")
            if candidate_separator and _runtime_pep503(candidate_name) == name:
                candidates.append(child)
        dist_path = site_packages / dist_info
        if candidates != [dist_path] or dist_path.resolve(strict=True) != dist_path or not dist_path.is_dir():
            raise GateFailure("runtime dist-info endpoint is invalid")
        metadata = _runtime_base64(installed["metadata_bytes"], f"{name}.metadata_bytes")
        record_bytes = _runtime_base64(installed["record_bytes"], f"{name}.record_bytes")
        if (
            len(metadata) > policy["limits"]["runtime_metadata_bytes"]
            or len(record_bytes) > policy["limits"]["runtime_record_bytes"]
            or type(installed["metadata_size"]) is not int
            or installed["metadata_size"] != len(metadata)
            or installed["metadata_sha256"] != _sha256(metadata)
            or type(installed["record_size"]) is not int
            or installed["record_size"] != len(record_bytes)
            or installed["record_sha256"] != _sha256(record_bytes)
            or _runtime_stable_read(dist_path / "METADATA", policy["limits"]["runtime_metadata_bytes"], f"{name} METADATA") != metadata
            or _runtime_stable_read(dist_path / "RECORD", policy["limits"]["runtime_record_bytes"], f"{name} RECORD") != record_bytes
        ):
            raise GateFailure("runtime distribution raw binding is invalid")
        metadata_name, metadata_version = _runtime_metadata(metadata)
        if metadata_name != name or metadata_version != version:
            raise GateFailure("runtime METADATA binding is invalid")
        required = RUNTIME_REQUIRED_ENTRIES[name]
        rows = _runtime_record(record_bytes, dist_info=dist_info, required=required)
        if _runtime_canonical_json(installed["record_rows"]) != _runtime_canonical_json(rows):
            raise GateFailure("runtime RECORD normalization is invalid")
        entries = _exact(installed["required_entries"], set(required), f"{name} entries")
        rows_by_path = {row["path"]: row for row in rows}
        entry_summary: dict[str, Any] = {}
        captured_entries: dict[Path, bytes] = {}
        for relative in required:
            entry = _exact(entries[relative], {"bytes", "size", "sha256"}, relative)
            entry_bytes = _runtime_base64(entry["bytes"], relative)
            entry_path = site_packages.joinpath(*PurePosixPath(relative).parts)
            live_entry = _runtime_stable_read(
                entry_path,
                policy["limits"]["runtime_required_entry_bytes"],
                relative,
            )
            captured_entry_bytes[entry_path] = live_entry
            if (
                len(entry_bytes) > policy["limits"]["runtime_required_entry_bytes"]
                or type(entry["size"]) is not int
                or entry["size"] != len(entry_bytes)
                or entry["sha256"] != _sha256(entry_bytes)
                or rows_by_path[relative]["sha256"] != entry["sha256"]
                or rows_by_path[relative]["size"] != entry["size"]
                or live_entry != entry_bytes
            ):
                raise GateFailure("runtime required entry binding is invalid")
            entry_summary[relative] = {"sha256": entry["sha256"], "size": entry["size"]}
            captured_entries[entry_path] = live_entry
        actual_package = _runtime_lock_packages(uv_lock_content)[name]
        sidecar_package = lock["exact_package_object"]
        if not isinstance(sidecar_package, dict):
            raise GateFailure("runtime lock package is invalid")
        actual_canonical = _runtime_canonical_json(actual_package)
        sidecar_canonical = _runtime_canonical_json(sidecar_package)
        dependencies = actual_package.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise GateFailure("runtime lock dependencies are invalid")
        names = []
        for dependency in dependencies:
            if not isinstance(dependency, dict) or not isinstance(dependency.get("name"), str):
                raise GateFailure("runtime lock dependency is invalid")
            names.append(_runtime_pep503(dependency["name"]))
        required_dependencies = list(RUNTIME_REQUIRED_DEPENDENCIES[name])
        if (
            len(names) != len(set(names))
            or any(item not in names for item in required_dependencies)
            or actual_package.get("name") != name
            or actual_package.get("version") != version
            or lock["name"] != name
            or lock["version"] != version
            or sidecar_canonical != actual_canonical
            or _runtime_base64(lock["canonical_package_bytes"], f"{name}.canonical") != sidecar_canonical
            or lock["lock_package_sha256"] != _sha256(actual_canonical)
            or lock["lock_file_sha256"] != _sha256(uv_lock_content)
            or lock["required_dependencies"] != required_dependencies
        ):
            raise GateFailure("runtime lock package binding is invalid")
        return {
            "version": version,
            "installed": installed,
            "summary": {
                "version": version,
                "metadata_sha256": installed["metadata_sha256"],
                "record_sha256": installed["record_sha256"],
                "lock_package_sha256": lock["lock_package_sha256"],
                "required_entries": entry_summary,
            },
            "captured_entries": captured_entries,
        }
    except (GateFailure, KeyError, TypeError, OSError, RuntimeError, ValueError):
        return None


def _runtime_identity_validation_core(
    content: bytes,
    *,
    raw_was_read: bool = True,
    mode_valid: bool = True,
    run_id: str,
    target: str,
    runner: str,
    attempt: int,
    started_at: str,
    policy: dict[str, Any],
    uv_lock_content: bytes,
    pytest_events_plugin_content: bytes,
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    artifact_sha256 = _sha256(content) if raw_was_read else None
    invalid = _runtime_invalid_summary(artifact_sha256)
    facts: dict[str, Any] = {
        "uv": None,
        "uv_live_sha256": None,
        "semantic_runtime_sha256": None,
        "distribution_versions": {},
    }
    if not raw_was_read or not mode_valid:
        return invalid, ["RUNTIME_IDENTITY_INVALID"], facts
    failures: list[str] = []
    envelope_valid = False
    record: dict[str, Any] = {}
    installed_values: dict[str, dict[str, Any]] = {}
    distribution_summary: dict[str, Any] = {}
    directory_paths: dict[str, Path] = {}
    captured_entry_bytes: dict[Path, bytes] = {}
    try:
        record = _exact(
            _strict_json(content, "runtime_identity"),
            {
                "schema_version",
                "provenance",
                "scope",
                "runtime",
                "uv",
                "uv_lock_sha256",
                "distributions",
                "plugins",
                "semantic_runtime_sha256",
            },
            "runtime_identity",
        )
        if type(record["schema_version"]) is not int or record["schema_version"] != 2 or record["provenance"] != policy["runtime"]["provenance"]:
            raise GateFailure("runtime identity envelope is invalid")
        envelope_valid = True
        try:
            scope = _exact(record["scope"], {"run_id", "target", "runner", "attempt", "timestamp"}, "runtime_identity.scope")
            if (
                type(scope["run_id"]) is not str
                or scope["run_id"] != run_id
                or type(scope["target"]) is not str
                or scope["target"] != target
                or type(scope["runner"]) is not str
                or scope["runner"] != runner
                or type(scope["attempt"]) is not int
                or scope["attempt"] != attempt
                or not isinstance(scope["timestamp"], str)
                or RUNTIME_TIMESTAMP.fullmatch(scope["timestamp"]) is None
                or scope["timestamp"] != started_at
            ):
                raise GateFailure("runtime identity scope is invalid")
        except (GateFailure, KeyError, TypeError, ValueError):
            failures.append("RUNTIME_IDENTITY_INVALID")
        try:
            uv = _exact(record["uv"], {"path", "version", "sha256"}, "runtime_identity.uv")
            uv_path = _runtime_path(uv["path"], "runtime uv", leaf=True)
            if (
                not isinstance(uv["version"], str)
                or len(uv["version"]) > 128
                or VERSION.fullmatch(uv["version"]) is None
                or not isinstance(uv["sha256"], str)
                or SHA256.fullmatch(uv["sha256"]) is None
            ):
                raise GateFailure("runtime uv identity is invalid")
            facts["uv"] = {
                "path": os.fspath(uv_path),
                "version": uv["version"],
                "sha256": uv["sha256"],
            }
        except (GateFailure, KeyError, TypeError, ValueError):
            failures.append("RUNTIME_IDENTITY_INVALID")
            uv = {}
            uv_path = None
        if uv_path is not None:
            try:
                uv_live_sha256 = _sha256(
                    _runtime_stable_read(
                        uv_path,
                        64 * 1024 * 1024,
                        "runtime uv",
                        single_link=False,
                    )
                )
                facts["uv_live_sha256"] = uv_live_sha256
                if uv_live_sha256 != uv["sha256"]:
                    failures.append("EVIDENCE_TOOLCHAIN_BINDING_INVALID")
            except (GateFailure, OSError, RuntimeError, ValueError):
                failures.append("EVIDENCE_TOOLCHAIN_BINDING_INVALID")
        claimed_semantic = record.get("semantic_runtime_sha256")
        semantic_value = dict(record)
        semantic_value.pop("semantic_runtime_sha256", None)
        semantic_value["scope"] = {"runner": runner}
        if (
            isinstance(claimed_semantic, str)
            and SHA256.fullmatch(claimed_semantic) is not None
            and claimed_semantic == _sha256(_runtime_canonical_json(semantic_value))
        ):
            facts["semantic_runtime_sha256"] = claimed_semantic
        else:
            failures.append("RUNTIME_IDENTITY_INVALID")
        runtime = _exact(
            record["runtime"],
            {
                "executable", "executable_realpath", "executable_size", "executable_sha256",
                "venv_root", "base_prefix", "site_packages", "home", "pyvenv_cfg_path",
                "pyvenv_cfg_bytes", "pyvenv_cfg_size", "pyvenv_cfg_sha256", "implementation",
                "version", "cache_tag", "system", "machine", "isolated", "no_site",
                "dont_write_bytecode",
            },
            "runtime_identity.runtime",
        )
        file_paths = {
            name: _runtime_path(runtime[name], f"runtime.{name}", leaf=True)
            for name in ("executable", "executable_realpath", "pyvenv_cfg_path")
        }
        directory_paths = {
            name: _runtime_path(runtime[name], f"runtime.{name}", leaf=False)
            for name in ("venv_root", "base_prefix", "site_packages", "home")
        }
        for path in directory_paths.values():
            if path.resolve(strict=True) != path or not path.is_dir():
                raise GateFailure("runtime directory path is not canonical")
        for distribution_name in RUNTIME_DISTRIBUTIONS:
            distribution_result = _runtime_distribution_version_fact(
                record,
                name=distribution_name,
                site_packages=directory_paths["site_packages"],
                policy=policy,
                uv_lock_content=uv_lock_content,
                captured_entry_bytes=captured_entry_bytes,
            )
            if distribution_result is None:
                failures.append("RUNTIME_IDENTITY_INVALID")
            else:
                facts["distribution_versions"][distribution_name] = distribution_result[
                    "version"
                ]
                installed_values[distribution_name] = distribution_result["installed"]
                distribution_summary[distribution_name] = distribution_result["summary"]
                captured_entry_bytes.update(distribution_result["captured_entries"])
        executable_snapshot = _runtime_executable_snapshot(file_paths["executable"])
        executable_target = _runtime_executable_target(file_paths["executable"])
        executable_bytes = _runtime_stable_read(executable_target, 64 * 1024 * 1024, "runtime executable")
        if (
            executable_target != file_paths["executable_realpath"]
            or executable_snapshot != _runtime_executable_snapshot(file_paths["executable"])
            or executable_target != _runtime_executable_target(file_paths["executable"])
        ):
            raise GateFailure("runtime executable realpath is invalid")
        if (
            type(runtime["executable_size"]) is not int
            or runtime["executable_size"] != len(executable_bytes)
            or runtime["executable_sha256"] != _sha256(executable_bytes)
        ):
            raise GateFailure("runtime executable binding is invalid")
        pyvenv_bytes = _runtime_base64(runtime["pyvenv_cfg_bytes"], "runtime.pyvenv_cfg_bytes")
        if len(pyvenv_bytes) > policy["limits"]["runtime_pyvenv_cfg_bytes"]:
            raise GateFailure("runtime pyvenv.cfg exceeds its byte limit")
        if (
            _runtime_stable_read(file_paths["pyvenv_cfg_path"], policy["limits"]["runtime_pyvenv_cfg_bytes"], "runtime pyvenv.cfg") != pyvenv_bytes
            or type(runtime["pyvenv_cfg_size"]) is not int
            or runtime["pyvenv_cfg_size"] != len(pyvenv_bytes)
            or runtime["pyvenv_cfg_sha256"] != _sha256(pyvenv_bytes)
        ):
            raise GateFailure("runtime pyvenv.cfg binding is invalid")
        pyvenv = _runtime_pyvenv(pyvenv_bytes)
        version_match = RUNTIME_PYTHON_VERSION.fullmatch(str(runtime["version"]))
        config_key = "version" if "version" in pyvenv else "version_info"
        config_match = RUNTIME_PYTHON_VERSION.fullmatch(pyvenv[config_key])
        if (
            version_match is None
            or config_match is None
            or version_match.groups() != config_match.groups()
            or not isinstance(runtime["version"], str)
            or len(runtime["version"]) > 128
            or runtime["implementation"] != "CPython"
            or runtime["system"] != ("Darwin" if runner == "macos" else "Linux")
            or not isinstance(runtime["machine"], str)
            or runtime["machine"] not in policy["runners"][runner]["machines"]
            or not isinstance(runtime["cache_tag"], str)
            or not runtime["cache_tag"]
            or any(runtime[name] is not True for name in ("isolated", "no_site", "dont_write_bytecode"))
        ):
            raise GateFailure("runtime implementation identity is invalid")
        major, minor = version_match.groups()[:2]
        if (
            file_paths["executable"].parent != directory_paths["venv_root"] / "bin"
            or file_paths["pyvenv_cfg_path"] != directory_paths["venv_root"] / "pyvenv.cfg"
            or directory_paths["site_packages"] != directory_paths["venv_root"] / "lib" / f"python{major}.{minor}" / "site-packages"
            or file_paths["executable_realpath"].parent != directory_paths["home"]
            or directory_paths["home"].parent != directory_paths["base_prefix"]
            or pyvenv["home"] != os.fspath(directory_paths["home"])
        ):
            raise GateFailure("runtime path relationships are invalid")
        if facts["uv"] is None:
            raise GateFailure("runtime uv identity is invalid")
        if record["uv_lock_sha256"] != _sha256(uv_lock_content):
            raise GateFailure("runtime uv.lock hash is invalid")
    except (GateFailure, KeyError, TypeError, OSError, RuntimeError, ValueError):
        failures.append("RUNTIME_IDENTITY_INVALID")

    if not envelope_valid:
        return invalid, sorted(set(failures)), facts

    try:
        plugins = _exact(record["plugins"], set(RUNTIME_PLUGINS), "runtime_identity.plugins")
        parsed_plugins: dict[str, dict[str, Any]] = {}
        for name in RUNTIME_PLUGINS:
            plugin = _exact(plugins[name], {"file", "sha256", "distribution", "entry"}, f"runtime_identity.plugins.{name}")
            path = _runtime_path(plugin["file"], f"runtime plugin {name}", leaf=True)
            if not isinstance(plugin["sha256"], str) or SHA256.fullmatch(plugin["sha256"]) is None:
                raise GateFailure("runtime plugin digest is invalid")
            parsed_plugins[name] = {**plugin, "path": path}
        cov = parsed_plugins["pytest_cov.plugin"]
        cov_live = captured_entry_bytes.get(cov["path"])
        if cov_live is None:
            cov_live = _runtime_stable_read(
                cov["path"],
                policy["limits"]["runtime_required_entry_bytes"],
                "pytest-cov plugin",
            )
        cov_live_sha256 = _sha256(cov_live)
        cov_entry = installed_values.get("pytest-cov", {}).get("required_entries", {}).get("pytest_cov/plugin.py")
        if (
            cov["distribution"] != "pytest-cov"
            or cov["entry"] != "pytest_cov/plugin.py"
            or (
                "site_packages" in directory_paths
                and cov["path"] != directory_paths["site_packages"] / "pytest_cov/plugin.py"
            )
            or (
                isinstance(cov_entry, dict)
                and cov["sha256"] != cov_entry.get("sha256")
            )
            or cov["sha256"] != cov_live_sha256
        ):
            raise GateFailure("pytest-cov plugin identity is invalid")
        local = parsed_plugins["scripts.pytest_security_events"]
        if (
            local["distribution"] is not None
            or local["entry"] is not None
            or local["path"] != PYTEST_EVENTS_PLUGIN_PATH.resolve(strict=True)
            or local["sha256"] != _sha256(pytest_events_plugin_content)
        ):
            raise GateFailure("local events plugin identity is invalid")
    except (GateFailure, KeyError, TypeError, OSError, RuntimeError, ValueError):
        if envelope_valid:
            failures.append("PLUGIN_IDENTITY_INVALID")

    if failures:
        return invalid, sorted(set(failures)), facts

    summary = {
        "status": "valid",
        "artifact_sha256": artifact_sha256,
        "schema_version": 2,
        "provenance": record["provenance"],
        "semantic_runtime_sha256": record["semantic_runtime_sha256"],
        "runtime": {
            "implementation": runtime["implementation"],
            "version": runtime["version"],
            "system": runtime["system"],
            "machine": runtime["machine"],
            "executable_sha256": runtime["executable_sha256"],
            "pyvenv_cfg_sha256": runtime["pyvenv_cfg_sha256"],
            "isolated": runtime["isolated"],
            "no_site": runtime["no_site"],
            "dont_write_bytecode": runtime["dont_write_bytecode"],
        },
        "uv": {"version": uv["version"], "sha256": uv["sha256"]},
        "uv_lock_sha256": record["uv_lock_sha256"],
        "distributions": distribution_summary,
        "plugins": {
            name: {
                "sha256": parsed_plugins[name]["sha256"],
                "distribution": parsed_plugins[name]["distribution"],
                "entry": parsed_plugins[name]["entry"],
            }
            for name in RUNTIME_PLUGINS
        },
    }
    return summary, sorted(set(failures)), facts


def _runtime_identity_report(
    content: bytes,
    *,
    raw_was_read: bool = True,
    mode_valid: bool = True,
    run_id: str,
    target: str,
    runner: str,
    attempt: int,
    started_at: str,
    policy: dict[str, Any],
    uv_lock_content: bytes,
    pytest_events_plugin_content: bytes,
) -> tuple[dict[str, Any], list[str]]:
    summary, failures, _facts = _runtime_identity_validation_core(
        content,
        raw_was_read=raw_was_read,
        mode_valid=mode_valid,
        run_id=run_id,
        target=target,
        runner=runner,
        attempt=attempt,
        started_at=started_at,
        policy=policy,
        uv_lock_content=uv_lock_content,
        pytest_events_plugin_content=pytest_events_plugin_content,
    )
    return summary, failures


def _environment(value: dict[str, Any], policy: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    record = _exact(
        value,
        {
            "schema_version",
            "run_id",
            "target",
            "runner",
            "attempt",
            "platform",
            "tools",
            "runtime_identity",
            "repository",
        },
        "environment",
    )
    if type(record["schema_version"]) is not int or record["schema_version"] != 5:
        raise GateFailure("environment.schema_version must be 5")
    if not isinstance(record["run_id"], str) or not RUN_ID.fullmatch(record["run_id"]):
        raise GateFailure("environment.run_id is invalid")
    if (
        not isinstance(record["target"], str)
        or record["target"] not in {"capture", "retention"}
        or not isinstance(record["runner"], str)
        or record["runner"] not in {"macos", "linux"}
    ):
        raise GateFailure("environment scope is invalid")
    _integer(record["attempt"], "environment.attempt", minimum=1)
    platform = _exact(
        record["platform"],
        {"system", "machine", "python_implementation", "python_version"},
        "environment.platform",
    )
    tools = _exact(record["tools"], {"coverage", "pytest", "uv"}, "environment.tools")
    runtime_identity = _exact(
        record["runtime_identity"],
        {"artifact_sha256", "semantic_runtime_sha256"},
        "environment.runtime_identity",
    )
    repository = _exact(
        record["repository"],
        {
            "git_head",
            "base_ref",
            "dirty",
            "source_sha256_before",
            "source_sha256_after",
            "test_sha256_before",
            "test_sha256_after",
            "policy_sha256_before",
            "policy_sha256_after",
            "manifest_sha256_before",
            "manifest_sha256_after",
            "runner_sha256_before",
            "runner_sha256_after",
            "verifier_sha256_before",
            "verifier_sha256_after",
            "bootstrap_sha256_before",
            "bootstrap_sha256_after",
            "pytest_config_sha256_before",
            "pytest_config_sha256_after",
            "pytest_events_plugin_sha256_before",
            "pytest_events_plugin_sha256_after",
            "uv_lock_sha256_before",
            "uv_lock_sha256_after",
            "uv_executable_sha256_before",
            "uv_executable_sha256_after",
        },
        "environment.repository",
    )
    runner_policy = policy["runners"].get(record["runner"])
    if runner_policy is None:
        failures.append("EVIDENCE_SCOPE_INVALID")
    else:
        if (
            platform["system"] != runner_policy["system"]
            or platform["machine"] not in runner_policy["machines"]
            or platform["python_implementation"] != runner_policy["python_implementation"]
            or not isinstance(platform["python_version"], str)
            or not platform["python_version"].startswith(runner_policy["python_major_minor"] + ".")
        ):
            failures.append("EVIDENCE_PLATFORM_INVALID")
    if any(
        item is not None
        and (not isinstance(item, str) or len(item) > 128 or VERSION.fullmatch(item) is None)
        for item in tools.values()
    ):
        raise GateFailure("environment tool versions are invalid")
    if any(
        item is not None and (not isinstance(item, str) or SHA256.fullmatch(item) is None)
        for item in runtime_identity.values()
    ):
        raise GateFailure("environment runtime identity observation is invalid")
    if (
        not isinstance(repository["git_head"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", repository["git_head"])
        or not isinstance(repository["base_ref"], str)
        or not repository["base_ref"]
        or not isinstance(repository["dirty"], bool)
        or not isinstance(repository["source_sha256_before"], str)
        or not SHA256.fullmatch(repository["source_sha256_before"])
        or not isinstance(repository["source_sha256_after"], str)
        or not SHA256.fullmatch(repository["source_sha256_after"])
        or not isinstance(repository["test_sha256_before"], str)
        or not SHA256.fullmatch(repository["test_sha256_before"])
        or not isinstance(repository["test_sha256_after"], str)
        or not SHA256.fullmatch(repository["test_sha256_after"])
        or not isinstance(repository["policy_sha256_before"], str)
        or not SHA256.fullmatch(repository["policy_sha256_before"])
        or not isinstance(repository["policy_sha256_after"], str)
        or not SHA256.fullmatch(repository["policy_sha256_after"])
        or not isinstance(repository["manifest_sha256_before"], str)
        or not SHA256.fullmatch(repository["manifest_sha256_before"])
        or not isinstance(repository["manifest_sha256_after"], str)
        or not SHA256.fullmatch(repository["manifest_sha256_after"])
        or not isinstance(repository["runner_sha256_before"], str)
        or not SHA256.fullmatch(repository["runner_sha256_before"])
        or not isinstance(repository["runner_sha256_after"], str)
        or not SHA256.fullmatch(repository["runner_sha256_after"])
        or not isinstance(repository["verifier_sha256_before"], str)
        or not SHA256.fullmatch(repository["verifier_sha256_before"])
        or not isinstance(repository["verifier_sha256_after"], str)
        or not SHA256.fullmatch(repository["verifier_sha256_after"])
        or not isinstance(repository["bootstrap_sha256_before"], str)
        or not SHA256.fullmatch(repository["bootstrap_sha256_before"])
        or not isinstance(repository["bootstrap_sha256_after"], str)
        or not SHA256.fullmatch(repository["bootstrap_sha256_after"])
        or not isinstance(repository["pytest_config_sha256_before"], str)
        or not SHA256.fullmatch(repository["pytest_config_sha256_before"])
        or not isinstance(repository["pytest_config_sha256_after"], str)
        or not SHA256.fullmatch(repository["pytest_config_sha256_after"])
        or not isinstance(repository["pytest_events_plugin_sha256_before"], str)
        or not SHA256.fullmatch(repository["pytest_events_plugin_sha256_before"])
        or not isinstance(repository["pytest_events_plugin_sha256_after"], str)
        or not SHA256.fullmatch(repository["pytest_events_plugin_sha256_after"])
        or not isinstance(repository["uv_lock_sha256_before"], str)
        or not SHA256.fullmatch(repository["uv_lock_sha256_before"])
        or not isinstance(repository["uv_lock_sha256_after"], str)
        or not SHA256.fullmatch(repository["uv_lock_sha256_after"])
        or not isinstance(repository["uv_executable_sha256_before"], str)
        or not SHA256.fullmatch(repository["uv_executable_sha256_before"])
        or not isinstance(repository["uv_executable_sha256_after"], str)
        or not SHA256.fullmatch(repository["uv_executable_sha256_after"])
    ):
        raise GateFailure("environment.repository is invalid")
    return record, failures


def _command_uv_observation(argv: object) -> dict[str, str] | None:
    if not isinstance(argv, list) or len(argv) < 16 or any(
        not isinstance(item, str) or not item for item in argv
    ):
        return None
    prefixes = (
        "--plugin-identity=",
        "--runtime-uv-path=",
        "--runtime-uv-version=",
        "--runtime-uv-sha256=",
        "--runtime-timestamp=",
    )
    if (
        argv[15] != "--"
        or not all(argv[10 + index].startswith(prefix) for index, prefix in enumerate(prefixes))
        or any(sum(item.startswith(prefix) for item in argv) != 1 for prefix in prefixes)
    ):
        return None
    path = Path(argv[0])
    observed_path = argv[11].removeprefix(prefixes[1])
    version = argv[12].removeprefix(prefixes[2])
    digest = argv[13].removeprefix(prefixes[3])
    timestamp = argv[14].removeprefix(prefixes[4])
    if (
        not path.is_absolute()
        or path != Path(os.path.normpath(os.fspath(path)))
        or not path.name
        or observed_path != os.fspath(path)
        or len(version) > 128
        or VERSION.fullmatch(version) is None
        or SHA256.fullmatch(digest) is None
        or RUNTIME_TIMESTAMP.fullmatch(timestamp) is None
    ):
        return None
    return {
        "path": os.fspath(path),
        "version": version,
        "sha256": digest,
        "timestamp": timestamp,
    }


def _command(
    value: dict[str, Any],
    *,
    target: str,
    policy: dict[str, Any],
    coverage_path: Path,
    junit_path: Path,
    pytest_events_path: Path,
    plugin_identity_path: Path,
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    record = _exact(
        value,
        {
            "schema_version",
            "run_id",
            "target",
            "runner",
            "attempt",
            "argv",
            "sanitized_environment",
            "exit_code",
            "started_at",
            "finished_at",
        },
        "command",
    )
    if type(record["schema_version"]) is not int or record["schema_version"] != 4:
        raise GateFailure("command.schema_version must be 4")
    if not isinstance(record["run_id"], str) or RUN_ID.fullmatch(record["run_id"]) is None:
        raise GateFailure("command.run_id is invalid")
    if (
        not isinstance(record["target"], str)
        or record["target"] not in {"capture", "retention"}
        or not isinstance(record["runner"], str)
        or record["runner"] not in {"macos", "linux"}
    ):
        raise GateFailure("command scope is invalid")
    _integer(record["attempt"], "command.attempt", minimum=1)
    argv = record["argv"]
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) or not item for item in argv)
    ):
        raise GateFailure("command.argv is invalid")
    exit_code = _integer(record["exit_code"], "command.exit_code")
    if exit_code != 0:
        failures.append("COMMAND_FAILED")
    if (
        not isinstance(record["started_at"], str)
        or RUNTIME_TIMESTAMP.fullmatch(record["started_at"]) is None
        or not isinstance(record["finished_at"], str)
        or RUNTIME_TIMESTAMP.fullmatch(record["finished_at"]) is None
    ):
        raise GateFailure("command timestamps are invalid")
    try:
        datetime.strptime(record["started_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        datetime.strptime(record["finished_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise GateFailure("command timestamps are invalid") from exc
    script = policy["scripts"][target]
    required_tokens = {
        script["test_file"],
        "--cov=" + script["module"],
        "--cov-branch",
        "--cov-fail-under=" + str(policy["thresholds"]["coverage_combined_percent"]),
    }
    if not required_tokens.issubset(set(argv)):
        failures.append("COMMAND_SCOPE_INVALID")
    if any(item.startswith("tests/") and item != script["test_file"] for item in argv):
        failures.append("COMMAND_SCOPE_INVALID")
    if any("coverage combine" in item for item in argv):
        failures.append("COMMAND_SCOPE_INVALID")
    if sum(item.startswith("--junitxml=") for item in argv) != 1:
        failures.append("COMMAND_SCOPE_INVALID")
    if sum(item.startswith("--cov-report=json:") for item in argv) != 1:
        failures.append("COMMAND_SCOPE_INVALID")
    uv_observation = _command_uv_observation(argv)
    uv_path = Path(argv[0])
    uv_version = ""
    uv_sha256 = ""
    runtime_timestamp = ""
    if uv_observation is not None:
        option_prefixes = (
            "--plugin-identity=",
            "--runtime-uv-path=",
            "--runtime-uv-version=",
            "--runtime-uv-sha256=",
            "--runtime-timestamp=",
        )
        if all(argv[10 + index].startswith(prefix) for index, prefix in enumerate(option_prefixes)):
            uv_version = uv_observation["version"]
            uv_sha256 = uv_observation["sha256"]
            runtime_timestamp = uv_observation["timestamp"]
    expected_argv = [
        os.fspath(uv_path),
        "run",
        "--offline",
        "--frozen",
        "--no-sync",
        "python",
        "-I",
        "-S",
        "-B",
        str(BOOTSTRAP_PATH.resolve(strict=True)),
        "--plugin-identity=" + str(plugin_identity_path),
        "--runtime-uv-path=" + os.fspath(uv_path),
        "--runtime-uv-version=" + uv_version,
        "--runtime-uv-sha256=" + uv_sha256,
        "--runtime-timestamp=" + runtime_timestamp,
        "--",
        script["test_file"],
        "-q",
        "-c",
        "pyproject.toml",
        "--noconftest",
        "-p",
        "no:cacheprovider",
        "-p",
        "pytest_cov.plugin",
        "-p",
        "scripts.pytest_security_events",
        "-o",
        "xfail_strict=true",
        "--security-events=" + str(pytest_events_path),
        "--security-run-id=" + str(record["run_id"]),
        "--security-target=" + str(record["target"]),
        "--security-runner=" + str(record["runner"]),
        "--security-attempt=" + str(record["attempt"]),
        "--security-test-file=" + script["test_file"],
        "--security-max-cases=" + str(policy["limits"]["testcases"]),
        "--security-max-nodeid-bytes="
        + str(policy["limits"]["pytest_events_nodeid_bytes"]),
        "--security-max-events-bytes=" + str(policy["limits"]["pytest_events_bytes"]),
        "--junitxml=" + str(junit_path),
        "--cov=" + script["module"],
        "--cov-branch",
        "--cov-report=json:" + str(coverage_path),
        "--cov-report=term-missing",
        "--cov-fail-under=" + str(policy["thresholds"]["coverage_combined_percent"]),
    ]
    expected_environment = {
        "COVERAGE_FILE": str(
            coverage_path.parent / (".coverage-" + target)
        ),
        "PYTHONHOME": None,
        "PYTHONPATH": None,
        "PYTHONUSERBASE": None,
        "PYTEST_ADDOPTS": None,
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_PLUGINS": None,
        "UV_PROJECT_ENVIRONMENT": None,
        "UV_PYTHON": None,
    }
    sanitized_environment = _exact(
        record["sanitized_environment"],
        set(expected_environment),
        "command.sanitized_environment",
    )
    if not isinstance(sanitized_environment["COVERAGE_FILE"], str) or any(
        value is not None and not isinstance(value, str)
        for key, value in sanitized_environment.items()
        if key != "COVERAGE_FILE"
    ):
        raise GateFailure("command.sanitized_environment value is invalid")
    if (
        argv != expected_argv
        or sanitized_environment != expected_environment
        or not uv_version
        or len(uv_version) > 128
        or VERSION.fullmatch(uv_version) is None
        or SHA256.fullmatch(uv_sha256) is None
        or runtime_timestamp != record["started_at"]
        or uv_observation is None
    ):
        failures.append("RUNNER_CONFIGURATION_INVALID")
    return record, failures


def _run_manifest(value: dict[str, Any]) -> dict[str, Any]:
    record = _exact(
        value,
        {
            "schema_version",
            "run_id",
            "target",
            "runner",
            "attempt",
            "artifact_hashes",
            "semantic_runtime_sha256",
        },
        "run_manifest",
    )
    if type(record["schema_version"]) is not int or record["schema_version"] != 5:
        raise GateFailure("run_manifest.schema_version must be 5")
    if not isinstance(record["run_id"], str) or not RUN_ID.fullmatch(record["run_id"]):
        raise GateFailure("run_manifest.run_id is invalid")
    if (
        not isinstance(record["target"], str)
        or record["target"] not in {"capture", "retention"}
        or not isinstance(record["runner"], str)
        or record["runner"] not in {"macos", "linux"}
    ):
        raise GateFailure("run_manifest scope is invalid")
    _integer(record["attempt"], "run_manifest.attempt", minimum=1)
    hashes = _exact(
        record["artifact_hashes"],
        {
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
        },
        "run_manifest.artifact_hashes",
    )
    if any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in hashes.values()):
        raise GateFailure("run_manifest artifact hash is invalid")
    semantic = record["semantic_runtime_sha256"]
    if semantic is not None and (
        not isinstance(semantic, str) or SHA256.fullmatch(semantic) is None
    ):
        raise GateFailure("run_manifest semantic runtime hash is invalid")
    return record


def verify_security_coverage(
    *,
    target: str,
    coverage_path: Path,
    junit_path: Path,
    pytest_events_path: Path,
    plugin_identity_path: Path,
    environment_path: Path,
    command_path: Path,
    run_manifest_path: Path,
    policy_path: Path = DEFAULT_POLICY,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> tuple[dict[str, Any], list[str]]:
    policy_content = _read_bounded(policy_path, 1024 * 1024, "policy")
    policy = _parse_policy(policy_content)
    if target not in policy["scripts"]:
        raise GateFailure("unknown security coverage target")
    manifest_content = _read_bounded(manifest_path, 4 * 1024 * 1024, "manifest")
    source_binding_failures: list[str] = []
    source_contents, source_symbols = _frozen_source_material(
        policy,
        binding_failures=source_binding_failures,
    )
    manifest = _parse_manifest(
        manifest_content,
        policy=policy,
        source_symbols=source_symbols,
        binding_failures=source_binding_failures,
    )
    source_content = source_contents[target]
    test_content = _read_bounded(
        REPOSITORY_ROOT / policy["scripts"][target]["test_file"],
        16 * 1024 * 1024,
        "test source",
    )
    runner_content = _read_bounded(RUNNER_PATH, 1024 * 1024, "security coverage runner")
    verifier_content = _read_bounded(
        VERIFIER_PATH, 16 * 1024 * 1024, "security coverage verifier"
    )
    bootstrap_content = _read_bounded(
        BOOTSTRAP_PATH, 4 * 1024 * 1024, "security pytest bootstrap"
    )
    pytest_config_content = _read_bounded(
        PYTEST_CONFIG_PATH, 1024 * 1024, "pytest configuration"
    )
    pytest_events_plugin_content = _read_bounded(
        PYTEST_EVENTS_PLUGIN_PATH, 1024 * 1024, "pytest events plugin"
    )
    uv_lock_content = _read_bounded(UV_LOCK_PATH, 16 * 1024 * 1024, "uv.lock")
    limits = policy["limits"]
    contents = {
        "coverage": _read_bounded(coverage_path, limits["coverage_bytes"], "coverage"),
        "junit": _read_bounded(junit_path, limits["junit_bytes"], "junit"),
        "environment": _read_bounded(environment_path, limits["environment_bytes"], "environment"),
        "command": _read_bounded(command_path, limits["command_bytes"], "command"),
        "run_manifest": _read_bounded(
            run_manifest_path, limits["run_manifest_bytes"], "run_manifest"
        ),
    }
    pytest_events_read_failure = False
    pytest_events_mode_failure = False
    try:
        contents["pytest_events"] = _read_bounded(
            pytest_events_path,
            limits["pytest_events_bytes"],
            "pytest_events",
        )
        pytest_events_mode_failure = stat.S_IMODE(pytest_events_path.stat().st_mode) != 0o600
    except (GateFailure, OSError):
        contents["pytest_events"] = b""
        pytest_events_read_failure = True
    runtime_identity_content, runtime_identity_mode_valid = _read_runtime_identity_artifact(
        plugin_identity_path,
        limits["plugin_identity_bytes"],
    )
    runtime_identity_read_failure = runtime_identity_content is None
    runtime_identity_mode_failure = not runtime_identity_mode_valid
    contents["plugin_identity"] = runtime_identity_content or b""
    coverage = _strict_json(contents["coverage"], "coverage")
    environment_value = _strict_json(contents["environment"], "environment")
    command_value = _strict_json(contents["command"], "command")
    run_manifest_value = _strict_json(contents["run_manifest"], "run_manifest")
    run_manifest = _run_manifest(run_manifest_value)
    environment, environment_failures = _environment(environment_value, policy)
    command, command_failures = _command(
        command_value,
        target=target,
        policy=policy,
        coverage_path=coverage_path,
        junit_path=junit_path,
        pytest_events_path=pytest_events_path,
        plugin_identity_path=plugin_identity_path,
    )
    failures = [
        *source_binding_failures,
        *environment_failures,
        *command_failures,
        *_pytest_configuration_failures(pytest_config_content),
    ]
    scopes = (
        (
            run_manifest["run_id"],
            run_manifest["target"],
            run_manifest["runner"],
            run_manifest["attempt"],
        ),
        (
            environment["run_id"],
            environment["target"],
            environment["runner"],
            environment["attempt"],
        ),
        (command["run_id"], command["target"], command["runner"], command["attempt"]),
    )
    if len(set(scopes)) != 1 or run_manifest["target"] != target:
        failures.append("EVIDENCE_SCOPE_INVALID")
    hashes = run_manifest["artifact_hashes"]
    actual_hashes = {
        "source_sha256": _sha256(source_content),
        "test_sha256": _sha256(test_content),
        "policy_sha256": _sha256(policy_content),
        "manifest_sha256": _sha256(manifest_content),
        "runner_sha256": _sha256(runner_content),
        "verifier_sha256": _sha256(verifier_content),
        "bootstrap_sha256": _sha256(bootstrap_content),
        "pytest_config_sha256": _sha256(pytest_config_content),
        "pytest_events_plugin_sha256": _sha256(pytest_events_plugin_content),
        "uv_lock_sha256": _sha256(uv_lock_content),
        "coverage_sha256": _sha256(contents["coverage"]),
        "junit_sha256": _sha256(contents["junit"]),
        "pytest_events_sha256": _sha256(contents["pytest_events"]),
        "plugin_identity_sha256": (
            None
            if runtime_identity_read_failure
            else _sha256(contents["plugin_identity"])
        ),
        "environment_sha256": _sha256(contents["environment"]),
        "command_sha256": _sha256(contents["command"]),
    }
    toolchain_hashes = {
        "runner_sha256",
        "verifier_sha256",
        "bootstrap_sha256",
        "pytest_config_sha256",
        "pytest_events_plugin_sha256",
        "uv_lock_sha256",
        "plugin_identity_sha256",
    }
    if any(
        actual_hashes[key] is not None and hashes[key] != actual_hashes[key]
        for key in toolchain_hashes
    ):
        failures.append("EVIDENCE_TOOLCHAIN_BINDING_INVALID")
    evidence_hashes = actual_hashes.keys() - toolchain_hashes
    if pytest_events_read_failure:
        evidence_hashes = evidence_hashes - {"pytest_events_sha256"}
    if any(hashes[key] != actual_hashes[key] for key in evidence_hashes):
        failures.append("EVIDENCE_BINDING_INVALID")
    if (
        environment["repository"]["source_sha256_before"] != actual_hashes["source_sha256"]
        or environment["repository"]["source_sha256_after"] != actual_hashes["source_sha256"]
        or environment["repository"]["test_sha256_before"] != actual_hashes["test_sha256"]
        or environment["repository"]["test_sha256_after"] != actual_hashes["test_sha256"]
        or environment["repository"]["policy_sha256_before"] != actual_hashes["policy_sha256"]
        or environment["repository"]["policy_sha256_after"] != actual_hashes["policy_sha256"]
        or environment["repository"]["manifest_sha256_before"] != actual_hashes["manifest_sha256"]
        or environment["repository"]["manifest_sha256_after"] != actual_hashes["manifest_sha256"]
    ):
        failures.append("EVIDENCE_BINDING_INVALID")
    if any(
        environment["repository"][name + "_sha256_before"]
        != actual_hashes[name + "_sha256"]
        or environment["repository"][name + "_sha256_after"]
        != actual_hashes[name + "_sha256"]
        for name in (
            "runner",
            "verifier",
            "bootstrap",
            "pytest_config",
            "pytest_events_plugin",
            "uv_lock",
        )
    ):
        failures.append("EVIDENCE_TOOLCHAIN_BINDING_INVALID")
    junit_cases, _, invalid_junit_nodeids = _junit_cases(
        contents["junit"],
        policy["limits"]["testcases"],
        test_file=policy["scripts"][target]["test_file"],
    )
    (
        pytest_events_report,
        xfail_nodeids,
        invalid_event_nodeids,
        pytest_events_failures,
    ) = _pytest_events_report(
        contents["pytest_events"],
        run_id=run_manifest["run_id"],
        target=target,
        runner=run_manifest["runner"],
        attempt=run_manifest["attempt"],
        test_file=policy["scripts"][target]["test_file"],
        junit_cases=None if invalid_junit_nodeids else junit_cases,
        limits=policy["limits"],
    )
    if pytest_events_read_failure:
        pytest_events_failures.append("PYTEST_EVENTS_INVALID")
    if pytest_events_mode_failure:
        pytest_events_failures.append("PYTEST_EVENTS_INVALID")
    (
        runtime_identity_report,
        runtime_identity_failures,
        runtime_identity_facts,
    ) = _runtime_identity_validation_core(
        contents["plugin_identity"],
        raw_was_read=not runtime_identity_read_failure,
        mode_valid=not runtime_identity_mode_failure,
        run_id=run_manifest["run_id"],
        target=target,
        runner=run_manifest["runner"],
        attempt=run_manifest["attempt"],
        started_at=command["started_at"],
        policy=policy,
        uv_lock_content=uv_lock_content,
        pytest_events_plugin_content=pytest_events_plugin_content,
    )
    runtime_raw_sha = actual_hashes["plugin_identity_sha256"]
    environment_runtime = environment["runtime_identity"]
    if runtime_raw_sha is not None and (
        hashes["plugin_identity_sha256"] != runtime_raw_sha
        or environment_runtime["artifact_sha256"] != runtime_raw_sha
    ):
        failures.append("EVIDENCE_TOOLCHAIN_BINDING_INVALID")
    if (
        environment["repository"]["uv_executable_sha256_before"]
        != environment["repository"]["uv_executable_sha256_after"]
    ):
        failures.append("EVIDENCE_TOOLCHAIN_BINDING_INVALID")
    semantic = runtime_identity_facts["semantic_runtime_sha256"]
    if semantic is not None and (
        run_manifest["semantic_runtime_sha256"] != semantic
        or environment_runtime["semantic_runtime_sha256"] != semantic
    ):
        failures.append("EVIDENCE_TOOLCHAIN_BINDING_INVALID")
    uv_fact = runtime_identity_facts["uv"]
    if uv_fact is not None:
        if (
            environment["repository"]["uv_executable_sha256_before"] != uv_fact["sha256"]
            or environment["tools"]["uv"] != uv_fact["version"]
        ):
            failures.append("EVIDENCE_TOOLCHAIN_BINDING_INVALID")
        command_uv = _command_uv_observation(command["argv"])
        if command_uv is not None and (
            command_uv["path"] != uv_fact["path"]
            or command_uv["version"] != uv_fact["version"]
            or command_uv["sha256"] != uv_fact["sha256"]
        ):
            failures.append("EVIDENCE_TOOLCHAIN_BINDING_INVALID")
    distribution_versions = runtime_identity_facts["distribution_versions"]
    if "coverage" in distribution_versions and environment["tools"]["coverage"] != distribution_versions["coverage"]:
        failures.append("EVIDENCE_TOOLCHAIN_BINDING_INVALID")
    if "pytest" in distribution_versions and environment["tools"]["pytest"] != distribution_versions["pytest"]:
        failures.append("EVIDENCE_TOOLCHAIN_BINDING_INVALID")
    coverage_report, coverage_failures = _coverage_report(
        coverage, target=target, policy=policy, manifest=manifest
    )
    junit_report, junit_failures = _junit_report(
        contents["junit"],
        target=target,
        runner=run_manifest["runner"],
        policy=policy,
        manifest=manifest,
        xfail_nodeids=xfail_nodeids,
        invalid_event_nodeids=invalid_event_nodeids,
    )
    failures.extend(coverage_failures)
    failures.extend(pytest_events_failures)
    failures.extend(runtime_identity_failures)
    failures.extend(junit_failures)
    failures = sorted(set(failures))
    capability_ids = sorted(
        capability["id"]
        for capability in manifest["capabilities"]
        if any(record["script"] == target for record in capability["targets"])
    )
    report = {
        "schema_version": 5,
        "gate": "security-coverage",
        "target": target,
        "run_id": run_manifest["run_id"],
        "runner": run_manifest["runner"],
        "attempt": run_manifest["attempt"],
        "coverage": coverage_report,
        "junit": junit_report,
        "pytest_events": pytest_events_report,
        "runtime_identity": runtime_identity_report,
        "capabilities": capability_ids,
        "artifact_hashes": actual_hashes,
        "passed": not failures,
        "failures": failures,
    }
    return report, failures


def _write_exclusive(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise GateFailure("invalid command line")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=("capture", "retention"))
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--pytest-events", required=True, type=Path)
    parser.add_argument("--plugin-identity", required=True, type=Path)
    parser.add_argument("--environment", required=True, type=Path)
    parser.add_argument("--command", required=True, type=Path)
    parser.add_argument("--run-manifest", required=True, type=Path)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        report, failures = verify_security_coverage(
            target=arguments.target,
            coverage_path=arguments.coverage,
            junit_path=arguments.junit,
            pytest_events_path=arguments.pytest_events,
            plugin_identity_path=arguments.plugin_identity,
            environment_path=arguments.environment,
            command_path=arguments.command,
            run_manifest_path=arguments.run_manifest,
            policy_path=arguments.policy,
            manifest_path=arguments.manifest,
        )
        content = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if arguments.output is None:
            sys.stdout.buffer.write(content)
        else:
            _write_exclusive(arguments.output, content)
        return 0 if not failures else 1
    except (GateFailure, OSError, ValueError, TypeError, KeyError):
        sys.stderr.write("SECURITY_COVERAGE_INPUT_INVALID\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
