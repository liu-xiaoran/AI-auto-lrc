"""B3f-R1b contracts for the internal runtime identity composers."""

from __future__ import annotations

import ast
import base64
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import security_pytest_bootstrap as bootstrap

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPOSITORY_ROOT / "scripts/security_pytest_bootstrap.py"
BOUND_MODULES = (
    "pluggy",
    "coverage",
    "pytest",
    "pytest_cov",
    "pytest_cov.plugin",
)
BOUND_PATHS = (
    "pluggy/__init__.py",
    "coverage/__init__.py",
    "pytest/__init__.py",
    "pytest_cov/__init__.py",
    "pytest_cov/plugin.py",
)
RUNTIME_LAYOUT_KEYS = frozenset(
    {
        "executable",
        "executable_realpath",
        "executable_size",
        "executable_sha256",
        "venv_root",
        "base_prefix",
        "site_packages",
        "home",
        "pyvenv_cfg_path",
        "pyvenv_cfg_bytes",
        "pyvenv_cfg_size",
        "pyvenv_cfg_sha256",
        "implementation",
        "version",
        "cache_tag",
        "system",
        "machine",
        "isolated",
        "no_site",
        "dont_write_bytecode",
    }
)
INSTALLED_DISTRIBUTION_KEYS = frozenset(
    {
        "name",
        "version",
        "dist_info",
        "metadata_bytes",
        "metadata_size",
        "metadata_sha256",
        "record_bytes",
        "record_size",
        "record_sha256",
        "record_rows",
        "required_entries",
    }
)
LOCK_PACKAGE_KEYS = frozenset(
    {
        "name",
        "version",
        "exact_package_object",
        "canonical_package_bytes",
        "lock_package_sha256",
        "lock_file_sha256",
        "required_dependencies",
    }
)
PLUGIN_KEYS = frozenset({"file", "sha256", "distribution", "entry"})


def _future(name: str):
    seam = getattr(bootstrap, name, None)
    assert callable(seam), f"B3f-R1b RED: missing callable {name}"
    return seam


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _record_digest(content: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()


def _record_row(path: str, content: bytes, *, newline: bytes = b"\n") -> bytes:
    return (
        path.encode()
        + b",sha256="
        + _record_digest(content).encode()
        + b","
        + str(len(content)).encode()
        + newline
    )


def _runtime_fixture(root: Path) -> dict[str, Path | bytes]:
    base_prefix = root / "base-python"
    home = base_prefix / "bin"
    home.mkdir(parents=True)
    target = home / "python3.11"
    python_bytes = b"synthetic bound python executable\n"
    target.write_bytes(python_bytes)
    target.chmod(0o700)
    venv = root / "runtime"
    executable = venv / "bin/python"
    executable.parent.mkdir(parents=True)
    executable.symlink_to(target)
    pyvenv = venv / "pyvenv.cfg"
    pyvenv_bytes = (
        f"home = {home}\n"
        "implementation = CPython\n"
        "version_info = 3.11.4\n"
        "include-system-site-packages = false\n"
    ).encode()
    pyvenv.write_bytes(pyvenv_bytes)
    site_packages = venv / "lib/python3.11/site-packages"
    site_packages.mkdir(parents=True)
    return {
        "base_prefix": base_prefix,
        "executable": executable,
        "home": home,
        "pyvenv": pyvenv,
        "pyvenv_bytes": pyvenv_bytes,
        "python_bytes": python_bytes,
        "site_packages": site_packages,
        "target": target,
        "venv": venv,
    }


def _metadata(name: str, version: str, *, newline: bytes = b"\n") -> bytes:
    return newline.join(
        (
            b"Metadata-Version: 2.4",
            b"Name: " + name.encode(),
            b"Version: " + version.encode(),
            b"Summary: exact raw metadata bytes",
            b"",
            b"",
        )
    )


def _make_distribution(
    site_packages: Path,
    *,
    name: str = "runtime-core",
    version: str = "1.0",
    dist_info_name: str | None = None,
    required_contents: dict[str, bytes] | None = None,
    newline: bytes = b"\n",
    metadata_bytes: bytes | None = None,
) -> tuple[Path, bytes, bytes, dict[str, bytes]]:
    contents = required_contents or {"pluggy/__init__.py": b"BOUND_EXECUTED = 'pluggy'\n"}
    for relative, content in contents.items():
        path = site_packages / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    dist_info = site_packages / (dist_info_name or f"{name.replace('-', '_')}-{version}.dist-info")
    dist_info.mkdir()
    raw_metadata = metadata_bytes if metadata_bytes is not None else _metadata(name, version, newline=newline)
    (dist_info / "METADATA").write_bytes(raw_metadata)
    rows = [_record_row(path, content, newline=newline) for path, content in contents.items()]
    rows.append(f"{dist_info.name}/RECORD,,".encode() + newline)
    opaque = b"opaque console script\n"
    rows.append(
        b'"../../../bin/runtime,core",sha256='
        + _record_digest(opaque).encode()
        + b","
        + str(len(opaque)).encode()
        + newline
    )
    raw_record = b"".join(rows)
    (dist_info / "RECORD").write_bytes(raw_record)
    return dist_info, raw_metadata, raw_record, contents


def _write_lock(path: Path, packages: list[dict[str, object]]) -> bytes:
    lines = ["version = 1", "revision = 3", "requires-python = \">=3.11\"", ""]
    for package in packages:
        lines.extend(("[[package]]", f'name = "{package["name"]}"', f'version = "{package["version"]}"'))
        source = package.get("source", {"registry": "https://example.invalid/simple"})
        assert isinstance(source, dict)
        if "registry" in source:
            lines.append(f'source = {{ registry = "{source["registry"]}" }}')
        dependencies = package.get("dependencies", [])
        assert isinstance(dependencies, list)
        if dependencies:
            rendered = ", ".join(f'{{ name = "{item}" }}' for item in dependencies)
            lines.append(f"dependencies = [{rendered}]")
        marker = package.get("marker")
        if marker is not None:
            lines.append(f'marker = "{marker}"')
        lines.append("")
    content = "\n".join(lines).encode()
    path.write_bytes(content)
    return content


def _installed_identity(
    name: str, entries: dict[str, bytes]
) -> dict[str, object]:
    version = "1.0"
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    metadata = _metadata(name, version)
    record = b"".join(
        (
            *(_record_row(path, content) for path, content in entries.items()),
            f"{dist_info}/RECORD,,\n".encode(),
        )
    )
    rows = bootstrap._parse_distribution_record(
        record,
        dist_info=dist_info,
        required_paths=tuple(entries),
    )
    return {
        "name": name,
        "version": version,
        "dist_info": dist_info,
        "metadata_bytes": metadata,
        "metadata_size": len(metadata),
        "metadata_sha256": _sha256(metadata),
        "record_bytes": record,
        "record_size": len(record),
        "record_sha256": _sha256(record),
        "record_rows": rows,
        "required_entries": {
            path: {"bytes": content, "size": len(content), "sha256": _sha256(content)}
            for path, content in entries.items()
        },
    }


def _lock_identity(name: str, *, dependencies: tuple[str, ...]) -> dict[str, object]:
    package = {
        "name": name,
        "version": "1.0",
        "source": {"registry": "https://example.invalid/simple"},
        "dependencies": [{"name": item} for item in dependencies],
    }
    canonical = json.dumps(
        package, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return {
        "name": name,
        "version": "1.0",
        "exact_package_object": package,
        "canonical_package_bytes": canonical,
        "lock_package_sha256": _sha256(canonical),
        "lock_file_sha256": "a" * 64,
        "required_dependencies": dependencies,
    }


def _builder_inputs(seed: bytes = b"seed") -> dict[str, object]:
    pyvenv = (
        b"home = /opt/python/bin\n"
        b"implementation = CPython\n"
        b"version_info = 3.11.4\n"
        b"include-system-site-packages = false\n"
    )
    runtime = {
        "executable": "/work/.venv/bin/python",
        "executable_realpath": "/opt/python/bin/python3.11",
        "executable_size": 32768,
        "executable_sha256": "1" * 64,
        "venv_root": "/work/.venv",
        "base_prefix": "/opt/python",
        "site_packages": "/work/.venv/lib/python3.11/site-packages",
        "home": "/opt/python/bin",
        "pyvenv_cfg_path": "/work/.venv/pyvenv.cfg",
        "pyvenv_cfg_bytes": pyvenv,
        "pyvenv_cfg_size": len(pyvenv),
        "pyvenv_cfg_sha256": _sha256(pyvenv),
        "implementation": "CPython",
        "version": "3.11.4",
        "cache_tag": "cpython-311",
        "system": "Darwin",
        "machine": "arm64",
        "isolated": True,
        "no_site": True,
        "dont_write_bytecode": True,
    }
    required = {
        "coverage": (("coverage/__init__.py",), ()),
        "pluggy": (("pluggy/__init__.py",), ()),
        "pytest": (("pytest/__init__.py",), ("pluggy",)),
        "pytest-cov": (
            ("pytest_cov/__init__.py", "pytest_cov/plugin.py"),
            ("coverage", "pluggy", "pytest"),
        ),
    }
    distributions = {
        name: {
            "installed": _installed_identity(
                name,
                {
                    path: seed + name.encode() + path.encode()
                    for path in paths
                },
            ),
            "lock": _lock_identity(name, dependencies=dependencies),
        }
        for name, (paths, dependencies) in required.items()
    }
    cov_entry = distributions["pytest-cov"]["installed"]["required_entries"][
        "pytest_cov/plugin.py"
    ]
    assert isinstance(cov_entry, dict)
    plugins = {
        "pytest_cov.plugin": {
            "file": "/work/.venv/lib/python3.11/site-packages/pytest_cov/plugin.py",
            "sha256": cov_entry["sha256"],
            "distribution": "pytest-cov",
            "entry": "pytest_cov/plugin.py",
        },
        "scripts.pytest_security_events": {
            "file": "/work/scripts/pytest_security_events.py",
            "sha256": "2" * 64,
            "distribution": None,
            "entry": None,
        },
    }
    return {
        "scope": {
            "run_id": "run-001",
            "target": "capture",
            "runner": "macos",
            "attempt": 1,
            "timestamp": "2026-09-07T00:00:00Z",
        },
        "runtime_layout": runtime,
        "uv_identity": {"path": "/opt/homebrew/bin/uv", "version": "0.8.15", "sha256": "3" * 64},
        "uv_lock_sha256": "a" * 64,
        "distributions": distributions,
        "plugins": plugins,
    }


def _assert_base64_copy(encoded: object, raw: bytes) -> None:
    assert isinstance(encoded, str)
    assert encoded == base64.b64encode(raw).decode("ascii")
    assert base64.b64decode(encoded, validate=True) == raw


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def test_s18_b3f_r1b_runtime_layout_binds_alias_target_pyvenv_and_base_prefix(tmp_path):
    capture = _future("_capture_runtime_layout")
    fixture = _runtime_fixture(tmp_path)
    result = capture(
        fixture["executable"],
        python_major_minor=(3, 11),
        base_prefix=fixture["base_prefix"],
    )
    assert frozenset(result) == RUNTIME_LAYOUT_KEYS
    assert result["executable"] == os.fspath(fixture["executable"])
    assert result["executable_realpath"] == os.fspath(fixture["target"])
    assert result["venv_root"] == os.fspath(fixture["venv"])
    assert result["base_prefix"] == os.fspath(fixture["base_prefix"])
    assert result["site_packages"] == os.fspath(fixture["site_packages"])
    assert result["home"] == os.fspath(fixture["home"])
    assert result["pyvenv_cfg_bytes"] == fixture["pyvenv_bytes"]
    assert result["pyvenv_cfg_size"] == len(fixture["pyvenv_bytes"])
    assert result["pyvenv_cfg_sha256"] == _sha256(fixture["pyvenv_bytes"])
    assert result["executable_size"] == len(fixture["python_bytes"])
    assert result["executable_sha256"] == _sha256(fixture["python_bytes"])


def test_s18_b3f_r1b_runtime_layout_rejects_alias_endpoint_swap(tmp_path, monkeypatch):
    capture = _future("_capture_runtime_layout")
    fixture = _runtime_fixture(tmp_path)
    second = fixture["home"] / "python3.11-second"
    second.write_bytes(fixture["python_bytes"])
    second.chmod(0o700)
    original = bootstrap._validate_executable_alias
    calls = 0

    def swapping_alias(executable):
        nonlocal calls
        result = original(executable)
        calls += 1
        if calls == 1:
            fixture["executable"].unlink()
            fixture["executable"].symlink_to(second)
        return result

    monkeypatch.setattr(bootstrap, "_validate_executable_alias", swapping_alias)
    with pytest.raises(bootstrap.BootstrapError):
        capture(
            fixture["executable"],
            python_major_minor=(3, 11),
            base_prefix=fixture["base_prefix"],
        )


def test_s18_b3f_r1b_runtime_layout_rejects_python_or_pyvenv_before_after_drift(
    tmp_path, monkeypatch
):
    capture = _future("_capture_runtime_layout")
    original = bootstrap._stable_read
    for field in ("target", "pyvenv"):
        fixture = _runtime_fixture(tmp_path / field)
        selected = fixture[field]

        def drifting_read(path, _selected=selected, **kwargs):
            content = original(path, **kwargs)
            if path == _selected:
                replacement = path.with_name(path.name + ".replacement")
                replacement.write_bytes(content)
                replacement.chmod(path.stat().st_mode)
                os.replace(replacement, path)
            return content

        with monkeypatch.context() as context:
            context.setattr(bootstrap, "_stable_read", drifting_read)
            with pytest.raises(bootstrap.BootstrapError):
                capture(
                    fixture["executable"],
                    python_major_minor=(3, 11),
                    base_prefix=fixture["base_prefix"],
                )


def test_s18_b3f_r1b_loader_failure_path_is_statically_terminal():
    tree = ast.parse(inspect.getsource(bootstrap.main))
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    prepare_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_prepare_bound_runtime"
    ]
    assert len(prepare_calls) == 1
    no_site_branches = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.If)
        and any(
            isinstance(part, ast.Attribute) and part.attr == "no_site"
            for part in ast.walk(node.test)
        )
    ]
    assert len(no_site_branches) == 1
    assert prepare_calls[0] not in tuple(ast.walk(no_site_branches[0]))
    assert any(
        isinstance(node, ast.Raise) for node in ast.walk(no_site_branches[0])
    )
    handlers = [node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler)]
    assert any(
        handler.type is not None
        and any(isinstance(node, ast.Name) and node.id == "BootstrapError" for node in ast.walk(handler.type))
        and any(isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and node.value.value == 2 for node in ast.walk(handler))
        for handler in handlers
    )
    assert not any(isinstance(node, ast.Try) and node.finalbody for node in ast.walk(function))


_TERMINAL_MAIN_PROBE = r"""
import importlib.util
import json
import sys
from pathlib import Path

bootstrap_path = Path(sys.argv[1])
output = Path(sys.argv[2])
trace = Path(sys.argv[3])
failure = sys.argv[4]
spec = importlib.util.spec_from_file_location("b3f_r1b_terminal_main", bootstrap_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
counts = {"prepare": 0, "builder": 0, "write": 0, "pytest_main": 0}

def persist():
    trace.write_text(json.dumps(counts, sort_keys=True), encoding="utf-8")

original_prepare = module._prepare_bound_runtime
original_validate = module._validate_bound_runtime_entries
original_read = module._stable_read
original_compile = __import__("builtins").compile
original_exec = __import__("builtins").exec

def tracked_prepare(*args, **kwargs):
    counts["prepare"] += 1
    persist()
    return original_prepare(*args, **kwargs)

def forbidden_builder(*args, **kwargs):
    counts["builder"] += 1
    persist()
    raise AssertionError("builder ran after loader failure")

def forbidden_write(*args, **kwargs):
    counts["write"] += 1
    persist()
    raise AssertionError("writer ran after loader failure")

class PytestTripwire:
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "pytest":
            return None
        counts["pytest_main"] += 1
        persist()
        raise AssertionError("pytest import ran after loader failure")

if failure == "validate":
    def injected_validate(*args, **kwargs):
        raise module.BootstrapError("injected validate failure")
    module._validate_bound_runtime_entries = injected_validate
elif failure == "read":
    def injected_read(path, **kwargs):
        if "required entry" in kwargs.get("field", ""):
            raise module.BootstrapError("injected read failure")
        return original_read(path, **kwargs)
    module._stable_read = injected_read
elif failure == "compile":
    def injected_compile(source, filename, *args, **kwargs):
        if str(filename).endswith("pluggy/__init__.py"):
            raise SyntaxError("injected compile failure")
        return original_compile(source, filename, *args, **kwargs)
    __import__("builtins").compile = injected_compile
elif failure == "exec":
    def injected_exec(code, globals=None, locals=None):
        if str(getattr(code, "co_filename", "")).endswith("pluggy/__init__.py"):
            raise RuntimeError("injected exec failure")
        return original_exec(code, globals, locals)
    __import__("builtins").exec = injected_exec
else:
    raise AssertionError("unknown injection")

module._prepare_bound_runtime = tracked_prepare
module._build_runtime_identity_v2 = forbidden_builder
module._write_exclusive = forbidden_write
sys.modules.pop("pytest", None)
sys.meta_path.insert(0, PytestTripwire())
result = module.main([
    "--plugin-identity=" + str(output),
    "--runtime-uv-path=" + str(Path(sys.executable)),
    "--runtime-uv-version=0.12.9",
    "--runtime-uv-sha256=" + "0" * 64,
    "--runtime-timestamp=2026-09-07T12:34:56.123456Z",
    "--",
    "--security-run-id=r1b-terminal",
    "--security-target=capture",
    "--security-runner=macos",
    "--security-attempt=1",
])
persist()
raise SystemExit(result)
"""


_REAL_PREPARE_SMOKE = r"""
import importlib.util
import json
import site
import sys
from pathlib import Path

bootstrap_path = Path(sys.argv[1])
lock_path = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("b3f_r1b_prepare_smoke", bootstrap_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_layout = module._capture_runtime_layout
original_distribution = module._capture_named_distribution
original_lock = module._capture_lock_package
original_loader = module._load_captured_runtime_modules
counts = {"layout": 0, "distributions": [], "locks": [], "loader": 0, "legacy": 0}
site_root = None

def tracked_layout(executable, **kwargs):
    global site_root
    counts["layout"] += 1
    assert executable == Path(sys.executable)
    assert kwargs["base_prefix"] == Path(sys.base_prefix)
    assert kwargs["python_major_minor"] == (sys.version_info.major, sys.version_info.minor)
    result = original_layout(executable, **kwargs)
    assert result["implementation"] == "CPython"
    assert result["version"] == ".".join(str(item) for item in sys.version_info[:3])
    assert result["cache_tag"] == sys.implementation.cache_tag
    assert result["isolated"] is result["no_site"] is result["dont_write_bytecode"] is True
    site_root = result["site_packages"]
    return result

def tracked_distribution(site_packages, **kwargs):
    counts["distributions"].append([kwargs["canonical_name"], list(kwargs["required_paths"])])
    assert str(site_packages) == site_root
    return original_distribution(site_packages, **kwargs)

def tracked_lock(path, **kwargs):
    counts["locks"].append([kwargs["canonical_name"], list(kwargs["required_dependencies"])])
    return original_lock(path, **kwargs)

def tracked_loader(entries, sources):
    counts["loader"] += 1
    return original_loader(entries, sources)

def forbidden_legacy(*args, **kwargs):
    counts["legacy"] += 1
    raise AssertionError("legacy pytest-cov resolver ran in no-site mode")

def forbidden_addsitedir(*args, **kwargs):
    raise AssertionError("site.addsitedir ran for captured runtime")

module._capture_runtime_layout = tracked_layout
module._capture_named_distribution = tracked_distribution
module._capture_lock_package = tracked_lock
module._load_captured_runtime_modules = tracked_loader
module._pytest_cov_identity = forbidden_legacy
site.addsitedir = forbidden_addsitedir
before_path = list(sys.path)
prepared = module._prepare_bound_runtime(
    Path(sys.executable),
    python_major_minor=(sys.version_info.major, sys.version_info.minor),
    base_prefix=Path(sys.base_prefix),
    lock_path=lock_path,
    uv_identity={"path": str(Path(sys.executable)), "version": "0.12.9", "sha256": "0" * 64},
)
plugin = prepared.loaded_modules["pytest_cov.plugin"]
identity = prepared.pytest_cov_plugin_identity
print(json.dumps({
    "added_sys_path": [item for item in sys.path if item not in before_path],
    "counts": counts,
    "distribution": identity["distribution"],
    "distribution_version": prepared.distributions["pytest-cov"]["installed"]["version"],
    "module": plugin.__name__,
    "no_site": bool(sys.flags.no_site),
}, sort_keys=True))
"""


_REAL_MAIN_SUCCESS_PROBE = r"""
import importlib.util
import json
import sys
import types
from pathlib import Path

bootstrap_path = Path(sys.argv[1])
output = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("b3f_r1b_main_success", bootstrap_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_prepare = module._prepare_bound_runtime
original_builder = module._build_runtime_identity_v2
state = {"prepare": 0, "pytest_main": 0, "builder": 0, "write": 0}
prepared_plugin = None

fake_pytest = types.ModuleType("pytest")

def fake_pytest_main(arguments, plugins):
    state["pytest_main"] += 1
    assert plugins[0] is prepared_plugin
    guard = plugins[-1]
    document = guard._document
    assert document["schema_version"] == 2
    assert len(document["semantic_runtime_sha256"]) == 64
    assert set(document["plugins"]) == {
        "pytest_cov.plugin", "scripts.pytest_security_events"
    }
    state["document"] = document
    return 0

fake_pytest.main = fake_pytest_main

def tracked_prepare(*args, **kwargs):
    global prepared_plugin
    state["prepare"] += 1
    prepared = original_prepare(*args, **kwargs)
    prepared_plugin = prepared.loaded_modules["pytest_cov.plugin"]
    sys.modules["pytest"] = fake_pytest
    return prepared

def fake_events(*args, **kwargs):
    plugin = types.ModuleType("scripts.pytest_security_events")
    return plugin, {
        "file": str(Path(args[0]) / "scripts/pytest_security_events.py"),
        "sha256": "0" * 64,
        "distribution": None,
        "entry": None,
    }

def tracked_builder(*args, **kwargs):
    state["builder"] += 1
    return original_builder(*args, **kwargs)

def forbidden_write(*args, **kwargs):
    state["write"] += 1
    raise AssertionError("identity writer ran before intercepted pytest.main")

module._prepare_bound_runtime = tracked_prepare
module._local_events_plugin = fake_events
module._build_runtime_identity_v2 = tracked_builder
module._write_exclusive = forbidden_write
result = module.main([
    "--plugin-identity=" + str(output),
    "--runtime-uv-path=" + str(Path(sys.executable)),
    "--runtime-uv-version=0.12.9",
    "--runtime-uv-sha256=" + "0" * 64,
    "--runtime-timestamp=2026-09-07T12:34:56.123456Z",
    "--",
    "--security-run-id=r1b-main-success",
    "--security-target=capture",
    "--security-runner=macos",
    "--security-attempt=1",
])
assert result == 0
assert not output.exists()
print(json.dumps(state, sort_keys=True))
"""


def test_s18_b3f_r1b_loader_failure_exits_without_publish_or_pytest(tmp_path):
    _future("_prepare_bound_runtime")
    compile(_TERMINAL_MAIN_PROBE, "<b3f-r1b-terminal-main>", "exec")
    for failure in ("validate", "read", "compile", "exec"):
        output = tmp_path / f"{failure}-identity.json"
        trace = tmp_path / f"{failure}-trace.json"
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                _TERMINAL_MAIN_PROBE,
                os.fspath(BOOTSTRAP),
                os.fspath(output),
                os.fspath(trace),
                failure,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2
        assert result.stdout == ""
        assert result.stderr.startswith("SECURITY_PYTEST_BOOTSTRAP_INVALID: ")
        assert "Traceback" not in result.stderr
        assert json.loads(trace.read_text(encoding="utf-8")) == {
            "builder": 0,
            "prepare": 1,
            "pytest_main": 0,
            "write": 0,
        }
        assert not output.exists()
        assert not tuple(tmp_path.glob(f".{output.name}.*.tmp"))

    smoke = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            _REAL_PREPARE_SMOKE,
            os.fspath(BOOTSTRAP),
            os.fspath(REPOSITORY_ROOT / "uv.lock"),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert smoke.returncode == 0, smoke.stderr
    smoke_document = json.loads(smoke.stdout)
    assert smoke_document == {
        "added_sys_path": [
            os.fspath(REPOSITORY_ROOT / ".venv/lib/python3.11/site-packages")
        ],
        "counts": {
            "layout": 1,
            "distributions": [
                ["coverage", ["coverage/__init__.py"]],
                ["pluggy", ["pluggy/__init__.py"]],
                ["pytest", ["pytest/__init__.py"]],
                ["pytest-cov", ["pytest_cov/__init__.py", "pytest_cov/plugin.py"]],
            ],
            "locks": [
                ["coverage", []],
                ["pluggy", []],
                ["pytest", ["pluggy"]],
                ["pytest-cov", ["coverage", "pluggy", "pytest"]],
            ],
            "loader": 1,
            "legacy": 0,
        },
        "distribution": "pytest-cov",
        "distribution_version": "6.3.0",
        "module": "pytest_cov.plugin",
        "no_site": True,
    }

    main_success = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            _REAL_MAIN_SUCCESS_PROBE,
            os.fspath(BOOTSTRAP),
            os.fspath(tmp_path / "main-success-identity.json"),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert main_success.returncode == 0, main_success.stderr
    main_document = json.loads(main_success.stdout)
    assert main_document["prepare"] == 1
    assert main_document["pytest_main"] == 1
    assert main_document["builder"] == 1
    assert main_document["write"] == 0
    assert main_document["document"]["schema_version"] == 2


def test_s18_b3f_r1b_distribution_resolution_requires_one_canonical_direct_child(tmp_path):
    capture = _future("_capture_named_distribution")
    site = tmp_path / "site-packages"
    site.mkdir()
    nested = site / "nested"
    nested.mkdir()
    _make_distribution(nested, name="runtime-core")
    with pytest.raises(bootstrap.BootstrapError):
        capture(site, canonical_name="runtime-core", required_paths=("pluggy/__init__.py",))

    first, _metadata_bytes, _record_bytes, _contents = _make_distribution(
        site, name="runtime-core", dist_info_name="Runtime_Core-1.0.dist-info"
    )
    installed, _entries, _sources = capture(
        site, canonical_name="runtime-core", required_paths=("pluggy/__init__.py",)
    )
    assert installed["dist_info"] == first.name

    _make_distribution(site, name="runtime-core", dist_info_name="runtime.core-2.0.dist-info", version="2.0")
    with pytest.raises(bootstrap.BootstrapError):
        capture(site, canonical_name="runtime-core", required_paths=("pluggy/__init__.py",))

    symlink_site = tmp_path / "symlink-site"
    symlink_site.mkdir()
    outside = tmp_path / "outside-1.0.dist-info"
    outside.mkdir()
    (symlink_site / "runtime_core-1.0.dist-info").symlink_to(outside, target_is_directory=True)
    with pytest.raises(bootstrap.BootstrapError):
        capture(
            symlink_site,
            canonical_name="runtime-core",
            required_paths=("pluggy/__init__.py",),
        )


def test_s18_b3f_r1b_distribution_metadata_name_and_version_are_exact(tmp_path):
    capture = _future("_capture_named_distribution")
    invalid_metadata = (
        b"Metadata-Version: 2.4\nVersion: 1.0\n\n",
        b"Metadata-Version: 2.4\nName: runtime-core\nName: runtime-core\nVersion: 1.0\n\n",
        b"Metadata-Version: 2.4\nName: Runtime.Core\nVersion: 1.0\n\n",
        b"Metadata-Version: 2.4\nName: runtime-core\nVersion: 2.0\n\n",
        b"\xff",
    )
    for index, metadata_bytes in enumerate(invalid_metadata):
        site = tmp_path / f"site-{index}"
        site.mkdir()
        _make_distribution(site, metadata_bytes=metadata_bytes)
        with pytest.raises(bootstrap.BootstrapError):
            capture(site, canonical_name="runtime-core", required_paths=("pluggy/__init__.py",))


def test_s18_b3f_r1b_distribution_hashes_original_metadata_and_record_bytes(tmp_path):
    capture = _future("_capture_named_distribution")
    results = []
    for label, newline in (("lf", b"\n"), ("crlf", b"\r\n")):
        site = tmp_path / label
        site.mkdir()
        _dist_info, metadata_bytes, record_bytes, _contents = _make_distribution(
            site, newline=newline
        )
        installed, _entries, _sources = capture(
            site, canonical_name="runtime-core", required_paths=("pluggy/__init__.py",)
        )
        assert installed["metadata_bytes"] == metadata_bytes
        assert installed["metadata_size"] == len(metadata_bytes)
        assert installed["metadata_sha256"] == _sha256(metadata_bytes)
        assert installed["record_bytes"] == record_bytes
        assert installed["record_size"] == len(record_bytes)
        assert installed["record_sha256"] == _sha256(record_bytes)
        results.append(installed)
    assert results[0]["record_rows"] == results[1]["record_rows"]
    assert results[0]["record_sha256"] != results[1]["record_sha256"]
    assert results[0]["metadata_sha256"] != results[1]["metadata_sha256"]


def test_s18_b3f_r1b_distribution_never_resolves_or_opens_opaque_record_rows(
    tmp_path, monkeypatch
):
    capture = _future("_capture_named_distribution")
    site = tmp_path / "site-packages"
    site.mkdir()
    _make_distribution(site)
    original_resolve = Path.resolve
    original_lstat = Path.lstat
    original_stat = Path.stat
    original_open = Path.open
    original_os_open = os.open
    original_stable_read = bootstrap._stable_read

    def opaque(path) -> bool:
        return ".." in path.parts or "runtime,core" in os.fspath(path)

    def guarded_resolve(path, *args, **kwargs):
        assert not opaque(path), "opaque RECORD row was resolved"
        return original_resolve(path, *args, **kwargs)

    def guarded_lstat(path, *args, **kwargs):
        assert not opaque(path), "opaque RECORD row reached lstat"
        return original_lstat(path, *args, **kwargs)

    def guarded_stat(path, *args, **kwargs):
        assert not opaque(path), "opaque RECORD row reached stat"
        return original_stat(path, *args, **kwargs)

    def guarded_open(path, *args, **kwargs):
        assert not opaque(path), "opaque RECORD row was opened"
        return original_open(path, *args, **kwargs)

    def guarded_os_open(path, *args, **kwargs):
        assert "runtime,core" not in os.fspath(path), "opaque RECORD row reached os.open"
        return original_os_open(path, *args, **kwargs)

    def guarded_stable_read(path, **kwargs):
        assert not opaque(path), "opaque RECORD row reached stable read"
        return original_stable_read(path, **kwargs)

    monkeypatch.setattr(Path, "resolve", guarded_resolve)
    monkeypatch.setattr(Path, "lstat", guarded_lstat)
    monkeypatch.setattr(Path, "stat", guarded_stat)
    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    monkeypatch.setattr(bootstrap, "_stable_read", guarded_stable_read)
    installed, _entries, _sources = capture(
        site, canonical_name="runtime-core", required_paths=("pluggy/__init__.py",)
    )
    assert [row["kind"] for row in installed["record_rows"]].count("opaque") == 1


_CAPTURED_LOADER_PROBE = r"""
import builtins
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

bootstrap_path = Path(sys.argv[1])
site = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("b3f_r1b_captured_loader", bootstrap_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
capture = module._capture_named_distribution
load = module._load_captured_runtime_modules
original = module._stable_read
counts = {}

def counted(path, **kwargs):
    counts[str(path)] = counts.get(str(path), 0) + 1
    return original(path, **kwargs)

module._stable_read = counted
installed, entries, sources = capture(
    site,
    canonical_name="runtime-core",
    required_paths=(
        "pluggy/__init__.py",
        "coverage/__init__.py",
        "pytest/__init__.py",
        "pytest_cov/__init__.py",
        "pytest_cov/plugin.py",
    ),
)

def rejected(candidate_entries, candidate_sources):
    try:
        load(candidate_entries, candidate_sources)
    except module.BootstrapError:
        pass
    else:
        raise AssertionError("invalid captured loader input was accepted")
    assert all(name not in sys.modules for name in (
        "pluggy", "coverage", "pytest", "pytest_cov", "pytest_cov.plugin"
    ))

rejected(entries, sources[:-1])
rejected(entries, list(sources))
wrong_order = list(entries)
wrong_order[0], wrong_order[1] = wrong_order[1], wrong_order[0]
rejected(tuple(wrong_order), sources)
wrong_hash = [dict(item) for item in entries]
wrong_hash[0]["expected_sha256"] = "0" * 64
rejected(tuple(wrong_hash), sources)
wrong_size = [dict(item) for item in entries]
wrong_size[0]["expected_size"] += 1
rejected(tuple(wrong_size), sources)
oversize = b"x" * (1024 * 1024 + 1)
oversize_entries = [dict(item) for item in entries]
oversize_entries[0]["expected_size"] = len(oversize)
oversize_entries[0]["expected_sha256"] = hashlib.sha256(oversize).hexdigest()
rejected(tuple(oversize_entries), (oversize, *sources[1:]))

source_ids = {id(source) for source in sources}
hashed_ids = set()
compiled_ids = set()
original_sha256 = module._sha256
original_compile = builtins.compile

def tracked_sha256(source):
    if id(source) in source_ids:
        hashed_ids.add(id(source))
    return original_sha256(source)

def tracked_compile(source, *args, **kwargs):
    if id(source) in source_ids:
        compiled_ids.add(id(source))
    return original_compile(source, *args, **kwargs)

module._sha256 = tracked_sha256
builtins.compile = tracked_compile
for entry in entries:
    Path(entry["path"]).write_text('raise RuntimeError("live source used")\n', encoding="utf-8")

def forbidden_read(*args, **kwargs):
    raise AssertionError("captured loader performed live I/O")

module._stable_read = forbidden_read
modules, identities = load(entries, sources)
assert hashed_ids == compiled_ids == source_ids
print(json.dumps({
    "counts": counts,
    "identities": identities,
    "loaded": {name: item.BOUND_EXECUTED for name, item in modules.items()},
    "required": {
        path: {"sha256": value["sha256"], "size": value["size"]}
        for path, value in installed["required_entries"].items()
    },
}, sort_keys=True))
"""


def test_s18_b3f_r1b_required_entry_drift_is_rejected_and_capture_bytes_drive_loader(
    tmp_path, monkeypatch
):
    capture = _future("_capture_named_distribution")
    _future("_load_captured_runtime_modules")
    sources = {
        "pluggy/__init__.py": b"BOUND_EXECUTED = 'pluggy'\n",
        "coverage/__init__.py": b"import pluggy\nBOUND_EXECUTED = 'coverage'\n",
        "pytest/__init__.py": b"import pluggy\nBOUND_EXECUTED = 'pytest'\n",
        "pytest_cov/__init__.py": b"import coverage, pluggy, pytest\nBOUND_EXECUTED = 'pytest_cov'\n",
        "pytest_cov/plugin.py": b"import pytest_cov\nBOUND_EXECUTED = 'pytest_cov.plugin'\n",
    }
    drift_site = tmp_path / "drift-site"
    drift_site.mkdir()
    _make_distribution(drift_site, required_contents=sources)
    selected = drift_site / "pytest/__init__.py"
    original = bootstrap._stable_read

    def endpoint_swap(path, **kwargs):
        content = original(path, **kwargs)
        if path == selected:
            replacement = path.with_name("replacement.py")
            replacement.write_bytes(content)
            os.replace(replacement, path)
        return content

    monkeypatch.setattr(bootstrap, "_stable_read", endpoint_swap)
    with pytest.raises(bootstrap.BootstrapError):
        capture(
            drift_site,
            canonical_name="runtime-core",
            required_paths=BOUND_PATHS,
        )

    site = tmp_path / "load-site"
    site.mkdir()
    _make_distribution(site, required_contents=sources)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            _CAPTURED_LOADER_PROBE,
            os.fspath(BOOTSTRAP),
            os.fspath(site),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["loaded"] == {name: name for name in BOUND_MODULES}
    for relative in BOUND_PATHS:
        assert document["counts"][os.fspath(site / relative)] == 1


def test_s18_b3f_r1b_lock_package_resolution_is_pep503_unique(tmp_path):
    capture = _future("_capture_lock_package")
    lock = tmp_path / "uv.lock"
    _write_lock(lock, [{"name": "other", "version": "1.0"}])
    with pytest.raises(bootstrap.BootstrapError):
        capture(lock, canonical_name="pytest-cov", required_dependencies=())

    _write_lock(
        lock,
        [
            {"name": "PyTest_Cov", "version": "1.0"},
            {"name": "pytest.cov", "version": "1.0"},
        ],
    )
    with pytest.raises(bootstrap.BootstrapError):
        capture(lock, canonical_name="pytest-cov", required_dependencies=())


def test_s18_b3f_r1b_lock_package_digest_binds_exact_canonical_object(
    tmp_path, monkeypatch
):
    capture = _future("_capture_lock_package")
    lock = tmp_path / "uv.lock"
    raw = _write_lock(
        lock,
        [
            {
                "name": "pytest-cov",
                "version": "1.0",
                "dependencies": ["pytest"],
                "marker": "python_version >= '3.11'",
            }
        ],
    )
    first = capture(lock, canonical_name="pytest-cov", required_dependencies=("pytest",))
    assert frozenset(first) == LOCK_PACKAGE_KEYS
    canonical = json.dumps(
        first["exact_package_object"],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    assert first["canonical_package_bytes"] == canonical
    assert first["lock_package_sha256"] == _sha256(canonical)
    assert first["lock_file_sha256"] == _sha256(raw)

    _write_lock(
        lock,
        [
            {
                "name": "pytest-cov",
                "version": "1.0",
                "dependencies": ["pytest"],
                "marker": "python_version >= '3.12'",
            }
        ],
    )
    second = capture(lock, canonical_name="pytest-cov", required_dependencies=("pytest",))
    assert second["lock_package_sha256"] != first["lock_package_sha256"]

    endpoint_swap_failures = []
    for stage in ("after-stable-read", "during-canonicalization"):
        raw = _write_lock(
            lock,
            [
                {
                    "name": "pytest-cov",
                    "version": "1.0",
                    "dependencies": ["pytest"],
                    "marker": "python_version >= '3.11'",
                }
            ],
        )
        replacement = tmp_path / f"uv.lock.{stage}.replacement"
        replacement.write_bytes(raw)
        original_inode = lock.lstat().st_ino
        replacement_inode = replacement.lstat().st_ino
        assert replacement_inode != original_inode
        swapped = False

        def replace_endpoint(
            replacement_path=replacement,
            expected_inode=replacement_inode,
        ) -> None:
            nonlocal swapped
            assert not swapped
            os.replace(replacement_path, lock)
            swapped = True
            assert lock.lstat().st_ino == expected_inode

        with monkeypatch.context() as context:
            if stage == "after-stable-read":
                original_stable_read = bootstrap._stable_read

                def swapping_stable_read(
                    path,
                    _original_stable_read=original_stable_read,
                    **kwargs,
                ):
                    content = _original_stable_read(path, **kwargs)
                    replace_endpoint()
                    return content

                context.setattr(bootstrap, "_stable_read", swapping_stable_read)
            else:
                original_canonical_json = bootstrap._canonical_json_bytes

                def swapping_canonical_json(
                    value,
                    _original_canonical_json=original_canonical_json,
                ):
                    content = _original_canonical_json(value)
                    replace_endpoint()
                    return content

                context.setattr(
                    bootstrap,
                    "_canonical_json_bytes",
                    swapping_canonical_json,
                )
            try:
                capture(
                    lock,
                    canonical_name="pytest-cov",
                    required_dependencies=("pytest",),
                )
            except bootstrap.BootstrapError:
                pass
            else:
                endpoint_swap_failures.append(stage)
        assert swapped
    assert endpoint_swap_failures == [], (
        "lock capture accepted same-content replacement inode at stages: "
        f"{endpoint_swap_failures}"
    )


def test_s18_b3f_r1b_lock_package_requires_named_dependency_edges(tmp_path):
    capture = _future("_capture_lock_package")
    lock = tmp_path / "uv.lock"
    for dependencies in ([], ["coverage"], ["Py_Test"], ["pytest", "pytest"]):
        _write_lock(
            lock,
            [{"name": "pytest-cov", "version": "1.0", "dependencies": dependencies}],
        )
        with pytest.raises(bootstrap.BootstrapError):
            capture(
                lock,
                canonical_name="pytest-cov",
                required_dependencies=("pytest",),
            )

    _write_lock(
        lock,
        [
            {
                "name": "pytest-cov",
                "version": "1.0",
                "dependencies": ["coverage", "pluggy", "pytest", "typing-extensions"],
            }
        ],
    )
    result = capture(
        lock,
        canonical_name="pytest-cov",
        required_dependencies=("coverage", "pluggy", "pytest"),
    )
    assert result["required_dependencies"] == ("coverage", "pluggy", "pytest")


def test_s18_b3f_r1b_identity_v2_has_exact_shape_and_rejects_unknown_fields(monkeypatch):
    build = _future("_build_runtime_identity_v2")
    inputs = _builder_inputs()

    def forbidden_io(*args, **kwargs):
        raise AssertionError("pure identity builder attempted filesystem I/O")

    monkeypatch.setattr(Path, "open", forbidden_io)
    monkeypatch.setattr(Path, "read_bytes", forbidden_io)
    monkeypatch.setattr(Path, "resolve", forbidden_io)
    monkeypatch.setattr(os, "open", forbidden_io)
    result = build(**inputs)
    assert frozenset(result) == {
        "schema_version",
        "provenance",
        "scope",
        "runtime",
        "uv",
        "uv_lock_sha256",
        "distributions",
        "plugins",
        "semantic_runtime_sha256",
    }
    assert result["schema_version"] == 2
    assert result["provenance"] == "installed-record-consistent"
    assert frozenset(result["runtime"]) == RUNTIME_LAYOUT_KEYS
    assert frozenset(result["uv"]) == {"path", "version", "sha256"}
    assert frozenset(result["distributions"]) == {
        "coverage",
        "pluggy",
        "pytest",
        "pytest-cov",
    }
    for name, value in result["distributions"].items():
        assert frozenset(value) == {"installed", "lock"}
        assert frozenset(value["installed"]) == INSTALLED_DISTRIBUTION_KEYS
        assert frozenset(value["lock"]) == LOCK_PACKAGE_KEYS
        assert value["installed"]["name"] == value["lock"]["name"] == name
        assert value["installed"]["version"] == value["lock"]["version"]
    assert frozenset(result["plugins"]) == {
        "pytest_cov.plugin",
        "scripts.pytest_security_events",
    }
    assert all(frozenset(value) == PLUGIN_KEYS for value in result["plugins"].values())
    encoded = result["runtime"]["pyvenv_cfg_bytes"]
    assert re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", encoded)
    _assert_base64_copy(encoded, inputs["runtime_layout"]["pyvenv_cfg_bytes"])
    for name in ("coverage", "pluggy", "pytest", "pytest-cov"):
        raw_installed = inputs["distributions"][name]["installed"]
        encoded_installed = result["distributions"][name]["installed"]
        _assert_base64_copy(
            encoded_installed["metadata_bytes"], raw_installed["metadata_bytes"]
        )
        _assert_base64_copy(
            encoded_installed["record_bytes"], raw_installed["record_bytes"]
        )
        for path, raw_entry in raw_installed["required_entries"].items():
            _assert_base64_copy(
                encoded_installed["required_entries"][path]["bytes"],
                raw_entry["bytes"],
            )
        _assert_base64_copy(
            result["distributions"][name]["lock"]["canonical_package_bytes"],
            inputs["distributions"][name]["lock"]["canonical_package_bytes"],
        )
    json.dumps(result, ensure_ascii=False, sort_keys=True)

    mutations = []
    unknown = deepcopy(inputs)
    unknown["runtime_layout"]["unknown"] = True
    mutations.append(unknown)
    missing = deepcopy(inputs)
    del missing["distributions"]["pytest"]["installed"]["metadata_sha256"]
    mutations.append(missing)
    wrong_type = deepcopy(inputs)
    wrong_type["scope"]["attempt"] = True
    mutations.append(wrong_type)
    unhashable_scope = deepcopy(inputs)
    unhashable_scope["scope"]["target"] = []
    mutations.append(unhashable_scope)
    missing_cov_init = deepcopy(inputs)
    del missing_cov_init["distributions"]["pytest-cov"]["installed"][
        "required_entries"
    ]["pytest_cov/__init__.py"]
    mutations.append(missing_cov_init)
    rebound = deepcopy(inputs)
    entry = rebound["distributions"]["pytest"]["installed"]["required_entries"][
        "pytest/__init__.py"
    ]
    entry["bytes"] = b"rebound"
    entry["size"] = len(entry["bytes"])
    entry["sha256"] = _sha256(entry["bytes"])
    mutations.append(rebound)
    unknown_entry_leaf = deepcopy(inputs)
    unknown_entry_leaf["distributions"]["pluggy"]["installed"][
        "required_entries"
    ]["pluggy/__init__.py"]["unknown"] = True
    mutations.append(unknown_entry_leaf)
    boolean_record_size = deepcopy(inputs)
    boolean_record_size["distributions"]["pytest"]["installed"]["record_rows"][0][
        "size"
    ] = True
    mutations.append(boolean_record_size)
    mixed_lock = deepcopy(inputs)
    mixed_lock["distributions"]["coverage"]["lock"]["lock_file_sha256"] = "b" * 64
    mutations.append(mixed_lock)
    lock_subset_rebind = deepcopy(inputs)
    lock_subset_rebind["distributions"]["pluggy"]["lock"]["exact_package_object"][
        "marker"
    ] = "python_version >= '3.11'"
    mutations.append(lock_subset_rebind)
    metadata_rebind = deepcopy(inputs)
    metadata = metadata_rebind["distributions"]["coverage"]["installed"]
    metadata["metadata_bytes"] = _metadata("coverage", "2.0")
    metadata["metadata_size"] = len(metadata["metadata_bytes"])
    metadata["metadata_sha256"] = _sha256(metadata["metadata_bytes"])
    mutations.append(metadata_rebind)
    wrong_plugin_entry = deepcopy(inputs)
    wrong_plugin_entry["plugins"]["pytest_cov.plugin"]["entry"] = "pytest_cov/__init__.py"
    mutations.append(wrong_plugin_entry)
    wrong_local_binding = deepcopy(inputs)
    wrong_local_binding["plugins"]["scripts.pytest_security_events"][
        "distribution"
    ] = "pytest-cov"
    mutations.append(wrong_local_binding)
    accepted_root_file_leaves = []
    for field, root_path in (
        ("uv.path", "/"),
        ("uv.path", "//"),
        ("events.file", "/"),
        ("events.file", "//"),
    ):
        root_file_leaf = deepcopy(inputs)
        if field == "uv.path":
            root_file_leaf["uv_identity"]["path"] = root_path
        else:
            root_file_leaf["plugins"]["scripts.pytest_security_events"][
                "file"
            ] = root_path
        try:
            build(**root_file_leaf)
        except bootstrap.BootstrapError:
            pass
        else:
            accepted_root_file_leaves.append((field, root_path))
    assert accepted_root_file_leaves == [], (
        "identity builder accepted root-like file leaves: "
        f"{accepted_root_file_leaves}"
    )
    for mutation in mutations:
        with pytest.raises(bootstrap.BootstrapError):
            build(**mutation)

    root_directories = deepcopy(inputs)
    root_runtime = root_directories["runtime_layout"]
    root_pyvenv = (
        b"home = /\n"
        b"implementation = CPython\n"
        b"version_info = 3.11.4\n"
        b"include-system-site-packages = false\n"
    )
    root_runtime.update(
        {
            "executable": "/bin/python",
            "executable_realpath": "/python3.11",
            "venv_root": "/",
            "base_prefix": "/",
            "site_packages": "/lib/python3.11/site-packages",
            "home": "/",
            "pyvenv_cfg_path": "/pyvenv.cfg",
            "pyvenv_cfg_bytes": root_pyvenv,
            "pyvenv_cfg_size": len(root_pyvenv),
            "pyvenv_cfg_sha256": _sha256(root_pyvenv),
        }
    )
    root_directories["plugins"]["pytest_cov.plugin"][
        "file"
    ] = "/lib/python3.11/site-packages/pytest_cov/plugin.py"
    root_result = build(**root_directories)
    assert root_result["runtime"]["venv_root"] == "/"
    assert root_result["runtime"]["base_prefix"] == "/"
    assert root_result["runtime"]["home"] == "/"

    reordered = deepcopy(inputs)
    reordered["distributions"] = dict(reversed(tuple(reordered["distributions"].items())))
    reordered["plugins"] = dict(reversed(tuple(reordered["plugins"].items())))
    assert build(**reordered) == result


def test_s18_b3f_r1b_semantic_runtime_digest_excludes_only_run_scope():
    build = _future("_build_runtime_identity_v2")
    inputs = _builder_inputs()
    baseline_document = build(**inputs)
    baseline = baseline_document["semantic_runtime_sha256"]
    projection = deepcopy(baseline_document)
    assert projection.pop("semantic_runtime_sha256") == baseline
    projection["scope"] = {"runner": projection["scope"]["runner"]}
    assert baseline == _sha256(_canonical_json(projection))
    for key, value in (
        ("run_id", "run-002"),
        ("target", "retention"),
        ("attempt", 2),
        ("timestamp", "2026-09-08T00:00:00Z"),
    ):
        changed = deepcopy(inputs)
        changed["scope"][key] = value
        assert build(**changed)["semantic_runtime_sha256"] == baseline

    runner_changed = deepcopy(inputs)
    runner_changed["scope"]["runner"] = "linux"
    with pytest.raises(bootstrap.BootstrapError):
        build(**runner_changed)

    platform_changed = deepcopy(runner_changed)
    platform_changed["runtime_layout"]["system"] = "Linux"
    platform_changed["runtime_layout"]["machine"] = "x86_64"
    assert build(**platform_changed)["semantic_runtime_sha256"] != baseline

    runtime_changed = deepcopy(inputs)
    runtime_changed["runtime_layout"]["machine"] = "x86_64"
    assert build(**runtime_changed)["semantic_runtime_sha256"] != baseline

    uv_changed = deepcopy(inputs)
    uv_changed["uv_identity"]["version"] = "0.8.16"
    assert build(**uv_changed)["semantic_runtime_sha256"] != baseline

    lock_changed = deepcopy(inputs)
    lock = lock_changed["distributions"]["pytest"]["lock"]
    lock["exact_package_object"]["marker"] = "python_version >= '3.11'"
    canonical = json.dumps(
        lock["exact_package_object"],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    lock["canonical_package_bytes"] = canonical
    lock["lock_package_sha256"] = _sha256(canonical)
    assert build(**lock_changed)["semantic_runtime_sha256"] != baseline

    assert build(**_builder_inputs(seed=b"other"))["semantic_runtime_sha256"] != baseline
    assert "semantic_runtime_sha256" not in json.dumps(
        {key: value for key, value in build(**inputs).items() if key != "semantic_runtime_sha256"},
        sort_keys=True,
    )
