from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts import evidence_manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts/evidence_manifest.py"


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_junit(
    path: Path,
    classnames: tuple[str, ...],
    *,
    skipped: tuple[int, ...] = (),
) -> None:
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


@pytest.fixture
def evidence_case(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "evidence@example.invalid")
    _git(repo, "config", "user.name", "Evidence Test")
    (repo / "uv.lock").write_text("lock\n", encoding="utf-8")
    profile = repo / "profile.json"
    profile.write_text('{"profile":"legacy-v1"}\n', encoding="utf-8")
    oracle = repo / "oracle.json"
    oracle.write_text('{"oracle":"fixed"}\n', encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")

    root = tmp_path / "evidence"
    root.mkdir()
    junit = root / "portable.xml"
    _write_junit(junit, ("tests.unit.test_example", "tests.contract.test_example"))
    gate = root / "portable-gate.json"
    gate.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "pytest-layer",
                "layer": "portable",
                "passed": True,
                "tests": 2,
                "skipped": 0,
                "failures_or_errors": 0,
                "input_junit_sha256": _sha256(junit),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "repo": repo,
        "root": root,
        "junit": junit,
        "gate": gate,
        "profile": profile,
        "oracle": oracle,
    }


def _create_portable(case: dict[str, object], **overrides: object) -> Path:
    arguments = {
        "output": Path(case["root"]) / "evidence.json",
        "repo_root": Path(case["repo"]),
        "evidence_root": Path(case["root"]),
        "layer": "portable",
        "network_policy": "network-denied",
        "junit": "portable.xml",
        "gate_json": "portable-gate.json",
        "lock": "uv.lock",
        "profile_manifest": None,
        "oracles": (),
        "command_id": "portable-required",
        "selectors": ("tests/unit", "tests/contract", "tests/component"),
        "started_at_utc": "2026-09-05T00:00:00Z",
        "duration_seconds": 1.25,
        "exit_code": 0,
        "qualification": "implemented-unqualified",
        "spec_ids": (),
        "container_image_digest": None,
        "wheelhouse_manifest": None,
        "release": None,
    }
    arguments.update(overrides)
    evidence_manifest.create_manifest(**arguments)
    return Path(arguments["output"])


def test_evidence_create_and_verify_round_trip_binds_local_state(evidence_case):
    manifest_path = _create_portable(evidence_case)

    document = evidence_manifest.verify_manifest(
        manifest_path,
        repo_root=Path(evidence_case["repo"]),
    )

    assert document["claim"] == {"layer": "portable", "spec_ids": []}
    assert document["source"] == {
        "head": _git(Path(evidence_case["repo"]), "rev-parse", "HEAD"),
        "dirty": False,
        "diff_sha256": hashlib.sha256(b"").hexdigest(),
    }
    assert document["environment"]["network_policy"] == "network-denied"
    assert document["inputs"]["lock"]["path"] == "uv.lock"
    assert document["artifacts"]["junit"]["sha256"] == _sha256(
        Path(evidence_case["junit"])
    )


def test_evidence_verify_rejects_tampered_artifact(evidence_case):
    manifest_path = _create_portable(evidence_case)
    Path(evidence_case["junit"]).write_text("tampered\n", encoding="utf-8")

    with pytest.raises(evidence_manifest.EvidenceError, match="mismatch"):
        evidence_manifest.verify_manifest(
            manifest_path,
            repo_root=Path(evidence_case["repo"]),
        )


def test_evidence_verify_rejects_source_change_after_creation(evidence_case):
    manifest_path = _create_portable(evidence_case)
    (Path(evidence_case["repo"]) / "new-untracked.txt").write_text(
        "changed source state\n",
        encoding="utf-8",
    )

    with pytest.raises(evidence_manifest.EvidenceError, match="source state"):
        evidence_manifest.verify_manifest(
            manifest_path,
            repo_root=Path(evidence_case["repo"]),
        )


@pytest.mark.parametrize("unsafe_path", ("../escape.xml", "/tmp/escape.xml"))
def test_evidence_verify_rejects_escaping_artifact_path(
    evidence_case,
    unsafe_path: str,
):
    manifest_path = _create_portable(evidence_case)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["artifacts"]["junit"]["path"] = unsafe_path
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(evidence_manifest.EvidenceError, match="canonical relative path"):
        evidence_manifest.verify_manifest(
            manifest_path,
            repo_root=Path(evidence_case["repo"]),
        )


def test_evidence_verify_rejects_symlink_artifact(evidence_case):
    manifest_path = _create_portable(evidence_case)
    junit = Path(evidence_case["junit"])
    real_junit = junit.with_name("real.xml")
    os.replace(junit, real_junit)
    junit.symlink_to(real_junit)

    with pytest.raises(evidence_manifest.EvidenceError, match="symlink"):
        evidence_manifest.verify_manifest(
            manifest_path,
            repo_root=Path(evidence_case["repo"]),
        )


@pytest.mark.parametrize("cross_layer", ("gate", "junit"))
def test_evidence_verify_rejects_cross_layer_results(evidence_case, cross_layer: str):
    manifest_path = _create_portable(evidence_case)
    if cross_layer == "gate":
        gate = json.loads(Path(evidence_case["gate"]).read_text(encoding="utf-8"))
        gate["layer"] = "package"
        Path(evidence_case["gate"]).write_text(json.dumps(gate), encoding="utf-8")
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        document["artifacts"]["gate_json"] = _record(
            Path(evidence_case["gate"]), Path(evidence_case["root"])
        )
        manifest_path.write_text(json.dumps(document), encoding="utf-8")
    else:
        _write_junit(Path(evidence_case["junit"]), ("tests.package.test_wheel",))
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        document["artifacts"]["junit"] = _record(
            Path(evidence_case["junit"]), Path(evidence_case["root"])
        )
        manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(evidence_manifest.EvidenceError, match="another layer"):
        evidence_manifest.verify_manifest(
            manifest_path,
            repo_root=Path(evidence_case["repo"]),
        )


def test_evidence_verify_rejects_missing_required_field(evidence_case):
    manifest_path = _create_portable(evidence_case)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    del document["source"]["diff_sha256"]
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(
        evidence_manifest.EvidenceError,
        match=r"source\.diff_sha256 is required",
    ):
        evidence_manifest.verify_manifest(
            manifest_path,
            repo_root=Path(evidence_case["repo"]),
        )


@pytest.mark.parametrize("missing", ("wheelhouse", "image-digest"))
def test_package_evidence_requires_wheelhouse_and_image_digest(
    evidence_case,
    missing: str,
):
    root = Path(evidence_case["root"])
    _write_junit(root / "package.xml", ("tests.package.test_wheel",))
    (root / "package-gate.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "pytest-layer",
                "layer": "package",
                "passed": True,
                "tests": 1,
                "skipped": 0,
                "failures_or_errors": 0,
                "input_junit_sha256": _sha256(root / "package.xml"),
            }
        ),
        encoding="utf-8",
    )
    wheelhouse = root / "wheelhouse-manifest.json"
    wheelhouse.write_text('{"schema_version":1}\n', encoding="utf-8")
    wheelhouse_argument = None if missing == "wheelhouse" else wheelhouse.name
    image_digest = None if missing == "image-digest" else f"sha256:{'a' * 64}"
    expected = (
        r"package\.wheelhouse_manifest is required"
        if missing == "wheelhouse"
        else r"environment\.container_image_digest must be a sha256 image digest"
    )
    with pytest.raises(
        evidence_manifest.EvidenceError,
        match=expected,
    ):
        _create_portable(
            evidence_case,
            layer="package",
            profile_manifest="profile.json",
            junit="package.xml",
            gate_json="package-gate.json",
            wheelhouse_manifest=wheelhouse_argument,
            container_image_digest=image_digest,
        )


def test_diagnostic_may_bind_failure_but_cannot_be_relabelled_qualifying(
    evidence_case,
):
    junit = Path(evidence_case["junit"])
    _write_junit(junit, ("tests.unit.test_example",), skipped=(0,))
    gate = Path(evidence_case["gate"])
    gate.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "pytest-layer",
                "layer": "portable",
                "passed": False,
                "tests": 1,
                "skipped": 1,
                "failures_or_errors": 0,
                "input_junit_sha256": _sha256(junit),
            }
        ),
        encoding="utf-8",
    )
    manifest_path = _create_portable(
        evidence_case,
        qualification="diagnostic",
        exit_code=1,
    )
    evidence_manifest.verify_manifest(
        manifest_path,
        repo_root=Path(evidence_case["repo"]),
    )

    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["qualification"]["level"] = "implemented-unqualified"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(evidence_manifest.EvidenceError, match="passing zero-skip gate"):
        evidence_manifest.verify_manifest(
            manifest_path,
            repo_root=Path(evidence_case["repo"]),
        )


@pytest.mark.parametrize("level", ("qualified-canonical", "qualified-release"))
def test_schema_v1_rejects_self_asserted_qualification(evidence_case, level: str):
    manifest_path = _create_portable(evidence_case)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["qualification"]["level"] = level
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(
        evidence_manifest.EvidenceError,
        match=rf"schema_version 1 cannot produce {level}",
    ):
        evidence_manifest.verify_manifest(
            manifest_path,
            repo_root=Path(evidence_case["repo"]),
        )


def test_evidence_cli_create_and_verify(evidence_case):
    root = Path(evidence_case["root"])
    repo = Path(evidence_case["repo"])
    output = root / "cli-evidence.json"
    create = subprocess.run(
        [
            sys.executable,
            os.fspath(SCRIPT),
            "create",
            "--repo-root",
            os.fspath(repo),
            "--evidence-root",
            os.fspath(root),
            "--output",
            "cli-evidence.json",
            "--layer",
            "portable",
            "--network-policy",
            "network-denied",
            "--junit",
            "portable.xml",
            "--gate-json",
            "portable-gate.json",
            "--command-id",
            "portable-required",
            "--started-at-utc",
            "2026-09-05T00:00:00Z",
            "--duration-seconds",
            "1.25",
            "--exit-code",
            "0",
            "--qualification",
            "implemented-unqualified",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert create.returncode == 0, create.stderr
    assert output.is_file()

    verify = subprocess.run(
        [
            sys.executable,
            os.fspath(SCRIPT),
            "verify",
            os.fspath(output),
            "--repo-root",
            os.fspath(repo),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stderr
    assert json.loads(verify.stdout)["valid"] is True


def test_evidence_cli_fails_closed_without_rewriting_manifest(evidence_case):
    manifest_path = _create_portable(evidence_case)
    original = manifest_path.read_bytes()
    Path(evidence_case["gate"]).write_text("{}\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            os.fspath(SCRIPT),
            "verify",
            os.fspath(manifest_path),
            "--repo-root",
            os.fspath(Path(evidence_case["repo"])),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "evidence verification failed:" in result.stderr
    assert manifest_path.read_bytes() == original


def test_evidence_verify_rejects_symlinked_manifest(evidence_case):
    manifest_path = _create_portable(evidence_case)
    real_manifest = manifest_path.with_name("real-evidence.json")
    os.replace(manifest_path, real_manifest)
    manifest_path.symlink_to(real_manifest)

    with pytest.raises(evidence_manifest.EvidenceError, match="must not be a symlink"):
        evidence_manifest.verify_manifest(
            manifest_path,
            repo_root=Path(evidence_case["repo"]),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("tests", 999),
        ("skipped", 1),
        ("failures_or_errors", 1),
        ("input_junit_sha256", "0" * 64),
        ("passed", False),
    ),
)
def test_evidence_verify_recomputes_gate_binding_and_counts(
    evidence_case,
    field: str,
    value: object,
):
    manifest_path = _create_portable(evidence_case)
    gate_path = Path(evidence_case["gate"])
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate[field] = value
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["artifacts"]["gate_json"] = _record(
        gate_path,
        Path(evidence_case["root"]),
    )
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(
        evidence_manifest.EvidenceError,
        match=r"does not match|does not bind",
    ):
        evidence_manifest.verify_manifest(
            manifest_path,
            repo_root=Path(evidence_case["repo"]),
        )
