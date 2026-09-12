"""B3f-R2 atomic runtime identity migration contracts."""

from __future__ import annotations

import ast
import base64
import errno
import hashlib
import inspect
import json
import os
import subprocess
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import security_pytest_bootstrap as bootstrap
from scripts import verify_security_coverage as verifier
from tests.contract import security_runtime_r2_artifact_oracles as artifact_oracles
from tests.contract import test_security_coverage_gate as gate_contract
from tests.contract.security_runtime_r2_runner_harness import (
    EXACT_UV_RUN_PREFIX,
    AliasSpec,
    BootstrapArtifacts,
    RunnerHarness,
    RunnerScenario,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPOSITORY_ROOT / "scripts/run_security_coverage.sh"
POLICY = REPOSITORY_ROOT / "packaging/security-coverage-policy.toml"
BOOTSTRAP_OBSERVATION = (
    "--plugin-identity=/evidence/plugin-identity.json",
    "--runtime-uv-path=/opt/homebrew/Cellar/uv/0.12.9/bin/uv",
    "--runtime-uv-version=0.12.9",
    "--runtime-uv-sha256=" + "a" * 64,
    "--runtime-timestamp=2026-09-07T12:34:56.123456Z",
)
RUNTIME_SUMMARY_KEYS = frozenset(
    {
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
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _runner_source() -> str:
    return RUNNER.read_text(encoding="utf-8")


def _policy() -> dict[str, object]:
    return verifier.tomllib.loads(POLICY.read_text(encoding="utf-8"))


def _expected_runtime_invalid(artifact_sha256: str | None) -> dict[str, object]:
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


def _future(module: object, name: str):
    value = getattr(module, name, None)
    assert callable(value), f"B3f-R2 RED: missing callable {name}"
    return value


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o700)


def _b64(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def _record_hash(content: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode()


def _runtime_identity_fixture(tmp_path, monkeypatch) -> dict[str, object]:
    base_prefix = tmp_path / "base"
    home = base_prefix / "home"
    home.mkdir(parents=True)
    executable_target = home / "python3.11"
    executable_bytes = b"synthetic python executable\n"
    executable_target.write_bytes(executable_bytes)
    executable_target.chmod(0o700)
    venv_root = tmp_path / "venv"
    (venv_root / "bin").mkdir(parents=True)
    executable = venv_root / "bin/python"
    executable.symlink_to(executable_target)
    site_packages = venv_root / "lib/python3.11/site-packages"
    site_packages.mkdir(parents=True)
    pyvenv = (
        f"home = {home}\n"
        "include-system-site-packages = false\n"
        "version = 3.11.9\n"
    ).encode()
    pyvenv_path = venv_root / "pyvenv.cfg"
    pyvenv_path.write_bytes(pyvenv)
    uv_path = tmp_path / "tools/uv"
    uv_path.parent.mkdir()
    uv_bytes = b"synthetic uv executable\n"
    uv_path.write_bytes(uv_bytes)
    uv_path.chmod(0o700)
    versions = {
        "coverage": "7.10.6",
        "pluggy": "1.6.0",
        "pytest": "8.4.2",
        "pytest-cov": "7.0.0",
    }
    sources = {
        "coverage/__init__.py": b"__version__ = '7.10.6'\n",
        "pluggy/__init__.py": b"__version__ = '1.6.0'\n",
        "pytest/__init__.py": b"__version__ = '8.4.2'\n",
        "pytest_cov/__init__.py": b"__version__ = '7.0.0'\n",
        "pytest_cov/plugin.py": b"def pytest_configure(config):\n    return None\n",
    }
    for relative, content in sources.items():
        path = site_packages.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    lock_content = (
        b'version = 1\nrevision = 1\nrequires-python = ">=3.11"\n'
        b'[[package]]\nname = "coverage"\nversion = "7.10.6"\n'
        b'[[package]]\nname = "pluggy"\nversion = "1.6.0"\n'
        b'[[package]]\nname = "pytest"\nversion = "8.4.2"\ndependencies = [{ name = "pluggy" }]\n'
        b'[[package]]\nname = "pytest-cov"\nversion = "7.0.0"\ndependencies = [{ name = "coverage" }, { name = "pluggy" }, { name = "pytest" }]\n'
    )
    lock_document = verifier.tomllib.loads(lock_content.decode())
    lock_packages = {item["name"]: item for item in lock_document["package"]}
    lock_sha = _sha256(lock_content)
    required_map = {
        "coverage": ("coverage/__init__.py",),
        "pluggy": ("pluggy/__init__.py",),
        "pytest": ("pytest/__init__.py",),
        "pytest-cov": ("pytest_cov/__init__.py", "pytest_cov/plugin.py"),
    }
    dependencies = {
        "coverage": [],
        "pluggy": [],
        "pytest": ["pluggy"],
        "pytest-cov": ["coverage", "pluggy", "pytest"],
    }
    distributions = {}
    for name, required in required_map.items():
        dist_info = f"{name.replace('-', '_')}-{versions[name]}.dist-info"
        dist_path = site_packages / dist_info
        dist_path.mkdir()
        metadata = f"Metadata-Version: 2.4\nName: {name}\nVersion: {versions[name]}\n\n".encode()
        rows = []
        normalized = []
        entries = {}
        for relative in required:
            content = sources[relative]
            digest = _sha256(content)
            rows.append(f"{relative},sha256={_record_hash(content)},{len(content)}")
            normalized.append({"kind": "required", "path": relative, "sha256": digest, "size": len(content)})
            entries[relative] = {"bytes": _b64(content), "size": len(content), "sha256": digest}
        opaque = f"../opaque-{name}.txt"
        opaque_content = name.encode()
        rows.append(f"{opaque},sha256={_record_hash(opaque_content)},{len(opaque_content)}")
        normalized.append({"kind": "opaque", "path": opaque, "sha256": _sha256(opaque_content), "size": len(opaque_content)})
        rows.append(f"{dist_info}/RECORD,,")
        normalized.append({"kind": "self", "path": f"{dist_info}/RECORD", "sha256": None, "size": None})
        record = ("\n".join(rows) + "\n").encode()
        (dist_path / "METADATA").write_bytes(metadata)
        (dist_path / "RECORD").write_bytes(record)
        package = lock_packages[name]
        canonical_package = _canonical(package)
        distributions[name] = {
            "installed": {
                "name": name,
                "version": versions[name],
                "dist_info": dist_info,
                "metadata_bytes": _b64(metadata),
                "metadata_size": len(metadata),
                "metadata_sha256": _sha256(metadata),
                "record_bytes": _b64(record),
                "record_size": len(record),
                "record_sha256": _sha256(record),
                "record_rows": normalized,
                "required_entries": entries,
            },
            "lock": {
                "name": name,
                "version": versions[name],
                "exact_package_object": package,
                "canonical_package_bytes": _b64(canonical_package),
                "lock_package_sha256": _sha256(canonical_package),
                "lock_file_sha256": lock_sha,
                "required_dependencies": dependencies[name],
            },
        }
    events_path = tmp_path / "repository/scripts/pytest_security_events.py"
    events_path.parent.mkdir(parents=True)
    events_content = b"def pytest_configure(config):\n    return None\n"
    events_path.write_bytes(events_content)
    monkeypatch.setattr(verifier, "PYTEST_EVENTS_PLUGIN_PATH", events_path)
    timestamp = "2026-09-07T12:34:56.123456Z"
    document = {
        "schema_version": 2,
        "provenance": "installed-record-consistent",
        "scope": {"run_id": "run-001", "target": "capture", "runner": "macos", "attempt": 1, "timestamp": timestamp},
        "runtime": {
            "executable": str(executable), "executable_realpath": str(executable_target),
            "executable_size": len(executable_bytes), "executable_sha256": _sha256(executable_bytes),
            "venv_root": str(venv_root), "base_prefix": str(base_prefix), "site_packages": str(site_packages), "home": str(home),
            "pyvenv_cfg_path": str(pyvenv_path), "pyvenv_cfg_bytes": _b64(pyvenv), "pyvenv_cfg_size": len(pyvenv), "pyvenv_cfg_sha256": _sha256(pyvenv),
            "implementation": "CPython", "version": "3.11.9", "cache_tag": "cpython-311", "system": "Darwin", "machine": "arm64",
            "isolated": True, "no_site": True, "dont_write_bytecode": True,
        },
        "uv": {"path": str(uv_path), "version": "0.12.9", "sha256": _sha256(uv_bytes)},
        "uv_lock_sha256": lock_sha,
        "distributions": distributions,
        "plugins": {
            "pytest_cov.plugin": {"file": str(site_packages / "pytest_cov/plugin.py"), "sha256": _sha256(sources["pytest_cov/plugin.py"]), "distribution": "pytest-cov", "entry": "pytest_cov/plugin.py"},
            "scripts.pytest_security_events": {"file": str(events_path), "sha256": _sha256(events_content), "distribution": None, "entry": None},
        },
    }
    semantic = dict(document)
    semantic["scope"] = {"runner": "macos"}
    document["semantic_runtime_sha256"] = _sha256(_canonical(semantic))
    return {
        "document": document,
        "content": (json.dumps(document, indent=2, sort_keys=True) + "\n").encode(),
        "lock_content": lock_content,
        "events_content": events_content,
        "timestamp": timestamp,
    }


def _rebind_semantic(document: dict[str, object]) -> None:
    semantic = deepcopy(document)
    semantic.pop("semantic_runtime_sha256", None)
    semantic["scope"] = {"runner": document["scope"]["runner"]}
    document["semantic_runtime_sha256"] = _sha256(_canonical(semantic))


def _runtime_report(fixture, document=None, **overrides):
    value = fixture["document"] if document is None else document
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    arguments = {
        "run_id": "run-001",
        "target": "capture",
        "runner": "macos",
        "attempt": 1,
        "started_at": fixture["timestamp"],
        "policy": _policy(),
        "uv_lock_content": fixture["lock_content"],
        "pytest_events_plugin_content": fixture["events_content"],
    }
    arguments.update(overrides)
    return verifier._runtime_identity_validation_core(content, **arguments)


def _command_fixture(fixture, tmp_path):
    policy = _policy()
    uv = fixture["document"]["uv"]
    started = fixture["timestamp"]
    plugin_path = tmp_path / "plugin-identity.json"
    coverage_path = tmp_path / "coverage.json"
    junit_path = tmp_path / "junit.xml"
    events_path = tmp_path / "pytest-events.json"
    argv = [
        uv["path"], "run", "--offline", "--frozen", "--no-sync", "python",
        "-I", "-S", "-B", str(verifier.BOOTSTRAP_PATH.resolve(strict=True)),
        "--plugin-identity=" + str(plugin_path), "--runtime-uv-path=" + uv["path"],
        "--runtime-uv-version=" + uv["version"], "--runtime-uv-sha256=" + uv["sha256"],
        "--runtime-timestamp=" + started, "--",
        "tests/contract/test_evidence_capture.py", "-q", "-c", "pyproject.toml", "--noconftest",
        "-p", "no:cacheprovider", "-p", "pytest_cov.plugin", "-p", "scripts.pytest_security_events",
        "-o", "xfail_strict=true", "--security-events=" + str(events_path),
        "--security-run-id=run-001", "--security-target=capture", "--security-runner=macos",
        "--security-attempt=1", "--security-test-file=tests/contract/test_evidence_capture.py",
        "--security-max-cases=4096", "--security-max-nodeid-bytes=4096",
        "--security-max-events-bytes=8388608", "--junitxml=" + str(junit_path),
        "--cov=scripts.capture_test_gate", "--cov-branch", "--cov-report=json:" + str(coverage_path),
        "--cov-report=term-missing", "--cov-fail-under=80",
    ]
    value = {
        "schema_version": 4, "run_id": "run-001", "target": "capture", "runner": "macos", "attempt": 1,
        "argv": argv,
        "sanitized_environment": {
            "COVERAGE_FILE": str(tmp_path / ".coverage-capture"), "PYTHONHOME": None,
            "PYTHONPATH": None, "PYTHONUSERBASE": None, "PYTEST_ADDOPTS": None,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_PLUGINS": None,
            "UV_PROJECT_ENVIRONMENT": None, "UV_PYTHON": None,
        },
        "exit_code": 0, "started_at": started, "finished_at": started,
    }
    paths = {
        "target": "capture", "policy": policy, "coverage_path": coverage_path,
        "junit_path": junit_path, "pytest_events_path": events_path,
        "plugin_identity_path": plugin_path,
    }
    return value, paths


def _rebind_artifact(bundle, name):
    manifest = json.loads(bundle["run_manifest"].read_text(encoding="utf-8"))
    manifest["artifact_hashes"][name + "_sha256"] = _sha256(bundle[name].read_bytes())
    bundle["run_manifest"].write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _runner_identity_template(
    *, run_id: str, target: str, attempt: int
) -> bytes:
    value = {
        "schema_version": 2,
        "provenance": "installed-record-consistent",
        "scope": {
            "run_id": run_id,
            "target": target,
            "runner": "macos" if sys.platform == "darwin" else "linux",
            "attempt": attempt,
            "timestamp": "{{RUNTIME_TIMESTAMP}}",
        },
        "runtime": {},
        "uv": {
            "path": "{{UV_PATH}}",
            "version": "{{UV_VERSION}}",
            "sha256": "{{UV_SHA256}}",
        },
        "uv_lock_sha256": "a" * 64,
        "distributions": {
            "coverage": {"installed": {"version": "7.10.6"}},
            "pytest": {"installed": {"version": "8.4.2"}},
        },
        "plugins": {},
        "semantic_runtime_sha256": "0" * 64,
    }
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


_GENERATED_RUNNER_IDENTITY = object()


def _runner_supplier(
    *,
    plugin_identity: bytes | object | None = _GENERATED_RUNNER_IDENTITY,
    pytest_events: bytes | None = b'{"schema_version":3}\n',
    coverage_data: bytes | None = b"raw coverage data\n",
):
    def supply(target: str, run_id: str, attempt: int) -> BootstrapArtifacts:
        identity = (
            _runner_identity_template(run_id=run_id, target=target, attempt=attempt)
            if plugin_identity is _GENERATED_RUNNER_IDENTITY
            else plugin_identity
        )
        return BootstrapArtifacts(
            plugin_identity=identity,
            pytest_events=pytest_events,
            coverage_data=coverage_data,
            coverage_json=b'{"meta":{},"files":{},"totals":{}}\n',
            junit_xml=b'<testsuites tests="0" failures="0" errors="0"/>\n',
            rebind_identity_semantic=(
                plugin_identity is _GENERATED_RUNNER_IDENTITY
            ),
        )

    return supply


_REAL_PREPARED_PUBLICATION_PROBE = r"""
import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

bootstrap_path = Path(sys.argv[1])
output = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("b3f_r2_prepared_publication", bootstrap_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_prepare = module._prepare_bound_runtime
original_local = module._local_events_plugin
original_builder = module._build_runtime_identity_v2
original_writer = module._write_exclusive
original_stable_read = module._stable_read
events_path = (bootstrap_path.parent / "pytest_security_events.py").resolve(strict=True)
state = {
    "prepare": 0,
    "local_events": 0,
    "events_reads": 0,
    "builder": 0,
    "pytest_main": 0,
    "writer": 0,
}
prepared_cov = None
loaded_events = None
built_document = None

def counting_stable_read(path, *args, **kwargs):
    if Path(path) == events_path:
        state["events_reads"] += 1
    return original_stable_read(path, *args, **kwargs)

module._stable_read = counting_stable_read

def tracked_prepare(*args, **kwargs):
    global prepared_cov
    state["prepare"] += 1
    prepared = original_prepare(*args, **kwargs)
    prepared_cov = prepared.loaded_modules["pytest_cov.plugin"]
    sys.modules["pytest"].main = fake_pytest_main
    return prepared

def forbidden_capture(*args, **kwargs):
    raise AssertionError("runtime capture/read occurred after the prepared boundary")

def tracked_local(*args, **kwargs):
    global loaded_events
    state["local_events"] += 1
    loaded_events, identity = original_local(*args, **kwargs)
    module._stable_read = forbidden_capture
    module._capture_runtime_layout = forbidden_capture
    module._capture_named_distribution = forbidden_capture
    module._capture_lock_package = forbidden_capture
    module._load_captured_runtime_modules = forbidden_capture
    return loaded_events, identity

def tracked_builder(*args, **kwargs):
    global built_document
    state["builder"] += 1
    built_document = original_builder(*args, **kwargs)
    return built_document

def tracked_writer(*args, **kwargs):
    state["writer"] += 1
    return original_writer(*args, **kwargs)

def fake_pytest_main(arguments, *, plugins):
    state["pytest_main"] += 1
    assert state["local_events"] == 1
    assert loaded_events is not None
    assert plugins[:2] == [prepared_cov, loaded_events]
    guard = plugins[-1]
    registrations = {
        "pytest_cov.plugin": prepared_cov,
        "scripts.pytest_security_events": loaded_events,
    }
    manager = type("PluginManager", (), {
        "get_plugin": lambda self, name: registrations.get(name)
    })()
    config = type("Config", (), {"pluginmanager": manager})()
    guard.pytest_configure(config)
    return 0

module._prepare_bound_runtime = tracked_prepare
module._local_events_plugin = tracked_local
module._build_runtime_identity_v2 = tracked_builder
module._write_exclusive = tracked_writer
result = module.main([
    "--plugin-identity=" + str(output),
    "--runtime-uv-path=" + str(Path(sys.executable)),
    "--runtime-uv-version=0.12.9",
    "--runtime-uv-sha256=" + "0" * 64,
    "--runtime-timestamp=2026-09-07T12:34:56.123456Z",
    "--",
    "--security-run-id=r2-prepared-publication",
    "--security-target=capture",
    "--security-runner=macos" if sys.platform == "darwin" else "--security-runner=linux",
    "--security-attempt=1",
])
assert result == 0
assert state == {
    "prepare": 1,
    "local_events": 1,
    "events_reads": 1,
    "builder": 1,
    "pytest_main": 1,
    "writer": 1,
}
raw = output.read_bytes()
assert json.loads(raw) == built_document
assert raw == (json.dumps(built_document, indent=2, sort_keys=True) + "\n").encode()
published = output.lstat()
assert stat.S_ISREG(published.st_mode)
assert stat.S_IMODE(published.st_mode) == 0o600
assert published.st_nlink == 1
assert not tuple(output.parent.glob("." + output.name + ".*.tmp"))
print(json.dumps({
    "raw_sha256": hashlib.sha256(raw).hexdigest(),
    "raw_size": len(raw),
    "schema_version": built_document["schema_version"],
    "semantic_runtime_sha256": built_document["semantic_runtime_sha256"],
    "state": state,
}, sort_keys=True))
"""


def test_s18_b3f_r2_existing_root_rejects_before_uv_resolution(tmp_path):
    source = _runner_source()
    shell_guard = 'if [ -e "$artifact_root" ] || [ -L "$artifact_root" ]; then'
    assert shell_guard in source
    assert source.index(shell_guard) < source.index("command -v uv")
    assert source.index(shell_guard) < source.index("python")

    shim = tmp_path / "shim"
    shim.mkdir()
    marker = tmp_path / "uv-called"
    _write_executable(
        shim / "uv",
        "#!/bin/sh\n"
        f"printf called > {marker!s}\n"
        "exit 97\n",
    )
    environment = os.environ.copy()
    environment["PATH"] = os.fspath(shim) + os.pathsep + environment["PATH"]
    cases = []
    directory = tmp_path / "existing-directory"
    directory.mkdir()
    cases.append(directory)
    regular = tmp_path / "existing-file"
    regular.write_text("preserve\n", encoding="utf-8")
    cases.append(regular)
    dangling = tmp_path / "dangling-link"
    dangling.symlink_to(tmp_path / "missing-target")
    cases.append(dangling)
    snapshots = {path: path.lstat() for path in cases}
    runner_copy = tmp_path / "runner-copy.sh"
    runner_copy.write_bytes(RUNNER.read_bytes())
    runner_copy.chmod(0o700)
    results = [
        subprocess.run(
            [os.fspath(runner_copy), os.fspath(path), "s18-r2-existing", "1"],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        for path in cases
    ]
    assert [(item.returncode, item.stdout, item.stderr) for item in results] == [
        (2, "", "SECURITY_COVERAGE_RUNNER_INPUT_INVALID\n")
    ] * 3
    assert not marker.exists()
    assert all(path.lstat() == snapshots[path] for path in cases)

    secret_marker = b"S18_R2_INPUT_HELPER_SECRET_STDERR\n"
    helper_failure = RunnerHarness.create(
        tmp_path / "input-helper-failure", source_root=REPOSITORY_ROOT
    ).run(
        _runner_supplier(),
        scenario=RunnerScenario(
            input_helper_exit_code=7,
            input_helper_stderr=secret_marker,
        ),
    )
    mkdir_results = []
    for label, injected_errno, expected_diagnostic in (
        ("eexist", errno.EEXIST, "SECURITY_COVERAGE_RUNNER_INPUT_INVALID\n"),
        ("eacces", errno.EACCES, "SECURITY_COVERAGE_RUNNER_CONFIGURATION_INVALID\n"),
        ("enospc", errno.ENOSPC, "SECURITY_COVERAGE_RUNNER_CONFIGURATION_INVALID\n"),
    ):
        injected = RunnerHarness.create(
            tmp_path / f"input-helper-{label}", source_root=REPOSITORY_ROOT
        ).run(
            _runner_supplier(),
            scenario=RunnerScenario(input_helper_mkdir_errno=injected_errno),
        )
        mkdir_results.append((injected, expected_diagnostic))
    validation_results = []
    for label, injected_errno, expected_diagnostic in (
        ("enoent", errno.ENOENT, "SECURITY_COVERAGE_RUNNER_INPUT_INVALID\n"),
        ("enotdir", errno.ENOTDIR, "SECURITY_COVERAGE_RUNNER_INPUT_INVALID\n"),
        ("eacces", errno.EACCES, "SECURITY_COVERAGE_RUNNER_CONFIGURATION_INVALID\n"),
        ("eio", errno.EIO, "SECURITY_COVERAGE_RUNNER_CONFIGURATION_INVALID\n"),
    ):
        injected = RunnerHarness.create(
            tmp_path / f"input-helper-validation-{label}",
            source_root=REPOSITORY_ROOT,
        ).run(
            _runner_supplier(),
            scenario=RunnerScenario(input_helper_validation_errno=injected_errno),
        )
        validation_results.append((injected, expected_diagnostic))

    observed = [
        (
            helper_failure.returncode,
            helper_failure.stdout,
            helper_failure.stderr,
            secret_marker.decode() in helper_failure.stderr,
            helper_failure.artifact_root.exists(),
        ),
        *[
            (
                result.returncode,
                result.stdout,
                result.stderr,
                False,
                result.artifact_root.exists(),
            )
            for result, _expected_diagnostic in mkdir_results
        ],
        *[
            (
                result.returncode,
                result.stdout,
                result.stderr,
                False,
                result.artifact_root.exists(),
            )
            for result, _expected_diagnostic in validation_results
        ],
    ]
    expected = [
        (
            2,
            "",
            "SECURITY_COVERAGE_RUNNER_CONFIGURATION_INVALID\n",
            False,
            False,
        ),
        *[
            (2, "", expected_diagnostic, False, False)
            for _result, expected_diagnostic in mkdir_results
        ],
        *[
            (2, "", expected_diagnostic, False, False)
            for _result, expected_diagnostic in validation_results
        ],
    ]
    labels = (
        "helper-stderr",
        "mkdir-eexist",
        "mkdir-eacces",
        "mkdir-enospc",
        "validation-enoent",
        "validation-enotdir",
        "validation-eacces",
        "validation-eio",
    )
    mismatches = [
        f"{label}: observed={actual!r}, expected={wanted!r}"
        for label, actual, wanted in zip(labels, observed, expected, strict=True)
        if actual != wanted
    ]
    assert not mismatches, "\n".join(mismatches)
    for result in [
        helper_failure,
        *(item[0] for item in mkdir_results),
        *(item[0] for item in validation_results),
    ]:
        assert [call.kind for call in result.calls()].count("input-helper") == 1
        assert not any(call.kind == "bootstrap-stub" for call in result.calls())


def test_s18_b3f_r2_runner_resolves_one_absolute_uv_and_reuses_final_prefix(tmp_path):
    source = _runner_source()
    assert source.count("command -v uv") == 1
    assert "/usr/bin/readlink" in source
    assert "python3 -I -B" not in source
    assert "uv run" not in source
    final_prefix = (
        '"$absolute_uv" run --offline --frozen --no-sync python -I -S -B'
    )
    assert source.count(final_prefix) >= 6
    assert source.count('[sys.argv[1], "--version"]') == 1
    assert '"$uv_alias_hops" -le 16' in source
    assert "uv_executable_sha256_before" in source
    assert "uv_executable_sha256_after" in source

    hash_function = source.index("uv_hash() {")
    hash_program_start = source.index("<<'PY'\n", hash_function) + len("<<'PY'\n")
    hash_program_end = source.index("\nPY\n}", hash_program_start)
    hash_program = source[hash_program_start:hash_program_end]
    uv_size_boundary = tmp_path / "uv-size-boundary"
    with uv_size_boundary.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024)
    uv_size_boundary.chmod(0o700)
    boundary_hash = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-", os.fspath(uv_size_boundary)],
        input=hash_program,
        capture_output=True,
        text=True,
        check=False,
        timeout=30.0,
    )
    assert boundary_hash.returncode == 0
    assert boundary_hash.stderr == ""
    assert len(boundary_hash.stdout) == 64
    with uv_size_boundary.open("r+b") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)
    plus_one_hash = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-", os.fspath(uv_size_boundary)],
        input=hash_program,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (plus_one_hash.returncode, plus_one_hash.stdout, plus_one_hash.stderr) == (
        1,
        "",
        "",
    )

    harness = RunnerHarness.create(tmp_path, source_root=REPOSITORY_ROOT)
    result = harness.run(
        _runner_supplier(),
        scenario=RunnerScenario(
            aliases=(AliasSpec(relative=True), AliasSpec(relative=False)),
            poison_path_after_first_call=True,
            verifier_mode="stub-success",
        ),
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    calls = result.calls()
    assert calls
    assert [call.kind for call in calls[:4]] == [
        "embedded-python",
        "embedded-python",
        "version",
        "embedded-python",
    ]
    assert [call.kind for call in calls].count("version") == 1
    assert not any(call.kind in {"invalid-prefix", "blocked-program", "poison"} for call in calls)
    assert all(
        call.prefix_valid is True
        for call in calls
        if call.kind not in {"version"}
    )
    bootstrap_calls = [call for call in calls if call.kind == "bootstrap-stub"]
    assert len(bootstrap_calls) == 2
    resolved_uv = bootstrap_calls[0].argv[0]
    assert Path(resolved_uv).is_absolute() and not Path(resolved_uv).is_symlink()
    assert {call.argv[0] for call in calls} == {resolved_uv}
    assert all(call.cwd == os.fspath(harness.repository_root) for call in calls)
    assert all(
        call.environment
        == {
            "COVERAGE_FILE": call.environment["COVERAGE_FILE"],
            "PYTHONHOME": None,
            "PYTHONPATH": None,
            "PYTHONUSERBASE": None,
            "PYTEST_ADDOPTS": None,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"
            if call.kind == "bootstrap-stub"
            else None,
            "PYTEST_PLUGINS": None,
            "UV_PROJECT_ENVIRONMENT": None,
            "UV_PYTHON": None,
        }
        for call in calls
    )
    assert result.gate_kind("capture") == "stub"
    assert result.gate_kind("retention") == "stub"

    valid_sixteen = RunnerHarness.create(
        tmp_path / "sixteen", source_root=REPOSITORY_ROOT
    ).run(
        _runner_supplier(),
        scenario=RunnerScenario(
            aliases=tuple(AliasSpec(relative=index % 2 == 0) for index in range(16)),
            verifier_mode="stub-success",
        ),
    )
    assert valid_sixteen.returncode == 0, (valid_sixteen.stdout, valid_sixteen.stderr)

    for label, aliases, cycle in (
        (
            "seventeen",
            tuple(AliasSpec(relative=True) for _index in range(17)),
            False,
        ),
        ("cycle", (AliasSpec(relative=True), AliasSpec(relative=False)), True),
    ):
        rejected = RunnerHarness.create(
            tmp_path / label, source_root=REPOSITORY_ROOT
        ).run(
            _runner_supplier(),
            scenario=RunnerScenario(aliases=aliases, alias_cycle=cycle),
        )
        assert (rejected.returncode, rejected.stdout, rejected.stderr) == (
            2,
            "",
            "SECURITY_COVERAGE_RUNNER_CONFIGURATION_INVALID\n",
        )
        assert rejected.calls() == ()

    for index, (banner, exit_code) in enumerate(
        (
            (b"uv 0.12.9\nextra\n", 0),
            (b"uv 0.12.9 (bad (nested))\n", 0),
            (b"uv 0.12.9\x00\n", 0),
            (b"uv 0.12.9\n", 7),
            (b"x" * 513, 0),
        )
    ):
        rejected = RunnerHarness.create(
            tmp_path / f"bad-version-{index}", source_root=REPOSITORY_ROOT
        ).run(
            _runner_supplier(),
            scenario=RunnerScenario(version_stdout=banner, version_exit_code=exit_code),
        )
        assert (rejected.returncode, rejected.stdout, rejected.stderr) == (
            2,
            "",
            "SECURITY_COVERAGE_RUNNER_CONFIGURATION_INVALID\n",
        )
        assert [call.kind for call in rejected.calls()].count("version") == 1

def test_s18_b3f_r2_bootstrap_accepts_only_exact_uv_observation_argv():
    output, uv_identity, timestamp, pytest_arguments = bootstrap._arguments(
        [*BOOTSTRAP_OBSERVATION, "--", "tests/contract/test_evidence_capture.py"]
    )
    assert output == Path("/evidence/plugin-identity.json")
    assert uv_identity == {
        "path": "/opt/homebrew/Cellar/uv/0.12.9/bin/uv",
        "version": "0.12.9",
        "sha256": "a" * 64,
    }
    assert timestamp == "2026-09-07T12:34:56.123456Z"
    assert pytest_arguments == ["tests/contract/test_evidence_capture.py"]

    malformed = []
    baseline = [*BOOTSTRAP_OBSERVATION, "--", "test.py"]
    malformed.append(baseline[1:])
    malformed.append([baseline[0], baseline[0], *baseline[1:]])
    malformed.append([baseline[1], baseline[0], *baseline[2:]])
    for index, replacement in (
        (1, "--runtime-uv-path=/"),
        (2, "--runtime-uv-version=uv 0.12.9"),
        (3, "--runtime-uv-sha256=" + "A" * 64),
        (4, "--runtime-timestamp=2026-09-07T12:34:56Z"),
    ):
        changed = list(baseline)
        changed[index] = replacement
        malformed.append(changed)
    accepted = []
    for arguments in malformed:
        try:
            bootstrap._arguments(arguments)
        except bootstrap.BootstrapError:
            pass
        else:
            accepted.append(arguments)
    assert accepted == []


def test_s18_b3f_r2_prepared_runtime_publishes_v2_without_live_reread(
    tmp_path, monkeypatch
):
    prepared_type = getattr(bootstrap, "PreparedBoundRuntime", None)
    assert prepared_type._fields == (
        "runtime_layout",
        "uv_identity",
        "uv_lock_sha256",
        "distributions",
        "loaded_modules",
        "pytest_cov_plugin_identity",
    )
    prepare_source = inspect.getsource(bootstrap._prepare_bound_runtime)
    assert "return PreparedBoundRuntime(" in prepare_source
    main_source = inspect.getsource(bootstrap.main)
    main_tree = ast.parse(main_source)
    calls = [
        node.func.id
        for node in ast.walk(main_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert calls.count("_prepare_bound_runtime") == 1
    assert calls.count("_local_events_plugin") == 1
    assert calls.count("_build_runtime_identity_v2") == 1
    assert "_pytest_cov_identity" not in calls
    assert '"schema_version": 1' not in main_source

    fixture = _runtime_identity_fixture(tmp_path, monkeypatch)
    runtime_layout = deepcopy(fixture["document"]["runtime"])
    runtime_layout["pyvenv_cfg_bytes"] = base64.b64decode(
        runtime_layout["pyvenv_cfg_bytes"], validate=True
    )
    distributions = deepcopy(fixture["document"]["distributions"])
    for pair in distributions.values():
        installed = pair["installed"]
        installed["metadata_bytes"] = base64.b64decode(
            installed["metadata_bytes"], validate=True
        )
        installed["record_bytes"] = base64.b64decode(
            installed["record_bytes"], validate=True
        )
        installed["record_rows"] = tuple(installed["record_rows"])
        for entry in installed["required_entries"].values():
            entry["bytes"] = base64.b64decode(entry["bytes"], validate=True)
        lock = pair["lock"]
        lock["canonical_package_bytes"] = base64.b64decode(
            lock["canonical_package_bytes"], validate=True
        )
        lock["required_dependencies"] = tuple(lock["required_dependencies"])

    pytest_cov_module = types.ModuleType("pytest_cov.plugin")
    events_module = types.ModuleType("scripts.pytest_security_events")
    prepared = bootstrap.PreparedBoundRuntime(
        runtime_layout=runtime_layout,
        uv_identity=deepcopy(fixture["document"]["uv"]),
        uv_lock_sha256=fixture["document"]["uv_lock_sha256"],
        distributions=distributions,
        loaded_modules={"pytest_cov.plugin": pytest_cov_module},
        pytest_cov_plugin_identity=deepcopy(
            fixture["document"]["plugins"]["pytest_cov.plugin"]
        ),
    )
    output = tmp_path / "published-runtime-identity.json"
    built_documents = []
    real_builder = bootstrap._build_runtime_identity_v2

    def prepared_once(*args, **kwargs):
        assert args == (Path(sys.executable),)
        assert kwargs["uv_identity"] == fixture["document"]["uv"]
        return prepared

    def local_once(repository_root):
        assert repository_root == REPOSITORY_ROOT
        return (
            events_module,
            deepcopy(fixture["document"]["plugins"]["scripts.pytest_security_events"]),
        )

    def build_once(**kwargs):
        assert kwargs["runtime_layout"] is prepared.runtime_layout
        assert kwargs["uv_identity"] is prepared.uv_identity
        assert kwargs["distributions"] is prepared.distributions
        document = real_builder(**kwargs)
        built_documents.append(document)
        return document

    def live_reread_bomb(*args, **kwargs):
        raise AssertionError("main re-read the live runtime after preparation")

    def pytest_main(arguments, *, plugins):
        assert arguments == [
            "--security-run-id=run-001",
            "--security-target=capture",
            "--security-runner=macos",
            "--security-attempt=1",
        ]
        assert plugins[:2] == [pytest_cov_module, events_module]
        manager = types.SimpleNamespace(
            get_plugin=lambda name: {
                "pytest_cov.plugin": pytest_cov_module,
                "scripts.pytest_security_events": events_module,
            }.get(name)
        )
        plugins[-1].pytest_configure(types.SimpleNamespace(pluginmanager=manager))
        return 0

    monkeypatch.setattr(bootstrap, "_prepare_bound_runtime", prepared_once)
    monkeypatch.setattr(bootstrap, "_local_events_plugin", local_once)
    monkeypatch.setattr(bootstrap, "_build_runtime_identity_v2", build_once)
    for name in (
        "_capture_runtime_layout",
        "_capture_named_distribution",
        "_capture_lock_package",
        "_load_captured_runtime_modules",
    ):
        monkeypatch.setattr(bootstrap, name, live_reread_bomb)
    isolated_flags = types.SimpleNamespace(
        **{
            name: getattr(sys.flags, name)
            for name in dir(sys.flags)
            if not name.startswith("_") and not callable(getattr(sys.flags, name))
        }
    )
    isolated_flags.isolated = True
    isolated_flags.no_site = True
    isolated_flags.dont_write_bytecode = True
    monkeypatch.setattr(bootstrap.sys, "flags", isolated_flags)
    monkeypatch.setitem(sys.modules, "pytest_cov.plugin", pytest_cov_module)
    monkeypatch.setitem(sys.modules, "scripts.pytest_security_events", events_module)
    monkeypatch.setattr(pytest, "main", pytest_main)
    result = bootstrap.main(
        [
            f"--plugin-identity={output}",
            f"--runtime-uv-path={prepared.uv_identity['path']}",
            f"--runtime-uv-version={prepared.uv_identity['version']}",
            f"--runtime-uv-sha256={prepared.uv_identity['sha256']}",
            f"--runtime-timestamp={fixture['timestamp']}",
            "--",
            "--security-run-id=run-001",
            "--security-target=capture",
            "--security-runner=macos",
            "--security-attempt=1",
        ]
    )
    assert result == 0
    assert len(built_documents) == 1
    assert json.loads(output.read_text(encoding="utf-8")) == built_documents[0]
    assert output.stat().st_mode & 0o777 == 0o600

    compile(
        _REAL_PREPARED_PUBLICATION_PROBE,
        "<s18-b3f-r2-prepared-publication>",
        "exec",
    )
    real_output = tmp_path / "real-prepared-publication.json"
    real_publication = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            _REAL_PREPARED_PUBLICATION_PROBE,
            os.fspath(bootstrap.__file__),
            os.fspath(real_output),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30.0,
    )
    assert (real_publication.returncode, real_publication.stderr) == (0, "")
    publication_record = json.loads(real_publication.stdout)
    assert publication_record["schema_version"] == 2
    assert len(publication_record["semantic_runtime_sha256"]) == 64
    assert len(publication_record["raw_sha256"]) == 64
    assert publication_record["raw_size"] <= 4 * 1024 * 1024
    assert publication_record["state"] == {
        "prepare": 1,
        "local_events": 1,
        "events_reads": 1,
        "builder": 1,
        "pytest_main": 1,
        "writer": 1,
    }


def test_s18_b3f_r2_timestamp_has_one_authority_and_cross_binding(tmp_path, monkeypatch):
    source = _runner_source()
    assert source.count("started_at=") == 1
    assert '"--runtime-timestamp=$started_at"' in source
    assert "datetime.now" in source
    assert ".%fZ" in source
    command_source = inspect.getsource(verifier._command)
    assert "runtime-timestamp" in command_source
    assert "started_at" in command_source
    assert "RUNNER_CONFIGURATION_INVALID" in command_source
    runtime_report = _future(verifier, "_runtime_identity_validation_core")
    assert "timestamp" in inspect.getsource(runtime_report)
    assert "RUNTIME_IDENTITY_INVALID" in inspect.getsource(runtime_report)
    fixture = _runtime_identity_fixture(tmp_path, monkeypatch)
    command, paths = _command_fixture(fixture, tmp_path)
    assert verifier._command(command, **paths)[1] == []
    changed_command = deepcopy(command)
    changed_command["argv"][14] = "--runtime-timestamp=2026-09-07T12:34:57.123456Z"
    assert verifier._command(changed_command, **paths)[1] == ["RUNNER_CONFIGURATION_INVALID"]
    changed_identity = deepcopy(fixture["document"])
    changed_identity["scope"]["timestamp"] = "2026-09-07T12:34:57.123456Z"
    summary, failures, facts = _runtime_report(fixture, changed_identity)
    assert summary["status"] == "invalid"
    assert failures == ["RUNTIME_IDENTITY_INVALID"]
    assert facts["uv"] == fixture["document"]["uv"]
    assert sorted({*failures, *verifier._command(changed_command, **paths)[1]}) == [
        "RUNNER_CONFIGURATION_INVALID", "RUNTIME_IDENTITY_INVALID"
    ]
    monkeypatch.setattr(
        verifier,
        "PYTEST_EVENTS_PLUGIN_PATH",
        REPOSITORY_ROOT / "scripts/pytest_security_events.py",
    )
    bundle = gate_contract._make_bundle(tmp_path / "full-timestamp")
    command_document = json.loads(bundle["command"].read_text(encoding="utf-8"))
    command_document["started_at"] = "2026-09-06T00:00:02.000000Z"
    bundle["command"].write_text(
        json.dumps(command_document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rebind_artifact(bundle, "command")
    _report, full_failures = gate_contract._verify(bundle)
    assert full_failures == ["RUNNER_CONFIGURATION_INVALID", "RUNTIME_IDENTITY_INVALID"]


def test_s18_b3f_r2_artifact_versions_are_exact_and_old_versions_fail_closed(tmp_path, monkeypatch):
    artifact_oracles.assert_non_identity_artifact_versions(tmp_path / "artifacts")
    policy = _policy()
    assert policy["schema_version"] == 3
    assert verifier._parse_policy(POLICY.read_bytes()) == policy
    assert "must be 3" in inspect.getsource(verifier._parse_policy)
    assert "must be 5" in inspect.getsource(verifier._environment)
    assert "must be 4" in inspect.getsource(verifier._command)
    assert "must be 5" in inspect.getsource(verifier._run_manifest)
    assert '"schema_version": 5' in inspect.getsource(
        verifier.verify_security_coverage
    )
    assert '"schema_version": 1' not in inspect.getsource(bootstrap.main)
    for old in (1, 2.0, True):
        changed = POLICY.read_text(encoding="utf-8").replace("schema_version = 3", f"schema_version = {str(old).lower()}", 1)
        with pytest.raises(verifier.GateFailure):
            verifier._parse_policy(changed.encode())
    fixture = _runtime_identity_fixture(tmp_path, monkeypatch)
    for schema_version in (1, 2.0, True):
        changed_identity = deepcopy(fixture["document"])
        changed_identity["schema_version"] = schema_version
        assert _runtime_report(fixture, changed_identity)[1] == [
            "RUNTIME_IDENTITY_INVALID"
        ]
    identity_shape_cases = []
    for label, container_path, operation, expected in (
        ("scope-extra", ("scope",), ("set", "unexpected", True), ["RUNTIME_IDENTITY_INVALID"]),
        ("scope-missing", ("scope",), ("delete", "attempt", None), ["RUNTIME_IDENTITY_INVALID"]),
        ("runtime-extra", ("runtime",), ("set", "unexpected", True), ["RUNTIME_IDENTITY_INVALID"]),
        ("runtime-missing", ("runtime",), ("delete", "cache_tag", None), ["RUNTIME_IDENTITY_INVALID"]),
        ("uv-extra", ("uv",), ("set", "unexpected", True), ["RUNTIME_IDENTITY_INVALID"]),
        ("uv-missing", ("uv",), ("delete", "version", None), ["RUNTIME_IDENTITY_INVALID"]),
        ("distributions-extra", ("distributions",), ("set", "unexpected", {}), ["RUNTIME_IDENTITY_INVALID"]),
        ("distributions-missing", ("distributions",), ("delete", "coverage", None), ["RUNTIME_IDENTITY_INVALID"]),
        ("plugins-extra", ("plugins",), ("set", "unexpected", {}), ["PLUGIN_IDENTITY_INVALID"]),
        ("plugins-missing", ("plugins",), ("delete", "pytest_cov.plugin", None), ["PLUGIN_IDENTITY_INVALID"]),
        ("plugin-extra", ("plugins", "pytest_cov.plugin"), ("set", "unexpected", True), ["PLUGIN_IDENTITY_INVALID"]),
        ("plugin-missing", ("plugins", "pytest_cov.plugin"), ("delete", "entry", None), ["PLUGIN_IDENTITY_INVALID"]),
    ):
        document = deepcopy(fixture["document"])
        container = document
        for component in container_path:
            container = container[component]
        action, key, value = operation
        if action == "set":
            container[key] = value
        else:
            del container[key]
        _rebind_semantic(document)
        identity_shape_cases.append((label, document, expected))
    assert [
        (label, _runtime_report(fixture, document)[1])
        for label, document, _expected in identity_shape_cases
    ] == [
        (label, expected)
        for label, _document, expected in identity_shape_cases
    ]
    command, paths = _command_fixture(fixture, tmp_path)
    command["schema_version"] = 3
    with pytest.raises(verifier.GateFailure):
        verifier._command(command, **paths)


def test_s18_b3f_r2_identity_read_mode_and_envelope_failures_are_runtime_invalid(tmp_path, monkeypatch):
    report = _future(verifier, "_runtime_identity_validation_core")
    source = inspect.getsource(report)
    assert "RUNTIME_IDENTITY_INVALID" in source
    assert "PLUGIN_IDENTITY_INVALID" in source
    assert "schema_version" in source
    assert "duplicate" in inspect.getsource(verifier._strict_json)
    verify_source = inspect.getsource(verifier.verify_security_coverage)
    assert "plugin_identity_read_failure" not in verify_source
    assert "runtime_identity_read_failure" in verify_source
    assert "runtime_identity_mode_failure" in verify_source
    assert "artifact_sha256" in source
    fixture = _runtime_identity_fixture(tmp_path, monkeypatch)
    invalid_payloads = (
        b"\xff",
        b'{"schema_version":2,"schema_version":2}',
        b'{"schema_version":2,"unknown":true}',
    )
    accepted_constants = []
    for token in (b"NaN", b"Infinity", b"-Infinity"):
        payload = b'{"nested":{"extractable_candidate":' + token + b"}}"
        try:
            verifier._strict_json(payload, "runtime_identity")
        except verifier.GateFailure:
            pass
        else:
            accepted_constants.append(token.decode("ascii"))
    assert accepted_constants == []
    for payload in invalid_payloads:
        summary, failures = verifier._runtime_identity_report(
            payload, run_id="run-001", target="capture", runner="macos", attempt=1,
            started_at=fixture["timestamp"], policy=_policy(),
            uv_lock_content=fixture["lock_content"], pytest_events_plugin_content=fixture["events_content"],
        )
        assert failures == ["RUNTIME_IDENTITY_INVALID"]
        assert summary == _expected_runtime_invalid(_sha256(payload))
    summary, failures = verifier._runtime_identity_report(
        fixture["content"], raw_was_read=True, mode_valid=False,
        run_id="run-001", target="capture", runner="macos", attempt=1,
        started_at=fixture["timestamp"], policy=_policy(),
        uv_lock_content=fixture["lock_content"], pytest_events_plugin_content=fixture["events_content"],
    )
    assert failures == ["RUNTIME_IDENTITY_INVALID"]
    assert summary == _expected_runtime_invalid(_sha256(fixture["content"]))

    identity_path = tmp_path / "raced-plugin-identity.json"

    def raced_read(mutate):
        identity_path.unlink(missing_ok=True)
        identity_path.write_bytes(fixture["content"])
        identity_path.chmod(0o600)
        real_read = os.read
        mutated = False

        def read_then_mutate(descriptor, size):
            nonlocal mutated
            content = real_read(descriptor, size)
            if content and not mutated:
                mutated = True
                mutate(identity_path)
            return content

        with monkeypatch.context() as context:
            context.setattr(verifier.os, "read", read_then_mutate)
            return verifier._read_runtime_identity_artifact(
                identity_path, _policy()["limits"]["plugin_identity_bytes"]
            )

    chmod_raw, chmod_mode_valid = raced_read(lambda path: path.chmod(0o644))
    assert chmod_raw == fixture["content"]
    assert chmod_mode_valid is False

    def replace_same_bytes(path):
        replacement = path.with_name("replacement-plugin-identity.json")
        replacement.write_bytes(fixture["content"])
        replacement.chmod(0o600)
        os.replace(replacement, path)

    replacement_raw, replacement_mode_valid = raced_read(replace_same_bytes)
    assert replacement_raw == fixture["content"]
    assert replacement_mode_valid is False

    identity_path.unlink(missing_ok=True)
    identity_path.write_bytes(fixture["content"])
    identity_path.chmod(0o600)
    real_read = os.read
    disappeared = False

    def read_then_disappear_at_eof(descriptor, size):
        nonlocal disappeared
        content = real_read(descriptor, size)
        if not content and not disappeared:
            disappeared = True
            identity_path.unlink()
        return content

    with monkeypatch.context() as context:
        context.setattr(verifier.os, "read", read_then_disappear_at_eof)
        disappeared_raw, disappeared_mode_valid = (
            verifier._read_runtime_identity_artifact(
                identity_path, _policy()["limits"]["plugin_identity_bytes"]
            )
        )
    assert disappeared is True
    assert disappeared_raw == fixture["content"]
    assert disappeared_mode_valid is False

    for raced_raw in (chmod_raw, replacement_raw, disappeared_raw):
        raced_summary, raced_failures = verifier._runtime_identity_report(
            raced_raw,
            raw_was_read=True,
            mode_valid=False,
            run_id="run-001",
            target="capture",
            runner="macos",
            attempt=1,
            started_at=fixture["timestamp"],
            policy=_policy(),
            uv_lock_content=fixture["lock_content"],
            pytest_events_plugin_content=fixture["events_content"],
        )
        assert raced_failures == ["RUNTIME_IDENTITY_INVALID"]
        assert raced_summary == _expected_runtime_invalid(
            _sha256(fixture["content"])
        )

    empty_path = tmp_path / "empty-plugin-identity.json"
    empty_path.write_bytes(b"")
    empty_path.chmod(0o600)
    empty_raw, empty_mode_valid = verifier._read_runtime_identity_artifact(
        empty_path, _policy()["limits"]["plugin_identity_bytes"]
    )
    assert (empty_raw, empty_mode_valid) == (b"", True)
    empty_summary, empty_failures = verifier._runtime_identity_report(
        empty_raw,
        raw_was_read=True,
        mode_valid=True,
        run_id="run-001",
        target="capture",
        runner="macos",
        attempt=1,
        started_at=fixture["timestamp"],
        policy=_policy(),
        uv_lock_content=fixture["lock_content"],
        pytest_events_plugin_content=fixture["events_content"],
    )
    assert empty_failures == ["RUNTIME_IDENTITY_INVALID"]
    assert empty_summary == _expected_runtime_invalid(_sha256(b""))
    missing_raw, missing_mode_valid = verifier._read_runtime_identity_artifact(
        tmp_path / "missing-plugin-identity.json",
        _policy()["limits"]["plugin_identity_bytes"],
    )
    assert (missing_raw, missing_mode_valid) == (None, False)
    unreadable_path = tmp_path / "unreadable-plugin-identity.json"
    unreadable_path.write_bytes(fixture["content"])
    unreadable_path.chmod(0o600)
    real_open = os.open

    def deny_unreadable(path, *args, **kwargs):
        if Path(path) == unreadable_path:
            raise PermissionError(errno.EACCES, "controlled unreadable identity")
        return real_open(path, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(verifier.os, "open", deny_unreadable)
        assert verifier._read_runtime_identity_artifact(
            unreadable_path, _policy()["limits"]["plugin_identity_bytes"]
        ) == (None, False)
    oversize_path = tmp_path / "oversize-plugin-identity.json"
    oversize_path.write_bytes(
        b"x" * (_policy()["limits"]["plugin_identity_bytes"] + 1)
    )
    oversize_path.chmod(0o600)
    assert verifier._read_runtime_identity_artifact(
        oversize_path, _policy()["limits"]["plugin_identity_bytes"]
    ) == (None, False)

    monkeypatch.setattr(
        verifier,
        "PYTEST_EVENTS_PLUGIN_PATH",
        REPOSITORY_ROOT / "scripts/pytest_security_events.py",
    )
    mode_bundle = gate_contract._make_bundle(tmp_path / "full-mode-invalid")
    raw_sha = _sha256(mode_bundle["plugin_identity"].read_bytes())
    mode_bundle["plugin_identity"].chmod(0o644)
    gate_report, gate_failures = gate_contract._verify(mode_bundle)
    assert gate_failures == ["RUNTIME_IDENTITY_INVALID"]
    assert gate_report["artifact_hashes"]["plugin_identity_sha256"] == raw_sha
    assert gate_report["runtime_identity"] == _expected_runtime_invalid(raw_sha)

    missing_bundle = gate_contract._make_bundle(tmp_path / "full-missing-identity")
    missing_bundle["plugin_identity"].unlink()
    missing_report, missing_failures = gate_contract._verify(missing_bundle)
    assert missing_failures == ["RUNTIME_IDENTITY_INVALID"]
    assert missing_report["artifact_hashes"]["plugin_identity_sha256"] is None
    assert missing_report["runtime_identity"] == _expected_runtime_invalid(None)

    full_oversize_bundle = gate_contract._make_bundle(
        tmp_path / "full-oversize-identity"
    )
    full_oversize_bundle["plugin_identity"].write_bytes(
        b"x" * (_policy()["limits"]["plugin_identity_bytes"] + 1)
    )
    full_oversize_bundle["plugin_identity"].chmod(0o600)
    oversize_report, oversize_failures = gate_contract._verify(
        full_oversize_bundle
    )
    assert oversize_failures == ["RUNTIME_IDENTITY_INVALID"]
    assert oversize_report["artifact_hashes"]["plugin_identity_sha256"] is None
    assert oversize_report["runtime_identity"] == _expected_runtime_invalid(None)

    unreadable_bundle = gate_contract._make_bundle(
        tmp_path / "full-unreadable-identity"
    )
    unreadable_artifact = unreadable_bundle["plugin_identity"]
    real_open = os.open

    def deny_full_unreadable(path, *args, **kwargs):
        if Path(path) == unreadable_artifact:
            raise PermissionError(errno.EACCES, "controlled unreadable identity")
        return real_open(path, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(verifier.os, "open", deny_full_unreadable)
        unreadable_report, unreadable_failures = gate_contract._verify(
            unreadable_bundle
        )
    assert unreadable_failures == ["RUNTIME_IDENTITY_INVALID"]
    assert unreadable_report["artifact_hashes"]["plugin_identity_sha256"] is None
    assert unreadable_report["runtime_identity"] == _expected_runtime_invalid(None)


def test_s18_b3f_r2_failure_classes_are_not_collapsed(tmp_path, monkeypatch):
    source = inspect.getsource(verifier.verify_security_coverage) + inspect.getsource(
        verifier._runtime_identity_validation_core
    ) + inspect.getsource(verifier._command)
    for failure in (
        "RUNTIME_IDENTITY_INVALID",
        "PLUGIN_IDENTITY_INVALID",
        "EVIDENCE_TOOLCHAIN_BINDING_INVALID",
        "RUNNER_CONFIGURATION_INVALID",
    ):
        assert failure in source
    runtime_source = inspect.getsource(
        _future(verifier, "_runtime_identity_validation_core")
    )
    assert "record" in runtime_source.lower()
    assert "semantic_runtime_sha256" in runtime_source
    assert "pytest_cov.plugin" in runtime_source
    assert "scripts.pytest_security_events" in runtime_source
    fixture = _runtime_identity_fixture(tmp_path, monkeypatch)
    plugin = deepcopy(fixture["document"])
    plugin["plugins"]["pytest_cov.plugin"]["sha256"] = "b" * 64
    _rebind_semantic(plugin)
    assert _runtime_report(fixture, plugin)[1] == ["PLUGIN_IDENTITY_INVALID"]
    lock = deepcopy(fixture["document"])
    lock["distributions"]["pytest"]["lock"]["exact_package_object"]["version"] = 8.4
    _rebind_semantic(lock)
    assert _runtime_report(fixture, lock)[1] == ["RUNTIME_IDENTITY_INVALID"]
    union = deepcopy(fixture["document"])
    union["scope"]["timestamp"] = "2026-09-07T12:34:57.123456Z"
    union["plugins"]["pytest_cov.plugin"]["sha256"] = "b" * 64
    _rebind_semantic(union)
    assert _runtime_report(fixture, union)[1] == [
        "PLUGIN_IDENTITY_INVALID", "RUNTIME_IDENTITY_INVALID"
    ]
    uv_path = Path(fixture["document"]["uv"]["path"])
    uv_path.write_bytes(b"drifted uv executable\n")
    assert _runtime_report(fixture)[1] == ["EVIDENCE_TOOLCHAIN_BINDING_INVALID"]
    uv_path.write_bytes(b"synthetic uv executable\n")

    late_distribution_failure = deepcopy(fixture["document"])
    late_distribution_failure["distributions"]["pytest-cov"]["lock"][
        "version"
    ] = "7.0.1"
    _rebind_semantic(late_distribution_failure)
    cov_endpoint = Path(
        late_distribution_failure["plugins"]["pytest_cov.plugin"]["file"]
    )
    stable_read = verifier._runtime_stable_read
    cov_reads = 0

    def count_cov_reads(path, *args, **kwargs):
        nonlocal cov_reads
        if path == cov_endpoint:
            cov_reads += 1
        return stable_read(path, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(verifier, "_runtime_stable_read", count_cov_reads)
        _summary, late_failures, late_facts = _runtime_report(
            fixture, late_distribution_failure
        )
    assert late_failures == ["RUNTIME_IDENTITY_INVALID"]
    assert late_facts["distribution_versions"] == {
        "coverage": "7.10.6",
        "pluggy": "1.6.0",
        "pytest": "8.4.2",
    }
    assert cov_reads == 1

    entry_binding_failure = deepcopy(fixture["document"])
    entry_binding_failure["distributions"]["pytest-cov"]["installed"][
        "required_entries"
    ]["pytest_cov/plugin.py"]["sha256"] = "b" * 64
    _rebind_semantic(entry_binding_failure)
    cov_reads = 0
    with monkeypatch.context() as context:
        context.setattr(verifier, "_runtime_stable_read", count_cov_reads)
        _summary, entry_failures, entry_facts = _runtime_report(
            fixture, entry_binding_failure
        )
    assert entry_failures == ["RUNTIME_IDENTITY_INVALID"]
    assert entry_facts["distribution_versions"] == {
        "coverage": "7.10.6",
        "pluggy": "1.6.0",
        "pytest": "8.4.2",
    }
    assert cov_reads == 1

    cov_reads = 0
    with monkeypatch.context() as context:
        context.setattr(verifier, "_runtime_stable_read", count_cov_reads)
        _summary, valid_failures, valid_facts = _runtime_report(fixture)
    assert valid_failures == []
    assert valid_facts["distribution_versions"] == {
        "coverage": "7.10.6",
        "pluggy": "1.6.0",
        "pytest": "8.4.2",
        "pytest-cov": "7.0.0",
    }
    assert cov_reads == 1

    scope_failure = deepcopy(fixture["document"])
    scope_failure["scope"]["timestamp"] = "2026-09-07T12:34:57.123456Z"
    _rebind_semantic(scope_failure)
    _summary, scope_failures, scope_facts = _runtime_report(fixture, scope_failure)
    assert scope_failures == ["RUNTIME_IDENTITY_INVALID"]
    assert scope_facts["uv"] == fixture["document"]["uv"]
    assert scope_facts["semantic_runtime_sha256"] == scope_failure[
        "semantic_runtime_sha256"
    ]
    assert scope_facts["distribution_versions"] == valid_facts[
        "distribution_versions"
    ]

    early_distribution_failure = deepcopy(fixture["document"])
    early_distribution_failure["distributions"]["coverage"]["lock"][
        "version"
    ] = "7.10.7"
    _rebind_semantic(early_distribution_failure)
    _summary, early_failures, early_facts = _runtime_report(
        fixture, early_distribution_failure
    )
    assert early_failures == ["RUNTIME_IDENTITY_INVALID"]
    assert early_facts["distribution_versions"] == {
        "pluggy": "1.6.0",
        "pytest": "8.4.2",
        "pytest-cov": "7.0.0",
    }

    monkeypatch.setattr(
        verifier,
        "PYTEST_EVENTS_PLUGIN_PATH",
        REPOSITORY_ROOT / "scripts/pytest_security_events.py",
    )
    full_cases = []
    runtime_bundle = gate_contract._make_bundle(tmp_path / "full-runtime")
    runtime_identity = json.loads(runtime_bundle["plugin_identity"].read_text(encoding="utf-8"))
    runtime_identity["distributions"]["coverage"]["installed"]["record_rows"][0]["size"] += 1
    _rebind_semantic(runtime_identity)
    runtime_bundle["plugin_identity"].write_text(json.dumps(runtime_identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    gate_contract._rebind_plugin_identity(runtime_bundle)
    full_cases.append((runtime_bundle, ["RUNTIME_IDENTITY_INVALID"]))

    plugin_bundle = gate_contract._make_bundle(tmp_path / "full-plugin")
    plugin_identity = json.loads(plugin_bundle["plugin_identity"].read_text(encoding="utf-8"))
    plugin_identity["plugins"]["pytest_cov.plugin"]["sha256"] = "b" * 64
    _rebind_semantic(plugin_identity)
    plugin_bundle["plugin_identity"].write_text(json.dumps(plugin_identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    gate_contract._rebind_plugin_identity(plugin_bundle)
    full_cases.append((plugin_bundle, ["PLUGIN_IDENTITY_INVALID"]))

    toolchain_bundle = gate_contract._make_bundle(tmp_path / "full-toolchain")
    toolchain_environment = json.loads(toolchain_bundle["environment"].read_text(encoding="utf-8"))
    toolchain_environment["repository"]["uv_executable_sha256_after"] = "b" * 64
    toolchain_bundle["environment"].write_text(json.dumps(toolchain_environment, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rebind_artifact(toolchain_bundle, "environment")
    full_cases.append((toolchain_bundle, ["EVIDENCE_TOOLCHAIN_BINDING_INVALID"]))

    config_bundle = gate_contract._make_bundle(tmp_path / "full-config")
    config_command = json.loads(config_bundle["command"].read_text(encoding="utf-8"))
    config_command["argv"][17] = "-v"
    config_bundle["command"].write_text(json.dumps(config_command, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rebind_artifact(config_bundle, "command")
    full_cases.append((config_bundle, ["RUNNER_CONFIGURATION_INVALID"]))

    union_bundle = gate_contract._make_bundle(tmp_path / "full-union")
    union_identity = json.loads(union_bundle["plugin_identity"].read_text(encoding="utf-8"))
    union_identity["distributions"]["coverage"]["installed"]["record_rows"][0]["size"] += 1
    union_identity["plugins"]["pytest_cov.plugin"]["sha256"] = "b" * 64
    _rebind_semantic(union_identity)
    union_bundle["plugin_identity"].write_text(json.dumps(union_identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    gate_contract._rebind_plugin_identity(union_bundle)
    full_cases.append((union_bundle, ["PLUGIN_IDENTITY_INVALID", "RUNTIME_IDENTITY_INVALID"]))

    plugin_toolchain_bundle = gate_contract._make_bundle(
        tmp_path / "full-plugin-toolchain"
    )
    plugin_toolchain_identity = json.loads(
        plugin_toolchain_bundle["plugin_identity"].read_text(encoding="utf-8")
    )
    plugin_toolchain_identity["plugins"]["pytest_cov.plugin"]["sha256"] = "b" * 64
    _rebind_semantic(plugin_toolchain_identity)
    plugin_toolchain_bundle["plugin_identity"].write_text(
        json.dumps(plugin_toolchain_identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    gate_contract._rebind_plugin_identity(plugin_toolchain_bundle)
    plugin_toolchain_environment = json.loads(
        plugin_toolchain_bundle["environment"].read_text(encoding="utf-8")
    )
    plugin_toolchain_environment["repository"][
        "uv_executable_sha256_before"
    ] = "b" * 64
    plugin_toolchain_environment["repository"][
        "uv_executable_sha256_after"
    ] = "b" * 64
    plugin_toolchain_bundle["environment"].write_text(
        json.dumps(plugin_toolchain_environment, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rebind_artifact(plugin_toolchain_bundle, "environment")
    full_cases.append(
        (
            plugin_toolchain_bundle,
            ["EVIDENCE_TOOLCHAIN_BINDING_INVALID", "PLUGIN_IDENTITY_INVALID"],
        )
    )

    scope_live_bundle = gate_contract._make_bundle(tmp_path / "full-scope-live")
    scope_live_identity = json.loads(
        scope_live_bundle["plugin_identity"].read_text(encoding="utf-8")
    )
    scope_live_identity["scope"]["timestamp"] = "2026-09-06T00:00:02.000000Z"
    scope_live_identity["uv"]["sha256"] = "b" * 64
    _rebind_semantic(scope_live_identity)
    scope_live_bundle["plugin_identity"].write_text(
        json.dumps(scope_live_identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    gate_contract._rebind_plugin_identity(scope_live_bundle)
    full_cases.append(
        (
            scope_live_bundle,
            ["EVIDENCE_TOOLCHAIN_BINDING_INVALID", "RUNTIME_IDENTITY_INVALID"],
        )
    )

    malformed_command_bundle = gate_contract._make_bundle(
        tmp_path / "full-malformed-command-uv"
    )
    malformed_command = json.loads(
        malformed_command_bundle["command"].read_text(encoding="utf-8")
    )
    malformed_command["argv"][11] = "--runtime-uv-path=relative/uv"
    malformed_command_bundle["command"].write_text(
        json.dumps(malformed_command, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rebind_artifact(malformed_command_bundle, "command")
    full_cases.append(
        (malformed_command_bundle, ["RUNNER_CONFIGURATION_INVALID"])
    )

    alternate_path_bundle = gate_contract._make_bundle(
        tmp_path / "full-alternate-uv-path"
    )
    alternate_identity = json.loads(
        alternate_path_bundle["plugin_identity"].read_text(encoding="utf-8")
    )
    original_uv_path = Path(alternate_identity["uv"]["path"])
    alternate_uv_path = tmp_path / "alternate-uv-endpoint"
    alternate_uv_path.write_bytes(original_uv_path.read_bytes())
    alternate_uv_path.chmod(0o700)
    alternate_identity["uv"]["path"] = os.fspath(alternate_uv_path)
    _rebind_semantic(alternate_identity)
    alternate_path_bundle["plugin_identity"].write_text(
        json.dumps(alternate_identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    gate_contract._rebind_plugin_identity(alternate_path_bundle)
    full_cases.append(
        (alternate_path_bundle, ["EVIDENCE_TOOLCHAIN_BINDING_INVALID"])
    )

    invalid_uv_bundle = gate_contract._make_bundle(tmp_path / "full-invalid-uv")
    invalid_uv_identity = json.loads(
        invalid_uv_bundle["plugin_identity"].read_text(encoding="utf-8")
    )
    invalid_uv_identity["uv"]["path"] = "relative/uv"
    _rebind_semantic(invalid_uv_identity)
    invalid_uv_bundle["plugin_identity"].write_text(
        json.dumps(invalid_uv_identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    gate_contract._rebind_plugin_identity(invalid_uv_bundle)
    full_cases.append((invalid_uv_bundle, ["RUNTIME_IDENTITY_INVALID"]))

    live_mismatch_bundle = gate_contract._make_bundle(
        tmp_path / "full-live-uv-mismatch"
    )
    live_mismatch_identity = json.loads(
        live_mismatch_bundle["plugin_identity"].read_text(encoding="utf-8")
    )
    live_mismatch_identity["uv"]["sha256"] = "b" * 64
    _rebind_semantic(live_mismatch_identity)
    live_mismatch_bundle["plugin_identity"].write_text(
        json.dumps(live_mismatch_identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    gate_contract._rebind_plugin_identity(live_mismatch_bundle)
    full_cases.append(
        (live_mismatch_bundle, ["EVIDENCE_TOOLCHAIN_BINDING_INVALID"])
    )

    config_toolchain_bundle = gate_contract._make_bundle(
        tmp_path / "full-config-toolchain"
    )
    config_toolchain_command = json.loads(
        config_toolchain_bundle["command"].read_text(encoding="utf-8")
    )
    config_toolchain_command["argv"][17] = "-v"
    config_toolchain_command["argv"][12] = "--runtime-uv-version=0.12.8"
    for index, prefix in enumerate(
        (
            "--plugin-identity=",
            "--runtime-uv-path=",
            "--runtime-uv-version=",
            "--runtime-uv-sha256=",
            "--runtime-timestamp=",
        ),
        start=10,
    ):
        assert config_toolchain_command["argv"][index].startswith(prefix)
    assert config_toolchain_command["argv"][15] == "--"
    config_toolchain_bundle["command"].write_text(
        json.dumps(config_toolchain_command, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rebind_artifact(config_toolchain_bundle, "command")
    full_cases.append(
        (
            config_toolchain_bundle,
            ["EVIDENCE_TOOLCHAIN_BINDING_INVALID", "RUNNER_CONFIGURATION_INVALID"],
        )
    )

    assert [gate_contract._verify(bundle)[1] for bundle, _expected in full_cases] == [
        expected for _bundle, expected in full_cases
    ]


def test_s18_b3f_r2_environment_uses_nullable_identity_observation_without_version_subprocess(
    tmp_path,
):
    source = _runner_source()
    assert '"schema_version": 5' in source
    assert '"runtime_identity"' in source
    assert '"artifact_sha256"' in source
    assert '"semantic_runtime_sha256"' in source
    assert "def version(" not in source
    assert "coverage.__version__" not in source
    assert "pytest.__version__" not in source
    assert "uv_executable_sha256_before" in source
    assert "uv_executable_sha256_after" in source

    harness = RunnerHarness.create(tmp_path, source_root=REPOSITORY_ROOT)
    valid = harness.run(
        _runner_supplier(),
        scenario=RunnerScenario(verifier_mode="stub-success"),
        run_id="r2-environment-valid",
    )
    assert valid.returncode == 0, (valid.stdout, valid.stderr)
    assert [call.kind for call in valid.calls()].count("version") == 1
    for target in ("capture", "retention"):
        artifacts = valid.artifacts(target)
        environment = json.loads(artifacts["environment"].read_text(encoding="utf-8"))
        command = json.loads(artifacts["command"].read_text(encoding="utf-8"))
        identity = json.loads(artifacts["plugin_identity"].read_text(encoding="utf-8"))
        assert environment["schema_version"] == 5
        assert environment["tools"] == {
            "coverage": "7.10.6",
            "pytest": "8.4.2",
            "uv": "0.12.9",
        }
        assert environment["runtime_identity"] == {
            "artifact_sha256": _sha256(artifacts["plugin_identity"].read_bytes()),
            "semantic_runtime_sha256": identity["semantic_runtime_sha256"],
        }
        assert (
            environment["repository"]["uv_executable_sha256_before"]
            == environment["repository"]["uv_executable_sha256_after"]
            == identity["uv"]["sha256"]
        )
        assert command["argv"][:9] == [
            identity["uv"]["path"],
            "run",
            "--offline",
            "--frozen",
            "--no-sync",
            "python",
            "-I",
            "-S",
            "-B",
        ]
        assert valid.gate_kind(target) == "stub"
    assert [call.kind for call in valid.calls()].count("verifier-stub") == 2

    malformed_content = b'{"schema_version":2,"broken":'
    malformed = harness.run(
        _runner_supplier(plugin_identity=malformed_content),
        scenario=RunnerScenario(verifier_mode="stub-success"),
        run_id="r2-environment-malformed",
    )
    assert malformed.returncode == 0, (malformed.stdout, malformed.stderr)
    assert [call.kind for call in malformed.calls()].count("version") == 1
    for target in ("capture", "retention"):
        artifacts = malformed.artifacts(target)
        environment = json.loads(artifacts["environment"].read_text(encoding="utf-8"))
        manifest = json.loads(artifacts["run_manifest"].read_text(encoding="utf-8"))
        assert environment["tools"] == {"coverage": None, "pytest": None, "uv": None}
        assert environment["runtime_identity"] == {
            "artifact_sha256": _sha256(malformed_content),
            "semantic_runtime_sha256": None,
        }
        assert manifest["semantic_runtime_sha256"] is None
        assert malformed.gate_kind(target) == "stub"


def test_s18_b3f_r2_manifest_cross_binds_identity_without_hash_cycle(tmp_path):
    artifact_oracles.assert_manifest_cross_bindings(tmp_path / "full-verifier")
    hashes = {
        key: "a" * 64
        for key in (
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
        )
    }
    baseline = {
        "schema_version": 5,
        "run_id": "s18-r2-manifest",
        "target": "capture",
        "runner": "macos",
        "attempt": 1,
        "semantic_runtime_sha256": "b" * 64,
        "artifact_hashes": hashes,
    }
    assert verifier._run_manifest(baseline) == baseline
    unknown = deepcopy(baseline)
    unknown["runtime_identity_sha256"] = "b" * 64
    with pytest.raises(verifier.GateFailure):
        verifier._run_manifest(unknown)
    missing = deepcopy(baseline)
    del missing["semantic_runtime_sha256"]
    with pytest.raises(verifier.GateFailure):
        verifier._run_manifest(missing)
    nested_unknown = deepcopy(baseline)
    nested_unknown["artifact_hashes"]["unexpected_sha256"] = "c" * 64
    with pytest.raises(verifier.GateFailure):
        verifier._run_manifest(nested_unknown)
    nested_missing = deepcopy(baseline)
    del nested_missing["artifact_hashes"]["source_sha256"]
    with pytest.raises(verifier.GateFailure):
        verifier._run_manifest(nested_missing)
    nullable = deepcopy(baseline)
    nullable["semantic_runtime_sha256"] = None
    assert verifier._run_manifest(nullable) == nullable


def test_s18_b3f_r2_gate_runtime_summary_is_exact_bounded_and_path_free(tmp_path, monkeypatch):
    report = _future(verifier, "_runtime_identity_report")
    fixture = _runtime_identity_fixture(tmp_path, monkeypatch)
    summary, failures = report(
        fixture["content"],
        run_id="run-001",
        target="capture",
        runner="macos",
        attempt=1,
        started_at=fixture["timestamp"],
        uv_lock_content=fixture["lock_content"],
        pytest_events_plugin_content=fixture["events_content"],
        policy=_policy(),
    )
    assert failures == []
    assert frozenset(summary) == RUNTIME_SUMMARY_KEYS
    assert summary["status"] == "valid"
    assert set(summary["runtime"]) == {
        "implementation", "version", "system", "machine", "executable_sha256",
        "pyvenv_cfg_sha256", "isolated", "no_site", "dont_write_bytecode",
    }
    assert set(summary["uv"]) == {"version", "sha256"}
    assert all(set(item) == {"sha256", "distribution", "entry"} for item in summary["plugins"].values())
    serialized = json.dumps(summary, sort_keys=True)
    for forbidden in ("site_packages", "dist_info", "metadata_bytes", "record_bytes", "canonical_package_bytes", '"file"', str(tmp_path)):
        assert forbidden not in serialized
    assert len(serialized.encode()) < 16 * 1024


def test_s18_b3f_r2_identity_limit_accepts_representative_and_rejects_plus_one(
    tmp_path,
    monkeypatch,
):
    policy = _policy()
    assert policy["limits"]["plugin_identity_bytes"] == 4 * 1024 * 1024
    limit = policy["limits"]["plugin_identity_bytes"]
    representative = b'{"schema_version":2}\n'
    assert len(representative) < limit
    path = tmp_path / "plugin-identity.json"
    path.write_bytes(representative)
    assert verifier._read_runtime_identity_artifact(path, limit)[0] == representative
    boundary = b"{" + b" " * (limit - 2) + b"}"
    path.write_bytes(boundary)
    assert len(verifier._read_runtime_identity_artifact(path, limit)[0]) == limit
    path.write_bytes(boundary + b"\n")
    assert verifier._read_runtime_identity_artifact(path, limit)[0] is None

    fixture = _runtime_identity_fixture(tmp_path / "valid-boundary", monkeypatch)
    valid_boundary = deepcopy(fixture["document"])
    valid_boundary["runtime"]["cache_tag"] = "x"
    _rebind_semantic(valid_boundary)
    preliminary = (
        json.dumps(valid_boundary, indent=2, sort_keys=True) + "\n"
    ).encode()
    assert len(preliminary) < limit
    valid_boundary["runtime"]["cache_tag"] += "x" * (limit - len(preliminary))
    _rebind_semantic(valid_boundary)
    valid_boundary_bytes = (
        json.dumps(valid_boundary, indent=2, sort_keys=True) + "\n"
    ).encode()
    assert len(valid_boundary_bytes) == limit
    path.write_bytes(valid_boundary_bytes)
    path.chmod(0o600)
    bounded_raw, bounded_mode_valid = verifier._read_runtime_identity_artifact(
        path, limit
    )
    assert (bounded_raw, bounded_mode_valid) == (valid_boundary_bytes, True)
    assert _runtime_report(fixture, valid_boundary)[1] == []
    path.write_bytes(valid_boundary_bytes + b"\n")
    assert verifier._read_runtime_identity_artifact(path, limit) == (None, False)

    def nested_identity(case: str, size: int, root: Path):
        nested_fixture = _runtime_identity_fixture(root, monkeypatch)
        document = deepcopy(nested_fixture["document"])
        runtime = document["runtime"]
        distributions = document["distributions"]
        if case == "metadata":
            installed = distributions["coverage"]["installed"]
            prefix = b"Metadata-Version: 2.4\nName: coverage\nVersion: 7.10.6\n"
            suffix = b"\n"
            remaining = size - len(prefix) - len(suffix)
            full_lines, final_length = divmod(remaining, 72)
            if 0 < final_length < 8:
                full_lines -= 1
                final_length += 72
            padding_lines = [b"X-Pad: " + b"x" * 64 + b"\n"] * full_lines
            if final_length:
                padding_lines.append(
                    b"X-Pad: " + b"x" * (final_length - 8) + b"\n"
                )
            payload = prefix + b"".join(padding_lines) + suffix
            endpoint = Path(runtime["site_packages"]) / installed["dist_info"] / "METADATA"
            endpoint.write_bytes(payload)
            installed["metadata_bytes"] = _b64(payload)
            installed["metadata_size"] = len(payload)
            installed["metadata_sha256"] = _sha256(payload)
        elif case == "record":
            installed = distributions["coverage"]["installed"]
            original = base64.b64decode(installed["record_bytes"], validate=True)
            lines = original.splitlines(keepends=True)
            digest = _record_hash(b"x")
            remaining = size - len(original)
            added_rows = []
            normalized_rows = []
            index = 0
            while remaining:
                prefix = f"padding/{index:06d}-"
                suffix = f",sha256={digest},1\n"
                minimum = len(prefix) + len(suffix)
                desired = min(200, remaining)
                if 0 < remaining - desired < minimum:
                    desired = remaining - minimum
                assert desired >= minimum
                relative = prefix + "x" * (desired - minimum)
                added_rows.append(f"{relative}{suffix}".encode())
                normalized_rows.append(
                    {
                        "kind": "entry",
                        "path": relative,
                        "sha256": _sha256(b"x"),
                        "size": 1,
                    }
                )
                remaining -= desired
                index += 1
            payload = b"".join((*lines[:-1], *added_rows, lines[-1]))
            endpoint = Path(runtime["site_packages"]) / installed["dist_info"] / "RECORD"
            endpoint.write_bytes(payload)
            installed["record_bytes"] = _b64(payload)
            installed["record_size"] = len(payload)
            installed["record_sha256"] = _sha256(payload)
            installed["record_rows"][-1:-1] = normalized_rows
        elif case == "entry":
            installed = distributions["coverage"]["installed"]
            relative = "coverage/__init__.py"
            payload = b"x" * size
            endpoint = Path(runtime["site_packages"]) / relative
            endpoint.write_bytes(payload)
            entry = installed["required_entries"][relative]
            entry.update(
                {"bytes": _b64(payload), "size": len(payload), "sha256": _sha256(payload)}
            )
            original = base64.b64decode(installed["record_bytes"], validate=True)
            lines = original.splitlines(keepends=True)
            lines[0] = (
                f"{relative},sha256={_record_hash(payload)},{len(payload)}\n".encode()
            )
            record = b"".join(lines)
            (Path(runtime["site_packages"]) / installed["dist_info"] / "RECORD").write_bytes(record)
            installed["record_bytes"] = _b64(record)
            installed["record_size"] = len(record)
            installed["record_sha256"] = _sha256(record)
            installed["record_rows"][0]["sha256"] = _sha256(payload)
            installed["record_rows"][0]["size"] = len(payload)
        elif case == "pyvenv":
            original = base64.b64decode(runtime["pyvenv_cfg_bytes"], validate=True)
            prefix = original + b"padding = "
            payload = prefix + b"x" * (size - len(prefix) - 1) + b"\n"
            Path(runtime["pyvenv_cfg_path"]).write_bytes(payload)
            runtime["pyvenv_cfg_bytes"] = _b64(payload)
            runtime["pyvenv_cfg_size"] = len(payload)
            runtime["pyvenv_cfg_sha256"] = _sha256(payload)
        else:
            raise AssertionError(case)
        assert len(payload) == size
        _rebind_semantic(document)
        return nested_fixture, document

    nested_limits = {
        "metadata": _policy()["limits"]["runtime_metadata_bytes"],
        "record": _policy()["limits"]["runtime_record_bytes"],
        "entry": _policy()["limits"]["runtime_required_entry_bytes"],
        "pyvenv": _policy()["limits"]["runtime_pyvenv_cfg_bytes"],
    }
    for case, nested_limit in nested_limits.items():
        exact_fixture, exact_document = nested_identity(
            case, nested_limit, tmp_path / f"nested-{case}-exact"
        )
        exact_failures = _runtime_report(exact_fixture, exact_document)[1]
        assert exact_failures == [], (case, exact_failures)
        plus_fixture, plus_document = nested_identity(
            case, nested_limit + 1, tmp_path / f"nested-{case}-plus-one"
        )
        assert _runtime_report(plus_fixture, plus_document)[1] == [
            "RUNTIME_IDENTITY_INVALID"
        ]


def test_s18_b3f_r2_verifier_recomputes_identity_without_producer_validator(
    tmp_path, monkeypatch,
):
    fixture = _runtime_identity_fixture(tmp_path, monkeypatch)

    def producer_bomb(*args, **kwargs):
        raise AssertionError("verifier called the producer validator")

    monkeypatch.setattr(bootstrap, "_build_runtime_identity_v2", producer_bomb)
    report = _future(verifier, "_runtime_identity_report")
    summary, failures = report(
        fixture["content"],
        run_id="run-001",
        target="capture",
        runner="macos",
        attempt=1,
        started_at=fixture["timestamp"],
        uv_lock_content=fixture["lock_content"],
        pytest_events_plugin_content=fixture["events_content"],
        policy=_policy(),
    )
    assert failures == []
    assert summary["status"] == "valid"
    verifier_tree = ast.parse(inspect.getsource(verifier))
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and "security_pytest_bootstrap" in ast.unparse(node)
        for node in ast.walk(verifier_tree)
    )
    assert not any(
        isinstance(node, ast.Call) and ast.unparse(node.func).endswith("_build_runtime_identity_v2")
        for node in ast.walk(verifier_tree)
    )


def test_s18_b3f_r2_artifact_profiles_preserve_early_no_events_and_malformed_identity(
    tmp_path,
):
    source = _runner_source()
    assert '"schema_version": 2' in source
    assert '"stage": "raw-completeness"' in source
    assert '"plugin-identity.json"' in source
    assert '"pytest-events.json"' in source
    assert '"semantic_runtime_sha256"' in source
    assert "artifact_sha, extracted" in source
    assert "semantic = extracted" in source
    assert "REQUIRED_RAW_ARTIFACT_MISSING" in source
    verifier_source = inspect.getsource(verifier.verify_security_coverage)
    assert "runtime_identity_read_failure" in verifier_source
    assert "pytest_events_read_failure" in verifier_source

    staging = tmp_path / "real-verifier-staging"
    staging.mkdir()

    def profile_supplier(
        harness,
        *,
        events_present=True,
        identity_override=_GENERATED_RUNNER_IDENTITY,
    ):
        def supply(target: str, run_id: str, attempt: int) -> BootstrapArtifacts:
            runner = "macos" if sys.platform == "darwin" else "linux"
            bundle = gate_contract._make_bundle(
                staging / f"{run_id}-{target}",
                target=target,
                runner=runner,
                run_id=run_id,
                attempt=attempt,
            )
            if identity_override is _GENERATED_RUNNER_IDENTITY:
                identity_document = gate_contract._plugin_identity_document(
                    run_id=run_id,
                    target=target,
                    runner=runner,
                    attempt=attempt,
                    repository_root=harness.repository_root,
                )
                identity_document["scope"]["timestamp"] = "{{RUNTIME_TIMESTAMP}}"
                identity_document["uv"] = {
                    "path": "{{UV_PATH}}",
                    "version": "{{UV_VERSION}}",
                    "sha256": "{{UV_SHA256}}",
                }
                _rebind_semantic(identity_document)
                identity = (
                    json.dumps(identity_document, indent=2, sort_keys=True) + "\n"
                ).encode()
                rebind = True
            else:
                identity = identity_override
                rebind = False
            return BootstrapArtifacts(
                plugin_identity=identity,
                pytest_events=(
                    bundle["pytest_events"].read_bytes()
                    if events_present
                    else None
                ),
                coverage_data=b"raw coverage data\n",
                coverage_json=bundle["coverage"].read_bytes(),
                junit_xml=bundle["junit"].read_bytes(),
                rebind_identity_semantic=rebind,
            )

        return supply

    baseline_harness = RunnerHarness.create(
        tmp_path / "real-verifier-baseline", source_root=REPOSITORY_ROOT
    )
    baseline = baseline_harness.run(
        profile_supplier(baseline_harness),
        scenario=RunnerScenario(verifier_mode="real"),
        run_id="r2-real-verifier-baseline",
    )
    assert baseline.returncode == 0, (baseline.stdout, baseline.stderr)
    for target in ("capture", "retention"):
        assert baseline.gate_kind(target) == "real"
        gate = json.loads(
            baseline.artifacts(target)["gate"].read_text(encoding="utf-8")
        )
        assert gate["passed"] is True
        assert gate["failures"] == []

    no_events_harness = RunnerHarness.create(
        tmp_path / "real-verifier-no-events", source_root=REPOSITORY_ROOT
    )
    real_no_events = no_events_harness.run(
        profile_supplier(no_events_harness, events_present=False),
        scenario=RunnerScenario(verifier_mode="real"),
        run_id="r2-real-verifier-no-events",
    )
    assert real_no_events.returncode == 1
    for target in ("capture", "retention"):
        assert real_no_events.gate_kind(target) == "real"
        gate = json.loads(
            real_no_events.artifacts(target)["gate"].read_text(encoding="utf-8")
        )
        assert gate["failures"] == ["PYTEST_EVENTS_INVALID"]

    malformed_harness = RunnerHarness.create(
        tmp_path / "real-verifier-malformed", source_root=REPOSITORY_ROOT
    )
    real_malformed = malformed_harness.run(
        profile_supplier(
            malformed_harness,
            identity_override=b'{"schema_version":2,"broken":',
        ),
        scenario=RunnerScenario(verifier_mode="real"),
        run_id="r2-real-verifier-malformed",
    )
    assert real_malformed.returncode == 1
    for target in ("capture", "retention"):
        assert real_malformed.gate_kind(target) == "real"
        gate = json.loads(
            real_malformed.artifacts(target)["gate"].read_text(encoding="utf-8")
        )
        assert gate["failures"] == ["RUNTIME_IDENTITY_INVALID"]
    for result in (baseline, real_no_events, real_malformed):
        kinds = [call.kind for call in result.calls()]
        assert kinds.count("bootstrap-stub") == 2
        assert kinds.count("verifier-real") == 2
        assert not any(kind in {"blocked-program", "invalid-prefix"} for kind in kinds)

    no_events = RunnerHarness.create(
        tmp_path / "no-events", source_root=REPOSITORY_ROOT
    ).run(
        _runner_supplier(pytest_events=None),
        scenario=RunnerScenario(verifier_mode="stub-success"),
        run_id="r2-no-events",
    )
    assert no_events.returncode == 0, (no_events.stdout, no_events.stderr)
    for target in ("capture", "retention"):
        artifacts = no_events.artifacts(target)
        assert not artifacts["pytest_events"].exists()
        assert artifacts["run_manifest"].exists()
        assert no_events.gate_kind(target) == "stub"
        gate = json.loads(artifacts["gate"].read_text(encoding="utf-8"))
        assert gate == {
            "harness_stub": True,
            "not_verification_evidence": True,
            "target": target,
        }
        manifest = json.loads(artifacts["run_manifest"].read_text(encoding="utf-8"))
        assert manifest["artifact_hashes"]["pytest_events_sha256"] == _sha256(b"")

    blocked_target = tmp_path / "must-not-run"
    blocked_marker = tmp_path / "must-not-run.marker"
    blocked_target.write_text(
        "#!/bin/sh\nprintf executed > \"$1\"\nexit 0\n",
        encoding="utf-8",
    )
    blocked_target.chmod(0o700)
    blocked_environment = os.environ.copy()
    blocked_environment.update(
        {
            "R2_HARNESS_CALL_LOG": os.fspath(no_events.call_log_path),
            "R2_HARNESS_CONFIG": os.fspath(
                no_events.call_log_path.with_name("fake-uv-config.json")
            ),
        }
    )
    blocked = subprocess.run(
        [
            no_events.calls()[0].argv[0],
            *EXACT_UV_RUN_PREFIX,
            os.fspath(blocked_target),
            os.fspath(blocked_marker),
        ],
        cwd=no_events.repository_root,
        env=blocked_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode == 97
    assert blocked.stdout == ""
    assert blocked.stderr == ""
    assert not blocked_marker.exists()
    assert no_events.calls()[-1].kind == "blocked-program"
    assert not any(call.kind == "poison" for call in no_events.calls())

    extractable_candidate = (
        b'{"schema_version":2,"semantic_runtime_sha256":"'
        + b"a" * 64
        + b'","uv":{"version":"0.12.9"},"distributions":'
        b'{"coverage":{"installed":{"version":"7.10.6","probe":TOKEN}},'
        b'"pytest":{"installed":{"version":"8.4.2"}}}}'
    )
    positive_content = extractable_candidate.replace(b"TOKEN", b"0")
    positive = RunnerHarness.create(
        tmp_path / "extractable-positive", source_root=REPOSITORY_ROOT
    ).run(
        _runner_supplier(plugin_identity=positive_content),
        scenario=RunnerScenario(verifier_mode="stub-success"),
        run_id="r2-extractable-positive",
    )
    assert positive.returncode == 0, (positive.stdout, positive.stderr)
    for target in ("capture", "retention"):
        artifacts = positive.artifacts(target)
        environment = json.loads(
            artifacts["environment"].read_text(encoding="utf-8")
        )
        manifest = json.loads(
            artifacts["run_manifest"].read_text(encoding="utf-8")
        )
        assert environment["runtime_identity"] == {
            "artifact_sha256": _sha256(positive_content),
            "semantic_runtime_sha256": "a" * 64,
        }
        assert environment["tools"] == {
            "coverage": "7.10.6",
            "pytest": "8.4.2",
            "uv": "0.12.9",
        }
        assert manifest["semantic_runtime_sha256"] == "a" * 64

    deep_token = b"[" * 2000 + b"0" + b"]" * 2000
    deep_content = extractable_candidate.replace(b"TOKEN", deep_token)
    assert len(deep_content) <= _policy()["limits"]["plugin_identity_bytes"]
    deep_stub = RunnerHarness.create(
        tmp_path / "deep-identity-stub", source_root=REPOSITORY_ROOT
    ).run(
        _runner_supplier(plugin_identity=deep_content),
        scenario=RunnerScenario(verifier_mode="stub-success"),
        run_id="r2-deep-identity-stub",
    )
    assert deep_stub.returncode == 0, (deep_stub.stdout, deep_stub.stderr)
    assert "Traceback" not in deep_stub.stdout
    assert "Traceback" not in deep_stub.stderr
    for target in ("capture", "retention"):
        artifacts = deep_stub.artifacts(target)
        environment = json.loads(
            artifacts["environment"].read_text(encoding="utf-8")
        )
        manifest = json.loads(
            artifacts["run_manifest"].read_text(encoding="utf-8")
        )
        assert environment["runtime_identity"] == {
            "artifact_sha256": _sha256(deep_content),
            "semantic_runtime_sha256": None,
        }
        assert environment["tools"] == {
            "coverage": None,
            "pytest": None,
            "uv": None,
        }
        assert manifest["semantic_runtime_sha256"] is None
        assert deep_stub.gate_kind(target) == "stub"

    deep_real_harness = RunnerHarness.create(
        tmp_path / "deep-identity-real", source_root=REPOSITORY_ROOT
    )
    deep_real = deep_real_harness.run(
        profile_supplier(deep_real_harness, identity_override=deep_content),
        scenario=RunnerScenario(verifier_mode="real"),
        run_id="r2-real-verifier-deep-identity",
    )
    assert deep_real.returncode == 1
    assert "Traceback" not in deep_real.stdout
    assert "Traceback" not in deep_real.stderr
    for target in ("capture", "retention"):
        assert deep_real.gate_kind(target) == "real"
        gate = json.loads(
            deep_real.artifacts(target)["gate"].read_text(encoding="utf-8")
        )
        assert gate["failures"] == ["RUNTIME_IDENTITY_INVALID"]
    deep_real_kinds = [call.kind for call in deep_real.calls()]
    assert deep_real_kinds.count("bootstrap-stub") == 2
    assert deep_real_kinds.count("verifier-real") == 2
    assert not any(
        kind in {"blocked-program", "invalid-prefix"} for kind in deep_real_kinds
    )

    malformed_candidates = [
        (label, extractable_candidate.replace(b"TOKEN", token))
        for label, token in (
            ("nan", b"NaN"),
            ("infinity", b"Infinity"),
            ("negative-infinity", b"-Infinity"),
        )
    ]
    malformed_candidates.append(
        (
            "nested-duplicate",
            extractable_candidate.replace(b'"probe":TOKEN', b'"probe":1,"probe":1'),
        )
    )
    for label, malformed_content in malformed_candidates:
        malformed = RunnerHarness.create(
            tmp_path / f"malformed-{label}", source_root=REPOSITORY_ROOT
        ).run(
            _runner_supplier(plugin_identity=malformed_content),
            scenario=RunnerScenario(verifier_mode="stub-success"),
            run_id=f"r2-malformed-identity-{label}",
        )
        assert malformed.returncode == 0, (malformed.stdout, malformed.stderr)
        for target in ("capture", "retention"):
            artifacts = malformed.artifacts(target)
            environment = json.loads(
                artifacts["environment"].read_text(encoding="utf-8")
            )
            manifest = json.loads(
                artifacts["run_manifest"].read_text(encoding="utf-8")
            )
            assert environment["runtime_identity"] == {
                "artifact_sha256": _sha256(malformed_content),
                "semantic_runtime_sha256": None,
            }
            assert environment["tools"] == {
                "coverage": None,
                "pytest": None,
                "uv": None,
            }
            assert manifest["semantic_runtime_sha256"] is None
            assert malformed.gate_kind(target) == "stub"

    absent = RunnerHarness.create(
        tmp_path / "absent-identity", source_root=REPOSITORY_ROOT
    ).run(
        _runner_supplier(plugin_identity=None),
        scenario=RunnerScenario(verifier_mode="stub-success"),
        run_id="r2-absent-identity",
    )
    assert absent.returncode == 1
    for target in ("capture", "retention"):
        artifacts = absent.artifacts(target)
        environment = json.loads(
            artifacts["environment"].read_text(encoding="utf-8")
        )
        assert environment["runtime_identity"] == {
            "artifact_sha256": None,
            "semantic_runtime_sha256": None,
        }
        assert environment["tools"] == {
            "coverage": None,
            "pytest": None,
            "uv": None,
        }
        assert artifacts["runner_error"].exists()
        assert absent.gate_kind(target) == "absent"

    oversize_content = b"x" * (_policy()["limits"]["plugin_identity_bytes"] + 1)
    oversize = RunnerHarness.create(
        tmp_path / "oversize-identity", source_root=REPOSITORY_ROOT
    ).run(
        _runner_supplier(plugin_identity=oversize_content),
        scenario=RunnerScenario(verifier_mode="stub-success"),
        run_id="r2-oversize-identity",
    )
    assert oversize.returncode == 0, (oversize.stdout, oversize.stderr)
    for target in ("capture", "retention"):
        artifacts = oversize.artifacts(target)
        environment = json.loads(
            artifacts["environment"].read_text(encoding="utf-8")
        )
        assert environment["runtime_identity"] == {
            "artifact_sha256": None,
            "semantic_runtime_sha256": None,
        }
        assert environment["tools"] == {
            "coverage": None,
            "pytest": None,
            "uv": None,
        }
        assert oversize.gate_kind(target) == "stub"

    unreadable = RunnerHarness.create(
        tmp_path / "unreadable-identity", source_root=REPOSITORY_ROOT
    ).run(
        _runner_supplier(plugin_identity=positive_content),
        scenario=RunnerScenario(
            verifier_mode="stub-success",
            environment_identity_errno=errno.EACCES,
        ),
        run_id="r2-unreadable-identity",
    )
    assert unreadable.returncode == 0, (unreadable.stdout, unreadable.stderr)
    for target in ("capture", "retention"):
        artifacts = unreadable.artifacts(target)
        environment = json.loads(
            artifacts["environment"].read_text(encoding="utf-8")
        )
        assert environment["runtime_identity"] == {
            "artifact_sha256": None,
            "semantic_runtime_sha256": None,
        }
        assert environment["tools"] == {
            "coverage": None,
            "pytest": None,
            "uv": None,
        }
        assert unreadable.gate_kind(target) == "stub"

    early = RunnerHarness.create(
        tmp_path / "early", source_root=REPOSITORY_ROOT
    ).run(
        _runner_supplier(coverage_data=None),
        scenario=RunnerScenario(verifier_mode="stub-success"),
        run_id="r2-missing-coverage-raw",
    )
    assert early.returncode == 1, (early.stdout, early.stderr)
    assert not any(call.kind.startswith("verifier-") for call in early.calls())
    for target in ("capture", "retention"):
        artifacts = early.artifacts(target)
        error = json.loads(artifacts["runner_error"].read_text(encoding="utf-8"))
        assert error["schema_version"] == 2
        assert error["stage"] == "raw-completeness"
        assert error["reason_code"] == "REQUIRED_RAW_ARTIFACT_MISSING"
        assert artifacts["coverage_data"].name in error["missing_artifacts"]
        assert not artifacts["run_manifest"].exists()
        assert early.gate_kind(target) == "absent"


def test_s18_b3f_r2_policy_and_gate_have_exact_current_schema(tmp_path):
    artifact_oracles.assert_policy_and_gate_exact_schema(tmp_path / "dynamic")
    policy = _policy()
    assert frozenset(policy) == frozenset(
        {"schema_version", "thresholds", "limits", "scripts", "runners", "runtime"}
    )
    assert policy["schema_version"] == 3
    assert policy["runtime"] == {
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
    assert {
        key: policy["limits"][key]
        for key in (
            "plugin_identity_bytes",
            "runtime_metadata_bytes",
            "runtime_record_bytes",
            "runtime_required_entry_bytes",
            "runtime_pyvenv_cfg_bytes",
        )
    } == {
        "plugin_identity_bytes": 4 * 1024 * 1024,
        "runtime_metadata_bytes": 256 * 1024,
        "runtime_record_bytes": 256 * 1024,
        "runtime_required_entry_bytes": 1024 * 1024,
        "runtime_pyvenv_cfg_bytes": 16 * 1024,
    }
    gate_source = inspect.getsource(verifier.verify_security_coverage)
    assert '"schema_version": 5' in gate_source
    assert '"runtime_identity":' in gate_source
    assert '"plugin_identity":' not in gate_source
