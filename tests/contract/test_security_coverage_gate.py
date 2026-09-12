"""Contract tests for the independent S18 security coverage qualification gate."""

from __future__ import annotations

import ast
import base64
import difflib
import errno
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from copy import deepcopy
from functools import lru_cache
from itertools import pairwise, product
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import pytest_security_events as security_events_plugin
from scripts import security_pytest_bootstrap as security_bootstrap
from scripts import verify_security_coverage as security_verifier
from scripts.verify_security_coverage import (
    DEFAULT_MANIFEST,
    DEFAULT_POLICY,
    GateFailure,
    load_manifest,
    load_policy,
    verify_security_coverage,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY_ROOT / "scripts/verify_security_coverage.py"
RUNNER = REPOSITORY_ROOT / "scripts/run_security_coverage.sh"
PYTEST_CONFIG = REPOSITORY_ROOT / "pyproject.toml"
PYTEST_EVENTS_PLUGIN = REPOSITORY_ROOT / "scripts/pytest_security_events.py"
BOOTSTRAP = REPOSITORY_ROOT / "scripts/security_pytest_bootstrap.py"
UV_LOCK = REPOSITORY_ROOT / "uv.lock"
TOOLCHAIN_PATHS = {
    "runner_sha256": RUNNER,
    "verifier_sha256": VERIFIER,
    "bootstrap_sha256": BOOTSTRAP,
    "pytest_config_sha256": PYTEST_CONFIG,
    "pytest_events_plugin_sha256": PYTEST_EVENTS_PLUGIN,
    "uv_lock_sha256": UV_LOCK,
}

B3E_SCENARIO_MANIFEST = (
    REPOSITORY_ROOT / "tests/fixtures/security_coverage_scenarios.json"
)
B3E_SCENARIO_KEYS = frozenset(
    {
        "scenario_id",
        "mutation",
        "target",
        "runner",
        "expected_pytest_exit",
        "expected_outer_exit",
        "expected_gate_failures",
        "required_artifacts",
        "forbidden_artifacts",
        "expected_sentinel_state",
        "victim_nodeid",
        "test_nodeid",
        "status",
    }
)
B3E_IMPLEMENTED_SCENARIO_IDS = (
    "B3E-XFAIL-REQUIRED",
    "B3E-XPASS-NONSTRICT",
    "B3E-XPASS-STRICT",
    "B3E-PLUGIN-IMPORT",
    "B3E-IDENTITY-CONFLICT",
    "B3E-SESSIONFINISH-FAILURE",
    "B3E-EVENTS-PUBLISH-FAILURE",
)
B3E_PLANNED_SCENARIO_IDS = (
    "B3E-PYTEST11-ENTRYPOINT-HOSTILE",
    "B3E-PYTEST-PLUGINS-MARKER-REMOVAL",
    "B3E-PYTEST-ADDOPTS-PLUGIN-INJECTION",
    "B3E-PYTEST-ADDOPTS-K-SELECTION",
    "B3E-PYTEST-ADDOPTS-M-SELECTION",
    "B3E-PYTEST-ADDOPTS-DESELECT",
    "B3E-PYTEST-ADDOPTS-SECOND-PATH",
    "B3E-ANCESTOR-CONFTEST",
    "B3E-REPOSITORY-CONFTEST",
    "B3E-RETENTION-PLUGIN-IMPORT",
    "B3E-RETENTION-IDENTITY-CONFLICT",
    "B3E-RETENTION-SESSIONFINISH-FAILURE",
    "B3E-RETENTION-EVENTS-PUBLISH-FAILURE",
)
B3E_SCENARIO_IDS = B3E_IMPLEMENTED_SCENARIO_IDS + B3E_PLANNED_SCENARIO_IDS
B3E_XFAIL_CASES = (
    ("B3E-XFAIL-REQUIRED", "xfail", 0, ["REQUIRED_TEST_XFAILED"]),
    ("B3E-XPASS-NONSTRICT", "non-strict-xpass", 0, ["REQUIRED_TEST_XFAILED"]),
    (
        "B3E-XPASS-STRICT",
        "strict-xpass",
        1,
        ["COMMAND_FAILED", "REQUIRED_TEST_XFAILED"],
    ),
)
B3E_BOOTSTRAP_FAILURE_CASES = (
    ("B3E-PLUGIN-IMPORT", "plugin-import", 2, "SECURITY_PYTEST_BOOTSTRAP_INVALID"),
    (
        "B3E-IDENTITY-CONFLICT",
        "identity-write",
        3,
        "plugin identity output path is invalid",
    ),
)
B3E_EVENTS_FAILURE_CASES = (
    ("B3E-SESSIONFINISH-FAILURE", "sessionfinish"),
    ("B3E-EVENTS-PUBLISH-FAILURE", "events-write"),
)
B3E_MANIFEST_MUTATIONS = {
    "B3E-XFAIL-REQUIRED": "required-node-xfail-run-true",
    "B3E-XPASS-NONSTRICT": "required-node-xpass-nonstrict",
    "B3E-XPASS-STRICT": "required-node-xpass-strict",
    "B3E-PLUGIN-IMPORT": "local-events-plugin-import-failure",
    "B3E-IDENTITY-CONFLICT": "plugin-identity-final-conflict",
    "B3E-SESSIONFINISH-FAILURE": "events-sessionfinish-failure",
    "B3E-EVENTS-PUBLISH-FAILURE": "events-atomic-write-precall-failure",
}
B3E_IMPLEMENTED_OUTCOMES = {
    **{
        scenario_id: (pytest_exit, tuple(gate_failures))
        for scenario_id, _mutation, pytest_exit, gate_failures in B3E_XFAIL_CASES
    },
    **{
        scenario_id: (pytest_exit, ())
        for scenario_id, _mutation, pytest_exit, _marker in B3E_BOOTSTRAP_FAILURE_CASES
    },
    **{
        scenario_id: (2, ("COMMAND_FAILED", "PYTEST_EVENTS_INVALID"))
        for scenario_id, _mutation in B3E_EVENTS_FAILURE_CASES
    },
}
B3E_PLANNED_AUTHORITY = {
    "B3E-PYTEST11-ENTRYPOINT-HOSTILE": (
        "installed-pytest11-hostile-distribution",
        "capture",
    ),
    "B3E-PYTEST-PLUGINS-MARKER-REMOVAL": (
        "pytest-plugins-removes-required-xfail-marker",
        "capture",
    ),
    "B3E-PYTEST-ADDOPTS-PLUGIN-INJECTION": (
        "pytest-addopts-plugin-injection",
        "capture",
    ),
    "B3E-PYTEST-ADDOPTS-K-SELECTION": (
        "pytest-addopts-k-selection-injection",
        "capture",
    ),
    "B3E-PYTEST-ADDOPTS-M-SELECTION": (
        "pytest-addopts-m-selection-injection",
        "capture",
    ),
    "B3E-PYTEST-ADDOPTS-DESELECT": (
        "pytest-addopts-deselect-injection",
        "capture",
    ),
    "B3E-PYTEST-ADDOPTS-SECOND-PATH": (
        "pytest-addopts-second-test-path-injection",
        "capture",
    ),
    "B3E-ANCESTOR-CONFTEST": ("ancestor-conftest-injection", "capture"),
    "B3E-REPOSITORY-CONFTEST": ("repository-conftest-injection", "capture"),
    "B3E-RETENTION-PLUGIN-IMPORT": (
        "retention-local-events-plugin-import-failure",
        "retention",
    ),
    "B3E-RETENTION-IDENTITY-CONFLICT": (
        "retention-plugin-identity-final-conflict",
        "retention",
    ),
    "B3E-RETENTION-SESSIONFINISH-FAILURE": (
        "retention-events-sessionfinish-failure",
        "retention",
    ),
    "B3E-RETENTION-EVENTS-PUBLISH-FAILURE": (
        "retention-events-atomic-write-precall-failure",
        "retention",
    ),
}
B3E_FULL_ARTIFACTS = frozenset(
    {
        ".coverage-capture",
        "coverage.json",
        "junit.xml",
        "pytest-events.json",
        "plugin-identity.json",
        "environment.json",
        "command.json",
        "run-manifest.json",
        "gate.json",
        "stdout.log",
        "stderr.log",
        "verifier.stderr.log",
    }
)
B3E_EARLY_ARTIFACTS = frozenset(
    {
        "environment.json",
        "command.json",
        "stdout.log",
        "stderr.log",
        "runner-error.json",
    }
)
B3E_EARLY_FORBIDDEN_ARTIFACTS = frozenset(
    {
        "coverage.json",
        "junit.xml",
        "pytest-events.json",
        "plugin-identity.json",
        "run-manifest.json",
        "gate.json",
        "verifier.stderr.log",
    }
)
B3E_ARTIFACT_AUTHORITY = {
    **{
        scenario_id: (B3E_FULL_ARTIFACTS, frozenset(), "not-applicable")
        for scenario_id in B3E_IMPLEMENTED_SCENARIO_IDS[:3]
    },
    "B3E-PLUGIN-IMPORT": (
        B3E_EARLY_ARTIFACTS,
        B3E_EARLY_FORBIDDEN_ARTIFACTS,
        "not-applicable",
    ),
    "B3E-IDENTITY-CONFLICT": (
        B3E_EARLY_ARTIFACTS | {"plugin-identity.json"},
        B3E_EARLY_FORBIDDEN_ARTIFACTS - {"plugin-identity.json"},
        "identity-marker-preserved-mode-0600",
    ),
    **{
        scenario_id: (
            B3E_FULL_ARTIFACTS - {"pytest-events.json"},
            frozenset({"pytest-events.json"}),
            "not-applicable",
        )
        for scenario_id in B3E_IMPLEMENTED_SCENARIO_IDS[5:]
    },
}
B3E_OUTER_TEST_NODEIDS = {
    **{
        scenario_id: (
            "tests/contract/test_security_coverage_gate.py::"
            "test_s18_real_runner_enforces_required_xfail_and_xpass"
            f"[{scenario_id}]"
        )
        for scenario_id in B3E_IMPLEMENTED_SCENARIO_IDS[:3]
    },
    **{
        scenario_id: (
            "tests/contract/test_security_coverage_gate.py::"
            "test_s18_real_runner_retains_raw_when_bootstrap_cannot_produce_identity"
            f"[{scenario_id}]"
        )
        for scenario_id in B3E_IMPLEMENTED_SCENARIO_IDS[3:5]
    },
    **{
        scenario_id: (
            "tests/contract/test_security_coverage_gate.py::"
            "test_s18_real_runner_fails_closed_when_events_are_not_published"
            f"[{scenario_id}]"
        )
        for scenario_id in B3E_IMPLEMENTED_SCENARIO_IDS[5:]
    },
}
_B3E_STABLE_SCENARIO_ID = re.compile(
    r"B3E-[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*\Z"
)

B3F_SCENARIO_KEYS = frozenset(
    {
        "scenario_id",
        "target",
        "fault",
        "publication_phase",
        "expected_producer_code",
        "expected_pytest_exit",
        "expected_outer_exit",
        "expected_gate_failures",
        "required_artifacts",
        "forbidden_artifacts",
        "expected_final_state",
        "expected_temp_state",
        "expected_sentinel_state",
        "outer_nodeid",
        "status",
    }
)


def _b3f_artifact_names(target: str, profile: str) -> tuple[str, ...]:
    full = {
        ".coverage-" + target,
        "coverage.json",
        "junit.xml",
        "pytest-events.json",
        "plugin-identity.json",
        "environment.json",
        "command.json",
        "run-manifest.json",
        "gate.json",
        "stdout.log",
        "stderr.log",
        "verifier.stderr.log",
    }
    if profile == "full":
        return tuple(sorted(full))
    if profile == "no-events":
        return tuple(sorted(full - {"pytest-events.json"}))
    if profile == "no-events-plus-pid-temp":
        return tuple(
            sorted((full - {"pytest-events.json"}) | {"<dynamic-pid-temp>"})
        )
    if profile == "full-plus-pid-temp":
        return tuple(sorted(full | {"<dynamic-pid-temp>"}))
    if profile == "early":
        return (
            "command.json",
            "environment.json",
            "junit.xml",
            "plugin-identity.json",
            "runner-error.json",
            "stderr.log",
            "stdout.log",
        )
    if profile == "early-configure":
        return (
            "command.json",
            "environment.json",
            "plugin-identity.json",
            "runner-error.json",
            "stderr.log",
            "stdout.log",
        )
    if profile == "early-configure-plus-events":
        return tuple(
            sorted(
                (
                    *_b3f_artifact_names(target, "early-configure"),
                    "pytest-events.json",
                )
            )
        )
    raise AssertionError(f"unknown B3f artifact profile: {profile}")


def _b3f_scenario(
    *,
    descriptive_id: str,
    parameter_id: str,
    test_name: str | None,
    target: str,
    fault: str,
    publication_phase: str,
    producer_code: str | None = None,
    pytest_exit: int | None = None,
    outer_exit: int | None = None,
    gate_failures: tuple[str, ...] | None = (),
    artifact_profile: str | None = None,
    final_state: str = "not-applicable",
    temp_state: str = "not-applicable",
    sentinel_state: str = "not-applicable",
    status: str,
) -> dict[str, object]:
    assert status in {"implemented", "planned"}
    runner_existing_attempt = (
        status == "implemented" and artifact_profile == "runner-existing-attempt"
    )
    if status == "planned":
        assert test_name is None
        assert producer_code is pytest_exit is outer_exit is None
        assert gate_failures == () and artifact_profile is None
        assert final_state == temp_state == sentinel_state == "not-applicable"
        required: tuple[str, ...] = ()
    elif runner_existing_attempt:
        assert test_name == "test_s18_b3f_existing_attempt_real_runner"
        assert target == "runner"
        assert fault == "existing-attempt"
        assert publication_phase == "pre-run"
        assert producer_code is pytest_exit is None
        assert outer_exit == 2
        assert gate_failures is None
        assert final_state == temp_state == "not-applicable"
        assert sentinel_state == "unchanged-recursive-tree"
        required = ()
    else:
        assert test_name is not None
        assert target in {"capture", "retention"}
        assert pytest_exit is not None and outer_exit is not None
        assert artifact_profile is not None
        required = _b3f_artifact_names(target, artifact_profile)
    forbidden = []
    if artifact_profile == "no-events":
        forbidden = ["pytest-events.json", "<dynamic-pid-temp>"]
    elif artifact_profile == "no-events-plus-pid-temp":
        forbidden = ["pytest-events.json"]
    elif artifact_profile == "full":
        forbidden = ["<dynamic-pid-temp>"]
    elif artifact_profile == "runner-existing-attempt":
        assert runner_existing_attempt
        forbidden = ["capture", "retention"]
    elif artifact_profile in {
        "early",
        "early-configure",
        "early-configure-plus-events",
    }:
        forbidden = sorted(
            set(_b3f_artifact_names(target, "full"))
            - set(_b3f_artifact_names(target, artifact_profile))
            | {"<dynamic-pid-temp>"}
        )
    return {
        "scenario_id": descriptive_id + ":" + target,
        "target": target,
        "fault": fault,
        "publication_phase": publication_phase,
        "expected_producer_code": producer_code,
        "expected_pytest_exit": pytest_exit,
        "expected_outer_exit": outer_exit,
        "expected_gate_failures": None
        if gate_failures is None
        else list(gate_failures),
        "required_artifacts": list(required),
        "forbidden_artifacts": forbidden,
        "expected_final_state": final_state,
        "expected_temp_state": temp_state,
        "expected_sentinel_state": sentinel_state,
        "outer_nodeid": None
        if test_name is None
        else (
            "tests/contract/test_security_coverage_gate.py::"
            + test_name
            + f"[{parameter_id}]"
        ),
        "status": status,
    }


_B3F_BATCH_A_IMPLEMENTED_VARIANTS = (
    ("B3F-L-007-invalid-limit-zero", "invalid-limit-zero"),
    ("B3F-L-007-invalid-limit-negative", "invalid-limit-negative"),
    ("B3F-L-007-invalid-limit-nondecimal", "invalid-limit-nondecimal"),
    ("B3F-L-007-invalid-limit-nonascii", "invalid-limit-nonascii"),
    ("B3F-L-007-invalid-limit-excessive-digits", "invalid-limit-excessive-digits"),
    ("B3F-L-007-invalid-limit-over-ceiling", "invalid-limit-over-ceiling"),
    ("B3F-L-008-duplicate-max-cases", "duplicate-max-cases"),
    ("B3F-L-008-duplicate-max-nodeid-bytes", "duplicate-max-nodeid-bytes"),
    ("B3F-L-008-duplicate-max-events-bytes", "duplicate-max-events-bytes"),
)
_B3F_BATCH_A_FAULTS = tuple(
    fault for _descriptive_id, fault in _B3F_BATCH_A_IMPLEMENTED_VARIANTS
)
_B3F_BATCH_B_IMPLEMENTED_VARIANTS = (
    ("B3F-L-003-nodeid-boundary", "nodeid-boundary"),
    ("B3F-L-004-nodeid-plus-one-ascii", "nodeid-plus-one-ascii"),
    ("B3F-L-004-nodeid-plus-one-multibyte", "nodeid-plus-one-multibyte"),
)
_B3F_BATCH_B_FAULTS = tuple(
    fault for _descriptive_id, fault in _B3F_BATCH_B_IMPLEMENTED_VARIANTS
)
_B3F_BATCH_C_VARIANTS = (
    ("B3F-L-005-serialized-boundary", "serialized-boundary"),
    ("B3F-L-006-serialized-plus-one", "serialized-plus-one"),
)
_B3F_BATCH_C_FAULTS = tuple(
    fault for _descriptive_id, fault in _B3F_BATCH_C_VARIANTS
)
_B3F_BATCH_D_VARIANTS = (
    ("B3F-L-009-write-zero", "write-zero"),
    ("B3F-L-011-temp-open", "temp-open"),
    ("B3F-L-011-fchmod", "fchmod"),
    ("B3F-L-011-partial-write-success", "partial-write-success"),
    (
        "B3F-L-011-write-exception-after-partial",
        "write-exception-after-partial",
    ),
    ("B3F-L-011-file-fsync", "file-fsync"),
    ("B3F-L-011-file-close", "file-close"),
)
_B3F_BATCH_D_FAULTS = tuple(
    fault for _descriptive_id, fault in _B3F_BATCH_D_VARIANTS
)
_B3F_BATCH_E_VARIANTS = (
    ("B3F-L-010-existing-final", "existing-final", "configure"),
    ("B3F-L-013-preexisting-temp", "preexisting-temp", "pre-publication"),
    ("B3F-L-015-publish-race", "publish-race", "pre-publication"),
)
_B3F_BATCH_E_FAULTS = tuple(
    fault for _descriptive_id, fault, _publication_phase in _B3F_BATCH_E_VARIANTS
)
_B3F_BATCH_F_VARIANTS = (
    ("B3F-L-011-temp-unlink-retry", "temp-unlink-retry"),
    ("B3F-L-011-directory-fsync", "directory-fsync"),
    ("B3F-L-011-directory-close", "directory-close"),
)
_B3F_BATCH_F_FAULTS = tuple(
    fault for _descriptive_id, fault in _B3F_BATCH_F_VARIANTS
)
_B3F_BATCH_G_VARIANTS = (("B3F-L-014-syscall-order", "syscall-order"),)
_B3F_BATCH_G_FAULTS = tuple(
    fault for _descriptive_id, fault in _B3F_BATCH_G_VARIANTS
)


_B3F_IMPLEMENTED_SCENARIO_SPECS = (
    (
        "B3F-L-001-cases-boundary",
        "b3fl001-cases-boundary",
        "cases-boundary",
        "collection",
        None,
        0,
        0,
        (),
        "full",
        "single-link-0600",
        "absent",
        "unchanged-mode-0600",
        "test_s18_b3f_events_limits_real_runner",
    ),
    (
        "B3F-L-002-cases-plus-one",
        "b3fl002-cases-plus-one",
        "cases-plus-one",
        "collection",
        "PYTEST_EVENTS_LIMIT_EXCEEDED",
        4,
        1,
        None,
        "early",
        "absent",
        "absent",
        "unchanged-mode-0600",
        "test_s18_b3f_events_limits_real_runner",
    ),
    *(
        (
            descriptive_id,
            descriptive_id.lower().replace("b3f-l-", "b3fl"),
            fault,
            "collection",
            None
            if fault == "nodeid-boundary"
            else "PYTEST_EVENTS_LIMIT_EXCEEDED",
            0 if fault == "nodeid-boundary" else 4,
            0 if fault == "nodeid-boundary" else 1,
            () if fault == "nodeid-boundary" else None,
            "full" if fault == "nodeid-boundary" else "early",
            "single-link-0600" if fault == "nodeid-boundary" else "absent",
            "absent",
            "unchanged-mode-0600",
            "test_s18_b3f_events_limits_real_runner",
        )
        for descriptive_id, fault in _B3F_BATCH_B_IMPLEMENTED_VARIANTS
    ),
    *(
        (
            descriptive_id,
            descriptive_id.lower().replace("b3f-l-", "b3fl"),
            fault,
            "sessionfinish",
            None
            if fault == "serialized-boundary"
            else "PYTEST_EVENTS_LIMIT_EXCEEDED",
            0 if fault == "serialized-boundary" else 4,
            0 if fault == "serialized-boundary" else 1,
            ()
            if fault == "serialized-boundary"
            else ("COMMAND_FAILED", "PYTEST_EVENTS_INVALID"),
            "full" if fault == "serialized-boundary" else "no-events",
            "single-link-0600" if fault == "serialized-boundary" else "absent",
            "absent",
            "unchanged-mode-0600",
            "test_s18_b3f_events_limits_real_runner",
        )
        for descriptive_id, fault in _B3F_BATCH_C_VARIANTS
    ),
    *(
        (
            descriptive_id,
            descriptive_id.lower().replace("b3f-l-", "b3fl"),
            fault,
            "configure",
            "PYTEST_EVENTS_CONFIGURATION_INVALID",
            4,
            1,
            None,
            "early-configure",
            "absent",
            "absent",
            "unchanged-mode-0600",
            "test_s18_b3f_events_limits_real_runner",
        )
        for descriptive_id, fault in _B3F_BATCH_A_IMPLEMENTED_VARIANTS
    ),
    *(
        (
            descriptive_id,
            descriptive_id.lower().replace("b3f-l-", "b3fl"),
            fault,
            "pre-publication",
            None
            if fault == "partial-write-success"
            else "PYTEST_EVENTS_PUBLICATION_FAILED",
            0 if fault == "partial-write-success" else 1,
            0 if fault == "partial-write-success" else 1,
            ()
            if fault == "partial-write-success"
            else ("COMMAND_FAILED", "PYTEST_EVENTS_INVALID"),
            "full" if fault == "partial-write-success" else "no-events",
            "single-link-0600"
            if fault == "partial-write-success"
            else "absent",
            "absent",
            "unchanged-mode-0600",
            "test_s18_b3f_events_writer_real_runner",
        )
        for descriptive_id, fault in _B3F_BATCH_D_VARIANTS
    ),
    (
        "B3F-L-011-link-failure",
        "b3fl011-link-failure",
        "link-failure",
        "pre-publication",
        "PYTEST_EVENTS_PUBLICATION_FAILED",
        1,
        1,
        ("COMMAND_FAILED", "PYTEST_EVENTS_INVALID"),
        "no-events",
        "absent",
        "absent",
        "unchanged-mode-0600",
        "test_s18_b3f_events_writer_real_runner",
    ),
    (
        "B3F-L-011-temp-unlink",
        "b3fl011-temp-unlink",
        "temp-unlink",
        "post-publication",
        "PYTEST_EVENTS_COMMIT_UNCERTAIN",
        1,
        1,
        ("COMMAND_FAILED", "PYTEST_EVENTS_INVALID"),
        "full-plus-pid-temp",
        "double-link-0600",
        "same-inode-nlink-2",
        "unchanged-mode-0600",
        "test_s18_b3f_events_writer_real_runner",
    ),
    (
        "B3F-L-011-directory-open",
        "b3fl011-directory-open",
        "directory-open",
        "post-publication",
        "PYTEST_EVENTS_COMMIT_UNCERTAIN",
        1,
        1,
        ("COMMAND_FAILED",),
        "full",
        "single-link-0600",
        "absent",
        "unchanged-mode-0600",
        "test_s18_b3f_events_writer_real_runner",
    ),
    (
        "B3F-L-010-existing-final",
        "b3fl010-existing-final",
        "existing-final",
        "configure",
        "PYTEST_EVENTS_CONFIGURATION_INVALID",
        4,
        1,
        None,
        "early-configure-plus-events",
        "protected-single-link-0640",
        "absent",
        "unchanged-mode-0600",
        "test_s18_b3f_events_writer_real_runner",
    ),
    (
        "B3F-L-013-preexisting-temp",
        "b3fl013-preexisting-temp",
        "preexisting-temp",
        "pre-publication",
        "PYTEST_EVENTS_PUBLICATION_FAILED",
        1,
        1,
        ("COMMAND_FAILED", "PYTEST_EVENTS_INVALID"),
        "no-events-plus-pid-temp",
        "absent",
        "protected-single-link-0640",
        "unchanged-mode-0600",
        "test_s18_b3f_events_writer_real_runner",
    ),
    (
        "B3F-L-015-publish-race",
        "b3fl015-publish-race",
        "publish-race",
        "pre-publication",
        "PYTEST_EVENTS_PUBLICATION_FAILED",
        1,
        1,
        ("COMMAND_FAILED", "PYTEST_EVENTS_INVALID"),
        "full",
        "protected-single-link-0640",
        "absent",
        "unchanged-mode-0600",
        "test_s18_b3f_events_writer_real_runner",
    ),
    *(
        (
            descriptive_id,
            descriptive_id.lower().replace("b3f-l-", "b3fl"),
            fault,
            "post-publication",
            "PYTEST_EVENTS_COMMIT_UNCERTAIN",
            1,
            1,
            ("COMMAND_FAILED",),
            "full",
            "single-link-0600",
            "absent",
            "unchanged-mode-0600",
            "test_s18_b3f_events_writer_real_runner",
        )
        for descriptive_id, fault in _B3F_BATCH_F_VARIANTS
    ),
    *(
        (
            descriptive_id,
            descriptive_id.lower().replace("b3f-l-", "b3fl"),
            fault,
            "publication",
            None,
            0,
            0,
            (),
            "full",
            "single-link-0600",
            "absent",
            "unchanged-mode-0600",
            "test_s18_b3f_events_writer_real_runner",
        )
        for descriptive_id, fault in _B3F_BATCH_G_VARIANTS
    ),
)

_B3F_PLANNED_VARIANTS: tuple[tuple[str, str, str], ...] = ()

_B3F_IMPLEMENTED_SCENARIOS = tuple(
    _b3f_scenario(
        descriptive_id=descriptive_id,
        parameter_id=parameter_id + "-" + target,
        test_name=test_name,
        target=target,
        fault=fault,
        publication_phase=publication_phase,
        producer_code=producer_code,
        pytest_exit=pytest_exit,
        outer_exit=outer_exit,
        gate_failures=gate_failures,
        artifact_profile=artifact_profile,
        final_state=final_state,
        temp_state=temp_state,
        sentinel_state=sentinel_state,
        status="implemented",
    )
    for (
        descriptive_id,
        parameter_id,
        fault,
        publication_phase,
        producer_code,
        pytest_exit,
        outer_exit,
        gate_failures,
        artifact_profile,
        final_state,
        temp_state,
        sentinel_state,
        test_name,
    ) in _B3F_IMPLEMENTED_SCENARIO_SPECS
    for target in ("capture", "retention")
)
_B3F_IMPLEMENTED_RUNNER_SCENARIOS = (
    _b3f_scenario(
        descriptive_id="B3F-L-012-existing-attempt",
        parameter_id="b3fl012-existing-attempt-runner",
        test_name="test_s18_b3f_existing_attempt_real_runner",
        target="runner",
        fault="existing-attempt",
        publication_phase="pre-run",
        producer_code=None,
        pytest_exit=None,
        outer_exit=2,
        gate_failures=None,
        artifact_profile="runner-existing-attempt",
        final_state="not-applicable",
        temp_state="not-applicable",
        sentinel_state="unchanged-recursive-tree",
        status="implemented",
    ),
)
B3F_SCENARIOS = (
    _B3F_IMPLEMENTED_SCENARIOS
    + _B3F_IMPLEMENTED_RUNNER_SCENARIOS
    + tuple(
    _b3f_scenario(
        descriptive_id=descriptive_id,
        parameter_id="",
        test_name=None,
        target=target,
        fault=fault,
        publication_phase=publication_phase,
        status="planned",
    )
    for descriptive_id, fault, publication_phase in _B3F_PLANNED_VARIANTS
    for target in (("runner",) if fault == "existing-attempt" else ("capture", "retention"))
    )
)
B3F_IMPLEMENTED_LIMIT_SCENARIOS = tuple(
    scenario
    for scenario in B3F_SCENARIOS
    if scenario["status"] == "implemented"
    and (
        str(scenario["fault"]).startswith("cases-")
        or scenario["fault"] in _B3F_BATCH_A_FAULTS
        or scenario["fault"] in _B3F_BATCH_B_FAULTS
        or scenario["fault"] in _B3F_BATCH_C_FAULTS
    )
)
B3F_IMPLEMENTED_WRITER_SCENARIOS = tuple(
    scenario
    for scenario in B3F_SCENARIOS
    if scenario["status"] == "implemented"
    and (
        scenario["publication_phase"] in {"pre-publication", "post-publication"}
        or scenario["fault"] in _B3F_BATCH_E_FAULTS
        or scenario["fault"] in _B3F_BATCH_G_FAULTS
    )
)


def _assert_b3f_scenario_authority(
    scenarios: tuple[dict[str, object], ...],
) -> None:
    expected_identities = tuple(
        (
            scenario["scenario_id"],
            scenario["target"],
            scenario["fault"],
            scenario["publication_phase"],
        )
        for scenario in (
            _B3F_IMPLEMENTED_SCENARIOS + _B3F_IMPLEMENTED_RUNNER_SCENARIOS
        )
    ) + tuple(
        (
            descriptive_id + ":" + target,
            target,
            fault,
            publication_phase,
        )
        for descriptive_id, fault, publication_phase in _B3F_PLANNED_VARIANTS
        for target in (
            ("runner",) if fault == "existing-attempt" else ("capture", "retention")
        )
    )
    assert len(scenarios) == 67
    assert tuple(
        (
            scenario["scenario_id"],
            scenario["target"],
            scenario["fault"],
            scenario["publication_phase"],
        )
        for scenario in scenarios
    ) == expected_identities
    assert len({scenario["scenario_id"] for scenario in scenarios}) == len(scenarios)
    for scenario in scenarios:
        assert frozenset(scenario) == B3F_SCENARIO_KEYS
        scenario_id = scenario["scenario_id"]
        assert isinstance(scenario_id, str)
        assert re.fullmatch(
            r"B3F-L-[0-9]{3}-[a-z0-9-]+:(?:capture|retention|runner)",
            scenario_id,
        )
        assert scenario["target"] in {"capture", "retention", "runner"}
        assert scenario["status"] in {"implemented", "planned"}
        for field in ("required_artifacts", "forbidden_artifacts"):
            values = scenario[field]
            assert isinstance(values, list)
            assert len(values) == len(set(values))
            assert all(isinstance(value, str) and value for value in values)
        gate_failures = scenario["expected_gate_failures"]
        assert gate_failures is None or (
            isinstance(gate_failures, list)
            and len(gate_failures) == len(set(gate_failures))
            and all(isinstance(value, str) and value for value in gate_failures)
        )
        assert not (
            set(scenario["required_artifacts"])
            & set(scenario["forbidden_artifacts"])
        )
        if scenario["status"] == "planned":
            assert scenario["expected_producer_code"] is None
            assert scenario["expected_pytest_exit"] is None
            assert scenario["expected_outer_exit"] is None
            assert scenario["expected_gate_failures"] == []
            assert scenario["required_artifacts"] == []
            assert scenario["forbidden_artifacts"] == []
            assert scenario["expected_final_state"] == "not-applicable"
            assert scenario["expected_temp_state"] == "not-applicable"
            assert scenario["expected_sentinel_state"] == "not-applicable"
            assert scenario["outer_nodeid"] is None
            continue
        if scenario["target"] == "runner":
            assert scenario == {
                "scenario_id": "B3F-L-012-existing-attempt:runner",
                "target": "runner",
                "fault": "existing-attempt",
                "publication_phase": "pre-run",
                "expected_producer_code": None,
                "expected_pytest_exit": None,
                "expected_outer_exit": 2,
                "expected_gate_failures": None,
                "required_artifacts": [],
                "forbidden_artifacts": ["capture", "retention"],
                "expected_final_state": "not-applicable",
                "expected_temp_state": "not-applicable",
                "expected_sentinel_state": "unchanged-recursive-tree",
                "outer_nodeid": (
                    "tests/contract/test_security_coverage_gate.py::"
                    "test_s18_b3f_existing_attempt_real_runner"
                    "[b3fl012-existing-attempt-runner]"
                ),
                "status": "implemented",
            }
            continue
        assert scenario["target"] in {"capture", "retention"}
        assert isinstance(scenario["expected_pytest_exit"], int)
        assert isinstance(scenario["expected_outer_exit"], int)
        assert scenario["required_artifacts"]
        outer_nodeid = scenario["outer_nodeid"]
        assert isinstance(outer_nodeid, str) and "::" in outer_nodeid
        parameter_id = outer_nodeid.rsplit("[", 1)[1][:-1]
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", parameter_id)
        assert "B3F-L-" not in parameter_id


def _b3f_scenario_by_id(scenario_id: str) -> dict[str, object]:
    scenarios = {
        str(scenario["scenario_id"]): scenario for scenario in B3F_SCENARIOS
    }
    return scenarios[scenario_id]


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate scenario manifest key: {key}")
        result[key] = value
    return result


def _assert_b3e_scenario_authority(scenarios: list[dict[str, object]]) -> None:
    assert tuple(scenario["scenario_id"] for scenario in scenarios) == B3E_SCENARIO_IDS
    for scenario in scenarios:
        scenario_id = scenario["scenario_id"]
        if scenario_id in B3E_IMPLEMENTED_SCENARIO_IDS:
            pytest_exit, gate_failures = B3E_IMPLEMENTED_OUTCOMES[scenario_id]
            required, forbidden, sentinel = B3E_ARTIFACT_AUTHORITY[scenario_id]
            assert scenario["mutation"] == B3E_MANIFEST_MUTATIONS[scenario_id]
            assert scenario["target"] == "capture"
            assert scenario["expected_pytest_exit"] == pytest_exit
            assert scenario["expected_outer_exit"] == 1
            assert tuple(scenario["expected_gate_failures"]) == gate_failures
            assert set(scenario["required_artifacts"]) == required, (
                f"artifact authority mismatch for {scenario_id} required artifacts"
            )
            assert set(scenario["forbidden_artifacts"]) == forbidden, (
                f"artifact authority mismatch for {scenario_id} forbidden artifacts"
            )
            assert scenario["expected_sentinel_state"] == sentinel
            assert scenario["test_nodeid"] == B3E_OUTER_TEST_NODEIDS[scenario_id]
            assert scenario["status"] == "implemented"
            assert scenario["runner"] == "host-contract"
        else:
            mutation, target = B3E_PLANNED_AUTHORITY[scenario_id]
            assert scenario["mutation"] == mutation
            assert scenario["target"] == target
            assert scenario["status"] == "planned"
            assert scenario["runner"] == "macos-linux"
            assert scenario["expected_pytest_exit"] is None
            assert scenario["expected_outer_exit"] is None
            assert scenario["expected_gate_failures"] == []
            assert scenario["required_artifacts"] == []
            assert scenario["forbidden_artifacts"] == []
            assert scenario["expected_sentinel_state"] == "not-characterized"
            assert scenario["victim_nodeid"] is None
            assert scenario["test_nodeid"] is None


def _load_b3e_scenarios(
    path: Path = B3E_SCENARIO_MANIFEST,
) -> tuple[dict[str, object], ...]:
    scenarios = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    assert isinstance(scenarios, list), "scenario manifest must be a JSON array"
    assert scenarios, "scenario manifest must not be empty"
    identifiers: set[str] = set()
    for index, scenario in enumerate(scenarios):
        assert isinstance(scenario, dict), f"scenario {index} must be an object"
        keys = frozenset(scenario)
        assert keys == B3E_SCENARIO_KEYS, (
            f"scenario {index} has missing={sorted(B3E_SCENARIO_KEYS - keys)} "
            f"unknown={sorted(keys - B3E_SCENARIO_KEYS)}"
        )
        scenario_id = scenario["scenario_id"]
        assert isinstance(scenario_id, str)
        assert _B3E_STABLE_SCENARIO_ID.fullmatch(scenario_id), (
            f"unstable scenario_id: {scenario_id!r}"
        )
        assert scenario_id not in identifiers, f"duplicate scenario_id: {scenario_id}"
        identifiers.add(scenario_id)
        for field in (
            "mutation",
            "target",
            "runner",
            "expected_sentinel_state",
            "status",
        ):
            assert isinstance(scenario[field], str) and scenario[field], (
                f"scenario {scenario_id} field {field} must be a non-empty string"
            )
        assert scenario["victim_nodeid"] is None or (
            isinstance(scenario["victim_nodeid"], str)
            and scenario["victim_nodeid"].startswith("tests/")
            and "::" in scenario["victim_nodeid"]
        ), f"scenario {scenario_id} victim_nodeid must be null or an exact nodeid"
        assert scenario["target"] in {"capture", "retention"}
        assert scenario["runner"] in {"host-contract", "macos-linux"}
        assert scenario["status"] in {"implemented", "planned"}
        assert scenario["test_nodeid"] is None or (
            isinstance(scenario["test_nodeid"], str)
            and scenario["test_nodeid"].startswith("tests/")
            and "::" in scenario["test_nodeid"]
        ), f"scenario {scenario_id} test_nodeid must be null or an exact nodeid"
        for field in ("expected_pytest_exit", "expected_outer_exit"):
            value = scenario[field]
            assert value is None or (type(value) is int and value >= 0), (
                f"scenario {scenario_id} field {field} must be null or non-negative"
            )
        for field in (
            "expected_gate_failures",
            "required_artifacts",
            "forbidden_artifacts",
        ):
            values = scenario[field]
            assert isinstance(values, list)
            assert all(isinstance(value, str) and value for value in values)
            assert len(values) == len(set(values)), (
                f"scenario {scenario_id} field {field} contains duplicates"
            )
        assert not (
            set(scenario["required_artifacts"])
            & set(scenario["forbidden_artifacts"])
        ), f"scenario {scenario_id} requires and forbids the same artifact"
    _assert_b3e_scenario_authority(scenarios)
    return tuple(scenarios)


def _b3e_scenario(scenario_id: str) -> dict[str, object]:
    scenarios = {
        scenario["scenario_id"]: scenario for scenario in _load_b3e_scenarios()
    }
    return scenarios[scenario_id]


def _assert_b3e_artifact_contract(
    root: Path, scenario: dict[str, object]
) -> None:
    artifacts = {path.name for path in root.iterdir()}
    assert artifacts == set(scenario["required_artifacts"]), (
        f"artifact allowlist mismatch: actual={sorted(artifacts)}"
    )
    assert not set(scenario["forbidden_artifacts"]) & artifacts


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_events_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_b3e_s_scenario_manifest_has_exact_schema_and_implemented_ids():
    scenarios = _load_b3e_scenarios()

    assert tuple(scenario["scenario_id"] for scenario in scenarios) == B3E_SCENARIO_IDS
    assert tuple(
        scenario["scenario_id"]
        for scenario in scenarios
        if scenario["status"] == "implemented"
    ) == B3E_IMPLEMENTED_SCENARIO_IDS
    assert tuple(
        scenario["scenario_id"]
        for scenario in scenarios
        if scenario["status"] == "planned"
    ) == B3E_PLANNED_SCENARIO_IDS


@pytest.mark.parametrize("mutation", ["missing-key", "unknown-key"])
def test_b3e_s_scenario_manifest_rejects_missing_and_unknown_keys(
    tmp_path, mutation
):
    scenarios = [dict(scenario) for scenario in _load_b3e_scenarios()]
    if mutation == "missing-key":
        scenarios[0].pop("runner")
    else:
        scenarios[0]["qualification"] = "platform-qualified"
    manifest = tmp_path / "scenarios.json"
    _write_json(manifest, scenarios)

    with pytest.raises(AssertionError, match=r"missing=.*unknown="):
        _load_b3e_scenarios(manifest)


def test_b3e_s_scenario_manifest_rejects_duplicate_object_key(tmp_path):
    content = B3E_SCENARIO_MANIFEST.read_text(encoding="utf-8")
    original = '"mutation": "required-node-xfail-run-true",'
    assert content.count(original) == 1
    content = content.replace(
        original,
        '"mutation": "duplicate", ' + original,
        1,
    )
    manifest = tmp_path / "scenarios.json"
    manifest.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate scenario manifest key: mutation"):
        _load_b3e_scenarios(manifest)


def test_b3e_s_scenario_manifest_rejects_duplicate_scenario_id(tmp_path):
    scenarios = [dict(scenario) for scenario in _load_b3e_scenarios()]
    scenarios[1]["scenario_id"] = scenarios[0]["scenario_id"]
    manifest = tmp_path / "scenarios.json"
    _write_json(manifest, scenarios)

    with pytest.raises(AssertionError, match="duplicate scenario_id"):
        _load_b3e_scenarios(manifest)


@pytest.mark.parametrize(
    "unstable_id",
    ["xfail-0-expected_failures0", "B3E_XFAIL_REQUIRED", "B3E-XFAIL-0"],
)
def test_b3e_s_scenario_manifest_rejects_unstable_scenario_id(
    tmp_path, unstable_id
):
    scenarios = [dict(scenario) for scenario in _load_b3e_scenarios()]
    scenarios[0]["scenario_id"] = unstable_id
    manifest = tmp_path / "scenarios.json"
    _write_json(manifest, scenarios)

    with pytest.raises(AssertionError, match="unstable scenario_id"):
        _load_b3e_scenarios(manifest)


def test_b3e_s_scenario_manifest_matches_implemented_parameter_matrix():
    scenarios = {
        scenario["scenario_id"]: scenario for scenario in _load_b3e_scenarios()
        if scenario["status"] == "implemented"
    }
    expected = {
        scenario_id: (pytest_exit, gate_failures)
        for scenario_id, _mutation, pytest_exit, gate_failures in B3E_XFAIL_CASES
    }
    expected.update(
        {
            scenario_id: (pytest_exit, [])
            for scenario_id, _mutation, pytest_exit, _ in B3E_BOOTSTRAP_FAILURE_CASES
        }
    )
    expected.update(
        {
            scenario_id: (2, ["COMMAND_FAILED", "PYTEST_EVENTS_INVALID"])
            for scenario_id, _mutation in B3E_EVENTS_FAILURE_CASES
        }
    )

    assert set(scenarios) == set(expected)
    for scenario_id, (pytest_exit, gate_failures) in expected.items():
        scenario = scenarios[scenario_id]
        assert scenario["mutation"] == B3E_MANIFEST_MUTATIONS[scenario_id]
        assert scenario["target"] == "capture"
        assert scenario["runner"] == "host-contract"
        assert scenario["expected_pytest_exit"] == pytest_exit
        assert scenario["expected_outer_exit"] == 1
        assert scenario["expected_gate_failures"] == gate_failures
        assert scenario["status"] == "implemented"
        if scenario_id in B3E_IMPLEMENTED_SCENARIO_IDS[:3]:
            assert scenario["victim_nodeid"] == (
                "tests/contract/test_evidence_capture.py::"
                "test_archived_integrity_rejects_tampered_untracked_snapshot"
            )
        else:
            assert scenario["victim_nodeid"] is None


def test_b3e_s_scenario_manifest_binds_exact_outer_test_nodeid():
    scenarios = _load_b3e_scenarios()

    for scenario in scenarios:
        if scenario["status"] == "implemented":
            assert scenario["test_nodeid"] == B3E_OUTER_TEST_NODEIDS[
                scenario["scenario_id"]
            ]
        else:
            assert scenario["test_nodeid"] is None


def test_b3e_s_scenario_manifest_keeps_unimplemented_hostile_scope_visible():
    scenarios = _load_b3e_scenarios()

    assert tuple(
        scenario["scenario_id"]
        for scenario in scenarios
        if scenario["status"] == "planned"
    ) == B3E_PLANNED_SCENARIO_IDS


def test_b3e_s_scenario_manifest_rejects_implemented_artifact_profile_shrink(
    tmp_path,
):
    scenarios = [dict(scenario) for scenario in _load_b3e_scenarios()]
    scenarios[0]["required_artifacts"] = []
    scenarios[0]["forbidden_artifacts"] = []
    manifest = tmp_path / "scenarios.json"
    _write_json(manifest, scenarios)

    with pytest.raises(AssertionError, match="artifact authority mismatch"):
        _load_b3e_scenarios(manifest)


def test_b3e_s_implemented_artifact_profile_rejects_unknown_extra(tmp_path):
    scenario = _b3e_scenario("B3E-XFAIL-REQUIRED")
    for artifact in scenario["required_artifacts"]:
        (tmp_path / artifact).touch()
    (tmp_path / "runner-error.json").touch()

    with pytest.raises(AssertionError, match="artifact allowlist mismatch"):
        _assert_b3e_artifact_contract(tmp_path, scenario)


def test_b3e_s_scenario_manifest_rejects_sentinel_or_outer_nodeid_drift(
    tmp_path,
):
    scenarios = [dict(scenario) for scenario in _load_b3e_scenarios()]
    scenarios[4]["expected_sentinel_state"] = "not-applicable"
    manifest = tmp_path / "sentinel-drift.json"
    _write_json(manifest, scenarios)
    with pytest.raises(AssertionError):
        _load_b3e_scenarios(manifest)

    scenarios = [dict(scenario) for scenario in _load_b3e_scenarios()]
    scenarios[0]["test_nodeid"] = scenarios[1]["test_nodeid"]
    manifest = tmp_path / "outer-nodeid-drift.json"
    _write_json(manifest, scenarios)
    with pytest.raises(AssertionError):
        _load_b3e_scenarios(manifest)

    scenarios = [dict(scenario) for scenario in _load_b3e_scenarios()]
    scenarios[-1]["mutation"] = "claimed-complete-without-implementation"
    manifest = tmp_path / "planned-drift.json"
    _write_json(manifest, scenarios)
    with pytest.raises(AssertionError):
        _load_b3e_scenarios(manifest)


def test_b3e_s_scenario_manifest_rejects_planned_scope_shrink_or_drift(
    tmp_path,
):
    scenarios = [dict(scenario) for scenario in _load_b3e_scenarios()]
    scenarios.pop()
    manifest = tmp_path / "planned-shrink.json"
    _write_json(manifest, scenarios)
    with pytest.raises(AssertionError):
        _load_b3e_scenarios(manifest)


def test_b3f_s_scenario_authority_has_exact_schema_and_complete_variant_scope():
    _assert_b3f_scenario_authority(B3F_SCENARIOS)

    assert len(B3F_SCENARIO_KEYS) == 15
    assert all("mutation_recipe_id" not in scenario for scenario in B3F_SCENARIOS)
    assert {
        scenario["fault"]
        for scenario in B3F_SCENARIOS
        if str(scenario["scenario_id"]).startswith("B3F-L-011-")
    } == {
        "temp-open",
        "fchmod",
        "partial-write-success",
        "write-exception-after-partial",
        "file-fsync",
        "file-close",
        "link-failure",
        "temp-unlink",
        "temp-unlink-retry",
        "directory-open",
        "directory-fsync",
        "directory-close",
    }


def test_b3f_s_scenario_authority_keeps_unexecuted_facts_planned():
    _assert_b3f_scenario_authority(B3F_SCENARIOS)

    planned = tuple(
        scenario for scenario in B3F_SCENARIOS if scenario["status"] == "planned"
    )
    implemented = tuple(
        scenario for scenario in B3F_SCENARIOS if scenario["status"] == "implemented"
    )
    assert len(implemented) == 67
    assert len(planned) == 0
    assert len(planned) + len(B3F_IMPLEMENTED_LIMIT_SCENARIOS) + len(
        B3F_IMPLEMENTED_WRITER_SCENARIOS
    ) + len(_B3F_IMPLEMENTED_RUNNER_SCENARIOS) == 67
    existing_attempt = tuple(
        scenario for scenario in B3F_SCENARIOS if scenario["fault"] == "existing-attempt"
    )
    assert len(existing_attempt) == 1
    assert existing_attempt[0]["target"] == "runner"
    assert existing_attempt[0]["publication_phase"] == "pre-run"
    assert existing_attempt[0]["status"] == "implemented"


@lru_cache(maxsize=2)
def _captured_runtime_identity(runner: str) -> dict[str, object]:
    executable = Path(sys.executable)
    runtime_layout = security_bootstrap._capture_runtime_layout(
        executable,
        python_major_minor=(sys.version_info.major, sys.version_info.minor),
        base_prefix=Path(sys.base_prefix),
    )
    runtime_layout.update({"isolated": True, "no_site": True, "dont_write_bytecode": True})
    site_packages = Path(runtime_layout["site_packages"])
    distributions = {}
    for name in security_bootstrap._RUNTIME_DISTRIBUTIONS:
        installed, _descriptors, _sources = security_bootstrap._capture_named_distribution(
            site_packages,
            canonical_name=name,
            required_paths=security_bootstrap._RUNTIME_REQUIRED_PATHS[name],
        )
        assert type(installed["name"]) is str
        assert type(installed["version"]) is str
        lock = security_bootstrap._capture_lock_package(
            UV_LOCK,
            canonical_name=name,
            required_dependencies=security_bootstrap._RUNTIME_REQUIRED_DEPENDENCIES[name],
        )
        distributions[name] = {"installed": installed, "lock": lock}
    uv_path = Path(shutil.which("uv") or "").resolve(strict=True)
    uv_content = uv_path.read_bytes()
    pytest_cov_entry = distributions["pytest-cov"]["installed"]["required_entries"][
        "pytest_cov/plugin.py"
    ]
    host_runner = "macos" if sys.platform == "darwin" else "linux"
    document = security_bootstrap._build_runtime_identity_v2(
        scope={
            "run_id": "cached",
            "target": "capture",
            "runner": host_runner,
            "attempt": 1,
            "timestamp": "2026-09-06T00:00:00.000000Z",
        },
        runtime_layout=runtime_layout,
        uv_identity={"path": os.fspath(uv_path), "version": "0.12.9", "sha256": hashlib.sha256(uv_content).hexdigest()},
        uv_lock_sha256=hashlib.sha256(UV_LOCK.read_bytes()).hexdigest(),
        distributions=distributions,
        plugins={
            "pytest_cov.plugin": {
                "file": os.fspath(site_packages / "pytest_cov/plugin.py"),
                "sha256": pytest_cov_entry["sha256"],
                "distribution": "pytest-cov",
                "entry": "pytest_cov/plugin.py",
            },
            "scripts.pytest_security_events": {
                "file": os.fspath(PYTEST_EVENTS_PLUGIN.resolve(strict=True)),
                "sha256": _sha256(PYTEST_EVENTS_PLUGIN),
                "distribution": None,
                "entry": None,
            },
        },
    )
    if runner != host_runner:
        document["scope"]["runner"] = runner
        document["runtime"]["system"] = "Darwin" if runner == "macos" else "Linux"
        document["runtime"]["machine"] = "arm64" if runner == "macos" else "x86_64"
        semantic = dict(document)
        semantic.pop("semantic_runtime_sha256")
        semantic["scope"] = {"runner": runner}
        document["semantic_runtime_sha256"] = hashlib.sha256(
            json.dumps(semantic, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
    return document


def _plugin_identity_document(
    *,
    run_id: str,
    target: str,
    runner: str,
    attempt: int,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    document = deepcopy(_captured_runtime_identity(runner))
    document["scope"] = {
        "run_id": run_id,
        "target": target,
        "runner": runner,
        "attempt": attempt,
        "timestamp": "2026-09-06T00:00:00.000000Z",
    }
    events_path = (repository_root / "scripts/pytest_security_events.py").resolve(strict=True)
    document["plugins"]["scripts.pytest_security_events"] = {
        "file": os.fspath(events_path),
        "sha256": _sha256(events_path),
        "distribution": None,
        "entry": None,
    }
    semantic = dict(document)
    semantic.pop("semantic_runtime_sha256")
    semantic["scope"] = {"runner": runner}
    document["semantic_runtime_sha256"] = hashlib.sha256(
        json.dumps(semantic, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    return document


def test_s18_plugin_identity_record_field_is_only_the_plugin_record_entry_digest():
    distribution = importlib.metadata.distribution("pytest-cov")
    entry = next(
        item
        for item in distribution.files or []
        if item.as_posix() == "pytest_cov/plugin.py"
    )
    record_entry_digest = security_bootstrap._record_entry_digest(
        entry,
        field="pytest-cov plugin",
    )
    identity = _plugin_identity_document(
        run_id="s18-b3c-record-field",
        target="capture",
        runner="macos" if sys.platform == "darwin" else "linux",
        attempt=1,
    )
    expected_keys = {"file", "sha256", "distribution", "entry"}
    cov = identity["plugins"]["pytest_cov.plugin"]
    local = identity["plugins"]["scripts.pytest_security_events"]

    assert set(cov) == expected_keys
    assert set(local) == expected_keys
    assert record_entry_digest.hex() == cov["sha256"]
    assert cov["distribution"] == "pytest-cov"
    assert cov["entry"] == "pytest_cov/plugin.py"
    assert local["distribution"] is None
    assert local["entry"] is None
    assert "RECORD entry" in security_bootstrap._record_entry_digest.__doc__
    assert "not the RECORD file" in security_bootstrap._record_entry_digest.__doc__
    assert "record_file_sha256" not in cov and "record_file_sha256" not in local
    assert "metadata_sha256" not in cov and "metadata_sha256" not in local


def _coverage_summary(
    *,
    covered_lines: int = 100,
    statements: int = 100,
    covered_branches: int = 100,
    branches: int = 100,
) -> dict[str, object]:
    line_percent = 100.0 if statements == 0 else covered_lines * 100.0 / statements
    branch_percent = 100.0 if branches == 0 else covered_branches * 100.0 / branches
    total = statements + branches
    covered = covered_lines + covered_branches
    combined = 100.0 if total == 0 else covered * 100.0 / total
    return {
        "covered_lines": covered_lines,
        "num_statements": statements,
        "percent_covered": combined,
        "percent_covered_display": str(round(combined)),
        "missing_lines": statements - covered_lines,
        "excluded_lines": 0,
        "percent_statements_covered": line_percent,
        "percent_statements_covered_display": str(round(line_percent)),
        "num_branches": branches,
        "num_partial_branches": 0,
        "covered_branches": covered_branches,
        "missing_branches": branches - covered_branches,
        "percent_branches_covered": branch_percent,
        "percent_branches_covered_display": str(round(branch_percent)),
    }


def _critical_symbols(manifest: dict[str, object], target: str) -> set[str]:
    result: set[str] = set()
    for capability in manifest["capabilities"]:
        for target_record in capability["targets"]:
            if target_record["script"] != target:
                continue
            for symbol in target_record["symbols"]:
                if symbol["critical_line"] or symbol["critical_branch"]:
                    result.add(symbol["name"])
    return result


def _coverage_document(
    manifest: dict[str, object],
    target: str,
    source_path: str,
) -> dict[str, object]:
    functions = {}
    for symbol in sorted(_critical_symbols(manifest, target)):
        functions[symbol] = {
            "executed_lines": [1],
            "summary": _coverage_summary(
                covered_lines=1,
                statements=1,
                covered_branches=1,
                branches=1,
            ),
            "missing_lines": [],
            "excluded_lines": [],
            "start_line": 1,
            "executed_branches": [[1, 2]],
            "missing_branches": [],
        }
    summary = _coverage_summary()
    return {
        "meta": {
            "format": 3,
            "version": "7.16.0",
            "timestamp": "2026-09-06T00:00:00",
            "branch_coverage": True,
            "show_contexts": False,
        },
        "files": {
            source_path: {
                "executed_lines": list(range(1, 101)),
                "summary": summary,
                "missing_lines": [],
                "excluded_lines": [],
                "executed_branches": [[value, value + 1] for value in range(1, 101)],
                "missing_branches": [],
                "functions": functions,
                "classes": {},
            }
        },
        "totals": deepcopy(summary),
    }


def _required_nodeids(manifest: dict[str, object], target: str, runner: str) -> list[str]:
    nodeids = []
    for capability in manifest["capabilities"]:
        for target_record in capability["targets"]:
            if target_record["script"] != target:
                continue
            nodeids.extend(
                requirement["nodeid"]
                for requirement in target_record["requirements"]
                if requirement["runner"] == runner
            )
    return sorted(nodeids)


def _junit_document(
    nodeids: list[str],
    *,
    mutation: tuple[str, str] | None = None,
    skip_message: str = "not available",
) -> ET.ElementTree:
    root = ET.Element("testsuites", tests="999", failures="0", skipped="0")
    suite = ET.SubElement(root, "testsuite", tests="999", failures="0", skipped="0")
    for nodeid in nodeids:
        path, name = nodeid.split("::", 1)
        classname = path.removesuffix(".py").replace("/", ".")
        case = ET.SubElement(suite, "testcase", classname=classname, name=name)
        if mutation is not None and nodeid == mutation[0]:
            status = mutation[1]
            if status == "skipped":
                ET.SubElement(case, "skipped", message=skip_message)
            elif status == "xfail":
                ET.SubElement(
                    case,
                    "skipped",
                    type="pytest.xfail",
                    message="expected failure",
                )
            else:
                ET.SubElement(case, status, message="synthetic failure")
    return ET.ElementTree(root)


def _pytest_events_document(
    nodeids: list[str],
    *,
    run_id: str,
    target: str,
    runner: str,
    attempt: int,
    test_file: str,
    mutation: tuple[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    cases = []
    for nodeid in sorted(nodeids):
        case: dict[str, object] = {
            "nodeid": nodeid,
            "xfail_marked": False,
            "phases": {
                "setup": {"outcome": "passed", "wasxfail": False},
                "call": {"outcome": "passed", "wasxfail": False},
                "teardown": {"outcome": "passed", "wasxfail": False},
            },
        }
        if mutation is not None and nodeid == mutation[0]:
            case.update(mutation[1])
        cases.append(case)
    return {
        "schema_version": 3,
        "run_id": run_id,
        "target": target,
        "runner": runner,
        "attempt": attempt,
        "test_file": test_file,
        "limits": {
            name: load_policy()["limits"][name]
            for name in (
                "testcases",
                "pytest_events_nodeid_bytes",
                "pytest_events_bytes",
            )
        },
        "cases": cases,
    }


def _make_bundle(
    root: Path,
    *,
    target: str = "capture",
    runner: str = "macos",
    run_id: str = "s18-contract-001",
    attempt: int = 1,
) -> dict[str, Path]:
    root.mkdir()
    policy = load_policy()
    manifest = load_manifest(policy=policy)
    source_path = policy["scripts"][target]["path"]
    test_file = policy["scripts"][target]["test_file"]
    coverage = root / "coverage.json"
    junit = root / "junit.xml"
    environment = root / "environment.json"
    command = root / "command.json"
    run_manifest = root / "run-manifest.json"
    pytest_events = root / "pytest-events.json"
    plugin_identity = root / "plugin-identity.json"

    _write_json(coverage, _coverage_document(manifest, target, source_path))
    nodeids = _required_nodeids(manifest, target, runner)
    _junit_document(nodeids).write(junit, encoding="utf-8", xml_declaration=True)
    _write_events_json(
        pytest_events,
        _pytest_events_document(
            nodeids,
            run_id=run_id,
            target=target,
            runner=runner,
            attempt=attempt,
            test_file=test_file,
        ),
    )
    identity_document = _plugin_identity_document(
        run_id=run_id,
        target=target,
        runner=runner,
        attempt=attempt,
    )
    _write_json(plugin_identity, identity_document)
    plugin_identity.chmod(0o600)

    platform = {
        "system": "Darwin" if runner == "macos" else "Linux",
        "machine": "arm64" if runner == "macos" else "x86_64",
        "python_implementation": "CPython",
        "python_version": "3.11.9",
    }
    _write_json(
        environment,
        {
            "schema_version": 5,
            "run_id": run_id,
            "target": target,
            "runner": runner,
            "attempt": attempt,
            "platform": platform,
            "tools": {
                "coverage": identity_document["distributions"]["coverage"]["installed"]["version"],
                "pytest": identity_document["distributions"]["pytest"]["installed"]["version"],
                "uv": identity_document["uv"]["version"],
            },
            "runtime_identity": {
                "artifact_sha256": _sha256(plugin_identity),
                "semantic_runtime_sha256": identity_document["semantic_runtime_sha256"],
            },
            "repository": {
                "git_head": "a" * 40,
                "base_ref": "HEAD",
                "dirty": True,
                "source_sha256_before": _sha256(REPOSITORY_ROOT / source_path),
                "source_sha256_after": _sha256(REPOSITORY_ROOT / source_path),
                "test_sha256_before": _sha256(REPOSITORY_ROOT / test_file),
                "test_sha256_after": _sha256(REPOSITORY_ROOT / test_file),
                "policy_sha256_before": _sha256(DEFAULT_POLICY),
                "policy_sha256_after": _sha256(DEFAULT_POLICY),
                "manifest_sha256_before": _sha256(DEFAULT_MANIFEST),
                "manifest_sha256_after": _sha256(DEFAULT_MANIFEST),
                "runner_sha256_before": _sha256(RUNNER),
                "runner_sha256_after": _sha256(RUNNER),
                "verifier_sha256_before": _sha256(VERIFIER),
                "verifier_sha256_after": _sha256(VERIFIER),
                "bootstrap_sha256_before": _sha256(BOOTSTRAP),
                "bootstrap_sha256_after": _sha256(BOOTSTRAP),
                "pytest_config_sha256_before": _sha256(PYTEST_CONFIG),
                "pytest_config_sha256_after": _sha256(PYTEST_CONFIG),
                "pytest_events_plugin_sha256_before": _sha256(PYTEST_EVENTS_PLUGIN),
                "pytest_events_plugin_sha256_after": _sha256(PYTEST_EVENTS_PLUGIN),
                "uv_lock_sha256_before": _sha256(UV_LOCK),
                "uv_lock_sha256_after": _sha256(UV_LOCK),
                "uv_executable_sha256_before": identity_document["uv"]["sha256"],
                "uv_executable_sha256_after": identity_document["uv"]["sha256"],
            },
        },
    )
    module = policy["scripts"][target]["module"]
    _write_json(
        command,
        {
            "schema_version": 4,
            "run_id": run_id,
            "target": target,
            "runner": runner,
            "attempt": attempt,
            "argv": [
                identity_document["uv"]["path"],
                "run",
                "--offline",
                "--frozen",
                "--no-sync",
                "python",
                "-I",
                "-S",
                "-B",
                os.fspath(BOOTSTRAP.resolve(strict=True)),
                "--plugin-identity=" + os.fspath(plugin_identity),
                "--runtime-uv-path=" + identity_document["uv"]["path"],
                "--runtime-uv-version=" + identity_document["uv"]["version"],
                "--runtime-uv-sha256=" + identity_document["uv"]["sha256"],
                "--runtime-timestamp=2026-09-06T00:00:00.000000Z",
                "--",
                test_file,
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
                "--security-events=" + str(pytest_events),
                "--security-run-id=" + run_id,
                "--security-target=" + target,
                "--security-runner=" + runner,
                "--security-attempt=" + str(attempt),
                "--security-test-file=" + test_file,
                "--security-max-cases=" + str(policy["limits"]["testcases"]),
                "--security-max-nodeid-bytes="
                + str(policy["limits"]["pytest_events_nodeid_bytes"]),
                "--security-max-events-bytes="
                + str(policy["limits"]["pytest_events_bytes"]),
                "--junitxml=" + str(junit),
                "--cov=" + module,
                "--cov-branch",
                "--cov-report=json:" + str(coverage),
                "--cov-report=term-missing",
                "--cov-fail-under=80",
            ],
            "sanitized_environment": {
                "COVERAGE_FILE": str(root / (".coverage-" + target)),
                "PYTHONHOME": None,
                "PYTHONPATH": None,
                "PYTHONUSERBASE": None,
                "PYTEST_ADDOPTS": None,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTEST_PLUGINS": None,
                "UV_PROJECT_ENVIRONMENT": None,
                "UV_PYTHON": None,
            },
            "exit_code": 0,
            "started_at": "2026-09-06T00:00:00.000000Z",
            "finished_at": "2026-09-06T00:00:01.000000Z",
        },
    )
    _write_json(
        run_manifest,
        {
            "schema_version": 5,
            "run_id": run_id,
            "target": target,
            "runner": runner,
            "attempt": attempt,
            "artifact_hashes": {
                "source_sha256": _sha256(REPOSITORY_ROOT / source_path),
                "test_sha256": _sha256(REPOSITORY_ROOT / test_file),
                "policy_sha256": _sha256(DEFAULT_POLICY),
                "manifest_sha256": _sha256(DEFAULT_MANIFEST),
                "runner_sha256": _sha256(RUNNER),
                "verifier_sha256": _sha256(VERIFIER),
                "bootstrap_sha256": _sha256(BOOTSTRAP),
                "pytest_config_sha256": _sha256(PYTEST_CONFIG),
                "pytest_events_plugin_sha256": _sha256(PYTEST_EVENTS_PLUGIN),
                "uv_lock_sha256": _sha256(UV_LOCK),
                "coverage_sha256": _sha256(coverage),
                "junit_sha256": _sha256(junit),
                "pytest_events_sha256": _sha256(pytest_events),
                "plugin_identity_sha256": _sha256(plugin_identity),
                "environment_sha256": _sha256(environment),
                "command_sha256": _sha256(command),
            },
            "semantic_runtime_sha256": identity_document["semantic_runtime_sha256"],
        },
    )
    return {
        "coverage": coverage,
        "junit": junit,
        "environment": environment,
        "command": command,
        "run_manifest": run_manifest,
        "pytest_events": pytest_events,
        "plugin_identity": plugin_identity,
    }


def _verify(bundle: dict[str, Path], *, target: str = "capture"):
    return verify_security_coverage(
        target=target,
        coverage_path=bundle["coverage"],
        junit_path=bundle["junit"],
        pytest_events_path=bundle["pytest_events"],
        plugin_identity_path=bundle["plugin_identity"],
        environment_path=bundle["environment"],
        command_path=bundle["command"],
        run_manifest_path=bundle["run_manifest"],
    )


def _bind_toolchain(bundle: dict[str, Path]) -> None:
    environment = json.loads(bundle["environment"].read_text(encoding="utf-8"))
    for key, path in TOOLCHAIN_PATHS.items():
        stem = key.removesuffix("_sha256")
        digest = _sha256(path)
        environment["repository"][stem + "_sha256_before"] = digest
        environment["repository"][stem + "_sha256_after"] = digest
    _write_json(bundle["environment"], environment)

    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    for key, path in TOOLCHAIN_PATHS.items():
        run_manifest["artifact_hashes"][key] = _sha256(path)
    run_manifest["artifact_hashes"]["environment_sha256"] = _sha256(bundle["environment"])
    _write_json(bundle["run_manifest"], run_manifest)


def _rebind_plugin_identity(bundle: dict[str, Path]) -> None:
    identity = json.loads(bundle["plugin_identity"].read_text(encoding="utf-8"))
    environment = json.loads(bundle["environment"].read_text(encoding="utf-8"))
    environment["runtime_identity"]["artifact_sha256"] = _sha256(bundle["plugin_identity"])
    semantic = identity.get("semantic_runtime_sha256")
    environment["runtime_identity"]["semantic_runtime_sha256"] = (
        semantic if isinstance(semantic, str) and re.fullmatch(r"[0-9a-f]{64}", semantic) else None
    )
    _write_json(bundle["environment"], environment)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["plugin_identity_sha256"] = _sha256(
        bundle["plugin_identity"]
    )
    run_manifest["artifact_hashes"]["environment_sha256"] = _sha256(bundle["environment"])
    run_manifest["semantic_runtime_sha256"] = environment["runtime_identity"][
        "semantic_runtime_sha256"
    ]
    _write_json(bundle["run_manifest"], run_manifest)


def _rebind_runtime_identity_semantic(identity: dict[str, object]) -> None:
    semantic = deepcopy(identity)
    semantic.pop("semantic_runtime_sha256", None)
    semantic["scope"] = {"runner": identity["scope"]["runner"]}
    identity["semantic_runtime_sha256"] = hashlib.sha256(
        json.dumps(
            semantic,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def test_s18_policy_is_exact_and_locks_two_script_targets():
    policy = load_policy()
    assert set(policy) == {"schema_version", "thresholds", "limits", "scripts", "runners"}
    assert policy["thresholds"] == {
        "coverage_combined_percent": 80,
        "statement_line_percent": 80,
        "branch_percent": 80,
        "critical_line_percent": 100,
        "critical_branch_percent": 100,
        "zero_required_skip": True,
    }
    assert set(policy["scripts"]) == {"capture", "retention"}
    assert policy["scripts"]["capture"]["path"] == "scripts/capture_test_gate.py"
    assert policy["scripts"]["retention"]["path"] == "scripts/manage_evidence_retention.py"
    assert set(policy["runners"]) == {"macos", "linux"}


@pytest.mark.parametrize("mutation", ["unknown", "duplicate"])
def test_s18_policy_rejects_unknown_or_duplicate_toml_keys(tmp_path, mutation):
    content = DEFAULT_POLICY.read_text(encoding="utf-8")
    if mutation == "unknown":
        content = content.replace("schema_version = 2", "schema_version = 2\nunknown = true", 1)
    else:
        content = content.replace("schema_version = 2", "schema_version = 2\nschema_version = 2", 1)
    policy = tmp_path / "policy.toml"
    policy.write_text(content, encoding="utf-8")
    with pytest.raises(GateFailure):
        load_policy(policy)


@pytest.mark.parametrize(
    ("field", "frozen", "mutated"),
    [
        ("testcases", 4096, 1),
        ("pytest_events_nodeid_bytes", 4096, 1),
        ("pytest_events_bytes", 8388608, 1),
    ],
    ids=["b3fl-policy-cases", "b3fl-policy-nodeid", "b3fl-policy-events"],
)
def test_s18_policy_rejects_nonfrozen_pytest_events_limits(
    tmp_path, field, frozen, mutated
):
    content = DEFAULT_POLICY.read_text(encoding="utf-8")
    content = content.replace(f"{field} = {frozen}", f"{field} = {mutated}", 1)
    policy = tmp_path / "policy.toml"
    policy.write_text(content, encoding="utf-8")

    with pytest.raises(GateFailure, match=rf"policy\.limits\.{field} must be {frozen}"):
        load_policy(policy)


@pytest.mark.parametrize(
    ("field", "frozen"),
    [
        ("testcases", 4096),
        ("pytest_events_nodeid_bytes", 4096),
        ("pytest_events_bytes", 8388608),
    ],
    ids=["b3fl-runner-cases", "b3fl-runner-nodeid", "b3fl-runner-events"],
)
def test_s18_runner_rejects_nonfrozen_pytest_events_policy(tmp_path, field, frozen):
    repository = tmp_path / "repository"
    for relative in (
        "packaging/security-coverage-policy.toml",
        "packaging/security-coverage-manifest.json",
        "scripts/run_security_coverage.sh",
        "scripts/verify_security_coverage.py",
        "scripts/security_pytest_bootstrap.py",
        "scripts/pytest_security_events.py",
        "pyproject.toml",
        "uv.lock",
    ):
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative, destination)
    policy_path = repository / "packaging/security-coverage-policy.toml"
    content = policy_path.read_text(encoding="utf-8").replace(
        f"{field} = {frozen}", f"{field} = 1", 1
    )
    policy_path.write_text(content, encoding="utf-8")
    artifact_root = tmp_path / "attempt-001"

    result = subprocess.run(
        [
            os.fspath(repository / "scripts/run_security_coverage.sh"),
            os.fspath(artifact_root),
            "s18-b3f-policy-mutation",
            "1",
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "SECURITY_COVERAGE_RUNNER_CONFIGURATION_INVALID\n"
    assert artifact_root.is_dir()
    assert not (artifact_root / "capture").exists()
    assert not (artifact_root / "retention").exists()


def test_s18_manifest_has_all_capabilities_semantics_and_real_symbols():
    policy = load_policy()
    manifest = load_manifest(policy=policy)
    capabilities = manifest["capabilities"]
    assert [item["id"] for item in capabilities] == [
        f"S18-CAP-{index:02d}" for index in range(1, 18)
    ]
    assert len({item["category"] for item in capabilities}) == 17
    all_requirements = []
    for capability in capabilities:
        assert capability["targets"]
        for target in capability["targets"]:
            semantics = {item["semantic"] for item in target["requirements"]}
            assert semantics == {"success", "fail_closed"}
            required_runners = {item["runner"] for item in target["requirements"]}
            for runner in required_runners:
                runner_semantics = {
                    item["semantic"]
                    for item in target["requirements"]
                    if item["runner"] == runner
                }
                assert runner_semantics == {"success", "fail_closed"}
            all_requirements.extend(
                (item["runner"], item["nodeid"]) for item in target["requirements"]
            )
    assert len(all_requirements) == len(set(all_requirements))
    mapped = {"capture": set(), "retention": set()}
    for capability in capabilities:
        for target in capability["targets"]:
            mapped[target["script"]].update(item["name"] for item in target["symbols"])
    assert mapped["capture"] == {
        "_DirFdReceiptIO._open_parent",
        "_DirFdReceiptIO.read",
        "_DirFdReceiptIO.file_closure",
        "_walk_receipt_closure",
        "_read_stable_regular",
        "_verify_record",
        "_source_material",
        "_source_material_at",
        "_verify_source_summary",
        "_preflight",
        "_seal_run",
        "_run_gate_process",
        "_normalize_returncode",
        "_portable_binding_reasons",
        "_validate_package_sidecar",
        "_package_binding_reasons",
        "_validate_canonical_sidecar",
        "_canonical_binding_reasons",
        "_finalize_run",
        "_verify_receipt_from_io",
        "verify_receipt_at",
        "main",
    }
    assert mapped["retention"] == {
        "_stable_bytes",
        "load_secret_rules",
        "load_retention_assessment",
        "_tree_snapshot",
        "_walk_retention_tree",
        "_scan_file",
        "_scan_tree",
        "_window_hits",
        "_rename_noreplace",
        "_publish_event",
        "_post_rename_identity",
        "_open_lock",
        "inspect_run",
        "_ledger_state",
        "verify_inspection",
        "main",
        "_output",
    }
    assert _critical_symbols(manifest, "capture") == {
        "_DirFdReceiptIO._open_parent",
        "_DirFdReceiptIO.read",
        "_DirFdReceiptIO.file_closure",
        "_walk_receipt_closure",
        "_read_stable_regular",
        "_verify_record",
        "_source_material_at",
        "_seal_run",
        "_normalize_returncode",
        "verify_receipt_at",
    }
    assert _critical_symbols(manifest, "retention") == {
        "_stable_bytes",
        "load_secret_rules",
        "load_retention_assessment",
        "_tree_snapshot",
        "_walk_retention_tree",
        "_scan_file",
        "_scan_tree",
        "_window_hits",
        "_rename_noreplace",
        "_publish_event",
        "_post_rename_identity",
        "_open_lock",
        "_ledger_state",
    }
    assert manifest["criticality_policy"]["thresholds_unchanged"] is True


def test_s18_manifest_rejects_duplicate_json_keys(tmp_path):
    content = DEFAULT_MANIFEST.read_text(encoding="utf-8").replace(
        '"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(content, encoding="utf-8")
    with pytest.raises(GateFailure):
        load_manifest(manifest, policy=load_policy())


def test_s18_manifest_allows_same_nodeid_on_distinct_runners(tmp_path):
    policy = load_policy()
    document = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    target = document["capabilities"][11]["targets"][0]
    original = deepcopy(target["requirements"][0])
    original["runner"] = "linux"
    target["requirements"].append(original)
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, document)
    loaded = load_manifest(manifest, policy=policy)
    requirements = loaded["capabilities"][11]["targets"][0]["requirements"]
    matches = [item for item in requirements if item["nodeid"] == original["nodeid"]]
    assert {item["runner"] for item in matches} == {"macos", "linux"}


def test_s18_manifest_rejects_duplicate_nodeid_on_same_runner(tmp_path):
    policy = load_policy()
    document = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    target = document["capabilities"][11]["targets"][0]
    target["requirements"].append(deepcopy(target["requirements"][0]))
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, document)
    with pytest.raises(GateFailure, match="runner/nodeid pairs must be unique"):
        load_manifest(manifest, policy=policy)


def test_s18_manifest_requires_success_and_fail_closed_per_required_runner(tmp_path):
    policy = load_policy()
    document = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    target = document["capabilities"][2]["targets"][0]
    target["requirements"] = [
        requirement
        for requirement in target["requirements"]
        if requirement["runner"] != "linux" or requirement["semantic"] == "success"
    ]
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, document)
    with pytest.raises(GateFailure, match="MANIFEST_RUNNER_SEMANTICS_INCOMPLETE"):
        load_manifest(manifest, policy=policy)


@pytest.mark.parametrize("target", ["capture", "retention"])
def test_s18_valid_single_source_bundle_passes(tmp_path, target):
    bundle = _make_bundle(tmp_path / target, target=target)
    report, failures = _verify(bundle, target=target)
    assert failures == []
    assert report["passed"] is True
    assert report["schema_version"] == 5
    assert report["coverage"]["combined_percent"] == 100.0
    assert report["coverage"]["statement_line_percent"] == 100.0
    assert report["coverage"]["branch_percent"] == 100.0
    assert report["junit"]["required_passed"] == report["junit"]["required_total"]
    assert report["runtime_identity"]["schema_version"] == 2
    assert report["runtime_identity"]["artifact_sha256"] == _sha256(
        bundle["plugin_identity"]
    )
    assert "file" not in json.dumps(report["runtime_identity"], sort_keys=True)


@pytest.mark.parametrize(
    "mutation",
    [
        "legacy-schema",
        "top-extra",
        "isolation-false",
        "plugin-missing",
        "plugin-extra",
        "plugin-record-extra",
    ],
)
def test_s18_gate_rejects_invalid_plugin_identity_schema(tmp_path, mutation):
    bundle = _make_bundle(tmp_path / mutation)
    identity = json.loads(bundle["plugin_identity"].read_text(encoding="utf-8"))
    if mutation == "legacy-schema":
        identity["schema_version"] = 0
    elif mutation == "top-extra":
        identity["unknown"] = True
    elif mutation == "isolation-false":
        identity["runtime"]["isolated"] = False
    elif mutation == "plugin-missing":
        del identity["plugins"]["scripts.pytest_security_events"]
    elif mutation == "plugin-extra":
        identity["plugins"]["hostile.plugin"] = deepcopy(
            identity["plugins"]["pytest_cov.plugin"]
        )
    else:
        identity["plugins"]["pytest_cov.plugin"]["unknown"] = True
    if mutation.startswith("plugin-"):
        _rebind_runtime_identity_semantic(identity)
    _write_json(bundle["plugin_identity"], identity)
    _rebind_plugin_identity(bundle)

    _, failures = _verify(bundle)

    expected = (
        ["PLUGIN_IDENTITY_INVALID"]
        if mutation.startswith("plugin-")
        else ["RUNTIME_IDENTITY_INVALID"]
    )
    assert failures == expected


def test_s18_gate_rejects_duplicate_plugin_identity_keys(tmp_path):
    bundle = _make_bundle(tmp_path / "duplicate")
    content = bundle["plugin_identity"].read_text(encoding="utf-8").replace(
        '"schema_version": 2', '"schema_version": 2, "schema_version": 2', 1
    )
    bundle["plugin_identity"].write_text(content, encoding="utf-8")
    _rebind_plugin_identity(bundle)

    _, failures = _verify(bundle)

    assert failures == ["RUNTIME_IDENTITY_INVALID"]


@pytest.mark.parametrize(
    "field",
    ["entries", "record_file_sha256", "metadata_sha256", "lock_package_sha256"],
)
def test_s18_gate_rejects_b3f_r_only_plugin_identity_fields(tmp_path, field):
    bundle = _make_bundle(tmp_path / field)
    identity = json.loads(bundle["plugin_identity"].read_text(encoding="utf-8"))
    identity["plugins"]["pytest_cov.plugin"][field] = {} if field == "entries" else "b" * 64
    _rebind_runtime_identity_semantic(identity)
    _write_json(bundle["plugin_identity"], identity)
    _rebind_plugin_identity(bundle)

    _, failures = _verify(bundle)

    assert failures == ["PLUGIN_IDENTITY_INVALID"]


@pytest.mark.parametrize("mode", [0o640, 0o644])
def test_s18_gate_rejects_plugin_identity_not_published_mode_0600(tmp_path, mode):
    bundle = _make_bundle(tmp_path / f"identity-mode-{mode:o}")
    bundle["plugin_identity"].chmod(mode)
    _rebind_plugin_identity(bundle)

    _, failures = _verify(bundle)

    assert failures == ["RUNTIME_IDENTITY_INVALID"]


@pytest.mark.parametrize("field", ["run_id", "target", "runner", "attempt"])
def test_s18_gate_rejects_cross_scope_plugin_identity(tmp_path, field):
    bundle = _make_bundle(tmp_path / field)
    identity = json.loads(bundle["plugin_identity"].read_text(encoding="utf-8"))
    identity["scope"][field] = {
        "run_id": "other-run",
        "target": "retention",
        "runner": "linux",
        "attempt": 2,
    }[field]
    _rebind_runtime_identity_semantic(identity)
    _write_json(bundle["plugin_identity"], identity)
    _rebind_plugin_identity(bundle)

    _, failures = _verify(bundle)

    assert failures == ["RUNTIME_IDENTITY_INVALID"]


@pytest.mark.parametrize(
    "mutation",
    [
        "local-path",
        "local-hash",
        "cov-path",
        "cov-hash",
        "cov-name",
        "cov-entry",
    ],
)
def test_s18_gate_rejects_plugin_identity_origin_or_record_mismatch(
    tmp_path, mutation
):
    bundle = _make_bundle(tmp_path / mutation)
    identity = json.loads(bundle["plugin_identity"].read_text(encoding="utf-8"))
    local = identity["plugins"]["scripts.pytest_security_events"]
    cov = identity["plugins"]["pytest_cov.plugin"]
    if mutation == "local-path":
        local["file"] = cov["file"]
    elif mutation == "local-hash":
        local["sha256"] = "b" * 64
    elif mutation == "cov-path":
        cov["file"] = local["file"]
    elif mutation == "cov-hash":
        cov["sha256"] = "b" * 64
    elif mutation == "cov-name":
        cov["distribution"] = "hostile-cov"
    else:
        cov["entry"] = "pytest_cov/__init__.py"
    _rebind_runtime_identity_semantic(identity)
    _write_json(bundle["plugin_identity"], identity)
    _rebind_plugin_identity(bundle)

    _, failures = _verify(bundle)

    assert failures == ["PLUGIN_IDENTITY_INVALID"]


def test_s18_gate_rejects_whole_record_file_hash_in_record_entry_field(tmp_path):
    bundle = _make_bundle(tmp_path / "whole-record-file-hash")
    distribution = importlib.metadata.distribution("pytest-cov")
    record_files = [
        item
        for item in distribution.files or []
        if item.as_posix().endswith(".dist-info/RECORD")
    ]
    assert len(record_files) == 1
    record_path = Path(distribution.locate_file(record_files[0])).resolve(strict=True)
    whole_record_sha256 = _sha256(record_path)

    identity = json.loads(bundle["plugin_identity"].read_text(encoding="utf-8"))
    cov = identity["plugins"]["pytest_cov.plugin"]
    assert whole_record_sha256 != cov["sha256"]
    cov["sha256"] = whole_record_sha256
    _rebind_runtime_identity_semantic(identity)
    _write_json(bundle["plugin_identity"], identity)
    _rebind_plugin_identity(bundle)

    _, failures = _verify(bundle)

    assert failures == ["PLUGIN_IDENTITY_INVALID"]


def test_s18_gate_binds_plugin_identity_artifact_hash(tmp_path):
    bundle = _make_bundle(tmp_path / "identity-hash")
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["plugin_identity_sha256"] = "b" * 64
    _write_json(bundle["run_manifest"], run_manifest)

    _, failures = _verify(bundle)

    assert failures == ["EVIDENCE_TOOLCHAIN_BINDING_INVALID"]


@pytest.mark.parametrize("artifact", ["environment", "run_manifest", "command"])
def test_s18_gate_rejects_legacy_toolchain_evidence_schema(tmp_path, artifact):
    bundle = _make_bundle(tmp_path / artifact)
    document = json.loads(bundle[artifact].read_text(encoding="utf-8"))
    document["schema_version"] = 1 if artifact == "command" else 2
    _write_json(bundle[artifact], document)
    if artifact in {"environment", "command"}:
        run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
        run_manifest["artifact_hashes"][artifact + "_sha256"] = _sha256(bundle[artifact])
        _write_json(bundle["run_manifest"], run_manifest)

    current_schema = 4 if artifact == "command" else 5
    with pytest.raises(
        GateFailure, match=rf"{artifact}\.schema_version must be {current_schema}"
    ):
        _verify(bundle)


def test_s18_gate_binds_runner_verifier_and_actual_pytest_config(tmp_path):
    bundle = _make_bundle(tmp_path / "toolchain")
    _bind_toolchain(bundle)

    report, failures = _verify(bundle)

    assert failures == []
    assert {
        key: report["artifact_hashes"][key]
        for key in TOOLCHAIN_PATHS
    } == {key: _sha256(path) for key, path in TOOLCHAIN_PATHS.items()}


@pytest.mark.parametrize("artifact", sorted(TOOLCHAIN_PATHS))
def test_s18_gate_rejects_toolchain_artifact_hash_drift_with_stable_code(
    tmp_path, artifact
):
    bundle = _make_bundle(tmp_path / artifact)
    _bind_toolchain(bundle)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"][artifact] = "b" * 64
    _write_json(bundle["run_manifest"], run_manifest)

    _, failures = _verify(bundle)

    assert "EVIDENCE_TOOLCHAIN_BINDING_INVALID" in failures


@pytest.mark.parametrize(
    "artifact", ["runner", "verifier", "pytest_config", "pytest_events_plugin"]
)
def test_s18_gate_rejects_toolchain_before_after_drift_with_stable_code(
    tmp_path, artifact
):
    bundle = _make_bundle(tmp_path / artifact)
    _bind_toolchain(bundle)
    environment = json.loads(bundle["environment"].read_text(encoding="utf-8"))
    environment["repository"][artifact + "_sha256_after"] = "b" * 64
    _write_json(bundle["environment"], environment)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["environment_sha256"] = _sha256(bundle["environment"])
    _write_json(bundle["run_manifest"], run_manifest)

    _, failures = _verify(bundle)

    assert "EVIDENCE_TOOLCHAIN_BINDING_INVALID" in failures


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("second-source", "SOURCE_SET_INVALID"),
        ("branch-disabled", "BRANCH_COVERAGE_REQUIRED"),
    ],
)
def test_s18_gate_requires_branch_coverage_and_exact_single_source(tmp_path, mutation, code):
    bundle = _make_bundle(tmp_path / mutation)
    coverage = json.loads(bundle["coverage"].read_text(encoding="utf-8"))
    if mutation == "second-source":
        coverage["files"]["t2l/borrowed.py"] = deepcopy(next(iter(coverage["files"].values())))
    else:
        coverage["meta"]["branch_coverage"] = False
    _write_json(bundle["coverage"], coverage)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["coverage_sha256"] = _sha256(bundle["coverage"])
    _write_json(bundle["run_manifest"], run_manifest)
    _, failures = _verify(bundle)
    assert code in failures


@pytest.mark.parametrize(
    ("covered_lines", "statements", "covered_branches", "branches", "code"),
    [
        (80, 100, 79, 100, "COMBINED_COVERAGE_BELOW_THRESHOLD"),
        (79, 100, 80, 80, "LINE_COVERAGE_BELOW_THRESHOLD"),
        (80, 80, 79, 100, "BRANCH_COVERAGE_BELOW_THRESHOLD"),
    ],
)
def test_s18_gate_recomputes_each_threshold_instead_of_trusting_displayed_totals(
    tmp_path, covered_lines, statements, covered_branches, branches, code
):
    bundle = _make_bundle(tmp_path / code)
    coverage = json.loads(bundle["coverage"].read_text(encoding="utf-8"))
    summary = _coverage_summary(
        covered_lines=covered_lines,
        statements=statements,
        covered_branches=covered_branches,
        branches=branches,
    )
    summary["percent_covered"] = 100.0
    summary["percent_covered_display"] = "100"
    summary["percent_statements_covered"] = 100.0
    summary["percent_branches_covered"] = 100.0
    coverage["totals"] = summary
    only_file = next(iter(coverage["files"].values()))
    only_file["summary"] = deepcopy(summary)
    _write_json(bundle["coverage"], coverage)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["coverage_sha256"] = _sha256(bundle["coverage"])
    _write_json(bundle["run_manifest"], run_manifest)
    report, failures = _verify(bundle)
    assert code in failures
    assert report["coverage"]["statement_line_percent"] == pytest.approx(
        covered_lines * 100 / statements
    )


@pytest.mark.parametrize("mutation", ["missing", "line", "branch"])
def test_s18_gate_requires_every_critical_target_at_one_hundred_percent(tmp_path, mutation):
    bundle = _make_bundle(tmp_path / mutation)
    coverage = json.loads(bundle["coverage"].read_text(encoding="utf-8"))
    functions = next(iter(coverage["files"].values()))["functions"]
    symbol = next(iter(functions))
    if mutation == "missing":
        del functions[symbol]
    elif mutation == "line":
        functions[symbol]["summary"]["covered_lines"] = 0
    else:
        functions[symbol]["summary"]["covered_branches"] = 0
    _write_json(bundle["coverage"], coverage)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["coverage_sha256"] = _sha256(bundle["coverage"])
    _write_json(bundle["run_manifest"], run_manifest)
    _, failures = _verify(bundle)
    assert "CRITICAL_TARGET_UNCOVERED" in failures


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("missing", "REQUIRED_TEST_MISSING"),
        ("skipped", "REQUIRED_TEST_SKIPPED"),
        ("xfail", "REQUIRED_TEST_XFAILED"),
        ("failure", "REQUIRED_TEST_FAILED"),
        ("error", "REQUIRED_TEST_ERROR"),
    ],
)
def test_s18_gate_rejects_nonpassing_required_nodeid_even_with_forged_suite_totals(
    tmp_path, status, code
):
    bundle = _make_bundle(tmp_path / status)
    manifest = load_manifest(policy=load_policy())
    nodeids = _required_nodeids(manifest, "capture", "macos")
    selected = nodeids[0]
    if status == "missing":
        nodeids.remove(selected)
        mutation = None
    else:
        mutation = (selected, status)
    _junit_document(nodeids, mutation=mutation).write(
        bundle["junit"], encoding="utf-8", xml_declaration=True
    )
    if status != "missing":
        events = json.loads(bundle["pytest_events"].read_text(encoding="utf-8"))
        event_case = next(case for case in events["cases"] if case["nodeid"] == selected)
        if status in {"skipped", "xfail"}:
            event_case["xfail_marked"] = status == "xfail"
            event_case["phases"]["call"] = {
                "outcome": "skipped",
                "wasxfail": status == "xfail",
            }
        elif status == "failure":
            event_case["phases"]["call"]["outcome"] = "failed"
        else:
            event_case["phases"]["teardown"]["outcome"] = "failed"
        _write_events_json(bundle["pytest_events"], events)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["junit_sha256"] = _sha256(bundle["junit"])
    run_manifest["artifact_hashes"]["pytest_events_sha256"] = _sha256(
        bundle["pytest_events"]
    )
    _write_json(bundle["run_manifest"], run_manifest)
    _, failures = _verify(bundle)
    assert code in failures


@pytest.mark.parametrize(
    ("required", "expected"),
    [(True, "REQUIRED_TEST_XFAILED"), (False, "UNEXPECTED_TEST_SKIP")],
)
def test_s18_gate_rejects_xfail_event_hidden_by_junit_pass(
    tmp_path, required, expected
):
    bundle = _make_bundle(tmp_path / ("required" if required else "nonrequired"))
    events = json.loads(bundle["pytest_events"].read_text(encoding="utf-8"))
    if required:
        nodeid = events["cases"][0]["nodeid"]
        events["cases"][0].update(
            {
                "xfail_marked": True,
                "phases": {
                    "setup": {"outcome": "passed", "wasxfail": False},
                    "call": {"outcome": "passed", "wasxfail": True},
                    "teardown": {"outcome": "passed", "wasxfail": False},
                },
            }
        )
    else:
        nodeid = "tests/contract/test_evidence_capture.py::test_unexpected_xpass"
        events["cases"].append(
            {
                "nodeid": nodeid,
                "xfail_marked": True,
                "phases": {
                    "setup": {"outcome": "passed", "wasxfail": False},
                    "call": {"outcome": "passed", "wasxfail": True},
                    "teardown": {"outcome": "passed", "wasxfail": False},
                },
            }
        )
        events["cases"].sort(key=lambda case: case["nodeid"])
        junit = ET.parse(bundle["junit"])
        suite = junit.find(".//testsuite")
        assert suite is not None
        ET.SubElement(
            suite,
            "testcase",
            classname="tests.contract.test_evidence_capture",
            name="test_unexpected_xpass",
        )
        junit.write(bundle["junit"], encoding="utf-8", xml_declaration=True)
    _write_events_json(bundle["pytest_events"], events)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["pytest_events_sha256"] = _sha256(
        bundle["pytest_events"]
    )
    run_manifest["artifact_hashes"]["junit_sha256"] = _sha256(bundle["junit"])
    _write_json(bundle["run_manifest"], run_manifest)

    report, failures = _verify(bundle)

    assert expected in failures
    required_results = {item["nodeid"]: item for item in report["junit"]["required_tests"]}
    if required:
        assert required_results[nodeid]["status"] == "xfail"


@pytest.mark.parametrize(
    "call_report",
    [
        {"outcome": "failed", "wasxfail": False},
        {"outcome": "skipped", "wasxfail": False},
        None,
    ],
    ids=["failed", "skipped", "missing"],
)
def test_s18_gate_rejects_junit_pass_with_nonpassing_or_missing_call_report(
    tmp_path, call_report
):
    label = "missing" if call_report is None else call_report["outcome"]
    bundle = _make_bundle(tmp_path / label)
    events = json.loads(bundle["pytest_events"].read_text(encoding="utf-8"))
    events["cases"][0]["phases"]["call"] = call_report
    _write_events_json(bundle["pytest_events"], events)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["pytest_events_sha256"] = _sha256(
        bundle["pytest_events"]
    )
    _write_json(bundle["run_manifest"], run_manifest)

    report, failures = _verify(bundle)

    assert "PYTEST_EVENTS_INVALID" in failures
    assert report["passed"] is False


@pytest.mark.parametrize(
    ("label", "phases", "junit_status", "expected"),
    [
        (
            "normal-failure",
            {
                "setup": {"outcome": "passed", "wasxfail": False},
                "call": {"outcome": "failed", "wasxfail": False},
                "teardown": {"outcome": "passed", "wasxfail": False},
            },
            "failure",
            "REQUIRED_TEST_FAILED",
        ),
        (
            "setup-failure",
            {
                "setup": {"outcome": "failed", "wasxfail": False},
                "call": None,
                "teardown": {"outcome": "passed", "wasxfail": False},
            },
            "error",
            "REQUIRED_TEST_ERROR",
        ),
        (
            "setup-skip",
            {
                "setup": {"outcome": "skipped", "wasxfail": False},
                "call": None,
                "teardown": {"outcome": "passed", "wasxfail": False},
            },
            "skipped",
            "REQUIRED_TEST_SKIPPED",
        ),
        (
            "call-skip",
            {
                "setup": {"outcome": "passed", "wasxfail": False},
                "call": {"outcome": "skipped", "wasxfail": False},
                "teardown": {"outcome": "passed", "wasxfail": False},
            },
            "skipped",
            "REQUIRED_TEST_SKIPPED",
        ),
        (
            "teardown-failure",
            {
                "setup": {"outcome": "passed", "wasxfail": False},
                "call": {"outcome": "passed", "wasxfail": False},
                "teardown": {"outcome": "failed", "wasxfail": False},
            },
            "error",
            "REQUIRED_TEST_ERROR",
        ),
    ],
)
def test_s18_gate_accepts_characterized_nonpassing_phase_combinations(
    tmp_path, label, phases, junit_status, expected
):
    bundle = _make_bundle(tmp_path / label)
    manifest = load_manifest(policy=load_policy())
    nodeids = _required_nodeids(manifest, "capture", "macos")
    selected = nodeids[0]
    _junit_document(nodeids, mutation=(selected, junit_status)).write(
        bundle["junit"], encoding="utf-8", xml_declaration=True
    )
    events = json.loads(bundle["pytest_events"].read_text(encoding="utf-8"))
    events["cases"][0]["phases"] = phases
    _write_events_json(bundle["pytest_events"], events)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["junit_sha256"] = _sha256(bundle["junit"])
    run_manifest["artifact_hashes"]["pytest_events_sha256"] = _sha256(
        bundle["pytest_events"]
    )
    _write_json(bundle["run_manifest"], run_manifest)

    _, failures = _verify(bundle)

    assert "PYTEST_EVENTS_INVALID" not in failures
    assert expected in failures


@pytest.mark.parametrize(
    ("junit_status", "phases"),
    [
        (
            "failure",
            {
                "setup": {"outcome": "passed", "wasxfail": False},
                "call": {"outcome": "passed", "wasxfail": False},
                "teardown": {"outcome": "passed", "wasxfail": False},
            },
        ),
        (
            "xfail",
            {
                "setup": {"outcome": "passed", "wasxfail": False},
                "call": {"outcome": "skipped", "wasxfail": False},
                "teardown": {"outcome": "passed", "wasxfail": False},
            },
        ),
    ],
)
def test_s18_gate_rejects_junit_and_phase_status_disagreement(
    tmp_path, junit_status, phases
):
    bundle = _make_bundle(tmp_path / junit_status)
    manifest = load_manifest(policy=load_policy())
    nodeids = _required_nodeids(manifest, "capture", "macos")
    selected = nodeids[0]
    _junit_document(nodeids, mutation=(selected, junit_status)).write(
        bundle["junit"], encoding="utf-8", xml_declaration=True
    )
    events = json.loads(bundle["pytest_events"].read_text(encoding="utf-8"))
    events["cases"][0]["phases"] = phases
    _write_events_json(bundle["pytest_events"], events)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["junit_sha256"] = _sha256(bundle["junit"])
    run_manifest["artifact_hashes"]["pytest_events_sha256"] = _sha256(
        bundle["pytest_events"]
    )
    _write_json(bundle["run_manifest"], run_manifest)

    _, failures = _verify(bundle)

    assert "PYTEST_EVENTS_INVALID" in failures


def test_s18_gate_rejects_forged_junit_classname(tmp_path):
    bundle = _make_bundle(tmp_path / "forged-classname")
    junit = ET.parse(bundle["junit"])
    testcase = junit.find(".//testcase")
    assert testcase is not None
    assert testcase.get("classname") == "tests.contract.test_evidence_capture"
    testcase.set("classname", "tests/contract/test_evidence_capture")
    junit.write(bundle["junit"], encoding="utf-8", xml_declaration=True)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["junit_sha256"] = _sha256(bundle["junit"])
    _write_json(bundle["run_manifest"], run_manifest)

    report, failures = _verify(bundle)

    assert failures == ["JUNIT_NODEID_INVALID"]
    assert report["passed"] is False


def test_s18_gate_rejects_noncanonical_junit_name(tmp_path):
    invalid_names = {
        "double-node-separator": "test_extra::alias",
        "path-in-base": "test_/extra",
        "unclosed-parameter": "test_extra[unterminated",
        "trailing-after-parameter": "test_extra[param]tail",
        "control-newline": "test_extra\n[param]",
        "stray-close-bracket": "test_extra]",
    }
    for label, invalid_name in invalid_names.items():
        bundle = _make_bundle(tmp_path / label)
        junit = ET.parse(bundle["junit"])
        suite = junit.find(".//testsuite")
        assert suite is not None
        ET.SubElement(
            suite,
            "testcase",
            classname="tests.contract.test_evidence_capture",
            name=invalid_name,
        )
        junit.write(bundle["junit"], encoding="utf-8", xml_declaration=True)
        run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
        run_manifest["artifact_hashes"]["junit_sha256"] = _sha256(bundle["junit"])
        _write_json(bundle["run_manifest"], run_manifest)

        report, failures = _verify(bundle)

        assert failures == ["JUNIT_NODEID_INVALID"], label
        assert report["passed"] is False, label


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "shape",
        "duplicate",
        "order",
        "nodeid",
        "scope",
        "collection",
        "phase-shape",
        "phase-name",
        "phase-outcome",
        "limit",
        "limits-missing",
        "limits-extra",
        "limits-mismatch",
        "noncanonical-whitespace",
        "nodeid-utf8-overflow",
        "mode",
    ],
)
def test_s18_gate_rejects_invalid_pytest_events(tmp_path, mutation):
    bundle = _make_bundle(tmp_path / mutation)
    events = json.loads(bundle["pytest_events"].read_text(encoding="utf-8"))
    if mutation == "schema":
        events["schema_version"] = True
    elif mutation == "shape":
        events["unknown"] = True
    elif mutation == "duplicate":
        events["cases"].append(deepcopy(events["cases"][0]))
    elif mutation == "order":
        events["cases"].reverse()
    elif mutation == "nodeid":
        events["cases"][0]["nodeid"] = "tests/contract/../test_evidence_capture.py::test_bad"
    elif mutation == "scope":
        events["target"] = "retention"
    elif mutation == "collection":
        events["cases"].pop()
    elif mutation == "phase-shape":
        events["cases"][0]["phases"]["call"] = "passed"
    elif mutation == "phase-name":
        events["cases"][0]["phases"]["collect"] = None
    elif mutation == "phase-outcome":
        events["cases"][0]["phases"]["call"]["outcome"] = "rerun"
    elif mutation == "limit":
        events["cases"] = [
            {
                "nodeid": f"tests/contract/test_evidence_capture.py::test_extra_{index}",
                "xfail_marked": False,
                "phases": {
                    "setup": {"outcome": "passed", "wasxfail": False},
                    "call": {"outcome": "passed", "wasxfail": False},
                    "teardown": {"outcome": "passed", "wasxfail": False},
                },
            }
            for index in range(load_policy()["limits"]["testcases"] + 1)
        ]
    elif mutation == "limits-missing":
        del events["limits"]["pytest_events_nodeid_bytes"]
    elif mutation == "limits-extra":
        events["limits"]["unknown"] = 1
    elif mutation == "limits-mismatch":
        events["limits"]["testcases"] = 1
    elif mutation == "nodeid-utf8-overflow":
        events["cases"][0]["nodeid"] = (
            "tests/contract/test_evidence_capture.py::test_case["
            + "é" * 2049
            + "]"
        )
    if mutation == "noncanonical-whitespace":
        _write_json(bundle["pytest_events"], events)
        bundle["pytest_events"].chmod(0o600)
    else:
        _write_events_json(bundle["pytest_events"], events)
    if mutation == "mode":
        bundle["pytest_events"].chmod(0o640)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["pytest_events_sha256"] = _sha256(
        bundle["pytest_events"]
    )
    _write_json(bundle["run_manifest"], run_manifest)

    _, failures = _verify(bundle)

    assert "PYTEST_EVENTS_INVALID" in failures


def test_s18_gate_rejects_duplicate_pytest_phase_keys(tmp_path):
    bundle = _make_bundle(tmp_path / "duplicate-phase-key")
    content = bundle["pytest_events"].read_text(encoding="utf-8").replace(
        '"setup":{', '"setup":null,"setup":{', 1
    )
    bundle["pytest_events"].write_text(content, encoding="utf-8")
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["pytest_events_sha256"] = _sha256(
        bundle["pytest_events"]
    )
    _write_json(bundle["run_manifest"], run_manifest)

    _, failures = _verify(bundle)

    assert "PYTEST_EVENTS_INVALID" in failures


def test_s18_gate_rejects_missing_pytest_events_with_stable_code(tmp_path):
    bundle = _make_bundle(tmp_path / "missing")
    bundle["pytest_events"].unlink()

    _, failures = _verify(bundle)

    assert failures == ["PYTEST_EVENTS_INVALID"]


def test_s18_b3f_events_read_failure_does_not_derive_binding_failure(tmp_path):
    bundle = _make_bundle(tmp_path / "events-hardlink")
    os.link(bundle["pytest_events"], tmp_path / "events-hardlink-sibling")

    _, failures = _verify(bundle)

    assert failures == ["PYTEST_EVENTS_INVALID"]


def test_s18_gate_binds_pytest_events_hash(tmp_path):
    bundle = _make_bundle(tmp_path / "hash")
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["pytest_events_sha256"] = "b" * 64
    _write_json(bundle["run_manifest"], run_manifest)

    _, failures = _verify(bundle)

    assert "EVIDENCE_BINDING_INVALID" in failures


@pytest.mark.parametrize(
    "config_content",
    [
        b"[tool.pytest.ini_options]\n",
        b"[tool.pytest.ini_options]\nxfail_strict = false\n",
        b'[tool.pytest.ini_options]\nxfail_strict = "true"\n',
        b"[tool.pytest.ini_options]\nxfail_strict = 1\n",
        b"[tool.pytest.ini_options\n",
        PYTEST_CONFIG.read_bytes().replace(
            b'addopts = "-ra --strict-config --strict-markers"',
            b'addopts = "-ra --strict-config --strict-markers -p hostile_plugin"',
        ),
        PYTEST_CONFIG.read_bytes().replace(
            b"xfail_strict = true",
            b'xfail_strict = true\nrequired_plugins = ["hostile-plugin"]',
        ),
        PYTEST_CONFIG.read_bytes().replace(
            b'testpaths = ["tests"]', b'testpaths = ["tests/contract"]'
        ),
    ],
)
def test_s18_gate_rejects_invalid_xfail_configuration(
    tmp_path, monkeypatch, config_content
):
    bundle = _make_bundle(tmp_path / hashlib.sha256(config_content).hexdigest())
    digest = hashlib.sha256(config_content).hexdigest()
    environment = json.loads(bundle["environment"].read_text(encoding="utf-8"))
    environment["repository"]["pytest_config_sha256_before"] = digest
    environment["repository"]["pytest_config_sha256_after"] = digest
    _write_json(bundle["environment"], environment)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["pytest_config_sha256"] = digest
    run_manifest["artifact_hashes"]["environment_sha256"] = _sha256(bundle["environment"])
    _write_json(bundle["run_manifest"], run_manifest)
    real_read_bounded = security_verifier._read_bounded

    def replace_config(path: Path, limit: int, field: str) -> bytes:
        if path == PYTEST_CONFIG:
            return config_content
        return real_read_bounded(path, limit, field)

    monkeypatch.setattr(security_verifier, "_read_bounded", replace_config)

    _, failures = _verify(bundle)

    assert failures == ["RUNNER_CONFIGURATION_INVALID"]


@pytest.mark.parametrize(
    "token",
    [
        "plugin",
        "strict",
        "strict-override",
        "strict-duplicate",
        "scope-override",
        "extra-plugin",
        "plugin-duplicate",
        "config-duplicate",
        "config-override",
        "selection-k",
        "selection-marker",
        "confcutdir",
        "environment-autoload",
        "environment-addopts",
        "environment-plugins",
        "environment-pythonpath",
        "environment-pythonhome",
        "environment-pythonuserbase",
        "environment-uv-project",
        "environment-uv-python",
        "environment-coverage",
        "environment-extra",
        "isolated-missing",
        "isolated-duplicate",
        "isolated-reordered",
        "bytecode-missing",
        "bytecode-duplicate",
        "bootstrap-replaced",
        "identity-replaced",
        "identity-duplicate",
        "delimiter-missing",
        "delimiter-duplicate",
        "limit-missing",
        "limit-duplicate",
        "limit-reordered",
        "limit-mismatch",
    ],
)
def test_s18_gate_requires_exact_pytest_plugin_and_strict_tokens(tmp_path, token):
    bundle = _make_bundle(tmp_path / token)
    command = json.loads(bundle["command"].read_text(encoding="utf-8"))
    if token in {"plugin", "strict"}:
        expected = {
            "plugin": ("-p", "scripts.pytest_security_events"),
            "strict": ("-o", "xfail_strict=true"),
        }[token]
        index = next(
            index
            for index in range(len(command["argv"]) - 1)
            if tuple(command["argv"][index : index + 2]) == expected
        )
        del command["argv"][index : index + 2]
    elif token == "strict-override":
        command["argv"].extend(["-o", "xfail_strict=false"])
    elif token == "strict-duplicate":
        command["argv"].extend(["-o", "xfail_strict=true"])
    elif token == "scope-override":
        command["argv"].append("--security-target=retention")
    elif token == "extra-plugin":
        command["argv"].extend(["-p", "hostile_plugin"])
    elif token == "plugin-duplicate":
        command["argv"].extend(["-p", "pytest_cov.plugin"])
    elif token == "config-duplicate":
        command["argv"].extend(["-c", "pyproject.toml"])
    elif token == "config-override":
        command["argv"].extend(["-c", "pytest.ini"])
    elif token == "selection-k":
        command["argv"].extend(["-k", "required"])
    elif token == "selection-marker":
        command["argv"].extend(["-m", "system"])
    elif token == "confcutdir":
        command["argv"].append("--confcutdir=tests")
    elif token == "environment-autoload":
        command["sanitized_environment"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "0"
    elif token == "environment-addopts":
        command["sanitized_environment"]["PYTEST_ADDOPTS"] = "-k required"
    elif token == "environment-plugins":
        command["sanitized_environment"]["PYTEST_PLUGINS"] = "hostile_plugin"
    elif token == "environment-pythonpath":
        command["sanitized_environment"]["PYTHONPATH"] = "/hostile"
    elif token == "environment-pythonhome":
        command["sanitized_environment"]["PYTHONHOME"] = "/hostile"
    elif token == "environment-pythonuserbase":
        command["sanitized_environment"]["PYTHONUSERBASE"] = "/hostile"
    elif token == "environment-uv-project":
        command["sanitized_environment"]["UV_PROJECT_ENVIRONMENT"] = "/hostile"
    elif token == "environment-uv-python":
        command["sanitized_environment"]["UV_PYTHON"] = "/hostile/python"
    elif token == "environment-coverage":
        command["sanitized_environment"]["COVERAGE_FILE"] += ".other"
    elif token == "isolated-missing":
        command["argv"].remove("-I")
    elif token == "isolated-duplicate":
        command["argv"].insert(command["argv"].index("-I"), "-I")
    elif token == "isolated-reordered":
        isolated = command["argv"].index("-I")
        bytecode = command["argv"].index("-B")
        command["argv"][isolated], command["argv"][bytecode] = (
            command["argv"][bytecode],
            command["argv"][isolated],
        )
    elif token == "bytecode-missing":
        command["argv"].remove("-B")
    elif token == "bytecode-duplicate":
        command["argv"].insert(command["argv"].index("-B"), "-B")
    elif token == "bootstrap-replaced":
        command["argv"][command["argv"].index(os.fspath(BOOTSTRAP))] = os.fspath(
            VERIFIER
        )
    elif token == "identity-replaced":
        index = next(
            index
            for index, value in enumerate(command["argv"])
            if value.startswith("--plugin-identity=")
        )
        command["argv"][index] = "--plugin-identity=/hostile/identity.json"
    elif token == "identity-duplicate":
        value = next(
            value
            for value in command["argv"]
            if value.startswith("--plugin-identity=")
        )
        command["argv"].insert(command["argv"].index(value), value)
    elif token == "delimiter-missing":
        command["argv"].remove("--")
    elif token == "delimiter-duplicate":
        command["argv"].insert(command["argv"].index("--"), "--")
    elif token == "limit-missing":
        command["argv"].remove("--security-max-cases=4096")
    elif token == "limit-duplicate":
        value = "--security-max-nodeid-bytes=4096"
        command["argv"].insert(command["argv"].index(value), value)
    elif token == "limit-reordered":
        cases_index = command["argv"].index("--security-max-cases=4096")
        nodeid_index = command["argv"].index("--security-max-nodeid-bytes=4096")
        command["argv"][cases_index], command["argv"][nodeid_index] = (
            command["argv"][nodeid_index],
            command["argv"][cases_index],
        )
    elif token == "limit-mismatch":
        index = command["argv"].index("--security-max-events-bytes=8388608")
        command["argv"][index] = "--security-max-events-bytes=1"
    else:
        command["sanitized_environment"]["UNKNOWN"] = "value"
    _write_json(bundle["command"], command)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["command_sha256"] = _sha256(bundle["command"])
    _write_json(bundle["run_manifest"], run_manifest)

    _, failures = _verify(bundle)

    assert "RUNNER_CONFIGURATION_INVALID" in failures


def test_s18_gate_rejects_undeclared_other_runner_skip(tmp_path):
    bundle = _make_bundle(tmp_path / "other-runner-skip", target="retention")
    manifest = load_manifest(policy=load_policy())
    nodeids = _required_nodeids(manifest, "retention", "macos")
    linux_nodeid = next(
        nodeid
        for nodeid in _required_nodeids(manifest, "retention", "linux")
        if "two_concurrent_publishers" in nodeid
    )
    nodeids.append(linux_nodeid)
    _junit_document(nodeids, mutation=(linux_nodeid, "skipped")).write(
        bundle["junit"], encoding="utf-8", xml_declaration=True
    )
    events = _pytest_events_document(
        nodeids,
        run_id="s18-contract-001",
        target="retention",
        runner="macos",
        attempt=1,
        test_file=load_policy()["scripts"]["retention"]["test_file"],
        mutation=(
            linux_nodeid,
            {
                "phases": {
                    "setup": {"outcome": "passed", "wasxfail": False},
                    "call": {"outcome": "skipped", "wasxfail": False},
                    "teardown": {"outcome": "passed", "wasxfail": False},
                }
            },
        ),
    )
    _write_events_json(bundle["pytest_events"], events)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["junit_sha256"] = _sha256(bundle["junit"])
    run_manifest["artifact_hashes"]["pytest_events_sha256"] = _sha256(
        bundle["pytest_events"]
    )
    _write_json(bundle["run_manifest"], run_manifest)
    _, failures = _verify(bundle, target="retention")
    assert "UNEXPECTED_TEST_SKIP" in failures


@pytest.mark.parametrize(
    ("reason", "expected_failure"),
    [
        ("requires Linux mknod device semantics", False),
        ("generic platform skip", True),
    ],
)
def test_s18_gate_allows_only_exact_declared_device_platform_exclusion(
    tmp_path, reason, expected_failure
):
    bundle = _make_bundle(tmp_path / reason.replace(" ", "-"), target="retention")
    manifest = load_manifest(policy=load_policy())
    nodeids = _required_nodeids(manifest, "retention", "macos")
    device_nodeid = next(
        nodeid
        for nodeid in _required_nodeids(manifest, "retention", "linux")
        if "block_and_char_devices" in nodeid
    )
    nodeids.append(device_nodeid)
    _junit_document(
        nodeids,
        mutation=(device_nodeid, "skipped"),
        skip_message=reason,
    ).write(bundle["junit"], encoding="utf-8", xml_declaration=True)
    events = _pytest_events_document(
        nodeids,
        run_id="s18-contract-001",
        target="retention",
        runner="macos",
        attempt=1,
        test_file=load_policy()["scripts"]["retention"]["test_file"],
        mutation=(
            device_nodeid,
            {
                "phases": {
                    "setup": {"outcome": "passed", "wasxfail": False},
                    "call": {"outcome": "skipped", "wasxfail": False},
                    "teardown": {"outcome": "passed", "wasxfail": False},
                }
            },
        ),
    )
    _write_events_json(bundle["pytest_events"], events)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["junit_sha256"] = _sha256(bundle["junit"])
    run_manifest["artifact_hashes"]["pytest_events_sha256"] = _sha256(
        bundle["pytest_events"]
    )
    _write_json(bundle["run_manifest"], run_manifest)
    _, failures = _verify(bundle, target="retention")
    assert ("UNEXPECTED_TEST_SKIP" in failures) is expected_failure


@pytest.mark.parametrize(
    "artifact", ["coverage", "junit", "pytest_events", "environment", "command"]
)
def test_s18_gate_binds_every_runtime_artifact_hash(tmp_path, artifact):
    bundle = _make_bundle(tmp_path / artifact)
    path = bundle[artifact]
    path.write_bytes(path.read_bytes() + b"\n")
    _, failures = _verify(bundle)
    assert "EVIDENCE_BINDING_INVALID" in failures


@pytest.mark.parametrize("artifact", ["source", "test", "policy", "manifest"])
def test_s18_gate_rejects_checked_in_input_hash_drift(tmp_path, artifact):
    bundle = _make_bundle(tmp_path / artifact)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"][artifact + "_sha256"] = "b" * 64
    _write_json(bundle["run_manifest"], run_manifest)
    _, failures = _verify(bundle)
    assert "EVIDENCE_BINDING_INVALID" in failures


def test_s18_gate_binds_target_test_file_hash(tmp_path):
    bundle = _make_bundle(tmp_path / "test-source")
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["test_sha256"] = "b" * 64
    _write_json(bundle["run_manifest"], run_manifest)
    _, failures = _verify(bundle)
    assert "EVIDENCE_BINDING_INVALID" in failures


def test_s18_gate_rejects_target_test_before_after_drift(tmp_path):
    bundle = _make_bundle(tmp_path / "test-runtime-drift")
    environment = json.loads(bundle["environment"].read_text(encoding="utf-8"))
    environment["repository"]["test_sha256_after"] = "b" * 64
    _write_json(bundle["environment"], environment)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["environment_sha256"] = _sha256(bundle["environment"])
    _write_json(bundle["run_manifest"], run_manifest)

    _, failures = _verify(bundle)

    assert "EVIDENCE_BINDING_INVALID" in failures


def test_s18_manifest_symbol_and_hash_use_same_frozen_source_bytes(
    tmp_path, monkeypatch
):
    bundle = _make_bundle(tmp_path / "frozen-source")
    policy = load_policy()
    source_path = REPOSITORY_ROOT / policy["scripts"]["capture"]["path"]
    original_source = source_path.read_bytes()
    frozen_source = original_source.replace(
        b"def _seal_run(",
        b"def _seal_run_removed(",
        1,
    )
    assert frozen_source != original_source
    frozen_sha256 = hashlib.sha256(frozen_source).hexdigest()

    environment = json.loads(bundle["environment"].read_text(encoding="utf-8"))
    environment["repository"]["source_sha256_before"] = frozen_sha256
    environment["repository"]["source_sha256_after"] = frozen_sha256
    _write_json(bundle["environment"], environment)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["source_sha256"] = frozen_sha256
    run_manifest["artifact_hashes"]["environment_sha256"] = _sha256(
        bundle["environment"]
    )
    _write_json(bundle["run_manifest"], run_manifest)

    real_read_bounded = security_verifier._read_bounded
    source_reads = 0

    def split_source_read(path: Path, limit: int, field: str) -> bytes:
        nonlocal source_reads
        if path == source_path:
            source_reads += 1
            return frozen_source
        return real_read_bounded(path, limit, field)

    monkeypatch.setattr(security_verifier, "_read_bounded", split_source_read)

    report, failures = _verify(bundle)

    assert source_reads == 1
    assert failures == ["EVIDENCE_BINDING_INVALID"]
    assert report["passed"] is False


def test_s18_gate_rejects_second_pytest_test_path(tmp_path):
    bundle = _make_bundle(tmp_path / "second-test-path")
    command = json.loads(bundle["command"].read_text(encoding="utf-8"))
    command["argv"].append("tests/contract/test_evidence_retention.py")
    _write_json(bundle["command"], command)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["command_sha256"] = _sha256(bundle["command"])
    _write_json(bundle["run_manifest"], run_manifest)

    _, failures = _verify(bundle)

    assert "COMMAND_SCOPE_INVALID" in failures


@pytest.mark.parametrize("field", ["run_id", "target", "runner", "attempt"])
def test_s18_gate_rejects_cross_attempt_or_cross_platform_evidence(tmp_path, field):
    bundle = _make_bundle(tmp_path / field)
    environment = json.loads(bundle["environment"].read_text(encoding="utf-8"))
    environment[field] = {
        "run_id": "other-run",
        "target": "retention",
        "runner": "linux",
        "attempt": 2,
    }[field]
    _write_json(bundle["environment"], environment)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["environment_sha256"] = _sha256(bundle["environment"])
    _write_json(bundle["run_manifest"], run_manifest)
    _, failures = _verify(bundle)
    assert "EVIDENCE_SCOPE_INVALID" in failures


def test_s18_gate_rejects_runner_platform_claim_that_breaks_policy(tmp_path):
    bundle = _make_bundle(tmp_path / "platform")
    environment = json.loads(bundle["environment"].read_text(encoding="utf-8"))
    environment["platform"]["system"] = "Linux"
    _write_json(bundle["environment"], environment)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["environment_sha256"] = _sha256(bundle["environment"])
    _write_json(bundle["run_manifest"], run_manifest)
    _, failures = _verify(bundle)
    assert "EVIDENCE_PLATFORM_INVALID" in failures


@pytest.mark.parametrize(
    "mutation",
    ["duplicate-capability", "duplicate-nodeid", "unknown-category", "unknown-runner"],
)
def test_s18_manifest_schema_fails_closed_on_ambiguous_mappings(tmp_path, mutation):
    policy = load_policy()
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    if mutation == "duplicate-capability":
        manifest["capabilities"].append(deepcopy(manifest["capabilities"][0]))
    elif mutation == "duplicate-nodeid":
        first = manifest["capabilities"][0]["targets"][0]["requirements"][0]
        manifest["capabilities"][1]["targets"][0]["requirements"][0]["nodeid"] = first["nodeid"]
    elif mutation == "unknown-category":
        manifest["capabilities"][0]["category"] = "not-declared"
    else:
        manifest["capabilities"][0]["targets"][0]["requirements"][0]["runner"] = "ci"
    path = tmp_path / "manifest.json"
    _write_json(path, manifest)
    with pytest.raises(GateFailure):
        load_manifest(path, policy=policy)


def test_s18_verifier_failure_is_read_only_for_all_inputs(tmp_path):
    bundle = _make_bundle(tmp_path / "readonly")
    coverage = json.loads(bundle["coverage"].read_text(encoding="utf-8"))
    coverage["files"]["borrowed.py"] = deepcopy(next(iter(coverage["files"].values())))
    _write_json(bundle["coverage"], coverage)
    run_manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    run_manifest["artifact_hashes"]["coverage_sha256"] = _sha256(bundle["coverage"])
    _write_json(bundle["run_manifest"], run_manifest)
    before = {
        name: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for name, path in bundle.items()
    }
    _, failures = _verify(bundle)
    after = {
        name: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for name, path in bundle.items()
    }
    assert "SOURCE_SET_INVALID" in failures
    assert after == before


def test_s18_cli_error_is_one_sanitized_line_and_stable_nonzero(tmp_path):
    secret = "do-not-echo-contract-secret"
    result = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--target",
            "capture",
            "--coverage",
            str(tmp_path / secret / "coverage.json"),
            "--junit",
            str(tmp_path / secret / "junit.xml"),
            "--pytest-events",
            str(tmp_path / secret / "pytest-events.json"),
            "--environment",
            str(tmp_path / secret / "environment.json"),
            "--command",
            str(tmp_path / secret / "command.json"),
            "--run-manifest",
            str(tmp_path / secret / "run-manifest.json"),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "SECURITY_COVERAGE_INPUT_INVALID\n"
    assert secret not in result.stderr
    assert str(Path.home()) not in result.stderr
    assert "Traceback" not in result.stderr


def test_s18_cli_argparse_rejects_sensitive_value_without_echo():
    secret = "do-not-echo-argparse-secret"
    result = subprocess.run(
        [sys.executable, str(VERIFIER), "--target", secret],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "SECURITY_COVERAGE_INPUT_INVALID\n"
    assert secret not in result.stderr


def test_s18_runner_is_executable_and_keeps_attempts_and_sources_separate():
    assert VERIFIER.stat().st_mode & stat.S_IXUSR
    assert RUNNER.stat().st_mode & stat.S_IXUSR
    text = RUNNER.read_text(encoding="utf-8")
    assert "coverage combine" not in text
    assert ".coverage-capture" in text
    assert ".coverage-retention" in text
    assert "tests/contract/test_evidence_capture.py" in text
    assert "tests/contract/test_evidence_retention.py" in text
    assert "mkdir" in text and "run-manifest.json" in text
    assert "--cov-branch" in text


def test_s18_pytest_events_plugin_records_setup_call_and_teardown_reports(tmp_path):
    test_file = tmp_path / "test_sample.py"
    test_file.write_text(
        """import pytest

@pytest.fixture
def fail_setup():
    raise RuntimeError("setup failed")

@pytest.fixture
def skip_setup():
    pytest.skip("setup skipped")

@pytest.fixture
def fail_teardown():
    yield
    raise RuntimeError("teardown failed")

def test_normal_pass():
    assert True

def test_normal_failure():
    assert False

def test_setup_failure(fail_setup):
    del fail_setup

def test_setup_skip(skip_setup):
    del skip_setup

def test_call_skip():
    pytest.skip("call skipped")

def test_teardown_failure(fail_teardown):
    del fail_teardown

@pytest.mark.xfail(reason="expected")
def test_expected_failure():
    assert False

@pytest.mark.xfail(reason="hidden xpass", strict=False)
def test_non_strict_xpass():
    assert True

@pytest.mark.xfail(reason="strict xpass", strict=True)
def test_strict_xpass():
    assert True
""",
        encoding="utf-8",
    )
    events = tmp_path / "pytest-events.json"
    junit = tmp_path / "junit.xml"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.fspath(REPOSITORY_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "scripts.pytest_security_events",
            "-o",
            "xfail_strict=true",
            "--security-events=" + os.fspath(events),
            "--security-run-id=s18-plugin-characterization",
            "--security-target=capture",
                "--security-runner=macos",
                "--security-attempt=1",
                "--security-test-file=test_sample.py",
                "--security-max-cases=4096",
                "--security-max-nodeid-bytes=4096",
                "--security-max-events-bytes=8388608",
                "--junitxml=" + os.fspath(junit),
                "test_sample.py",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    document = json.loads(events.read_text(encoding="utf-8"))
    assert {key: document[key] for key in document if key != "cases"} == {
        "schema_version": 3,
        "run_id": "s18-plugin-characterization",
        "target": "capture",
        "runner": "macos",
        "attempt": 1,
        "test_file": "test_sample.py",
        "limits": {
            "testcases": 4096,
            "pytest_events_nodeid_bytes": 4096,
            "pytest_events_bytes": 8388608,
        },
    }
    cases = {case["nodeid"].split("::", 1)[1]: case for case in document["cases"]}

    def phase(outcome, wasxfail=False):
        return {"outcome": outcome, "wasxfail": wasxfail}

    assert cases == {
        "test_call_skip": {
            "nodeid": "test_sample.py::test_call_skip",
            "xfail_marked": False,
            "phases": {
                "setup": phase("passed"),
                "call": phase("skipped"),
                "teardown": phase("passed"),
            },
        },
        "test_expected_failure": {
            "nodeid": "test_sample.py::test_expected_failure",
            "xfail_marked": True,
            "phases": {
                "setup": phase("passed"),
                "call": phase("skipped", True),
                "teardown": phase("passed"),
            },
        },
        "test_non_strict_xpass": {
            "nodeid": "test_sample.py::test_non_strict_xpass",
            "xfail_marked": True,
            "phases": {
                "setup": phase("passed"),
                "call": phase("passed", True),
                "teardown": phase("passed"),
            },
        },
        "test_normal_failure": {
            "nodeid": "test_sample.py::test_normal_failure",
            "xfail_marked": False,
            "phases": {
                "setup": phase("passed"),
                "call": phase("failed"),
                "teardown": phase("passed"),
            },
        },
        "test_normal_pass": {
            "nodeid": "test_sample.py::test_normal_pass",
            "xfail_marked": False,
            "phases": {
                "setup": phase("passed"),
                "call": phase("passed"),
                "teardown": phase("passed"),
            },
        },
        "test_setup_failure": {
            "nodeid": "test_sample.py::test_setup_failure",
            "xfail_marked": False,
            "phases": {
                "setup": phase("failed"),
                "call": None,
                "teardown": phase("passed"),
            },
        },
        "test_setup_skip": {
            "nodeid": "test_sample.py::test_setup_skip",
            "xfail_marked": False,
            "phases": {
                "setup": phase("skipped"),
                "call": None,
                "teardown": phase("passed"),
            },
        },
        "test_strict_xpass": {
            "nodeid": "test_sample.py::test_strict_xpass",
            "xfail_marked": True,
            "phases": {
                "setup": phase("passed"),
                "call": phase("failed"),
                "teardown": phase("passed"),
            },
        },
        "test_teardown_failure": {
            "nodeid": "test_sample.py::test_teardown_failure",
            "xfail_marked": False,
            "phases": {
                "setup": phase("passed"),
                "call": phase("passed"),
                "teardown": phase("failed"),
            },
        },
    }
    junit_cases, _, invalid = security_verifier._junit_cases(
        junit.read_bytes(), 32, test_file="test_sample.py"
    )
    assert invalid == 0
    assert junit_cases == {
        "test_sample.py::test_call_skip": "skipped",
        "test_sample.py::test_expected_failure": "xfail",
        "test_sample.py::test_non_strict_xpass": "passed",
        "test_sample.py::test_normal_failure": "failure",
        "test_sample.py::test_normal_pass": "passed",
        "test_sample.py::test_setup_failure": "error",
        "test_sample.py::test_setup_skip": "skipped",
        "test_sample.py::test_strict_xpass": "failure",
        "test_sample.py::test_teardown_failure": "error",
    }
    assert stat.S_IMODE(events.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".pytest-events.json.*.tmp"))


@pytest.mark.parametrize(
    ("when", "outcome", "existing_phase"),
    [
        ("collect", "passed", None),
        ("call", "rerun", None),
        ("call", "passed", {"outcome": "passed", "wasxfail": False}),
    ],
    ids=["unknown-phase", "illegal-outcome", "duplicate-phase"],
)
def test_s18_pytest_events_plugin_rejects_invalid_phase_reports(
    when, outcome, existing_phase
):
    nodeid = "test_sample.py::test_case"
    case = {
        "nodeid": nodeid,
        "xfail_marked": False,
        "phases": {"setup": None, "call": existing_phase, "teardown": None},
    }
    config = SimpleNamespace(
        _s18_security_events_state={"cases": {nodeid: case}}
    )
    item = SimpleNamespace(config=config)
    report = SimpleNamespace(
        nodeid=nodeid,
        when=when,
        outcome=outcome,
        wasxfail=False,
    )
    hook_outcome = SimpleNamespace(get_result=lambda: report)
    hook = security_events_plugin.pytest_runtest_makereport(item, None)
    next(hook)

    with pytest.raises(pytest.UsageError, match="PYTEST_EVENTS_CONFIGURATION_INVALID"):
        hook.send(hook_outcome)


def test_s18_b3f_report_fatal_prevents_partial_sidecar(tmp_path):
    output = tmp_path / "pytest-events.json"
    config = _b3f_events_config(output)
    security_events_plugin.pytest_configure(config)
    item = _b3f_item("test_sample.py::test_case")
    item.config = config
    security_events_plugin.pytest_collection_modifyitems(config, [item])
    report = SimpleNamespace(
        nodeid=item.nodeid,
        when="collect",
        outcome="passed",
        wasxfail=False,
    )
    hook = security_events_plugin.pytest_runtest_makereport(item, None)
    next(hook)

    with pytest.raises(pytest.UsageError, match="PYTEST_EVENTS_CONFIGURATION_INVALID"):
        hook.send(SimpleNamespace(get_result=lambda: report))

    security_events_plugin.pytest_sessionfinish(SimpleNamespace(config=config), 2)
    assert not output.exists()
    assert not output.with_name(f".{output.name}.{os.getpid()}.tmp").exists()


def _b3f_events_config(
    output: Path,
    *,
    max_cases: str = "4096",
    max_nodeid_bytes: str = "4096",
    max_events_bytes: str = "8388608",
    raw_argument_mutation=None,
):
    options = {
        "security_events": os.fspath(output),
        "security_run_id": "s18-b3f-l-unit",
        "security_target": "capture",
        "security_runner": "macos",
        "security_attempt": "1",
        "security_test_file": "test_sample.py",
        "security_max_cases": max_cases,
        "security_max_nodeid_bytes": max_nodeid_bytes,
        "security_max_events_bytes": max_events_bytes,
    }
    arguments = [
        "--security-events=" + options["security_events"],
        "--security-run-id=" + options["security_run_id"],
        "--security-target=" + options["security_target"],
        "--security-runner=" + options["security_runner"],
        "--security-attempt=" + options["security_attempt"],
        "--security-test-file=" + options["security_test_file"],
        "--security-max-cases=" + max_cases,
        "--security-max-nodeid-bytes=" + max_nodeid_bytes,
        "--security-max-events-bytes=" + max_events_bytes,
    ]
    if raw_argument_mutation is not None:
        raw_argument_mutation(arguments)
    return SimpleNamespace(
        getoption=options.__getitem__,
        invocation_params=SimpleNamespace(args=tuple(arguments)),
    )


def test_s18_b3f_policy_v2_freezes_exact_producer_limits():
    policy = load_policy()

    assert policy["schema_version"] == 2
    assert {
        name: policy["limits"][name]
        for name in (
            "testcases",
            "pytest_events_nodeid_bytes",
            "pytest_events_bytes",
        )
    } == {
        "testcases": 4096,
        "pytest_events_nodeid_bytes": 4096,
        "pytest_events_bytes": 8388608,
    }


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("max_cases", "0"),
        ("max_cases", "-1"),
        ("max_cases", "1.0"),
        ("max_cases", "\N{ARABIC-INDIC DIGIT ONE}"),
        ("max_cases", "9" * 5000),
        ("max_cases", "4097"),
        ("max_nodeid_bytes", "4097"),
        ("max_events_bytes", "8388609"),
    ],
    ids=[
        "b3fl007-zero",
        "b3fl007-negative",
        "b3fl007-non-decimal",
        "b3fl007-non-ascii-decimal",
        "b3fl007-excessive-digits",
        "b3fl007-cases-overflow",
        "b3fl007-nodeid-overflow",
        "b3fl007-events-overflow",
    ],
)
def test_s18_b3f_events_rejects_invalid_limits(tmp_path, option, value):
    config = _b3f_events_config(tmp_path / "pytest-events.json", **{option: value})

    with pytest.raises(pytest.UsageError, match="PYTEST_EVENTS_CONFIGURATION_INVALID"):
        security_events_plugin.pytest_configure(config)


def test_s18_b3f_real_configure_rejects_excessive_decimal_digits(tmp_path):
    test_file = tmp_path / "test_sample.py"
    test_file.write_text("def test_case():\n    pass\n", encoding="utf-8")
    output = tmp_path / "pytest-events.json"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.fspath(REPOSITORY_ROOT)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--noconftest",
            "-p",
            "no:cacheprovider",
            "-p",
            "scripts.pytest_security_events",
            "--security-events=" + os.fspath(output),
            "--security-run-id=s18-b3f-long-decimal",
            "--security-target=capture",
            "--security-runner=macos",
            "--security-attempt=1",
            "--security-test-file=test_sample.py",
            "--security-max-cases=" + "9" * 5000,
            "--security-max-nodeid-bytes=4096",
            "--security-max-events-bytes=8388608",
            "test_sample.py",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 4
    assert result.stdout == ""
    assert result.stderr == "ERROR: PYTEST_EVENTS_CONFIGURATION_INVALID\n\n"
    assert not output.exists()
    assert not list(tmp_path.glob(".pytest-events.json.*.tmp"))


@pytest.mark.parametrize(
    "name",
    [
        "--security-max-cases",
        "--security-max-nodeid-bytes",
        "--security-max-events-bytes",
    ],
    ids=[
        "b3fl008-cases",
        "b3fl008-nodeid-bytes",
        "b3fl008-events-bytes",
    ],
)
def test_s18_b3f_events_rejects_duplicate_limit_options(tmp_path, name):
    def duplicate(arguments):
        value = next(item for item in arguments if item.startswith(name + "="))
        arguments.append(value)

    config = _b3f_events_config(
        tmp_path / "pytest-events.json", raw_argument_mutation=duplicate
    )

    with pytest.raises(pytest.UsageError, match="PYTEST_EVENTS_CONFIGURATION_INVALID"):
        security_events_plugin.pytest_configure(config)


def _b3f_item(nodeid: str, *, xfail: bool = False):
    return SimpleNamespace(
        nodeid=nodeid,
        iter_markers=lambda *, name: [object()] if xfail and name == "xfail" else [],
    )


def test_s18_b3f_events_cases_exact_boundary_and_plus_one(tmp_path):
    config = _b3f_events_config(tmp_path / "pytest-events.json")
    security_events_plugin.pytest_configure(config)
    exact = [_b3f_item(f"test_sample.py::test_case[{index}]") for index in range(4096)]

    security_events_plugin.pytest_collection_modifyitems(config, exact)

    assert len(config._s18_security_events_state["cases"]) == 4096
    overflow = _b3f_item("test_sample.py::test_case[overflow]")
    with pytest.raises(pytest.UsageError, match="PYTEST_EVENTS_LIMIT_EXCEEDED"):
        security_events_plugin.pytest_collection_modifyitems(config, [overflow])
    assert overflow.nodeid not in config._s18_security_events_state["cases"]
    security_events_plugin.pytest_sessionfinish(SimpleNamespace(config=config), 2)
    assert not (tmp_path / "pytest-events.json").exists()


@pytest.mark.parametrize(
    "multibyte",
    [False, True],
    ids=["b3fl004-ascii", "b3fl004-multibyte"],
)
def test_s18_b3f_events_nodeid_utf8_exact_boundary_and_plus_one(tmp_path, multibyte):
    config = _b3f_events_config(tmp_path / "pytest-events.json")
    security_events_plugin.pytest_configure(config)
    prefix = "test_sample.py::test_case["
    suffix = "]"

    def nodeid_with_bytes(size):
        remaining = size - len((prefix + suffix).encode())
        if multibyte:
            return prefix + ("é" * (remaining // 2)) + ("x" * (remaining % 2)) + suffix
        return prefix + ("x" * remaining) + suffix

    exact = nodeid_with_bytes(4096)
    security_events_plugin.pytest_collection_modifyitems(config, [_b3f_item(exact)])
    assert exact in config._s18_security_events_state["cases"]

    overflow = nodeid_with_bytes(4097)
    with pytest.raises(pytest.UsageError, match="PYTEST_EVENTS_LIMIT_EXCEEDED"):
        security_events_plugin.pytest_collection_modifyitems(config, [_b3f_item(overflow)])
    assert overflow not in config._s18_security_events_state["cases"]
    security_events_plugin.pytest_sessionfinish(SimpleNamespace(config=config), 2)
    assert not (tmp_path / "pytest-events.json").exists()
    assert not (tmp_path / f".pytest-events.json.{os.getpid()}.tmp").exists()


def test_s18_b3f_events_compact_serialized_bytes_exact_boundary_and_plus_one():
    document = {
        "schema_version": 3,
        "run_id": "s18-b3f-l-unit",
        "target": "capture",
        "runner": "macos",
        "attempt": 1,
        "test_file": "test_sample.py",
        "limits": {
            "testcases": 4096,
            "pytest_events_nodeid_bytes": 4096,
            "pytest_events_bytes": 8388608,
        },
        "cases": [{"nodeid": "", "xfail_marked": False, "phases": {}}],
    }
    empty_nodeid_bytes = (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()
    document["cases"][0]["nodeid"] = "x" * (8388608 - len(empty_nodeid_bytes))
    expected = (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()

    assert len(expected) == 8388608
    assert security_events_plugin._canonical_events_bytes(
        document, max_bytes=8388608
    ) == expected
    with pytest.raises(pytest.UsageError, match="PYTEST_EVENTS_LIMIT_EXCEEDED"):
        security_events_plugin._canonical_events_bytes(document, max_bytes=8388607)


def test_s18_b3f_case_byte_estimate_is_the_exact_legal_maximum():
    nodeid = "test_sample.py::test_case[é]"
    phase_values = [None]
    phase_values.extend(
        {"outcome": outcome, "wasxfail": wasxfail}
        for outcome in ("passed", "failed", "skipped")
        for wasxfail in (False, True)
    )

    for xfail_marked in (False, True):
        estimate = len(
            security_events_plugin._worst_case_bytes(
                nodeid, xfail_marked=xfail_marked
            )
        )
        actual_sizes = []
        for setup, call, teardown in product(phase_values, repeat=3):
            actual_sizes.append(
                len(
                    security_events_plugin._canonical_json_bytes(
                        {
                            "nodeid": nodeid,
                            "xfail_marked": xfail_marked,
                            "phases": {
                                "setup": setup,
                                "call": call,
                                "teardown": teardown,
                            },
                        }
                    )
                )
            )

        assert all(estimate >= actual for actual in actual_sizes)
        assert estimate == max(actual_sizes)


def test_s18_b3f_events_writer_write_zero_fails_before_deadline(tmp_path):
    output = tmp_path / "pytest-events.json"
    script = "\n".join(
        [
            "from pathlib import Path",
            "from scripts import pytest_security_events as plugin",
            f"output = Path({os.fspath(output)!r})",
            "temporary = output.with_name(f'.{output.name}.{plugin.os.getpid()}.tmp')",
            "plugin.os.write = lambda descriptor, view: 0",
            "try:",
            "    plugin._atomic_write(output, b'payload\\n')",
            "except Exception as exc:",
            "    ok = ('PYTEST_EVENTS_PUBLICATION_FAILED' in str(exc)",
            "          and not output.exists()",
            "          and not temporary.exists())",
            "    raise SystemExit(0 if ok else 3)",
            "raise SystemExit(4)",
        ]
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=2,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_s18_b3f_events_writer_preserves_preexisting_temp(tmp_path):
    output = tmp_path / "pytest-events.json"
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_bytes(b"old temp\n")
    temporary.chmod(0o640)
    before = (
        temporary.stat().st_dev,
        temporary.stat().st_ino,
        stat.S_IMODE(temporary.stat().st_mode),
        temporary.stat().st_nlink,
        temporary.stat().st_size,
        _sha256(temporary),
    )

    with pytest.raises(
        security_events_plugin.EventsPublicationError,
        match="PYTEST_EVENTS_PUBLICATION_FAILED",
    ):
        security_events_plugin._atomic_write(output, b"new payload\n")

    assert before == (
        temporary.stat().st_dev,
        temporary.stat().st_ino,
        stat.S_IMODE(temporary.stat().st_mode),
        temporary.stat().st_nlink,
        temporary.stat().st_size,
        _sha256(temporary),
    )
    assert not output.exists()


def test_s18_b3f_events_writer_uses_exact_no_replace_syscall_order(tmp_path, monkeypatch):
    output = tmp_path / "pytest-events.json"
    calls = []
    real_open = security_events_plugin.os.open
    real_fchmod = security_events_plugin.os.fchmod
    real_write = security_events_plugin.os.write
    real_fsync = security_events_plugin.os.fsync
    real_close = security_events_plugin.os.close
    real_link = security_events_plugin.os.link
    real_unlink = security_events_plugin.os.unlink

    def open_record(path, flags, mode=0o777):
        if flags & os.O_CREAT:
            descriptor = real_open(path, flags, mode)
            calls.append(("open-temp", descriptor, flags, mode))
        else:
            descriptor = real_open(path, flags)
            calls.append(("open-dir", descriptor, flags))
        return descriptor

    def fchmod_record(descriptor, mode):
        calls.append(("fchmod", descriptor, mode))
        return real_fchmod(descriptor, mode)

    def write_record(descriptor, view):
        calls.append(("write", descriptor))
        return real_write(descriptor, view[:3])

    def fsync_record(descriptor):
        calls.append(("fsync", descriptor))
        return real_fsync(descriptor)

    def close_record(descriptor):
        calls.append(("close", descriptor))
        return real_close(descriptor)

    def link_record(source, destination, *, follow_symlinks):
        calls.append(("link", source, destination, follow_symlinks))
        return real_link(source, destination, follow_symlinks=follow_symlinks)

    def unlink_record(path):
        calls.append(("unlink", path))
        return real_unlink(path)

    monkeypatch.setattr(security_events_plugin.os, "open", open_record)
    monkeypatch.setattr(security_events_plugin.os, "fchmod", fchmod_record)
    monkeypatch.setattr(security_events_plugin.os, "write", write_record)
    monkeypatch.setattr(security_events_plugin.os, "fsync", fsync_record)
    monkeypatch.setattr(security_events_plugin.os, "close", close_record)
    monkeypatch.setattr(security_events_plugin.os, "link", link_record)
    monkeypatch.setattr(security_events_plugin.os, "unlink", unlink_record)
    monkeypatch.setattr(
        security_events_plugin.os,
        "replace",
        lambda *args, **kwargs: pytest.fail("events writer must not call os.replace"),
    )

    security_events_plugin._atomic_write(output, b"payload\n")

    temp_fd = calls[0][1]
    directory_fd = next(call[1] for call in calls if call[0] == "open-dir")
    temp_flags = calls[0][2]
    directory_flags = next(call[2] for call in calls if call[0] == "open-dir")
    assert temp_flags & os.O_WRONLY
    assert temp_flags & os.O_CREAT
    assert temp_flags & os.O_EXCL
    assert temp_flags & getattr(os, "O_CLOEXEC", 0) == getattr(os, "O_CLOEXEC", 0)
    assert not temp_flags & os.O_TRUNC
    assert calls[0][3] == 0o600
    assert directory_flags & os.O_RDONLY == os.O_RDONLY
    assert directory_flags & getattr(os, "O_DIRECTORY", 0)
    assert directory_flags & getattr(os, "O_CLOEXEC", 0) == getattr(
        os, "O_CLOEXEC", 0
    )
    assert calls == [
        ("open-temp", temp_fd, temp_flags, 0o600),
        ("fchmod", temp_fd, 0o600),
        ("write", temp_fd),
        ("write", temp_fd),
        ("write", temp_fd),
        ("fsync", temp_fd),
        ("close", temp_fd),
        ("link", output.with_name(f".{output.name}.{os.getpid()}.tmp"), output, False),
        ("unlink", output.with_name(f".{output.name}.{os.getpid()}.tmp")),
        ("open-dir", directory_fd, directory_flags),
        ("fsync", directory_fd),
        ("close", directory_fd),
    ]
    assert output.read_bytes() == b"payload\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.stat().st_nlink == 1


def test_s18_b3f_events_writer_forces_mode_0600_under_restrictive_umask(tmp_path):
    output = tmp_path / "pytest-events.json"
    previous_umask = security_events_plugin.os.umask(0o777)
    try:
        security_events_plugin._atomic_write(output, b"payload\n")
    finally:
        security_events_plugin.os.umask(previous_umask)

    assert output.read_bytes() == b"payload\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.stat().st_nlink == 1
    assert not output.with_name(f".{output.name}.{os.getpid()}.tmp").exists()


def test_s18_b3f_events_writer_publish_race_preserves_winner(tmp_path, monkeypatch):
    output = tmp_path / "pytest-events.json"
    winner = b"winner\n"
    real_link = security_events_plugin.os.link
    winner_identity = None

    def publish_winner(source, destination, *, follow_symlinks):
        nonlocal winner_identity
        Path(destination).write_bytes(winner)
        Path(destination).chmod(0o640)
        winner_identity = (Path(destination).stat().st_dev, Path(destination).stat().st_ino)
        return real_link(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(security_events_plugin.os, "link", publish_winner)

    with pytest.raises(
        security_events_plugin.EventsPublicationError,
        match="PYTEST_EVENTS_PUBLICATION_FAILED",
    ):
        security_events_plugin._atomic_write(output, b"loser\n")

    assert output.read_bytes() == winner
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    assert winner_identity == (output.stat().st_dev, output.stat().st_ino)
    assert not output.with_name(f".{output.name}.{os.getpid()}.tmp").exists()


@pytest.mark.parametrize(
    "stage",
    ["open", "fchmod", "write", "file-fsync", "link"],
    ids=[
        "b3fl011-open",
        "b3fl011-fchmod",
        "b3fl011-write-exception",
        "b3fl011-file-fsync",
        "b3fl011-link-failure",
    ],
)
def test_s18_b3f_events_writer_prepublication_faults_cleanup(
    tmp_path, monkeypatch, stage
):
    output = tmp_path / "pytest-events.json"
    if stage == "open":
        monkeypatch.setattr(
            security_events_plugin.os,
            "open",
            lambda *args: (_ for _ in ()).throw(OSError("controlled open")),
        )
    elif stage == "fchmod":
        monkeypatch.setattr(
            security_events_plugin.os,
            "fchmod",
            lambda *args: (_ for _ in ()).throw(OSError("controlled fchmod")),
        )
    elif stage == "write":
        real_write = security_events_plugin.os.write
        write_calls = 0

        def write_fault(descriptor, view):
            nonlocal write_calls
            write_calls += 1
            if write_calls == 1:
                return real_write(descriptor, view[:1])
            raise OSError("controlled write")

        monkeypatch.setattr(
            security_events_plugin.os,
            "write",
            write_fault,
        )
    elif stage == "file-fsync":
        monkeypatch.setattr(
            security_events_plugin.os,
            "fsync",
            lambda *args: (_ for _ in ()).throw(OSError("controlled fsync")),
        )
    else:
        monkeypatch.setattr(
            security_events_plugin.os,
            "link",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("controlled link")),
        )

    with pytest.raises(
        security_events_plugin.EventsPublicationError,
        match="PYTEST_EVENTS_PUBLICATION_FAILED",
    ):
        security_events_plugin._atomic_write(output, b"payload\n")

    assert not output.exists()
    assert not output.with_name(f".{output.name}.{os.getpid()}.tmp").exists()


@pytest.mark.parametrize(
    "stage",
    [
        "temp-unlink",
        "temp-unlink-once",
        "directory-open",
        "directory-fsync",
        "directory-close",
    ],
    ids=[
        "b3fl011-temp-unlink",
        "b3fl011-temp-unlink-retry-cleanup",
        "b3fl011-directory-open",
        "b3fl011-directory-fsync",
        "b3fl011-directory-close",
    ],
)
def test_s18_b3f_events_writer_postpublication_faults_are_uncertain(
    tmp_path, monkeypatch, stage
):
    output = tmp_path / "pytest-events.json"
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    real_open = security_events_plugin.os.open
    real_fsync = security_events_plugin.os.fsync
    real_close = security_events_plugin.os.close
    directory_descriptor = None
    fsync_calls = 0

    if stage in {"temp-unlink", "temp-unlink-once"}:
        unlink_calls = 0
        real_unlink = security_events_plugin.os.unlink

        def unlink_fault(path):
            nonlocal unlink_calls
            unlink_calls += 1
            if stage == "temp-unlink" or unlink_calls == 1:
                raise OSError("controlled unlink")
            return real_unlink(path)

        monkeypatch.setattr(
            security_events_plugin.os,
            "unlink",
            unlink_fault,
        )
    elif stage == "directory-open":
        def open_fault(path, flags, mode=0o777):
            if flags & getattr(os, "O_DIRECTORY", 0):
                raise OSError("controlled directory open")
            return real_open(path, flags, mode)

        monkeypatch.setattr(security_events_plugin.os, "open", open_fault)
    elif stage == "directory-fsync":
        def fsync_fault(descriptor):
            nonlocal fsync_calls
            fsync_calls += 1
            if fsync_calls == 2:
                raise OSError("controlled directory fsync")
            return real_fsync(descriptor)

        monkeypatch.setattr(security_events_plugin.os, "fsync", fsync_fault)
    else:
        def open_record(path, flags, mode=0o777):
            nonlocal directory_descriptor
            if flags & getattr(os, "O_DIRECTORY", 0):
                directory_descriptor = real_open(path, flags)
                return directory_descriptor
            return real_open(path, flags, mode)

        def close_fault(descriptor):
            if descriptor == directory_descriptor:
                real_close(descriptor)
                raise OSError("controlled directory close")
            return real_close(descriptor)

        monkeypatch.setattr(security_events_plugin.os, "open", open_record)
        monkeypatch.setattr(security_events_plugin.os, "close", close_fault)

    with pytest.raises(
        security_events_plugin.EventsCommitUncertain,
        match="PYTEST_EVENTS_COMMIT_UNCERTAIN",
    ):
        security_events_plugin._atomic_write(output, b"payload\n")

    assert output.read_bytes() == b"payload\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    if stage == "temp-unlink":
        assert temporary.stat().st_ino == output.stat().st_ino
        assert output.stat().st_nlink == temporary.stat().st_nlink == 2
    else:
        assert not temporary.exists()
        assert output.stat().st_nlink == 1


@pytest.mark.parametrize("flags", [[], ["-I"], ["-B"]])
def test_s18_security_bootstrap_requires_isolated_no_bytecode_python(tmp_path, flags):
    identity = tmp_path / ("identity-" + ("".join(flags) or "none") + ".json")
    result = subprocess.run(
        [
            sys.executable,
            *flags,
            os.fspath(BOOTSTRAP),
            "--plugin-identity=" + os.fspath(identity),
            "--",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("SECURITY_PYTEST_BOOTSTRAP_INVALID:")
    assert not identity.exists()


def test_s18_plugin_identity_writer_never_overwrites_existing_output(tmp_path):
    output = tmp_path / "plugin-identity.json"
    output.write_bytes(b"preserve\n")
    before = output.read_bytes()

    with pytest.raises(security_bootstrap.BootstrapError):
        security_bootstrap._write_exclusive(output, {"schema_version": 1})

    assert output.read_bytes() == before
    assert not list(tmp_path.glob(".plugin-identity.json.*.tmp"))


def test_s18_plugin_identity_writer_publishes_exact_single_link_mode_0600(tmp_path):
    output = tmp_path / "plugin-identity.json"
    document = {"schema_version": 1, "value": "exact"}
    expected = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()

    security_bootstrap._write_exclusive(output, document)

    assert output.read_bytes() == expected
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.stat().st_nlink == 1
    assert not list(tmp_path.glob(".plugin-identity.json.*.tmp"))


def test_s18_plugin_identity_writer_forces_mode_0600_under_restrictive_umask(tmp_path):
    output = tmp_path / "plugin-identity.json"
    previous_umask = security_bootstrap.os.umask(0o777)
    try:
        security_bootstrap._write_exclusive(output, {"schema_version": 1})
    finally:
        security_bootstrap.os.umask(previous_umask)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.stat().st_nlink == 1
    assert not list(tmp_path.glob(".plugin-identity.json.*.tmp"))


def test_s18_plugin_identity_writer_loses_publish_race_without_replacement(
    tmp_path, monkeypatch
):
    output = tmp_path / "plugin-identity.json"
    competing_bytes = b"competing identity\n"
    competing_mode = 0o640
    real_link = security_bootstrap.os.link
    competing_identity = None

    def publish_competitor(source, destination, *, follow_symlinks):
        nonlocal competing_identity
        Path(destination).write_bytes(competing_bytes)
        Path(destination).chmod(competing_mode)
        competing_identity = (
            Path(destination).stat().st_dev,
            Path(destination).stat().st_ino,
        )
        return real_link(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(security_bootstrap.os, "link", publish_competitor)

    with pytest.raises(
        security_bootstrap.BootstrapError,
        match="cannot be published without replacement",
    ):
        security_bootstrap._write_exclusive(output, {"schema_version": 1})

    assert output.read_bytes() == competing_bytes
    assert stat.S_IMODE(output.stat().st_mode) == competing_mode
    assert competing_identity == (output.stat().st_dev, output.stat().st_ino)
    assert not list(tmp_path.glob(".plugin-identity.json.*.tmp"))


def test_s18_identity_guard_rejects_same_name_different_plugin_object(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    output = tmp_path / "plugin-identity.json"
    expected_cov = SimpleNamespace(__name__="pytest_cov.plugin")
    expected_events = SimpleNamespace(__name__="scripts.pytest_security_events")
    clone = SimpleNamespace(__name__="pytest_cov.plugin")
    modules = {
        "pytest_cov.plugin": expected_cov,
        "scripts.pytest_security_events": expected_events,
    }
    manager = SimpleNamespace(
        get_plugin=lambda name: clone if name == "pytest_cov.plugin" else modules[name]
    )
    guard = security_bootstrap._IdentityGuard(
        modules=modules,
        output=output,
        repository_root=repository,
        document={"schema_version": 1},
    )

    with pytest.raises(security_bootstrap.BootstrapError, match="registration differs"):
        guard.pytest_configure(SimpleNamespace(pluginmanager=manager))

    assert not output.exists()
    assert os.fspath(repository) not in sys.path


def test_s18_identity_guard_writes_mode_0600_after_object_validation(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    repository.mkdir()
    output = tmp_path / "plugin-identity.json"
    cov = SimpleNamespace(__name__="pytest_cov.plugin")
    events = SimpleNamespace(__name__="scripts.pytest_security_events")
    modules = {
        "pytest_cov.plugin": cov,
        "scripts.pytest_security_events": events,
    }
    manager = SimpleNamespace(get_plugin=modules.__getitem__)
    isolated_path = [item for item in sys.path if item != os.fspath(repository)]
    monkeypatch.setattr(security_bootstrap.sys, "path", isolated_path)
    for name, module in modules.items():
        monkeypatch.setitem(security_bootstrap.sys.modules, name, module)
    guard = security_bootstrap._IdentityGuard(
        modules=modules,
        output=output,
        repository_root=repository,
        document={"schema_version": 1},
    )

    guard.pytest_configure(SimpleNamespace(pluginmanager=manager))

    assert json.loads(output.read_text(encoding="utf-8")) == {"schema_version": 1}
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert security_bootstrap.sys.path[0] == os.fspath(repository)


def _b3e_minimal_source(manifest: dict[str, object], target: str) -> str:
    symbols = sorted(
        {
            symbol["name"]
            for capability in manifest["capabilities"]
            for target_record in capability["targets"]
            if target_record["script"] == target
            for symbol in target_record["symbols"]
        }
    )
    classes: dict[str, list[str]] = {}
    functions: list[str] = []
    for symbol in symbols:
        if "." in symbol:
            class_name, method_name = symbol.split(".", 1)
            classes.setdefault(class_name, []).append(method_name)
        else:
            functions.append(symbol)
    lines = ['"""Minimal real-pytest B3e fixture source."""', ""]
    for function_name in functions:
        lines.extend(
            [
                f"def {function_name}():",
                "    return True",
                "",
            ]
        )
    for class_name, methods in sorted(classes.items()):
        lines.append(f"class {class_name}:")
        for method_name in sorted(methods):
            lines.extend(
                [
                    f"    def {method_name}(self):",
                    "        return True",
                    "",
                ]
            )
    return "\n".join(lines)


def _b3e_minimal_tests(
    manifest: dict[str, object],
    *,
    target: str,
    runner: str,
    selected_nodeid: str | None = None,
    selected_behavior: str | None = None,
) -> str:
    module = {"capture": "capture_test_gate", "retention": "manage_evidence_retention"}[
        target
    ]
    source_symbols = sorted(
        {
            symbol["name"]
            for capability in manifest["capabilities"]
            for target_record in capability["targets"]
            if target_record["script"] == target
            for symbol in target_record["symbols"]
        }
    )
    exercises = []
    for symbol in source_symbols:
        if "." in symbol:
            class_name, method_name = symbol.split(".", 1)
            exercises.append(f"    target.{class_name}().{method_name}()")
        else:
            exercises.append(f"    target.{symbol}()")
    lines = [
        "import pytest",
        f"from scripts import {module} as target",
        "",
        "def _exercise():",
        *exercises,
        "",
    ]
    grouped: dict[str, list[tuple[str, str | None]]] = {}
    for nodeid in _required_nodeids(manifest, target, runner):
        name = nodeid.split("::", 1)[1]
        parameter_start = name.find("[")
        if parameter_start == -1:
            grouped.setdefault(name, []).append((nodeid, None))
        else:
            grouped.setdefault(name[:parameter_start], []).append(
                (nodeid, name[parameter_start + 1 : -1])
            )
    for function_name, cases in sorted(grouped.items()):
        if cases[0][1] is None:
            nodeid = cases[0][0]
            if nodeid == selected_nodeid:
                strict = selected_behavior == "strict-xpass"
                lines.append(
                    f'@pytest.mark.xfail(reason="b3e controlled", strict={strict!r})'
                )
            lines.append(f"def {function_name}():")
            lines.append("    _exercise()")
            if nodeid == selected_nodeid and selected_behavior == "xfail":
                lines.append('    pytest.fail("b3e controlled xfail")')
            lines.append("")
            continue
        parameters = []
        for nodeid, parameter_id in cases:
            assert parameter_id is not None
            marks = ""
            if nodeid == selected_nodeid:
                strict = selected_behavior == "strict-xpass"
                marks = (
                    ", marks=pytest.mark.xfail("
                    f'reason="b3e controlled", strict={strict!r})'
                )
            parameters.append(
                f"pytest.param({parameter_id!r}, id={parameter_id!r}{marks})"
            )
        lines.append('@pytest.mark.parametrize("_case", [' + ", ".join(parameters) + "])")
        lines.append(f"def {function_name}(_case):")
        lines.append("    _exercise()")
        if selected_behavior == "xfail" and any(
            nodeid == selected_nodeid for nodeid, _ in cases
        ):
            selected_id = next(
                parameter_id
                for nodeid, parameter_id in cases
                if nodeid == selected_nodeid
            )
            lines.extend(
                [
                    f"    if _case == {selected_id!r}:",
                    '        pytest.fail("b3e controlled xfail")',
                ]
            )
        lines.append("")
    return "\n".join(lines)


def _b3e_real_runner_repository(
    root: Path,
    *,
    selected_behavior: str | None = None,
    selected_nodeid: str | None = None,
    implementation_failure: str | None = None,
) -> tuple[Path, str, str | None]:
    repository = root / "repository"
    copied_paths = (
        "pyproject.toml",
        "uv.lock",
        "packaging/security-coverage-policy.toml",
        "packaging/security-coverage-manifest.json",
        "scripts/run_security_coverage.sh",
        "scripts/verify_security_coverage.py",
        "scripts/security_pytest_bootstrap.py",
        "scripts/pytest_security_events.py",
    )
    for relative in copied_paths:
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative, destination)
    (repository / ".venv").symlink_to(REPOSITORY_ROOT / ".venv", target_is_directory=True)

    policy = load_policy()
    manifest = load_manifest(policy=policy)
    runner = "macos" if sys.platform == "darwin" else "linux"
    if selected_behavior is not None:
        assert selected_nodeid in _required_nodeids(manifest, "capture", runner)
    else:
        assert selected_nodeid is None
    for target in ("capture", "retention"):
        source = repository / policy["scripts"][target]["path"]
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(_b3e_minimal_source(manifest, target), encoding="utf-8")
        test_file = repository / policy["scripts"][target]["test_file"]
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(
            _b3e_minimal_tests(
                manifest,
                target=target,
                runner=runner,
                selected_nodeid=selected_nodeid if target == "capture" else None,
                selected_behavior=selected_behavior if target == "capture" else None,
            ),
            encoding="utf-8",
        )

    if implementation_failure == "plugin-import":
        plugin = repository / "scripts/pytest_security_events.py"
        plugin.write_text(
            plugin.read_text(encoding="utf-8")
            + (
                "\nimport sys\n"
                'if "--security-target=capture" in sys.argv:\n'
                '    raise ImportError("controlled local plugin import failure")\n'
            ),
            encoding="utf-8",
        )
    elif implementation_failure == "identity-write":
        bootstrap = repository / "scripts/security_pytest_bootstrap.py"
        content = bootstrap.read_text(encoding="utf-8")
        old = (
            "        output, pytest_arguments = _arguments("
            "sys.argv[1:] if argv is None else argv)"
        )
        assert content.count(old) == 1
        bootstrap.write_text(
            content.replace(
                old,
                (
                    old
                    + "\n"
                    + '        if output.parent.name == "capture":\n'
                    + '            output.write_bytes(b"preserved identity marker\\n")\n'
                    + "            output.chmod(0o600)"
                ),
            ),
            encoding="utf-8",
        )
    elif implementation_failure in {"sessionfinish", "events-write"}:
        plugin = repository / "scripts/pytest_security_events.py"
        content = plugin.read_text(encoding="utf-8")
        if implementation_failure == "sessionfinish":
            old = (
                "    del exitstatus\n"
                "    state: dict[str, Any] = getattr(session.config, _STATE_ATTRIBUTE)\n"
            )
            new = (
                "    del exitstatus\n"
                "    state: dict[str, Any] = getattr(session.config, _STATE_ATTRIBUTE)\n"
                '    if state["target"] == "capture":\n'
                '        raise OSError("controlled sessionfinish failure")\n'
            )
        else:
            old = '    _atomic_write(state["output"], content)'
            new = (
                '    if state["target"] == "capture":\n'
                '        raise OSError("controlled events write failure")\n'
                '    _atomic_write(state["output"], content)'
            )
        assert content.count(old) == 1
        plugin.write_text(content.replace(old, new), encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=S18 Test",
            "-c",
            "user.email=s18@example.invalid",
            "commit",
            "-qm",
            "b3e real pytest fixture",
        ],
        cwd=repository,
        check=True,
    )
    return repository, runner, selected_nodeid


def _run_b3e_real_runner(
    tmp_path: Path,
    *,
    scenario_id: str,
    selected_behavior: str | None = None,
    implementation_failure: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, str | None]:
    scenario = _b3e_scenario(scenario_id)
    repository, _, selected_nodeid = _b3e_real_runner_repository(
        tmp_path,
        selected_behavior=selected_behavior,
        selected_nodeid=scenario["victim_nodeid"],
        implementation_failure=implementation_failure,
    )
    attempt = tmp_path / "attempt-001"
    result = subprocess.run(
        [
            os.fspath(repository / "scripts/run_security_coverage.sh"),
            os.fspath(attempt),
            "s18-b3e-real-pytest",
            "1",
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, attempt, selected_nodeid


@pytest.mark.parametrize(
    ("scenario_id", "behavior", "pytest_exit_code", "expected_failures"),
    [pytest.param(*case, id=case[0]) for case in B3E_XFAIL_CASES],
    ids=tuple(case[0] for case in B3E_XFAIL_CASES),
)
def test_s18_real_runner_enforces_required_xfail_and_xpass(
    tmp_path, scenario_id, behavior, pytest_exit_code, expected_failures
):
    scenario = _b3e_scenario(scenario_id)
    result, attempt, selected_nodeid = _run_b3e_real_runner(
        tmp_path,
        scenario_id=scenario_id,
        selected_behavior=behavior,
    )

    assert result.returncode == scenario["expected_outer_exit"]
    assert result.stdout == ""
    assert result.stderr == ""
    capture = attempt / "capture"
    command = json.loads((capture / "command.json").read_text(encoding="utf-8"))
    gate = json.loads((capture / "gate.json").read_text(encoding="utf-8"))
    assert scenario["expected_pytest_exit"] == command["exit_code"] == pytest_exit_code
    assert scenario["expected_gate_failures"] == gate["failures"] == expected_failures
    assert scenario["expected_sentinel_state"] == "not-applicable"
    assert scenario["victim_nodeid"] == selected_nodeid
    _assert_b3e_artifact_contract(capture, scenario)
    assert {
        ".coverage-capture",
        "coverage.json",
        "junit.xml",
        "pytest-events.json",
        "plugin-identity.json",
        "environment.json",
        "command.json",
        "run-manifest.json",
        "gate.json",
        "stdout.log",
        "stderr.log",
        "verifier.stderr.log",
    } <= {path.name for path in capture.iterdir()}
    required = {item["nodeid"]: item for item in gate["junit"]["required_tests"]}
    assert required[selected_nodeid]["status"] == "xfail"
    events = json.loads((capture / "pytest-events.json").read_text(encoding="utf-8"))
    selected = next(case for case in events["cases"] if case["nodeid"] == selected_nodeid)
    assert selected["xfail_marked"] is True
    assert selected["phases"]["call"] == {
        "xfail": {"outcome": "skipped", "wasxfail": True},
        "non-strict-xpass": {"outcome": "passed", "wasxfail": True},
        "strict-xpass": {"outcome": "failed", "wasxfail": False},
    }[behavior]
    assert json.loads((attempt / "retention/gate.json").read_text(encoding="utf-8"))[
        "passed"
    ] is True


@pytest.mark.parametrize(
    ("scenario_id", "failure", "pytest_exit_code", "stderr_marker"),
    [pytest.param(*case, id=case[0]) for case in B3E_BOOTSTRAP_FAILURE_CASES],
    ids=tuple(case[0] for case in B3E_BOOTSTRAP_FAILURE_CASES),
)
def test_s18_real_runner_retains_raw_when_bootstrap_cannot_produce_identity(
    tmp_path, scenario_id, failure, pytest_exit_code, stderr_marker
):
    scenario = _b3e_scenario(scenario_id)
    result, attempt, _ = _run_b3e_real_runner(
        tmp_path,
        scenario_id=scenario_id,
        implementation_failure=failure,
    )

    assert result.returncode == scenario["expected_outer_exit"]
    assert result.stdout == ""
    assert result.stderr == ""
    capture = attempt / "capture"
    _assert_b3e_artifact_contract(capture, scenario)
    assert {
        "stdout.log",
        "stderr.log",
        "environment.json",
        "command.json",
        "runner-error.json",
    } <= {path.name for path in capture.iterdir()}
    if failure == "identity-write":
        identity = capture / "plugin-identity.json"
        assert identity.read_bytes() == b"preserved identity marker\n"
        assert stat.S_IMODE(identity.stat().st_mode) == 0o600
        assert scenario["expected_sentinel_state"] == (
            "identity-marker-preserved-mode-0600"
        )
    else:
        assert not (capture / "plugin-identity.json").exists()
        assert scenario["expected_sentinel_state"] == "not-applicable"
    assert not (capture / "gate.json").exists()
    error = json.loads((capture / "runner-error.json").read_text(encoding="utf-8"))
    command = json.loads((capture / "command.json").read_text(encoding="utf-8"))
    assert set(error) == {
        "schema_version",
        "run_id",
        "target",
        "runner",
        "attempt",
        "stage",
        "reason_code",
        "pytest_exit_code",
        "environment_exit_code",
        "command_exit_code",
        "qualification",
        "present_artifacts",
        "missing_artifacts",
        "present_hashes",
    }
    assert error["schema_version"] == 2
    assert error["stage"] == "raw-completeness"
    assert error["reason_code"] == "REQUIRED_RAW_ARTIFACT_MISSING"
    assert error["qualification"] == "INCOMPLETE_RAW_EVIDENCE"
    assert (
        scenario["expected_pytest_exit"]
        == error["pytest_exit_code"]
        == command["exit_code"]
        == pytest_exit_code
    )
    known_raw = {
        ".coverage-capture",
        "coverage.json",
        "junit.xml",
        "pytest-events.json",
        "plugin-identity.json",
        "environment.json",
        "command.json",
        "stdout.log",
        "stderr.log",
    }
    present_raw = {path.name for path in capture.iterdir()} - {"runner-error.json"}
    assert error["present_artifacts"] == sorted(present_raw)
    assert error["missing_artifacts"] == sorted(known_raw - present_raw)
    assert error["present_hashes"] == {
        name: _sha256(capture / name) for name in sorted(present_raw)
    }
    assert scenario["expected_gate_failures"] == []
    assert scenario["victim_nodeid"] is None
    assert stderr_marker in (capture / "stderr.log").read_text(encoding="utf-8")
    retention_gate = json.loads((attempt / "retention/gate.json").read_text(encoding="utf-8"))
    assert retention_gate["passed"] is True
    assert retention_gate["failures"] == []


@pytest.mark.parametrize(
    ("scenario_id", "failure"),
    [pytest.param(*case, id=case[0]) for case in B3E_EVENTS_FAILURE_CASES],
    ids=tuple(case[0] for case in B3E_EVENTS_FAILURE_CASES),
)
def test_s18_real_runner_fails_closed_when_events_are_not_published(
    tmp_path, scenario_id, failure
):
    scenario = _b3e_scenario(scenario_id)
    result, attempt, _ = _run_b3e_real_runner(
        tmp_path,
        scenario_id=scenario_id,
        implementation_failure=failure,
    )

    assert result.returncode == scenario["expected_outer_exit"]
    assert result.stdout == ""
    assert result.stderr == ""
    capture = attempt / "capture"
    command = json.loads((capture / "command.json").read_text(encoding="utf-8"))
    gate = json.loads((capture / "gate.json").read_text(encoding="utf-8"))
    assert scenario["expected_pytest_exit"] == command["exit_code"] == 2
    assert scenario["expected_gate_failures"] == gate["failures"] == [
        "COMMAND_FAILED",
        "PYTEST_EVENTS_INVALID",
    ]
    assert scenario["victim_nodeid"] is None
    _assert_b3e_artifact_contract(capture, scenario)
    assert (capture / "plugin-identity.json").is_file()
    assert not (capture / "pytest-events.json").exists()
    retention_gate = json.loads((attempt / "retention/gate.json").read_text(encoding="utf-8"))
    assert retention_gate["passed"] is True
    assert retention_gate["failures"] == []


def test_b3e_s_real_runner_parameter_ids_are_explicit_and_stable():
    functions = (
        test_s18_real_runner_enforces_required_xfail_and_xpass,
        test_s18_real_runner_retains_raw_when_bootstrap_cannot_produce_identity,
        test_s18_real_runner_fails_closed_when_events_are_not_published,
    )
    parameter_ids: list[str] = []
    for function in functions:
        marks = [mark for mark in function.pytestmark if mark.name == "parametrize"]
        assert len(marks) == 1
        assert "ids" in marks[0].kwargs
        ids = tuple(marks[0].kwargs["ids"])
        assert tuple(parameter.id for parameter in marks[0].args[1]) == ids
        parameter_ids.extend(ids)

    assert tuple(parameter_ids) == B3E_IMPLEMENTED_SCENARIO_IDS


def test_b3e_s_real_runner_collects_exact_stable_scenario_nodeids():
    test_file = "tests/contract/test_security_coverage_gate.py"
    test_names = (
        "test_s18_real_runner_enforces_required_xfail_and_xpass",
        "test_s18_real_runner_retains_raw_when_bootstrap_cannot_produce_identity",
        "test_s18_real_runner_fails_closed_when_events_are_not_published",
    )
    environment = os.environ.copy()
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "--noconftest",
            "-c",
            "pyproject.toml",
            *(f"{test_file}::{test_name}" for test_name in test_names),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    collected = {
        line
        for line in result.stdout.splitlines()
        if line.startswith(f"{test_file}::")
    }
    expected = {
        f"{test_file}::{test_names[0]}[{scenario_id}]"
        for scenario_id in B3E_IMPLEMENTED_SCENARIO_IDS[:3]
    }
    expected.update(
        {
            f"{test_file}::{test_names[1]}[{scenario_id}]"
            for scenario_id in B3E_IMPLEMENTED_SCENARIO_IDS[3:5]
        }
    )
    expected.update(
        {
            f"{test_file}::{test_names[2]}[{scenario_id}]"
            for scenario_id in B3E_IMPLEMENTED_SCENARIO_IDS[5:]
        }
    )
    assert collected == expected


def _b3f_file_state(path: Path) -> dict[str, object] | str:
    if not path.exists():
        return "absent"
    value = path.stat()
    return {
        "dev": value.st_dev,
        "ino": value.st_ino,
        "mode": stat.S_IMODE(value.st_mode),
        "nlink": value.st_nlink,
        "size": value.st_size,
        "sha256": _sha256(path),
    }


def _b3f_lstat_regular_state(path: Path) -> dict[str, object] | str:
    try:
        value = path.lstat()
    except FileNotFoundError:
        return "absent"
    assert stat.S_ISREG(value.st_mode)
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        assert (opened.st_dev, opened.st_ino) == (value.st_dev, value.st_ino)
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    finally:
        os.close(descriptor)
    assert size == value.st_size
    return {
        "dev": value.st_dev,
        "ino": value.st_ino,
        "mode": stat.S_IMODE(value.st_mode),
        "nlink": value.st_nlink,
        "size": value.st_size,
        "sha256": digest.hexdigest(),
    }


def _b3f_append_case_fillers(
    repository: Path, *, target: str, runner: str, total_cases: int
) -> Path:
    policy = load_policy()
    manifest = load_manifest(policy=policy)
    existing_cases = len(_required_nodeids(manifest, target, runner))
    assert 0 < existing_cases < total_cases
    filler_cases = total_cases - existing_cases
    test_file = repository / policy["scripts"][target]["test_file"]
    with test_file.open("a", encoding="utf-8") as stream:
        stream.write(
            "\n@pytest.mark.parametrize(\n"
            '    "_b3f_case",\n'
            f"    range({filler_cases}),\n"
            '    ids=lambda value: f"b3f{value:04d}",\n'
            ")\n"
            "def test_b3f_case_filler(_b3f_case):\n"
            "    del _b3f_case\n"
            "    _exercise()\n"
        )
    return test_file


def _b3f_append_nodeid_fixture(
    repository: Path,
    *,
    target: str,
    runner: str,
    fault: str,
) -> tuple[Path, dict[str, object]]:
    policy = load_policy()
    test_file_relative = policy["scripts"][target]["test_file"]
    test_file = repository / test_file_relative
    function_name = "test_b3f_nodeid_fixture"
    desired_bytes = 4096 if fault == "nodeid-boundary" else 4097
    prefix = f"{test_file_relative}::{function_name}["
    suffix = "]"
    payload_bytes = desired_bytes - len((prefix + suffix).encode("utf-8"))
    assert payload_bytes > 0
    if fault == "nodeid-plus-one-multibyte":
        decomposed = "e\N{COMBINING ACUTE ACCENT}"
        repetitions, remainder = divmod(payload_bytes, len(decomposed.encode("utf-8")))
        payload = decomposed * repetitions + "a" * remainder
    elif fault in {"nodeid-boundary", "nodeid-plus-one-ascii"}:
        payload = "a" * payload_bytes
    else:
        raise AssertionError(f"unsupported B3f nodeid fixture fault: {fault}")
    assert "[" not in payload and "]" not in payload
    assert all(ord(character) >= 32 and ord(character) != 127 for character in payload)
    expected_nodeid = prefix + payload + suffix
    expected_bytes = expected_nodeid.encode("utf-8", "strict")
    assert len(expected_bytes) == desired_bytes
    if fault == "nodeid-plus-one-multibyte":
        assert len(expected_nodeid) < desired_bytes
        assert expected_nodeid != unicodedata.normalize("NFC", expected_nodeid)
        assert expected_bytes != unicodedata.normalize(
            "NFC", expected_nodeid
        ).encode("utf-8", "strict")
    else:
        assert len(expected_nodeid) == desired_bytes
        assert expected_nodeid.isascii()
    assert security_events_plugin._canonical_nodeid(
        expected_nodeid, test_file_relative
    )
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "UV_PROJECT_ENVIRONMENT",
        "UV_PYTHON",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
    ):
        environment.pop(name, None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    def collect_nodeids() -> tuple[str, ...]:
        collection = subprocess.run(
            [
                "uv",
                "run",
                "--offline",
                "--frozen",
                "--no-sync",
                "python",
                "-B",
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                "--noconftest",
                "-c",
                "pyproject.toml",
                test_file_relative,
            ],
            cwd=repository,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert collection.returncode == 0, collection.stdout + collection.stderr
        return tuple(
            line
            for line in collection.stdout.splitlines()
            if line.startswith(test_file_relative + "::")
        )

    baseline_nodeids = collect_nodeids()
    with test_file.open("a", encoding="utf-8") as stream:
        stream.write(
            "\ndef _b3f_nodeid_fixture():\n"
            "    _exercise()\n\n\n"
            f"globals()[{function_name + '[' + payload + ']'!r}] = "
            "_b3f_nodeid_fixture\n"
            "del _b3f_nodeid_fixture\n"
        )
    collected_nodeids = collect_nodeids()
    assert len(collected_nodeids) == len(baseline_nodeids) + 1
    assert set(collected_nodeids) - set(baseline_nodeids) == {expected_nodeid}
    assert collected_nodeids.count(expected_nodeid) == 1
    assert collected_nodeids[-1] == expected_nodeid
    assert len(collected_nodeids) < policy["limits"]["testcases"]
    empty_document = {
        "schema_version": 3,
        "run_id": "s18-b3f-real-pytest",
        "target": target,
        "runner": runner,
        "attempt": 1,
        "test_file": test_file_relative,
        "limits": {
            "testcases": policy["limits"]["testcases"],
            "pytest_events_nodeid_bytes": policy["limits"][
                "pytest_events_nodeid_bytes"
            ],
            "pytest_events_bytes": policy["limits"]["pytest_events_bytes"],
        },
        "cases": [],
    }
    serialized_upper_bound = (
        len(security_events_plugin._canonical_json_bytes(empty_document)) + 1
    )
    for index, nodeid in enumerate(collected_nodeids):
        serialized_upper_bound += max(
            len(
                security_events_plugin._worst_case_bytes(
                    nodeid, xfail_marked=xfail_marked
                )
            )
            for xfail_marked in (False, True)
        )
        if index:
            serialized_upper_bound += 1
    assert serialized_upper_bound < policy["limits"]["pytest_events_bytes"]
    return test_file, {
        "schema_version": 1,
        "fault": fault,
        "target": target,
        "test_file": test_file_relative,
        "nodeid": expected_nodeid,
        "python_characters": len(expected_nodeid),
        "utf8_bytes": len(expected_bytes),
        "utf8_sha256": hashlib.sha256(expected_bytes).hexdigest(),
        "nfc_equal": expected_nodeid == unicodedata.normalize("NFC", expected_nodeid),
        "canonical_grammar": True,
        "collected_exactly_once": True,
        "baseline_case_count": len(baseline_nodeids),
        "collected_last": True,
        "case_count": len(collected_nodeids),
        "case_limit": policy["limits"]["testcases"],
        "serialized_upper_bound": serialized_upper_bound,
        "serialized_limit": policy["limits"]["pytest_events_bytes"],
    }


def _b3f_independent_compact_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8", "strict")


def _b3f_passing_case(nodeid: str, *, outcome: str = "passed") -> dict[str, object]:
    return {
        "nodeid": nodeid,
        "xfail_marked": False,
        "phases": {
            phase: {"outcome": outcome, "wasxfail": False}
            for phase in ("setup", "call", "teardown")
        },
    }


def _b3f_independent_document_bytes(
    metadata: dict[str, object], nodeids: tuple[str, ...]
) -> tuple[bytes, int]:
    empty = dict(metadata)
    empty["cases"] = []
    empty_size = len(_b3f_independent_compact_json_bytes(empty)) + 1
    cases = tuple(_b3f_passing_case(nodeid) for nodeid in sorted(nodeids))
    calculated_size = empty_size + sum(
        len(_b3f_independent_compact_json_bytes(case)) for case in cases
    ) + max(0, len(cases) - 1)
    document = dict(metadata)
    document["cases"] = list(cases)
    content = _b3f_independent_compact_json_bytes(document) + b"\n"
    assert len(content) == calculated_size
    return content, calculated_size


def _b3f_append_serialized_fixture(
    repository: Path,
    *,
    target: str,
    runner: str,
    fault: str,
) -> tuple[Path, dict[str, object]]:
    policy = load_policy()
    test_file_relative = policy["scripts"][target]["test_file"]
    test_file = repository / test_file_relative
    desired_bytes = 8388608 if fault == "serialized-boundary" else 8388609
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "UV_PROJECT_ENVIRONMENT",
        "UV_PYTHON",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
    ):
        environment.pop(name, None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    def collect_nodeids() -> tuple[str, ...]:
        collection = subprocess.run(
            [
                "uv",
                "run",
                "--offline",
                "--frozen",
                "--no-sync",
                "python",
                "-B",
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                "--noconftest",
                "-c",
                "pyproject.toml",
                test_file_relative,
            ],
            cwd=repository,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert collection.returncode == 0, collection.stdout + collection.stderr
        return tuple(
            line
            for line in collection.stdout.splitlines()
            if line.startswith(test_file_relative + "::")
        )

    metadata = {
        "schema_version": 3,
        "run_id": "s18-b3f-real-pytest",
        "target": target,
        "runner": runner,
        "attempt": 1,
        "test_file": test_file_relative,
        "limits": {
            "testcases": policy["limits"]["testcases"],
            "pytest_events_nodeid_bytes": policy["limits"][
                "pytest_events_nodeid_bytes"
            ],
            "pytest_events_bytes": policy["limits"]["pytest_events_bytes"],
        },
    }
    baseline_nodeids = collect_nodeids()
    baseline_content, baseline_size = _b3f_independent_document_bytes(
        metadata, baseline_nodeids
    )
    del baseline_content
    maximum_nodeid_bytes = policy["limits"]["pytest_events_nodeid_bytes"]

    def generated_nodeid(index: int, nodeid_bytes: int) -> str:
        prefix = f"{test_file_relative}::test_b3f_serialized_{index:04d}["
        suffix = "]"
        payload_bytes = nodeid_bytes - len((prefix + suffix).encode("utf-8"))
        assert payload_bytes >= 0
        return prefix + "a" * payload_bytes + suffix

    def case_delta(index: int, nodeid_bytes: int) -> int:
        nodeid = generated_nodeid(index, nodeid_bytes)
        return len(_b3f_independent_compact_json_bytes(_b3f_passing_case(nodeid))) + 1

    minimum_nodeid_bytes = len(
        f"{test_file_relative}::test_b3f_serialized_0000[]".encode()
    )
    maximum_delta = case_delta(0, maximum_nodeid_bytes)
    minimum_delta = case_delta(0, minimum_nodeid_bytes)
    assert maximum_delta - minimum_delta == (
        maximum_nodeid_bytes - minimum_nodeid_bytes
    )
    remaining = desired_bytes - baseline_size
    assert remaining > maximum_delta
    full_length_count, tail_delta = divmod(remaining, maximum_delta)
    tail_lengths: list[int] = []
    if tail_delta:
        if tail_delta >= minimum_delta:
            tail_lengths.append(minimum_nodeid_bytes + tail_delta - minimum_delta)
        else:
            assert full_length_count > 0
            full_length_count -= 1
            tail_lengths.extend(
                [
                    maximum_nodeid_bytes - (minimum_delta - tail_delta),
                    minimum_nodeid_bytes,
                ]
            )
    nodeid_lengths = (maximum_nodeid_bytes,) * full_length_count + tuple(tail_lengths)
    generated_nodeids = tuple(
        generated_nodeid(index, nodeid_bytes)
        for index, nodeid_bytes in enumerate(nodeid_lengths)
    )
    assert len(baseline_nodeids) + len(generated_nodeids) < policy["limits"][
        "testcases"
    ]
    assert all(
        len(nodeid.encode("utf-8", "strict")) <= maximum_nodeid_bytes
        and security_events_plugin._canonical_nodeid(nodeid, test_file_relative)
        for nodeid in generated_nodeids
    )
    all_nodeids = baseline_nodeids + generated_nodeids
    expected_content, calculated_size = _b3f_independent_document_bytes(
        metadata, all_nodeids
    )
    assert calculated_size == desired_bytes
    source_append = (
        "\ndef _b3f_serialized_fixture():\n"
        "    _exercise()\n\n\n"
        f"_B3F_SERIALIZED_NODEID_LENGTHS = {nodeid_lengths!r}\n"
        "for _b3f_index, _b3f_nodeid_bytes in enumerate(\n"
        "    _B3F_SERIALIZED_NODEID_LENGTHS\n"
        "):\n"
        '    _b3f_name = f"test_b3f_serialized_{_b3f_index:04d}"\n'
        '    _b3f_prefix = f"{_b3f_name}["\n'
        "    _b3f_payload_bytes = _b3f_nodeid_bytes - len(\n"
        f"        ({test_file_relative!r} + \"::\" + _b3f_prefix + \"]\").encode(\n"
        '            "utf-8"\n'
        "        )\n"
        "    )\n"
        "    globals()[_b3f_prefix + \"a\" * _b3f_payload_bytes + \"]\"] = (\n"
        "        _b3f_serialized_fixture\n"
        "    )\n"
        "del _b3f_serialized_fixture\n"
        "del _b3f_index, _b3f_name, _b3f_nodeid_bytes, _b3f_payload_bytes, _b3f_prefix\n"
    )
    with test_file.open("a", encoding="utf-8") as stream:
        stream.write(source_append)
    collected_nodeids = collect_nodeids()
    assert len(collected_nodeids) == len(all_nodeids)
    assert set(collected_nodeids) - set(baseline_nodeids) == set(generated_nodeids)
    assert set(baseline_nodeids) <= set(collected_nodeids)
    independent_content, observed_calculated_size = _b3f_independent_document_bytes(
        metadata, collected_nodeids
    )
    assert independent_content == expected_content
    assert observed_calculated_size == desired_bytes
    skipped_case_size = sum(
        len(
            _b3f_independent_compact_json_bytes(
                _b3f_passing_case(nodeid, outcome="skipped")
            )
        )
        for nodeid in sorted(collected_nodeids)
    )
    empty = dict(metadata)
    empty["cases"] = []
    collection_upper_bound = (
        len(_b3f_independent_compact_json_bytes(empty))
        + 1
        + skipped_case_size
        + len(collected_nodeids)
        - 1
    )
    assert collection_upper_bound > policy["limits"]["pytest_events_bytes"]
    generated_nodeids_bytes = "\n".join(generated_nodeids).encode("utf-8", "strict")
    return test_file, {
        "schema_version": 1,
        "calculator": "independent-json-dumps-explicit-compact-v1",
        "generator": "dynamic-global-ascii-nodeids-v1",
        "fault": fault,
        "target": target,
        "test_file": test_file_relative,
        "desired_bytes": desired_bytes,
        "calculated_bytes": calculated_size,
        "expected_content_sha256": hashlib.sha256(expected_content).hexdigest(),
        "baseline_case_count": len(baseline_nodeids),
        "generated_case_count": len(generated_nodeids),
        "case_count": len(collected_nodeids),
        "case_limit": policy["limits"]["testcases"],
        "maximum_nodeid_bytes": maximum_nodeid_bytes,
        "maximum_nodeid_count": full_length_count,
        "tail_nodeid_bytes": tail_lengths,
        "nodeid_lengths_sha256": hashlib.sha256(
            json.dumps(nodeid_lengths, separators=(",", ":")).encode("ascii")
        ).hexdigest(),
        "generated_nodeids_sha256": hashlib.sha256(generated_nodeids_bytes).hexdigest(),
        "collection_upper_bound": collection_upper_bound,
        "events_limit": policy["limits"]["pytest_events_bytes"],
        "source_append_sha256": hashlib.sha256(source_append.encode("utf-8")).hexdigest(),
    }


def _b3f_mutate_collection_budget(
    repository: Path, *, target: str, exact_ceiling: int
) -> Path:
    plugin = repository / "scripts/pytest_security_events.py"
    content = plugin.read_text(encoding="utf-8")
    old = (
        "        if (\n"
        '            state["serialized_upper_bound"] + addition\n'
        '            > state["limits"]["pytest_events_bytes"]\n'
        "        ):\n"
    )
    new = (
        "        b3f_collection_ceiling = (\n"
        f"            {exact_ceiling}\n"
        f'            if state["target"] == {target!r}\n'
        '            else state["limits"]["pytest_events_bytes"]\n'
        "        )\n"
        "        if (\n"
        '            state["serialized_upper_bound"] + addition\n'
        "            > b3f_collection_ceiling\n"
        "        ):\n"
    )
    assert content.count(old) == 1
    plugin.write_text(content.replace(old, new), encoding="utf-8")
    return plugin


def _b3f_configure_argv_recipe(fault: str) -> dict[str, object]:
    invalid_values = {
        "invalid-limit-zero": "0",
        "invalid-limit-negative": "-1",
        "invalid-limit-nondecimal": "abc",
        "invalid-limit-nonascii": "１２",  # noqa: RUF001 - intentional invalid argv
        "invalid-limit-excessive-digits": "9" * 5000,
        "invalid-limit-over-ceiling": "4097",
    }
    duplicate_options = {
        "duplicate-max-cases": ("--security-max-cases", "4096"),
        "duplicate-max-nodeid-bytes": ("--security-max-nodeid-bytes", "4096"),
        "duplicate-max-events-bytes": ("--security-max-events-bytes", "8388608"),
    }
    if fault in invalid_values:
        return {
            "mode": "replace-one",
            "option": "--security-max-cases",
            "value": invalid_values[fault],
        }
    if fault in duplicate_options:
        option, value = duplicate_options[fault]
        return {"mode": "duplicate-exact", "option": option, "value": value}
    raise AssertionError(f"unsupported B3f configure fault: {fault}")


def _b3f_mutate_runner_argv(repository: Path, *, target: str, fault: str) -> Path:
    runner = repository / "scripts/run_security_coverage.sh"
    content = runner.read_text(encoding="utf-8")
    recipe = _b3f_configure_argv_recipe(fault)
    marker = "    --cov-fail-under=80\n  )\n  (\n"
    assert content.count(marker) == 1
    option = str(recipe["option"])
    if recipe["mode"] == "replace-one":
        replacement = option + "=" + str(recipe["value"])
        mutation = (
            f'  if [ "$target" = {target!r} ]; then\n'
            "    for ((b3f_index=0; b3f_index<${#command[@]}; b3f_index++)); do\n"
            f'      case "${{command[$b3f_index]}}" in\n        {option}=*)\n'
            f"          command[$b3f_index]={replacement!r}\n"
            "          ;;\n"
            "      esac\n"
            "    done\n"
            "  fi\n"
        )
    else:
        mutation = (
            f'  if [ "$target" = {target!r} ]; then\n'
            "    b3f_command=()\n"
            '    for b3f_argument in "${command[@]}"; do\n'
            '      b3f_command+=("$b3f_argument")\n'
            f'      case "$b3f_argument" in\n        {option}=*)\n'
            '          b3f_command+=("$b3f_argument")\n'
            "          ;;\n"
            "      esac\n"
            "    done\n"
            '    command=("${b3f_command[@]}")\n'
            "  fi\n"
        )
    content = content.replace(marker, marker.removesuffix("  (\n") + mutation + "  (\n")
    runner.write_text(content, encoding="utf-8")
    subprocess.run(["bash", "-n", runner], check=True)
    return runner


def _b3f_argv_option_tokens(argv: object, option: str) -> list[str]:
    assert isinstance(argv, list)
    assert all(isinstance(argument, str) for argument in argv)
    return [
        argument
        for argument in argv
        if argument == option or argument.startswith(option + "=")
    ]


def _assert_b3f_configure_argv(
    target_command: dict[str, object],
    control_command: dict[str, object],
    fault: str,
) -> None:
    canonical = {
        "--security-max-cases": "4096",
        "--security-max-nodeid-bytes": "4096",
        "--security-max-events-bytes": "8388608",
    }
    recipe = _b3f_configure_argv_recipe(fault)
    mutated_option = str(recipe["option"])
    mutated_token = mutated_option + "=" + str(recipe["value"])
    for option, value in canonical.items():
        canonical_token = option + "=" + value
        expected_target = [canonical_token]
        if option == mutated_option:
            expected_target = (
                [mutated_token]
                if recipe["mode"] == "replace-one"
                else [canonical_token, canonical_token]
            )
        assert _b3f_argv_option_tokens(target_command["argv"], option) == expected_target
        assert _b3f_argv_option_tokens(control_command["argv"], option) == [
            canonical_token
        ]
    if fault == "invalid-limit-excessive-digits":
        assert len(mutated_token.removeprefix(mutated_option + "=")) == 5000
        assert mutated_token.removeprefix(mutated_option + "=") == "9" * 5000


def _assert_b3f_canonical_limit_argv(command: dict[str, object]) -> None:
    for option, value in {
        "--security-max-cases": "4096",
        "--security-max-nodeid-bytes": "4096",
        "--security-max-events-bytes": "8388608",
    }.items():
        assert _b3f_argv_option_tokens(command["argv"], option) == [
            option + "=" + value
        ]


def _assert_b3f_batch_d_writer_trace(
    execution: dict[str, object], scenario: dict[str, object]
) -> None:
    receipt = execution["mutation_receipt"]
    fault = str(scenario["fault"])
    target = str(scenario["target"])
    trace_path = execution["writer_trace_path"]
    assert isinstance(trace_path, Path)
    raw = trace_path.read_bytes()
    trace = receipt["writer_trace"]
    assert trace["path"] == os.fspath(trace_path)
    assert trace["sha256"] == hashlib.sha256(raw).hexdigest()
    assert trace["size"] == len(raw) > 0
    entries = trace["parsed_sequence"]
    assert [entry["sequence"] for entry in entries] == list(
        range(1, len(entries) + 1)
    )
    assert {entry["pid"] for entry in entries} == {receipt["child_pid"]}
    assert {entry["output"] for entry in entries} == {receipt["target_output"]}
    assert {entry["temporary"] for entry in entries} == {
        receipt["target_temporary"]
    }
    guard_events = "--security-events=" + receipt["target_output"]
    guard_target = "--security-target=" + target
    assert {entry["guard_events_argv"] for entry in entries} == {guard_events}
    assert {entry["guard_target_argv"] for entry in entries} == {guard_target}
    assert receipt["target_output"] == os.fspath(
        execution["attempt"] / target / "pytest-events.json"
    )
    assert receipt["target_temporary"] == os.fspath(execution["temp_path"])
    assert receipt["runner_deadline_seconds"] == 60
    assert 0 < receipt["runner_elapsed_seconds"] < 60
    assert receipt["writer_fault_injection"] == {
        "fault": fault,
        "target": target,
        "target_output": receipt["target_output"],
        "guard_events_argv": guard_events,
        "guard_target_argv": guard_target,
        "trace_path": os.fspath(trace_path),
        "exact_call_site": _b3f_writer_exact_call_site(fault),
        "injection_position": _b3f_writer_injection_position(fault),
    }
    assert len({entry["content_bytes"] for entry in entries}) == 1
    content_bytes = entries[0]["content_bytes"]
    assert isinstance(content_bytes, int) and content_bytes > 0
    operations = [entry["operation"] for entry in entries]
    statuses = [entry["status"] for entry in entries]
    if fault == "temp-open":
        assert operations == ["TEMP_OPEN"]
        assert statuses == ["error"]
    elif fault == "fchmod":
        assert operations == [
            "TEMP_OPEN",
            "FCHMOD",
            "FILE_CLOSE",
            "CLEANUP_UNLINK",
        ]
        assert statuses == ["ok", "error", "ok", "ok"]
    elif fault == "write-zero":
        assert operations == [
            "TEMP_OPEN",
            "FCHMOD",
            "WRITE",
            "FILE_CLOSE",
            "CLEANUP_UNLINK",
        ]
        assert statuses == ["ok", "ok", "zero", "ok", "ok"]
        writes = [entry for entry in entries if entry["operation"] == "WRITE"]
        assert len(writes) == 1
        assert writes[0]["written_bytes"] == 0
        assert "FILE_FSYNC" not in operations and "LINK" not in operations
    elif fault == "partial-write-success":
        assert operations[:2] == ["TEMP_OPEN", "FCHMOD"]
        assert operations[-7:] == [
            "FILE_FSYNC",
            "FILE_CLOSE",
            "LINK",
            "PUBLISH_UNLINK",
            "DIR_OPEN",
            "DIR_FSYNC",
            "DIR_CLOSE",
        ]
        writes = entries[2:-7]
        assert len(writes) >= 2
        assert all(entry["operation"] == "WRITE" for entry in writes)
        assert all(entry["status"] == "ok" for entry in entries)
        assert writes[0]["written_bytes"] == 1
        assert all(entry["written_bytes"] > 0 for entry in writes)
        assert sum(entry["written_bytes"] for entry in writes) == content_bytes
    elif fault == "write-exception-after-partial":
        assert operations == [
            "TEMP_OPEN",
            "FCHMOD",
            "WRITE",
            "WRITE",
            "FILE_CLOSE",
            "CLEANUP_UNLINK",
        ]
        assert statuses == ["ok", "ok", "ok", "error", "ok", "ok"]
        writes = entries[2:4]
        assert writes[0]["written_bytes"] == 1
        assert writes[1]["injected"] is True
    elif fault == "file-fsync":
        assert operations[:2] == ["TEMP_OPEN", "FCHMOD"]
        assert operations[-3:] == ["FILE_FSYNC", "FILE_CLOSE", "CLEANUP_UNLINK"]
        writes = entries[2:-3]
        assert writes and all(entry["operation"] == "WRITE" for entry in writes)
        assert all(entry["written_bytes"] > 0 for entry in writes)
        assert sum(entry["written_bytes"] for entry in writes) == content_bytes
        assert statuses[-3:] == ["error", "ok", "ok"]
    elif fault == "file-close":
        assert operations[:2] == ["TEMP_OPEN", "FCHMOD"]
        assert operations[-3:] == ["FILE_FSYNC", "FILE_CLOSE", "CLEANUP_UNLINK"]
        writes = entries[2:-3]
        assert writes and all(entry["operation"] == "WRITE" for entry in writes)
        assert all(entry["written_bytes"] > 0 for entry in writes)
        assert sum(entry["written_bytes"] for entry in writes) == content_bytes
        assert statuses[-3:] == ["ok", "error", "ok"]
        assert entries[-2]["injection_position"] == "after-real"
        assert "LINK" not in operations and not any(
            operation.startswith("DIR_") for operation in operations
        )
    else:
        raise AssertionError(f"unsupported Batch D writer trace fault: {fault}")

    injected = [entry for entry in entries if entry["injected"]]
    assert len(injected) == 1
    copied_plugin = execution["repository"] / "scripts/pytest_security_events.py"
    copied_text = copied_plugin.read_text(encoding="utf-8")
    assert copied_text.count(repr(receipt["target_output"])) == 1
    assert "monkeypatch" not in copied_text
    for operation in (
        "TEMP_OPEN",
        "FCHMOD",
        "WRITE",
        "FILE_FSYNC",
        "FILE_CLOSE",
        "LINK",
        "PUBLISH_UNLINK",
        "DIR_OPEN",
        "DIR_FSYNC",
        "DIR_CLOSE",
        "CLEANUP_UNLINK",
    ):
        assert copied_text.count(f'"{operation}"') >= 1


def _assert_b3f_batch_f_writer_trace(
    execution: dict[str, object], scenario: dict[str, object]
) -> None:
    receipt = execution["mutation_receipt"]
    fault = str(scenario["fault"])
    target = str(scenario["target"])
    trace_path = execution["writer_trace_path"]
    assert isinstance(trace_path, Path)
    raw = trace_path.read_bytes()
    trace = receipt["writer_trace"]
    assert trace["path"] == os.fspath(trace_path)
    assert trace["sha256"] == hashlib.sha256(raw).hexdigest()
    assert trace["size"] == len(raw) > 0
    entries = trace["parsed_sequence"]
    assert [entry["sequence"] for entry in entries] == list(
        range(1, len(entries) + 1)
    )
    assert {entry["pid"] for entry in entries} == {receipt["child_pid"]}
    assert {entry["output"] for entry in entries} == {receipt["target_output"]}
    assert {entry["temporary"] for entry in entries} == {
        receipt["target_temporary"]
    }
    guard_events = "--security-events=" + receipt["target_output"]
    guard_target = "--security-target=" + target
    assert {entry["guard_events_argv"] for entry in entries} == {guard_events}
    assert {entry["guard_target_argv"] for entry in entries} == {guard_target}
    assert receipt["target_output"] == os.fspath(
        execution["attempt"] / target / "pytest-events.json"
    )
    assert receipt["target_temporary"] == os.fspath(execution["temp_path"])
    assert receipt["runner_deadline_seconds"] == 60
    assert 0 < receipt["runner_elapsed_seconds"] < 60
    assert receipt["writer_fault_injection"] == {
        "fault": fault,
        "target": target,
        "target_output": receipt["target_output"],
        "guard_events_argv": guard_events,
        "guard_target_argv": guard_target,
        "trace_path": os.fspath(trace_path),
        "exact_call_site": _b3f_writer_exact_call_site(fault),
        "injection_position": _b3f_writer_injection_position(fault),
    }
    assert len({entry["content_bytes"] for entry in entries}) == 1
    content_bytes = entries[0]["content_bytes"]
    assert isinstance(content_bytes, int) and content_bytes > 0
    operations = [entry["operation"] for entry in entries]
    assert operations[:2] == ["TEMP_OPEN", "FCHMOD"]
    assert "CLEANUP_DIR_CLOSE" not in operations
    temp_open = entries[0]
    assert temp_open["status"] == "ok"
    assert temp_open["injected"] is False
    assert temp_open["real_call"] is True
    temp_descriptor = temp_open["result_descriptor"]
    writes = [entry for entry in entries if entry["operation"] == "WRITE"]
    assert writes
    assert all(
        entry["status"] == "ok"
        and entry["injected"] is False
        and entry["real_call"] is True
        and entry["written_bytes"] > 0
        for entry in writes
    )
    assert sum(entry["written_bytes"] for entry in writes) == content_bytes
    file_fsync = [entry for entry in entries if entry["operation"] == "FILE_FSYNC"]
    file_close = [entry for entry in entries if entry["operation"] == "FILE_CLOSE"]
    assert len(file_fsync) == len(file_close) == 1
    assert file_fsync[0]["input_descriptor"] == temp_descriptor
    assert file_close[0]["input_descriptor"] == temp_descriptor
    assert all(
        entry["status"] == "ok"
        and entry["injected"] is False
        and entry["real_call"] is True
        for entry in (file_fsync[0], file_close[0])
    )

    links = [entry for entry in entries if entry["operation"] == "LINK"]
    assert len(links) == 1
    link = links[0]
    assert link["status"] == "ok"
    assert link["injected"] is False
    assert link["real_call"] is True
    final_after_link = link["final_after_link"]
    temp_after_link = link["temporary_after_link"]
    assert final_after_link["mode"] == temp_after_link["mode"] == 0o600
    assert final_after_link["nlink"] == temp_after_link["nlink"] == 2
    assert final_after_link["dev"] == temp_after_link["dev"]
    assert final_after_link["ino"] == temp_after_link["ino"]
    assert final_after_link["size"] == temp_after_link["size"] == content_bytes
    assert final_after_link["sha256"] == temp_after_link["sha256"]
    assert receipt["publication"] == {
        "link_sequence": link["sequence"],
        "link_status": "ok",
        "final_after_link": final_after_link,
        "temp_after_link": temp_after_link,
        "same_inode": True,
    }
    final_after = receipt["final_after"]
    assert final_after["mode"] == 0o600 and final_after["nlink"] == 1
    for field in ("dev", "ino", "size", "sha256"):
        assert final_after[field] == final_after_link[field]
    assert receipt["final_before"] == "absent"
    assert receipt["temp_before"] == receipt["temp_after"] == "absent"

    injected = [entry for entry in entries if entry["injected"]]
    assert len(injected) == 1
    assert injected[0]["operation"] == {
        "temp-unlink-retry": "PUBLISH_UNLINK",
        "directory-fsync": "DIR_FSYNC",
        "directory-close": "DIR_CLOSE",
    }[fault]
    unlink_entries = [
        entry
        for entry in entries
        if entry["operation"] in {"PUBLISH_UNLINK", "CLEANUP_UNLINK"}
    ]
    assert receipt["unlink_attempts"] == [
        {
            "operation": entry["operation"],
            "sequence": entry["sequence"],
            "status": entry["status"],
            "injected": entry["injected"],
            "real_call": entry["real_call"],
            "path": entry["path"],
        }
        for entry in unlink_entries
    ]
    assert {entry["path"] for entry in unlink_entries} == {
        receipt["target_temporary"]
    }

    if fault == "temp-unlink-retry":
        assert operations[-5:] == [
            "FILE_FSYNC",
            "FILE_CLOSE",
            "LINK",
            "PUBLISH_UNLINK",
            "CLEANUP_UNLINK",
        ]
        assert all(operation == "WRITE" for operation in operations[2:-5])
        assert [entry["operation"] for entry in unlink_entries] == [
            "PUBLISH_UNLINK",
            "CLEANUP_UNLINK",
        ]
        publish_unlink, cleanup_unlink = unlink_entries
        assert publish_unlink["status"] == "error"
        assert publish_unlink["injected"] is True
        assert publish_unlink["real_call"] is False
        assert publish_unlink["injection_position"] == "before-real"
        assert cleanup_unlink["status"] == "ok"
        assert cleanup_unlink["injected"] is False
        assert cleanup_unlink["real_call"] is True
        assert not any(operation.startswith("DIR_") for operation in operations)
        assert receipt["directory"] == {
            "open_descriptor": None,
            "fsync_descriptor": None,
            "close_descriptor": None,
            "fsync_real_call": None,
            "close_real_call": None,
            "real_close_completed": None,
        }
    else:
        assert operations[-7:] == [
            "FILE_FSYNC",
            "FILE_CLOSE",
            "LINK",
            "PUBLISH_UNLINK",
            "DIR_OPEN",
            "DIR_FSYNC",
            "DIR_CLOSE",
        ]
        assert all(operation == "WRITE" for operation in operations[2:-7])
        assert [entry["operation"] for entry in unlink_entries] == [
            "PUBLISH_UNLINK"
        ]
        assert unlink_entries[0]["status"] == "ok"
        assert unlink_entries[0]["injected"] is False
        assert unlink_entries[0]["real_call"] is True
        directory_open = entries[-3]
        directory_fsync = entries[-2]
        directory_close = entries[-1]
        directory_descriptor = directory_open["result_descriptor"]
        assert directory_open["status"] == "ok"
        assert directory_open["injected"] is False
        assert directory_open["real_call"] is True
        assert directory_fsync["input_descriptor"] == directory_descriptor
        assert directory_close["input_descriptor"] == directory_descriptor
        assert directory_close["real_close_completed"] is True
        assert receipt["directory"] == {
            "open_descriptor": directory_descriptor,
            "fsync_descriptor": directory_descriptor,
            "close_descriptor": directory_descriptor,
            "fsync_real_call": directory_fsync["real_call"],
            "close_real_call": directory_close["real_call"],
            "real_close_completed": True,
        }
        if fault == "directory-fsync":
            assert directory_fsync["status"] == "error"
            assert directory_fsync["injected"] is True
            assert directory_fsync["real_call"] is False
            assert directory_fsync["injection_position"] == "before-real"
            assert directory_close["status"] == "ok"
            assert directory_close["injected"] is False
            assert directory_close["real_call"] is True
        elif fault == "directory-close":
            assert directory_fsync["status"] == "ok"
            assert directory_fsync["injected"] is False
            assert directory_fsync["real_call"] is True
            assert directory_close["status"] == "error"
            assert directory_close["injected"] is True
            assert directory_close["real_call"] is True
            assert directory_close["injection_position"] == "after-real"
            assert sum(operation == "DIR_CLOSE" for operation in operations) == 1
        else:
            raise AssertionError(f"unsupported Batch F writer trace fault: {fault}")

    copied_plugin = execution["repository"] / "scripts/pytest_security_events.py"
    copied_text = copied_plugin.read_text(encoding="utf-8")
    assert copied_text.count(repr(receipt["target_output"])) == 1
    assert "monkeypatch" not in copied_text
    assert ".parent.name" not in copied_text
    assert "glob(" not in copied_text
    events = json.loads(
        (execution["attempt"] / target / "pytest-events.json").read_text(
            encoding="utf-8"
        )
    )
    assert events["schema_version"] == 3
    assert events["run_id"] == "s18-b3f-real-pytest"
    assert events["target"] == target
    assert events["attempt"] == 1
    assert isinstance(events["cases"], list) and events["cases"]


def _assert_b3f_batch_g_syscall_order_trace(
    execution: dict[str, object], scenario: dict[str, object]
) -> None:
    receipt = execution["mutation_receipt"]
    target = str(scenario["target"])
    assert scenario["fault"] == "syscall-order"
    trace_path = execution["writer_trace_path"]
    assert isinstance(trace_path, Path)
    raw = trace_path.read_bytes()
    trace = receipt["writer_trace"]
    assert trace["path"] == os.fspath(trace_path)
    assert trace["sha256"] == hashlib.sha256(raw).hexdigest()
    assert trace["size"] == len(raw) > 0
    assert raw.endswith(b"\n")
    entries = trace["parsed_sequence"]
    assert [entry["sequence"] for entry in entries] == list(
        range(1, len(entries) + 1)
    )
    assert {entry["pid"] for entry in entries} == {receipt["child_pid"]}
    assert {entry["output"] for entry in entries} == {receipt["target_output"]}
    assert {entry["temporary"] for entry in entries} == {
        receipt["target_temporary"]
    }
    guard_events = "--security-events=" + receipt["target_output"]
    guard_target = "--security-target=" + target
    assert {entry["guard_events_argv"] for entry in entries} == {guard_events}
    assert {entry["guard_target_argv"] for entry in entries} == {guard_target}
    assert Path(receipt["target_output"]).is_absolute()
    assert receipt["target_output"] == os.fspath(
        execution["attempt"] / target / "pytest-events.json"
    )
    assert receipt["target_temporary"] == os.fspath(execution["temp_path"])
    assert receipt["runner_deadline_seconds"] == 60
    assert 0 < receipt["runner_elapsed_seconds"] < 60
    assert receipt["writer_fault_injection"] == {
        "fault": "syscall-order",
        "target": target,
        "target_output": receipt["target_output"],
        "guard_events_argv": guard_events,
        "guard_target_argv": guard_target,
        "trace_path": os.fspath(trace_path),
        "exact_call_site": "atomic-write:record-only-approved-sequence",
        "injection_position": None,
    }
    assert all(
        entry["status"] == "ok"
        and entry["injected"] is False
        and entry["real_call"] is True
        for entry in entries
    )
    assert len({entry["content_bytes"] for entry in entries}) == 1
    content_bytes = entries[0]["content_bytes"]
    assert isinstance(content_bytes, int) and content_bytes > 0
    writes = [entry for entry in entries if entry["operation"] == "WRITE"]
    assert writes
    assert [entry["write_index"] for entry in writes] == list(
        range(1, len(writes) + 1)
    )
    assert all(
        entry["requested_bytes"] == entry["original_requested_bytes"]
        and 0 < entry["written_bytes"] <= entry["requested_bytes"]
        for entry in writes
    )
    assert sum(entry["written_bytes"] for entry in writes) == content_bytes
    operations = [entry["operation"] for entry in entries]
    assert operations == [
        "TEMP_OPEN",
        "FCHMOD",
        *("WRITE" for _entry in writes),
        "FILE_FSYNC",
        "FILE_CLOSE",
        "LINK",
        "PUBLISH_UNLINK",
        "DIR_OPEN",
        "DIR_FSYNC",
        "DIR_CLOSE",
    ]
    assert operations.count("CLEANUP_UNLINK") == 0
    assert operations.count("CLEANUP_DIR_CLOSE") == 0

    temporary = receipt["target_temporary"]
    output = receipt["target_output"]
    temp_open = entries[0]
    temp_flags = temp_open["flags"]
    assert temp_open["path"] == temporary
    assert (temp_flags & os.O_ACCMODE) == os.O_WRONLY
    assert temp_flags & os.O_CREAT == os.O_CREAT
    assert temp_flags & os.O_EXCL == os.O_EXCL
    assert getattr(os, "O_CLOEXEC", 0) != 0
    assert temp_flags & os.O_CLOEXEC == os.O_CLOEXEC
    assert temp_flags & os.O_TRUNC == 0
    assert temp_open["mode"] == 0o600
    temp_descriptor = temp_open["result_descriptor"]
    fchmod = entries[1]
    assert fchmod["input_descriptor"] == temp_descriptor
    assert all(entry["input_descriptor"] == temp_descriptor for entry in writes)
    file_fsync = entries[-7]
    file_close = entries[-6]
    assert file_fsync["input_descriptor"] == temp_descriptor
    assert file_close["input_descriptor"] == temp_descriptor

    link = entries[-5]
    assert link["source"] == temporary
    assert link["destination"] == output
    assert link["follow_symlinks"] is False
    final_after_link = link["final_after_link"]
    temp_after_link = link["temporary_after_link"]
    assert final_after_link["mode"] == temp_after_link["mode"] == 0o600
    assert final_after_link["nlink"] == temp_after_link["nlink"] == 2
    for field in ("dev", "ino", "size", "sha256"):
        assert final_after_link[field] == temp_after_link[field]
    assert final_after_link["size"] == content_bytes
    assert receipt["publication"] == {
        "link_sequence": link["sequence"],
        "link_status": "ok",
        "final_after_link": final_after_link,
        "temp_after_link": temp_after_link,
        "same_inode": True,
    }
    publish_unlink = entries[-4]
    assert publish_unlink["path"] == temporary
    directory_open = entries[-3]
    directory_flags = directory_open["flags"]
    assert directory_open["path"] == os.fspath(Path(output).parent)
    assert (directory_flags & os.O_ACCMODE) == os.O_RDONLY
    assert getattr(os, "O_DIRECTORY", 0) != 0
    assert directory_flags & os.O_DIRECTORY == os.O_DIRECTORY
    assert directory_flags & os.O_CLOEXEC == os.O_CLOEXEC
    directory_descriptor = directory_open["result_descriptor"]
    assert entries[-2]["input_descriptor"] == directory_descriptor
    assert entries[-1]["input_descriptor"] == directory_descriptor
    assert entries[-1]["real_close_completed"] is True
    assert receipt["unlink_attempts"] == [
        {
            "operation": "PUBLISH_UNLINK",
            "sequence": publish_unlink["sequence"],
            "status": "ok",
            "injected": False,
            "real_call": True,
            "path": temporary,
        }
    ]
    assert receipt["directory"] == {
        "open_descriptor": directory_descriptor,
        "fsync_descriptor": directory_descriptor,
        "close_descriptor": directory_descriptor,
        "fsync_real_call": True,
        "close_real_call": True,
        "real_close_completed": True,
    }
    final_after = receipt["final_after"]
    assert final_after["mode"] == 0o600 and final_after["nlink"] == 1
    for field in ("dev", "ino", "size", "sha256"):
        assert final_after[field] == final_after_link[field]
    assert receipt["final_before"] == "absent"
    assert receipt["temp_before"] == receipt["temp_after"] == "absent"

    plugin_relative = "scripts/pytest_security_events.py"
    metadata = receipt["syscall_order_mutation"]
    assert metadata["recipe"] == "record-only-real-filesystem-v1"
    assert metadata["injection_position"] is None
    assert metadata["target_guard"] == {
        "absolute_output": output,
        "security_events_argv": guard_events,
        "security_target_argv": guard_target,
    }
    base_sha256 = "aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6"
    assert metadata["base_plugin_sha256"] == receipt["base_plugin_sha256"]
    assert metadata["base_plugin_sha256"] == base_sha256
    assert metadata["mutated_plugin_sha256"] == receipt["mutated_plugin_sha256"]
    assert metadata["mutated_plugin_sha256"] == receipt["files"][plugin_relative][
        "mutated_sha256"
    ]
    base_content = PYTEST_EVENTS_PLUGIN.read_text(encoding="utf-8")
    copied_plugin = execution["repository"] / plugin_relative
    mutated_content = copied_plugin.read_text(encoding="utf-8")
    assert hashlib.sha256(base_content.encode("utf-8")).hexdigest() == base_sha256
    assert hashlib.sha256(mutated_content.encode("utf-8")).hexdigest() == metadata[
        "mutated_plugin_sha256"
    ]
    assert mutated_content.count(repr(output)) == 1
    assert "monkeypatch" not in mutated_content
    approved_call_sites = [
        "TEMP_OPEN",
        "FCHMOD",
        "WRITE",
        "FILE_FSYNC",
        "FILE_CLOSE",
        "LINK",
        "PUBLISH_UNLINK",
        "DIR_OPEN",
        "DIR_FSYNC",
        "DIR_CLOSE",
        "CLEANUP_DIR_CLOSE",
        "CLEANUP_UNLINK",
    ]
    assert metadata["approved_call_sites"] == approved_call_sites
    groups = metadata["approved_replacement_groups"]
    assert len(groups) == 11
    assert sum(group["replacement_count"] for group in groups) == 12
    assert [group["operations"] for group in groups] == [
        [operation] for operation in approved_call_sites[:9]
    ] + [["DIR_CLOSE", "CLEANUP_DIR_CLOSE"], ["CLEANUP_UNLINK"]]
    replacements = metadata["approved_replacements"]
    assert [replacement["operation"] for replacement in replacements] == (
        approved_call_sites
    )
    reconstructed = mutated_content
    for replacement in reversed(replacements):
        old = replacement["old_fragment"]
        new = replacement["new_fragment"]
        expected_count = replacement["expected_count"]
        assert replacement["old_sha256"] == hashlib.sha256(
            old.encode("utf-8")
        ).hexdigest()
        assert replacement["new_sha256"] == hashlib.sha256(
            new.encode("utf-8")
        ).hexdigest()
        assert reconstructed.count(new) == expected_count
        reconstructed = reconstructed.replace(new, old, expected_count)
    helper = metadata["helper_fragment"]
    assert metadata["helper_sha256"] == hashlib.sha256(
        helper.encode("utf-8")
    ).hexdigest()
    function = "def _atomic_write(path: Path, content: bytes) -> None:\n"
    assert reconstructed.count(helper + function) == 1
    reconstructed = reconstructed.replace(helper + function, function, 1)
    assert reconstructed == base_content
    assert metadata["reconstructed_base_sha256"] == hashlib.sha256(
        reconstructed.encode("utf-8")
    ).hexdigest()
    assert metadata["reconstructed_base_sha256"] == base_sha256
    diff = "".join(
        difflib.unified_diff(
            base_content.splitlines(keepends=True),
            mutated_content.splitlines(keepends=True),
            fromfile="base/scripts/pytest_security_events.py",
            tofile="mutated/scripts/pytest_security_events.py",
        )
    )
    assert metadata["approved_diff_sha256"] == hashlib.sha256(
        diff.encode("utf-8")
    ).hexdigest()
    assert metadata["approved_diff_bytes"] == len(diff.encode("utf-8"))
    atomic_start = base_content.index(function)
    next_function = "\n\ndef pytest_sessionfinish("
    base_atomic_end = base_content.index(next_function, atomic_start)
    mutated_atomic_end = mutated_content.index(next_function, atomic_start)
    base_prefix = base_content[:atomic_start]
    base_suffix = base_content[base_atomic_end:]
    assert mutated_content[:atomic_start] == base_prefix
    assert mutated_content[mutated_atomic_end:] == base_suffix
    assert metadata["unchanged_regions_sha256"] == {
        "before_atomic_write": hashlib.sha256(base_prefix.encode("utf-8")).hexdigest(),
        "after_atomic_write": hashlib.sha256(base_suffix.encode("utf-8")).hexdigest(),
    }
    assert metadata["unchanged_region_bytes"] == {
        "before_atomic_write": len(base_prefix.encode("utf-8")),
        "after_atomic_write": len(base_suffix.encode("utf-8")),
    }
    base_inventory = _b3f_atomic_write_forbidden_call_inventory(base_content)
    mutated_inventory = _b3f_atomic_write_forbidden_call_inventory(mutated_content)
    assert metadata["forbidden_call_inventory"] == {
        "base": base_inventory,
        "mutated": mutated_inventory,
    }
    assert base_inventory == mutated_inventory == []

    attempt = execution["attempt"]
    control = "retention" if target == "capture" else "capture"
    control_output = attempt / control / "pytest-events.json"
    assert os.fspath(control_output).encode("utf-8") not in raw
    for lane in (target, control):
        events_path = attempt / lane / "pytest-events.json"
        events = json.loads(events_path.read_text(encoding="utf-8"))
        assert events["schema_version"] == 3
        assert events["run_id"] == "s18-b3f-real-pytest"
        assert events["target"] == lane
        assert events["attempt"] == 1
        assert isinstance(events["cases"], list) and events["cases"]
        assert set(receipt["artifact_sets"][lane]) == set(
            _b3f_artifact_names(lane, "full")
        )
        gate_path = attempt / lane / "gate.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        assert gate["passed"] is True and gate["failures"] == []
        replay_path = execution["root"] / f"replay-{lane}-gate.json"
        assert replay_path.read_bytes() == gate_path.read_bytes()


def _b3f_batch_e_fixture_bytes(fault: str, target: str) -> bytes:
    return f"B3f protected fixture {fault}:{target}\n".encode("ascii")


def _b3f_batch_e_mutation_recipe(fault: str) -> dict[str, object]:
    recipes = {
        "existing-final": {
            "stage": "plugin-import",
            "position": "before-pytest-configure",
            "real_syscall": "os.open(O_CREAT|O_EXCL)",
            "expected_errno": None,
            "protected_role": "existing-final",
        },
        "preexisting-temp": {
            "stage": "plugin-import",
            "position": "before-atomic-write-temp-open",
            "real_syscall": "os.open",
            "expected_errno": errno.EEXIST,
            "protected_role": "preexisting-temp",
        },
        "publish-race": {
            "stage": "atomic-write",
            "position": "after-file-close-before-link",
            "real_syscall": "os.link",
            "expected_errno": errno.EEXIST,
            "protected_role": "publish-race-winner",
        },
    }
    return dict(recipes[fault])


def _b3f_mutate_protected_writer(
    repository: Path,
    *,
    target: str,
    target_output: Path,
    trace_path: Path,
    fault: str,
) -> Path:
    plugin = repository / "scripts/pytest_security_events.py"
    content = plugin.read_text(encoding="utf-8")
    fixture_content = _b3f_batch_e_fixture_bytes(fault, target)
    function = "def _atomic_write(path: Path, content: bytes) -> None:\n"
    helper = f'''import errno as _b3f_e_errno
import hashlib as _b3f_e_hashlib
import stat as _b3f_e_stat
import sys as _b3f_e_sys

_B3F_E_FAULT = {fault!r}
_B3F_E_TARGET = {target!r}
_B3F_E_TARGET_OUTPUT = {os.fspath(target_output)!r}
_B3F_E_EVENTS_ARG = {("--security-events=" + os.fspath(target_output))!r}
_B3F_E_TARGET_ARG = {("--security-target=" + target)!r}
_B3F_E_TRACE = {os.fspath(trace_path)!r}
_B3F_E_FIXTURE_CONTENT = {fixture_content!r}
_B3F_E_SEQUENCE = 0


def _b3f_e_active(path: Path | None = None) -> bool:
    return (
        Path(_B3F_E_TARGET_OUTPUT).is_absolute()
        and _b3f_e_sys.argv.count(_B3F_E_EVENTS_ARG) == 1
        and _b3f_e_sys.argv.count(_B3F_E_TARGET_ARG) == 1
        and (path is None or os.fspath(path) == _B3F_E_TARGET_OUTPUT)
    )


def _b3f_e_trace(operation: str, **details: object) -> None:
    global _B3F_E_SEQUENCE
    _B3F_E_SEQUENCE += 1
    entry = {{
        "sequence": _B3F_E_SEQUENCE,
        "operation": operation,
        "pid": os.getpid(),
        "output": _B3F_E_TARGET_OUTPUT,
        "temporary": os.fspath(
            Path(_B3F_E_TARGET_OUTPUT).with_name(
                f".{{Path(_B3F_E_TARGET_OUTPUT).name}}.{{os.getpid()}}.tmp"
            )
        ),
        "guard_events_argv": _B3F_E_EVENTS_ARG,
        "guard_target_argv": _B3F_E_TARGET_ARG,
        **details,
    }}
    try:
        with Path(_B3F_E_TRACE).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\\n")
    except BaseException:
        pass


def _b3f_e_identity(path: Path) -> dict[str, object]:
    value = os.lstat(path)
    assert _b3f_e_stat.S_ISREG(value.st_mode)
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        assert (opened.st_dev, opened.st_ino) == (value.st_dev, value.st_ino)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    data = b"".join(chunks)
    return {{
        "dev": value.st_dev,
        "ino": value.st_ino,
        "mode": _b3f_e_stat.S_IMODE(value.st_mode),
        "nlink": value.st_nlink,
        "size": value.st_size,
        "sha256": _b3f_e_hashlib.sha256(data).hexdigest(),
    }}


def _b3f_e_create_protected(
    path: Path, operation: str, **details: object
) -> dict[str, object]:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o640,
    )
    try:
        os.fchmod(descriptor, 0o640)
        view = memoryview(_B3F_E_FIXTURE_CONTENT)
        while view:
            written = os.write(descriptor, view)
            assert written > 0
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    identity = _b3f_e_identity(path)
    _b3f_e_trace(
        operation,
        status="ok",
        injected=False,
        protected_path=os.fspath(path),
        protected_identity=identity,
        **details,
    )
    return identity


def _b3f_e_call(
    path: Path,
    temporary: Path,
    content_bytes: int,
    operation: str,
    function: object,
    *args: object,
    **kwargs: object,
) -> object:
    if not _b3f_e_active(path):
        return function(*args, **kwargs)
    if _B3F_E_FAULT == "publish-race" and operation == "LINK":
        try:
            os.lstat(path)
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("B3f publish-race output existed before competitor")
        owned_temp_before_link = _b3f_e_identity(temporary)
        _b3f_e_create_protected(
            path,
            "RACE_WINNER_CREATE",
            owned_temp_before_link=owned_temp_before_link,
        )
    details: dict[str, object] = {{
        "status": "ok",
        "injected": False,
        "content_bytes": content_bytes,
    }}
    if operation == "WRITE":
        details["requested_bytes"] = len(args[1])
    try:
        result = function(*args, **kwargs)
    except OSError as exc:
        details.update(status="error", errno=exc.errno)
        _b3f_e_trace(operation, **details)
        raise
    if operation == "WRITE":
        details["written_bytes"] = result
    elif operation in {{"TEMP_OPEN", "DIR_OPEN"}}:
        details["descriptor"] = result
    _b3f_e_trace(operation, **details)
    return result


if _b3f_e_active():
    _b3f_e_output = Path(_B3F_E_TARGET_OUTPUT)
    if _B3F_E_FAULT == "existing-final":
        _b3f_e_create_protected(_b3f_e_output, "FIXTURE_FINAL_CREATE")
    elif _B3F_E_FAULT == "preexisting-temp":
        _b3f_e_temp = _b3f_e_output.with_name(
            f".{{_b3f_e_output.name}}.{{os.getpid()}}.tmp"
        )
        _b3f_e_create_protected(_b3f_e_temp, "FIXTURE_TEMP_CREATE")


'''
    assert content.count(function) == 1
    content = content.replace(function, helper + function)
    configure = "    output = Path(output_text)\n"
    configure_trace = (
        configure
        + '    if _B3F_E_FAULT == "existing-final" and _b3f_e_active(output):\n'
        + "        _b3f_e_trace(\n"
        + '            "CONFIGURE_OUTPUT_EXISTS",\n'
        + '            status="ok",\n'
        + "            injected=False,\n"
        + "            output_exists=output.exists(),\n"
        + "        )\n"
    )
    assert content.count(configure) == 1
    content = content.replace(configure, configure_trace)
    replacements = (
        (
            "            descriptor = os.open(\n",
            "            descriptor = _b3f_e_call(\n"
            '                path, temporary, len(content), "TEMP_OPEN", os.open,\n',
            1,
        ),
        (
            "            os.fchmod(descriptor, 0o600)\n",
            "            _b3f_e_call(\n"
            '                path, temporary, len(content), "FCHMOD", os.fchmod, descriptor, 0o600\n'
            "            )\n",
            1,
        ),
        (
            "                written = os.write(descriptor, view)\n",
            "                written = _b3f_e_call(\n"
            '                    path, temporary, len(content), "WRITE", os.write, descriptor, view\n'
            "                )\n",
            1,
        ),
        (
            "            os.fsync(descriptor)\n",
            "            _b3f_e_call(\n"
            '                path, temporary, len(content), "FILE_FSYNC", os.fsync, descriptor\n'
            "            )\n",
            1,
        ),
        (
            "                    os.close(descriptor)\n",
            "                    _b3f_e_call(\n"
            '                        path, temporary, len(content), "FILE_CLOSE", os.close, descriptor\n'
            "                    )\n",
            1,
        ),
        (
            "            os.link(temporary, path, follow_symlinks=False)\n",
            "            _b3f_e_call(\n"
            '                path, temporary, len(content), "LINK", os.link, temporary, path, follow_symlinks=False\n'
            "            )\n",
            1,
        ),
        (
            "        try:\n"
            "            os.unlink(temporary)\n"
            "            temp_owned = False\n",
            "        try:\n"
            "            _b3f_e_call(\n"
            '                path, temporary, len(content), "PUBLISH_UNLINK", os.unlink, temporary\n'
            "            )\n"
            "            temp_owned = False\n",
            1,
        ),
        (
            "            directory = os.open(\n",
            "            directory = _b3f_e_call(\n"
            '                path, temporary, len(content), "DIR_OPEN", os.open,\n',
            1,
        ),
        (
            "                os.fsync(directory)\n",
            "                _b3f_e_call(\n"
            '                    path, temporary, len(content), "DIR_FSYNC", os.fsync, directory\n'
            "                )\n",
            1,
        ),
        (
            "                os.close(directory)\n",
            "                _b3f_e_call(\n"
            '                    path, temporary, len(content), "DIR_CLOSE", os.close, directory\n'
            "                )\n",
            2,
        ),
        (
            "        if temp_owned:\n"
            "            with contextlib.suppress(OSError):\n"
            "                os.unlink(temporary)\n",
            "        if temp_owned:\n"
            "            with contextlib.suppress(OSError):\n"
            "                _b3f_e_call(\n"
            '                    path, temporary, len(content), "CLEANUP_UNLINK", os.unlink, temporary\n'
            "                )\n",
            1,
        ),
    )
    for old, new, expected_count in replacements:
        assert content.count(old) == expected_count, (old, content.count(old))
        content = content.replace(old, new)
    plugin.write_text(content, encoding="utf-8")
    return plugin


def _assert_b3f_batch_e_protected_trace(
    execution: dict[str, object], scenario: dict[str, object]
) -> None:
    receipt = execution["mutation_receipt"]
    fault = str(scenario["fault"])
    target = str(scenario["target"])
    trace_path = execution["writer_trace_path"]
    assert isinstance(trace_path, Path)
    raw = trace_path.read_bytes()
    trace = receipt["writer_trace"]
    assert trace["path"] == os.fspath(trace_path)
    assert trace["sha256"] == hashlib.sha256(raw).hexdigest()
    assert trace["size"] == len(raw) > 0
    entries = trace["parsed_sequence"]
    assert [entry["sequence"] for entry in entries] == list(
        range(1, len(entries) + 1)
    )
    assert {entry["pid"] for entry in entries} == {receipt["child_pid"]}
    assert {entry["output"] for entry in entries} == {receipt["target_output"]}
    assert {entry["temporary"] for entry in entries} == {
        receipt["target_temporary"]
    }
    guard_events = "--security-events=" + receipt["target_output"]
    guard_target = "--security-target=" + target
    assert {entry["guard_events_argv"] for entry in entries} == {guard_events}
    assert {entry["guard_target_argv"] for entry in entries} == {guard_target}
    recipe = _b3f_batch_e_mutation_recipe(fault)
    assert receipt["protected_path_mutation"] == {
        "fault": fault,
        "target": target,
        "target_output": receipt["target_output"],
        "guard_events_argv": guard_events,
        "guard_target_argv": guard_target,
        "trace_path": os.fspath(trace_path),
        **recipe,
    }
    assert receipt["runner_deadline_seconds"] == 60
    assert 0 < receipt["runner_elapsed_seconds"] < 60
    assert all(entry["injected"] is False for entry in entries)
    protected = receipt["protected_fixture"]
    assert protected["role"] == recipe["protected_role"]
    assert protected["owned_by_writer"] is False
    assert protected["expected_mode"] == 0o640
    assert protected["before"] == protected["after"]
    assert protected["before"]["mode"] == 0o640
    assert protected["before"]["nlink"] == 1
    assert protected["before"]["sha256"] == protected["expected_sha256"]
    assert protected["expected_sha256"] == hashlib.sha256(
        _b3f_batch_e_fixture_bytes(fault, target)
    ).hexdigest()
    operations = [entry["operation"] for entry in entries]
    statuses = [entry["status"] for entry in entries]
    if fault == "existing-final":
        assert operations == ["FIXTURE_FINAL_CREATE", "CONFIGURE_OUTPUT_EXISTS"]
        assert statuses == ["ok", "ok"]
        assert entries[1]["output_exists"] is True
        assert protected["path"] == receipt["target_output"]
        assert receipt["final_before"] == receipt["final_after"] == protected["before"]
        assert receipt["temp_before"] == receipt["temp_after"] == "absent"
        assert receipt["owned_temp_before_link"] is None
        assert receipt["owned_temp_after"] is None
    elif fault == "preexisting-temp":
        assert operations == ["FIXTURE_TEMP_CREATE", "TEMP_OPEN"]
        assert statuses == ["ok", "error"]
        assert entries[1]["errno"] == errno.EEXIST
        assert protected["path"] == receipt["target_temporary"]
        assert protected["role"] == "preexisting-temp"
        assert receipt["final_before"] == receipt["final_after"] == "absent"
        assert receipt["temp_before"] == receipt["temp_after"] == protected["before"]
        assert receipt["owned_temp_before_link"] is None
        assert receipt["owned_temp_after"] is None
    elif fault == "publish-race":
        assert operations[:2] == ["TEMP_OPEN", "FCHMOD"]
        assert operations[-5:] == [
            "FILE_FSYNC",
            "FILE_CLOSE",
            "RACE_WINNER_CREATE",
            "LINK",
            "CLEANUP_UNLINK",
        ]
        assert all(operation == "WRITE" for operation in operations[2:-5])
        writes = [
            entry for entry in entries if entry["operation"] == "WRITE"
        ]
        assert writes
        assert all(entry["written_bytes"] > 0 for entry in writes)
        assert sum(entry["written_bytes"] for entry in writes) == writes[0][
            "content_bytes"
        ]
        assert entries[-2]["operation"] == "LINK"
        assert entries[-2]["status"] == "error"
        assert entries[-2]["errno"] == errno.EEXIST
        assert "PUBLISH_UNLINK" not in operations
        assert not any(operation.startswith("DIR_") for operation in operations)
        assert protected["path"] == receipt["target_output"]
        assert receipt["final_before"] == receipt["final_after"] == protected["before"]
        owned = receipt["owned_temp_before_link"]
        assert owned["mode"] == 0o600 and owned["nlink"] == 1
        assert owned["ino"] != protected["before"]["ino"]
        assert receipt["owned_temp_after"] == "absent"
        assert receipt["temp_before"] == receipt["temp_after"] == "absent"
    else:
        raise AssertionError(f"unsupported Batch E protected fault: {fault}")
    copied_plugin = execution["repository"] / "scripts/pytest_security_events.py"
    copied_text = copied_plugin.read_text(encoding="utf-8")
    assert copied_text.count(repr(receipt["target_output"])) == 1
    assert copied_text.count(repr(guard_events)) == 1
    assert copied_text.count(repr(guard_target)) == 1
    assert "parent.name" not in copied_text
    assert "monkeypatch" not in copied_text
    assert "glob(" not in copied_text


def _b3f_atomic_write_forbidden_call_inventory(
    content: str,
) -> list[dict[str, object]]:
    tree = ast.parse(content)
    atomic_writes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_atomic_write"
    ]
    assert len(atomic_writes) == 1

    def call_name(value: ast.expr) -> str:
        if isinstance(value, ast.Name):
            return value.id
        if isinstance(value, ast.Attribute):
            prefix = call_name(value.value)
            return value.attr if not prefix else prefix + "." + value.attr
        return ""

    inventory = []
    for node in ast.walk(atomic_writes[0]):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node.func)
        terminal = name.rsplit(".", 1)[-1]
        if name in {"os.replace", "os.rename", "renameat2"} or terminal in {
            "replace",
            "rename",
            "renameat2",
        }:
            inventory.append(
                {
                    "call": name,
                    "line": node.lineno,
                    "column": node.col_offset,
                }
            )
    return sorted(
        inventory,
        key=lambda item: (int(item["line"]), int(item["column"]), str(item["call"])),
    )


def _b3f_writer_injection_position(fault: str) -> str | None:
    positions = {
        "temp-open": "before-temp-open",
        "fchmod": "before-fchmod",
        "write-zero": "first-write-returns-zero",
        "partial-write-success": "first-write-limited-to-one-byte",
        "write-exception-after-partial": "before-second-write-after-one-real-byte",
        "file-fsync": "before-file-fsync",
        "file-close": "after-real-file-close",
        "temp-unlink-retry": "before-real",
        "directory-fsync": "before-real",
        "directory-close": "after-real",
        "syscall-order": None,
    }
    return positions[fault]


def _b3f_writer_exact_call_site(fault: str) -> str:
    call_sites = {
        "temp-open": "atomic-write:TEMP_OPEN",
        "fchmod": "atomic-write:FCHMOD",
        "write-zero": "atomic-write:WRITE",
        "partial-write-success": "atomic-write:WRITE",
        "write-exception-after-partial": "atomic-write:WRITE",
        "file-fsync": "atomic-write:FILE_FSYNC",
        "file-close": "atomic-write:FILE_CLOSE",
        "temp-unlink-retry": "atomic-write:PUBLISH_UNLINK",
        "directory-fsync": "atomic-write:DIR_FSYNC",
        "directory-close": "atomic-write:DIR_CLOSE",
        "syscall-order": "atomic-write:record-only-approved-sequence",
    }
    return call_sites[fault]


def _b3f_mutate_writer_calls(
    repository: Path,
    *,
    target: str,
    target_output: Path,
    trace_path: Path,
    fault: str,
    mutation_metadata: dict[str, object] | None = None,
) -> Path:
    plugin = repository / "scripts/pytest_security_events.py"
    base_content = plugin.read_text(encoding="utf-8")
    content = base_content
    assert (mutation_metadata is not None) is (fault in _B3F_BATCH_G_FAULTS)
    function = "def _atomic_write(path: Path, content: bytes) -> None:\n"
    helper = f'''_B3F_WRITER_TARGET_OUTPUT = {os.fspath(target_output)!r}
_B3F_WRITER_TARGET = {target!r}
_B3F_WRITER_TRACE = {os.fspath(trace_path)!r}
_B3F_WRITER_FAULT = {fault!r}
_B3F_WRITER_SEQUENCE = 0
_B3F_WRITER_WRITE_CALLS = 0


def _b3f_writer_active(path: Path) -> bool:
    import sys as _b3f_sys

    return (
        os.fspath(path) == _B3F_WRITER_TARGET_OUTPUT
        and _b3f_sys.argv.count("--security-events=" + _B3F_WRITER_TARGET_OUTPUT) == 1
        and _b3f_sys.argv.count("--security-target=" + _B3F_WRITER_TARGET) == 1
    )


def _b3f_writer_regular_state(path: Path) -> dict[str, object]:
    import hashlib as _b3f_hashlib
    import stat as _b3f_stat

    before = path.lstat()
    if not _b3f_stat.S_ISREG(before.st_mode):
        raise AssertionError("B3f writer identity target is not regular")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise AssertionError("B3f writer identity changed during no-follow open")
        digest = _b3f_hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    finally:
        os.close(descriptor)
    return {{
        "dev": after.st_dev,
        "ino": after.st_ino,
        "mode": _b3f_stat.S_IMODE(after.st_mode),
        "nlink": after.st_nlink,
        "size": size,
        "sha256": digest.hexdigest(),
    }}


def _b3f_writer_trace(output_path: Path, temporary: Path, content_bytes: int, operation: str, **details: object) -> None:
    global _B3F_WRITER_SEQUENCE
    _B3F_WRITER_SEQUENCE += 1
    entry = {{
        "sequence": _B3F_WRITER_SEQUENCE,
        "operation": operation,
        "pid": os.getpid(),
        "output": os.fspath(output_path),
        "temporary": os.fspath(temporary),
        "content_bytes": content_bytes,
        "guard_events_argv": "--security-events=" + _B3F_WRITER_TARGET_OUTPUT,
        "guard_target_argv": "--security-target=" + _B3F_WRITER_TARGET,
        **details,
    }}
    try:
        with Path(_B3F_WRITER_TRACE).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\\n")
    except BaseException:
        pass


def _b3f_writer_call(path: Path, temporary: Path, content_bytes: int, operation: str, function: object, *args: object, **kwargs: object) -> object:
    global _B3F_WRITER_WRITE_CALLS
    if not _b3f_writer_active(path):
        return function(*args, **kwargs)
    details: dict[str, object] = {{
        "status": "ok",
        "injected": False,
        "real_call": False,
    }}
    call_args = args
    if operation in {{
        "FCHMOD",
        "WRITE",
        "FILE_FSYNC",
        "FILE_CLOSE",
        "DIR_FSYNC",
        "DIR_CLOSE",
        "CLEANUP_DIR_CLOSE",
    }}:
        details["input_descriptor"] = args[0]
    if operation == "TEMP_OPEN":
        details.update(path=os.fspath(args[0]), flags=args[1], mode=args[2])
    elif operation == "DIR_OPEN":
        details.update(path=os.fspath(args[0]), flags=args[1])
    elif operation == "LINK":
        details.update(
            source=os.fspath(args[0]),
            destination=os.fspath(args[1]),
            follow_symlinks=kwargs.get("follow_symlinks"),
        )
    if operation in {{"PUBLISH_UNLINK", "CLEANUP_UNLINK"}}:
        details["path"] = os.fspath(args[0])
    if operation == "WRITE":
        _B3F_WRITER_WRITE_CALLS += 1
        details["write_index"] = _B3F_WRITER_WRITE_CALLS
        details["original_requested_bytes"] = len(args[1])
        if _B3F_WRITER_FAULT in {{"partial-write-success", "write-exception-after-partial"}} and _B3F_WRITER_WRITE_CALLS == 1:
            call_args = (args[0], args[1][:1])
            if _B3F_WRITER_FAULT == "partial-write-success":
                details.update(injected=True, injection_position="argument-limited-before-real")
        details["requested_bytes"] = len(call_args[1])
    inject_before = (
        (_B3F_WRITER_FAULT == "temp-open" and operation == "TEMP_OPEN")
        or (_B3F_WRITER_FAULT == "fchmod" and operation == "FCHMOD")
        or (_B3F_WRITER_FAULT == "file-fsync" and operation == "FILE_FSYNC")
        or (
            _B3F_WRITER_FAULT == "temp-unlink-retry"
            and operation == "PUBLISH_UNLINK"
        )
        or (
            _B3F_WRITER_FAULT == "directory-fsync"
            and operation == "DIR_FSYNC"
        )
        or (
            _B3F_WRITER_FAULT == "write-exception-after-partial"
            and operation == "WRITE"
            and _B3F_WRITER_WRITE_CALLS == 2
        )
    )
    if inject_before:
        details.update(status="error", injected=True, injection_position="before-real")
        _b3f_writer_trace(path, temporary, content_bytes, operation, **details)
        raise OSError("controlled B3f writer call failure")
    if _B3F_WRITER_FAULT == "write-zero" and operation == "WRITE" and _B3F_WRITER_WRITE_CALLS == 1:
        details.update(status="zero", injected=True, injection_position="instead-of-real", written_bytes=0)
        _b3f_writer_trace(path, temporary, content_bytes, operation, **details)
        return 0
    try:
        details["real_call"] = True
        result = function(*call_args, **kwargs)
    except OSError as exc:
        details.update(status="error", errno=exc.errno)
        _b3f_writer_trace(path, temporary, content_bytes, operation, **details)
        raise
    if operation == "WRITE":
        details["written_bytes"] = result
    elif operation in {{"TEMP_OPEN", "DIR_OPEN"}}:
        details["descriptor"] = result
        details["result_descriptor"] = result
    elif operation == "LINK":
        details["final_after_link"] = _b3f_writer_regular_state(path)
        details["temporary_after_link"] = _b3f_writer_regular_state(temporary)
    elif operation == "DIR_CLOSE":
        details["real_close_completed"] = True
    if _B3F_WRITER_FAULT == "file-close" and operation == "FILE_CLOSE":
        details.update(status="error", injected=True, injection_position="after-real")
        _b3f_writer_trace(path, temporary, content_bytes, operation, **details)
        raise OSError("controlled B3f post-close failure")
    if _B3F_WRITER_FAULT == "directory-close" and operation == "DIR_CLOSE":
        details.update(status="error", injected=True, injection_position="after-real")
        _b3f_writer_trace(path, temporary, content_bytes, operation, **details)
        raise OSError("controlled B3f post-directory-close failure")
    _b3f_writer_trace(path, temporary, content_bytes, operation, **details)
    return result


'''
    assert content.count(function) == 1
    content = content.replace(function, helper + function)
    replacements = (
        (
            "            descriptor = os.open(\n",
            "            descriptor = _b3f_writer_call(\n"
            "                path, temporary, len(content), \"TEMP_OPEN\", os.open,\n",
            1,
        ),
        (
            "            os.fchmod(descriptor, 0o600)\n",
            "            _b3f_writer_call(\n"
            "                path, temporary, len(content), \"FCHMOD\", os.fchmod, descriptor, 0o600\n"
            "            )\n",
            1,
        ),
        (
            "                written = os.write(descriptor, view)\n",
            "                written = _b3f_writer_call(\n"
            "                    path, temporary, len(content), \"WRITE\", os.write, descriptor, view\n"
            "                )\n",
            1,
        ),
        (
            "            os.fsync(descriptor)\n",
            "            _b3f_writer_call(\n"
            "                path, temporary, len(content), \"FILE_FSYNC\", os.fsync, descriptor\n"
            "            )\n",
            1,
        ),
        (
            "                    os.close(descriptor)\n",
            "                    _b3f_writer_call(\n"
            "                        path, temporary, len(content), \"FILE_CLOSE\", os.close, descriptor\n"
            "                    )\n",
            1,
        ),
        (
            "            os.link(temporary, path, follow_symlinks=False)\n",
            "            _b3f_writer_call(\n"
            "                path, temporary, len(content), \"LINK\", os.link, temporary, path, follow_symlinks=False\n"
            "            )\n",
            1,
        ),
        (
            "        try:\n"
            "            os.unlink(temporary)\n"
            "            temp_owned = False\n",
            "        try:\n"
            "            _b3f_writer_call(\n"
            "                path, temporary, len(content), \"PUBLISH_UNLINK\", os.unlink, temporary\n"
            "            )\n"
            "            temp_owned = False\n",
            1,
        ),
        (
            "            directory = os.open(\n",
            "            directory = _b3f_writer_call(\n"
            "                path, temporary, len(content), \"DIR_OPEN\", os.open,\n",
            1,
        ),
        (
            "                os.fsync(directory)\n",
            "                _b3f_writer_call(\n"
            "                    path, temporary, len(content), \"DIR_FSYNC\", os.fsync, directory\n"
            "                )\n",
            1,
        ),
        (
            "            try:\n"
            "                os.close(directory)\n"
            "            except OSError as exc:\n",
            "            try:\n"
            "                _b3f_writer_call(\n"
            "                    path, temporary, len(content), \"DIR_CLOSE\", os.close, directory\n"
            "                )\n"
            "            except OSError as exc:\n",
            1,
        ),
        (
            "        if directory is not None:\n"
            "            with contextlib.suppress(OSError):\n"
            "                os.close(directory)\n",
            "        if directory is not None:\n"
            "            with contextlib.suppress(OSError):\n"
            "                _b3f_writer_call(\n"
            "                    path, temporary, len(content), \"CLEANUP_DIR_CLOSE\", os.close, directory\n"
            "                )\n",
            1,
        ),
        (
            "        if temp_owned:\n"
            "            with contextlib.suppress(OSError):\n"
            "                os.unlink(temporary)\n",
            "        if temp_owned:\n"
            "            with contextlib.suppress(OSError):\n"
            "                _b3f_writer_call(\n"
            "                    path, temporary, len(content), \"CLEANUP_UNLINK\", os.unlink, temporary\n"
            "                )\n",
            1,
        ),
    )
    approved_call_sites = (
        "TEMP_OPEN",
        "FCHMOD",
        "WRITE",
        "FILE_FSYNC",
        "FILE_CLOSE",
        "LINK",
        "PUBLISH_UNLINK",
        "DIR_OPEN",
        "DIR_FSYNC",
        "DIR_CLOSE",
        "CLEANUP_DIR_CLOSE",
        "CLEANUP_UNLINK",
    )
    assert len(replacements) == len(approved_call_sites) == 12
    for old, new, expected_count in replacements:
        assert content.count(old) == expected_count, (old, content.count(old))
        content = content.replace(old, new)
    if mutation_metadata is not None:
        base_bytes = base_content.encode("utf-8")
        mutated_bytes = content.encode("utf-8")
        base_sha256 = hashlib.sha256(base_bytes).hexdigest()
        mutated_sha256 = hashlib.sha256(mutated_bytes).hexdigest()
        assert (
            base_sha256
            == "aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6"
        )
        reconstructed = content
        for old, new, expected_count in reversed(replacements):
            assert reconstructed.count(new) == expected_count
            reconstructed = reconstructed.replace(new, old, expected_count)
        assert reconstructed.count(helper + function) == 1
        reconstructed = reconstructed.replace(helper + function, function, 1)
        assert reconstructed == base_content
        diff = "".join(
            difflib.unified_diff(
                base_content.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile="base/scripts/pytest_security_events.py",
                tofile="mutated/scripts/pytest_security_events.py",
            )
        )
        atomic_start = base_content.index(function)
        next_function = "\n\ndef pytest_sessionfinish("
        base_atomic_end = base_content.index(next_function, atomic_start)
        mutated_atomic_end = content.index(next_function, atomic_start)
        base_prefix = base_content[:atomic_start]
        base_suffix = base_content[base_atomic_end:]
        assert content[:atomic_start] == base_prefix
        assert content[mutated_atomic_end:] == base_suffix
        base_inventory = _b3f_atomic_write_forbidden_call_inventory(base_content)
        mutated_inventory = _b3f_atomic_write_forbidden_call_inventory(content)
        assert base_inventory == mutated_inventory == []
        mutation_metadata.update(
            {
                "recipe": "record-only-real-filesystem-v1",
                "injection_position": None,
                "target_guard": {
                    "absolute_output": os.fspath(target_output),
                    "security_events_argv": "--security-events="
                    + os.fspath(target_output),
                    "security_target_argv": "--security-target=" + target,
                },
                "base_plugin_sha256": base_sha256,
                "mutated_plugin_sha256": mutated_sha256,
                "approved_call_sites": list(approved_call_sites),
                "approved_replacement_groups": [
                    {
                        "group": operation.lower().replace("_", "-"),
                        "operations": [operation],
                        "replacement_count": 1,
                    }
                    for operation in approved_call_sites[:9]
                ]
                + [
                    {
                        "group": "directory-close-sites",
                        "operations": ["DIR_CLOSE", "CLEANUP_DIR_CLOSE"],
                        "replacement_count": 2,
                    },
                    {
                        "group": "cleanup-unlink",
                        "operations": ["CLEANUP_UNLINK"],
                        "replacement_count": 1,
                    },
                ],
                "approved_replacements": [
                    {
                        "operation": operation,
                        "expected_count": expected_count,
                        "old_fragment": old,
                        "new_fragment": new,
                        "old_sha256": hashlib.sha256(old.encode("utf-8")).hexdigest(),
                        "new_sha256": hashlib.sha256(new.encode("utf-8")).hexdigest(),
                    }
                    for operation, (old, new, expected_count) in zip(
                        approved_call_sites, replacements, strict=True
                    )
                ],
                "approved_diff_sha256": hashlib.sha256(
                    diff.encode("utf-8")
                ).hexdigest(),
                "approved_diff_bytes": len(diff.encode("utf-8")),
                "helper_fragment": helper,
                "helper_sha256": hashlib.sha256(helper.encode("utf-8")).hexdigest(),
                "unchanged_regions_sha256": {
                    "before_atomic_write": hashlib.sha256(
                        base_prefix.encode("utf-8")
                    ).hexdigest(),
                    "after_atomic_write": hashlib.sha256(
                        base_suffix.encode("utf-8")
                    ).hexdigest(),
                },
                "unchanged_region_bytes": {
                    "before_atomic_write": len(base_prefix.encode("utf-8")),
                    "after_atomic_write": len(base_suffix.encode("utf-8")),
                },
                "reconstructed_base_sha256": hashlib.sha256(
                    reconstructed.encode("utf-8")
                ).hexdigest(),
                "forbidden_call_inventory": {
                    "base": base_inventory,
                    "mutated": mutated_inventory,
                },
            }
        )
    plugin.write_text(content, encoding="utf-8")
    return plugin


def _b3f_mutate_writer(
    repository: Path,
    *,
    target: str,
    fault: str,
    pid_receipt: Path,
    target_output: Path,
    trace_path: Path,
    mutation_metadata: dict[str, object] | None = None,
) -> Path:
    plugin = repository / "scripts/pytest_security_events.py"
    content = plugin.read_text(encoding="utf-8")
    if fault in _B3F_BATCH_E_FAULTS:
        return _b3f_mutate_protected_writer(
            repository,
            target=target,
            target_output=target_output,
            trace_path=trace_path,
            fault=fault,
        )
    if fault in _B3F_BATCH_D_FAULTS + _B3F_BATCH_F_FAULTS + _B3F_BATCH_G_FAULTS:
        return _b3f_mutate_writer_calls(
            repository,
            target=target,
            target_output=target_output,
            trace_path=trace_path,
            fault=fault,
            mutation_metadata=mutation_metadata,
        )
    if fault == "link-failure":
        old = "        try:\n            os.link(temporary, path, follow_symlinks=False)\n"
        new = (
            "        try:\n"
            f"            if path.parent.name == {target!r}:\n"
            '                raise OSError("controlled B3f link failure")\n'
            "            os.link(temporary, path, follow_symlinks=False)\n"
        )
        assert content.count(old) == 1
        content = content.replace(old, new)
    elif fault == "temp-unlink":
        function = "def _atomic_write(path: Path, content: bytes) -> None:\n"
        helper = (
            "def _b3f_controlled_unlink(temporary: Path) -> None:\n"
            f"    if temporary.parent.name == {target!r}:\n"
            '        raise OSError("controlled B3f permanent temp unlink failure")\n'
            "    os.unlink(temporary)\n\n\n"
        )
        assert content.count(function) == 1
        content = content.replace(function, helper + function)
        temporary = '    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")\n'
        receipt = (
            temporary
            + f"    if path.parent.name == {target!r}:\n"
            + f"        Path({os.fspath(pid_receipt)!r}).write_text(\n"
            + '            str(os.getpid()), encoding="ascii"\n'
            + "        )\n"
        )
        assert content.count(temporary) == 1
        content = content.replace(temporary, receipt)
        assert content.count("os.unlink(temporary)") == 3
        content = content.replace(
            "                os.unlink(temporary)",
            "                _b3f_controlled_unlink(temporary)",
        ).replace(
            "            os.unlink(temporary)",
            "            _b3f_controlled_unlink(temporary)",
        )
    elif fault == "directory-open":
        old = "            directory = os.open(\n"
        new = (
            f"            if path.parent.name == {target!r}:\n"
            '                raise OSError("controlled B3f directory open failure")\n'
            "            directory = os.open(\n"
        )
        assert content.count(old) == 1
        content = content.replace(old, new)
    else:
        raise AssertionError(f"unsupported representative B3f writer fault: {fault}")
    plugin.write_text(content, encoding="utf-8")
    return plugin


def _b3f_replay_gate(
    repository: Path, execution_root: Path, attempt: Path, target: str
) -> dict[str, object]:
    target_root = attempt / target
    output = execution_root / f"replay-{target}-gate.json"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            os.fspath(repository / "scripts/verify_security_coverage.py"),
            "--target",
            target,
            "--coverage",
            os.fspath(target_root / "coverage.json"),
            "--junit",
            os.fspath(target_root / "junit.xml"),
            "--pytest-events",
            os.fspath(target_root / "pytest-events.json"),
            "--plugin-identity",
            os.fspath(target_root / "plugin-identity.json"),
            "--environment",
            os.fspath(target_root / "environment.json"),
            "--command",
            os.fspath(target_root / "command.json"),
            "--run-manifest",
            os.fspath(target_root / "run-manifest.json"),
            "--policy",
            os.fspath(repository / "packaging/security-coverage-policy.toml"),
            "--manifest",
            os.fspath(repository / "packaging/security-coverage-manifest.json"),
            "--output",
            os.fspath(output),
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    (execution_root / f"replay-{target}.stdout.log").write_text(
        result.stdout, encoding="utf-8"
    )
    (execution_root / f"replay-{target}.stderr.log").write_text(
        result.stderr, encoding="utf-8"
    )
    return {
        "returncode": result.returncode,
        "gate": None
        if not output.exists()
        else json.loads(output.read_text(encoding="utf-8")),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _b3f_writer_trace_receipt(trace_path: Path) -> dict[str, object]:
    raw = trace_path.read_bytes()
    assert raw and raw.endswith(b"\n")
    entries = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    assert [entry["sequence"] for entry in entries] == list(
        range(1, len(entries) + 1)
    )
    assert all(entry["output"] and entry["temporary"] for entry in entries)
    return {
        "path": os.fspath(trace_path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
        "parsed_sequence": entries,
    }


def _run_b3f_real_scenario(scenario: dict[str, object]) -> dict[str, object]:
    execution_root = Path(
        tempfile.mkdtemp(prefix="ai-auto-lrc-s18-b3f-", dir="/private/tmp")
    )
    print(f"B3F_EVIDENCE_ROOT={execution_root}")
    repository, runner, _ = _b3e_real_runner_repository(execution_root)
    target = str(scenario["target"])
    fault = str(scenario["fault"])
    attempt = execution_root / "attempt-001"
    target_output = attempt / target / "pytest-events.json"
    writer_trace_path = execution_root / "writer-trace.jsonl"
    policy = load_policy()
    target_test = repository / policy["scripts"][target]["test_file"]
    plugin = repository / "scripts/pytest_security_events.py"
    runner_path = repository / "scripts/run_security_coverage.sh"
    pytest_config = repository / "pyproject.toml"
    bound_paths = (plugin, target_test, runner_path, pytest_config)
    base_hashes = {
        path.relative_to(repository).as_posix(): _sha256(path) for path in bound_paths
    }
    pid_receipt = execution_root / "child-pid.txt"
    nodeid_fixture = None
    serialized_fixture = None
    syscall_order_mutation: dict[str, object] | None = (
        {} if fault in _B3F_BATCH_G_FAULTS else None
    )
    if fault in _B3F_BATCH_A_FAULTS:
        mutated_paths = (
            _b3f_mutate_runner_argv(
                repository,
                target=target,
                fault=fault,
            ),
        )
    elif fault in _B3F_BATCH_B_FAULTS:
        mutated_path, nodeid_fixture = _b3f_append_nodeid_fixture(
            repository,
            target=target,
            runner=runner,
            fault=fault,
        )
        mutated_paths = (mutated_path,)
    elif fault in _B3F_BATCH_C_FAULTS:
        mutated_test, serialized_fixture = _b3f_append_serialized_fixture(
            repository,
            target=target,
            runner=runner,
            fault=fault,
        )
        mutated_plugin = _b3f_mutate_collection_budget(
            repository,
            target=target,
            exact_ceiling=int(serialized_fixture["collection_upper_bound"]),
        )
        mutated_paths = (mutated_test, mutated_plugin)
    elif fault in {"cases-boundary", "cases-plus-one"}:
        total_cases = 4096 if fault == "cases-boundary" else 4097
        mutated_paths = (
            _b3f_append_case_fillers(
                repository,
                target=target,
                runner=runner,
                total_cases=total_cases,
            ),
        )
    else:
        mutated_paths = (
            _b3f_mutate_writer(
                repository,
                target=target,
                fault=fault,
                pid_receipt=pid_receipt,
                target_output=target_output,
                trace_path=writer_trace_path,
                mutation_metadata=syscall_order_mutation,
            ),
        )
    mutated_hashes = {
        path.relative_to(repository).as_posix(): _sha256(path) for path in bound_paths
    }
    subprocess.run(
        [
            "git",
            "add",
            *(os.fspath(path.relative_to(repository)) for path in mutated_paths),
        ],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--amend", "--no-edit", "-q"],
        cwd=repository,
        check=True,
    )
    assert (
        subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=repository,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        == ""
    )
    mutation_receipt: dict[str, object] = {
        "schema_version": 1,
        "scenario_id": scenario["scenario_id"],
        "mutation_recipe_id": fault + ":" + target,
        "real_runner": os.fspath(repository / "scripts/run_security_coverage.sh"),
        "uses_fake_uv": False,
        "bound_files": sorted(base_hashes),
        "files": {
            relative: {
                "base_sha256": base_hashes[relative],
                "mutated_sha256": mutated_hashes[relative],
            }
            for relative in base_hashes
        },
        "mutated_files": sorted(
            relative
            for relative in base_hashes
            if base_hashes[relative] != mutated_hashes[relative]
        ),
        "base_plugin_sha256": base_hashes["scripts/pytest_security_events.py"],
        "mutated_plugin_sha256": mutated_hashes["scripts/pytest_security_events.py"],
        "base_runner_sha256": base_hashes["scripts/run_security_coverage.sh"],
        "mutated_runner_sha256": mutated_hashes["scripts/run_security_coverage.sh"],
        "base_pytest_config_sha256": base_hashes["pyproject.toml"],
        "mutated_pytest_config_sha256": mutated_hashes["pyproject.toml"],
        "argv_mutation": None
        if fault not in _B3F_BATCH_A_FAULTS
        else _b3f_configure_argv_recipe(fault),
        "nodeid_fixture": nodeid_fixture,
        "serialized_fixture": serialized_fixture,
        "collection_budget_bypass": None
        if fault not in _B3F_BATCH_C_FAULTS
        else {
            "target": target,
            "scenario_id": scenario["scenario_id"],
            "scope": "target-exact-collection-ceiling",
            "policy_limit": policy["limits"]["pytest_events_bytes"],
            "natural_upper_bound": serialized_fixture["collection_upper_bound"],
        },
        "writer_fault_injection": None
        if fault
        not in _B3F_BATCH_D_FAULTS + _B3F_BATCH_F_FAULTS + _B3F_BATCH_G_FAULTS
        else {
            "fault": fault,
            "target": target,
            "target_output": os.fspath(target_output),
            "guard_events_argv": "--security-events=" + os.fspath(target_output),
            "guard_target_argv": "--security-target=" + target,
            "trace_path": os.fspath(writer_trace_path),
            "exact_call_site": _b3f_writer_exact_call_site(fault),
            "injection_position": _b3f_writer_injection_position(fault),
        },
        "syscall_order_mutation": syscall_order_mutation,
        "protected_path_mutation": None
        if fault not in _B3F_BATCH_E_FAULTS
        else {
            "fault": fault,
            "target": target,
            "target_output": os.fspath(target_output),
            "guard_events_argv": "--security-events=" + os.fspath(target_output),
            "guard_target_argv": "--security-target=" + target,
            "trace_path": os.fspath(writer_trace_path),
            **_b3f_batch_e_mutation_recipe(fault),
        },
    }
    sentinel = execution_root / "sentinel.bin"
    sentinel.write_bytes(b"B3f unrelated sentinel\n")
    sentinel.chmod(0o600)
    sentinel_before = _b3f_file_state(sentinel)
    deadline_seconds = (
        60
        if fault
        in _B3F_BATCH_D_FAULTS
        + _B3F_BATCH_E_FAULTS
        + _B3F_BATCH_F_FAULTS
        + _B3F_BATCH_G_FAULTS
        else 240
    )
    runner_started = time.monotonic()
    try:
        result = subprocess.run(
            [
                os.fspath(repository / "scripts/run_security_coverage.sh"),
                os.fspath(attempt),
                "s18-b3f-real-pytest",
                "1",
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
            timeout=deadline_seconds,
        )
    except subprocess.TimeoutExpired:
        elapsed_seconds = time.monotonic() - runner_started
        _write_json(
            execution_root / "runner-timeout-receipt.json",
            {
                "scenario_id": scenario["scenario_id"],
                "deadline_seconds": deadline_seconds,
                "elapsed_seconds": elapsed_seconds,
                "target_output": os.fspath(target_output),
                "trace_path": os.fspath(writer_trace_path),
            },
        )
        raise
    elapsed_seconds = time.monotonic() - runner_started
    child_pid = None
    temp_path = None
    writer_trace = None
    if fault == "temp-unlink":
        child_pid = int(pid_receipt.read_text(encoding="ascii"))
        temp_path = attempt / target / f".pytest-events.json.{child_pid}.tmp"
    elif fault in (
        _B3F_BATCH_D_FAULTS
        + _B3F_BATCH_E_FAULTS
        + _B3F_BATCH_F_FAULTS
        + _B3F_BATCH_G_FAULTS
    ):
        writer_trace = _b3f_writer_trace_receipt(writer_trace_path)
        entries = writer_trace["parsed_sequence"]
        child_pids = {entry["pid"] for entry in entries}
        outputs = {entry["output"] for entry in entries}
        temporaries = {entry["temporary"] for entry in entries}
        assert len(child_pids) == len(outputs) == len(temporaries) == 1
        child_pid = child_pids.pop()
        assert outputs.pop() == os.fspath(target_output)
        temp_path = Path(temporaries.pop())
        assert temp_path == target_output.with_name(
            f".{target_output.name}.{child_pid}.tmp"
        )
    protected_fixture = None
    owned_temp_before_link = None
    owned_temp_after = None
    publication = None
    unlink_attempts = None
    directory_receipt = None
    if fault in _B3F_BATCH_E_FAULTS:
        recipe = _b3f_batch_e_mutation_recipe(fault)
        protected_operation = {
            "existing-final": "FIXTURE_FINAL_CREATE",
            "preexisting-temp": "FIXTURE_TEMP_CREATE",
            "publish-race": "RACE_WINNER_CREATE",
        }[fault]
        protected_events = [
            entry
            for entry in writer_trace["parsed_sequence"]
            if entry["operation"] == protected_operation
        ]
        assert len(protected_events) == 1
        protected_event = protected_events[0]
        protected_path = Path(protected_event["protected_path"])
        expected_protected_path = (
            temp_path if fault == "preexisting-temp" else target_output
        )
        assert protected_path == expected_protected_path
        protected_before = protected_event["protected_identity"]
        protected_after = _b3f_lstat_regular_state(protected_path)
        protected_fixture = {
            "role": recipe["protected_role"],
            "path": os.fspath(protected_path),
            "expected_mode": 0o640,
            "expected_sha256": hashlib.sha256(
                _b3f_batch_e_fixture_bytes(fault, target)
            ).hexdigest(),
            "owned_by_writer": False,
            "before": protected_before,
            "after": protected_after,
        }
        if fault == "publish-race":
            owned_temp_before_link = protected_event["owned_temp_before_link"]
            owned_temp_after = _b3f_lstat_regular_state(temp_path)
    if fault in _B3F_BATCH_F_FAULTS + _B3F_BATCH_G_FAULTS:
        entries = writer_trace["parsed_sequence"]
        links = [entry for entry in entries if entry["operation"] == "LINK"]
        assert len(links) == 1
        link = links[0]
        assert link["status"] == "ok"
        final_after_link = link["final_after_link"]
        temp_after_link = link["temporary_after_link"]
        assert final_after_link["mode"] == temp_after_link["mode"] == 0o600
        assert final_after_link["nlink"] == temp_after_link["nlink"] == 2
        assert final_after_link["dev"] == temp_after_link["dev"]
        assert final_after_link["ino"] == temp_after_link["ino"]
        assert final_after_link["size"] == temp_after_link["size"]
        assert final_after_link["sha256"] == temp_after_link["sha256"]
        publication = {
            "link_sequence": link["sequence"],
            "link_status": link["status"],
            "final_after_link": final_after_link,
            "temp_after_link": temp_after_link,
            "same_inode": True,
        }
        unlink_attempts = [
            {
                "operation": entry["operation"],
                "sequence": entry["sequence"],
                "status": entry["status"],
                "injected": entry["injected"],
                "real_call": entry["real_call"],
                "path": entry["path"],
            }
            for entry in entries
            if entry["operation"] in {"PUBLISH_UNLINK", "CLEANUP_UNLINK"}
        ]

        def directory_entry(operation: str) -> dict[str, object] | None:
            matches = [entry for entry in entries if entry["operation"] == operation]
            assert len(matches) <= 1
            return None if not matches else matches[0]

        directory_open = directory_entry("DIR_OPEN")
        directory_fsync = directory_entry("DIR_FSYNC")
        directory_close = directory_entry("DIR_CLOSE")
        directory_receipt = {
            "open_descriptor": None
            if directory_open is None
            else directory_open["result_descriptor"],
            "fsync_descriptor": None
            if directory_fsync is None
            else directory_fsync["input_descriptor"],
            "close_descriptor": None
            if directory_close is None
            else directory_close["input_descriptor"],
            "fsync_real_call": None
            if directory_fsync is None
            else directory_fsync["real_call"],
            "close_real_call": None
            if directory_close is None
            else directory_close["real_call"],
            "real_close_completed": None
            if directory_close is None
            else directory_close["real_close_completed"],
        }
    artifact_sets = {
        lane: sorted(path.name for path in (attempt / lane).iterdir())
        for lane in ("capture", "retention")
    }
    hash_manifest = {
        lane: {
            path.name: _sha256(path)
            for path in sorted((attempt / lane).iterdir())
            if path.is_file()
        }
        for lane in ("capture", "retention")
    }
    replays = {
        lane: _b3f_replay_gate(repository, execution_root, attempt, lane)
        for lane in ("capture", "retention")
    }
    target_final = attempt / target / "pytest-events.json"
    mutation_receipt.update(
        {
            "child_pid": child_pid,
            "derived_temp_basename": None if temp_path is None else temp_path.name,
            "target_output": os.fspath(target_output),
            "target_temporary": None if temp_path is None else os.fspath(temp_path),
            "runner_deadline_seconds": deadline_seconds,
            "runner_elapsed_seconds": elapsed_seconds,
            "writer_trace": writer_trace,
            "protected_fixture": protected_fixture,
            "owned_temp_before_link": owned_temp_before_link,
            "owned_temp_after": owned_temp_after,
            "publication": publication,
            "unlink_attempts": unlink_attempts,
            "directory": directory_receipt,
            "artifact_sets": artifact_sets,
            "artifact_hashes": hash_manifest,
            "final_before": protected_fixture["before"]
            if fault in {"existing-final", "publish-race"}
            else "absent",
            "final_after": _b3f_lstat_regular_state(target_final)
            if fault
            in _B3F_BATCH_E_FAULTS + _B3F_BATCH_F_FAULTS + _B3F_BATCH_G_FAULTS
            else _b3f_file_state(target_final),
            "temp_before": protected_fixture["before"]
            if fault == "preexisting-temp"
            else "absent",
            "temp_after": "absent"
            if temp_path is None
            else (
                _b3f_lstat_regular_state(temp_path)
                if fault
                in _B3F_BATCH_E_FAULTS
                + _B3F_BATCH_F_FAULTS
                + _B3F_BATCH_G_FAULTS
                else _b3f_file_state(temp_path)
            ),
            "sentinel_before": sentinel_before,
            "sentinel_after": _b3f_file_state(sentinel),
        }
    )
    _write_json(execution_root / "mutation-receipt.json", mutation_receipt)
    if nodeid_fixture is not None:
        _write_json(execution_root / "nodeid-fixture-receipt.json", nodeid_fixture)
    if serialized_fixture is not None:
        _write_json(
            execution_root / "serialized-fixture-receipt.json", serialized_fixture
        )
    _write_json(execution_root / "artifact-hash-manifest.json", hash_manifest)
    return {
        "root": execution_root,
        "repository": repository,
        "attempt": attempt,
        "result": result,
        "mutation_receipt": mutation_receipt,
        "hash_manifest": hash_manifest,
        "replays": replays,
        "temp_path": temp_path,
        "writer_trace_path": writer_trace_path,
    }


def _assert_b3f_real_scenario(
    execution: dict[str, object], scenario: dict[str, object]
) -> None:
    evidence_root = execution["root"]
    assert isinstance(evidence_root, Path)
    message = f"B3f evidence retained at {evidence_root}"
    result = execution["result"]
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == scenario["expected_outer_exit"], message
    assert result.stdout == "", message
    assert result.stderr == "", message
    attempt = execution["attempt"]
    assert isinstance(attempt, Path)
    target = str(scenario["target"])
    control = "retention" if target == "capture" else "capture"
    target_root = attempt / target
    control_root = attempt / control
    target_command = json.loads(
        (target_root / "command.json").read_text(encoding="utf-8")
    )
    assert target_command["exit_code"] == scenario["expected_pytest_exit"], message
    expects_gate = scenario["expected_gate_failures"] is not None
    if expects_gate:
        target_gate = json.loads(
            (target_root / "gate.json").read_text(encoding="utf-8")
        )
        assert target_gate["failures"] == scenario["expected_gate_failures"], message
    else:
        assert not (target_root / "gate.json").exists(), message
    producer_code = scenario["expected_producer_code"]
    if producer_code is not None:
        target_stderr = (target_root / "stderr.log").read_text(encoding="utf-8")
        assert producer_code in target_stderr, message
        if scenario["fault"] in _B3F_BATCH_A_FAULTS:
            assert target_stderr.count(producer_code) == 1, message
            assert "INTERNALERROR" not in target_stderr, message
            assert "Traceback" not in target_stderr, message
            assert "Exceeds the limit" not in target_stderr, message
            assert "integer string conversion" not in target_stderr, message
        if scenario["fault"] in _B3F_BATCH_B_FAULTS:
            assert target_stderr.count(producer_code) == 1, message
            assert "PYTEST_EVENTS_CONFIGURATION_INVALID" not in target_stderr, message
            assert "INTERNALERROR" not in target_stderr, message
            assert "Traceback" not in target_stderr, message
        if scenario["fault"] in _B3F_BATCH_C_FAULTS:
            assert target_stderr.count(producer_code) == 1, message
            assert "PYTEST_EVENTS_CONFIGURATION_INVALID" not in target_stderr, message
            assert "INTERNALERROR" not in target_stderr, message
            assert "Traceback" not in target_stderr, message
        if scenario["fault"] in _B3F_BATCH_D_FAULTS:
            emitted_codes = re.findall(
                r"^scripts\.pytest_security_events\.EventsPublicationError: "
                r"(PYTEST_EVENTS_[A-Z_]+)$",
                target_stderr,
                flags=re.MULTILINE,
            )
            assert emitted_codes == [producer_code], message
            assert "PYTEST_EVENTS_CONFIGURATION_INVALID" not in target_stderr, message
            assert "PYTEST_EVENTS_COMMIT_UNCERTAIN" not in target_stderr, message
        if scenario["fault"] in _B3F_BATCH_E_FAULTS:
            if scenario["fault"] == "existing-final":
                assert target_stderr.count(producer_code) == 1, message
                assert "Traceback" not in target_stderr, message
            else:
                emitted_codes = re.findall(
                    r"^scripts\.pytest_security_events\.EventsPublicationError: "
                    r"(PYTEST_EVENTS_[A-Z_]+)$",
                    target_stderr,
                    flags=re.MULTILINE,
                )
                assert emitted_codes == [producer_code], message
            assert "PYTEST_EVENTS_COMMIT_UNCERTAIN" not in target_stderr, message
        if scenario["fault"] in _B3F_BATCH_F_FAULTS:
            emitted_codes = re.findall(
                r"^scripts\.pytest_security_events\.EventsCommitUncertain: "
                r"(PYTEST_EVENTS_[A-Z_]+)$",
                target_stderr,
                flags=re.MULTILINE,
            )
            assert emitted_codes == [producer_code], message
            assert "PYTEST_EVENTS_PUBLICATION_FAILED" not in target_stderr, message
            assert "PYTEST_EVENTS_CONFIGURATION_INVALID" not in target_stderr, message
    control_command = json.loads(
        (control_root / "command.json").read_text(encoding="utf-8")
    )
    control_gate = json.loads((control_root / "gate.json").read_text(encoding="utf-8"))
    assert control_command["exit_code"] == 0, message
    assert control_gate["passed"] is True, message
    assert control_gate["failures"] == [], message
    if scenario["fault"] in (
        _B3F_BATCH_D_FAULTS
        + _B3F_BATCH_E_FAULTS
        + _B3F_BATCH_F_FAULTS
        + _B3F_BATCH_G_FAULTS
    ):
        control_stderr = (control_root / "stderr.log").read_text(encoding="utf-8")
        assert not re.findall(
            r"^scripts\.pytest_security_events\.(?:EventsPublicationError|"
            r"EventsCommitUncertain): PYTEST_EVENTS_[A-Z_]+$",
            control_stderr,
            flags=re.MULTILINE,
        ), message
    if scenario["fault"] in _B3F_BATCH_A_FAULTS:
        _assert_b3f_configure_argv(
            target_command,
            control_command,
            str(scenario["fault"]),
        )
    if scenario["fault"] in (
        _B3F_BATCH_D_FAULTS + _B3F_BATCH_F_FAULTS + _B3F_BATCH_G_FAULTS
    ):
        _assert_b3f_canonical_limit_argv(target_command)
        _assert_b3f_canonical_limit_argv(control_command)
        writer_mutation = execution["mutation_receipt"]["writer_fault_injection"]
        assert target_command["argv"].count(
            writer_mutation["guard_events_argv"]
        ) == 1, message
        assert target_command["argv"].count(
            writer_mutation["guard_target_argv"]
        ) == 1, message
        assert writer_mutation["guard_events_argv"] not in control_command["argv"]
    if scenario["fault"] in _B3F_BATCH_E_FAULTS:
        _assert_b3f_canonical_limit_argv(target_command)
        _assert_b3f_canonical_limit_argv(control_command)
        protected_mutation = execution["mutation_receipt"][
            "protected_path_mutation"
        ]
        assert target_command["argv"].count(
            protected_mutation["guard_events_argv"]
        ) == 1, message
        assert target_command["argv"].count(
            protected_mutation["guard_target_argv"]
        ) == 1, message
        assert protected_mutation["guard_events_argv"] not in control_command["argv"]

    receipt = execution["mutation_receipt"]
    assert isinstance(receipt, dict)
    assert receipt["mutation_recipe_id"] == scenario["fault"] + ":" + target
    assert receipt["uses_fake_uv"] is False
    assert receipt["bound_files"] == sorted(receipt["files"])
    assert receipt["sentinel_before"] == receipt["sentinel_after"], message
    assert receipt["sentinel_after"]["mode"] == 0o600
    mutated_files = receipt["mutated_files"]
    expected_mutated = (
        ["scripts/run_security_coverage.sh"]
        if scenario["fault"] in _B3F_BATCH_A_FAULTS
        else (
            [
                "scripts/pytest_security_events.py",
                load_policy()["scripts"][target]["test_file"],
            ]
            if scenario["fault"] in _B3F_BATCH_C_FAULTS
            else (
                [load_policy()["scripts"][target]["test_file"]]
                if str(scenario["fault"]).startswith("cases-")
                or scenario["fault"] in _B3F_BATCH_B_FAULTS
                else ["scripts/pytest_security_events.py"]
            )
        )
    )
    assert mutated_files == expected_mutated, message
    for relative in mutated_files:
        hashes = receipt["files"][relative]
        assert hashes["base_sha256"] != hashes["mutated_sha256"]
    if scenario["fault"] in _B3F_BATCH_A_FAULTS:
        runner_relative = "scripts/run_security_coverage.sh"
        runner_hashes = receipt["files"][runner_relative]
        assert receipt["base_runner_sha256"] == runner_hashes["base_sha256"]
        assert receipt["mutated_runner_sha256"] == runner_hashes["mutated_sha256"]
        copied_runner = execution["repository"] / runner_relative
        assert _sha256(copied_runner) == receipt["mutated_runner_sha256"], message
        for lane_root in (target_root, control_root):
            environment = json.loads(
                (lane_root / "environment.json").read_text(encoding="utf-8")
            )
            repository = environment["repository"]
            assert repository["runner_sha256_before"] == receipt[
                "mutated_runner_sha256"
            ], message
            assert repository["runner_sha256_after"] == receipt[
                "mutated_runner_sha256"
            ], message
        control_manifest = json.loads(
            (control_root / "run-manifest.json").read_text(encoding="utf-8")
        )
        assert control_manifest["artifact_hashes"]["runner_sha256"] == receipt[
            "mutated_runner_sha256"
        ], message
    if scenario["fault"] in _B3F_BATCH_B_FAULTS:
        target_test_relative = load_policy()["scripts"][target]["test_file"]
        assert receipt["mutated_files"] == [target_test_relative], message
        for relative in (
            "scripts/pytest_security_events.py",
            "scripts/run_security_coverage.sh",
            "pyproject.toml",
        ):
            assert receipt["files"][relative]["base_sha256"] == receipt["files"][
                relative
            ]["mutated_sha256"], message
        fixture = receipt["nodeid_fixture"]
        assert isinstance(fixture, dict), message
        expected_bytes = 4096 if scenario["fault"] == "nodeid-boundary" else 4097
        assert fixture["utf8_bytes"] == expected_bytes, message
        assert fixture["utf8_sha256"] == hashlib.sha256(
            str(fixture["nodeid"]).encode("utf-8", "strict")
        ).hexdigest(), message
        assert fixture["canonical_grammar"] is True, message
        assert fixture["collected_exactly_once"] is True, message
        assert fixture["collected_last"] is True, message
        assert fixture["case_count"] == fixture["baseline_case_count"] + 1, message
        assert fixture["case_count"] < fixture["case_limit"] == 4096, message
        assert (
            fixture["serialized_upper_bound"] < fixture["serialized_limit"] == 8388608
        ), message
        if scenario["fault"] == "nodeid-plus-one-multibyte":
            assert fixture["python_characters"] < 4096, message
            assert fixture["nfc_equal"] is False, message
            assert fixture["nodeid"] != unicodedata.normalize(
                "NFC", str(fixture["nodeid"])
            ), message
        else:
            assert fixture["python_characters"] == expected_bytes, message
            assert fixture["nfc_equal"] is True, message
        target_environment = json.loads(
            (target_root / "environment.json").read_text(encoding="utf-8")
        )["repository"]
        assert target_environment["test_sha256_before"] == receipt["files"][
            target_test_relative
        ]["mutated_sha256"], message
        assert target_environment["test_sha256_after"] == receipt["files"][
            target_test_relative
        ]["mutated_sha256"], message
        for key, relative in (
            ("runner", "scripts/run_security_coverage.sh"),
            ("pytest_events_plugin", "scripts/pytest_security_events.py"),
            ("pytest_config", "pyproject.toml"),
        ):
            expected_hash = receipt["files"][relative]["mutated_sha256"]
            for lane_root in (target_root, control_root):
                environment = json.loads(
                    (lane_root / "environment.json").read_text(encoding="utf-8")
                )["repository"]
                assert environment[key + "_sha256_before"] == expected_hash, message
                assert environment[key + "_sha256_after"] == expected_hash, message
                manifest_path = lane_root / "run-manifest.json"
                if manifest_path.exists():
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    assert manifest["artifact_hashes"][key + "_sha256"] == expected_hash
        target_manifest_path = target_root / "run-manifest.json"
        if target_manifest_path.exists():
            target_manifest = json.loads(
                target_manifest_path.read_text(encoding="utf-8")
            )
            assert target_manifest["artifact_hashes"]["test_sha256"] == receipt[
                "files"
            ][target_test_relative]["mutated_sha256"], message
    if scenario["fault"] in _B3F_BATCH_C_FAULTS:
        target_test_relative = load_policy()["scripts"][target]["test_file"]
        plugin_relative = "scripts/pytest_security_events.py"
        assert receipt["mutated_files"] == [plugin_relative, target_test_relative]
        assert receipt["collection_budget_bypass"] == {
            "target": target,
            "scenario_id": scenario["scenario_id"],
            "scope": "target-exact-collection-ceiling",
            "policy_limit": 8388608,
            "natural_upper_bound": receipt["serialized_fixture"][
                "collection_upper_bound"
            ],
        }
        for relative in ("scripts/run_security_coverage.sh", "pyproject.toml"):
            assert receipt["files"][relative]["base_sha256"] == receipt["files"][
                relative
            ]["mutated_sha256"], message
        for relative in (plugin_relative, target_test_relative):
            assert receipt["files"][relative]["base_sha256"] != receipt["files"][
                relative
            ]["mutated_sha256"], message
        fixture = receipt["serialized_fixture"]
        assert fixture["calculator"] == "independent-json-dumps-explicit-compact-v1"
        assert fixture["generator"] == "dynamic-global-ascii-nodeids-v1"
        expected_bytes = 8388608 if scenario["fault"] == "serialized-boundary" else 8388609
        assert fixture["desired_bytes"] == expected_bytes, message
        assert fixture["calculated_bytes"] == expected_bytes, message
        assert fixture["events_limit"] == 8388608, message
        assert fixture["case_count"] == (
            fixture["baseline_case_count"] + fixture["generated_case_count"]
        ), message
        assert fixture["case_count"] < fixture["case_limit"] == 4096, message
        assert fixture["maximum_nodeid_bytes"] == 4096, message
        assert fixture["collection_upper_bound"] > fixture["events_limit"], message
        assert re.fullmatch(r"[0-9a-f]{64}", str(fixture["nodeid_lengths_sha256"]))
        assert re.fullmatch(r"[0-9a-f]{64}", str(fixture["generated_nodeids_sha256"]))
        assert re.fullmatch(r"[0-9a-f]{64}", str(fixture["source_append_sha256"]))
        copied_plugin = execution["repository"] / plugin_relative
        copied_plugin_text = copied_plugin.read_text(encoding="utf-8")
        ceiling_fragment = (
            "        b3f_collection_ceiling = (\n"
            f'            {fixture["collection_upper_bound"]}\n'
            f'            if state["target"] == {target!r}\n'
            '            else state["limits"]["pytest_events_bytes"]\n'
            "        )\n"
            "        if (\n"
            '            state["serialized_upper_bound"] + addition\n'
            "            > b3f_collection_ceiling\n"
            "        ):\n"
        )
        assert copied_plugin_text.count(ceiling_fragment) == 1, message
        assert copied_plugin_text.count("PYTEST_EVENTS_LIMIT_EXCEEDED") >= 2, message
        control_events = json.loads(
            (control_root / "pytest-events.json").read_text(encoding="utf-8")
        )
        assert control_events["target"] == control != target, message
        control_empty = dict(control_events)
        control_cases = control_empty.pop("cases")
        control_upper_bound = (
            len(_b3f_independent_compact_json_bytes(control_empty | {"cases": []}))
            + 1
        )
        for index, case in enumerate(control_cases):
            skipped_case = {
                "nodeid": case["nodeid"],
                "xfail_marked": case["xfail_marked"],
                "phases": {
                    phase: {"outcome": "skipped", "wasxfail": False}
                    for phase in ("setup", "call", "teardown")
                },
            }
            control_upper_bound += len(
                _b3f_independent_compact_json_bytes(skipped_case)
            )
            if index:
                control_upper_bound += 1
        assert control_upper_bound <= control_events["limits"]["pytest_events_bytes"]
        for key, relative in (
            ("runner", "scripts/run_security_coverage.sh"),
            ("pytest_events_plugin", plugin_relative),
            ("pytest_config", "pyproject.toml"),
        ):
            expected_hash = receipt["files"][relative]["mutated_sha256"]
            for lane_root in (target_root, control_root):
                environment = json.loads(
                    (lane_root / "environment.json").read_text(encoding="utf-8")
                )["repository"]
                assert environment[key + "_sha256_before"] == expected_hash, message
                assert environment[key + "_sha256_after"] == expected_hash, message
                manifest = json.loads(
                    (lane_root / "run-manifest.json").read_text(encoding="utf-8")
                )
                assert manifest["artifact_hashes"][key + "_sha256"] == expected_hash
        target_environment = json.loads(
            (target_root / "environment.json").read_text(encoding="utf-8")
        )["repository"]
        expected_test_hash = receipt["files"][target_test_relative]["mutated_sha256"]
        assert target_environment["test_sha256_before"] == expected_test_hash, message
        assert target_environment["test_sha256_after"] == expected_test_hash, message
        target_manifest = json.loads(
            (target_root / "run-manifest.json").read_text(encoding="utf-8")
        )
        assert target_manifest["artifact_hashes"]["test_sha256"] == expected_test_hash
    if scenario["fault"] in (
        _B3F_BATCH_D_FAULTS + _B3F_BATCH_F_FAULTS + _B3F_BATCH_G_FAULTS
    ):
        plugin_relative = "scripts/pytest_security_events.py"
        assert receipt["mutated_files"] == [plugin_relative], message
        for relative in (
            load_policy()["scripts"][target]["test_file"],
            "scripts/run_security_coverage.sh",
            "pyproject.toml",
        ):
            assert receipt["files"][relative]["base_sha256"] == receipt["files"][
                relative
            ]["mutated_sha256"], message
        assert receipt["files"][plugin_relative]["base_sha256"] != receipt[
            "files"
        ][plugin_relative]["mutated_sha256"], message
        for key, relative in (
            ("runner", "scripts/run_security_coverage.sh"),
            ("pytest_events_plugin", plugin_relative),
            ("pytest_config", "pyproject.toml"),
        ):
            expected_hash = receipt["files"][relative]["mutated_sha256"]
            for lane_root in (target_root, control_root):
                environment = json.loads(
                    (lane_root / "environment.json").read_text(encoding="utf-8")
                )["repository"]
                assert environment[key + "_sha256_before"] == expected_hash, message
                assert environment[key + "_sha256_after"] == expected_hash, message
                manifest = json.loads(
                    (lane_root / "run-manifest.json").read_text(encoding="utf-8")
                )
                assert manifest["artifact_hashes"][key + "_sha256"] == expected_hash
        if scenario["fault"] in _B3F_BATCH_D_FAULTS:
            _assert_b3f_batch_d_writer_trace(execution, scenario)
        elif scenario["fault"] in _B3F_BATCH_F_FAULTS:
            _assert_b3f_batch_f_writer_trace(execution, scenario)
        else:
            _assert_b3f_batch_g_syscall_order_trace(execution, scenario)
    if scenario["fault"] in _B3F_BATCH_E_FAULTS:
        plugin_relative = "scripts/pytest_security_events.py"
        assert receipt["mutated_files"] == [plugin_relative], message
        for relative in (
            load_policy()["scripts"][target]["test_file"],
            "scripts/run_security_coverage.sh",
            "pyproject.toml",
        ):
            assert receipt["files"][relative]["base_sha256"] == receipt["files"][
                relative
            ]["mutated_sha256"], message
        assert receipt["files"][plugin_relative]["base_sha256"] != receipt[
            "files"
        ][plugin_relative]["mutated_sha256"], message
        assert receipt["artifact_hashes"] == execution["hash_manifest"], message
        for key, relative in (
            ("runner", "scripts/run_security_coverage.sh"),
            ("pytest_events_plugin", plugin_relative),
            ("pytest_config", "pyproject.toml"),
        ):
            expected_hash = receipt["files"][relative]["mutated_sha256"]
            for lane_root in (target_root, control_root):
                environment = json.loads(
                    (lane_root / "environment.json").read_text(encoding="utf-8")
                )["repository"]
                assert environment[key + "_sha256_before"] == expected_hash, message
                assert environment[key + "_sha256_after"] == expected_hash, message
                manifest_path = lane_root / "run-manifest.json"
                if manifest_path.exists():
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    assert manifest["artifact_hashes"][key + "_sha256"] == expected_hash
        _assert_b3f_batch_e_protected_trace(execution, scenario)

    expected_artifacts = set(scenario["required_artifacts"])
    dynamic_temp = receipt["derived_temp_basename"]
    if "<dynamic-pid-temp>" in expected_artifacts:
        assert isinstance(receipt["child_pid"], int), message
        assert isinstance(dynamic_temp, str), message
        expected_artifacts.remove("<dynamic-pid-temp>")
        expected_artifacts.add(dynamic_temp)
    assert set(receipt["artifact_sets"][target]) == expected_artifacts, message
    assert set(receipt["artifact_sets"][control]) == set(
        _b3f_artifact_names(control, "full")
    ), message

    if not expects_gate:
        runner_error = json.loads(
            (target_root / "runner-error.json").read_text(encoding="utf-8")
        )
        assert runner_error["schema_version"] == 2, message
        assert runner_error["run_id"] == "s18-b3f-real-pytest", message
        assert runner_error["target"] == target, message
        assert runner_error["runner"] in {"macos", "linux"}, message
        assert runner_error["attempt"] == 1, message
        assert runner_error["stage"] == "raw-completeness", message
        assert runner_error["reason_code"] == "REQUIRED_RAW_ARTIFACT_MISSING", message
        assert runner_error["pytest_exit_code"] == scenario[
            "expected_pytest_exit"
        ], message
        assert runner_error["environment_exit_code"] == 0, message
        assert runner_error["command_exit_code"] == 0, message
        assert runner_error["qualification"] == "INCOMPLETE_RAW_EVIDENCE", message
        present = runner_error["present_artifacts"]
        expected_present = sorted(
            set(receipt["artifact_sets"][target]) - {"runner-error.json"}
        )
        assert present == expected_present, message
        known_artifacts = {
            ".coverage-" + target,
            "coverage.json",
            "junit.xml",
            "pytest-events.json",
            "plugin-identity.json",
            "environment.json",
            "command.json",
            "stdout.log",
            "stderr.log",
        }
        assert runner_error["missing_artifacts"] == sorted(
            known_artifacts - set(expected_present)
        ), message
        assert runner_error["present_hashes"] == {
            name: execution["hash_manifest"][target][name] for name in present
        }, message

    final_after = receipt["final_after"]
    temp_after = receipt["temp_after"]
    if scenario["expected_final_state"] == "absent":
        assert final_after == "absent", message
    elif scenario["expected_final_state"] == "single-link-0600":
        assert final_after["mode"] == 0o600 and final_after["nlink"] == 1, message
    elif scenario["expected_final_state"] == "protected-single-link-0640":
        assert final_after["mode"] == 0o640 and final_after["nlink"] == 1, message
    elif scenario["expected_final_state"] == "double-link-0600":
        assert final_after["mode"] == 0o600 and final_after["nlink"] == 2, message
    else:
        raise AssertionError(message)
    if scenario["expected_temp_state"] == "absent":
        assert temp_after == "absent", message
    elif scenario["expected_temp_state"] == "protected-single-link-0640":
        assert temp_after["mode"] == 0o640 and temp_after["nlink"] == 1, message
    elif scenario["expected_temp_state"] == "same-inode-nlink-2":
        assert temp_after["mode"] == 0o600 and temp_after["nlink"] == 2, message
        assert temp_after["dev"] == final_after["dev"], message
        assert temp_after["ino"] == final_after["ino"], message
        assert temp_after["sha256"] == final_after["sha256"], message
    else:
        raise AssertionError(message)

    if scenario["fault"] == "cases-boundary":
        events = json.loads(
            (target_root / "pytest-events.json").read_text(encoding="utf-8")
        )
        assert len(events["cases"]) == 4096, message
    if scenario["fault"] == "nodeid-boundary":
        events = json.loads(
            (target_root / "pytest-events.json").read_text(encoding="utf-8")
        )
        fixture_nodeid = receipt["nodeid_fixture"]["nodeid"]
        matching = [case for case in events["cases"] if case["nodeid"] == fixture_nodeid]
        assert len(matching) == 1, message
        assert len(str(fixture_nodeid).encode("utf-8", "strict")) == 4096, message
    if scenario["fault"] == "serialized-boundary":
        final = target_root / "pytest-events.json"
        fixture = receipt["serialized_fixture"]
        assert final.stat().st_size == 8388608, message
        assert stat.S_IMODE(final.stat().st_mode) == 0o600, message
        assert final.stat().st_nlink == 1, message
        assert _sha256(final) == fixture["expected_content_sha256"], message
        events = json.loads(final.read_text(encoding="utf-8"))
        assert len(events["cases"]) == fixture["case_count"], message
        expected_phases = {
            phase: {"outcome": "passed", "wasxfail": False}
            for phase in ("setup", "call", "teardown")
        }
        assert all(
            case["xfail_marked"] is False and case["phases"] == expected_phases
            for case in events["cases"]
        ), message
    for lane in ("capture", "retention"):
        replay = execution["replays"][lane]
        gate_path = attempt / lane / "gate.json"
        if not gate_path.exists():
            assert lane == target and not expects_gate, message
            assert replay["gate"] is None, message
            assert replay["returncode"] == 2, message
            assert replay["stdout"] == "", message
            assert replay["stderr"] == "SECURITY_COVERAGE_INPUT_INVALID\n", message
            continue
        runner_gate = json.loads(gate_path.read_text(encoding="utf-8"))
        assert replay["gate"] == runner_gate, message
        assert replay["returncode"] == (0 if runner_gate["passed"] else 1), message


def _b3f_outer_parameter_id(scenario: dict[str, object]) -> str:
    outer_nodeid = scenario["outer_nodeid"]
    assert isinstance(outer_nodeid, str)
    return outer_nodeid.rsplit("[", 1)[1][:-1]


@pytest.mark.parametrize(
    "scenario",
    tuple(
        pytest.param(scenario, id=_b3f_outer_parameter_id(scenario))
        for scenario in B3F_IMPLEMENTED_LIMIT_SCENARIOS
    ),
    ids=tuple(
        _b3f_outer_parameter_id(scenario)
        for scenario in B3F_IMPLEMENTED_LIMIT_SCENARIOS
    ),
)
def test_s18_b3f_events_limits_real_runner(scenario):
    execution = _run_b3f_real_scenario(scenario)
    _assert_b3f_real_scenario(execution, scenario)


@pytest.mark.parametrize(
    "scenario",
    tuple(
        pytest.param(scenario, id=_b3f_outer_parameter_id(scenario))
        for scenario in B3F_IMPLEMENTED_WRITER_SCENARIOS
    ),
    ids=tuple(
        _b3f_outer_parameter_id(scenario)
        for scenario in B3F_IMPLEMENTED_WRITER_SCENARIOS
    ),
)
def test_s18_b3f_events_writer_real_runner(scenario):
    execution = _run_b3f_real_scenario(scenario)
    _assert_b3f_real_scenario(execution, scenario)


def _b3f_existing_attempt_recursive_manifest(
    root: Path,
) -> list[dict[str, object]]:
    assert root.is_absolute()
    records: list[dict[str, object]] = []
    pending = [(Path("."), root)]
    while pending:
        relative, path = pending.pop()
        value = path.lstat()
        entry_type: str
        content_sha256: str | None = None
        symlink_target: str | None = None
        symlink_target_sha256: str | None = None
        if stat.S_ISDIR(value.st_mode):
            entry_type = "directory"
            children = sorted(path.iterdir(), key=lambda child: os.fsencode(child.name))
            pending.extend(
                (relative / child.name, child) for child in reversed(children)
            )
        elif stat.S_ISREG(value.st_mode):
            entry_type = "regular"
            descriptor = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
            )
            try:
                opened = os.fstat(descriptor)
                assert (opened.st_dev, opened.st_ino) == (value.st_dev, value.st_ino)
                digest = hashlib.sha256()
                content_size = 0
                while True:
                    chunk = os.read(descriptor, 65536)
                    if not chunk:
                        break
                    content_size += len(chunk)
                    digest.update(chunk)
            finally:
                os.close(descriptor)
            assert content_size == value.st_size
            content_sha256 = digest.hexdigest()
        elif stat.S_ISLNK(value.st_mode):
            entry_type = "symlink"
            symlink_target = os.readlink(path)
            symlink_target_sha256 = hashlib.sha256(
                os.fsencode(symlink_target)
            ).hexdigest()
        else:
            raise AssertionError(f"unsupported existing-attempt fixture type: {path}")
        records.append(
            {
                "relative_path": "."
                if relative == Path(".")
                else relative.as_posix(),
                "entry_type": entry_type,
                "mode": stat.S_IMODE(value.st_mode),
                "dev": value.st_dev,
                "ino": value.st_ino,
                "nlink": value.st_nlink,
                "size": value.st_size,
                "content_sha256": content_sha256,
                "symlink_target": symlink_target,
                "symlink_target_sha256": symlink_target_sha256,
            }
        )
    records.sort(key=lambda entry: os.fsencode(str(entry["relative_path"])))
    return records


def _b3f_existing_attempt_manifest_bytes(
    manifest: list[dict[str, object]],
) -> bytes:
    return (
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _b3f_existing_attempt_runner_source_order(source: str) -> dict[str, int]:
    lines = source.splitlines()

    def exact_line(value: str) -> int:
        matches = [index for index, line in enumerate(lines, 1) if line == value]
        assert len(matches) == 1, (value, matches)
        return matches[0]

    invalid_stderr_line = exact_line(
        '  echo "SECURITY_COVERAGE_RUNNER_INPUT_INVALID" >&2'
    )
    invalid_exit_matches = [
        index
        for index, line in enumerate(lines, 1)
        if line == "  exit 2" and invalid_stderr_line < index <= invalid_stderr_line + 2
    ]
    assert len(invalid_exit_matches) == 1
    source_order = {
        "input_guard_shell_line": exact_line(
            'if ! python3 -I -B - "$artifact_root" "$run_id" "$attempt" <<\'PY\''
        ),
        "root_exists_guard_line": exact_line(
            "if not root.is_absolute() or root.exists():"
        ),
        "invalid_stderr_line": invalid_stderr_line,
        "invalid_exit_line": invalid_exit_matches[0],
        "platform_case_line": exact_line('case "$(uname -s)/$(uname -m)" in'),
        "repository_cd_line": exact_line('cd "$repository_root" || exit 2'),
        "run_one_definition_line": exact_line("run_one() {"),
        "uv_command_line": exact_line(
            '    uv run --frozen --no-sync python -I -B "$bootstrap_path"'
        ),
        "capture_invocation_line": exact_line(
            "run_one capture scripts.capture_test_gate scripts/capture_test_gate.py "
            "tests/contract/test_evidence_capture.py .coverage-capture || overall_status=1"
        ),
        "retention_invocation_line": exact_line(
            "run_one retention scripts.manage_evidence_retention "
            "scripts/manage_evidence_retention.py "
            "tests/contract/test_evidence_retention.py .coverage-retention || overall_status=1"
        ),
    }
    assert (
        source_order["input_guard_shell_line"]
        < source_order["root_exists_guard_line"]
        < source_order["invalid_stderr_line"]
        < source_order["invalid_exit_line"]
        < source_order["platform_case_line"]
        < source_order["repository_cd_line"]
        < source_order["run_one_definition_line"]
        < source_order["uv_command_line"]
        < source_order["capture_invocation_line"]
        < source_order["retention_invocation_line"]
    )
    return source_order


def _run_b3f_existing_attempt_scenario(
    scenario: dict[str, object],
) -> dict[str, object]:
    assert scenario["scenario_id"] == "B3F-L-012-existing-attempt:runner"
    assert scenario["target"] == "runner"
    assert scenario["fault"] == "existing-attempt"
    execution_root = Path(
        tempfile.mkdtemp(prefix="ai-auto-lrc-s18-b3f-existing-attempt-", dir="/private/tmp")
    )
    print(f"B3F_EXISTING_ATTEMPT_EVIDENCE_ROOT={execution_root}")
    attempt_root = execution_root / "attempt-001"
    attempt_root.mkdir(mode=0o700)
    attempt_root.chmod(0o700)
    preserve = attempt_root / "preserve.txt"
    preserve_bytes = b"B3f existing attempt preserved\n"
    preserve.write_bytes(preserve_bytes)
    preserve.chmod(0o640)
    empty = attempt_root / "empty.bin"
    empty.write_bytes(b"")
    empty.chmod(0o440)
    nested = attempt_root / "nested"
    nested.mkdir(mode=0o750)
    nested.chmod(0o750)
    binary = nested / "binary.bin"
    binary_bytes = b"\x00\xffB3f\x80existing-attempt\n"
    binary.write_bytes(binary_bytes)
    binary.chmod(0o600)
    hardlink_source = attempt_root / "hardlink-source.bin"
    hardlink_bytes = b"B3f hardlink identity\x00\xfe\n"
    hardlink_source.write_bytes(hardlink_bytes)
    hardlink_source.chmod(0o600)
    hardlink_peer = attempt_root / "hardlink-peer.bin"
    os.link(hardlink_source, hardlink_peer, follow_symlinks=False)
    symlink = attempt_root / "nested-link"
    symlink_target = "nested/binary.bin"
    os.symlink(symlink_target, symlink)

    tripwire_directory = execution_root / "tripwire-bin"
    tripwire_directory.mkdir(mode=0o700)
    tripwire = tripwire_directory / "uv"
    tripwire_marker = execution_root / "uv-invoked.marker"
    assert "'" not in os.fspath(tripwire_marker)
    tripwire.write_text(
        "#!/bin/sh\n"
        "umask 077\n"
        f"printf '%s\\n' invoked > '{os.fspath(tripwire_marker)}'\n"
        "exit 97\n",
        encoding="utf-8",
    )
    tripwire.chmod(0o700)
    assert not tripwire_marker.exists()

    before_manifest = _b3f_existing_attempt_recursive_manifest(attempt_root)
    before_manifest_bytes = _b3f_existing_attempt_manifest_bytes(before_manifest)
    runner_source = RUNNER.read_text(encoding="utf-8")
    runner_hash_before = _sha256(RUNNER)
    source_order = _b3f_existing_attempt_runner_source_order(runner_source)
    argv = [
        os.fspath(RUNNER),
        os.fspath(attempt_root),
        "s18-b3f-existing-attempt",
        "1",
    ]
    environment = os.environ.copy()
    environment["PATH"] = (
        os.fspath(tripwire_directory) + os.pathsep + environment["PATH"]
    )
    deadline_seconds = 10
    started = time.monotonic()
    try:
        result = subprocess.run(
            argv,
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            check=False,
            timeout=deadline_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        _write_json(
            execution_root / "runner-timeout-receipt.json",
            {
                "schema_version": 1,
                "scenario_id": scenario["scenario_id"],
                "deadline_seconds": deadline_seconds,
                "stdout_sha256": hashlib.sha256(exc.stdout or b"").hexdigest(),
                "stderr_sha256": hashlib.sha256(exc.stderr or b"").hexdigest(),
            },
        )
        raise
    elapsed_seconds = time.monotonic() - started
    stdout_path = execution_root / "runner.stdout.bin"
    stderr_path = execution_root / "runner.stderr.bin"
    stdout_path.write_bytes(result.stdout)
    stderr_path.write_bytes(result.stderr)
    runner_hash_after = _sha256(RUNNER)
    after_manifest = _b3f_existing_attempt_recursive_manifest(attempt_root)
    after_manifest_bytes = _b3f_existing_attempt_manifest_bytes(after_manifest)
    before_paths = {str(entry["relative_path"]) for entry in before_manifest}
    after_paths = {str(entry["relative_path"]) for entry in after_manifest}
    generated_artifact_names = {
        "command.json",
        "environment.json",
        "runner-error.json",
        "gate.json",
        "junit.xml",
        "coverage.json",
        "pytest-events.json",
        "plugin-identity.json",
        "run-manifest.json",
    }
    generated_artifacts = sorted(
        str(entry["relative_path"])
        for entry in after_manifest
        if Path(str(entry["relative_path"])).name in generated_artifact_names
    )
    receipt = {
        "schema_version": 1,
        "scenario_id": scenario["scenario_id"],
        "target": "runner",
        "fault": "existing-attempt",
        "uses_copied_repository": False,
        "uses_fake_uv": False,
        "uses_uv_tripwire": True,
        "mutated_files": [],
        "runner": {
            "path": os.fspath(RUNNER),
            "sha256_before": runner_hash_before,
            "sha256_after": runner_hash_after,
            "argv": argv,
            "cwd": os.fspath(REPOSITORY_ROOT),
            "deadline_seconds": deadline_seconds,
            "elapsed_seconds": elapsed_seconds,
            "source_order": source_order,
        },
        "environment_contract": {
            "mode": "inherited-with-uv-tripwire-path-prefix",
            "path_prefix": os.fspath(tripwire_directory),
            "explicitly_set": ["PATH"],
            "explicitly_unset": [],
        },
        "attempt_root": {
            "absolute_path": os.fspath(attempt_root),
            "root_identity_before": before_manifest[0],
            "root_identity_after": after_manifest[0],
            "recursive_manifest_before": before_manifest,
            "recursive_manifest_after": after_manifest,
            "manifest_sha256_before": hashlib.sha256(
                before_manifest_bytes
            ).hexdigest(),
            "manifest_sha256_after": hashlib.sha256(
                after_manifest_bytes
            ).hexdigest(),
            "manifest_bytes_before": len(before_manifest_bytes),
            "manifest_bytes_after": len(after_manifest_bytes),
        },
        "fixture": {
            "marker_path": "preserve.txt",
            "marker_bytes_sha256": hashlib.sha256(preserve_bytes).hexdigest(),
            "empty_path": "empty.bin",
            "binary_path": "nested/binary.bin",
            "binary_bytes_sha256": hashlib.sha256(binary_bytes).hexdigest(),
            "hardlink_paths": ["hardlink-peer.bin", "hardlink-source.bin"],
            "hardlink_bytes_sha256": hashlib.sha256(hardlink_bytes).hexdigest(),
            "symlink_path": "nested-link",
            "symlink_target": symlink_target,
        },
        "tripwire": {
            "uv_path": os.fspath(tripwire),
            "uv_sha256": _sha256(tripwire),
            "marker_path": os.fspath(tripwire_marker),
            "invoked": tripwire_marker.exists(),
        },
        "result": {
            "outer_exit": result.returncode,
            "stdout_bytes_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "stderr_bytes_sha256": hashlib.sha256(result.stderr).hexdigest(),
            "stdout_exact": result.stdout.decode("utf-8", "strict"),
            "stderr_exact": result.stderr.decode("utf-8", "strict"),
        },
        "generated": {
            "capture_exists": (attempt_root / "capture").exists(),
            "retention_exists": (attempt_root / "retention").exists(),
            "unexpected_entries": sorted(after_paths - before_paths, key=os.fsencode),
            "missing_entries": sorted(before_paths - after_paths, key=os.fsencode),
            "generated_artifacts": generated_artifacts,
            "pytest_started": tripwire_marker.exists()
            or any(Path(path).name == "junit.xml" for path in after_paths),
            "gate_started": any(Path(path).name == "gate.json" for path in after_paths),
        },
    }
    receipt_path = execution_root / "existing-attempt-receipt.json"
    _write_json(receipt_path, receipt)
    return {
        "root": execution_root,
        "attempt_root": attempt_root,
        "result": result,
        "receipt": receipt,
        "receipt_path": receipt_path,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "tripwire_marker": tripwire_marker,
    }


def _assert_b3f_existing_attempt_scenario(
    execution: dict[str, object], scenario: dict[str, object]
) -> None:
    root = execution["root"]
    attempt_root = execution["attempt_root"]
    result = execution["result"]
    receipt = execution["receipt"]
    assert isinstance(root, Path) and isinstance(attempt_root, Path)
    assert isinstance(result, subprocess.CompletedProcess)
    message = f"B3f existing-attempt evidence retained at {root}"
    assert result.returncode == 2, message
    assert result.stdout == b"", message
    assert result.stderr == b"SECURITY_COVERAGE_RUNNER_INPUT_INVALID\n", message
    assert receipt["scenario_id"] == scenario["scenario_id"]
    assert receipt["target"] == scenario["target"] == "runner"
    assert receipt["fault"] == scenario["fault"] == "existing-attempt"
    assert receipt["uses_copied_repository"] is False
    assert receipt["uses_fake_uv"] is False
    assert receipt["uses_uv_tripwire"] is True
    assert receipt["mutated_files"] == []
    runner = receipt["runner"]
    expected_runner_sha256 = (
        "ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8"
    )
    assert runner["path"] == os.fspath(RUNNER)
    assert runner["sha256_before"] == runner["sha256_after"] == expected_runner_sha256
    assert _sha256(RUNNER) == expected_runner_sha256
    assert runner["argv"] == [
        os.fspath(RUNNER),
        os.fspath(attempt_root),
        "s18-b3f-existing-attempt",
        "1",
    ]
    assert len(runner["argv"]) == 4
    assert Path(runner["argv"][1]).is_absolute()
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", runner["argv"][2])
    assert runner["argv"][3] == "1"
    assert runner["cwd"] == os.fspath(REPOSITORY_ROOT)
    assert runner["deadline_seconds"] == 10
    assert 0 < runner["elapsed_seconds"] < 10
    source_order = runner["source_order"]
    assert list(source_order) == [
        "input_guard_shell_line",
        "root_exists_guard_line",
        "invalid_stderr_line",
        "invalid_exit_line",
        "platform_case_line",
        "repository_cd_line",
        "run_one_definition_line",
        "uv_command_line",
        "capture_invocation_line",
        "retention_invocation_line",
    ]
    assert list(source_order.values()) == sorted(source_order.values())
    environment_contract = receipt["environment_contract"]
    assert environment_contract == {
        "mode": "inherited-with-uv-tripwire-path-prefix",
        "path_prefix": os.fspath(root / "tripwire-bin"),
        "explicitly_set": ["PATH"],
        "explicitly_unset": [],
    }
    tripwire = receipt["tripwire"]
    assert tripwire["uv_path"] == os.fspath(root / "tripwire-bin" / "uv")
    assert tripwire["uv_sha256"] == _sha256(Path(tripwire["uv_path"]))
    assert tripwire["marker_path"] == os.fspath(execution["tripwire_marker"])
    assert tripwire["invoked"] is False
    assert not execution["tripwire_marker"].exists()
    assert attempt_root not in Path(execution["receipt_path"]).parents
    assert attempt_root not in Path(execution["stdout_path"]).parents
    assert attempt_root not in Path(execution["stderr_path"]).parents
    assert Path(execution["receipt_path"]).read_text(encoding="utf-8")
    assert Path(execution["stdout_path"]).read_bytes() == result.stdout
    assert Path(execution["stderr_path"]).read_bytes() == result.stderr
    result_receipt = receipt["result"]
    assert result_receipt == {
        "outer_exit": 2,
        "stdout_bytes_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_bytes_sha256": hashlib.sha256(
            b"SECURITY_COVERAGE_RUNNER_INPUT_INVALID\n"
        ).hexdigest(),
        "stdout_exact": "",
        "stderr_exact": "SECURITY_COVERAGE_RUNNER_INPUT_INVALID\n",
    }

    attempt = receipt["attempt_root"]
    assert attempt["absolute_path"] == os.fspath(attempt_root)
    assert Path(attempt["absolute_path"]).is_absolute()
    before = attempt["recursive_manifest_before"]
    after = attempt["recursive_manifest_after"]
    assert before == after
    assert attempt["root_identity_before"] == attempt["root_identity_after"]
    assert attempt["root_identity_before"] == before[0]
    assert before[0]["relative_path"] == "."
    assert before[0]["entry_type"] == "directory"
    assert before[0]["mode"] == 0o700
    assert (before[0]["dev"], before[0]["ino"]) == (
        after[0]["dev"],
        after[0]["ino"],
    )
    before_bytes = _b3f_existing_attempt_manifest_bytes(before)
    after_bytes = _b3f_existing_attempt_manifest_bytes(after)
    assert attempt["manifest_sha256_before"] == hashlib.sha256(before_bytes).hexdigest()
    assert attempt["manifest_sha256_after"] == hashlib.sha256(after_bytes).hexdigest()
    assert attempt["manifest_sha256_before"] == attempt["manifest_sha256_after"]
    assert attempt["manifest_bytes_before"] == len(before_bytes)
    assert attempt["manifest_bytes_after"] == len(after_bytes)
    assert [entry["relative_path"] for entry in before] == sorted(
        (entry["relative_path"] for entry in before), key=os.fsencode
    )
    by_path = {entry["relative_path"]: entry for entry in before}
    assert list(by_path) == [
        ".",
        "empty.bin",
        "hardlink-peer.bin",
        "hardlink-source.bin",
        "nested",
        "nested-link",
        "nested/binary.bin",
        "preserve.txt",
    ]
    assert {path: entry["entry_type"] for path, entry in by_path.items()} == {
        ".": "directory",
        "empty.bin": "regular",
        "hardlink-peer.bin": "regular",
        "hardlink-source.bin": "regular",
        "nested": "directory",
        "nested-link": "symlink",
        "nested/binary.bin": "regular",
        "preserve.txt": "regular",
    }
    assert {
        path: by_path[path]["mode"]
        for path in by_path
        if path != "nested-link"
    } == {
        ".": 0o700,
        "empty.bin": 0o440,
        "hardlink-peer.bin": 0o600,
        "hardlink-source.bin": 0o600,
        "nested": 0o750,
        "nested/binary.bin": 0o600,
        "preserve.txt": 0o640,
    }
    assert by_path["nested-link"]["mode"] == stat.S_IMODE(
        (attempt_root / "nested-link").lstat().st_mode
    )
    fixture = receipt["fixture"]
    assert by_path[fixture["marker_path"]]["content_sha256"] == fixture[
        "marker_bytes_sha256"
    ]
    assert by_path[fixture["empty_path"]]["size"] == 0
    assert by_path[fixture["empty_path"]]["content_sha256"] == hashlib.sha256(
        b""
    ).hexdigest()
    assert by_path[fixture["binary_path"]]["content_sha256"] == fixture[
        "binary_bytes_sha256"
    ]
    hardlink_peer, hardlink_source = (
        by_path[path] for path in fixture["hardlink_paths"]
    )
    assert hardlink_peer["content_sha256"] == hardlink_source["content_sha256"]
    assert hardlink_peer["content_sha256"] == fixture["hardlink_bytes_sha256"]
    assert (hardlink_peer["dev"], hardlink_peer["ino"]) == (
        hardlink_source["dev"],
        hardlink_source["ino"],
    )
    assert hardlink_peer["nlink"] == hardlink_source["nlink"] == 2
    symlink = by_path[fixture["symlink_path"]]
    assert symlink["entry_type"] == "symlink"
    assert symlink["content_sha256"] is None
    assert symlink["symlink_target"] == fixture["symlink_target"]
    assert symlink["symlink_target_sha256"] == hashlib.sha256(
        os.fsencode(fixture["symlink_target"])
    ).hexdigest()
    assert all(
        entry["symlink_target"] is None
        and entry["symlink_target_sha256"] is None
        for entry in before
        if entry["entry_type"] != "symlink"
    )
    assert all(
        entry["content_sha256"] is None
        for entry in before
        if entry["entry_type"] != "regular"
    )
    assert receipt["generated"] == {
        "capture_exists": False,
        "retention_exists": False,
        "unexpected_entries": [],
        "missing_entries": [],
        "generated_artifacts": [],
        "pytest_started": False,
        "gate_started": False,
    }
    assert not (attempt_root / "capture").exists()
    assert not (attempt_root / "retention").exists()


@pytest.mark.parametrize(
    "scenario",
    tuple(
        pytest.param(scenario, id=_b3f_outer_parameter_id(scenario))
        for scenario in _B3F_IMPLEMENTED_RUNNER_SCENARIOS
    ),
    ids=tuple(
        _b3f_outer_parameter_id(scenario)
        for scenario in _B3F_IMPLEMENTED_RUNNER_SCENARIOS
    ),
)
def test_s18_b3f_existing_attempt_real_runner(scenario):
    execution = _run_b3f_existing_attempt_scenario(scenario)
    _assert_b3f_existing_attempt_scenario(execution, scenario)


def test_b3f_s_real_runner_parameters_are_derived_from_implemented_authority():
    functions = (
        (
            "test_s18_b3f_events_limits_real_runner",
            test_s18_b3f_events_limits_real_runner,
        ),
        (
            "test_s18_b3f_events_writer_real_runner",
            test_s18_b3f_events_writer_real_runner,
        ),
        (
            "test_s18_b3f_existing_attempt_real_runner",
            test_s18_b3f_existing_attempt_real_runner,
        ),
    )
    parameter_ids: list[str] = []
    parameter_nodeids: set[str] = set()
    for function_name, function in functions:
        marks = [mark for mark in function.pytestmark if mark.name == "parametrize"]
        assert len(marks) == 1
        ids = tuple(marks[0].kwargs["ids"])
        assert tuple(parameter.id for parameter in marks[0].args[1]) == ids
        parameter_ids.extend(ids)
        parameter_nodeids.update(
            "tests/contract/test_security_coverage_gate.py::"
            + function_name
            + f"[{parameter_id}]"
            for parameter_id in ids
        )
    expected_ids = tuple(
        _b3f_outer_parameter_id(scenario)
        for scenario in B3F_IMPLEMENTED_LIMIT_SCENARIOS
        + B3F_IMPLEMENTED_WRITER_SCENARIOS
        + _B3F_IMPLEMENTED_RUNNER_SCENARIOS
    )
    assert tuple(parameter_ids) == expected_ids
    assert {
        scenario["outer_nodeid"]
        for scenario in B3F_SCENARIOS
        if scenario["status"] == "implemented"
    } == parameter_nodeids


def test_b3f_s_real_runner_collects_exact_implemented_authority_nodeids():
    test_file = "tests/contract/test_security_coverage_gate.py"
    test_names = (
        "test_s18_b3f_events_limits_real_runner",
        "test_s18_b3f_events_writer_real_runner",
        "test_s18_b3f_existing_attempt_real_runner",
    )
    environment = os.environ.copy()
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "--noconftest",
            "-c",
            "pyproject.toml",
            *(f"{test_file}::{test_name}" for test_name in test_names),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    collected = {
        line for line in result.stdout.splitlines() if line.startswith(f"{test_file}::")
    }
    assert collected == {
        scenario["outer_nodeid"]
        for scenario in B3F_SCENARIOS
        if scenario["status"] == "implemented"
    }


def test_s18_runner_ignores_hostile_pytest_environment_and_conftest(tmp_path):
    isolated_repository = tmp_path / "repository"
    for directory in ("scripts", "packaging", "tests/fixtures"):
        shutil.copytree(REPOSITORY_ROOT / directory, isolated_repository / directory)
    target_tests = isolated_repository / "tests/contract"
    target_tests.mkdir(parents=True)
    for name in ("test_evidence_capture.py", "test_evidence_retention.py"):
        shutil.copy2(REPOSITORY_ROOT / "tests/contract" / name, target_tests / name)
    shutil.copy2(REPOSITORY_ROOT / "pyproject.toml", isolated_repository / "pyproject.toml")
    shutil.copy2(REPOSITORY_ROOT / "uv.lock", isolated_repository / "uv.lock")

    hostile_log = tmp_path / "hostile-pytest.log"
    plugin_source = """from pathlib import Path
import os

def pytest_configure(config):
    del config
    with Path(os.environ[\"S18_HOSTILE_PYTEST_LOG\"]).open(\"a\", encoding=\"utf-8\") as stream:
        stream.write(__name__ + \"\\n\")
"""
    (isolated_repository / "hostile_env_plugin.py").write_text(
        plugin_source, encoding="utf-8"
    )
    (isolated_repository / "hostile_addopts_plugin.py").write_text(
        plugin_source, encoding="utf-8"
    )
    (isolated_repository / "conftest.py").write_text(
        plugin_source, encoding="utf-8"
    )
    hostile_pythonpath = tmp_path / "hostile-pythonpath"
    (hostile_pythonpath / "scripts").mkdir(parents=True)
    (hostile_pythonpath / "pytest_cov").mkdir()
    sentinel_source = """from pathlib import Path
import os
with Path(os.environ["S18_HOSTILE_PYTEST_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(__name__ + "\\n")
"""
    (hostile_pythonpath / "sitecustomize.py").write_text(
        sentinel_source, encoding="utf-8"
    )
    (hostile_pythonpath / "scripts/__init__.py").write_text(
        sentinel_source, encoding="utf-8"
    )
    (hostile_pythonpath / "scripts/pytest_security_events.py").write_text(
        sentinel_source, encoding="utf-8"
    )
    (hostile_pythonpath / "pytest_cov/__init__.py").write_text(
        sentinel_source, encoding="utf-8"
    )
    (hostile_pythonpath / "pytest_cov/plugin.py").write_text(
        sentinel_source, encoding="utf-8"
    )

    shim_directory = tmp_path / "bin"
    shim_directory.mkdir()
    fake_uv = shim_directory / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env python3
import os
import sys

arguments = sys.argv[1:]
if arguments[:3] != [\"run\", \"--frozen\", \"--no-sync\"]:
    raise SystemExit(2)
arguments = arguments[3:]
if not arguments or arguments[0] != \"python\":
    raise SystemExit(2)
python = os.environ[\"S18_REAL_PYTHON\"]
os.execv(python, [python, *arguments[1:]])
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o700)
    subprocess.run(["git", "init", "-q"], cwd=isolated_repository, check=True)
    subprocess.run(["git", "add", "."], cwd=isolated_repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=S18 Test",
            "-c",
            "user.email=s18@example.invalid",
            "commit",
            "-qm",
            "test fixture",
        ],
        cwd=isolated_repository,
        check=True,
    )

    attempt_root = tmp_path / "attempt-001"
    environment = os.environ.copy()
    environment.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    environment["PATH"] = os.fspath(shim_directory) + os.pathsep + environment["PATH"]
    environment["PYTHONPATH"] = os.fspath(hostile_pythonpath)
    environment["PYTEST_PLUGINS"] = "hostile_env_plugin"
    environment["PYTEST_ADDOPTS"] = "-p hostile_addopts_plugin"
    environment["S18_HOSTILE_PYTEST_LOG"] = os.fspath(hostile_log)
    environment["S18_REAL_PYTHON"] = sys.executable
    result = subprocess.run(
        [
            os.fspath(isolated_repository / "scripts/run_security_coverage.sh"),
            os.fspath(attempt_root),
            "s18-hostile-pytest-environment",
            "1",
        ],
        cwd=isolated_repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert not hostile_log.exists(), hostile_log.read_text(encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    for target in ("capture", "retention"):
        target_root = attempt_root / target
        command = json.loads((target_root / "command.json").read_text(encoding="utf-8"))
        assert command["schema_version"] == 4
        assert command["sanitized_environment"] == {
            "COVERAGE_FILE": os.fspath(target_root / (".coverage-" + target)),
            "PYTHONHOME": None,
            "PYTHONPATH": None,
            "PYTHONUSERBASE": None,
            "PYTEST_ADDOPTS": None,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTEST_PLUGINS": None,
            "UV_PROJECT_ENVIRONMENT": None,
            "UV_PYTHON": None,
        }
        argv = command["argv"]
        assert argv.count("--noconftest") == 1
        assert [argv[index : index + 2] for index in range(len(argv) - 1)].count(
            ["-c", "pyproject.toml"]
        ) == 1
        for plugin in (
            "no:cacheprovider",
            "pytest_cov.plugin",
            "scripts.pytest_security_events",
        ):
            assert [argv[index : index + 2] for index in range(len(argv) - 1)].count(
                ["-p", plugin]
            ) == 1
        gate = json.loads((target_root / "gate.json").read_text(encoding="utf-8"))
        assert gate["passed"] is True
        assert gate["failures"] == []
        assert "file" not in json.dumps(gate["runtime_identity"], sort_keys=True)
        identity = json.loads(
            (target_root / "plugin-identity.json").read_text(encoding="utf-8")
        )
        local = identity["plugins"]["scripts.pytest_security_events"]
        assert local["file"] == os.fspath(
            (isolated_repository / "scripts/pytest_security_events.py").resolve(
                strict=True
            )
        )
        assert local["sha256"] == _sha256(
            isolated_repository / "scripts/pytest_security_events.py"
        )
        cov = identity["plugins"]["pytest_cov.plugin"]
        assert cov["distribution"] == "pytest-cov"
        assert cov["entry"] == "pytest_cov/plugin.py"
        assert cov["sha256"] == identity["distributions"]["pytest-cov"][
            "installed"
        ]["required_entries"]["pytest_cov/plugin.py"]["sha256"]


def test_s18_runner_rejects_target_test_drift_during_pytest(tmp_path):
    isolated_repository = tmp_path / "repository"
    copied_paths = (
        "pyproject.toml",
        "packaging/security-coverage-policy.toml",
        "packaging/security-coverage-manifest.json",
        "scripts/run_security_coverage.sh",
        "scripts/verify_security_coverage.py",
        "scripts/security_pytest_bootstrap.py",
        "scripts/pytest_security_events.py",
        "uv.lock",
        "scripts/capture_test_gate.py",
        "scripts/manage_evidence_retention.py",
        "tests/contract/test_evidence_capture.py",
        "tests/contract/test_evidence_retention.py",
    )
    for relative in copied_paths:
        destination = isolated_repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative, destination)

    policy = load_policy()
    manifest = load_manifest(policy=policy)
    runner_name = "macos" if sys.platform == "darwin" else "linux"
    fixture_root = tmp_path / "controlled-pytest"
    for target in ("capture", "retention"):
        target_fixture = fixture_root / target
        target_fixture.mkdir(parents=True)
        source_path = policy["scripts"][target]["path"]
        _write_json(
            target_fixture / "coverage.json",
            _coverage_document(manifest, target, source_path),
        )
        _junit_document(_required_nodeids(manifest, target, runner_name)).write(
            target_fixture / "junit.xml",
            encoding="utf-8",
            xml_declaration=True,
        )
        _write_events_json(
            target_fixture / "pytest-events.json",
            _pytest_events_document(
                _required_nodeids(manifest, target, runner_name),
                run_id="s18-controlled-test-drift",
                target=target,
                runner=runner_name,
                attempt=1,
                test_file=policy["scripts"][target]["test_file"],
            ),
        )
        _write_json(
            target_fixture / "plugin-identity.json",
            _plugin_identity_document(
                run_id="s18-controlled-test-drift",
                target=target,
                runner=runner_name,
                attempt=1,
                repository_root=isolated_repository,
            ),
        )

    shim_directory = tmp_path / "bin"
    shim_directory.mkdir()
    fake_uv = shim_directory / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env python3
import os
import shutil
import sys
from pathlib import Path

arguments = sys.argv[1:]
if arguments[:7] == ["run", "--frozen", "--no-sync", "python", "-I", "-B", "-c"]:
    statement = arguments[7]
    if "coverage.__version__" in statement:
        print("7.16.0")
        raise SystemExit(0)
    if "pytest.__version__" in statement:
        print("9.0.2")
        raise SystemExit(0)
    raise SystemExit(2)

if (
    arguments[:6] != ["run", "--frozen", "--no-sync", "python", "-I", "-B"]
    or len(arguments) < 9
    or not Path(arguments[6]).is_absolute()
    or not arguments[6].endswith("/scripts/security_pytest_bootstrap.py")
    or arguments[8] != "--"
):
    raise SystemExit(2)
test_file = next(item for item in arguments if item.startswith("tests/contract/test_evidence_"))
target = "capture" if test_file.endswith("test_evidence_capture.py") else "retention"
fixture = Path(os.environ["S18_CONTROLLED_PYTEST_FIXTURES"]) / target
junit = Path(next(item.split("=", 1)[1] for item in arguments if item.startswith("--junitxml=")))
coverage = Path(
    next(
        item.removeprefix("--cov-report=json:")
        for item in arguments
        if item.startswith("--cov-report=json:")
    )
)
events = Path(
    next(
        item.removeprefix("--security-events=")
        for item in arguments
        if item.startswith("--security-events=")
    )
)
identity = Path(
    next(
        item.removeprefix("--plugin-identity=")
        for item in arguments
        if item.startswith("--plugin-identity=")
    )
)
shutil.copyfile(fixture / "junit.xml", junit)
shutil.copyfile(fixture / "coverage.json", coverage)
shutil.copyfile(fixture / "pytest-events.json", events)
shutil.copyfile(fixture / "plugin-identity.json", identity)
coverage_data = os.environ.get("COVERAGE_FILE")
if coverage_data:
    Path(coverage_data).write_bytes(b"controlled raw coverage data\\n")
if target == "capture":
    with Path(test_file).open("ab") as stream:
        stream.write(b"\\n# controlled drift during pytest\\n")
print("controlled pytest completed")
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o700)
    fake_git = shim_directory / "git"
    fake_git.write_text(
        """#!/bin/sh
case "$1" in
  rev-parse) printf '%040d\\n' 0 ;;
  status) printf ' M tests/contract/test_evidence_capture.py\\n' ;;
  *) exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    fake_git.chmod(0o700)

    attempt_root = tmp_path / "attempt-001"
    environment = os.environ.copy()
    environment["PATH"] = os.fspath(shim_directory) + os.pathsep + environment["PATH"]
    environment["S18_CONTROLLED_PYTEST_FIXTURES"] = os.fspath(fixture_root)
    result = subprocess.run(
        [
            os.fspath(isolated_repository / "scripts/run_security_coverage.sh"),
            os.fspath(attempt_root),
            "s18-controlled-test-drift",
            "1",
        ],
        cwd=isolated_repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    capture = attempt_root / "capture"
    expected_raw = {
        ".coverage-capture",
        "coverage.json",
        "junit.xml",
        "pytest-events.json",
        "stdout.log",
        "stderr.log",
        "environment.json",
        "command.json",
        "run-manifest.json",
        "plugin-identity.json",
        "gate.json",
        "verifier.stderr.log",
    }
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == ""
    assert expected_raw <= {path.name for path in capture.iterdir()}
    captured_environment = json.loads((capture / "environment.json").read_text())
    repository = captured_environment["repository"]
    assert repository["test_sha256_before"] != repository["test_sha256_after"]
    assert repository["test_sha256_after"] == _sha256(
        isolated_repository / "tests/contract/test_evidence_capture.py"
    )
    command = json.loads((capture / "command.json").read_text())
    assert command["exit_code"] == 0
    gate = json.loads((capture / "gate.json").read_text())
    assert gate["passed"] is False
    assert gate["failures"] == ["EVIDENCE_BINDING_INVALID"]
    retention_gate = json.loads((attempt_root / "retention/gate.json").read_text())
    assert retention_gate["passed"] is True
    assert retention_gate["failures"] == []


@pytest.mark.parametrize(
    ("scenario", "expected_failures", "pytest_exit_code"),
    [
        ("required-xfail", ["REQUIRED_TEST_XFAILED"], 0),
        ("non-strict-xpass", ["REQUIRED_TEST_XFAILED"], 0),
        (
            "strict-xpass",
            ["COMMAND_FAILED", "REQUIRED_TEST_XFAILED"],
            1,
        ),
        ("config-drift", ["EVIDENCE_TOOLCHAIN_BINDING_INVALID"], 0),
        (
            "plugin-drift",
            ["EVIDENCE_TOOLCHAIN_BINDING_INVALID", "PLUGIN_IDENTITY_INVALID"],
            0,
        ),
        ("events-missing", ["PYTEST_EVENTS_INVALID"], 0),
    ],
)
def test_s18_runner_enforces_xfail_events_and_toolchain_drift(
    tmp_path, scenario, expected_failures, pytest_exit_code
):
    isolated_repository = tmp_path / "repository"
    copied_paths = (
        "pyproject.toml",
        "packaging/security-coverage-policy.toml",
        "packaging/security-coverage-manifest.json",
        "scripts/run_security_coverage.sh",
        "scripts/verify_security_coverage.py",
        "scripts/security_pytest_bootstrap.py",
        "scripts/pytest_security_events.py",
        "uv.lock",
        "scripts/capture_test_gate.py",
        "scripts/manage_evidence_retention.py",
        "tests/contract/test_evidence_capture.py",
        "tests/contract/test_evidence_retention.py",
    )
    for relative in copied_paths:
        destination = isolated_repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative, destination)

    policy = load_policy()
    manifest = load_manifest(policy=policy)
    runner_name = "macos" if sys.platform == "darwin" else "linux"
    fixture_root = tmp_path / "controlled-pytest"
    selected_required = ""
    for target in ("capture", "retention"):
        target_fixture = fixture_root / target
        target_fixture.mkdir(parents=True)
        source_path = policy["scripts"][target]["path"]
        test_file = policy["scripts"][target]["test_file"]
        nodeids = _required_nodeids(manifest, target, runner_name)
        junit_mutation = None
        events_mutation = None
        if target == "capture" and scenario in {
            "required-xfail",
            "non-strict-xpass",
            "strict-xpass",
        }:
            selected_required = nodeids[0]
            if scenario == "required-xfail":
                junit_mutation = (selected_required, "xfail")
                events_mutation = (
                    selected_required,
                    {
                        "xfail_marked": True,
                        "phases": {
                            "setup": {"outcome": "passed", "wasxfail": False},
                            "call": {"outcome": "skipped", "wasxfail": True},
                            "teardown": {"outcome": "passed", "wasxfail": False},
                        },
                    },
                )
            elif scenario == "non-strict-xpass":
                events_mutation = (
                    selected_required,
                    {
                        "xfail_marked": True,
                        "phases": {
                            "setup": {"outcome": "passed", "wasxfail": False},
                            "call": {"outcome": "passed", "wasxfail": True},
                            "teardown": {"outcome": "passed", "wasxfail": False},
                        },
                    },
                )
            else:
                junit_mutation = (selected_required, "failure")
                events_mutation = (
                    selected_required,
                    {
                        "xfail_marked": True,
                        "phases": {
                            "setup": {"outcome": "passed", "wasxfail": False},
                            "call": {"outcome": "failed", "wasxfail": False},
                            "teardown": {"outcome": "passed", "wasxfail": False},
                        },
                    },
                )
        _write_json(
            target_fixture / "coverage.json",
            _coverage_document(manifest, target, source_path),
        )
        _junit_document(nodeids, mutation=junit_mutation).write(
            target_fixture / "junit.xml",
            encoding="utf-8",
            xml_declaration=True,
        )
        _write_events_json(
            target_fixture / "pytest-events.json",
            _pytest_events_document(
                nodeids,
                run_id="s18-controlled-xfail",
                target=target,
                runner=runner_name,
                attempt=1,
                test_file=test_file,
                mutation=events_mutation,
            ),
        )
        _write_json(
            target_fixture / "plugin-identity.json",
            _plugin_identity_document(
                run_id="s18-controlled-xfail",
                target=target,
                runner=runner_name,
                attempt=1,
                repository_root=isolated_repository,
            ),
        )

    shim_directory = tmp_path / "bin"
    shim_directory.mkdir()
    fake_uv = shim_directory / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env python3
import os
import shutil
import sys
from pathlib import Path

arguments = sys.argv[1:]
if arguments[:7] == ["run", "--frozen", "--no-sync", "python", "-I", "-B", "-c"]:
    statement = arguments[7]
    if "coverage.__version__" in statement:
        print("7.16.0")
        raise SystemExit(0)
    if "pytest.__version__" in statement:
        print("9.0.2")
        raise SystemExit(0)
    raise SystemExit(2)

if (
    arguments[:6] != ["run", "--frozen", "--no-sync", "python", "-I", "-B"]
    or len(arguments) < 9
    or not Path(arguments[6]).is_absolute()
    or not arguments[6].endswith("/scripts/security_pytest_bootstrap.py")
    or arguments[8] != "--"
):
    raise SystemExit(2)
test_file = next(item for item in arguments if item.startswith("tests/contract/test_evidence_"))
target = "capture" if test_file.endswith("test_evidence_capture.py") else "retention"
fixture = Path(os.environ["S18_CONTROLLED_PYTEST_FIXTURES"]) / target
junit = Path(next(item.split("=", 1)[1] for item in arguments if item.startswith("--junitxml=")))
coverage = Path(
    next(
        item.removeprefix("--cov-report=json:")
        for item in arguments
        if item.startswith("--cov-report=json:")
    )
)
events = Path(
    next(
        item.removeprefix("--security-events=")
        for item in arguments
        if item.startswith("--security-events=")
    )
)
identity = Path(
    next(
        item.removeprefix("--plugin-identity=")
        for item in arguments
        if item.startswith("--plugin-identity=")
    )
)
shutil.copyfile(fixture / "junit.xml", junit)
shutil.copyfile(fixture / "coverage.json", coverage)
shutil.copyfile(fixture / "plugin-identity.json", identity)
if os.environ["S18_CONTROLLED_SCENARIO"] != "events-missing" or target != "capture":
    shutil.copyfile(fixture / "pytest-events.json", events)
coverage_data = os.environ.get("COVERAGE_FILE")
if coverage_data:
    Path(coverage_data).write_bytes(b"controlled raw coverage data\\n")
scenario = os.environ["S18_CONTROLLED_SCENARIO"]
if target == "capture" and scenario == "config-drift":
    with Path("pyproject.toml").open("ab") as stream:
        stream.write(b"\\n# controlled config drift\\n")
if target == "capture" and scenario == "plugin-drift":
    with Path("scripts/pytest_security_events.py").open("ab") as stream:
        stream.write(b"\\n# controlled plugin drift\\n")
if target == "capture" and scenario == "strict-xpass":
    raise SystemExit(1)
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o700)
    fake_git = shim_directory / "git"
    fake_git.write_text(
        """#!/bin/sh
case "$1" in
  rev-parse) printf '%040d\\n' 0 ;;
  status) printf ' M controlled-xfail-evidence\\n' ;;
  *) exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    fake_git.chmod(0o700)

    attempt_root = tmp_path / "attempt-001"
    environment = os.environ.copy()
    environment["PATH"] = os.fspath(shim_directory) + os.pathsep + environment["PATH"]
    environment["S18_CONTROLLED_PYTEST_FIXTURES"] = os.fspath(fixture_root)
    environment["S18_CONTROLLED_SCENARIO"] = scenario
    result = subprocess.run(
        [
            os.fspath(isolated_repository / "scripts/run_security_coverage.sh"),
            os.fspath(attempt_root),
            "s18-controlled-xfail",
            "1",
        ],
        cwd=isolated_repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == ""
    capture = attempt_root / "capture"
    expected_raw = {
        ".coverage-capture",
        "coverage.json",
        "junit.xml",
        "stdout.log",
        "stderr.log",
        "environment.json",
        "command.json",
        "run-manifest.json",
        "plugin-identity.json",
        "gate.json",
        "verifier.stderr.log",
    }
    if scenario != "events-missing":
        expected_raw.add("pytest-events.json")
    assert expected_raw <= {path.name for path in capture.iterdir()}
    command = json.loads((capture / "command.json").read_text(encoding="utf-8"))
    assert command["schema_version"] == 4
    assert command["exit_code"] == pytest_exit_code
    assert command["sanitized_environment"] == {
        "COVERAGE_FILE": os.fspath(capture / ".coverage-capture"),
        "PYTHONHOME": None,
        "PYTHONPATH": None,
        "PYTHONUSERBASE": None,
        "PYTEST_ADDOPTS": None,
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_PLUGINS": None,
        "UV_PROJECT_ENVIRONMENT": None,
        "UV_PYTHON": None,
    }
    assert command["argv"].count("--noconftest") == 1
    assert [
        command["argv"][index : index + 2]
        for index in range(len(command["argv"]) - 1)
    ].count(["-c", "pyproject.toml"]) == 1
    assert [
        command["argv"][index : index + 2]
        for index in range(len(command["argv"]) - 1)
    ].count(["-p", "pytest_cov.plugin"]) == 1
    assert command["argv"][
        command["argv"].index("scripts.pytest_security_events") - 1 :
        command["argv"].index("scripts.pytest_security_events") + 1
    ] == ["-p", "scripts.pytest_security_events"]
    assert command["argv"][
        command["argv"].index("xfail_strict=true") - 1 :
        command["argv"].index("xfail_strict=true") + 1
    ] == ["-o", "xfail_strict=true"]
    gate = json.loads((capture / "gate.json").read_text(encoding="utf-8"))
    assert gate["schema_version"] == 5
    assert gate["failures"] == expected_failures
    if selected_required:
        required = {item["nodeid"]: item for item in gate["junit"]["required_tests"]}
        assert required[selected_required]["status"] == "xfail"
    if scenario.endswith("drift"):
        repository = json.loads(
            (capture / "environment.json").read_text(encoding="utf-8")
        )["repository"]
        stem = "pytest_config" if scenario == "config-drift" else "pytest_events_plugin"
        assert repository[stem + "_sha256_before"] != repository[stem + "_sha256_after"]


def test_s18_runner_refuses_to_overwrite_an_existing_attempt(tmp_path):
    attempt = tmp_path / "attempt-001"
    attempt.mkdir()
    marker = attempt / "preserve.txt"
    marker.write_text("original\n", encoding="utf-8")
    before = marker.read_bytes()
    result = subprocess.run(
        [str(RUNNER), str(attempt), "s18-no-overwrite", "1"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "SECURITY_COVERAGE_RUNNER_INPUT_INVALID\n"
    assert marker.read_bytes() == before
    assert set(attempt.iterdir()) == {marker}


_B3F_R_SITE_PACKAGES_PROBE = r"""
import importlib.util
import json
import sys
from pathlib import Path

bootstrap_path = Path(sys.argv[1])
executable = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("b3f_r_site_probe", bootstrap_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
derive = getattr(module, "_derive_runtime_site_packages")
site_packages = derive(executable, python_major_minor=(3, 11))
print(json.dumps({
    "dont_write_bytecode": bool(sys.flags.dont_write_bytecode),
    "isolated": bool(sys.flags.isolated),
    "no_site": bool(sys.flags.no_site),
    "site_packages": str(site_packages),
    "sys_path": sys.path,
}, sort_keys=True))
"""


_B3F_R_BOUND_LOADER_PROBE = r"""
import builtins
import hashlib
import importlib.util
import json
import site
import sys
from pathlib import Path

bootstrap_path = Path(sys.argv[1])
site_packages = Path(sys.argv[2])
expected_hashes = json.loads(sys.argv[3])
pth_marker = Path(sys.argv[4])
sitecustomize_marker = Path(sys.argv[5])
spec = importlib.util.spec_from_file_location("b3f_r_loader_probe", bootstrap_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
load = getattr(module, "_load_bound_runtime_modules")

names = ("pluggy", "coverage", "pytest", "pytest_cov", "pytest_cov.plugin")
paths = {
    "pluggy": site_packages / "pluggy/__init__.py",
    "coverage": site_packages / "coverage/__init__.py",
    "pytest": site_packages / "pytest/__init__.py",
    "pytest_cov": site_packages / "pytest_cov/__init__.py",
    "pytest_cov.plugin": site_packages / "pytest_cov/plugin.py",
}
entries = tuple({
    "module": name,
    "path": paths[name],
    "is_package": name != "pytest_cov.plugin",
    "expected_sha256": expected_hashes[name],
    "expected_size": paths[name].stat().st_size,
} for name in names)

read_ids = {}
hash_ids = {}
compile_ids = {}
compiled_codes = {}
executed = []
original_stable_read = module._stable_read
original_sha256 = module._sha256
original_compile = builtins.compile
original_exec = builtins.exec

def tracked_stable_read(path, **kwargs):
    key = str(path)
    if key in read_ids:
        raise AssertionError(f"bound entry was read more than once: {key}")
    content = original_stable_read(path, **kwargs)
    read_ids[key] = id(content)
    return content

def tracked_sha256(content):
    digest = original_sha256(content)
    hash_ids[digest] = id(content)
    return digest

def tracked_compile(source, filename, *args, **kwargs):
    code = original_compile(source, filename, *args, **kwargs)
    key = str(filename)
    if key in {str(path) for path in paths.values()}:
        compile_ids[key] = id(source)
        compiled_codes[id(code)] = key
    return code

def tracked_exec(code, globals=None, locals=None):
    key = compiled_codes.get(id(code))
    if key is not None:
        executed.append(key)
    return original_exec(code, globals, locals)

def forbidden_addsitedir(*args, **kwargs):
    raise AssertionError("site.addsitedir must not run for bound entries")

module._stable_read = tracked_stable_read
module._sha256 = tracked_sha256
builtins.compile = tracked_compile
builtins.exec = tracked_exec
site.addsitedir = forbidden_addsitedir
modules, identities = load(entries)

assert tuple(modules) == names
assert tuple(identities) == names
assert tuple(executed) == tuple(str(paths[name]) for name in names)
for name in names:
    path = paths[name]
    key = str(path)
    digest = expected_hashes[name]
    assert read_ids[key] == hash_ids[digest] == compile_ids[key]
    assert modules[name].BOUND_EXECUTED == name
    assert identities[name] == {
        "path": str(path.resolve(strict=True)),
        "sha256": digest,
        "size": path.stat().st_size,
    }
assert not pth_marker.exists()
assert not sitecustomize_marker.exists()
print(json.dumps({
    "dont_write_bytecode": bool(sys.flags.dont_write_bytecode),
    "isolated": bool(sys.flags.isolated),
    "loaded": list(modules),
    "no_site": bool(sys.flags.no_site),
}, sort_keys=True))
"""


def _b3f_r_future_bootstrap_seam(name: str, red_reason: str):
    seam = getattr(security_bootstrap, name, None)
    assert callable(seam), f"B3f-R0 RED [{red_reason}]: missing callable {name}"
    return seam


def _b3f_r_record_row(path: str, content: bytes) -> bytes:
    digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=")
    return (
        path.encode("utf-8")
        + b",sha256="
        + digest
        + b","
        + str(len(content)).encode("ascii")
        + b"\n"
    )


def _b3f_r_record_fixture() -> tuple[bytes, tuple[dict[str, object], ...]]:
    init_content = b'BOUND_EXECUTED = "pytest"\n'
    main_content = b'BOUND_EXECUTED = "pytest-main"\n'
    script_content = b"#!/bin/sh\n"
    dist_info = "pytest-9.0.2.dist-info"
    content = b"".join(
        (
            _b3f_r_record_row("pytest/__init__.py", init_content),
            _b3f_r_record_row("pytest/__main__.py", main_content),
            f"{dist_info}/RECORD,,\n".encode(),
            _b3f_r_record_row("../../../bin/pytest", script_content),
        )
    )
    expected = (
        {
            "kind": "required",
            "path": "pytest/__init__.py",
            "sha256": hashlib.sha256(init_content).hexdigest(),
            "size": len(init_content),
        },
        {
            "kind": "required",
            "path": "pytest/__main__.py",
            "sha256": hashlib.sha256(main_content).hexdigest(),
            "size": len(main_content),
        },
        {
            "kind": "self",
            "path": f"{dist_info}/RECORD",
            "sha256": None,
            "size": None,
        },
        {
            "kind": "opaque",
            "path": "../../../bin/pytest",
            "sha256": hashlib.sha256(script_content).hexdigest(),
            "size": len(script_content),
        },
    )
    return content, expected


def test_s18_b3f_r_isolated_no_site_probe_derives_exact_venv_site_packages(tmp_path):
    compile(_B3F_R_SITE_PACKAGES_PROBE, "<b3f-r-site-packages-probe>", "exec")
    _b3f_r_future_bootstrap_seam(
        "_derive_runtime_site_packages",
        "isolated-no-site-exact-venv-site-packages",
    )
    venv = tmp_path / "runtime"
    executable = venv / "bin/python"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"synthetic python executable\n")
    executable.chmod(0o700)
    (venv / "pyvenv.cfg").write_text(
        f"home = {executable.parent}\n"
        "include-system-site-packages = false\n"
        "version = 3.11.0\n",
        encoding="utf-8",
    )
    expected = venv / "lib/python3.11/site-packages"
    expected.mkdir(parents=True)
    poison = tmp_path / "poison-pythonpath"
    poison.mkdir()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.fspath(poison)

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            _B3F_R_SITE_PACKAGES_PROBE,
            os.fspath(BOOTSTRAP),
            os.fspath(executable),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    document = json.loads(result.stdout)
    assert document["isolated"] is True
    assert document["no_site"] is True
    assert document["dont_write_bytecode"] is True
    assert document["site_packages"] == os.fspath(expected.resolve(strict=True))
    assert os.fspath(poison) not in document["sys_path"]


def test_s18_b3f_r_bound_package_entries_compile_from_stable_bytes(tmp_path):
    compile(_B3F_R_BOUND_LOADER_PROBE, "<b3f-r-bound-loader-probe>", "exec")
    _b3f_r_future_bootstrap_seam(
        "_load_bound_runtime_modules",
        "stable-bytes-drive-hash-compile-and-exec",
    )
    site_packages = tmp_path / "site-packages"
    sources = {
        "pluggy": b'BOUND_EXECUTED = "pluggy"\n',
        "coverage": b'import pluggy\nBOUND_EXECUTED = "coverage"\n',
        "pytest": b'import pluggy\nBOUND_EXECUTED = "pytest"\n',
        "pytest_cov": (
            b'import coverage, pluggy, pytest\nBOUND_EXECUTED = "pytest_cov"\n'
        ),
        "pytest_cov.plugin": (
            b'import pytest_cov\nBOUND_EXECUTED = "pytest_cov.plugin"\n'
        ),
    }
    paths = {
        "pluggy": site_packages / "pluggy/__init__.py",
        "coverage": site_packages / "coverage/__init__.py",
        "pytest": site_packages / "pytest/__init__.py",
        "pytest_cov": site_packages / "pytest_cov/__init__.py",
        "pytest_cov.plugin": site_packages / "pytest_cov/plugin.py",
    }
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(sources[name])
    pth_marker = tmp_path / "pth-executed"
    sitecustomize_marker = tmp_path / "sitecustomize-executed"
    (site_packages / "poison.pth").write_text(
        f"import pathlib; pathlib.Path({os.fspath(pth_marker)!r}).touch()\n",
        encoding="utf-8",
    )
    (site_packages / "sitecustomize.py").write_text(
        f"from pathlib import Path\nPath({os.fspath(sitecustomize_marker)!r}).touch()\n",
        encoding="utf-8",
    )
    expected_hashes = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in sources.items()
    }

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            _B3F_R_BOUND_LOADER_PROBE,
            os.fspath(BOOTSTRAP),
            os.fspath(site_packages),
            json.dumps(expected_hashes, sort_keys=True, separators=(",", ":")),
            os.fspath(pth_marker),
            os.fspath(sitecustomize_marker),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "dont_write_bytecode": True,
        "isolated": True,
        "loaded": ["pluggy", "coverage", "pytest", "pytest_cov", "pytest_cov.plugin"],
        "no_site": True,
    }
    assert not pth_marker.exists()
    assert not sitecustomize_marker.exists()


def test_s18_b3f_r_record_parser_accepts_only_one_self_record_exception():
    parse = _b3f_r_future_bootstrap_seam(
        "_parse_distribution_record",
        "unique-canonical-record-self-row",
    )
    content, expected = _b3f_r_record_fixture()
    dist_info = "pytest-9.0.2.dist-info"
    required = ("pytest/__init__.py", "pytest/__main__.py")

    assert parse(content, dist_info=dist_info, required_paths=required) == expected

    safe_without_self = b"".join(content.splitlines(keepends=True)[:2])
    self_row = f"{dist_info}/RECORD,,\n".encode()
    digest = base64.urlsafe_b64encode(hashlib.sha256(b"x").digest()).rstrip(b"=")
    invalid_records = (
        ("missing-self", safe_without_self, required),
        ("duplicate-path", content + content.splitlines(keepends=True)[0], required),
        ("duplicate-self", content + self_row, required),
        ("wrong-self", content.replace(self_row, b"other.dist-info/RECORD,,\n"), required),
        ("self-hash", content.replace(self_row, self_row[:-2] + b"sha256=" + digest + b",\n"), required),
        ("self-size", content.replace(self_row, self_row[:-2] + b",1\n"), required),
        ("absolute-row", content + _b3f_r_record_row("/absolute.py", b"x"), required),
        ("non-sha256", content.replace(b"sha256=", b"sha512=", 1), required),
        ("missing-hash", content.replace(b",sha256=", b",", 1), required),
        (
            "missing-size",
            content.replace(b"," + str(len(b'BOUND_EXECUTED = "pytest"\n')).encode("ascii") + b"\n", b",\n", 1),
            required,
        ),
    )
    for _label, invalid, required_paths in invalid_records:
        with pytest.raises(security_bootstrap.BootstrapError):
            parse(invalid, dist_info=dist_info, required_paths=required_paths)

    for unsafe_required in (
        "/pytest/__init__.py",
        ".",
        "./pytest/__init__.py",
        "pytest/../pytest/__init__.py",
        "../pytest/__init__.py",
    ):
        with pytest.raises(security_bootstrap.BootstrapError):
            parse(content, dist_info=dist_info, required_paths=(unsafe_required,))


def test_s18_b3f_r_record_parser_never_resolves_parent_path_rows(monkeypatch):
    parse = _b3f_r_future_bootstrap_seam(
        "_parse_distribution_record",
        "parent-path-record-rows-remain-opaque",
    )
    content, expected = _b3f_r_record_fixture()
    original_resolve = Path.resolve
    original_path_open = Path.open
    original_os_open = os.open

    def guarded_resolve(path, *args, **kwargs):
        assert ".." not in path.parts, "parent-path RECORD row was resolved"
        return original_resolve(path, *args, **kwargs)

    def guarded_path_open(path, *args, **kwargs):
        assert ".." not in path.parts, "parent-path RECORD row was opened"
        return original_path_open(path, *args, **kwargs)

    def guarded_os_open(path, *args, **kwargs):
        assert "../../../bin/pytest" not in os.fspath(path), (
            "parent-path RECORD row reached os.open"
        )
        return original_os_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", guarded_resolve)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    parsed = parse(
        content,
        dist_info="pytest-9.0.2.dist-info",
        required_paths=("pytest/__init__.py", "pytest/__main__.py"),
    )

    assert parsed == expected
    opaque = [row for row in parsed if row["kind"] == "opaque"]
    assert opaque == [expected[-1]]


def test_s18_b3f_r_policy_v3_freezes_named_runtime_contract():
    policy = security_verifier.tomllib.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
    assert policy.get("schema_version") == 3, (
        "B3f-R0 RED [policy-v3-runtime]: policy schema must migrate atomically to v3"
    )
    assert policy.get("runtime") == {
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
    limits = policy["limits"]
    assert limits["plugin_identity_bytes"] == 4 * 1024 * 1024
    assert limits["runtime_metadata_bytes"] == 256 * 1024
    assert limits["runtime_record_bytes"] == 256 * 1024
    assert limits["runtime_required_entry_bytes"] == 1024 * 1024
    assert limits["runtime_pyvenv_cfg_bytes"] == 16 * 1024


_B3F_R_LOADER_OWNED_BINDINGS_PROBE = r"""
import hashlib
import importlib.util
import sys
from pathlib import Path

bootstrap_path = Path(sys.argv[1])
site_packages = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("b3f_r_loader_owned_bindings", bootstrap_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
load = getattr(module, "_load_bound_runtime_modules")
names = ("pluggy", "coverage", "pytest", "pytest_cov", "pytest_cov.plugin")
paths = {
    "pluggy": site_packages / "pluggy/__init__.py",
    "coverage": site_packages / "coverage/__init__.py",
    "pytest": site_packages / "pytest/__init__.py",
    "pytest_cov": site_packages / "pytest_cov/__init__.py",
    "pytest_cov.plugin": site_packages / "pytest_cov/plugin.py",
}

def entry(name, path=None):
    selected = paths[name] if path is None else path
    content = selected.read_bytes() if selected.is_file() else b""
    return {
        "module": name,
        "path": selected,
        "is_package": name != "pytest_cov.plugin",
        "expected_sha256": hashlib.sha256(content).hexdigest(),
        "expected_size": len(content),
    }

def base_entries():
    return [entry(name) for name in names]

def rejected(entries):
    try:
        load(tuple(entries))
    except module.BootstrapError:
        pass
    else:
        raise AssertionError("invalid bound runtime entries were accepted")
    assert all(name not in sys.modules for name in names)

wrong_order = base_entries()
wrong_order[0], wrong_order[1] = wrong_order[1], wrong_order[0]
rejected(wrong_order)

unknown_key = base_entries()
unknown_key[0]["unknown"] = True
rejected(unknown_key)

bad_digest = base_entries()
bad_digest[1]["expected_sha256"] = "0" * 64
rejected(bad_digest)

bad_size = base_entries()
bad_size[1]["expected_size"] += 1
rejected(bad_size)

relative_path = base_entries()
relative_path[2]["path"] = Path("pytest/__init__.py")
rejected(relative_path)

symlink_path = site_packages / "symlink.py"
symlink_path.symlink_to(paths["pytest"])
symlink_entry = base_entries()
symlink_entry[2] = entry("pytest", symlink_path)
rejected(symlink_entry)

directory_path = site_packages / "directory-entry"
directory_path.mkdir()
directory_entry = base_entries()
directory_entry[2] = entry("pytest", directory_path)
rejected(directory_entry)

paths["pytest_cov"].write_text(
    'raise RuntimeError("controlled owned-binding cleanup")\n',
    encoding="utf-8",
)
rejected(base_entries())
"""


def _b3f_r_make_venv_layout(root: Path) -> tuple[Path, Path, Path]:
    executable = root / "bin/python"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"synthetic python executable\n")
    executable.chmod(0o700)
    config = root / "pyvenv.cfg"
    config.write_text(
        f"home = {executable.parent}\n"
        "include-system-site-packages = false\n"
        "version = 3.11.0\n",
        encoding="utf-8",
    )
    site_packages = root / "lib/python3.11/site-packages"
    site_packages.mkdir(parents=True)
    return executable, config, site_packages


def test_s18_b3f_r_derive_runtime_site_packages_rejects_unsafe_layouts(tmp_path):
    derive = _b3f_r_future_bootstrap_seam(
        "_derive_runtime_site_packages",
        "derive-rejects-unsafe-venv-layouts",
    )
    invalid: list[Path] = [Path("relative/bin/python")]

    executable, _config, site_packages = _b3f_r_make_venv_layout(
        tmp_path / "symlink-exe"
    )
    target = tmp_path / "real-python"
    target.write_bytes(b"real python\n")
    target.chmod(0o700)
    executable.unlink()
    executable.symlink_to(target)
    (executable.parents[1] / "pyvenv.cfg").write_text(
        f"home = {target.parent}\n"
        "include-system-site-packages = false\n"
        "version = 3.11.0\n",
        encoding="utf-8",
    )
    assert derive(executable, python_major_minor=(3, 11)) == site_packages

    executable, config, site_packages = _b3f_r_make_venv_layout(
        tmp_path / "uv-extra-keys"
    )
    config.write_text(
        f"home = {executable.parent}\n"
        "implementation = CPython\n"
        "uv = 0.12.9\n"
        "version_info = 3.11.4\n"
        "include-system-site-packages = false\n"
        "prompt = controlled\n",
        encoding="utf-8",
    )
    assert derive(executable, python_major_minor=(3, 11)) == site_packages

    executable, _config, _site = _b3f_r_make_venv_layout(tmp_path / "nonregular-exe")
    executable.unlink()
    executable.mkdir()
    invalid.append(executable)

    executable, _config, _site = _b3f_r_make_venv_layout(tmp_path / "broken-exe")
    executable.unlink()
    executable.symlink_to(tmp_path / "missing-python")
    invalid.append(executable)

    executable, _config, _site = _b3f_r_make_venv_layout(tmp_path / "loop-exe")
    peer = executable.with_name("python-peer")
    executable.unlink()
    executable.symlink_to(peer.name)
    peer.symlink_to(executable.name)
    invalid.append(executable)

    executable, _config, _site = _b3f_r_make_venv_layout(tmp_path / "deep-exe")
    executable.unlink()
    links = [executable.with_name(f"python-link-{index}") for index in range(17)]
    executable.symlink_to(links[0].name)
    for current, following in pairwise(links):
        current.symlink_to(following.name)
    deep_target = tmp_path / "deep-real-python"
    deep_target.write_bytes(b"deep real python\n")
    deep_target.chmod(0o700)
    links[-1].symlink_to(deep_target)
    invalid.append(executable)

    executable, _config, _site = _b3f_r_make_venv_layout(
        tmp_path / "nonregular-target"
    )
    directory_target = tmp_path / "python-directory"
    directory_target.mkdir()
    executable.unlink()
    executable.symlink_to(directory_target, target_is_directory=True)
    invalid.append(executable)

    executable, config, _site = _b3f_r_make_venv_layout(tmp_path / "missing-config")
    config.unlink()
    invalid.append(executable)

    executable, config, _site = _b3f_r_make_venv_layout(tmp_path / "symlink-config")
    real_config = tmp_path / "real-pyvenv.cfg"
    config.replace(real_config)
    config.symlink_to(real_config)
    invalid.append(executable)

    executable, config, _site = _b3f_r_make_venv_layout(tmp_path / "duplicate-key")
    with config.open("a", encoding="utf-8") as stream:
        stream.write("version = 3.11.1\n")
    invalid.append(executable)

    executable, config, _site = _b3f_r_make_venv_layout(tmp_path / "duplicate-version")
    with config.open("a", encoding="utf-8") as stream:
        stream.write("version_info = 3.11.0\n")
    invalid.append(executable)

    executable, config, _site = _b3f_r_make_venv_layout(tmp_path / "malformed-key")
    config.write_text(
        f"home {executable.parent}\n"
        "include-system-site-packages = false\n"
        "version = 3.11.0\n",
        encoding="utf-8",
    )
    invalid.append(executable)

    executable, config, _site = _b3f_r_make_venv_layout(tmp_path / "system-site")
    config.write_text(
        f"home = {executable.parent}\n"
        "include-system-site-packages = true\n"
        "version = 3.11.0\n",
        encoding="utf-8",
    )
    invalid.append(executable)

    executable, config, _site = _b3f_r_make_venv_layout(tmp_path / "version-mismatch")
    config.write_text(
        f"home = {executable.parent}\n"
        "include-system-site-packages = false\n"
        "version = 3.12.0\n",
        encoding="utf-8",
    )
    invalid.append(executable)

    executable, _config, site_packages = _b3f_r_make_venv_layout(tmp_path / "missing-site")
    site_packages.rmdir()
    invalid.append(executable)

    executable, _config, site_packages = _b3f_r_make_venv_layout(tmp_path / "symlink-site")
    site_packages.rmdir()
    real_site = tmp_path / "real-site-packages"
    real_site.mkdir()
    site_packages.symlink_to(real_site, target_is_directory=True)
    invalid.append(executable)

    executable, _config, _site = _b3f_r_make_venv_layout(tmp_path / "ambiguous-site")
    (executable.parents[1] / "lib/python3.10/site-packages").mkdir(parents=True)
    invalid.append(executable)

    for candidate in invalid:
        with pytest.raises(security_bootstrap.BootstrapError):
            derive(candidate, python_major_minor=(3, 11))


def test_s18_b3f_r_bound_module_loader_cleans_only_owned_bindings(
    tmp_path,
):
    compile(
        _B3F_R_LOADER_OWNED_BINDINGS_PROBE,
        "<b3f-r-loader-owned-bindings>",
        "exec",
    )
    _b3f_r_future_bootstrap_seam(
        "_load_bound_runtime_modules",
        "loader-owned-binding-cleanup",
    )
    site_packages = tmp_path / "site-packages"
    sources = {
        "pluggy": b'BOUND_EXECUTED = "pluggy"\n',
        "coverage": b'import pluggy\nBOUND_EXECUTED = "coverage"\n',
        "pytest": b'import pluggy\nBOUND_EXECUTED = "pytest"\n',
        "pytest_cov": b'import coverage, pluggy, pytest\nBOUND_EXECUTED = "pytest_cov"\n',
        "pytest_cov.plugin": b'import pytest_cov\nBOUND_EXECUTED = "pytest_cov.plugin"\n',
    }
    paths = {
        "pluggy": site_packages / "pluggy/__init__.py",
        "coverage": site_packages / "coverage/__init__.py",
        "pytest": site_packages / "pytest/__init__.py",
        "pytest_cov": site_packages / "pytest_cov/__init__.py",
        "pytest_cov.plugin": site_packages / "pytest_cov/plugin.py",
    }
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(sources[name])

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            _B3F_R_LOADER_OWNED_BINDINGS_PROBE,
            os.fspath(BOOTSTRAP),
            os.fspath(site_packages),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


def test_s18_b3f_r_record_parser_handles_crlf_and_rejects_malformed_csv():
    parse = _b3f_r_future_bootstrap_seam(
        "_parse_distribution_record",
        "record-csv-and-encoding-boundaries",
    )
    content, expected = _b3f_r_record_fixture()
    required = ("pytest/__init__.py", "pytest/__main__.py")
    assert parse(
        content.replace(b"\n", b"\r\n"),
        dist_info="pytest-9.0.2.dist-info",
        required_paths=required,
    ) == expected

    digest = base64.urlsafe_b64encode(hashlib.sha256(b"x").digest()).rstrip(b"=")
    malformed = (
        b"\xff",
        content + b"nul.py,sha256=" + digest + b",1\x00\n",
        content + b'"unterminated,sha256=' + digest + b",1\n",
        content + b"too,few\n",
        content + b"too,many,columns,1\n",
        content + b"\n",
        content + b"leading-zero.py,sha256=" + digest + b",01\n",
        content + b"padded.py,sha256=" + digest + b"=,1\n",
    )
    for invalid in malformed:
        with pytest.raises(security_bootstrap.BootstrapError):
            parse(
                invalid,
                dist_info="pytest-9.0.2.dist-info",
                required_paths=required,
            )


def test_s18_b3f_r_derive_rejects_invalid_version_inputs_without_raw_errors(
    tmp_path,
):
    derive = _b3f_r_future_bootstrap_seam(
        "_derive_runtime_site_packages",
        "derive-invalid-version-inputs",
    )
    executable, config, _site_packages = _b3f_r_make_venv_layout(
        tmp_path / "invalid-version-inputs"
    )

    invalid_versions = (
        None,
        [3, 11],
        (3,),
        (3, 11, 0),
        (True, 11),
        (3, False),
        (-1, 11),
        (3, -1),
        (1000, 11),
        (3, 1000),
    )
    for invalid in invalid_versions:
        with pytest.raises(security_bootstrap.BootstrapError):
            derive(executable, python_major_minor=invalid)

    config.write_text(
        f"home = {executable.parent}\n"
        "include-system-site-packages = false\n"
        f"version = {'9' * 5000}.11.0\n",
        encoding="utf-8",
    )
    with pytest.raises(security_bootstrap.BootstrapError):
        derive(executable, python_major_minor=(3, 11))


def test_s18_b3f_r_derive_binds_home_and_current_uv_runtime(tmp_path):
    derive = _b3f_r_future_bootstrap_seam(
        "_derive_runtime_site_packages",
        "derive-home-binding-and-current-uv-runtime",
    )
    executable, config, _site_packages = _b3f_r_make_venv_layout(
        tmp_path / "home-mismatch"
    )
    mismatched_home = tmp_path / "different-home"
    mismatched_home.mkdir()
    config.write_text(
        f"home = {mismatched_home}\n"
        "include-system-site-packages = false\n"
        "version = 3.11.0\n",
        encoding="utf-8",
    )
    with pytest.raises(security_bootstrap.BootstrapError):
        derive(executable, python_major_minor=(3, 11))

    symlink_home = tmp_path / "symlink-home"
    symlink_home.symlink_to(executable.parent, target_is_directory=True)
    file_home = tmp_path / "file-home"
    file_home.write_text("not a directory\n", encoding="utf-8")
    invalid_homes = (
        "relative/home",
        os.fspath(symlink_home),
        os.fspath(file_home),
        os.fspath(tmp_path / "missing-home"),
    )
    for invalid_home in invalid_homes:
        config.write_text(
            f"home = {invalid_home}\n"
            "include-system-site-packages = false\n"
            "version = 3.11.0\n",
            encoding="utf-8",
        )
        with pytest.raises(security_bootstrap.BootstrapError):
            derive(executable, python_major_minor=(3, 11))

    real_executable = REPOSITORY_ROOT / ".venv/bin/python"
    expected = REPOSITORY_ROOT / ".venv/lib/python3.11/site-packages"
    assert derive(
        real_executable,
        python_major_minor=(sys.version_info.major, sys.version_info.minor),
    ) == expected


def test_s18_b3f_r_record_rejects_invalid_inputs_and_freezes_uint63_size():
    parse = _b3f_r_future_bootstrap_seam(
        "_parse_distribution_record",
        "record-invalid-inputs-and-uint63-size",
    )
    content, expected = _b3f_r_record_fixture()
    dist_info = "pytest-9.0.2.dist-info"
    required = ("pytest/__init__.py", "pytest/__main__.py")

    invalid_required_paths = (
        None,
        ["pytest/__init__.py", "pytest/__main__.py"],
        (["pytest/__init__.py"], "pytest/__main__.py"),
        ("pytest/__init__.py", "pytest/__init__.py"),
    )
    for invalid in invalid_required_paths:
        with pytest.raises(security_bootstrap.BootstrapError):
            parse(content, dist_info=dist_info, required_paths=invalid)

    original_size = str(expected[0]["size"]).encode("ascii")
    size_marker = b"," + original_size + b"\n"
    maximum_size = str(2**63 - 1).encode("ascii")
    maximum = content.replace(size_marker, b"," + maximum_size + b"\n", 1)
    parsed = parse(maximum, dist_info=dist_info, required_paths=required)
    assert parsed[0]["size"] == 2**63 - 1

    for invalid_size in (b"9" * 5000, str(2**63).encode("ascii")):
        invalid = content.replace(size_marker, b"," + invalid_size + b"\n", 1)
        with pytest.raises(security_bootstrap.BootstrapError):
            parse(invalid, dist_info=dist_info, required_paths=required)
