#!/usr/bin/env python3
"""Verify diff/critical coverage and zero-skip pytest layer evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 gate
    import tomli as tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = REPOSITORY_ROOT / "packaging/quality-gates.toml"
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
EVIDENCE_RUN_ID_ENV = "AI_AUTO_LRC_EVIDENCE_RUN_ID"
EVIDENCE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class GateFailure(RuntimeError):
    """Raised when evidence does not satisfy a declared local gate."""


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    policy = tomllib.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 1:
        raise GateFailure("quality gate policy schema_version must be 1")
    return policy


def _git(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GateFailure(result.stderr.strip() or f"git {' '.join(arguments)} failed")
    return result.stdout


def changed_python_lines(
    repo_root: Path,
    base_ref: str,
    *,
    source_root: str,
    excluded_paths: set[str],
) -> dict[str, set[int]]:
    """Return added/modified current line numbers, including untracked files."""

    _git(repo_root, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
    patch = _git(
        repo_root,
        "diff",
        "--no-ext-diff",
        "--no-color",
        "--unified=0",
        base_ref,
        "--",
        source_root,
    )
    changed: dict[str, set[int]] = defaultdict(set)
    current_path: str | None = None
    for line in patch.splitlines():
        if line.startswith("+++ "):
            value = line[4:]
            current_path = None if value == "/dev/null" else value.removeprefix("b/")
            continue
        match = HUNK.match(line)
        if match is None or current_path is None:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        if count:
            changed[current_path].update(range(start, start + count))

    untracked = _git(
        repo_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        source_root,
    )
    for relative in untracked.splitlines():
        path = repo_root / relative
        if path.is_file() and path.suffix == ".py":
            line_count = len(path.read_text(encoding="utf-8").splitlines())
            changed[relative].update(range(1, line_count + 1))

    return {
        path: lines
        for path, lines in changed.items()
        if path.endswith(".py") and path not in excluded_paths
    }


def _percent(covered: int, total: int) -> float:
    return 100.0 if total == 0 else covered * 100.0 / total


def coverage_gate_report(
    coverage: dict[str, Any],
    changed: dict[str, set[int]],
    policy: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    if coverage.get("meta", {}).get("branch_coverage") is not True:
        failures.append("coverage JSON was not produced with branch coverage enabled")

    files = coverage.get("files", {})
    coverage_policy = policy["coverage"]
    line_threshold = int(coverage_policy["overall_line_percent"])
    totals = coverage.get("totals", {})
    covered_lines = int(totals.get("covered_lines", 0))
    statement_count = int(totals.get("num_statements", 0))
    overall_line = _percent(covered_lines, statement_count)
    if overall_line < line_threshold:
        failures.append(
            f"overall line coverage {overall_line:.2f}% is below {line_threshold}%"
        )

    diff_files: dict[str, Any] = {}
    diff_covered = 0
    diff_total = 0
    for path in sorted(changed):
        record = files.get(path)
        if record is None:
            failures.append(f"changed source file has no coverage record: {path}")
            continue
        executable = set(record["executed_lines"]) | set(record["missing_lines"])
        changed_executable = sorted(changed[path] & executable)
        executed = set(record["executed_lines"])
        missing = sorted(set(changed_executable) - executed)
        covered = len(changed_executable) - len(missing)
        diff_covered += covered
        diff_total += len(changed_executable)
        if changed_executable:
            diff_files[path] = {
                "covered": covered,
                "executable": len(changed_executable),
                "missing_lines": missing,
            }

    diff_threshold = int(coverage_policy["diff_line_percent"])
    diff_percent = _percent(diff_covered, diff_total)
    if diff_total == 0:
        failures.append("diff coverage has no changed executable lines")
    elif diff_percent < diff_threshold:
        failures.append(
            f"diff line coverage {diff_percent:.2f}% is below {diff_threshold}%"
        )

    critical: list[dict[str, Any]] = []
    for target in policy["critical_targets"]:
        path = target["path"]
        function = target["function"]
        try:
            summary = files[path]["functions"][function]["summary"]
        except KeyError:
            failures.append(f"critical coverage target is missing: {path}:{function}")
            continue
        statements = int(summary["num_statements"])
        lines_covered = int(summary["covered_lines"])
        branches = int(summary["num_branches"])
        branches_covered = int(summary["covered_branches"])
        line_percent = _percent(lines_covered, statements)
        branch_percent = _percent(branches_covered, branches)
        result = {
            "category": target["category"],
            "path": path,
            "function": function,
            "line_percent": line_percent,
            "branch_percent": branch_percent,
            "branches": branches,
        }
        critical.append(result)
        if line_percent != 100.0 or branch_percent != 100.0:
            failures.append(
                f"critical target {path}:{function} requires 100% line/branch; "
                f"got {line_percent:.2f}%/{branch_percent:.2f}%"
            )

    report = {
        "schema_version": 1,
        "gate": "coverage",
        "overall_line": {
            "covered": covered_lines,
            "statements": statement_count,
            "percent": overall_line,
            "required_percent": line_threshold,
        },
        "diff_line": {
            "covered": diff_covered,
            "executable": diff_total,
            "percent": diff_percent,
            "required_percent": diff_threshold,
            "files": diff_files,
        },
        "critical_targets": critical,
        "passed": not failures,
        "failures": failures,
    }
    return report, failures


def junit_gate_report(
    junit_path: Path,
    layer: str,
    policy: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    layer_policy = policy["pytest_layers"].get(layer)
    if layer_policy is None:
        raise GateFailure(f"unknown pytest evidence layer: {layer}")
    root = ET.parse(junit_path).getroot()
    cases = root.findall(".//testcase")
    prefixes = tuple(layer_policy["allowed_classname_prefixes"])
    skipped = [case for case in cases if case.find("skipped") is not None]
    failures_and_errors = [
        case
        for case in cases
        if case.find("failure") is not None or case.find("error") is not None
    ]
    outside = [
        f"{case.get('classname')}::{case.get('name')}"
        for case in cases
        if not (case.get("classname") or "").startswith(prefixes)
    ]
    failures: list[str] = []
    if not cases:
        failures.append(f"{layer} JUnit contains no test cases")
    if failures_and_errors:
        failures.append(
            f"{layer} JUnit contains {len(failures_and_errors)} failures/errors"
        )
    if layer_policy["zero_skip"] and skipped:
        failures.append(f"{layer} required gate contains {len(skipped)} skipped tests")
    if outside:
        failures.append(
            f"{layer} evidence contains tests from another layer: {outside[:5]}"
        )

    report = {
        "schema_version": 1,
        "gate": "pytest-layer",
        "layer": layer,
        "required_markers": layer_policy["required_markers"],
        "tests": len(cases),
        "skipped": len(skipped),
        "failures_or_errors": len(failures_and_errors),
        "outside_layer": outside,
        "passed": not failures,
        "failures": failures,
    }
    return report, failures


def _write_report(report: dict[str, Any], output: Path | None) -> None:
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(payload)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_run_id(cli_run_id: str | None) -> str | None:
    environment_run_id = os.environ.get(EVIDENCE_RUN_ID_ENV)
    if (
        cli_run_id is not None
        and environment_run_id is not None
        and cli_run_id != environment_run_id
    ):
        raise GateFailure(f"--run-id does not match {EVIDENCE_RUN_ID_ENV}")
    run_id = cli_run_id if cli_run_id is not None else environment_run_id
    if run_id is not None and EVIDENCE_RUN_ID.fullmatch(run_id) is None:
        raise GateFailure(
            "run_id must be 1-128 ASCII letters, digits, dots, underscores, or hyphens"
        )
    return run_id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    subparsers = parser.add_subparsers(dest="command", required=True)

    coverage_parser = subparsers.add_parser("coverage")
    coverage_parser.add_argument("--coverage-json", type=Path, required=True)
    coverage_parser.add_argument("--base-ref", required=True)
    coverage_parser.add_argument("--repo-root", type=Path, default=REPOSITORY_ROOT)
    coverage_parser.add_argument("--run-id")
    coverage_parser.add_argument("--output", type=Path)

    junit_parser = subparsers.add_parser("junit")
    junit_parser.add_argument("--junit-xml", type=Path, required=True)
    junit_parser.add_argument(
        "--layer", choices=("portable", "package", "canonical"), required=True
    )
    junit_parser.add_argument("--run-id")
    junit_parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        run_id = _resolve_run_id(arguments.run_id)
        policy = load_policy(arguments.policy)
        if arguments.command == "coverage":
            coverage = json.loads(arguments.coverage_json.read_text(encoding="utf-8"))
            coverage_policy = policy["coverage"]
            changed = changed_python_lines(
                arguments.repo_root.resolve(),
                arguments.base_ref,
                source_root=coverage_policy["source_root"],
                excluded_paths=set(coverage_policy["excluded_paths"]),
            )
            report, failures = coverage_gate_report(coverage, changed, policy)
            report["input_coverage_sha256"] = _sha256(arguments.coverage_json)
            report["policy_sha256"] = _sha256(arguments.policy)
            report["base_ref"] = arguments.base_ref
        else:
            report, failures = junit_gate_report(
                arguments.junit_xml, arguments.layer, policy
            )
            report["input_junit_sha256"] = _sha256(arguments.junit_xml)
            report["policy_sha256"] = _sha256(arguments.policy)
        report["run_id"] = run_id
        _write_report(report, arguments.output)
    except (GateFailure, OSError, ValueError, ET.ParseError) as error:
        sys.stderr.write(f"quality gate evidence error: {error}\n")
        return 2
    if failures:
        for failure in failures:
            sys.stderr.write(f"quality gate failed: {failure}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
