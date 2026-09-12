from __future__ import annotations

import copy
import errno
import hashlib
import importlib
import inspect
import json
import os
import select
import signal
import socket
import stat
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from scripts import capture_test_gate

_DELETE = object()
_SECRET = b"sentinel-secret-contract-value"
_CHUNK_BYTES = 64
_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts/manage_evidence_retention.py"
_CRASH_WORKER = _ROOT / "tests/fixtures/retention_crash_worker.py"
_DEFAULT_RULES = _ROOT / "packaging/evidence-secret-rules.json"
_DEFAULT_ASSESSMENT = _ROOT / "packaging/evidence-retention-assessment.json"


@dataclass(frozen=True, slots=True)
class SealedRun:
    repo: Path
    retention: Path
    receipt: Path


@pytest.fixture
def manager() -> ModuleType:
    return importlib.import_module("scripts.manage_evidence_retention")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_runner(path: Path) -> None:
    path.write_text(
        """#!/bin/sh
set -eu
artifact_root="$AI_AUTO_LRC_GATE_ARTIFACT_DIR"
mkdir -p "$artifact_root"
printf '<testsuites><testsuite><testcase classname="tests.unit.test_fake" name="test_ok"/></testsuite></testsuites>\n' > "$artifact_root/portable.xml"
printf '{"meta":{"branch_coverage":true}}\n' > "$artifact_root/coverage.json"
junit_sha=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$artifact_root/portable.xml")
coverage_sha=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$artifact_root/coverage.json")
printf '{"schema_version":1,"gate":"pytest-layer","layer":"portable","passed":true,"tests":1,"skipped":0,"failures_or_errors":0,"run_id":"%s","input_junit_sha256":"%s","policy_sha256":"%s"}\n' "$AI_AUTO_LRC_EVIDENCE_RUN_ID" "$junit_sha" "$AI_AUTO_LRC_EVIDENCE_POLICY_SHA256" > "$artifact_root/portable-gate.json"
printf '{"schema_version":1,"gate":"coverage","passed":true,"run_id":"%s","input_coverage_sha256":"%s","policy_sha256":"%s","base_ref":"%s"}\n' "$AI_AUTO_LRC_EVIDENCE_RUN_ID" "$coverage_sha" "$AI_AUTO_LRC_EVIDENCE_POLICY_SHA256" "$AI_AUTO_LRC_EVIDENCE_BASE_REF" > "$artifact_root/coverage-gate.json"
printf 'stdout bytes\n'
printf 'stderr bytes\n' >&2
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


@pytest.fixture
def sealed_run_factory(tmp_path: Path) -> Callable[..., SealedRun]:
    counter = 0

    def factory(*, untracked: dict[str, bytes] | None = None) -> SealedRun:
        nonlocal counter
        counter += 1
        root = tmp_path / f"case-{counter}"
        repo = root / "repo"
        scripts = repo / "scripts"
        scripts.mkdir(parents=True)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "retention@example.invalid")
        _git(repo, "config", "user.name", "Retention Contract")
        (repo / "uv.lock").write_text("lock\n", encoding="utf-8")
        (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        quality_policy = repo / "packaging/quality-gates.toml"
        quality_policy.parent.mkdir()
        quality_policy.write_text("schema_version = 1\n", encoding="utf-8")
        _write_runner(scripts / "run_test_gate.sh")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "baseline")
        for name, content in (untracked or {}).items():
            destination = repo / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        retention = root / "retention"
        retention.mkdir()
        result = capture_test_gate.capture_gate(
            repo_root=repo,
            retention_root=retention,
            layer="portable",
            base_ref="HEAD",
        )
        assert result.exit_code == 0
        assert result.run_directory is not None
        return SealedRun(repo, retention, result.run_directory / "receipt.json")

    return factory


def _rule(
    rule_id: str,
    *,
    category: str,
    matcher: str,
    terms: list[str],
    max_value_bytes: int = 0,
) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "category": category,
        "matcher": matcher,
        "terms": terms,
        "max_value_bytes": max_value_bytes,
    }


def _rules() -> dict[str, Any]:
    return {
        "schema": "ai-auto-lrc/evidence-secret-rules",
        "schema_version": 1,
        "rule_set_id": "w1b5-assessment-v1",
        "scanner_id": "ai-auto-lrc-byte-scanner-v1",
        "chunk_bytes": _CHUNK_BYTES,
        "rules": [
            _rule(
                "SEC-ASSIGNMENT",
                category="credential",
                matcher="assignment-value-ascii-ci",
                terms=["api_key", "secret", "token"],
                max_value_bytes=64,
            ),
            _rule(
                "SEC-AUTH-SCHEME",
                category="credential",
                matcher="scheme-value-ascii-ci",
                terms=["Basic", "Bearer"],
                max_value_bytes=64,
            ),
            _rule(
                "SEC-HOME",
                category="privacy",
                matcher="literal-ascii",
                terms=["/Users/", "/home/"],
            ),
            _rule(
                "SEC-PRIVATE-KEY",
                category="credential",
                matcher="literal-ascii",
                terms=["-----BEGIN PRIVATE KEY-----"],
            ),
            _rule(
                "SEC-SENTINEL",
                category="credential",
                matcher="literal-ascii-ci",
                terms=["sentinel-secret"],
            ),
        ],
    }


def _assessment(rules_content: bytes) -> dict[str, Any]:
    unresolved = {
        "decision_id": None,
        "status": "unresolved",
        "value": None,
    }
    return {
        "schema": "ai-auto-lrc/retention-assessment",
        "schema_version": 1,
        "assessment_id": "w1b5-local-assessment-v1",
        "created_at_utc": "2026-09-06T00:00:00Z",
        "mode": "assessment-only",
        "decision_state": "pending-human-approval",
        "capabilities": {
            "archive": False,
            "destroy": False,
            "expire": False,
            "inspect": True,
            "prepare_export": False,
            "scan": True,
        },
        "classifications": sorted(
            {
                "metadata",
                "captured-input",
                "test-evidence",
                "source-raw",
                "log-raw",
                "checkpoint",
                "unknown",
            }
        ),
        "decisions": {
            key: copy.deepcopy(unresolved)
            for key in (
                "approval_count",
                "approval_ttl_seconds",
                "archive_provider",
                "checkpoint_strategy",
                "destruction",
                "evidence_owner",
                "export_classes",
                "export_purposes",
                "key_custody",
                "key_rotation",
                "release_owner",
                "retention_by_class",
                "rpo_hours",
                "rto_hours",
                "security_owner",
                "tombstone_days",
            )
        },
        "scanner": {
            "rule_set_id": "w1b5-assessment-v1",
            "rule_set_sha256": _sha256(rules_content),
            "max_file_bytes": 4 * 1024 * 1024,
            "on_error": "block",
        },
    }


def _change_path(document: dict[str, Any], dotted_path: str, value: object) -> None:
    target: Any = document
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    final: str | int = int(parts[-1]) if isinstance(target, list) else parts[-1]
    if value is _DELETE:
        del target[final]
    else:
        target[final] = value


def _write_config(
    root: Path,
    *,
    rules: dict[str, Any] | None = None,
    assessment_mutation: tuple[str, object] | None = None,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    rules_document = copy.deepcopy(rules or _rules())
    rules_path = root / "evidence-secret-rules.json"
    rules_content = _json_bytes(rules_document)
    rules_path.write_bytes(rules_content)
    assessment_document = _assessment(rules_content)
    if assessment_mutation is not None:
        _change_path(assessment_document, *assessment_mutation)
    assessment_path = root / "evidence-retention-assessment.json"
    assessment_path.write_bytes(_json_bytes(assessment_document))
    return rules_path, assessment_path


def _inspect(
    manager: ModuleType,
    run: SealedRun,
    rules_path: Path,
    assessment_path: Path,
) -> object:
    arguments: dict[str, object] = {
        "receipt": run.receipt,
        "rules_path": rules_path,
        "assessment_path": assessment_path,
        "actor": "contract-test",
    }
    parameters = inspect.signature(manager.inspect_run).parameters
    if "expected_rules_sha256" in parameters:
        arguments["expected_rules_sha256"] = _sha256(rules_path.read_bytes())
    if "expected_assessment_sha256" in parameters:
        arguments["expected_assessment_sha256"] = _sha256(
            assessment_path.read_bytes()
        )
    return manager.inspect_run(**arguments)


def _inspect_with_expected_digests(
    manager: ModuleType,
    run: SealedRun,
    rules_path: Path,
    assessment_path: Path,
    *,
    expected_rules_sha256: str,
    expected_assessment_sha256: str,
) -> object:
    return manager.inspect_run(
        receipt=run.receipt,
        rules_path=rules_path,
        assessment_path=assessment_path,
        actor="contract-test",
        expected_rules_sha256=expected_rules_sha256,
        expected_assessment_sha256=expected_assessment_sha256,
    )


def _load_rules(manager: ModuleType, rules_path: Path) -> object:
    parameters = inspect.signature(manager.load_secret_rules).parameters
    if "expected_sha256" in parameters:
        return manager.load_secret_rules(
            rules_path,
            expected_sha256=_sha256(rules_path.read_bytes()),
        )
    return manager.load_secret_rules(rules_path)


def _load_assessment(
    manager: ModuleType,
    assessment_path: Path,
    rules_path: Path,
) -> object:
    rules = _load_rules(manager, rules_path)
    parameters = inspect.signature(manager.load_retention_assessment).parameters
    if "rules" in parameters:
        return manager.load_retention_assessment(
            assessment_path,
            rules=rules,
            expected_sha256=_sha256(assessment_path.read_bytes()),
        )
    return manager.load_retention_assessment(
        assessment_path,
        rules_sha256=rules.sha256,
    )


def _verify(
    manager: ModuleType,
    run: SealedRun,
    result: object,
    rules_path: Path,
    assessment_path: Path,
) -> None:
    arguments: dict[str, object] = {
        "receipt": run.receipt,
        "inspection": result.inspection_path,
        "control_event": result.control_event_path,
        "rules_path": rules_path,
        "assessment_path": assessment_path,
    }
    parameters = inspect.signature(manager.verify_inspection).parameters
    if "expected_rules_sha256" in parameters:
        arguments["expected_rules_sha256"] = _sha256(rules_path.read_bytes())
    if "expected_assessment_sha256" in parameters:
        arguments["expected_assessment_sha256"] = _sha256(
            assessment_path.read_bytes()
        )
    manager.verify_inspection(**arguments)


def _verify_paths(
    manager: ModuleType,
    run: SealedRun,
    inspection_path: Path,
    event_path: Path,
    rules_path: Path,
    assessment_path: Path,
) -> object:
    arguments: dict[str, object] = {
        "receipt": run.receipt,
        "inspection": inspection_path,
        "control_event": event_path,
        "rules_path": rules_path,
        "assessment_path": assessment_path,
    }
    parameters = inspect.signature(manager.verify_inspection).parameters
    if "expected_rules_sha256" in parameters:
        arguments["expected_rules_sha256"] = _sha256(rules_path.read_bytes())
    if "expected_assessment_sha256" in parameters:
        arguments["expected_assessment_sha256"] = _sha256(
            assessment_path.read_bytes()
        )
    return manager.verify_inspection(**arguments)


def _assert_error(manager: ModuleType, code: str, call: Callable[[], object]) -> None:
    with pytest.raises(manager.RetentionError) as raised:
        call()
    assert raised.value.code == code
    assert _SECRET.decode() not in str(raised.value)


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int, str | None]]:
    result: dict[str, tuple[str, int, str | None]] = {}
    for path in [root, *sorted(root.rglob("*"))]:
        item_stat = path.lstat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        if stat.S_ISREG(item_stat.st_mode):
            result[relative] = (
                "file",
                stat.S_IMODE(item_stat.st_mode),
                _sha256(path.read_bytes()),
            )
        elif stat.S_ISDIR(item_stat.st_mode):
            result[relative] = ("directory", stat.S_IMODE(item_stat.st_mode), None)
        elif stat.S_ISLNK(item_stat.st_mode):
            result[relative] = ("symlink", stat.S_IMODE(item_stat.st_mode), os.readlink(path))
        else:
            result[relative] = ("special", stat.S_IMODE(item_stat.st_mode), None)
    return result


def _seal_snapshot_fixture(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        path.chmod(0o500 if path.is_dir() else 0o400)


def _unseal_snapshot_fixture(root: Path) -> None:
    if not root.exists():
        return
    root.chmod(0o700)
    for path in root.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)


def _scan_path(result: object) -> Path:
    return result.inspection_path / "secret-scan.json"


def _complete_path(result: object) -> Path:
    return result.inspection_path / "COMPLETE"


def _rewrite_private(path: Path, content: bytes) -> None:
    parent = path.parent
    original_parent_mode = stat.S_IMODE(parent.stat().st_mode)
    original_mode = stat.S_IMODE(path.stat().st_mode)
    parent.chmod(0o700)
    path.chmod(0o600)
    path.write_bytes(content)
    path.chmod(original_mode)
    parent.chmod(original_parent_mode)


def _assert_no_sensitive_material(*values: bytes | str) -> None:
    forbidden = (
        _SECRET,
        _SECRET.hex().encode(),
        str(Path.home()).encode(),
        b"/Users/",
        b"pattern_base64",
    )
    for value in values:
        content = value if isinstance(value, bytes) else value.encode()
        for item in forbidden:
            assert item not in content


# P0: every path component must be trusted before any read or control write.


@pytest.mark.parametrize(
    "mutation",
    (
        ("schema", _DELETE),
        ("unknown", "forbidden"),
        ("schema_version", True),
        ("scanner_id", 7),
        ("rules", []),
    ),
    ids=("missing", "unknown", "bool-as-int", "wrong-type", "empty-rules"),
)
def test_ret_t01_rules_reject_missing_unknown_and_wrong_typed_keys(
    manager: ModuleType,
    tmp_path: Path,
    mutation: tuple[str, object],
) -> None:
    rules = _rules()
    _change_path(rules, *mutation)
    rules_path = tmp_path / "rules.json"
    rules_path.write_bytes(_json_bytes(rules))

    _assert_error(
        manager,
        "RULE_SCHEMA_INVALID",
        lambda: _load_rules(manager, rules_path),
    )


@pytest.mark.parametrize(
    "mutation,expected_code",
    (
        (("decisions.security_owner", _DELETE), "ASSESSMENT_SCHEMA_INVALID"),
        (("decisions.unknown", None), "ASSESSMENT_SCHEMA_INVALID"),
        (("scanner.max_file_bytes", True), "ASSESSMENT_SCHEMA_INVALID"),
        (("classifications", ["source-raw"]), "ASSESSMENT_SCHEMA_INVALID"),
        (("capabilities.prepare_export", True), "ASSESSMENT_NOT_SAFE"),
        (("decisions.archive_provider.status", "resolved"), "ASSESSMENT_NOT_SAFE"),
        (("decisions.rpo_hours.value", 24), "ASSESSMENT_NOT_SAFE"),
        (("capabilities.destroy", True), "ASSESSMENT_NOT_SAFE"),
    ),
    ids=(
        "nested-missing",
        "nested-unknown",
        "bool-as-int",
        "classification-incomplete",
        "prepare-export-enabled",
        "archive-provider",
        "recovery-claim",
        "destruction-enabled",
    ),
)
def test_ret_t01_assessment_rejects_missing_unknown_and_wrong_typed_keys(
    manager: ModuleType,
    tmp_path: Path,
    mutation: tuple[str, object],
    expected_code: str,
) -> None:
    rules_path, assessment_path = _write_config(
        tmp_path / "config",
        assessment_mutation=mutation,
    )

    _assert_error(
        manager,
        expected_code,
        lambda: _load_assessment(manager, assessment_path, rules_path),
    )


@pytest.mark.parametrize(
    "mutation",
    (
        ("rules.1.rule_id", "SEC-ASSIGNMENT"),
        ("rules.0.rule_id", "ZZZ-UNSORTED"),
        ("rules.0.terms", ["token", "api_key", "secret"]),
        ("rules.0.terms", ["api_key", "api_key"]),
    ),
    ids=("duplicate-id", "unsorted-id", "unsorted-terms", "duplicate-terms"),
)
def test_ret_t01_rules_reject_duplicate_or_unsorted_ids_and_terms(
    manager: ModuleType,
    tmp_path: Path,
    mutation: tuple[str, object],
) -> None:
    rules = _rules()
    _change_path(rules, *mutation)
    rules_path = tmp_path / "rules.json"
    rules_path.write_bytes(_json_bytes(rules))

    _assert_error(
        manager,
        "RULE_SCHEMA_INVALID",
        lambda: _load_rules(manager, rules_path),
    )


@pytest.mark.parametrize(
    "mutation,expected_code",
    (
        (("decisions.evidence_owner.value", "TODO"), "ASSESSMENT_NOT_SAFE"),
        (("decisions.security_owner.value", "placeholder"), "ASSESSMENT_NOT_SAFE"),
        (("operational", True), "ASSESSMENT_SCHEMA_INVALID"),
        (("mode", "operational"), "ASSESSMENT_NOT_SAFE"),
    ),
    ids=("todo-owner", "placeholder-owner", "operational-flag", "operational-mode"),
)
def test_ret_t12_operational_or_placeholder_assessment_is_rejected(
    manager: ModuleType,
    tmp_path: Path,
    mutation: tuple[str, object],
    expected_code: str,
) -> None:
    rules_path, assessment_path = _write_config(
        tmp_path / "config",
        assessment_mutation=mutation,
    )

    _assert_error(
        manager,
        expected_code,
        lambda: _load_assessment(manager, assessment_path, rules_path),
    )


def test_ret_t02_invalid_receipt_publishes_no_control_state(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    rules_path, policy_path = _write_config(tmp_path / "config")
    sealed = run.receipt.parent / "SEALED"
    run.receipt.parent.chmod(0o700)
    sealed.chmod(0o600)
    sealed.write_bytes(sealed.read_bytes() + b"tampered")
    sealed.chmod(0o400)
    run.receipt.parent.chmod(0o500)

    _assert_error(
        manager,
        "RECEIPT_INVALID",
        lambda: _inspect(manager, run, rules_path, policy_path),
    )
    assert not (run.retention / ".control").exists()


def test_ret_t04_receipt_parent_symlink_is_rejected(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    before = _tree_snapshot(run.receipt.parent)
    rules_path, policy_path = _write_config(tmp_path / "config")
    alias = tmp_path / "aliased-run"
    alias.symlink_to(run.receipt.parent, target_is_directory=True)

    _assert_error(
        manager,
        "SYMLINK_FORBIDDEN",
        lambda: manager.inspect_run(
            receipt=alias / "receipt.json",
            rules_path=rules_path,
            assessment_path=policy_path,
            actor="contract-test",
        ),
    )
    assert _tree_snapshot(run.receipt.parent) == before
    assert not (run.retention / ".control").exists()


@pytest.mark.parametrize(
    "which",
    ("rules", "assessment"),
    ids=("rules", "assessment"),
)
def test_ret_t04_config_parent_symlink_is_rejected(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    which: str,
) -> None:
    run = sealed_run_factory()
    before = _tree_snapshot(run.receipt.parent)
    rules_path, policy_path = _write_config(tmp_path / "real-config")
    alias = tmp_path / "config-link"
    alias.symlink_to(rules_path.parent, target_is_directory=True)
    if which == "rules":
        rules_path = alias / rules_path.name
    else:
        policy_path = alias / policy_path.name

    _assert_error(
        manager,
        "SYMLINK_FORBIDDEN",
        lambda: _inspect(manager, run, rules_path, policy_path),
    )
    assert _tree_snapshot(run.receipt.parent) == before
    assert not (run.retention / ".control").exists()


def test_ret_t04_control_parent_symlink_cannot_escape_retention_root(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    rules_path, policy_path = _write_config(tmp_path / "config")
    outside = tmp_path / "outside-control"
    outside.mkdir()
    (run.retention / ".control").symlink_to(outside, target_is_directory=True)

    _assert_error(
        manager,
        "SYMLINK_FORBIDDEN",
        lambda: _inspect(manager, run, rules_path, policy_path),
    )
    assert list(outside.iterdir()) == []


def test_ret_t03_checked_in_assessment_binds_exact_checked_in_rules_bytes(
    manager: ModuleType,
) -> None:
    rules = _load_rules(manager, _DEFAULT_RULES)
    _load_assessment(manager, _DEFAULT_ASSESSMENT, _DEFAULT_RULES)
    assessment = json.loads(_DEFAULT_ASSESSMENT.read_text(encoding="utf-8"))
    assert rules.rule_set_id == "w1b5-assessment-v1"
    assert assessment["schema"] == "ai-auto-lrc/retention-assessment"
    assert assessment["mode"] == "assessment-only"
    assert assessment["decision_state"] == "pending-human-approval"
    assert assessment["classifications"] == [
        "captured-input",
        "checkpoint",
        "log-raw",
        "metadata",
        "source-raw",
        "test-evidence",
        "unknown",
    ]
    assignment = next(
        rule for rule in json.loads(_DEFAULT_RULES.read_text(encoding="utf-8"))["rules"]
        if rule["rule_id"] == "SEC-ASSIGNMENT"
    )
    assert set(assignment["terms"]) >= {
        "token",
        "api_key",
        "apikey",
        "secret",
        "password",
        "credential",
        "access_key",
        "private_key",
    }


def test_ret_t03_verifier_requires_external_config_trust_anchors(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    rules_path, policy_path = _write_config(tmp_path / "strong")
    result = _inspect(manager, run, rules_path, policy_path)
    weak_rules = _rules()
    weak_rules["rules"] = weak_rules["rules"][:-1]
    weak_rules_path, weak_policy_path = _write_config(tmp_path / "weak", rules=weak_rules)

    _assert_error(
        manager,
        "RULE_BINDING_MISMATCH",
        lambda: _verify_paths(
            manager,
            run,
            result.inspection_path,
            result.control_event_path,
            weak_rules_path,
            weak_policy_path,
        ),
    )


def test_ret_t03_whole_package_rebind_cannot_replace_external_config_anchor(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    before = _tree_snapshot(run.receipt.parent)
    rules_path, policy_path = _write_config(tmp_path / "strong")
    result = _inspect(manager, run, rules_path, policy_path)
    weak_rules = _rules()
    weak_rules["rules"] = weak_rules["rules"][:-1]
    weak_rules_path, weak_policy_path = _write_config(tmp_path / "weak", rules=weak_rules)
    report_path = _scan_path(result)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["rules_sha256"] = _sha256(weak_rules_path.read_bytes())
    report["assessment_sha256"] = _sha256(weak_policy_path.read_bytes())
    report_content = _json_bytes(report)
    _rewrite_private(report_path, report_content)
    complete_path = _complete_path(result)
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    complete["inspection_sha256"] = _sha256(report_content)
    complete_content = _json_bytes(complete)
    _rewrite_private(complete_path, complete_content)
    event_path = result.control_event_path
    event = json.loads(event_path.read_text(encoding="utf-8"))
    event["assessment_sha256"] = _sha256(weak_policy_path.read_bytes())
    event["details"]["rules_sha256"] = _sha256(weak_rules_path.read_bytes())
    event["details"]["inspection_sha256"] = _sha256(report_content)
    event["details"]["completion_sha256"] = _sha256(complete_content)
    event_content = _json_bytes(event)
    _rewrite_private(event_path, event_content)
    rebound_event = event_path.with_name(f"00000001-{_sha256(event_content)}.json")
    event_path.parent.chmod(0o700)
    event_path.rename(rebound_event)
    event_path.parent.chmod(0o700)

    _assert_error(
        manager,
        "RULE_BINDING_MISMATCH",
        lambda: _verify_paths(
            manager,
            run,
            result.inspection_path,
            rebound_event,
            rules_path,
            policy_path,
        ),
    )
    assert _tree_snapshot(run.receipt.parent) == before


def test_ret_t06_report_event_and_cli_material_do_not_embed_reversible_rules(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory(untracked={"secret.bin": b"\xff" + _SECRET + b"\x00"})
    rules_path, policy_path = _write_config(tmp_path / "config")
    result = _inspect(manager, run, rules_path, policy_path)

    assert result.state == "SCANNED_BLOCKED"
    _assert_no_sensitive_material(
        _scan_path(result).read_bytes(),
        result.control_event_path.read_bytes(),
    )
    report = json.loads(_scan_path(result).read_text(encoding="utf-8"))
    assert "rules" not in report
    assert "pattern_base64" not in json.dumps(report)


@pytest.mark.parametrize(
    "phase",
    ("before-inspection-publish", "before-event-commit", "after-event-commit"),
)
def test_ret_t05_source_mutation_around_commit_never_returns_valid_inspection(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    run = sealed_run_factory()
    rules_path, policy_path = _write_config(tmp_path / "config")
    before = _tree_snapshot(run.receipt.parent)
    target = run.receipt.parent / "logs/stdout.bin"
    original = target.read_bytes()
    original_rename_noreplace = manager._rename_noreplace
    fired = False

    def mutate() -> None:
        nonlocal fired
        if fired:
            return
        fired = True
        target.chmod(0o600)
        target.write_bytes(original + b"mutated-during-commit")
        target.chmod(0o400)

    def rename_noreplace(source: Path, destination: Path) -> None:
        destination_path = Path(destination)
        is_inspection = destination_path.parent.name == "inspections"
        is_event = destination_path.parent.name == "events"
        if phase == "before-inspection-publish" and is_inspection:
            mutate()
        if phase == "before-event-commit" and is_event:
            mutate()
        original_rename_noreplace(source, destination)
        if phase == "after-event-commit" and is_event:
            mutate()

    monkeypatch.setattr(manager, "_rename_noreplace", rename_noreplace)
    try:
        with pytest.raises(manager.RetentionError) as raised:
            _inspect(manager, run, rules_path, policy_path)
        assert raised.value.code in {
            "FILE_CHANGED_DURING_SCAN",
            "CONTROL_COMMIT_UNCERTAIN",
            "CONTROL_PUBLICATION_FAILED",
            "INSPECTION_INVALID",
            "RECEIPT_INVALID",
        }
        assert fired is True
    finally:
        target.chmod(0o600)
        target.write_bytes(original)
        target.chmod(0o400)
    assert _tree_snapshot(run.receipt.parent) == before


# P0/P1 scanner: bounded, non-regex and overlap-safe.


@pytest.mark.parametrize("matcher", ("regex-bytes", "glob", "script"))
def test_ret_t08_rules_reject_unbounded_or_executable_matchers(
    manager: ModuleType,
    tmp_path: Path,
    matcher: str,
) -> None:
    rules = _rules()
    rules["rules"][0]["matcher"] = matcher
    rules_path = tmp_path / "rules.json"
    rules_path.write_bytes(_json_bytes(rules))

    _assert_error(manager, "RULE_SCHEMA_INVALID", lambda: _load_rules(manager, rules_path))


@pytest.mark.parametrize(
    "matcher,term,sensitive",
    (
        ("literal-ascii-ci", "sentinel-secret", b"sentinel-secret-contract"),
        ("assignment-value-ascii-ci", "token", b"token = contract-secret"),
        ("scheme-value-ascii-ci", "Bearer", b"Bearer contract-secret"),
    ),
)
def test_ret_t07_literal_assignment_and_scheme_match_across_chunk_boundary(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    matcher: str,
    term: str,
    sensitive: bytes,
) -> None:
    prefix = b"\xff" + b"x" * (_CHUNK_BYTES - 5) + b" "
    run = sealed_run_factory(untracked={"boundary.bin": prefix + sensitive + b"\xfe"})
    rules = _rules()
    rules["rules"] = [
        _rule(
            "SEC-BOUNDARY",
            category="credential",
            matcher=matcher,
            terms=[term],
            max_value_bytes=(64 if matcher.endswith("value-ascii-ci") else 0),
        )
    ]
    rules_path, policy_path = _write_config(tmp_path / "config", rules=rules)

    result = _inspect(manager, run, rules_path, policy_path)

    assert result.state == "SCANNED_BLOCKED"
    report = json.loads(_scan_path(result).read_text(encoding="utf-8"))
    records = [item for item in report["files"] if item["path"].endswith("boundary.bin")]
    assert records
    assert all(len(item["hits"]) == 1 for item in records)
    assert all(item["hits"][0]["rule_id"] == "SEC-BOUNDARY" for item in records)


def test_ret_t08_scan_limit_is_decided_before_any_oversize_file_read(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory(untracked={"oversize.bin": b"x" * 4096})
    rules_path, policy_path = _write_config(tmp_path / "config")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["scanner"]["max_file_bytes"] = 1024
    policy_path.write_bytes(_json_bytes(policy))
    archived_targets = {
        path
        for path in run.receipt.parent.rglob("oversize.bin")
        if path.is_file()
    }
    original_scan_file = manager._scan_file

    def scan_file_spy(
        path: Path,
        *args: object,
        **kwargs: object,
    ) -> object:
        if path not in archived_targets:
            return original_scan_file(path, *args, **kwargs)

        def forbidden_read(_descriptor: int, _size: int) -> bytes:
            raise AssertionError("oversize file content was read")

        with monkeypatch.context() as scoped:
            scoped.setattr(manager.os, "read", forbidden_read)
            return original_scan_file(path, *args, **kwargs)

    monkeypatch.setattr(manager, "_scan_file", scan_file_spy)

    result = _inspect(manager, run, rules_path, policy_path)

    assert result.state == "SCANNED_BLOCKED"
    report = json.loads(_scan_path(result).read_text(encoding="utf-8"))
    records = [item for item in report["files"] if item["path"].endswith("oversize.bin")]
    assert records and all(item["sha256"] is None for item in records)
    assert any(error["code"] == "SCAN_LIMIT_EXCEEDED" for error in report["errors"])


# P1 schema, classification, permission and independent verification.


@pytest.mark.parametrize(
    "mutation",
    (
        ("scanner_id", True),
        ("created_at", "yesterday"),
        ("files.0.size", True),
        ("files.0.unknown", "forbidden"),
        ("files.0.hits", [{"rule_id": "SEC-X", "start_byte": True, "end_byte": 1}]),
        ("errors", [{"code": "SECRET_MATCHED", "path": "/absolute/leak"}]),
        ("aggregate_sha256", "short"),
    ),
    ids=(
        "scanner-bool",
        "invalid-time",
        "file-bool-size",
        "file-unknown-key",
        "finding-bool-offset",
        "absolute-error-path",
        "aggregate-hash",
    ),
)
def test_ret_t01_scan_report_nested_schema_is_exact_after_hash_rebinding(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    mutation: tuple[str, object],
) -> None:
    run = sealed_run_factory()
    rules_path, policy_path = _write_config(tmp_path / "config")
    result = _inspect(manager, run, rules_path, policy_path)
    report_path = _scan_path(result)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    _change_path(report, *mutation)
    report_content = _json_bytes(report)
    _rewrite_private(report_path, report_content)
    complete_path = _complete_path(result)
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    complete["inspection_sha256"] = _sha256(report_content)
    complete_content = _json_bytes(complete)
    _rewrite_private(complete_path, complete_content)
    event = json.loads(result.control_event_path.read_text(encoding="utf-8"))
    event["details"]["inspection_sha256"] = _sha256(report_content)
    event["details"]["completion_sha256"] = _sha256(complete_content)
    event_content = _json_bytes(event)
    _rewrite_private(result.control_event_path, event_content)
    rebound_event = result.control_event_path.with_name(
        f"00000001-{_sha256(event_content)}.json"
    )
    result.control_event_path.rename(rebound_event)

    _assert_error(
        manager,
        "INSPECTION_INVALID",
        lambda: _verify_paths(
            manager,
            run,
            result.inspection_path,
            rebound_event,
            rules_path,
            policy_path,
        ),
    )


@pytest.mark.parametrize(
    "target,mode",
    (
        ("inspection-dir", 0o750),
        ("scan-file", 0o640),
        ("complete-file", 0o400),
        ("event-file", 0o640),
        ("events-dir", 0o750),
    ),
)
def test_ret_t18_verifier_requires_exact_private_modes(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    target: str,
    mode: int,
) -> None:
    run = sealed_run_factory()
    rules_path, policy_path = _write_config(tmp_path / "config")
    result = _inspect(manager, run, rules_path, policy_path)
    paths = {
        "inspection-dir": result.inspection_path,
        "scan-file": _scan_path(result),
        "complete-file": _complete_path(result),
        "event-file": result.control_event_path,
        "events-dir": result.control_event_path.parent,
    }
    paths[target].chmod(mode)

    _assert_error(
        manager,
        "INSPECTION_INVALID",
        lambda: _verify(manager, run, result, rules_path, policy_path),
    )


def test_ret_t09_all_source_paths_are_source_raw_and_unknown_claim_is_rejected(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    rules_path, policy_path = _write_config(tmp_path / "config")
    result = _inspect(manager, run, rules_path, policy_path)
    report = json.loads(_scan_path(result).read_text(encoding="utf-8"))
    source_records = [item for item in report["files"] if item["path"].startswith("source/")]
    assert source_records
    assert {item["classification"] for item in source_records} == {"source-raw"}
    report["files"][0]["classification"] = "unknown"
    report["errors"].append({"code": "CLASSIFICATION_UNKNOWN", "path": report["files"][0]["path"]})
    report_content = _json_bytes(report)
    _rewrite_private(_scan_path(result), report_content)
    complete = json.loads(_complete_path(result).read_text(encoding="utf-8"))
    complete["inspection_sha256"] = _sha256(report_content)
    _rewrite_private(_complete_path(result), _json_bytes(complete))

    _assert_error(
        manager,
        "INSPECTION_INVALID",
        lambda: _verify(manager, run, result, rules_path, policy_path),
    )


def test_ret_t09_every_regular_closure_file_has_one_scan_record(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory(untracked={".hidden-proof": b"hidden\n"})
    rules_path, policy_path = _write_config(tmp_path / "config")

    result = _inspect(manager, run, rules_path, policy_path)

    report = json.loads(_scan_path(result).read_text(encoding="utf-8"))
    reported_paths = [item["path"] for item in report["files"]]
    actual_paths = sorted(
        path.relative_to(run.receipt.parent).as_posix()
        for path in run.receipt.parent.rglob("*")
        if path.is_file()
    )
    assert reported_paths == actual_paths
    assert len(reported_paths) == len(set(reported_paths))
    assert any(path.endswith("/.hidden-proof") for path in reported_paths)


@pytest.mark.parametrize(
    "target",
    ("report", "complete", "event"),
)
def test_ret_t16_verify_rejects_tampered_report_marker_or_event(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    target: str,
) -> None:
    run = sealed_run_factory()
    rules_path, policy_path = _write_config(tmp_path / "config")
    result = _inspect(manager, run, rules_path, policy_path)
    targets = {
        "report": _scan_path(result),
        "complete": _complete_path(result),
        "event": result.control_event_path,
    }
    tampered = targets[target]
    _rewrite_private(tampered, tampered.read_bytes() + b" \n")

    expected = "EVENT_HASH_CHAIN_INVALID" if target == "event" else "INSPECTION_INVALID"
    _assert_error(
        manager,
        expected,
        lambda: _verify(manager, run, result, rules_path, policy_path),
    )


def test_ret_t14_second_inspection_never_overwrites_committed_state(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    rules_path, policy_path = _write_config(tmp_path / "config")
    first = _inspect(manager, run, rules_path, policy_path)
    committed = _tree_snapshot(first.control_event_path.parent.parent)

    _assert_error(
        manager,
        "INSPECTION_ALREADY_COMMITTED",
        lambda: _inspect(manager, run, rules_path, policy_path),
    )
    assert _tree_snapshot(first.control_event_path.parent.parent) == committed


def test_ret_t29_old_inspection_cannot_bind_a_different_receipt(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    original_run = sealed_run_factory()
    different_run = sealed_run_factory(untracked={"different.txt": b"different\n"})
    rules_path, policy_path = _write_config(tmp_path / "config")
    result = _inspect(manager, original_run, rules_path, policy_path)

    _assert_error(
        manager,
        "INSPECTION_INVALID",
        lambda: _verify_paths(
            manager,
            different_run,
            result.inspection_path,
            result.control_event_path,
            rules_path,
            policy_path,
        ),
    )


# P1 CLI: real sealed receipt, checked-in defaults, stable exit codes and redaction.


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, os.fspath(_SCRIPT), *arguments],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_cli_pass_uses_checked_in_defaults_and_emits_sanitized_json(
    sealed_run_factory: Callable[..., SealedRun],
) -> None:
    run = sealed_run_factory()

    completed = _run_cli(
        "inspect",
        "--receipt",
        os.fspath(run.receipt),
        "--actor",
        "cli-contract",
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert completed.stdout.count("\n") == 1
    document = json.loads(completed.stdout)
    assert set(document) == {"run_id", "inspection_id", "state"}
    assert document["run_id"] == run.receipt.parent.name
    assert document["state"] == "SCANNED_PASS"
    _assert_no_sensitive_material(completed.stdout, completed.stderr)
    assert os.fspath(run.receipt.parent) not in completed.stdout


def test_cli_secret_match_commits_blocked_exits_three_and_verifies_blocked(
    sealed_run_factory: Callable[..., SealedRun],
) -> None:
    run = sealed_run_factory(untracked={"blocked.bin": b"\xff" + _SECRET + b"\x00"})

    completed = _run_cli(
        "inspect",
        "--receipt",
        os.fspath(run.receipt),
        "--actor",
        "cli-contract",
    )

    assert completed.returncode == 3
    assert completed.stderr == ""
    document = json.loads(completed.stdout)
    assert document["state"] == "SCANNED_BLOCKED"
    _assert_no_sensitive_material(completed.stdout, completed.stderr)
    run_control = run.retention / ".control" / run.receipt.parent.name
    inspection = run_control / "inspections" / document["inspection_id"]
    event = next((run_control / "events").glob("*.json"))
    verified = _run_cli(
        "verify-inspection",
        "--receipt",
        os.fspath(run.receipt),
        "--inspection",
        os.fspath(inspection),
        "--control-event",
        os.fspath(event),
    )
    assert verified.returncode == 3
    assert json.loads(verified.stdout)["state"] == "SCANNED_BLOCKED"
    _assert_no_sensitive_material(verified.stdout, verified.stderr)


def test_cli_known_failure_is_one_sanitized_stderr_line_without_paths() -> None:
    missing = Path.home() / "private-secret-receipt.json"

    completed = _run_cli(
        "inspect",
        "--receipt",
        os.fspath(missing),
        "--actor",
        "cli-contract",
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr.count("\n") == 1
    assert completed.stderr.startswith("RECEIPT_INVALID:")
    _assert_no_sensitive_material(completed.stderr)
    assert os.fspath(missing) not in completed.stderr


@pytest.mark.parametrize(
    "command",
    ("prepare-export", "verify-export", "export", "upload", "archive", "destroy"),
)
def test_cli_forbidden_commands_are_argparse_errors_without_side_effects(
    sealed_run_factory: Callable[..., SealedRun],
    command: str,
) -> None:
    run = sealed_run_factory()

    completed = _run_cli(command, "--receipt", os.fspath(run.receipt))

    assert completed.returncode == 2
    assert not (run.retention / ".control").exists()
    _assert_no_sensitive_material(completed.stdout, completed.stderr)


def test_ret_t30_inspection_preserves_original_sealed_run_bytes_and_modes(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    before = _tree_snapshot(run.receipt.parent)
    rules_path, policy_path = _write_config(tmp_path / "config")

    result = _inspect(manager, run, rules_path, policy_path)

    assert _tree_snapshot(run.receipt.parent) == before
    report = json.loads(_scan_path(result).read_text(encoding="utf-8"))
    serialized = json.dumps(report)
    for forbidden in ("qualification", "spec_ids", "release-ready", "safe-to-export"):
        assert forbidden not in serialized


# S7: descriptor-relative path resolution must survive check/use parent swaps.


def test_ret_s7_config_parent_swap_after_validation_is_rejected(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted = tmp_path / "trusted-config"
    rules_path, _assessment_path = _write_config(trusted)
    weak_rules = _rules()
    weak_rules["rules"] = weak_rules["rules"][:-1]
    attacker = tmp_path / "attacker-config"
    attacker_rules, _attacker_assessment = _write_config(attacker, rules=weak_rules)
    original_check = manager._assert_no_symlink_components
    swapped = False

    def check_then_swap(path: Path, code: str, **kwargs: object) -> None:
        nonlocal swapped
        original_check(path, code, **kwargs)
        if Path(path) == rules_path and not swapped:
            swapped = True
            trusted.rename(tmp_path / "trusted-config-pinned")
            trusted.symlink_to(attacker, target_is_directory=True)

    monkeypatch.setattr(manager, "_assert_no_symlink_components", check_then_swap)

    _assert_error(
        manager,
        "SYMLINK_FORBIDDEN",
        lambda: _load_rules(manager, rules_path),
    )
    assert swapped is True
    assert rules_path.read_bytes() == attacker_rules.read_bytes()


def test_ret_s7_control_parent_swap_never_writes_outside_verified_root(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_parent = tmp_path / "trusted-control"
    trusted_parent.mkdir()
    outside = tmp_path / "outside-control"
    outside.mkdir()
    target = trusted_parent / "child"
    original_mkdir = manager.os.mkdir
    swapped = False

    def mkdir_after_parent_swap(
        path: object,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if path == target.name and dir_fd is not None and not swapped:
            swapped = True
            trusted_parent.rename(tmp_path / "trusted-control-pinned")
            trusted_parent.symlink_to(outside, target_is_directory=True)
        original_mkdir(path, mode=mode, dir_fd=dir_fd)

    monkeypatch.setattr(manager.os, "mkdir", mkdir_after_parent_swap)

    manager._private_dir(target)
    assert swapped is True
    assert list(outside.iterdir()) == []
    assert (tmp_path / "trusted-control-pinned" / "child").is_dir()


@pytest.mark.parametrize(
    "kind,expected_code",
    (
        ("symlink", "SYMLINK_FORBIDDEN"),
        ("hardlink", "HARDLINK_FORBIDDEN"),
        ("fifo", "UNSAFE_FILE_TYPE"),
        ("socket", "UNSAFE_FILE_TYPE"),
    ),
)
def test_ret_s7_sealed_special_files_are_rejected_before_scan_open(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    expected_code: str,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    sealed_root = run.receipt.parent
    target = sealed_root / f"unsafe-{kind}"
    sealed_root.chmod(0o700)
    bound_socket: socket.socket | None = None
    if kind == "symlink":
        target.symlink_to(sealed_root / "SEALED")
    elif kind == "hardlink":
        os.link(sealed_root / "SEALED", target)
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        bound_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        current_directory = Path.cwd()
        os.chdir(sealed_root)
        try:
            bound_socket.bind(target.name)
        finally:
            os.chdir(current_directory)
        bound_socket.close()
    sealed_root.chmod(0o500)

    opened_unsafe = False
    original_open = manager.os.open

    def open_spy(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        nonlocal opened_unsafe
        if isinstance(path, (str, bytes, Path)) and os.fspath(path) == os.fspath(target):
            opened_unsafe = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(manager.os, "open", open_spy)
    _assert_error(
        manager,
        expected_code,
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    assert opened_unsafe is False
    assert not (run.retention / ".control").exists()


@pytest.mark.parametrize("phase", ("before-open", "during-read", "after-read"))
def test_ret_s7_scanner_rejects_before_open_during_read_and_after_read_identity_change(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    source_root = tmp_path / "source-root"
    target = source_root / "source" / "source.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"stable scanner bytes")
    rules_path, _assessment_path = _write_config(tmp_path / "config")
    rules = _load_rules(manager, rules_path)
    initial = target.lstat()
    original_open = manager.os.open
    original_read = manager.os.read
    mutated = False

    def mutate() -> None:
        nonlocal mutated
        if not mutated:
            mutated = True
            target.write_bytes(b"changed scanner bytes")

    def open_spy(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        if (
            phase == "before-open"
            and isinstance(path, (str, bytes, Path))
            and path == target.name
            and kwargs.get("dir_fd") is not None
        ):
            mutate()
        return original_open(path, flags, *args, **kwargs)

    def read_spy(descriptor: int, size: int) -> bytes:
        if phase == "during-read" and not mutated:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) == (initial.st_dev, initial.st_ino):
                mutate()
        chunk = original_read(descriptor, size)
        if phase == "after-read" and not chunk and not mutated:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) == (initial.st_dev, initial.st_ino):
                mutate()
        return chunk

    monkeypatch.setattr(manager.os, "open", open_spy)
    monkeypatch.setattr(manager.os, "read", read_spy)
    root_fd = os.open(source_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        record, errors, _limit_exceeded = manager._scan_file(
            root_fd,
            "source/source.bin",
            manager._identity(initial),
            rules,
            1024,
            manager.MAX_TOTAL_HITS,
        )
    finally:
        os.close(root_fd)

    assert mutated is True
    assert record["sha256"] is None
    assert errors == [
        {"code": "FILE_CHANGED_DURING_SCAN", "path": "source/source.bin"}
    ]


# S8: external digests and rule-set identity are trust roots, not package claims.


def test_ret_s8_custom_paths_require_external_expected_digests(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    custom_rules, custom_assessment = _write_config(tmp_path / "custom")
    custom_rules.write_bytes(custom_rules.read_bytes() + b" ")
    assessment_document = _assessment(custom_rules.read_bytes())
    custom_assessment.write_bytes(_json_bytes(assessment_document))

    _assert_error(
        manager,
        "EXPECTED_DIGEST_INVALID",
        lambda: manager.inspect_run(
            receipt=run.receipt,
            rules_path=custom_rules,
            assessment_path=custom_assessment,
            actor="contract-test",
        ),
    )
    assert not (run.retention / ".control").exists()


def test_ret_s8_weak_rules_from_start_cannot_false_pass_against_expected_digest(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory(untracked={"credential.bin": _SECRET})
    strong_rules, strong_assessment = _write_config(tmp_path / "strong")
    weak = _rules()
    weak["rules"] = weak["rules"][:-1]
    weak_rules, weak_assessment = _write_config(tmp_path / "weak", rules=weak)

    _assert_error(
        manager,
        "RULE_TRUST_MISMATCH",
        lambda: _inspect_with_expected_digests(
            manager,
            run,
            weak_rules,
            weak_assessment,
            expected_rules_sha256=_sha256(strong_rules.read_bytes()),
            expected_assessment_sha256=_sha256(strong_assessment.read_bytes()),
        ),
    )
    assert not (run.retention / ".control").exists()


def test_ret_s8_equivalent_json_byte_drift_fails_external_digest_binding(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    canonical_rules, canonical_assessment = _write_config(tmp_path / "canonical")
    drifted = tmp_path / "drifted"
    drifted.mkdir()
    rules_document = json.loads(canonical_rules.read_text(encoding="utf-8"))
    drifted_rules = drifted / canonical_rules.name
    drifted_rules.write_bytes(
        (json.dumps(rules_document, separators=(",", ":"), sort_keys=True) + "\n").encode()
    )
    assert json.loads(drifted_rules.read_bytes()) == rules_document
    assert drifted_rules.read_bytes() != canonical_rules.read_bytes()
    drifted_assessment_document = _assessment(drifted_rules.read_bytes())
    drifted_assessment = drifted / canonical_assessment.name
    drifted_assessment.write_bytes(_json_bytes(drifted_assessment_document))

    _assert_error(
        manager,
        "RULE_TRUST_MISMATCH",
        lambda: _inspect_with_expected_digests(
            manager,
            run,
            drifted_rules,
            drifted_assessment,
            expected_rules_sha256=_sha256(canonical_rules.read_bytes()),
            expected_assessment_sha256=_sha256(canonical_assessment.read_bytes()),
        ),
    )
    assert not (run.retention / ".control").exists()


def test_ret_s8_rules_and_assessment_rule_set_ids_must_match(
    manager: ModuleType,
    tmp_path: Path,
) -> None:
    rules = _rules()
    rules["rule_set_id"] = "different-rule-set"
    rules_path, assessment_path = _write_config(tmp_path / "config", rules=rules)
    loaded_rules = _load_rules(manager, rules_path)

    _assert_error(
        manager,
        "RULE_SET_ID_MISMATCH",
        lambda: manager.load_retention_assessment(
            assessment_path,
            rules=loaded_rules,
            expected_sha256=_sha256(assessment_path.read_bytes()),
        ),
    )


# S9: hit metadata and report bytes are bounded across the complete run.


def _many_hit_rules() -> dict[str, Any]:
    rules = _rules()
    rules["rules"] = [
        _rule(
            "SEC-MANY",
            category="credential",
            matcher="literal-ascii",
            terms=["x"],
        )
    ]
    return rules


def test_ret_s9_11050_hits_are_bounded_blocked_and_independently_verifiable(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory(untracked={"many-hits.bin": b"x" * 11_050})
    rules_path, assessment_path = _write_config(
        tmp_path / "config",
        rules=_many_hit_rules(),
    )

    result = _inspect(manager, run, rules_path, assessment_path)

    assert result.state == "SCANNED_BLOCKED"
    report_path = _scan_path(result)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    target = next(item for item in report["files"] if item["path"].endswith("many-hits.bin"))
    assert len(target["hits"]) <= manager.MAX_TOTAL_HITS
    assert "SCAN_HIT_LIMIT_EXCEEDED" in {item["code"] for item in report["errors"]}
    assert report_path.stat().st_size <= manager.MAX_REPORT_BYTES
    _verify(manager, run, result, rules_path, assessment_path)


def test_ret_s9_hit_limit_is_global_across_multiple_files(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory(
        untracked={
            "many-a.bin": b"x" * 6_000,
            "many-b.bin": b"x" * 6_000,
        }
    )
    rules_path, assessment_path = _write_config(
        tmp_path / "config",
        rules=_many_hit_rules(),
    )

    result = _inspect(manager, run, rules_path, assessment_path)

    report = json.loads(_scan_path(result).read_text(encoding="utf-8"))
    total_hits = sum(len(item["hits"]) for item in report["files"])
    assert result.state == "SCANNED_BLOCKED"
    assert total_hits <= manager.MAX_TOTAL_HITS
    assert "SCAN_HIT_LIMIT_EXCEEDED" in {item["code"] for item in report["errors"]}
    assert _scan_path(result).stat().st_size <= manager.MAX_REPORT_BYTES
    _verify(manager, run, result, rules_path, assessment_path)


def test_ret_s9_oversize_report_is_rejected_before_event_commit(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    original_json_bytes = manager._json_bytes

    def oversize_report(value: object) -> bytes:
        content = original_json_bytes(value)
        if isinstance(value, dict) and value.get("schema") == manager.SCAN_SCHEMA:
            return content + b" " * (manager.MAX_CONFIG_BYTES + 1)
        return content

    monkeypatch.setattr(manager, "_json_bytes", oversize_report)

    _assert_error(
        manager,
        "REPORT_LIMIT_EXCEEDED",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    run_control = run.retention / ".control" / run.receipt.parent.name
    assert not (run_control / "events").exists() or not any(
        (run_control / "events").iterdir()
    )


# S10: publication failures, orphan recovery and ledger semantics are explicit.


@pytest.mark.parametrize("point", ("write", "fsync", "rename"))
def test_ret_s10_fault_before_inspection_publish_leaves_no_commit(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    run = sealed_run_factory()
    before = _tree_snapshot(run.receipt.parent)
    rules_path, assessment_path = _write_config(tmp_path / "config")
    original_write = manager._write_exclusive
    original_fsync = manager._fsync_dir
    original_rename = manager._rename_noreplace

    def write_fault(path: Path, content: bytes) -> None:
        if point == "write" and path.parent.parent.name == "inspections":
            raise OSError("injected inspection write fault")
        original_write(path, content)

    def fsync_fault(path: Path) -> None:
        if point == "fsync" and path.name.startswith(".incomplete-"):
            raise OSError("injected inspection fsync fault")
        original_fsync(path)

    def rename_fault(source: Path, destination: Path) -> None:
        if point == "rename" and destination.parent.name == "inspections":
            raise OSError("injected inspection rename fault")
        original_rename(source, destination)

    monkeypatch.setattr(manager, "_write_exclusive", write_fault)
    monkeypatch.setattr(manager, "_fsync_dir", fsync_fault)
    monkeypatch.setattr(manager, "_rename_noreplace", rename_fault)

    _assert_error(
        manager,
        "CONTROL_PUBLICATION_FAILED",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    run_control = run.retention / ".control" / run.receipt.parent.name
    assert _tree_snapshot(run.receipt.parent) == before
    assert not any((run_control / "events").iterdir())
    assert not any((run_control / "inspections").iterdir())


@pytest.mark.parametrize("point", ("event-write", "event-rename"))
def test_ret_s10_fault_after_inspection_publish_leaves_detectable_orphan(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    run = sealed_run_factory()
    before = _tree_snapshot(run.receipt.parent)
    rules_path, assessment_path = _write_config(tmp_path / "config")
    original_write = manager._write_exclusive
    original_rename = manager._rename_noreplace

    def write_fault(path: Path, content: bytes) -> None:
        if point == "event-write" and path.parent.name == "events":
            raise OSError("injected event write fault")
        original_write(path, content)

    def rename_fault(source: Path, destination: Path) -> None:
        if point == "event-rename" and destination.parent.name == "events":
            raise OSError("injected event rename fault")
        original_rename(source, destination)

    monkeypatch.setattr(manager, "_write_exclusive", write_fault)
    monkeypatch.setattr(manager, "_rename_noreplace", rename_fault)

    _assert_error(
        manager,
        "CONTROL_PUBLICATION_FAILED",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    run_control = run.retention / ".control" / run.receipt.parent.name
    inspections = list((run_control / "inspections").iterdir())
    assert len(inspections) == 1
    assert not any((run_control / "events").iterdir())
    assert _tree_snapshot(run.receipt.parent) == before

    _assert_error(
        manager,
        "CONTROL_RECOVERY_REQUIRED",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    assert list((run_control / "inspections").iterdir()) == inspections


def test_ret_s10_unsupported_no_replace_fails_closed_without_event(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")

    class UnsupportedLibc:
        pass

    monkeypatch.setattr(manager.sys, "platform", "unsupported-contract-os")
    monkeypatch.setattr(manager.ctypes, "CDLL", lambda *args, **kwargs: UnsupportedLibc())

    _assert_error(
        manager,
        "NO_REPLACE_UNSUPPORTED",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    run_control = run.retention / ".control" / run.receipt.parent.name
    assert not (run_control / "events").exists() or not any(
        (run_control / "events").iterdir()
    )


def test_ret_s10_post_commit_self_verify_failure_is_not_reported_as_committed(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    original_publish = manager._publish_event
    injected = False

    def publish_invalid_event(events: Path, content: bytes, sequence: int) -> Path:
        nonlocal injected
        event_path = original_publish(events, content, sequence)
        injected = True
        _rewrite_private(event_path, event_path.read_bytes() + b" ")
        return event_path

    monkeypatch.setattr(manager, "_publish_event", publish_invalid_event)
    _assert_error(
        manager,
        "CONTROL_COMMIT_UNCERTAIN",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    assert injected is True

    _assert_error(
        manager,
        "CONTROL_RECOVERY_REQUIRED",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )


def _rewrite_event_with_valid_content_hash(
    result: object,
    event: dict[str, Any],
) -> Path:
    old_path = result.control_event_path
    content = _json_bytes(event)
    _rewrite_private(old_path, content)
    sequence = event["sequence"]
    new_path = old_path.with_name(f"{sequence:08d}-{_sha256(content)}.json")
    old_path.rename(new_path)
    return new_path


@pytest.mark.parametrize(
    "mutation,expected_code",
    (
        (("sequence", 2), "EVENT_SEQUENCE_INVALID"),
        (("previous_event_sha256", "0" * 64), "EVENT_HASH_CHAIN_INVALID"),
        (("from_state", "SCANNED_PASS"), "EVENT_SEQUENCE_INVALID"),
        (("to_state", "LOCAL_SEALED"), "EVENT_SEQUENCE_INVALID"),
    ),
    ids=("gap", "bad-previous-hash", "bad-from-state", "bad-to-state"),
)
def test_ret_s10_rehashed_semantically_invalid_ledger_event_is_rejected(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    mutation: tuple[str, object],
    expected_code: str,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    result = _inspect(manager, run, rules_path, assessment_path)
    event = json.loads(result.control_event_path.read_text(encoding="utf-8"))
    _change_path(event, *mutation)
    rebound = _rewrite_event_with_valid_content_hash(result, event)

    _assert_error(
        manager,
        expected_code,
        lambda: _verify_paths(
            manager,
            run,
            result.inspection_path,
            rebound,
            rules_path,
            assessment_path,
        ),
    )


@pytest.mark.parametrize(
    "kind,expected_code",
    (
        ("symlink", "INSPECTION_INVALID"),
        ("hardlink", "INSPECTION_INVALID"),
        ("fifo", "INSPECTION_INVALID"),
        ("socket", "INSPECTION_INVALID"),
    ),
)
def test_ret_s7_control_files_reject_symlink_hardlink_fifo_and_socket(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    kind: str,
    expected_code: str,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    result = _inspect(manager, run, rules_path, assessment_path)
    lock_path = result.control_directory / "LOCK"
    lock_path.unlink()
    if kind == "symlink":
        lock_path.symlink_to(_scan_path(result))
    elif kind == "hardlink":
        os.link(_scan_path(result), lock_path)
    elif kind == "fifo":
        os.mkfifo(lock_path)
    else:
        bound_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        current_directory = Path.cwd()
        os.chdir(result.control_directory)
        try:
            bound_socket.bind(lock_path.name)
        finally:
            os.chdir(current_directory)
        bound_socket.close()

    _assert_error(
        manager,
        expected_code,
        lambda: _verify(manager, run, result, rules_path, assessment_path),
    )


def test_ret_s7_control_owner_uid_mismatch_is_rejected(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    result = _inspect(manager, run, rules_path, assessment_path)
    lock_path = result.control_directory / "LOCK"
    original_stat = manager.os.stat

    def wrong_owner(path: object, *args: object, **kwargs: object) -> os.stat_result:
        item = original_stat(path, *args, **kwargs)
        if path == lock_path.name and kwargs.get("dir_fd") is not None:
            values = list(item)
            values[4] = item.st_uid + 1
            return os.stat_result(values)
        return item

    monkeypatch.setattr(manager.os, "stat", wrong_owner)
    _assert_error(
        manager,
        "INSPECTION_INVALID",
        lambda: _verify(manager, run, result, rules_path, assessment_path),
    )


@pytest.mark.parametrize(
    "target",
    (
        "control-root",
        "run-control",
        "inspections-dir",
        "lock-file",
        "rules-snapshot",
        "assessment-snapshot",
    ),
)
def test_ret_s7_all_control_nodes_require_exact_private_modes(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    target: str,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    result = _inspect(manager, run, rules_path, assessment_path)
    run_control = result.control_directory
    paths = {
        "control-root": run_control.parent,
        "run-control": run_control,
        "inspections-dir": run_control / "inspections",
        "lock-file": run_control / "LOCK",
        "rules-snapshot": result.inspection_path / "secret-rules.json",
        "assessment-snapshot": result.inspection_path / "retention-assessment.json",
    }
    paths[target].chmod(0o755 if paths[target].is_dir() else 0o644)

    _assert_error(
        manager,
        "INSPECTION_INVALID",
        lambda: _verify(manager, run, result, rules_path, assessment_path),
    )


# S11: mode combinations, concurrent publishers and output hygiene are contractual.


def _inspect_mode(
    manager: ModuleType,
    run: SealedRun,
    rules_path: Path,
    assessment_path: Path,
    *,
    mode: str,
    repo_root: Path | None,
) -> object:
    arguments: dict[str, object] = {
        "receipt": run.receipt,
        "rules_path": rules_path,
        "assessment_path": assessment_path,
        "actor": "contract-test",
        "mode": mode,
        "repo_root": repo_root,
    }
    parameters = inspect.signature(manager.inspect_run).parameters
    if "expected_rules_sha256" in parameters:
        arguments["expected_rules_sha256"] = _sha256(rules_path.read_bytes())
    if "expected_assessment_sha256" in parameters:
        arguments["expected_assessment_sha256"] = _sha256(
            assessment_path.read_bytes()
        )
    return manager.inspect_run(**arguments)


def _verify_mode(
    manager: ModuleType,
    run: SealedRun,
    result: object,
    rules_path: Path,
    assessment_path: Path,
    *,
    mode: str,
    repo_root: Path | None,
) -> object:
    arguments: dict[str, object] = {
        "receipt": run.receipt,
        "inspection": result.inspection_path,
        "control_event": result.control_event_path,
        "rules_path": rules_path,
        "assessment_path": assessment_path,
        "mode": mode,
        "repo_root": repo_root,
    }
    parameters = inspect.signature(manager.verify_inspection).parameters
    if "expected_rules_sha256" in parameters:
        arguments["expected_rules_sha256"] = _sha256(rules_path.read_bytes())
    if "expected_assessment_sha256" in parameters:
        arguments["expected_assessment_sha256"] = _sha256(
            assessment_path.read_bytes()
        )
    return manager.verify_inspection(**arguments)


def _inspect_actor(
    manager: ModuleType,
    run: SealedRun,
    rules_path: Path,
    assessment_path: Path,
    actor: str,
) -> object:
    arguments: dict[str, object] = {
        "receipt": run.receipt,
        "rules_path": rules_path,
        "assessment_path": assessment_path,
        "actor": actor,
    }
    parameters = inspect.signature(manager.inspect_run).parameters
    if "expected_rules_sha256" in parameters:
        arguments["expected_rules_sha256"] = _sha256(rules_path.read_bytes())
    if "expected_assessment_sha256" in parameters:
        arguments["expected_assessment_sha256"] = _sha256(
            assessment_path.read_bytes()
        )
    return manager.inspect_run(**arguments)


@pytest.mark.parametrize("operation", ("inspect", "verify"))
@pytest.mark.parametrize(
    "mode,use_repo,inspect_outcome,verify_outcome",
    (
        ("archived-integrity", False, "accepted", "accepted"),
        ("archived-integrity", True, "RECEIPT_INVALID", "RECEIPT_INVALID"),
        ("current-source", False, "RECEIPT_INVALID", "RECEIPT_INVALID"),
        (
            "current-source",
            True,
            "CURRENT_SOURCE_DIAGNOSTIC_ONLY",
            "accepted",
        ),
    ),
    ids=("archived", "archived-with-repo", "current-missing-repo", "current"),
)
def test_ret_s11_current_source_and_repo_root_parameter_matrix(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    operation: str,
    mode: str,
    use_repo: bool,
    inspect_outcome: str,
    verify_outcome: str,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    repo_root = run.repo if use_repo else None

    if operation == "inspect":
        def call() -> object:
            return _inspect_mode(
                manager,
                run,
                rules_path,
                assessment_path,
                mode=mode,
                repo_root=repo_root,
            )
    else:
        result = _inspect(manager, run, rules_path, assessment_path)

        def call() -> object:
            return _verify_mode(
                manager,
                run,
                result,
                rules_path,
                assessment_path,
                mode=mode,
                repo_root=repo_root,
            )

    # S15 transition: current-source inspection is frozen until report schema
    # v2, while verification of already-existing artifacts remains unchanged.
    outcome = inspect_outcome if operation == "inspect" else verify_outcome
    if outcome == "accepted":
        verified = call()
        assert verified.state == "SCANNED_PASS"
    else:
        _assert_error(manager, outcome, call)


def test_ret_s11_current_source_diagnostic_boundary_precedes_checkout_drift(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    (run.repo / "tracked.txt").write_text("drifted\n", encoding="utf-8")

    _assert_error(
        manager,
        "CURRENT_SOURCE_DIAGNOSTIC_ONLY",
        lambda: _inspect_mode(
            manager,
            run,
            rules_path,
            assessment_path,
            mode="current-source",
            repo_root=run.repo,
        ),
    )
    assert not (run.retention / ".control").exists()


def test_ret_s11_two_concurrent_publishers_have_one_committer(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    entered_scan = threading.Event()
    release_scan = threading.Event()
    gate = threading.Lock()
    held_once = False
    original_scan_tree = manager._scan_tree

    def gated_scan_tree(*args: object, **kwargs: object) -> object:
        nonlocal held_once
        should_hold = False
        with gate:
            if not held_once:
                held_once = True
                should_hold = True
        if should_hold:
            entered_scan.set()
            assert release_scan.wait(timeout=10)
        return original_scan_tree(*args, **kwargs)

    def call() -> tuple[str, object]:
        try:
            return "result", _inspect(manager, run, rules_path, assessment_path)
        except manager.RetentionError as error:
            return "error", error.code

    monkeypatch.setattr(manager, "_scan_tree", gated_scan_tree)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(call)
        assert entered_scan.wait(timeout=10)
        second_future = executor.submit(call)
        try:
            second = second_future.result(timeout=10)
        finally:
            release_scan.set()
        first = first_future.result(timeout=10)

    outcomes = [first, second]
    assert sum(kind == "result" for kind, _value in outcomes) == 1
    assert ("error", "CONTROL_LOCKED") in outcomes
    run_control = run.retention / ".control" / run.receipt.parent.name
    assert len(list((run_control / "inspections").iterdir())) == 1
    assert len(list((run_control / "events").iterdir())) == 1


@pytest.mark.parametrize(
    "matcher,term,sensitive",
    (
        ("literal-ascii-ci", "sentinel-secret", b"sentinel-secret"),
        ("assignment-value-ascii-ci", "token", b"token = contract-secret"),
        ("scheme-value-ascii-ci", "Bearer", b"Bearer contract-secret"),
    ),
)
def test_ret_s11_overlap_hit_has_one_exact_absolute_byte_range(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    matcher: str,
    term: str,
    sensitive: bytes,
) -> None:
    prefix = b"\xff" + b"z" * (_CHUNK_BYTES - 5) + b" "
    expected_start = len(prefix)
    run = sealed_run_factory(untracked={"offset.bin": prefix + sensitive + b" \xfe"})
    rules = _rules()
    rules["rules"] = [
        _rule(
            "SEC-OFFSET",
            category="credential",
            matcher=matcher,
            terms=[term],
            max_value_bytes=(64 if matcher.endswith("value-ascii-ci") else 0),
        )
    ]
    rules_path, assessment_path = _write_config(tmp_path / "config", rules=rules)

    result = _inspect(manager, run, rules_path, assessment_path)

    report = json.loads(_scan_path(result).read_text(encoding="utf-8"))
    records = [item for item in report["files"] if item["path"].endswith("offset.bin")]
    assert records
    expected_hit = {
        "rule_id": "SEC-OFFSET",
        "start_byte": expected_start,
        "end_byte": expected_start + len(sensitive),
    }
    assert all(item["hits"] == [expected_hit] for item in records)


def test_ret_s11_secret_filename_is_absent_from_report_event_and_cli_output(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    secret_name = f"{_SECRET.decode()}.txt"
    run = sealed_run_factory(untracked={secret_name: b"benign content\n"})
    rules_path, assessment_path = _write_config(tmp_path / "config")

    result = _inspect(manager, run, rules_path, assessment_path)

    _assert_no_sensitive_material(
        _scan_path(result).read_bytes(),
        result.control_event_path.read_bytes(),
    )


def test_ret_s11_secret_like_actor_claim_is_rejected_before_control_write(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")

    _assert_error(
        manager,
        "ASSESSMENT_SCHEMA_INVALID",
        lambda: _inspect_actor(
            manager,
            run,
            rules_path,
            assessment_path,
            _SECRET.decode(),
        ),
    )
    assert not (run.retention / ".control").exists()


@pytest.mark.parametrize(
    "actor",
    (
        os.fspath(Path.home()),
        f"operator-{Path.home()}",
        "operator\nsecret",
    ),
    ids=("absolute-home", "embedded-home", "control-character"),
)
def test_ret_s11_actor_path_and_control_characters_are_rejected_without_echo(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    actor: str,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")

    with pytest.raises(manager.RetentionError) as raised:
        _inspect_actor(
            manager,
            run,
            rules_path,
            assessment_path,
            actor,
        )
    assert raised.value.code == "ASSESSMENT_SCHEMA_INVALID"
    _assert_no_sensitive_material(str(raised.value))
    assert not (run.retention / ".control").exists()


# S12: a lock only protects the directory object that owns it; every later control
# operation must remain anchored to that same object for the complete transaction.


@pytest.mark.parametrize("swap_target", ("run-control", "inspections", "events"))
def test_ret_s12_control_tree_swap_after_flock_fails_closed_without_replacement_writes(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap_target: str,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    run_control = run.retention / ".control" / run.receipt.parent.name
    original_flock = manager.fcntl.flock
    swapped = False

    def flock_then_swap(descriptor: int, operation: int) -> None:
        nonlocal swapped
        original_flock(descriptor, operation)
        if (
            not swapped
            and operation & manager.fcntl.LOCK_EX
            and operation & manager.fcntl.LOCK_NB
        ):
            swapped = True
            if swap_target == "run-control":
                displaced = run_control.with_name(f"{run_control.name}.locked")
                run_control.rename(displaced)
                run_control.mkdir(mode=0o700)
                (run_control / "inspections").mkdir(mode=0o700)
                (run_control / "events").mkdir(mode=0o700)
                replacement_lock = run_control / "LOCK"
                replacement_lock.write_bytes(b"")
                replacement_lock.chmod(0o600)
            else:
                replaced = run_control / swap_target
                replaced.rename(run_control / f"{swap_target}.locked")
                replaced.mkdir(mode=0o700)

    monkeypatch.setattr(manager.fcntl, "flock", flock_then_swap)
    error_code: str | None = None
    try:
        _inspect(manager, run, rules_path, assessment_path)
    except manager.RetentionError as error:
        error_code = error.code

    assert swapped is True
    published_counts = (
        len(list((run_control / "inspections").iterdir())),
        len(list((run_control / "events").iterdir())),
    )
    assert published_counts == (0, 0)
    assert error_code == "CONTROL_PUBLICATION_FAILED"


# S13: after the no-replace event rename succeeds, every subsequent failure is an
# uncertain commit regardless of which durability or validation check detects it.


@pytest.mark.parametrize(
    "fault",
    (
        "post-stat",
        "temporary-unlink",
        "target-mode-check",
        "events-fsync",
        "run-fsync",
        "final-verify",
    ),
)
def test_ret_s13_every_post_event_rename_failure_is_commit_uncertain(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    run_control = run.retention / ".control" / run.receipt.parent.name
    original_stat = manager.os.stat
    original_unlink = manager._unlink_control_file
    original_private_file = manager._private_file
    original_fsync = manager._fsync_dir
    event_target_stats = 0

    def stat_fault(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal event_target_stats
        if (
            fault == "post-stat"
            and isinstance(path, (str, bytes))
            and os.fsdecode(path).startswith("00000001-")
            and kwargs.get("dir_fd") is not None
        ):
            event_target_stats += 1
            if event_target_stats == 2:
                raise OSError("injected event post-rename stat fault")
        return original_stat(path, *args, **kwargs)

    def unlink_fault(path: Path) -> None:
        if fault == "temporary-unlink" and path.parent.name == "events":
            raise OSError("injected event temporary unlink fault")
        original_unlink(path)

    def private_file_fault(path: Path) -> None:
        if fault == "target-mode-check" and path.parent.name == "events":
            raise manager.RetentionError("INSPECTION_INVALID")
        original_private_file(path)

    def fsync_fault(path: Path) -> None:
        if fault == "events-fsync" and path.name == "events":
            raise OSError("injected events fsync fault")
        if fault == "run-fsync" and path == run_control:
            raise OSError("injected run control fsync fault")
        original_fsync(path)

    def verify_fault(**_kwargs: object) -> object:
        raise manager.RetentionError("INSPECTION_INVALID")

    monkeypatch.setattr(manager.os, "stat", stat_fault)
    monkeypatch.setattr(manager, "_unlink_control_file", unlink_fault)
    monkeypatch.setattr(manager, "_private_file", private_file_fault)
    monkeypatch.setattr(manager, "_fsync_dir", fsync_fault)
    if fault == "final-verify":
        monkeypatch.setattr(manager, "verify_inspection", verify_fault)

    _assert_error(
        manager,
        "CONTROL_COMMIT_UNCERTAIN",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    visible_events = [
        path
        for path in (run_control / "events").iterdir()
        if not path.name.startswith(".incomplete-")
    ]
    assert len(visible_events) == 1
    assert len(list((run_control / "inspections").iterdir())) == 1


# S12a/S13a: final verification and transaction teardown remain inside the
# event-visible uncertainty boundary.  These are intentionally exact contracts:
# neither a successful return nor a broader set of error codes is acceptable.


def test_ret_s12a_run_control_swap_during_final_verifier_return_is_uncertain_without_replacement_writes(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    run_control = run.retention / ".control" / run.receipt.parent.name
    displaced = run_control.with_name(f"{run_control.name}.verified")
    original_verify = manager.verify_inspection
    swapped = False

    def verify_then_swap(**kwargs: object) -> object:
        nonlocal swapped
        result = original_verify(**kwargs)
        run_control.rename(displaced)
        run_control.mkdir(mode=0o700)
        (run_control / "inspections").mkdir(mode=0o700)
        (run_control / "events").mkdir(mode=0o700)
        replacement_lock = run_control / "LOCK"
        replacement_lock.write_bytes(b"")
        replacement_lock.chmod(0o600)
        swapped = True
        return result

    monkeypatch.setattr(manager, "verify_inspection", verify_then_swap)

    _assert_error(
        manager,
        "CONTROL_COMMIT_UNCERTAIN",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    assert swapped is True
    assert not any((run_control / "inspections").iterdir())
    assert not any((run_control / "events").iterdir())
    assert len(list((displaced / "inspections").iterdir())) == 1
    assert len(list((displaced / "events").iterdir())) == 1


def test_ret_s13a_final_post_event_namespace_check_failure_is_commit_uncertain(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    run_control = run.retention / ".control" / run.receipt.parent.name
    events = run_control / "events"
    original_assert = manager._assert_control_namespace
    post_event_checks = 0
    injected = False

    def fail_final_post_event_check(context: object) -> None:
        nonlocal post_event_checks, injected
        visible_event = events.exists() and any(
            not path.name.startswith(".incomplete-") for path in events.iterdir()
        )
        if visible_event:
            post_event_checks += 1
            if post_event_checks == 2:
                injected = True
                raise OSError("injected final control namespace check fault")
        original_assert(context)

    monkeypatch.setattr(
        manager,
        "_assert_control_namespace",
        fail_final_post_event_check,
    )

    _assert_error(
        manager,
        "CONTROL_COMMIT_UNCERTAIN",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    assert injected is True


def test_ret_s13a_lock_unlock_failure_after_visible_event_is_commit_uncertain(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    run_control = run.retention / ".control" / run.receipt.parent.name
    original_flock = manager.fcntl.flock
    unlock_faults = 0

    def fail_unlock(descriptor: int, operation: int) -> None:
        nonlocal unlock_faults
        if operation == manager.fcntl.LOCK_UN:
            unlock_faults += 1
            raise OSError("injected LOCK_UN fault")
        original_flock(descriptor, operation)

    monkeypatch.setattr(manager.fcntl, "flock", fail_unlock)

    _assert_error(
        manager,
        "CONTROL_COMMIT_UNCERTAIN",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    assert unlock_faults == 1
    assert len(list((run_control / "inspections").iterdir())) == 1
    assert len(list((run_control / "events").iterdir())) == 1


def test_ret_s13a_source_check_after_final_verify_failure_is_commit_uncertain(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    original_verify = manager.verify_inspection
    original_assert_same_tree = manager._assert_same_tree
    final_verify_returned = False
    injected = False

    def mark_final_verify_return(**kwargs: object) -> object:
        nonlocal final_verify_returned
        result = original_verify(**kwargs)
        final_verify_returned = True
        return result

    def fail_first_source_check_after_verify(
        root: Path,
        expected: dict[str, tuple[int, int, int, int, int, int, int, int]],
    ) -> None:
        nonlocal injected
        if final_verify_returned and not injected:
            injected = True
            raise manager.RetentionError("FILE_CHANGED_DURING_SCAN")
        original_assert_same_tree(root, expected)

    monkeypatch.setattr(manager, "verify_inspection", mark_final_verify_return)
    monkeypatch.setattr(manager, "_assert_same_tree", fail_first_source_check_after_verify)

    _assert_error(
        manager,
        "CONTROL_COMMIT_UNCERTAIN",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    assert injected is True


@pytest.mark.parametrize("fault", ("lock-fd-close", "control-context-exit"))
def test_ret_s13b_post_event_teardown_failure_is_uncertain_and_context_is_released(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    run_control = run.retention / ".control" / run.receipt.parent.name
    original_open_lock = manager._open_lock
    original_flock = manager.fcntl.flock
    original_close = manager.os.close
    original_context_factory = manager._control_directory_context
    lock_descriptor: int | None = None
    fault_hits = 0
    teardown_calls = {"unlock": 0, "lock-close": 0, "context-exit": 0}

    def record_lock(path: Path) -> int:
        nonlocal lock_descriptor
        descriptor = original_open_lock(path)
        lock_descriptor = descriptor
        return descriptor

    def record_unlock(descriptor: int, operation: int) -> None:
        if descriptor == lock_descriptor and operation == manager.fcntl.LOCK_UN:
            teardown_calls["unlock"] += 1
        original_flock(descriptor, operation)

    def fail_exact_lock_close(descriptor: int) -> None:
        nonlocal fault_hits
        if descriptor == lock_descriptor:
            teardown_calls["lock-close"] += 1
            original_close(descriptor)
            if fault == "lock-fd-close":
                fault_hits += 1
                raise OSError("injected exact lock fd close fault")
            return
        original_close(descriptor)

    class ContextExitProxy:
        def __init__(self, wrapped: Any) -> None:
            self.wrapped = wrapped

        def __enter__(self) -> object:
            return self.wrapped.__enter__()

        def __exit__(self, *exc_info: object) -> object:
            nonlocal fault_hits
            result = self.wrapped.__exit__(*exc_info)
            teardown_calls["context-exit"] += 1
            if fault == "control-context-exit":
                fault_hits += 1
                raise OSError("injected post-cleanup control context exit fault")
            return result

    def context_factory(
        path: Path,
        inspections: Path,
        events: Path,
    ) -> ContextExitProxy:
        return ContextExitProxy(original_context_factory(path, inspections, events))

    monkeypatch.setattr(manager, "_open_lock", record_lock)
    monkeypatch.setattr(manager.fcntl, "flock", record_unlock)
    monkeypatch.setattr(manager.os, "close", fail_exact_lock_close)
    monkeypatch.setattr(manager, "_control_directory_context", context_factory)

    _assert_error(
        manager,
        "CONTROL_COMMIT_UNCERTAIN",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    assert lock_descriptor is not None
    assert fault_hits == 1
    assert teardown_calls == {"unlock": 1, "lock-close": 1, "context-exit": 1}
    assert len(list((run_control / "inspections").iterdir())) == 1
    assert len(list((run_control / "events").iterdir())) == 1
    assert manager._ACTIVE_CONTROL_CONTEXT.get() is None

    monkeypatch.setattr(manager, "_open_lock", original_open_lock)
    monkeypatch.setattr(manager.fcntl, "flock", original_flock)
    monkeypatch.setattr(manager.os, "close", original_close)
    monkeypatch.setattr(manager, "_control_directory_context", original_context_factory)

    followup = sealed_run_factory()
    followup_result = _inspect(manager, followup, rules_path, assessment_path)
    assert followup_result.state == "SCANNED_PASS"
    assert manager._ACTIVE_CONTROL_CONTEXT.get() is None


def test_ret_s13a_public_api_cli_and_inspection_layout_golden(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    inspect_signature = inspect.signature(manager.inspect_run)
    inspect_parameters = inspect_signature.parameters
    assert tuple(inspect_parameters) == (
        "receipt",
        "rules_path",
        "assessment_path",
        "expected_rules_sha256",
        "expected_assessment_sha256",
        "actor",
        "mode",
        "repo_root",
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in inspect_parameters.values()
    )
    assert inspect_parameters["receipt"].default is inspect.Parameter.empty
    assert inspect_parameters["actor"].default is inspect.Parameter.empty
    assert inspect_parameters["rules_path"].default == manager.DEFAULT_RULES
    assert inspect_parameters["assessment_path"].default == manager.DEFAULT_ASSESSMENT
    assert inspect_parameters["expected_rules_sha256"].default is None
    assert inspect_parameters["expected_assessment_sha256"].default is None
    assert inspect_parameters["mode"].default == "archived-integrity"
    assert inspect_parameters["repo_root"].default is None
    assert {
        name: parameter.annotation for name, parameter in inspect_parameters.items()
    } == {
        "receipt": "Path",
        "rules_path": "Path",
        "assessment_path": "Path",
        "expected_rules_sha256": "str | None",
        "expected_assessment_sha256": "str | None",
        "actor": "str",
        "mode": "Literal['archived-integrity', 'current-source']",
        "repo_root": "Path | None",
    }
    assert inspect_signature.return_annotation == "InspectionResult"

    verify_signature = inspect.signature(manager.verify_inspection)
    verify_parameters = verify_signature.parameters
    assert tuple(verify_parameters) == (
        "receipt",
        "inspection",
        "control_event",
        "rules_path",
        "assessment_path",
        "expected_rules_sha256",
        "expected_assessment_sha256",
        "mode",
        "repo_root",
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in verify_parameters.values()
    )
    assert all(
        verify_parameters[name].default is inspect.Parameter.empty
        for name in ("receipt", "inspection", "control_event")
    )
    assert verify_parameters["rules_path"].default == manager.DEFAULT_RULES
    assert verify_parameters["assessment_path"].default == manager.DEFAULT_ASSESSMENT
    assert verify_parameters["expected_rules_sha256"].default is None
    assert verify_parameters["expected_assessment_sha256"].default is None
    assert verify_parameters["mode"].default == "archived-integrity"
    assert verify_parameters["repo_root"].default is None
    assert {
        name: parameter.annotation for name, parameter in verify_parameters.items()
    } == {
        "receipt": "Path",
        "inspection": "Path",
        "control_event": "Path",
        "rules_path": "Path",
        "assessment_path": "Path",
        "expected_rules_sha256": "str | None",
        "expected_assessment_sha256": "str | None",
        "mode": "Literal['archived-integrity', 'current-source']",
        "repo_root": "Path | None",
    }
    assert verify_signature.return_annotation == "InspectionResult"

    parser = manager._build_parser()
    command_actions = [
        action for action in parser._actions if action.dest == "command"
    ]
    assert len(command_actions) == 1
    assert tuple(command_actions[0].choices) == ("inspect", "verify-inspection")

    expected_inspection_files = {
        "secret-scan.json",
        "secret-rules.json",
        "retention-assessment.json",
        "COMPLETE",
    }
    assert expected_inspection_files == manager.INSPECTION_FILES

    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    result = _inspect(manager, run, rules_path, assessment_path)
    run_control = run.retention / ".control" / run.receipt.parent.name
    assert set(path.name for path in run_control.iterdir()) == {
        "LOCK",
        "inspections",
        "events",
    }
    assert result.inspection_path.parent == run_control / "inspections"
    assert result.control_event_path.parent == run_control / "events"
    assert set(path.name for path in result.inspection_path.iterdir()) == (
        expected_inspection_files
    )
    assert list((run_control / "inspections").iterdir()) == [
        result.inspection_path
    ]
    assert list((run_control / "events").iterdir()) == [result.control_event_path]
    assert stat.S_IMODE(run_control.stat().st_mode) == 0o700
    assert stat.S_IMODE(result.inspection_path.stat().st_mode) == 0o700
    for path in (
        run_control / "LOCK",
        result.control_event_path,
        *(result.inspection_path / name for name in expected_inspection_files),
    ):
        assert stat.S_ISREG(path.stat().st_mode)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


# S14: every inventory budget is enforced while walking the tree.  The entry
# budget counts directory entries (not the synthetic root record), is shared by
# all recursion levels, and must stop scandir before it can exhaust an oversized
# directory into a list for sorting.


def test_ret_s14_shallow_total_entries_over_cap_fails_during_snapshot(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "shallow"
    root.mkdir()
    for name in ("a", "b", "c"):
        (root / name).mkdir()
    _seal_snapshot_fixture(root)
    monkeypatch.setattr(manager, "MAX_RUN_ENTRIES", 2, raising=False)
    monkeypatch.setattr(manager, "MAX_RUN_FILES", 10)
    monkeypatch.setattr(manager, "MAX_RUN_BYTES", 1024)
    monkeypatch.setattr(
        manager,
        "MAX_RUN_SNAPSHOT_METADATA_BYTES",
        1024 * 1024,
        raising=False,
    )

    try:
        _assert_error(
            manager,
            "SCAN_RUN_LIMIT_EXCEEDED",
            lambda: manager._tree_snapshot(root),
        )
    finally:
        _unseal_snapshot_fixture(root)


def test_ret_s14_deep_entries_share_one_global_cap(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "deep"
    (root / "a" / "b" / "c").mkdir(parents=True)
    _seal_snapshot_fixture(root)
    monkeypatch.setattr(manager, "MAX_RUN_ENTRIES", 2, raising=False)
    monkeypatch.setattr(manager, "MAX_RUN_FILES", 10)
    monkeypatch.setattr(manager, "MAX_RUN_BYTES", 1024)
    monkeypatch.setattr(
        manager,
        "MAX_RUN_SNAPSHOT_METADATA_BYTES",
        1024 * 1024,
        raising=False,
    )

    try:
        _assert_error(
            manager,
            "SCAN_RUN_LIMIT_EXCEEDED",
            lambda: manager._tree_snapshot(root),
        )
    finally:
        _unseal_snapshot_fixture(root)


@pytest.mark.parametrize(
    "budget,limit,files",
    (
        ("MAX_RUN_FILES", 2, {"a": b"", "b": b"", "c": b""}),
        ("MAX_RUN_BYTES", 3, {"payload": b"1234"}),
    ),
    ids=("regular-files", "declared-bytes"),
)
def test_ret_s14_file_and_declared_byte_caps_trigger_independently(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    budget: str,
    limit: int,
    files: dict[str, bytes],
) -> None:
    root = tmp_path / budget.lower()
    root.mkdir()
    for name, content in files.items():
        (root / name).write_bytes(content)
    _seal_snapshot_fixture(root)
    monkeypatch.setattr(manager, "MAX_RUN_ENTRIES", 100, raising=False)
    monkeypatch.setattr(manager, "MAX_RUN_FILES", 100)
    monkeypatch.setattr(manager, "MAX_RUN_BYTES", 1024)
    monkeypatch.setattr(
        manager,
        "MAX_RUN_SNAPSHOT_METADATA_BYTES",
        1024 * 1024,
        raising=False,
    )
    monkeypatch.setattr(manager, budget, limit)

    try:
        _assert_error(
            manager,
            "SCAN_RUN_LIMIT_EXCEEDED",
            lambda: manager._tree_snapshot(root),
        )
    finally:
        _unseal_snapshot_fixture(root)


def test_ret_s14_long_basename_snapshot_metadata_cap_is_exact(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "metadata"
    root.mkdir()
    (root / ("x" * 240)).write_bytes(b"")
    _seal_snapshot_fixture(root)
    monkeypatch.setattr(manager, "MAX_RUN_ENTRIES", 10, raising=False)
    monkeypatch.setattr(manager, "MAX_RUN_FILES", 10)
    monkeypatch.setattr(manager, "MAX_RUN_BYTES", 1024)
    monkeypatch.setattr(
        manager,
        "MAX_RUN_SNAPSHOT_METADATA_BYTES",
        1024 * 1024,
        raising=False,
    )

    try:
        baseline = manager._tree_snapshot(root)
        exact_metadata_bytes = len(manager._compact_bytes(baseline))
        monkeypatch.setattr(
            manager,
            "MAX_RUN_SNAPSHOT_METADATA_BYTES",
            exact_metadata_bytes - 1,
        )
        _assert_error(
            manager,
            "SCAN_RUN_LIMIT_EXCEEDED",
            lambda: manager._tree_snapshot(root),
        )
    finally:
        _unseal_snapshot_fixture(root)


def test_ret_s14_scandir_stops_at_cap_plus_one_without_exhausting_iterator(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "lazy-scandir"
    root.mkdir()
    for name in ("a", "b", "c", "d"):
        (root / name).write_bytes(b"")
    original_scandir = manager.os.scandir
    with original_scandir(root) as entries:
        real_entries = sorted(entries, key=lambda entry: entry.name)
    _seal_snapshot_fixture(root)
    monkeypatch.setattr(manager, "MAX_RUN_ENTRIES", 2, raising=False)
    monkeypatch.setattr(manager, "MAX_RUN_FILES", 100)
    monkeypatch.setattr(manager, "MAX_RUN_BYTES", 1024)
    monkeypatch.setattr(
        manager,
        "MAX_RUN_SNAPSHOT_METADATA_BYTES",
        1024 * 1024,
        raising=False,
    )
    iterator_state = {"consumed": 0, "exhaustion_requests": 0}

    class CapPlusOneIterator:
        def __init__(self) -> None:
            self.index = 0

        def __enter__(self) -> CapPlusOneIterator:
            return self

        def __exit__(self, *_exc_info: object) -> None:
            return None

        def __iter__(self) -> CapPlusOneIterator:
            return self

        def __next__(self) -> Any:
            if self.index < len(real_entries):
                entry = real_entries[self.index]
                self.index += 1
                iterator_state["consumed"] += 1
                return entry
            iterator_state["exhaustion_requests"] += 1
            raise AssertionError("scandir iterator was exhausted past cap+1")

    monkeypatch.setattr(manager.os, "scandir", lambda _descriptor: CapPlusOneIterator())

    try:
        _assert_error(
            manager,
            "SCAN_RUN_LIMIT_EXCEEDED",
            lambda: manager._tree_snapshot(root),
        )
        assert iterator_state == {"consumed": 3, "exhaustion_requests": 0}
        assert len(real_entries) - iterator_state["consumed"] == 1
    finally:
        monkeypatch.setattr(manager.os, "scandir", original_scandir)
        _unseal_snapshot_fixture(root)


def test_ret_s14_exact_entry_file_byte_and_metadata_caps_are_accepted(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "exact-boundary"
    root.mkdir()
    (root / "a").write_bytes(b"12")
    (root / "b").write_bytes(b"3")
    _seal_snapshot_fixture(root)
    monkeypatch.setattr(manager, "MAX_RUN_ENTRIES", 100, raising=False)
    monkeypatch.setattr(manager, "MAX_RUN_FILES", 100)
    monkeypatch.setattr(manager, "MAX_RUN_BYTES", 1024)
    monkeypatch.setattr(
        manager,
        "MAX_RUN_SNAPSHOT_METADATA_BYTES",
        1024 * 1024,
        raising=False,
    )

    try:
        baseline = manager._tree_snapshot(root)
        monkeypatch.setattr(manager, "MAX_RUN_ENTRIES", 2)
        monkeypatch.setattr(manager, "MAX_RUN_FILES", 2)
        monkeypatch.setattr(manager, "MAX_RUN_BYTES", 3)
        monkeypatch.setattr(
            manager,
            "MAX_RUN_SNAPSHOT_METADATA_BYTES",
            len(manager._compact_bytes(baseline)),
        )
        assert manager._tree_snapshot(root) == baseline
    finally:
        _unseal_snapshot_fixture(root)


def test_ret_s14_inspect_entry_limit_failure_creates_no_control_tree(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    monkeypatch.setattr(manager, "MAX_RUN_ENTRIES", 1, raising=False)
    error_code: str | None = None

    try:
        _inspect(manager, run, rules_path, assessment_path)
    except manager.RetentionError as error:
        error_code = error.code

    assert error_code == "SCAN_RUN_LIMIT_EXCEEDED"
    assert not (run.retention / ".control").exists()


def test_ret_s14_default_entry_limit_rejects_4097_empty_directories(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert manager.MAX_RUN_ENTRIES == 4096
    root = tmp_path / "default-entry-limit"
    root.mkdir()
    for index in range(manager.MAX_RUN_ENTRIES + 1):
        (root / f"entry-{index:04d}").mkdir()
    assert all(path.is_dir() for path in root.iterdir())
    _seal_snapshot_fixture(root)
    # Empty directories cannot consume the regular-file or declared-byte
    # budgets.  Widen only the platform-sensitive serialized identity budget,
    # so the default entry cap is the sole possible limit at entry 4097.
    monkeypatch.setattr(
        manager,
        "MAX_RUN_SNAPSHOT_METADATA_BYTES",
        16 * 1024 * 1024,
    )

    try:
        _assert_error(
            manager,
            "SCAN_RUN_LIMIT_EXCEEDED",
            lambda: manager._tree_snapshot(root),
        )
    finally:
        _unseal_snapshot_fixture(root)


def test_ret_s14_growth_between_initial_and_assert_same_tree_snapshot_fails_before_control(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    source_root = run.receipt.parent
    initial_entries = sum(1 for _path in source_root.rglob("*"))
    original_snapshot = manager._tree_snapshot
    snapshot_calls = 0
    growth = source_root / "growth-after-first-snapshot"

    def snapshot_with_growth(
        root: Path,
    ) -> dict[str, tuple[int, int, int, int, int, int, int, int]]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls == 2:
            original_mode = stat.S_IMODE(root.stat().st_mode)
            root.chmod(0o700)
            try:
                growth.mkdir()
                growth.chmod(0o500)
            finally:
                root.chmod(original_mode)
        return original_snapshot(root)

    monkeypatch.setattr(manager, "MAX_RUN_ENTRIES", initial_entries)
    monkeypatch.setattr(manager, "_tree_snapshot", snapshot_with_growth)

    _assert_error(
        manager,
        "SCAN_RUN_LIMIT_EXCEEDED",
        lambda: _inspect(manager, run, rules_path, assessment_path),
    )
    assert snapshot_calls == 2
    assert growth.is_dir()
    assert stat.S_IMODE(growth.stat().st_mode) == 0o500
    assert not (run.retention / ".control").exists()


# S15 transition contract: current-source cannot publish schema-v1 reports.
# Verification of historical/current-source artifacts is intentionally not
# broadened here; only the inspect entry point is frozen before control writes.


def test_ret_s15_current_source_api_is_diagnostic_only_before_control_write(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    sealed_before = _tree_snapshot(run.receipt.parent)
    original_private_dir = manager._private_dir
    private_dir_calls: list[Path] = []

    def record_private_dir(path: Path) -> None:
        private_dir_calls.append(path)
        original_private_dir(path)

    monkeypatch.setattr(manager, "_private_dir", record_private_dir)
    error_code: str | None = None
    try:
        _inspect_mode(
            manager,
            run,
            rules_path,
            assessment_path,
            mode="current-source",
            repo_root=run.repo,
        )
    except manager.RetentionError as error:
        error_code = error.code

    assert error_code == "CURRENT_SOURCE_DIAGNOSTIC_ONLY"
    assert private_dir_calls == []
    assert not (run.retention / ".control").exists()
    assert _tree_snapshot(run.receipt.parent) == sealed_before


def test_ret_s15_current_source_cli_is_sanitized_exit_one_without_control_write(
    sealed_run_factory: Callable[..., SealedRun],
) -> None:
    secret_name = f"{_SECRET.decode()}-source.txt"
    run = sealed_run_factory(untracked={secret_name: b"benign\n"})

    completed = _run_cli(
        "inspect",
        "--receipt",
        os.fspath(run.receipt),
        "--actor",
        "cli-contract",
        "--mode",
        "current-source",
        "--repo-root",
        os.fspath(run.repo),
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr == (
        "CURRENT_SOURCE_DIAGNOSTIC_ONLY: request rejected\n"
    )
    _assert_no_sensitive_material(completed.stdout, completed.stderr)
    assert os.fspath(run.receipt) not in completed.stderr
    assert os.fspath(run.repo) not in completed.stderr
    assert secret_name not in completed.stderr
    assert not (run.retention / ".control").exists()


def test_ret_s15_archived_integrity_inspect_and_verify_remain_successful(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")

    inspected = _inspect_mode(
        manager,
        run,
        rules_path,
        assessment_path,
        mode="archived-integrity",
        repo_root=None,
    )
    verified = _verify_mode(
        manager,
        run,
        inspected,
        rules_path,
        assessment_path,
        mode="archived-integrity",
        repo_root=None,
    )

    assert inspected.state == "SCANNED_PASS"
    assert verified.state == "SCANNED_PASS"
    assert verified.inspection_path == inspected.inspection_path
    assert verified.control_event_path == inspected.control_event_path


# S16 process-crash contract.  The worker only monkeypatches private seams in a
# child interpreter; production CLI/configuration has no crash switch.


@dataclass(slots=True)
class _S16Worker:
    process: subprocess.Popen[str]
    ready_fd: int
    release_fd: int
    phase: str


def _spawn_s16_worker(run: SealedRun, phase: str) -> _S16Worker:
    ready_read, ready_write = os.pipe()
    release_read, release_write = os.pipe()
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["LC_ALL"] = "C"
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                os.fspath(_CRASH_WORKER),
                "--mode",
                "inspect",
                "--receipt",
                os.fspath(run.receipt),
                "--actor",
                "s16-process-worker",
                "--phase",
                phase,
                "--ready-fd",
                str(ready_write),
                "--release-fd",
                str(release_read),
            ],
            cwd=_ROOT,
            env=environment,
            pass_fds=(ready_write, release_read),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except BaseException:
        os.close(ready_read)
        os.close(ready_write)
        os.close(release_read)
        os.close(release_write)
        raise
    os.close(ready_write)
    os.close(release_read)
    return _S16Worker(process, ready_read, release_write, phase)


def _await_s16_checkpoint(worker: _S16Worker) -> None:
    readable, _writable, _exceptional = select.select(
        [worker.ready_fd],
        [],
        [],
        10,
    )
    if not readable:
        raise AssertionError(f"worker did not reach {worker.phase!r} within 10 seconds")
    token = os.read(worker.ready_fd, 256)
    assert token == f"{worker.phase}\n".encode("ascii")
    os.close(worker.ready_fd)
    worker.ready_fd = -1


def _finish_s16_worker(
    worker: _S16Worker,
    *,
    kill: bool,
) -> subprocess.CompletedProcess[str]:
    if kill:
        os.kill(worker.process.pid, signal.SIGKILL)
    else:
        os.write(worker.release_fd, b"G")
    stdout, stderr = worker.process.communicate(timeout=10)
    os.close(worker.release_fd)
    worker.release_fd = -1
    return subprocess.CompletedProcess(
        worker.process.args,
        worker.process.returncode,
        stdout,
        stderr,
    )


def _dispose_s16_worker(worker: _S16Worker) -> None:
    for descriptor in (worker.ready_fd, worker.release_fd):
        with suppress(OSError):
            os.close(descriptor)
    if worker.process.poll() is None:
        worker.process.kill()
        worker.process.communicate(timeout=10)


def _s16_classify(run: SealedRun) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            os.fspath(_CRASH_WORKER),
            "--mode",
            "classify",
            "--receipt",
            os.fspath(run.receipt),
        ],
        cwd=_ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C"},
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _s16_control_paths(run: SealedRun) -> tuple[Path, Path, Path]:
    run_control = run.retention / ".control" / run.receipt.parent.name
    return run_control, run_control / "inspections", run_control / "events"


def _assert_s16_private_control_tree(run_control: Path) -> None:
    for path in [run_control.parent, run_control, *sorted(run_control.rglob("*"))]:
        item = path.lstat()
        if stat.S_ISDIR(item.st_mode):
            assert stat.S_IMODE(item.st_mode) == 0o700
        elif stat.S_ISREG(item.st_mode):
            assert stat.S_IMODE(item.st_mode) == 0o600
            assert item.st_nlink == 1
        else:
            raise AssertionError(f"unexpected control node type: {path.name}")


_S16_POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix" or not hasattr(signal, "SIGKILL"),
    reason="requires POSIX pass_fds, flock, and SIGKILL",
)


@pytest.mark.system
@_S16_POSIX_ONLY
def test_ret_s16_subprocess_lock_contention_is_fail_fast_and_write_free(
    sealed_run_factory: Callable[..., SealedRun],
) -> None:
    run = sealed_run_factory()
    sealed_before = _tree_snapshot(run.receipt.parent)
    worker = _spawn_s16_worker(run, "lock-held")
    try:
        _await_s16_checkpoint(worker)
        run_control, inspections, events = _s16_control_paths(run)
        assert list(inspections.iterdir()) == []
        assert list(events.iterdir()) == []

        contender = _run_cli(
            "inspect",
            "--receipt",
            os.fspath(run.receipt),
            "--actor",
            "s16-lock-contender",
        )
        assert contender.returncode == 1
        assert contender.stdout == ""
        assert contender.stderr == "CONTROL_LOCKED: request rejected\n"
        assert list(inspections.iterdir()) == []
        assert list(events.iterdir()) == []

        holder = _finish_s16_worker(worker, kill=False)
        assert holder.returncode == 0
        assert holder.stderr == ""
        assert json.loads(holder.stdout)["state"] == "SCANNED_PASS"
        assert len(list(inspections.iterdir())) == 1
        assert len(list(events.glob("*.json"))) == 1
        assert _tree_snapshot(run.receipt.parent) == sealed_before
        _assert_s16_private_control_tree(run_control)
    finally:
        _dispose_s16_worker(worker)


@pytest.mark.system
@_S16_POSIX_ONLY
def test_ret_s16_two_subprocess_publishers_never_double_commit(
    sealed_run_factory: Callable[..., SealedRun],
) -> None:
    run = sealed_run_factory()
    sealed_before = _tree_snapshot(run.receipt.parent)
    workers = [
        _spawn_s16_worker(run, "before-start"),
        _spawn_s16_worker(run, "before-start"),
    ]
    try:
        for worker in workers:
            _await_s16_checkpoint(worker)
        for worker in workers:
            os.write(worker.release_fd, b"G")
        results: list[subprocess.CompletedProcess[str]] = []
        for worker in workers:
            stdout, stderr = worker.process.communicate(timeout=10)
            results.append(
                subprocess.CompletedProcess(
                    worker.process.args,
                    worker.process.returncode,
                    stdout,
                    stderr,
                )
            )

        successes = [result for result in results if result.returncode == 0]
        failures = [result for result in results if result.returncode != 0]
        assert len(successes) == 1
        assert len(failures) == 1
        assert successes[0].stderr == ""
        assert json.loads(successes[0].stdout)["state"] == "SCANNED_PASS"
        assert failures[0].returncode == 1
        assert failures[0].stdout == ""
        assert failures[0].stderr in {
            "CONTROL_LOCKED: request rejected\n",
            "INSPECTION_ALREADY_COMMITTED: request rejected\n",
        }

        run_control, inspections, events = _s16_control_paths(run)
        assert len(list(inspections.iterdir())) == 1
        assert len(list(events.glob("*.json"))) == 1
        assert not any(
            path.name.startswith(".incomplete-")
            for path in run_control.rglob("*")
        )
        classified = _s16_classify(run)
        assert classified.returncode == 0
        assert classified.stderr == ""
        assert classified.stdout == '{"state":"COMMITTED_VALID"}\n'
        assert _tree_snapshot(run.receipt.parent) == sealed_before
        _assert_s16_private_control_tree(run_control)
    finally:
        for worker in workers:
            _dispose_s16_worker(worker)


@pytest.mark.system
@_S16_POSIX_ONLY
@pytest.mark.parametrize(
    "phase,expected_state,expected_retry",
    (
        ("staging-fsynced", "STAGING_PRESENT", "CONTROL_RECOVERY_REQUIRED"),
        ("inspection-fsynced", "ORPHAN_INSPECTION", "CONTROL_RECOVERY_REQUIRED"),
        ("event-renamed", "COMMITTED_VALID", "INSPECTION_ALREADY_COMMITTED"),
        ("events-fsynced", "COMMITTED_VALID", "INSPECTION_ALREADY_COMMITTED"),
        ("run-fsynced", "COMMITTED_VALID", "INSPECTION_ALREADY_COMMITTED"),
        ("teardown-entered", "COMMITTED_VALID", "INSPECTION_ALREADY_COMMITTED"),
    ),
)
def test_ret_s16_sigkill_checkpoint_has_stable_restart_classification(
    sealed_run_factory: Callable[..., SealedRun],
    phase: str,
    expected_state: str,
    expected_retry: str,
) -> None:
    run = sealed_run_factory()
    sealed_before = _tree_snapshot(run.receipt.parent)
    worker = _spawn_s16_worker(run, phase)
    try:
        _await_s16_checkpoint(worker)
        crashed = _finish_s16_worker(worker, kill=True)
        assert crashed.returncode == -signal.SIGKILL
        assert crashed.stdout == ""
        assert crashed.stderr == ""

        run_control, inspections, events = _s16_control_paths(run)
        control_before = _tree_snapshot(run_control)
        first = _s16_classify(run)
        control_after_first = _tree_snapshot(run_control)
        second = _s16_classify(run)
        control_after_second = _tree_snapshot(run_control)
        expected_output = json.dumps(
            {"state": expected_state},
            separators=(",", ":"),
            sort_keys=True,
        ) + "\n"
        for classified in (first, second):
            assert classified.returncode == 0
            assert classified.stderr == ""
            assert classified.stdout == expected_output
        assert control_after_first == control_before
        assert control_after_second == control_before

        if expected_state == "STAGING_PRESENT":
            entries = list(inspections.iterdir())
            assert len(entries) == 1
            assert entries[0].name.startswith(".incomplete-")
            assert entries[0].is_dir()
            assert list(events.iterdir()) == []
        elif expected_state == "ORPHAN_INSPECTION":
            entries = list(inspections.iterdir())
            assert len(entries) == 1
            assert not entries[0].name.startswith(".incomplete-")
            assert entries[0].is_dir()
            assert list(events.iterdir()) == []
        else:
            published = [
                path
                for path in inspections.iterdir()
                if not path.name.startswith(".incomplete-")
            ]
            event_paths = list(events.glob("*.json"))
            assert len(published) == 1
            assert len(event_paths) == 1
            before_verify = _tree_snapshot(run_control)
            verified = _run_cli(
                "verify-inspection",
                "--receipt",
                os.fspath(run.receipt),
                "--inspection",
                os.fspath(published[0]),
                "--control-event",
                os.fspath(event_paths[0]),
            )
            assert verified.returncode == 0
            assert verified.stderr == ""
            assert json.loads(verified.stdout)["state"] == "SCANNED_PASS"
            assert _tree_snapshot(run_control) == before_verify

        before_retry = _tree_snapshot(run_control)
        retried = _run_cli(
            "inspect",
            "--receipt",
            os.fspath(run.receipt),
            "--actor",
            "s16-retry",
        )
        assert retried.returncode == 1
        assert retried.stdout == ""
        assert retried.stderr == f"{expected_retry}: request rejected\n"
        assert _tree_snapshot(run_control) == before_retry
        assert _tree_snapshot(run.receipt.parent) == sealed_before
        _assert_s16_private_control_tree(run_control)
    finally:
        _dispose_s16_worker(worker)


# S17 input-boundary and real-CLI contract.  Dangerous configuration nodes must
# fail before the control namespace exists, and rejected actor values must never
# be echoed by the production CLI.


@pytest.mark.parametrize("config_name", ("rules", "assessment"))
@pytest.mark.parametrize("kind", ("hardlink", "fifo", "socket"))
def test_ret_s17_config_special_file_fails_before_control_write(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    config_name: str,
    kind: str,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    rules_content = rules_path.read_bytes()
    assessment_content = assessment_path.read_bytes()
    target = rules_path if config_name == "rules" else assessment_path
    target_content = target.read_bytes()
    target.unlink()
    if kind == "hardlink":
        source = target.with_name(f"{target.name}.source")
        source.write_bytes(target_content)
        os.link(source, target)
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        bound_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        previous_directory = Path.cwd()
        try:
            os.chdir(target.parent)
            bound_socket.bind(target.name)
        finally:
            os.chdir(previous_directory)
            bound_socket.close()

    sealed_before = _tree_snapshot(run.receipt.parent)
    expected_code = (
        "RULE_SCHEMA_INVALID"
        if config_name == "rules"
        else "ASSESSMENT_SCHEMA_INVALID"
    )
    _assert_error(
        manager,
        expected_code,
        lambda: manager.inspect_run(
            receipt=run.receipt,
            rules_path=rules_path,
            assessment_path=assessment_path,
            expected_rules_sha256=_sha256(rules_content),
            expected_assessment_sha256=_sha256(assessment_content),
            actor="s17-config-node",
        ),
    )
    assert not (run.retention / ".control").exists()
    assert _tree_snapshot(run.receipt.parent) == sealed_before


@pytest.mark.parametrize("config_name", ("rules", "assessment"))
def test_ret_s17_config_wrong_owner_fails_before_control_write(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_name: str,
) -> None:
    run = sealed_run_factory()
    rules_path, assessment_path = _write_config(tmp_path / "config")
    rules_sha256 = _sha256(rules_path.read_bytes())
    assessment_sha256 = _sha256(assessment_path.read_bytes())
    target = rules_path if config_name == "rules" else assessment_path
    original_stat = manager.os.stat

    def wrong_owner(path: object, *args: object, **kwargs: object) -> os.stat_result:
        item = original_stat(path, *args, **kwargs)
        if path == target.name and kwargs.get("dir_fd") is not None:
            values = list(item)
            values[4] = item.st_uid + 1
            return os.stat_result(values)
        return item

    monkeypatch.setattr(manager.os, "stat", wrong_owner)
    sealed_before = _tree_snapshot(run.receipt.parent)
    expected_code = (
        "RULE_SCHEMA_INVALID"
        if config_name == "rules"
        else "ASSESSMENT_SCHEMA_INVALID"
    )
    _assert_error(
        manager,
        expected_code,
        lambda: manager.inspect_run(
            receipt=run.receipt,
            rules_path=rules_path,
            assessment_path=assessment_path,
            expected_rules_sha256=rules_sha256,
            expected_assessment_sha256=assessment_sha256,
            actor="s17-config-owner",
        ),
    )
    assert not (run.retention / ".control").exists()
    assert _tree_snapshot(run.receipt.parent) == sealed_before


@pytest.mark.parametrize(
    "actor",
    (
        _SECRET.decode(),
        os.fspath(Path.home()),
        f"operator-{Path.home()}",
        "operator\nsecret",
    ),
    ids=("secret", "absolute-home", "embedded-home", "control-character"),
)
def test_ret_s17_real_cli_rejects_sensitive_actor_without_echo(
    sealed_run_factory: Callable[..., SealedRun],
    actor: str,
) -> None:
    run = sealed_run_factory()

    completed = _run_cli(
        "inspect",
        "--receipt",
        os.fspath(run.receipt),
        "--actor",
        actor,
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr == "ASSESSMENT_SCHEMA_INVALID: request rejected\n"
    _assert_no_sensitive_material(completed.stdout, completed.stderr)
    assert actor not in completed.stderr
    assert not (run.retention / ".control").exists()


def test_ret_s17_real_cli_does_not_echo_secret_filename(
    sealed_run_factory: Callable[..., SealedRun],
) -> None:
    secret_name = f"{_SECRET.decode()}.txt"
    run = sealed_run_factory(untracked={secret_name: b"benign content\n"})

    completed = _run_cli(
        "inspect",
        "--receipt",
        os.fspath(run.receipt),
        "--actor",
        "s17-cli-filename",
    )

    assert completed.returncode == 3
    assert completed.stderr == ""
    assert json.loads(completed.stdout)["state"] == "SCANNED_BLOCKED"
    _assert_no_sensitive_material(completed.stdout, completed.stderr)
    assert secret_name not in completed.stdout


@pytest.mark.system
@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="requires Linux mknod device semantics",
)
def test_ret_s17_linux_block_and_char_devices_fail_before_control_write(
    manager: ModuleType,
    sealed_run_factory: Callable[..., SealedRun],
    tmp_path: Path,
) -> None:
    for kind, mode, device in (
        ("block", stat.S_IFBLK | 0o400, os.makedev(7, 0)),
        ("char", stat.S_IFCHR | 0o400, os.makedev(1, 3)),
    ):
        run = sealed_run_factory()
        rules_path, assessment_path = _write_config(tmp_path / kind)
        sealed_root = run.receipt.parent
        target = sealed_root / f"unsafe-{kind}-device"
        sealed_root.chmod(0o700)
        os.mknod(target, mode, device)
        sealed_root.chmod(0o500)
        sealed_before = _tree_snapshot(run.receipt.parent)

        with pytest.raises(manager.RetentionError) as raised:
            _inspect(manager, run, rules_path, assessment_path)
        assert raised.value.code == "UNSAFE_FILE_TYPE"

        assert not (run.retention / ".control").exists()
        assert _tree_snapshot(run.receipt.parent) == sealed_before


# S18 retention-only security coverage.  These contracts exercise the real
# dirfd/path and CLI decision boundaries instead of relying on cross-suite
# coverage data.


def test_ret_s18_path_directory_closes_child_fd_when_fstat_fails(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = tmp_path / "s18-fstat-child"
    child.mkdir()
    original_open = manager.os.open
    original_fstat = manager.os.fstat
    original_close = manager.os.close
    opened_child_fd: int | None = None

    def record_child_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal opened_child_fd
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == child.name and dir_fd is not None:
            opened_child_fd = descriptor
        return descriptor

    def fail_child_fstat(descriptor: int) -> os.stat_result:
        if descriptor == opened_child_fd:
            raise OSError(errno.EIO, "injected child fstat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(manager.os, "open", record_child_open)
    monkeypatch.setattr(manager.os, "fstat", fail_child_fstat)
    _assert_error(
        manager,
        "PATH_INVALID",
        lambda: manager._path_directory_fd(
            child,
            "PATH_INVALID",
        ).__enter__(),
    )
    assert opened_child_fd is not None
    try:
        with pytest.raises(OSError) as raised:
            original_fstat(opened_child_fd)
    finally:
        with suppress(OSError):
            original_close(opened_child_fd)
    assert raised.value.errno == errno.EBADF


def test_ret_s18_anchored_directory_closes_child_fd_when_fstat_fails(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    original_open = manager.os.open
    original_fstat = manager.os.fstat
    original_close = manager.os.close
    opened_child_fd: int | None = None

    def record_child_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal opened_child_fd
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == "child" and dir_fd is not None:
            opened_child_fd = descriptor
        return descriptor

    def fail_child_fstat(descriptor: int) -> os.stat_result:
        if descriptor == opened_child_fd:
            raise OSError(errno.EIO, "injected child fstat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(manager.os, "open", record_child_open)
    monkeypatch.setattr(manager.os, "fstat", fail_child_fstat)
    try:
        _assert_error(
            manager,
            "ANCHOR_INVALID",
            lambda: manager._anchored_directory_fd(
                parent_fd,
                ("child",),
                "ANCHOR_INVALID",
            ).__enter__(),
        )
        assert opened_child_fd is not None
        try:
            with pytest.raises(OSError) as raised:
                original_fstat(opened_child_fd)
        finally:
            with suppress(OSError):
                original_close(opened_child_fd)
        assert raised.value.errno == errno.EBADF
    finally:
        original_close(parent_fd)


def test_ret_s18_relative_parent_fd_closes_child_when_fstat_fails_and_preserves_reason(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "relative-root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    original_open = manager.os.open
    original_fstat = manager.os.fstat
    original_close = manager.os.close
    opened_child_fd: int | None = None

    def record_child_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal opened_child_fd
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == "nested" and dir_fd is not None:
            opened_child_fd = descriptor
        return descriptor

    def fail_child_fstat(descriptor: int) -> os.stat_result:
        if descriptor == opened_child_fd:
            raise OSError(errno.EIO, "injected relative child fstat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(manager.os, "open", record_child_open)
    monkeypatch.setattr(manager.os, "fstat", fail_child_fstat)
    try:
        _assert_error(
            manager,
            "RELATIVE_PARENT_TEST_FAILURE",
            lambda: manager._relative_parent_fd(
                root_fd,
                "nested/leaf.json",
                "RELATIVE_PARENT_TEST_FAILURE",
            ).__enter__(),
        )
        assert opened_child_fd is not None
        with pytest.raises(OSError) as raised:
            original_fstat(opened_child_fd)
        assert raised.value.errno == errno.EBADF
        assert stat.S_ISDIR(original_fstat(root_fd).st_mode)
    finally:
        if opened_child_fd is not None:
            with suppress(OSError):
                original_close(opened_child_fd)
        original_close(root_fd)


def test_ret_s18_private_dir_closes_child_when_fstat_fails(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = tmp_path / "private-control"
    original_open = manager.os.open
    original_fstat = manager.os.fstat
    original_close = manager.os.close
    opened_child_fd: int | None = None

    def record_child_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal opened_child_fd
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == child.name and dir_fd is not None:
            opened_child_fd = descriptor
        return descriptor

    def fail_child_fstat(descriptor: int) -> os.stat_result:
        if descriptor == opened_child_fd:
            raise OSError(errno.EIO, "injected private directory fstat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(manager.os, "open", record_child_open)
    monkeypatch.setattr(manager.os, "fstat", fail_child_fstat)
    try:
        _assert_error(
            manager,
            "CONTROL_PUBLICATION_FAILED",
            lambda: manager._private_dir(child),
        )
        assert opened_child_fd is not None
        with pytest.raises(OSError) as raised:
            original_fstat(opened_child_fd)
        assert raised.value.errno == errno.EBADF
    finally:
        if opened_child_fd is not None:
            with suppress(OSError):
                original_close(opened_child_fd)


def test_ret_s18_tree_snapshot_maps_root_fstat_error_and_closes_root_fd(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "snapshot-root"
    root.mkdir(mode=0o500)
    root.chmod(0o500)
    original_open = manager.os.open
    original_fstat = manager.os.fstat
    original_close = manager.os.close
    opened_root_fd: int | None = None
    root_fstat_calls = 0

    def record_root_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal opened_root_fd
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == root.name and dir_fd is not None:
            opened_root_fd = descriptor
        return descriptor

    def fail_snapshot_root_fstat(descriptor: int) -> os.stat_result:
        nonlocal root_fstat_calls
        if descriptor == opened_root_fd:
            root_fstat_calls += 1
            if root_fstat_calls == 2:
                raise OSError(errno.EIO, "injected snapshot root fstat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(manager.os, "open", record_root_open)
    monkeypatch.setattr(manager.os, "fstat", fail_snapshot_root_fstat)
    try:
        with pytest.raises(manager.RetentionError) as raised:
            manager._tree_snapshot(root)
        assert raised.value.code == "UNSAFE_FILE_TYPE"
        assert opened_root_fd is not None
        assert root_fstat_calls == 2
        with pytest.raises(OSError) as closed:
            original_fstat(opened_root_fd)
        assert closed.value.errno == errno.EBADF
    finally:
        if opened_root_fd is not None:
            with suppress(OSError):
                original_close(opened_root_fd)


@pytest.mark.parametrize(
    ("parts", "node_kind", "expected_code"),
    (
        (("..",), "directory", "ANCHOR_INVALID"),
        (("regular",), "regular", "ANCHOR_INVALID"),
        (("link",), "symlink", "SYMLINK_FORBIDDEN"),
    ),
    ids=("parent-component", "regular-node", "symlink-node"),
)
def test_ret_s18_anchored_directory_rejects_unsafe_components(
    manager: ModuleType,
    tmp_path: Path,
    parts: tuple[str, ...],
    node_kind: str,
    expected_code: str,
) -> None:
    if node_kind == "regular":
        (tmp_path / "regular").write_bytes(b"not a directory")
    elif node_kind == "symlink":
        (tmp_path / "target").mkdir()
        (tmp_path / "link").symlink_to(tmp_path / "target", target_is_directory=True)
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        _assert_error(
            manager,
            expected_code,
            lambda: manager._anchored_directory_fd(
                parent_fd,
                parts,
                "ANCHOR_INVALID",
            ).__enter__(),
        )
    finally:
        os.close(parent_fd)


def test_ret_s18_anchored_directory_rejects_identity_change_and_closes_child(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "child").mkdir()
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    original_open = manager.os.open
    original_fstat = manager.os.fstat
    opened_child_fd: int | None = None

    def record_child_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal opened_child_fd
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == "child" and dir_fd is not None:
            opened_child_fd = descriptor
        return descriptor

    monkeypatch.setattr(manager.os, "open", record_child_open)
    monkeypatch.setattr(manager, "_same_open_directory", lambda _left, _right: False)
    try:
        _assert_error(
            manager,
            "ANCHOR_INVALID",
            lambda: manager._anchored_directory_fd(
                parent_fd,
                ("child",),
                "ANCHOR_INVALID",
            ).__enter__(),
        )
        assert opened_child_fd is not None
        with pytest.raises(OSError) as raised:
            original_fstat(opened_child_fd)
        assert raised.value.errno == errno.EBADF
    finally:
        os.close(parent_fd)


@pytest.mark.parametrize("name", ("", ".", "..", "child/name"))
def test_ret_s18_private_child_rejects_non_leaf_names(
    manager: ModuleType,
    tmp_path: Path,
    name: str,
) -> None:
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        _assert_error(
            manager,
            "PRIVATE_CHILD_INVALID",
            lambda: manager._private_child_directory_fd(
                parent_fd,
                name,
                "PRIVATE_CHILD_INVALID",
            ).__enter__(),
        )
    finally:
        os.close(parent_fd)


@pytest.mark.parametrize(
    ("node_kind", "expected_code"),
    (
        ("wrong-mode-directory", "PRIVATE_CHILD_INVALID"),
        ("regular", "PRIVATE_CHILD_INVALID"),
        ("symlink", "SYMLINK_FORBIDDEN"),
    ),
)
def test_ret_s18_private_child_requires_owned_private_directory(
    manager: ModuleType,
    tmp_path: Path,
    node_kind: str,
    expected_code: str,
) -> None:
    child = tmp_path / "child"
    if node_kind == "wrong-mode-directory":
        child.mkdir(mode=0o755)
        child.chmod(0o755)
    elif node_kind == "regular":
        child.write_bytes(b"not a directory")
    else:
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        child.symlink_to(target, target_is_directory=True)
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        _assert_error(
            manager,
            expected_code,
            lambda: manager._private_child_directory_fd(
                parent_fd,
                "child",
                "PRIVATE_CHILD_INVALID",
            ).__enter__(),
        )
    finally:
        os.close(parent_fd)


def test_ret_s18_private_child_closes_fd_on_fstat_failure(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "child").mkdir(mode=0o700)
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    original_open = manager.os.open
    original_fstat = manager.os.fstat
    opened_child_fd: int | None = None

    def record_child_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal opened_child_fd
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == "child" and dir_fd is not None:
            opened_child_fd = descriptor
        return descriptor

    def fail_child_fstat(descriptor: int) -> os.stat_result:
        if descriptor == opened_child_fd:
            raise OSError(errno.EIO, "injected child fstat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(manager.os, "open", record_child_open)
    monkeypatch.setattr(manager.os, "fstat", fail_child_fstat)
    try:
        _assert_error(
            manager,
            "PRIVATE_CHILD_INVALID",
            lambda: manager._private_child_directory_fd(
                parent_fd,
                "child",
                "PRIVATE_CHILD_INVALID",
            ).__enter__(),
        )
        assert opened_child_fd is not None
        with pytest.raises(OSError) as raised:
            original_fstat(opened_child_fd)
        assert raised.value.errno == errno.EBADF
    finally:
        os.close(parent_fd)


def test_ret_s18_private_child_rejects_identity_change_and_closes_fd(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "child").mkdir(mode=0o700)
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    original_open = manager.os.open
    original_fstat = manager.os.fstat
    opened_child_fd: int | None = None

    def record_child_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal opened_child_fd
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == "child" and dir_fd is not None:
            opened_child_fd = descriptor
        return descriptor

    monkeypatch.setattr(manager.os, "open", record_child_open)
    monkeypatch.setattr(manager, "_same_open_directory", lambda _left, _right: False)
    try:
        _assert_error(
            manager,
            "PRIVATE_CHILD_INVALID",
            lambda: manager._private_child_directory_fd(
                parent_fd,
                "child",
                "PRIVATE_CHILD_INVALID",
            ).__enter__(),
        )
        assert opened_child_fd is not None
        with pytest.raises(OSError) as raised:
            original_fstat(opened_child_fd)
        assert raised.value.errno == errno.EBADF
    finally:
        os.close(parent_fd)


def test_ret_s18_stable_bytes_rejects_declared_oversize_and_short_read(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "config.json"
    target.write_bytes(b"12345")
    _assert_error(
        manager,
        "CONFIG_INVALID",
        lambda: manager._stable_bytes(target, "CONFIG_INVALID", limit=4),
    )

    monkeypatch.setattr(manager.os, "read", lambda _descriptor, _size: b"")
    _assert_error(
        manager,
        "CONFIG_INVALID",
        lambda: manager._stable_bytes(target, "CONFIG_INVALID", limit=5),
    )


def test_ret_s18_stable_bytes_rejects_growth_during_read(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "config.json"
    target.write_bytes(b"1234")
    original_read = manager.os.read
    grown = False

    def grow_before_read(descriptor: int, size: int) -> bytes:
        nonlocal grown
        if not grown:
            grown = True
            with target.open("ab") as stream:
                stream.write(b"56")
        return original_read(descriptor, size)

    monkeypatch.setattr(manager.os, "read", grow_before_read)
    _assert_error(
        manager,
        "CONFIG_INVALID",
        lambda: manager._stable_bytes(target, "CONFIG_INVALID", limit=4),
    )
    assert grown is True
    assert target.read_bytes() == b"123456"


def test_ret_s18_stable_bytes_rejects_post_read_identity_change(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "config.json"
    target.write_bytes(b"stable")
    original_stat = manager.os.stat
    relative_stats = 0

    def mutate_before_final_stat(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal relative_stats
        if path == target.name and kwargs.get("dir_fd") is not None:
            relative_stats += 1
            if relative_stats == 2:
                with target.open("ab") as stream:
                    stream.write(b"-changed")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(manager.os, "stat", mutate_before_final_stat)
    _assert_error(
        manager,
        "CONFIG_INVALID",
        lambda: manager._stable_bytes(target, "CONFIG_INVALID"),
    )
    assert relative_stats == 2
    assert target.read_bytes() == b"stable-changed"


@pytest.mark.parametrize(
    ("argv", "message"),
    (
        (
            ("inspect", "--receipt", "/tmp/receipt", "--actor", "actor", "--rules", "/tmp/rules"),
            "custom --rules requires --expected-rules-sha256",
        ),
        (
            ("inspect", "--receipt", "/tmp/receipt", "--actor", "actor", "--expected-rules-sha256", "0" * 64),
            "--expected-rules-sha256 requires custom --rules",
        ),
        (
            ("inspect", "--receipt", "/tmp/receipt", "--actor", "actor", "--assessment", "/tmp/assessment"),
            "custom --assessment requires --expected-assessment-sha256",
        ),
        (
            ("inspect", "--receipt", "/tmp/receipt", "--actor", "actor", "--expected-assessment-sha256", "0" * 64),
            "--expected-assessment-sha256 requires custom --assessment",
        ),
        (
            ("inspect", "--receipt", "/tmp/receipt", "--actor", "actor", "--mode", "current-source"),
            "--mode current-source requires --repo-root",
        ),
        (
            ("inspect", "--receipt", "/tmp/receipt", "--actor", "actor", "--repo-root", "/tmp/repo"),
            "--repo-root requires --mode current-source",
        ),
    ),
    ids=(
        "rules-without-digest",
        "digest-without-rules",
        "assessment-without-digest",
        "digest-without-assessment",
        "current-source-without-repo",
        "repo-with-archived-mode",
    ),
)
def test_ret_s18_cli_pairing_errors_are_fail_closed(
    manager: ModuleType,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    message: str,
) -> None:
    parser = manager._build_parser()
    arguments = parser.parse_args(argv)
    with pytest.raises(SystemExit) as raised:
        manager._resolve_cli_arguments(parser, arguments)
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.endswith(f"error: {message}\n")


def test_ret_s18_cli_defaults_and_explicit_trust_anchors_are_preserved(
    manager: ModuleType,
) -> None:
    parser = manager._build_parser()
    defaults = parser.parse_args(
        ("inspect", "--receipt", "/tmp/receipt", "--actor", "actor")
    )
    manager._resolve_cli_arguments(parser, defaults)
    assert defaults.rules == manager.DEFAULT_RULES
    assert defaults.assessment == manager.DEFAULT_ASSESSMENT
    assert defaults.expected_rules_sha256 == manager.DEFAULT_RULES_SHA256
    assert defaults.expected_assessment_sha256 == manager.DEFAULT_ASSESSMENT_SHA256

    explicit = parser.parse_args(
        (
            "inspect",
            "--receipt",
            "/tmp/receipt",
            "--actor",
            "actor",
            "--rules",
            "/tmp/rules",
            "--expected-rules-sha256",
            "1" * 64,
            "--assessment",
            "/tmp/assessment",
            "--expected-assessment-sha256",
            "2" * 64,
            "--mode",
            "current-source",
            "--repo-root",
            "/tmp/repo",
        )
    )
    manager._resolve_cli_arguments(parser, explicit)
    assert explicit.rules == Path("/tmp/rules")
    assert explicit.assessment == Path("/tmp/assessment")
    assert explicit.expected_rules_sha256 == "1" * 64
    assert explicit.expected_assessment_sha256 == "2" * 64
    assert explicit.repo_root == Path("/tmp/repo")


def test_ret_s18_open_lock_rejects_non_private_existing_file(
    manager: ModuleType,
    tmp_path: Path,
) -> None:
    run_control = tmp_path / "run"
    run_control.mkdir(mode=0o700)
    lock = run_control / "LOCK"
    lock.write_bytes(b"")
    lock.chmod(0o644)

    _assert_error(
        manager,
        "CONTROL_PUBLICATION_FAILED",
        lambda: manager._open_lock(run_control),
    )
    assert stat.S_IMODE(lock.stat().st_mode) == 0o644


def test_ret_s18_open_lock_rejects_post_flock_name_replacement(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_control = tmp_path / "run"
    run_control.mkdir(mode=0o700)
    original_stat = manager.os.stat
    named_stats = 0
    original_inode: int | None = None

    def replace_before_second_named_stat(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal named_stats, original_inode
        if path == "LOCK" and kwargs.get("dir_fd") is not None:
            named_stats += 1
            if named_stats == 1:
                original_inode = original_stat(path, *args, **kwargs).st_ino
            elif named_stats == 2:
                os.unlink(path, dir_fd=kwargs["dir_fd"])
                replacement = os.open(
                    path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=kwargs["dir_fd"],
                )
                os.close(replacement)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(manager.os, "stat", replace_before_second_named_stat)
    _assert_error(
        manager,
        "CONTROL_PUBLICATION_FAILED",
        lambda: manager._open_lock(run_control),
    )
    assert named_stats == 2
    assert original_inode is not None
    assert (run_control / "LOCK").stat().st_ino != original_inode


def test_ret_s18_rename_noreplace_rejects_unsafe_source_and_existing_target(
    manager: ModuleType,
    tmp_path: Path,
) -> None:
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    _assert_error(
        manager,
        "CONTROL_PUBLICATION_FAILED",
        lambda: manager._rename_noreplace(fifo, tmp_path / "target"),
    )

    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    with pytest.raises(FileExistsError):
        manager._rename_noreplace(source, target)
    assert source.read_bytes() == b"source"
    assert target.read_bytes() == b"target"


def test_ret_s18_native_rename_noreplace_commits_once_and_preserves_existing_target(
    manager: ModuleType,
    tmp_path: Path,
) -> None:
    if sys.platform == "darwin":
        native_symbol = "renameatx_np"
    elif sys.platform.startswith("linux"):
        native_symbol = "renameat2"
    else:
        pytest.fail(f"native no-replace contract unsupported on {sys.platform!r}")

    native_library = manager.ctypes.CDLL(None, use_errno=True)
    assert hasattr(native_library, native_symbol), f"missing native no-replace ABI: {native_symbol}"

    first_source = tmp_path / "first-source"
    second_source = tmp_path / "second-source"
    target = tmp_path / "target"
    first_content = b"first committed payload\n"
    second_content = b"second collision payload\n"
    first_source.write_bytes(first_content)
    second_source.write_bytes(second_content)

    first_before = os.stat(first_source, follow_symlinks=False)
    first_hash = _sha256(first_content)
    second_before = os.stat(second_source, follow_symlinks=False)
    second_hash = _sha256(second_content)

    manager._rename_noreplace(first_source, target)

    assert not first_source.exists()
    target_after_commit = os.stat(target, follow_symlinks=False)
    target_content_after_commit = target.read_bytes()
    target_hash_after_commit = _sha256(target_content_after_commit)
    assert target_after_commit.st_ino == first_before.st_ino
    assert target_content_after_commit == first_content
    assert target_hash_after_commit == first_hash

    with pytest.raises(FileExistsError):
        manager._rename_noreplace(second_source, target)

    target_after_collision = os.stat(target, follow_symlinks=False)
    target_content_after_collision = target.read_bytes()
    second_after_collision = os.stat(second_source, follow_symlinks=False)
    second_content_after_collision = second_source.read_bytes()
    assert target_after_collision.st_ino == target_after_commit.st_ino
    assert target_content_after_collision == target_content_after_commit
    assert _sha256(target_content_after_collision) == target_hash_after_commit
    assert second_after_collision.st_ino == second_before.st_ino
    assert second_content_after_collision == second_content
    assert _sha256(second_content_after_collision) == second_hash


def test_ret_s18_rename_noreplace_rejects_unsupported_platform(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"source")
    monkeypatch.setattr(manager.sys, "platform", "unsupported-test-platform")

    _assert_error(
        manager,
        "NO_REPLACE_UNSUPPORTED",
        lambda: manager._rename_noreplace(source, target),
    )
    assert source.read_bytes() == b"source"
    assert not target.exists()


@pytest.mark.parametrize(
    ("native_errno", "expected"),
    (
        (errno.EEXIST, "exists"),
        (errno.ENOSYS, "unsupported"),
        (errno.EIO, "os-error"),
    ),
)
def test_ret_s18_rename_noreplace_maps_native_errors_without_mutation(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_errno: int,
    expected: str,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"source")

    class NativeRename:
        argtypes: object = None
        restype: object = None

        def __call__(self, *_arguments: object) -> int:
            manager.ctypes.set_errno(native_errno)
            return -1

    class NativeLibrary:
        renameatx_np = NativeRename()
        renameat2 = renameatx_np

    monkeypatch.setattr(manager.ctypes, "CDLL", lambda *_args, **_kwargs: NativeLibrary())
    if expected == "exists":
        with pytest.raises(FileExistsError):
            manager._rename_noreplace(source, target)
    elif expected == "unsupported":
        _assert_error(
            manager,
            "NO_REPLACE_UNSUPPORTED",
            lambda: manager._rename_noreplace(source, target),
        )
    else:
        with pytest.raises(OSError) as raised:
            manager._rename_noreplace(source, target)
        assert raised.value.errno == native_errno
    assert source.read_bytes() == b"source"
    assert not target.exists()


@pytest.mark.parametrize(
    "phase",
    ("initial-stat", "open", "opened-identity", "final-stat"),
)
def test_ret_s18_stable_bytes_maps_every_io_and_identity_failure(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    target = tmp_path / "config.json"
    target.write_bytes(b"stable bytes")
    original_stat = manager.os.stat
    original_open = manager.os.open
    original_fstat = manager.os.fstat
    relative_stats = 0

    def stat_fault(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal relative_stats
        if path == target.name and kwargs.get("dir_fd") is not None:
            relative_stats += 1
            if phase == "initial-stat" and relative_stats == 1:
                raise OSError(errno.EIO, "injected initial stat failure")
            if phase == "final-stat" and relative_stats == 2:
                raise OSError(errno.EIO, "injected final stat failure")
        return original_stat(path, *args, **kwargs)

    def open_fault(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if phase == "open" and path == target.name and dir_fd is not None:
            raise OSError(errno.EIO, "injected open failure")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    def fstat_fault(descriptor: int) -> os.stat_result:
        item = original_fstat(descriptor)
        if phase == "opened-identity" and stat.S_ISREG(item.st_mode):
            values = list(item)
            values[4] = item.st_uid + 1
            return os.stat_result(values)
        return item

    monkeypatch.setattr(manager.os, "stat", stat_fault)
    monkeypatch.setattr(manager.os, "open", open_fault)
    monkeypatch.setattr(manager.os, "fstat", fstat_fault)

    _assert_error(
        manager,
        "CONFIG_INVALID",
        lambda: manager._stable_bytes(target, "CONFIG_INVALID"),
    )
    assert target.read_bytes() == b"stable bytes"


@pytest.mark.parametrize(
    "phase",
    ("create-open", "existing-open", "initial-fstat", "post-flock-fstat"),
)
def test_ret_s18_open_lock_closes_descriptors_on_every_io_failure(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    run_control = tmp_path / "run"
    run_control.mkdir(mode=0o700)
    lock = run_control / "LOCK"
    if phase == "existing-open":
        lock.write_bytes(b"")
        lock.chmod(0o600)
    original_open = manager.os.open
    original_fstat = manager.os.fstat
    lock_fd: int | None = None
    lock_fstats = 0

    def open_fault(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal lock_fd
        if path == "LOCK" and dir_fd is not None:
            if phase == "create-open" and flags & os.O_CREAT:
                raise OSError(errno.EIO, "injected lock create failure")
            if phase == "existing-open" and not flags & os.O_CREAT:
                raise OSError(errno.EIO, "injected existing lock open failure")
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == "LOCK" and dir_fd is not None:
            lock_fd = descriptor
        return descriptor

    def fstat_fault(descriptor: int) -> os.stat_result:
        nonlocal lock_fstats
        if descriptor == lock_fd:
            lock_fstats += 1
            if phase == "initial-fstat" and lock_fstats == 1:
                raise OSError(errno.EIO, "injected initial lock fstat failure")
            if phase == "post-flock-fstat" and lock_fstats == 2:
                raise OSError(errno.EIO, "injected post-flock fstat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(manager.os, "open", open_fault)
    monkeypatch.setattr(manager.os, "fstat", fstat_fault)
    _assert_error(
        manager,
        "CONTROL_PUBLICATION_FAILED",
        lambda: manager._open_lock(run_control),
    )
    if lock_fd is not None:
        with pytest.raises(OSError) as raised:
            original_fstat(lock_fd)
        assert raised.value.errno == errno.EBADF


@pytest.mark.parametrize("phase", ("source-stat", "target-stat"))
def test_ret_s18_rename_noreplace_maps_precommit_stat_failures(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"source")
    original_stat = manager.os.stat

    def stat_fault(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        if kwargs.get("dir_fd") is not None and (
            (phase == "source-stat" and path == source.name)
            or (phase == "target-stat" and path == target.name)
        ):
            raise OSError(errno.EIO, f"injected {phase} failure")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(manager.os, "stat", stat_fault)
    _assert_error(
        manager,
        "CONTROL_PUBLICATION_FAILED",
        lambda: manager._rename_noreplace(source, target),
    )
    assert source.read_bytes() == b"source"
    assert not target.exists()


def test_ret_s18_rename_noreplace_linux_abi_commits_real_rename(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"source")
    calls: list[int] = []

    class LinuxRename:
        argtypes: object = None
        restype: object = None

        def __call__(
            self,
            source_fd: int,
            source_name: bytes,
            target_fd: int,
            target_name: bytes,
            flags: int,
        ) -> int:
            calls.append(flags)
            os.rename(
                source_name,
                target_name,
                src_dir_fd=source_fd,
                dst_dir_fd=target_fd,
            )
            return 0

    class LinuxLibrary:
        renameat2 = LinuxRename()

    monkeypatch.setattr(manager.sys, "platform", "linux")
    monkeypatch.setattr(manager.ctypes, "CDLL", lambda *_args, **_kwargs: LinuxLibrary())
    manager._rename_noreplace(source, target)

    assert calls == [1]
    assert not source.exists()
    assert target.read_bytes() == b"source"


@pytest.mark.parametrize("race", ("missing", "replaced"))
def test_ret_s18_rename_noreplace_rejects_post_syscall_target_race(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    race: str,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"source")

    class DarwinRename:
        argtypes: object = None
        restype: object = None

        def __call__(
            self,
            source_fd: int,
            source_name: bytes,
            target_fd: int,
            target_name: bytes,
            _flags: int,
        ) -> int:
            os.rename(
                source_name,
                target_name,
                src_dir_fd=source_fd,
                dst_dir_fd=target_fd,
            )
            os.unlink(target_name, dir_fd=target_fd)
            if race == "replaced":
                replacement = os.open(
                    target_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=target_fd,
                )
                os.write(replacement, b"replacement")
                os.close(replacement)
            return 0

    class DarwinLibrary:
        renameatx_np = DarwinRename()

    monkeypatch.setattr(manager.sys, "platform", "darwin")
    monkeypatch.setattr(manager.ctypes, "CDLL", lambda *_args, **_kwargs: DarwinLibrary())
    _assert_error(
        manager,
        "CONTROL_PUBLICATION_FAILED",
        lambda: manager._rename_noreplace(source, target),
    )
    assert not source.exists()
    if race == "missing":
        assert not target.exists()
    else:
        assert target.read_bytes() == b"replacement"


def test_ret_s18_post_rename_identity_rejects_wrong_inode(
    manager: ModuleType,
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"content")
    actual = manager._directory_identity(target.stat())
    wrong = (actual[0], actual[1] + 1, *actual[2:])

    _assert_error(
        manager,
        "CONTROL_PUBLICATION_FAILED",
        lambda: manager._post_rename_identity(target, wrong),
    )
    assert target.read_bytes() == b"content"


def test_ret_s18_publish_event_marks_post_rename_exception_uncertain(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = tmp_path / "events"
    events.mkdir(mode=0o700)
    content = b'{"event":"committed"}\n'
    original_rename = manager._rename_noreplace

    def raise_after_commit(source: Path, target: Path) -> None:
        original_rename(source, target)
        raise OSError(errno.EIO, "injected post-rename exception")

    monkeypatch.setattr(manager, "_rename_noreplace", raise_after_commit)
    _assert_error(
        manager,
        "CONTROL_COMMIT_UNCERTAIN",
        lambda: manager._publish_event(events, content, 1),
    )
    visible = [path for path in events.iterdir() if not path.name.startswith(".incomplete-")]
    assert len(visible) == 1
    assert visible[0].read_bytes() == content


def test_ret_s18_scan_file_records_unknown_classification(
    manager: ModuleType,
    tmp_path: Path,
) -> None:
    target = tmp_path / "unknown.bin"
    target.write_bytes(b"ordinary bytes")
    rules_path, _assessment_path = _write_config(tmp_path / "config")
    rules = _load_rules(manager, rules_path)
    root_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        record, errors, exceeded = manager._scan_file(
            root_fd,
            target.name,
            manager._identity(target.stat()),
            rules,
            1024,
            manager.MAX_TOTAL_HITS,
        )
    finally:
        os.close(root_fd)

    assert record["classification"] == "unknown"
    assert record["sha256"] == _sha256(b"ordinary bytes")
    assert errors == [{"code": "CLASSIFICATION_UNKNOWN", "path": target.name}]
    assert exceeded is False


def test_ret_s18_scan_file_preopen_failure_never_closes_sentinel_fd(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "source" / "source.bin"
    target.parent.mkdir()
    target.write_bytes(b"ordinary bytes")
    rules_path, _assessment_path = _write_config(tmp_path / "config")
    rules = _load_rules(manager, rules_path)
    expected = manager._identity(target.stat())
    original_stat = manager.os.stat
    original_close = manager.os.close
    closed: list[int] = []

    def stat_fault(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        if path == target.name and kwargs.get("dir_fd") is not None:
            raise OSError(errno.EIO, "injected pre-open stat failure")
        return original_stat(path, *args, **kwargs)

    def close_spy(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(manager.os, "stat", stat_fault)
    monkeypatch.setattr(manager.os, "close", close_spy)
    root_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    record, errors, exceeded = manager._scan_file(
        root_fd,
        "source/source.bin",
        expected,
        rules,
        1024,
        manager.MAX_TOTAL_HITS,
    )
    assert -1 not in closed
    assert record["sha256"] is None
    assert errors == [
        {"code": "FILE_CHANGED_DURING_SCAN", "path": "source/source.bin"}
    ]
    assert exceeded is False
    original_close(root_fd)


def test_ret_s18_scan_tree_rejects_snapshot_entry_cap_before_open(
    manager: ModuleType,
    tmp_path: Path,
) -> None:
    root_identity = manager._identity(tmp_path.stat())
    snapshot = {".": root_identity}
    snapshot.update(
        {
            f"entry-{index}": root_identity
            for index in range(manager.MAX_RUN_ENTRIES + 1)
        }
    )
    rules_path, _assessment_path = _write_config(tmp_path / "config")
    rules = _load_rules(manager, rules_path)

    _assert_error(
        manager,
        "SCAN_RUN_LIMIT_EXCEEDED",
        lambda: manager._scan_tree(tmp_path, snapshot, rules, 1024),
    )


def test_ret_s18_scan_tree_secondary_file_cap_is_independent(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "file.bin"
    target.write_bytes(b"x")
    snapshot = {
        ".": manager._identity(tmp_path.stat()),
        target.name: manager._identity(target.stat()),
    }
    rules_path, _assessment_path = _write_config(tmp_path / "config")
    rules = _load_rules(manager, rules_path)

    class IndependentBudget:
        def reserve(self, *_args: object, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr(manager, "_SnapshotBudget", IndependentBudget)
    monkeypatch.setattr(manager, "MAX_RUN_FILES", 0)
    _assert_error(
        manager,
        "SCAN_RUN_LIMIT_EXCEEDED",
        lambda: manager._scan_tree(tmp_path, snapshot, rules, 1024),
    )


def test_ret_s18_scan_tree_rejects_root_identity_change_before_file_scan(
    manager: ModuleType,
    tmp_path: Path,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir(mode=0o500)
    root.chmod(0o500)
    snapshot = manager._tree_snapshot(root)
    root.chmod(0o700)
    rules_path, _assessment_path = _write_config(tmp_path / "config")
    rules = _load_rules(manager, rules_path)

    _assert_error(
        manager,
        "FILE_CHANGED_DURING_SCAN",
        lambda: manager._scan_tree(root, snapshot, rules, 1024),
    )


def test_ret_s18_scan_tree_enforces_metadata_output_cap(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir(mode=0o500)
    root.chmod(0o500)
    snapshot = manager._tree_snapshot(root)
    rules_path, _assessment_path = _write_config(tmp_path / "config")
    rules = _load_rules(manager, rules_path)
    monkeypatch.setattr(manager, "MAX_REPORT_METADATA_BYTES", 1)

    _assert_error(
        manager,
        "SCAN_RUN_LIMIT_EXCEEDED",
        lambda: manager._scan_tree(root, snapshot, rules, 1024),
    )


@pytest.mark.parametrize("matcher", ("scheme-value-ascii-ci", "assignment-value-ascii-ci"))
def test_ret_s18_window_hits_reports_matcher_specific_limit_exhaustion(
    manager: ModuleType,
    matcher: str,
) -> None:
    if matcher == "scheme-value-ascii-ci":
        term = b"Bearer"
        content = b"Bearer token"
    else:
        term = b"api_key"
        content = b'api_key="secret"'
    rule = manager.SecretRule("SEC-LIMIT", "credential", matcher, (term,), 64)
    rules = manager.SecretRules(
        "s18-rules",
        manager.SCANNER_ID,
        64,
        (rule,),
        b"",
        "0" * 64,
    )

    hits, exceeded = manager._window_hits(
        content,
        0,
        rules,
        seen=set(),
        limit=0,
    )
    assert hits == set()
    assert exceeded is True


@pytest.mark.parametrize("layout", ("multiple", "wrong-types"))
def test_ret_s18_ledger_state_rejects_ambiguous_layout(
    manager: ModuleType,
    tmp_path: Path,
    layout: str,
) -> None:
    inspections = tmp_path / "inspections"
    events = tmp_path / "events"
    inspections.mkdir()
    events.mkdir()
    if layout == "multiple":
        (inspections / "one").mkdir()
        (inspections / "two").mkdir()
        (events / "event.json").write_bytes(b"{}")
    else:
        (inspections / "not-a-directory").write_bytes(b"bad")
        (events / "event.json").write_bytes(b"{}")

    state = manager._ledger_state(
        receipt=tmp_path / "receipt.json",
        inspections=inspections,
        events=events,
        rules_path=tmp_path / "rules.json",
        assessment_path=tmp_path / "assessment.json",
        expected_rules_sha256="0" * 64,
        expected_assessment_sha256="0" * 64,
        mode="archived-integrity",
        repo_root=None,
    )
    assert state == "LEDGER_INVALID"


def test_ret_s18_ledger_state_classifies_incomplete_staging(
    manager: ModuleType,
    tmp_path: Path,
) -> None:
    inspections = tmp_path / "inspections"
    events = tmp_path / "events"
    inspections.mkdir()
    events.mkdir()
    (inspections / ".incomplete-inspection").mkdir()

    state = manager._ledger_state(
        receipt=tmp_path / "receipt.json",
        inspections=inspections,
        events=events,
        rules_path=tmp_path / "rules.json",
        assessment_path=tmp_path / "assessment.json",
        expected_rules_sha256="0" * 64,
        expected_assessment_sha256="0" * 64,
        mode="archived-integrity",
        repo_root=None,
    )
    assert state == "STAGING_PRESENT"


def test_ret_s18_tree_snapshot_rejects_writable_root_before_walk(
    manager: ModuleType,
    tmp_path: Path,
) -> None:
    root = tmp_path / "writable-root"
    root.mkdir(mode=0o700)
    root.chmod(0o700)

    _assert_error(
        manager,
        "UNSAFE_FILE_TYPE",
        lambda: manager._tree_snapshot(root),
    )
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


@pytest.mark.parametrize(
    ("terms", "matcher", "maximum"),
    (
        (["密码"], "literal-ascii", 0),
        (["bad\nterm"], "literal-ascii", 0),
        (["TOKEN", "token"], "literal-ascii-ci", 0),
        (["token"], "literal-ascii", 1),
        (["token"], "scheme-value-ascii-ci", 0),
    ),
    ids=(
        "non-ascii",
        "control-byte",
        "case-fold-duplicate",
        "literal-has-maximum",
        "scheme-has-no-maximum",
    ),
)
def test_ret_s18_rules_reject_encoded_term_and_matcher_bounds(
    manager: ModuleType,
    tmp_path: Path,
    terms: list[str],
    matcher: str,
    maximum: int,
) -> None:
    document = _rules()
    document["rules"] = [
        _rule(
            "SEC-ENCODING",
            category="credential",
            matcher=matcher,
            terms=terms,
            max_value_bytes=maximum,
        )
    ]
    path = tmp_path / "rules.json"
    path.write_bytes(_json_bytes(document))

    _assert_error(
        manager,
        "RULE_SCHEMA_INVALID",
        lambda: manager.load_secret_rules(
            path,
            expected_sha256=_sha256(path.read_bytes()),
        ),
    )


@pytest.mark.parametrize(
    ("case", "expected_code"),
    (
        ("trust", "ASSESSMENT_TRUST_MISMATCH"),
        ("schema", "ASSESSMENT_SCHEMA_INVALID"),
        ("binding", "RULE_BINDING_MISMATCH"),
    ),
)
def test_ret_s18_assessment_rejects_trust_schema_and_rule_binding(
    manager: ModuleType,
    tmp_path: Path,
    case: str,
    expected_code: str,
) -> None:
    mutation: tuple[str, object] | None = None
    if case == "schema":
        mutation = ("schema", "wrong-schema")
    elif case == "binding":
        mutation = ("scanner.rule_set_sha256", "0" * 64)
    rules_path, assessment_path = _write_config(
        tmp_path / "config",
        assessment_mutation=mutation,
    )
    rules = _load_rules(manager, rules_path)
    expected = "0" * 64 if case == "trust" else _sha256(assessment_path.read_bytes())

    _assert_error(
        manager,
        expected_code,
        lambda: manager.load_retention_assessment(
            assessment_path,
            rules=rules,
            expected_sha256=expected,
        ),
    )


def test_ret_s18_main_dispatches_verify_and_sanitizes_unexpected_error(
    manager: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = manager.InspectionResult(
        inspection_path=Path("/tmp/inspection"),
        control_event_path=Path("/tmp/event"),
        state="SCANNED_PASS",
        run_id="run-id",
        inspection_id="inspection-id",
    )
    calls: list[dict[str, object]] = []

    def verify_stub(**kwargs: object) -> object:
        calls.append(kwargs)
        return result

    monkeypatch.setattr(manager, "verify_inspection", verify_stub)
    exit_code = manager.main(
        [
            "verify-inspection",
            "--receipt",
            "/tmp/receipt",
            "--inspection",
            "/tmp/inspection",
            "--control-event",
            "/tmp/event",
        ]
    )
    assert exit_code == 0
    assert len(calls) == 1
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {
        "inspection_id": "inspection-id",
        "run_id": "run-id",
        "state": "SCANNED_PASS",
    }

    def inspect_fault(**_kwargs: object) -> object:
        raise OSError(errno.EIO, "sensitive internal path /tmp/do-not-echo")

    monkeypatch.setattr(manager, "inspect_run", inspect_fault)
    exit_code = manager.main(
        ["inspect", "--receipt", "/tmp/receipt", "--actor", "actor"]
    )
    assert exit_code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "CONTROL_PUBLICATION_FAILED: request rejected\n"
    assert "do-not-echo" not in output.err


def test_ret_s18_main_sanitizes_retention_error_code(
    manager: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def inspect_fault(**_kwargs: object) -> object:
        raise manager.RetentionError("INSPECTION_INVALID")

    monkeypatch.setattr(manager, "inspect_run", inspect_fault)
    exit_code = manager.main(
        ["inspect", "--receipt", "/tmp/receipt", "--actor", "actor"]
    )
    assert exit_code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "INSPECTION_INVALID: request rejected\n"


# R1: the retention walker is a stable, fd-anchored enforcement seam.  Direct
# contracts must not resolve the source tree by mutable Path after the caller
# has pinned its root descriptor.


def test_ret_s18_walk_retention_tree_records_exact_nested_snapshot(
    manager: ModuleType,
    tmp_path: Path,
) -> None:
    root = tmp_path / "sealed"
    nested = root / "nested"
    nested.mkdir(parents=True)
    top_file = root / "top.bin"
    nested_file = nested / "nested.bin"
    top_file.write_bytes(b"top")
    nested_file.write_bytes(b"nested")
    top_file.chmod(0o400)
    nested_file.chmod(0o400)
    nested.chmod(0o500)
    root.chmod(0o500)
    snapshot: dict[str, tuple[int, int, int, int, int, int, int, int]] = {}
    budget = manager._SnapshotBudget()
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        manager._walk_retention_tree(
            root_fd,
            None,
            budget=budget,
            snapshot=snapshot,
        )
    finally:
        os.close(root_fd)

    assert snapshot == {
        "nested": manager._identity(nested.stat()),
        "nested/nested.bin": manager._identity(nested_file.stat()),
        "top.bin": manager._identity(top_file.stat()),
    }
    assert budget.entries == 3
    assert budget.regular_files == 2
    assert budget.declared_bytes == len(b"topnested")


def test_ret_s18_walk_retention_tree_stops_at_exact_cap_plus_one(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir(mode=0o500)
    root.chmod(0o700)
    for name in ("a", "b", "c"):
        path = root / name
        path.write_bytes(name.encode())
        path.chmod(0o400)
    root.chmod(0o500)
    monkeypatch.setattr(manager, "MAX_RUN_ENTRIES", 2)
    snapshot: dict[str, tuple[int, int, int, int, int, int, int, int]] = {}
    budget = manager._SnapshotBudget()
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        _assert_error(
            manager,
            "SCAN_RUN_LIMIT_EXCEEDED",
            lambda: manager._walk_retention_tree(
                root_fd,
                None,
                budget=budget,
                snapshot=snapshot,
            ),
        )
    finally:
        os.close(root_fd)

    assert budget.entries == 2
    assert budget.regular_files == 2
    assert snapshot == {}


def test_ret_s18_walk_retention_tree_rejects_special_node_before_record(
    manager: ModuleType,
    tmp_path: Path,
) -> None:
    root = tmp_path / "sealed"
    root.mkdir(mode=0o700)
    fifo = root / "unsafe-fifo"
    os.mkfifo(fifo, mode=0o400)
    root.chmod(0o500)
    snapshot: dict[str, tuple[int, int, int, int, int, int, int, int]] = {}
    budget = manager._SnapshotBudget()
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        _assert_error(
            manager,
            "UNSAFE_FILE_TYPE",
            lambda: manager._walk_retention_tree(
                root_fd,
                None,
                budget=budget,
                snapshot=snapshot,
            ),
        )
    finally:
        os.close(root_fd)
    assert budget.entries == 0
    assert snapshot == {}


def test_ret_s18_walk_retention_tree_rejects_child_identity_change(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sealed"
    child = root / "child"
    child.mkdir(parents=True)
    child.chmod(0o500)
    root.chmod(0o500)
    child_inode = child.stat().st_ino
    original_same = manager._same_open_directory
    original_open = manager.os.open
    original_fstat = manager.os.fstat
    child_fd: int | None = None

    def record_child_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal child_fd
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == child.name and dir_fd is not None:
            child_fd = descriptor
        return descriptor

    def changed(left: os.stat_result, right: os.stat_result) -> bool:
        if left.st_ino == child_inode or right.st_ino == child_inode:
            return False
        return original_same(left, right)

    monkeypatch.setattr(manager.os, "open", record_child_open)
    monkeypatch.setattr(manager, "_same_open_directory", changed)
    snapshot: dict[str, tuple[int, int, int, int, int, int, int, int]] = {}
    budget = manager._SnapshotBudget()
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        _assert_error(
            manager,
            "FILE_CHANGED_DURING_SCAN",
            lambda: manager._walk_retention_tree(
                root_fd,
                None,
                budget=budget,
                snapshot=snapshot,
            ),
        )
        assert child_fd is not None
        with pytest.raises(OSError) as raised:
            original_fstat(child_fd)
        assert raised.value.errno == errno.EBADF
    finally:
        os.close(root_fd)


def test_ret_s18_walk_retention_tree_rejects_invalid_provider_entry_name(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidEntry:
        name = ".."

    class InvalidScandir:
        def __enter__(self) -> object:
            return iter((InvalidEntry(),))

        def __exit__(self, *_exc_info: object) -> None:
            return None

    monkeypatch.setattr(manager.os, "scandir", lambda _descriptor: InvalidScandir())
    snapshot: dict[str, tuple[int, int, int, int, int, int, int, int]] = {}
    budget = manager._SnapshotBudget()
    root_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        _assert_error(
            manager,
            "UNSAFE_FILE_TYPE",
            lambda: manager._walk_retention_tree(
                root_fd,
                None,
                budget=budget,
                snapshot=snapshot,
            ),
        )
    finally:
        os.close(root_fd)
    assert budget.entries == 0
    assert snapshot == {}


@pytest.mark.parametrize(
    "phase",
    ("scandir", "entry-stat", "child-open", "child-fstat"),
)
def test_ret_s18_walk_retention_tree_maps_io_failure_and_closes_child(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    root = tmp_path / "sealed"
    child = root / "child"
    child.mkdir(parents=True)
    child.chmod(0o500)
    root.chmod(0o500)
    original_scandir = manager.os.scandir
    original_stat = manager.os.stat
    original_open = manager.os.open
    original_fstat = manager.os.fstat
    child_fd: int | None = None

    def scandir_fault(descriptor: int) -> object:
        if phase == "scandir":
            raise OSError(errno.EIO, "injected scandir failure")
        return original_scandir(descriptor)

    def stat_fault(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        if phase == "entry-stat" and path == child.name:
            raise OSError(errno.EIO, "injected entry stat failure")
        return original_stat(path, *args, **kwargs)

    def open_fault(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal child_fd
        if phase == "child-open" and path == child.name:
            raise OSError(errno.EIO, "injected child open failure")
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == child.name and dir_fd is not None:
            child_fd = descriptor
        return descriptor

    def fstat_fault(descriptor: int) -> os.stat_result:
        if phase == "child-fstat" and descriptor == child_fd:
            raise OSError(errno.EIO, "injected child fstat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(manager.os, "scandir", scandir_fault)
    monkeypatch.setattr(manager.os, "stat", stat_fault)
    monkeypatch.setattr(manager.os, "open", open_fault)
    monkeypatch.setattr(manager.os, "fstat", fstat_fault)
    snapshot: dict[str, tuple[int, int, int, int, int, int, int, int]] = {}
    budget = manager._SnapshotBudget()
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        _assert_error(
            manager,
            "UNSAFE_FILE_TYPE",
            lambda: manager._walk_retention_tree(
                root_fd,
                None,
                budget=budget,
                snapshot=snapshot,
            ),
        )
        if phase == "child-fstat":
            assert child_fd is not None
            with pytest.raises(OSError) as raised:
                original_fstat(child_fd)
            assert raised.value.errno == errno.EBADF
    finally:
        os.close(root_fd)
