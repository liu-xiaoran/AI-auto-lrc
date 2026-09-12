"""Run the unchanged R3 baseline under OS network and checkout write denial.

This harness never installs dependencies, changes the runner, or supplies fake
pytest artifacts. Raw evidence is retained even when the baseline fails.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "packaging/security-coverage-policy.toml",
    "packaging/security-coverage-manifest.json",
    "packaging/evidence-secret-rules.json",
    "packaging/evidence-retention-assessment.json",
    "scripts/run_security_coverage.sh",
    "scripts/security_pytest_bootstrap.py",
    "scripts/verify_security_coverage.py",
    "scripts/pytest_security_events.py",
    "scripts/capture_test_gate.py",
    "scripts/manage_evidence_retention.py",
    "tests/contract/test_evidence_capture.py",
    "tests/contract/test_evidence_retention.py",
    "tests/fixtures/retention_crash_worker.py",
    "tests/system/security_runtime_r3_baseline.py",
    "tests/system/test_security_runtime_identity_r3.py",
)


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _snapshot(uv: Path) -> dict[str, object]:
    files = [ROOT / name for name in INPUTS]
    files.extend(sorted((ROOT / ".venv").rglob("*")))
    files.extend((uv, Path(sys.executable).resolve()))
    result = {}
    for path in files:
        metadata = path.lstat()
        result[str(path)] = {
            "inode": metadata.st_ino,
            "device": metadata.st_dev,
            "mode": metadata.st_mode,
            "size": metadata.st_size,
            "mtime_ns": metadata.st_mtime_ns,
            "sha256": _sha(path) if path.is_file() and not path.is_symlink() else None,
            "link": os.readlink(path) if path.is_symlink() else None,
        }
    return result


def _execute(argv, *, root, environment, name, timeout):
    (root / f"{name}.argv.json").write_text(json.dumps(argv, indent=2) + "\n")
    with (
        (root / f"{name}.stdout").open("wb") as stdout,
        (root / f"{name}.stderr").open("wb") as stderr,
    ):
        process = subprocess.Popen(
            argv,
            cwd=ROOT,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        timed_out = False
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            returncode = process.wait()
        except BaseException:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            returncode = process.wait()
            (root / f"{name}.exit.json").write_text(
                json.dumps({"returncode": returncode, "interrupted": True}) + "\n"
            )
            raise
    (root / f"{name}.exit.json").write_text(
        json.dumps({"returncode": returncode, "timed_out": timed_out}) + "\n"
    )
    return returncode


def _prepare_baseline(root: Path):
    if root != root.resolve() or root.is_relative_to(ROOT):
        raise ValueError("R3 evidence must be outside the checkout at a canonical path")
    uv_name = shutil.which("uv")
    if uv_name is None:
        raise RuntimeError("R3 requires the installed uv executable")
    uv = Path(uv_name).resolve(strict=True)
    profile = root / "isolation.sb"
    protected = (ROOT, Path(sys.base_prefix).resolve(), uv)
    profile.write_text(
        "(version 1)\n(allow default)\n(deny network*)\n"
        + f"(allow network-bind (subpath {json.dumps(str(root))}))\n"
        + "\n".join(f"(deny file-write* (subpath {json.dumps(str(path))}))" for path in protected)
        + "\n"
    )
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "UV_PROJECT_ENVIRONMENT",
        "UV_PYTHON",
        "COVERAGE_FILE",
    ):
        environment.pop(name, None)
    for name in ("HOME", "UV_CACHE_DIR", "XDG_CACHE_HOME", "TMPDIR", "PIP_CACHE_DIR"):
        directory = root / name.lower()
        directory.mkdir()
        environment[name] = str(directory)
    environment.update(
        {
            "UV_OFFLINE": "1",
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_NO_CACHE": "1",
            "PIP_NO_INDEX": "1",
            "PIP_CONFIG_FILE": os.devnull,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
    )
    prefix = ["/usr/bin/sandbox-exec", "-f", str(profile)]
    probe = (
        "import errno,json,os,socket,sys; "
        "s=socket.socket(); n=s.connect_ex(('127.0.0.1',9)); s.close(); "
        "denied=[]\n"
        "for path in sys.argv[1:]:\n"
        " try:\n"
        "  fd=os.open(path,os.O_WRONLY); os.close(fd); denied.append(False)\n"
        " except OSError as e: denied.append(e.errno in (errno.EPERM,errno.EACCES))\n"
        "os.chdir(os.environ['TMPDIR'])\n"
        "u=socket.socket(socket.AF_UNIX); u.bind('probe.sock'); u.close()\n"
        "b=socket.socket(); bind_denied=False\n"
        "try: b.bind(('127.0.0.1',0))\n"
        "except OSError as e: bind_denied=e.errno in (errno.EPERM,errno.EACCES)\n"
        "finally: b.close()\n"
        "print(json.dumps({'network_denied':n in (errno.EPERM,errno.EACCES),"
        "'writes_denied':denied,'local_socket_bound':True,'ip_bind_denied':bind_denied}))\n"
    )
    before = _snapshot(uv)
    (root / "before.json").write_text(json.dumps(before, sort_keys=True, indent=2))
    probe_status = _execute(
        [
            *prefix,
            str(ROOT / ".venv/bin/python"),
            "-I",
            "-S",
            "-B",
            "-c",
            probe,
            str(ROOT / "pyproject.toml"),
            str(ROOT / ".venv/pyvenv.cfg"),
            str(uv),
        ],
        root=root,
        environment=environment,
        name="isolation-probe",
        timeout=15,
    )
    if probe_status != 0:
        raise RuntimeError(f"OS isolation probe failed; evidence: {root}")
    observed = json.loads((root / "isolation-probe.stdout").read_text())
    if (
        not observed["network_denied"]
        or not observed["ip_bind_denied"]
        or observed["writes_denied"] != [True] * 3
    ):
        raise RuntimeError(f"OS isolation was not established; evidence: {root}")
    return prefix, environment, observed, uv, profile


def run_baseline(root: Path) -> dict[str, object]:
    prefix, environment, observed, uv, profile = _prepare_baseline(root)
    argv = [
        *prefix,
        str(ROOT / "scripts/run_security_coverage.sh"),
        str(root / "attempt"),
        "s18-r3-baseline",
        "1",
    ]
    status = _execute(argv, root=root, environment=environment, name="runner", timeout=240)
    after = _snapshot(uv)
    (root / "after.json").write_text(json.dumps(after, sort_keys=True, indent=2))
    result = {
        "returncode": status,
        "network_denied": observed["network_denied"],
        "checkout_write_denied": all(observed["writes_denied"]),
        "before": _sha(root / "before.json"),
        "after": _sha(root / "after.json"),
        "local_socket_bound": observed["local_socket_bound"],
        "ip_bind_denied": observed["ip_bind_denied"],
        "profile_sha256": _sha(profile),
        "evidence_root": str(root),
        "private_directories": {
            name: environment[name]
            for name in (
                "HOME",
                "UV_CACHE_DIR",
                "XDG_CACHE_HOME",
                "TMPDIR",
                "PIP_CACHE_DIR",
            )
        },
    }
    (root / "receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2))
    print(f"R3_EVIDENCE_ROOT={root}")
    return result
