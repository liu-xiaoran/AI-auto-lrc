"""Machine-checkable governance for the refactor plan's stable test IDs."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = REPOSITORY_ROOT / "tests" / "spec_inventory.json"
PYPROJECT_PATH = REPOSITORY_ROOT / "pyproject.toml"
S18_P1_PLAN_PATH = REPOSITORY_ROOT / "docs/S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md"
B3E_SCENARIO_MANIFEST_PATH = REPOSITORY_ROOT / "tests/fixtures/security_coverage_scenarios.json"
STABLE_ID = re.compile(r"\b[A-Z][A-Z0-9]*-[0-9]{3}\b")
PREFIX = re.compile(r"^[A-Z][A-Z0-9]*$")
ABBREVIATED_RANGE = re.compile(r"\b[A-Z][A-Z0-9]*-[0-9]{3}\s*\.\.\s*[0-9]{3}\b")
ABBREVIATED_CHAIN = re.compile(r"(?<=[0-9]{3})/[0-9]{3}\b")
DECORATED_ID = re.compile(r"\b[A-Z][A-Z0-9]*-[0-9]{3}-[A-Za-z0-9]+\b")
S18_P1_FULL_ID = re.compile(r"^S18-[A-Z][A-Z0-9]*-[0-9]{3}$")
S18_P1_AUTHORITY = {
    "S18-ABA-001": {
        "implementation_status": "planned",
        "verification_status": "unverified",
        "qualification_status": "unqualified",
        "runner_scope": ("host",),
        "target_scope": ("capture",),
        "nodeids": (),
        "evidence_refs": (),
    },
    "S18-CLAIM-001": {
        "implementation_status": "planned",
        "verification_status": "unverified",
        "qualification_status": "unqualified",
        "runner_scope": ("host",),
        "target_scope": ("capture",),
        "nodeids": (),
        "evidence_refs": (),
    },
    "S18-COV-015": {
        "implementation_status": "implemented",
        "verification_status": "unverified",
        "qualification_status": "unqualified",
        "runner_scope": ("host",),
        "target_scope": ("capture",),
        "nodeids": (
            "tests/contract/test_security_coverage_gate.py::"
            "test_s18_runner_rejects_target_test_drift_during_pytest",
        ),
        "evidence_refs": (),
    },
    "S18-JUNIT-001": {
        "implementation_status": "implemented",
        "verification_status": "unverified",
        "qualification_status": "unqualified",
        "runner_scope": ("host",),
        "target_scope": ("capture",),
        "nodeids": (
            "tests/contract/test_security_coverage_gate.py::"
            "test_s18_gate_rejects_forged_junit_classname",
        ),
        "evidence_refs": (),
    },
    "S18-JUNIT-002": {
        "implementation_status": "implemented",
        "verification_status": "unverified",
        "qualification_status": "unqualified",
        "runner_scope": ("host",),
        "target_scope": ("capture",),
        "nodeids": (
            "tests/contract/test_security_coverage_gate.py::"
            "test_s18_gate_rejects_noncanonical_junit_name",
        ),
        "evidence_refs": (),
    },
    "S18-SRC-001": {
        "implementation_status": "implemented",
        "verification_status": "unverified",
        "qualification_status": "unqualified",
        "runner_scope": ("host",),
        "target_scope": ("capture",),
        "nodeids": (
            "tests/contract/test_security_coverage_gate.py::"
            "test_s18_manifest_symbol_and_hash_use_same_frozen_source_bytes",
        ),
        "evidence_refs": (),
    },
    "S18-XFAIL-001": {
        "implementation_status": "implemented",
        "verification_status": "unverified",
        "qualification_status": "unqualified",
        "runner_scope": ("host",),
        "target_scope": ("capture",),
        "nodeids": (
            "tests/contract/test_security_coverage_gate.py::"
            "test_s18_real_runner_enforces_required_xfail_and_xpass"
            "[B3E-XFAIL-REQUIRED]",
            "tests/contract/test_security_coverage_gate.py::"
            "test_s18_real_runner_enforces_required_xfail_and_xpass"
            "[B3E-XPASS-NONSTRICT]",
            "tests/contract/test_security_coverage_gate.py::"
            "test_s18_real_runner_enforces_required_xfail_and_xpass"
            "[B3E-XPASS-STRICT]",
        ),
        "evidence_refs": (),
    },
}
S18_P1_ID_AUTHORITY = tuple(S18_P1_AUTHORITY)
S18_P1_SPEC_KEYS = {
    "full_id",
    "implementation_status",
    "verification_status",
    "qualification_status",
    "runner_scope",
    "target_scope",
    "nodeids",
    "evidence_refs",
}
S18_P1_EVIDENCE_KEYS = {"kind", "path", "sha256"}
S18_P1_EVIDENCE_KINDS = {
    "host-bundle",
    "raw-run-manifest",
    "independent-review",
    "qualification-ledger",
}
SPEC_INVENTORY_TOP_LEVEL_KEYS = {
    "schema_version",
    "source_plan",
    "expected_plan_id_count",
    "default_status",
    "default_implemented_qualification",
    "qualification_levels",
    "qualification_overrides",
    "plan_id_ranges",
    "work_package_specs",
    "ignored_non_spec_tokens",
    "implemented",
}
S18_P1_XFAIL_SCENARIOS = (
    "B3E-XFAIL-REQUIRED",
    "B3E-XPASS-NONSTRICT",
    "B3E-XPASS-STRICT",
)
S18_P1_MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
S18_P1_COLLECTION_SCRIPT = r"""
import json
import pathlib
import pytest
import sys


class ExactCollector:
    def __init__(self):
        self.nodeids = []

    def pytest_collection_finish(self, session):
        self.nodeids = [item.nodeid for item in session.items]


output_path = pathlib.Path(sys.argv[1])
repository_root = pathlib.Path(sys.argv[2]).resolve(strict=True)
sys.path.insert(0, str(repository_root))
collector = ExactCollector()
exit_code = pytest.main(sys.argv[3:], plugins=[collector])
payload = {
    "exit_code": int(exit_code),
    "nodeids": collector.nodeids,
    "schema_version": 1,
}
output_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
raise SystemExit(int(exit_code))
"""


class DuplicateInventoryKey(ValueError):
    """Raised before JSON can silently overwrite a duplicate inventory key."""


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateInventoryKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_inventory():
    return json.loads(
        INVENTORY_PATH.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )


def _expanded_plan_ids(inventory):
    expanded = set()
    for prefix, bounds in inventory["plan_id_ranges"].items():
        assert PREFIX.fullmatch(prefix), f"invalid inventory prefix: {prefix!r}"
        assert (
            isinstance(bounds, list)
            and len(bounds) == 2
            and all(isinstance(value, int) for value in bounds)
        ), f"invalid inventory range for {prefix}: {bounds!r}"
        start, end = bounds
        assert 1 <= start <= end <= 999, f"invalid inventory bounds for {prefix}"
        expanded.update(f"{prefix}-{number:03d}" for number in range(start, end + 1))
    return expanded


def _test_functions(tree, relative_path):
    def visit(body, parents=()):
        for node in body:
            if isinstance(node, ast.ClassDef):
                yield from visit(node.body, (*parents, node.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
                "test_"
            ):
                suffix = "::".join((*parents, node.name))
                yield node, f"{relative_path}::{suffix}"

    yield from visit(tree.body)


def _parameter_ids(function):
    for decorator in function.decorator_list:
        for node in ast.walk(decorator):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "id" and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, str):
                        yield keyword.value.value
                elif keyword.arg == "ids" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                    for element in keyword.value.elts:
                        if isinstance(element, ast.Constant) and isinstance(element.value, str):
                            yield element.value


def _source_evidence():
    evidence = defaultdict(list)
    docstrings = []
    for path in sorted((REPOSITORY_ROOT / "tests").rglob("test_*.py")):
        relative_path = path.relative_to(REPOSITORY_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_docstring = ast.get_docstring(tree, clean=False)
        if module_docstring:
            docstrings.append((relative_path, module_docstring))

        for function, base_nodeid in _test_functions(tree, relative_path):
            docstring = ast.get_docstring(function, clean=False)
            if docstring:
                docstrings.append((base_nodeid, docstring))
                for stable_id in set(STABLE_ID.findall(docstring)):
                    evidence[stable_id].append(("docstring", base_nodeid))
            for parameter_id in _parameter_ids(function):
                docstrings.append((base_nodeid, parameter_id))
                for stable_id in set(STABLE_ID.findall(parameter_id)):
                    evidence[stable_id].append(("parameter", base_nodeid))
    return evidence, docstrings


def _collect_nodes(marker=None):
    environment = os.environ.copy()
    for name in (
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONUSERBASE",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
    ):
        environment.pop(name, None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    with tempfile.TemporaryDirectory(prefix="ai-auto-lrc-spec-collect-") as directory:
        output_path = Path(directory) / "collected.json"
        pytest_arguments = [
            "--collect-only",
            "-q",
            "--disable-plugin-autoload",
            "--noconftest",
            "-c",
            str(PYPROJECT_PATH),
            "-p",
            "no:cacheprovider",
        ]
        if marker is not None:
            pytest_arguments.extend(("-m", marker))
        pytest_arguments.append("tests")
        command = [
            sys.executable,
            "-I",
            "-B",
            "-c",
            S18_P1_COLLECTION_SCRIPT,
            str(output_path),
            str(REPOSITORY_ROOT),
            *pytest_arguments,
        ]
        result = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert output_path.is_file(), result.stdout + result.stderr
        payload = json.loads(output_path.read_text(encoding="utf-8"))

    allowed_returncodes = {0, 5} if marker is not None else {0}
    assert result.returncode in allowed_returncodes, result.stdout + result.stderr
    assert set(payload) == {"exit_code", "nodeids", "schema_version"}
    assert payload["schema_version"] == 1
    assert payload["exit_code"] == result.returncode
    nodeids = payload["nodeids"]
    assert isinstance(nodeids, list)
    assert all(
        isinstance(nodeid, str) and nodeid.startswith("tests/") and "::" in nodeid
        for nodeid in nodeids
    )
    assert len(nodeids) == len(set(nodeids)), "duplicate collected test nodeid"
    return set(nodeids)


def _read_s18_p1_evidence(reference):
    assert isinstance(reference, dict)
    assert set(reference) == S18_P1_EVIDENCE_KEYS
    assert reference["kind"] in S18_P1_EVIDENCE_KINDS
    raw_path = reference["path"]
    expected_sha256 = reference["sha256"]
    assert isinstance(raw_path, str) and raw_path
    assert isinstance(expected_sha256, str)
    assert re.fullmatch(r"[0-9a-f]{64}", expected_sha256)

    declared = Path(raw_path)
    assert raw_path == declared.as_posix(), (
        f"noncanonical S18 P1 evidence path spelling: {raw_path}"
    )
    candidate = declared if declared.is_absolute() else REPOSITORY_ROOT / declared
    current = Path(candidate.anchor)
    for component in candidate.parts[1:]:
        try:
            with os.scandir(current) as entries:
                exact_component = any(entry.name == component for entry in entries)
        except OSError as error:
            raise AssertionError(f"missing S18 P1 evidence path: {raw_path}") from error
        assert exact_component, f"noncanonical S18 P1 evidence path spelling: {raw_path}"
        current /= component
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise AssertionError(f"missing S18 P1 evidence path: {raw_path}") from error
    assert candidate == resolved, f"noncanonical S18 P1 evidence path: {raw_path}"
    assert not candidate.is_symlink(), f"symlink S18 P1 evidence path: {raw_path}"

    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(candidate, flags)
    except OSError as error:
        raise AssertionError(f"cannot open S18 P1 evidence path: {raw_path}") from error
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode), f"non-regular S18 P1 evidence path: {raw_path}"
        assert before.st_size <= S18_P1_MAX_EVIDENCE_BYTES, (
            f"oversize S18 P1 evidence path: {raw_path}"
        )
        chunks = []
        remaining = S18_P1_MAX_EVIDENCE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        assert len(content) <= S18_P1_MAX_EVIDENCE_BYTES, (
            f"oversize S18 P1 evidence path: {raw_path}"
        )
        after = os.fstat(descriptor)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
        )
        assert before_identity == after_identity, f"S18 P1 evidence changed during read: {raw_path}"
    finally:
        os.close(descriptor)

    actual_sha256 = hashlib.sha256(content).hexdigest()
    assert expected_sha256 == actual_sha256, f"S18 P1 evidence hash mismatch: {raw_path}"
    return content


def _validate_s18_p1_work_package(inventory, *, collected=None):
    assert set(inventory) == SPEC_INVENTORY_TOP_LEVEL_KEYS
    assert inventory["schema_version"] == 3
    assert set(inventory["work_package_specs"]) == {"S18_P1"}
    work_package = inventory["work_package_specs"]["S18_P1"]
    assert set(work_package) == {
        "schema_version",
        "source_plan",
        "source_section",
        "specs",
    }
    assert work_package["schema_version"] == 1
    assert work_package["source_plan"] == ("docs/S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md")
    assert work_package["source_section"] == "19.2"

    specs = work_package["specs"]
    assert isinstance(specs, list)
    assert all(isinstance(spec, dict) for spec in specs)
    assert all(set(spec) == S18_P1_SPEC_KEYS for spec in specs)
    identifiers = [spec["full_id"] for spec in specs]
    assert identifiers == list(S18_P1_ID_AUTHORITY), (
        "S18 P1 inventory must equal the independent exact ID authority"
    )
    assert len(identifiers) == len(set(identifiers)), "duplicate S18 P1 full ID"

    all_nodeids = []
    for spec in specs:
        full_id = spec["full_id"]
        assert isinstance(full_id, str)
        assert not full_id.startswith("S18-CAP-"), "S18 CAP IDs are manifest-only"
        assert S18_P1_FULL_ID.fullmatch(full_id), f"invalid S18 P1 full ID: {full_id}"
        assert full_id in S18_P1_ID_AUTHORITY, f"unknown S18 P1 full ID: {full_id}"

        implementation = spec["implementation_status"]
        verification = spec["verification_status"]
        qualification = spec["qualification_status"]
        assert implementation in {"planned", "implemented"}
        assert verification in {"unverified", "host-verified", "evidence-closed"}
        assert qualification in {"unqualified", "platform-qualified"}

        for field, allowed in (
            ("runner_scope", {"host", "macos", "linux"}),
            ("target_scope", {"capture", "retention"}),
        ):
            values = spec[field]
            assert isinstance(values, list) and values
            assert all(isinstance(value, str) for value in values)
            assert values == sorted(set(values))
            assert set(values) <= allowed

        nodeids = spec["nodeids"]
        assert isinstance(nodeids, list)
        assert all(isinstance(nodeid, str) for nodeid in nodeids)
        assert nodeids == sorted(set(nodeids))
        assert all(nodeid.startswith("tests/") and "::" in nodeid for nodeid in nodeids)
        all_nodeids.extend(nodeids)

        evidence_refs = spec["evidence_refs"]
        assert isinstance(evidence_refs, list)
        assert all(isinstance(reference, dict) for reference in evidence_refs)
        assert all(set(reference) == S18_P1_EVIDENCE_KEYS for reference in evidence_refs)
        for reference in evidence_refs:
            assert isinstance(reference["kind"], str)
            assert reference["kind"] in S18_P1_EVIDENCE_KINDS
            assert isinstance(reference["path"], str) and reference["path"]
            assert isinstance(reference["sha256"], str)
            assert re.fullmatch(r"[0-9a-f]{64}", reference["sha256"])
        evidence_order = [
            (reference["kind"], reference["path"], reference["sha256"])
            for reference in evidence_refs
        ]
        assert evidence_order == sorted(set(evidence_order))
        evidence_kinds = set()
        for reference in evidence_refs:
            evidence_kinds.add(reference["kind"])

        actual_record = {
            "implementation_status": implementation,
            "verification_status": verification,
            "qualification_status": qualification,
            "runner_scope": tuple(spec["runner_scope"]),
            "target_scope": tuple(spec["target_scope"]),
            "nodeids": tuple(nodeids),
            "evidence_refs": tuple(evidence_order),
        }
        assert actual_record == S18_P1_AUTHORITY[full_id], (
            f"S18 P1 inventory record drift for {full_id}"
        )
        for reference in evidence_refs:
            _read_s18_p1_evidence(reference)

        if implementation == "planned":
            assert verification == "unverified"
            assert qualification == "unqualified"
            assert nodeids == []
            assert evidence_refs == []
        else:
            assert nodeids, f"implemented S18 P1 spec {full_id} has no nodeids"
        if verification == "unverified":
            assert evidence_refs == []
        elif verification == "host-verified":
            assert implementation == "implemented"
            assert "host-bundle" in evidence_kinds
        else:
            assert implementation == "implemented"
            assert {"raw-run-manifest", "independent-review"} <= evidence_kinds
        if qualification == "platform-qualified":
            assert verification == "evidence-closed"
            assert "qualification-ledger" in evidence_kinds

    assert len(all_nodeids) == len(set(all_nodeids)), (
        "one collected node cannot silently sign multiple S18 P1 specs"
    )

    plan_text = S18_P1_PLAN_PATH.read_text(encoding="utf-8")
    for full_id in S18_P1_ID_AUTHORITY:
        assert f"`{full_id}`" in plan_text, f"undocumented S18 P1 ID: {full_id}"

    if collected is not None:
        for nodeid in all_nodeids:
            assert nodeid in collected, f"uncollectable S18 P1 nodeid: {nodeid}"

        scenarios = json.loads(B3E_SCENARIO_MANIFEST_PATH.read_text(encoding="utf-8"))
        scenario_nodeids = {
            scenario["scenario_id"]: scenario["test_nodeid"] for scenario in scenarios
        }
        xfail_spec = next(spec for spec in specs if spec["full_id"] == "S18-XFAIL-001")
        assert xfail_spec["nodeids"] == sorted(
            scenario_nodeids[scenario_id] for scenario_id in S18_P1_XFAIL_SCENARIOS
        )


def _base_nodeid(nodeid):
    return nodeid.rsplit("[", 1)[0] if nodeid.endswith("]") else nodeid


def _declared_markers():
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    pytest_section = re.search(r"(?ms)^\[tool\.pytest\.ini_options\]\s*$\n(.*?)(?=^\[|\Z)", text)
    assert pytest_section, "pyproject.toml must define [tool.pytest.ini_options]"
    marker_list = re.search(r"(?ms)^markers\s*=\s*\[(.*?)^\]", pytest_section.group(1))
    assert marker_list, "pytest markers must be declared as an explicit list"
    declarations = re.findall(r'"([^"\n]+)"', marker_list.group(1))
    return {declaration.split(":", 1)[0].strip() for declaration in declarations}


def test_inventory_matches_plan_and_collected_evidence():
    inventory = _load_inventory()
    assert inventory["schema_version"] == 3
    assert inventory["default_status"] == "planned"

    plan_ids = _expanded_plan_ids(inventory)
    assert len(plan_ids) == inventory["expected_plan_id_count"]

    plan_path = REPOSITORY_ROOT / inventory["source_plan"]
    documented_ids = set(STABLE_ID.findall(plan_path.read_text(encoding="utf-8")))
    ignored = set(inventory["ignored_non_spec_tokens"])
    assert ignored <= documented_ids
    assert documented_ids - ignored == plan_ids

    implemented = inventory["implemented"]
    assert set(implemented) <= plan_ids

    evidence, searchable_text = _source_evidence()
    for location, text in searchable_text:
        assert not ABBREVIATED_RANGE.search(text), f"abbreviated ID range in {location}"
        assert not ABBREVIATED_CHAIN.search(text), f"abbreviated chained ID in {location}"
        assert not DECORATED_ID.search(text), f"decorated stable ID in {location}"
        unknown = set(STABLE_ID.findall(text)) - plan_ids
        assert not unknown, f"unknown stable IDs in {location}: {sorted(unknown)}"

    assert set(evidence) == set(implemented), (
        "implemented inventory and source evidence differ: "
        f"inventory_only={sorted(set(implemented) - set(evidence))}, "
        f"source_only={sorted(set(evidence) - set(implemented))}"
    )
    conflicts = {
        stable_id: sorted({base for _kind, base in claims})
        for stable_id, claims in evidence.items()
        if len({base for _kind, base in claims}) > 1
    }
    assert not conflicts, f"stable IDs claimed by multiple test nodes: {conflicts}"

    collected = _collect_nodes()
    collected_bases = {_base_nodeid(nodeid) for nodeid in collected}
    for stable_id, nodeid in implemented.items():
        kind, evidence_base = evidence[stable_id][0]
        if kind == "docstring":
            assert nodeid == evidence_base
            assert nodeid in collected_bases
        else:
            assert _base_nodeid(nodeid) == evidence_base
            assert nodeid in collected
            assert stable_id in nodeid.rsplit("[", 1)[-1]


def test_s18_p1_work_package_inventory_has_exact_schema_and_authority():
    inventory = _load_inventory()

    _validate_s18_p1_work_package(inventory)


@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "unknown", "missing", "cap", "legacy"],
    ids=[
        "duplicate-full-id",
        "unknown-valid-id",
        "missing-authority-id",
        "reserved-cap-id",
        "legacy-invalid-id",
    ],
)
def test_s18_p1_work_package_inventory_rejects_id_set_drift(mutation):
    inventory = deepcopy(_load_inventory())
    specs = inventory["work_package_specs"]["S18_P1"]["specs"]
    if mutation == "duplicate":
        specs.insert(1, deepcopy(specs[0]))
    elif mutation == "unknown":
        extra = deepcopy(specs[0])
        extra["full_id"] = "S18-COV-016"
        specs.append(extra)
    elif mutation == "missing":
        specs.pop()
    elif mutation == "cap":
        extra = deepcopy(specs[0])
        extra["full_id"] = "S18-CAP-001"
        specs.append(extra)
    else:
        extra = deepcopy(specs[0])
        extra["full_id"] = "S18-P1-CLAIM-001"
        specs.append(extra)

    with pytest.raises(AssertionError):
        _validate_s18_p1_work_package(inventory)


@pytest.mark.parametrize(
    "level",
    ["top", "work-package", "spec"],
    ids=["top-level", "work-package", "spec-record"],
)
def test_s18_p1_work_package_inventory_rejects_unknown_schema_keys(level):
    inventory = deepcopy(_load_inventory())
    package = inventory["work_package_specs"]["S18_P1"]
    if level == "top":
        inventory["authority_ids"] = list(S18_P1_ID_AUTHORITY)
    elif level == "work-package":
        package["default_status"] = "planned"
    else:
        package["specs"][0]["reason"] = "free-form status is not authoritative"

    with pytest.raises(AssertionError):
        _validate_s18_p1_work_package(inventory)


def test_s18_p1_work_package_inventory_binds_stable_exact_collected_nodeids():
    inventory = _load_inventory()

    _validate_s18_p1_work_package(inventory, collected=_collect_nodes())


def test_s18_p1_collection_authority_ignores_hostile_pytest_environment(tmp_path, monkeypatch):
    plugin = tmp_path / "hostile_collection_plugin.py"
    forged = tuple(nodeid for record in S18_P1_AUTHORITY.values() for nodeid in record["nodeids"])
    plugin.write_text(
        "def pytest_sessionfinish(session, exitstatus):\n"
        + "    print("
        + repr("\n".join(forged))
        + ")\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("PYTEST_PLUGINS", "hostile_collection_plugin")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--ignore=tests/contract/test_security_coverage_gate.py")

    collected = _collect_nodes()

    assert set(forged) <= collected


@pytest.mark.parametrize(
    "mutation",
    [
        "implemented-without-node",
        "planned-host-verified",
        "host-verified-without-bundle",
        "qualified-without-closed-evidence",
    ],
)
def test_s18_p1_work_package_inventory_status_and_evidence_are_coherent(mutation):
    inventory = deepcopy(_load_inventory())
    specs = inventory["work_package_specs"]["S18_P1"]["specs"]
    implemented = next(spec for spec in specs if spec["full_id"] == "S18-COV-015")
    planned = next(spec for spec in specs if spec["full_id"] == "S18-ABA-001")
    if mutation == "implemented-without-node":
        implemented["nodeids"] = []
    elif mutation == "planned-host-verified":
        planned["verification_status"] = "host-verified"
    elif mutation == "host-verified-without-bundle":
        implemented["verification_status"] = "host-verified"
    else:
        implemented["qualification_status"] = "platform-qualified"

    with pytest.raises(AssertionError):
        _validate_s18_p1_work_package(inventory)


@pytest.mark.parametrize(
    "mutation",
    ["nodeid-swap", "runner-scope", "target-scope", "status-downgrade"],
    ids=[
        "cross-id-nodeid-swap",
        "runner-scope-drift",
        "target-scope-drift",
        "implemented-status-downgrade",
    ],
)
def test_s18_p1_work_package_inventory_rejects_semantic_mapping_drift(mutation):
    inventory = deepcopy(_load_inventory())
    specs = inventory["work_package_specs"]["S18_P1"]["specs"]
    cov = next(spec for spec in specs if spec["full_id"] == "S18-COV-015")
    junit = next(spec for spec in specs if spec["full_id"] == "S18-JUNIT-001")
    if mutation == "nodeid-swap":
        cov["nodeids"], junit["nodeids"] = junit["nodeids"], cov["nodeids"]
    elif mutation == "runner-scope":
        cov["runner_scope"] = ["macos"]
    elif mutation == "target-scope":
        cov["target_scope"] = ["retention"]
    else:
        cov["implementation_status"] = "planned"
        cov["nodeids"] = []

    with pytest.raises(AssertionError):
        _validate_s18_p1_work_package(inventory)


def _new_evidence_reference(tmp_path, name="evidence.json"):
    evidence_path = tmp_path / name
    content = b'{"kind":"independent-review"}\n'
    evidence_path.write_bytes(content)
    return {
        "kind": "independent-review",
        "path": str(evidence_path),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "missing"),
        ("hash-mismatch", "hash mismatch"),
        ("symlink", "noncanonical|symlink"),
        ("case-drift", "missing|spelling"),
        ("parent-segment", "noncanonical"),
        ("dot-segment", "noncanonical"),
        ("duplicate-separator", "noncanonical"),
        ("directory", "non-regular"),
    ],
)
def test_s18_p1_evidence_reader_rejects_path_or_hash_drift(mutation, message, tmp_path):
    reference = _new_evidence_reference(tmp_path)
    evidence_path = Path(reference["path"])
    if mutation == "missing":
        reference["path"] = str(tmp_path / "missing.json")
    elif mutation == "hash-mismatch":
        reference["sha256"] = "0" * 64
    elif mutation == "symlink":
        symlink_path = tmp_path / "evidence-link.json"
        symlink_path.symlink_to(evidence_path)
        reference["path"] = str(symlink_path)
    elif mutation == "case-drift":
        reference["path"] = str(evidence_path.with_name(evidence_path.name.upper()))
    elif mutation == "parent-segment":
        reference["path"] = f"{tmp_path}/../{tmp_path.name}/{evidence_path.name}"
    elif mutation == "dot-segment":
        reference["path"] = f"{tmp_path}/./{evidence_path.name}"
    elif mutation == "duplicate-separator":
        reference["path"] = f"{tmp_path}//{evidence_path.name}"
    else:
        reference["path"] = str(tmp_path)

    with pytest.raises(AssertionError, match=message):
        _read_s18_p1_evidence(reference)


def test_s18_p1_evidence_reader_hashes_canonical_regular_file(tmp_path):
    reference = _new_evidence_reference(tmp_path)

    content = _read_s18_p1_evidence(reference)

    assert hashlib.sha256(content).hexdigest() == reference["sha256"]


def test_s18_p1_evidence_reader_rejects_oversize_regular_file(tmp_path):
    reference = _new_evidence_reference(tmp_path)
    evidence_path = Path(reference["path"])
    evidence_path.write_bytes(b"")
    with evidence_path.open("r+b") as stream:
        stream.truncate(S18_P1_MAX_EVIDENCE_BYTES + 1)

    with pytest.raises(AssertionError, match="oversize"):
        _read_s18_p1_evidence(reference)


def test_s18_p1_work_package_inventory_cannot_self_issue_verification_evidence(
    tmp_path,
):
    inventory = deepcopy(_load_inventory())
    spec = next(
        item
        for item in inventory["work_package_specs"]["S18_P1"]["specs"]
        if item["full_id"] == "S18-COV-015"
    )
    spec["verification_status"] = "evidence-closed"
    spec["qualification_status"] = "platform-qualified"
    references = []
    for index, kind in enumerate(
        ("independent-review", "qualification-ledger", "raw-run-manifest")
    ):
        reference = _new_evidence_reference(tmp_path, f"{index}-{kind}.json")
        reference["kind"] = kind
        references.append(reference)
    spec["evidence_refs"] = sorted(
        references,
        key=lambda reference: (
            reference["kind"],
            reference["path"],
            reference["sha256"],
        ),
    )

    with pytest.raises(AssertionError, match="inventory record drift"):
        _validate_s18_p1_work_package(inventory)


def test_s18_p1_work_package_rejects_unauthorized_evidence_before_path_io():
    inventory = deepcopy(_load_inventory())
    spec = next(
        item
        for item in inventory["work_package_specs"]["S18_P1"]["specs"]
        if item["full_id"] == "S18-COV-015"
    )
    spec["evidence_refs"] = [
        {
            "kind": "host-bundle",
            "path": "/private/tmp/authority-must-reject-before-opening.json",
            "sha256": "0" * 64,
        }
    ]

    with pytest.raises(AssertionError, match="inventory record drift"):
        _validate_s18_p1_work_package(inventory)


@pytest.mark.parametrize(
    "mutation",
    ["non-object-spec", "missing-full-id", "non-object-evidence", "missing-sha", "int-sha"],
)
def test_s18_p1_work_package_inventory_rejects_malformed_records_stably(mutation):
    inventory = deepcopy(_load_inventory())
    specs = inventory["work_package_specs"]["S18_P1"]["specs"]
    if mutation == "non-object-spec":
        specs[0] = []
    elif mutation == "missing-full-id":
        specs[0].pop("full_id")
    else:
        evidence = {
            "kind": "host-bundle",
            "path": "/private/tmp/not-read-before-authority.json",
            "sha256": "0" * 64,
        }
        if mutation == "non-object-evidence":
            specs[2]["evidence_refs"] = [[]]
        elif mutation == "missing-sha":
            evidence.pop("sha256")
            specs[2]["evidence_refs"] = [evidence]
        else:
            evidence["sha256"] = 1
            specs[2]["evidence_refs"] = [evidence]

    with pytest.raises(AssertionError):
        _validate_s18_p1_work_package(inventory)


def test_s18_p1_work_package_inventory_preserves_product_inventory_semantics():
    inventory = _load_inventory()

    assert inventory["source_plan"] == "docs/AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md"
    assert inventory["expected_plan_id_count"] == 274
    assert len(_expanded_plan_ids(inventory)) == 274
    assert inventory["ignored_non_spec_tokens"] == ["SHA-256"]


def test_qualification_is_separate_from_implementation_evidence():
    inventory = _load_inventory()
    implemented = inventory["implemented"]
    levels = inventory["qualification_levels"]
    overrides = inventory["qualification_overrides"]

    assert levels == [
        "implemented-unqualified",
        "qualified-portable",
        "qualified-canonical",
        "qualified-release",
    ]
    assert inventory["default_implemented_qualification"] == levels[0]
    assert set(overrides) <= set(implemented)

    for stable_id, qualification in overrides.items():
        assert set(qualification) == {
            "status",
            "scope",
            "environment_manifest",
            "nodeid",
        }
        assert qualification["status"] in levels[1:]
        assert qualification["scope"]
        assert qualification["nodeid"] == implemented[stable_id]

        manifest_path = REPOSITORY_ROOT / qualification["environment_manifest"]
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "canonical"
        assert manifest["scope"] == qualification["scope"]
        assert stable_id in manifest["case_id"]

        if qualification["status"] == "qualified-release":
            assert manifest.get("release_provenance"), (
                f"{stable_id} cannot be release-qualified without release provenance"
            )


def test_every_declared_marker_selects_collected_tests():
    all_nodes = _collect_nodes()
    declared = _declared_markers()
    assert declared, "at least one real test marker must be declared"

    for marker in sorted(declared):
        selected = _collect_nodes(marker)
        assert selected, f"declared marker {marker!r} has no collected tests"
        assert selected <= all_nodes

        directory = REPOSITORY_ROOT / "tests" / marker
        if directory.is_dir():
            expected = {nodeid for nodeid in all_nodes if nodeid.startswith(f"tests/{marker}/")}
            if marker == "system":
                # POSIX system semantics are cross-cutting: existing retention
                # contracts also carry this marker. The dedicated directory
                # must be fully marked without excluding those contract tests.
                assert expected <= selected, (
                    f"tests/system/ contains unmarked nodes: {sorted(expected - selected)}"
                )
                continue
            assert selected == expected, (
                f"marker {marker!r} must exactly cover tests/{marker}/: "
                f"missing={sorted(expected - selected)}, "
                f"outside={sorted(selected - expected)}"
            )


def test_portable_coverage_gate_is_executable_and_scoped():
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    coverage = pyproject["tool"]["coverage"]
    assert coverage["run"]["source"] == ["t2l"]
    assert coverage["run"]["omit"] == ["*/t2l/mtl/*"]
    assert coverage["report"]["omit"] == ["*/t2l/mtl/*"]
    assert coverage["report"]["fail_under"] == 80

    script_path = REPOSITORY_ROOT / "scripts" / "run_portable_coverage.sh"
    script_mode = script_path.stat().st_mode
    assert script_mode & stat.S_IXUSR
    script = script_path.read_text(encoding="utf-8")
    assert "tests/unit tests/contract tests/component" in script
    assert "--cov=t2l" in script
    assert "--cov-fail-under=80" in script
