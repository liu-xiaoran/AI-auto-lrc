#!/usr/bin/env python3
"""Observe the canonical container and execute its frozen golden test suite."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

CANONICAL_SELECTORS = (
    "tests/golden/test_legacy_v1_feature_golden.py",
    "tests/golden/test_legacy_v1_numeric_golden.py",
    "tests/golden/test_legacy_v1_public_e2e_golden.py",
)


def _network_observation() -> dict[str, object]:
    probe = socket.socket()
    probe.settimeout(3)
    try:
        result = probe.connect_ex(("1.1.1.1", 443))
    finally:
        probe.close()
    return {
        "policy": "denied",
        "probe": "connect_ex",
        "blocked": result != 0,
        "result_code": result,
    }


def _root_filesystem_observation() -> dict[str, object]:
    target = Path("/workspace") / f".canonical-write-probe-{uuid.uuid4().hex}"
    blocked = False
    error_number = 0
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        blocked = error.errno == errno.EROFS
        error_number = error.errno or 0
    else:
        os.close(descriptor)
        target.unlink(missing_ok=True)
    return {
        "policy": "read-only",
        "probe": "create",
        "blocked": blocked,
        "errno": error_number,
    }


def _tmpfs_observation() -> dict[str, object]:
    descriptor, raw_path = tempfile.mkstemp(prefix="canonical-tmpfs-", dir="/tmp")
    try:
        os.write(descriptor, b"tmpfs probe\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
        Path(raw_path).unlink(missing_ok=True)
    return {
        "path": "/tmp",
        "writable": True,
        "options": "rw,noexec,nosuid,size=64m",
    }


def _installed_observation() -> dict[str, object]:
    program = r'''
import hashlib
import importlib.metadata
import json
import pathlib
import platform
import sysconfig

import t2l
import torch

distribution = importlib.metadata.distribution("ai-auto-lrc")
entry_points = {
    entry.name: entry.value
    for entry in distribution.entry_points
    if entry.group == "console_scripts"
}
purelib = pathlib.Path(sysconfig.get_path("purelib")).resolve()
package = pathlib.Path(t2l.__file__).resolve()
assert package.is_relative_to(purelib), (package, purelib)
content = package.read_bytes()
print(json.dumps({
    "scope": {
        "os": platform.system().lower(),
        "arch": platform.machine(),
        "platform": sysconfig.get_platform(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "device": "cpu",
    },
    "installation": {
        "distribution_name": distribution.metadata["Name"],
        "distribution_version": distribution.version,
        "console_entry_point": entry_points.get("ai-auto-lrc"),
        "origin_scope": "site-packages",
        "installed_package": {
            "name": package.relative_to(purelib).as_posix(),
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    },
    "runtime": {
        "cuda_available": torch.cuda.is_available(),
        "torch_cuda_version": torch.version.cuda,
        "torch_intraop_threads": torch.get_num_threads(),
    },
}))
'''
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-I", "-c", program],
        cwd="/tmp",
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0 or result.stderr:
        raise RuntimeError("isolated installed package observation failed")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("isolated installed package observation was invalid")
    return value


def _junit_summary(content: bytes) -> dict[str, int]:
    root = ET.fromstring(content)
    cases = root.findall(".//testcase")
    return {
        "tests": len(cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
        "failures_or_errors": sum(
            case.find("failure") is not None or case.find("error") is not None
            for case in cases
        ),
    }


def _write_observation(path: Path, value: object) -> None:
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def observe_and_run(*, output: Path, junit: Path, run_id: str) -> int:
    installed = _installed_observation()
    network = _network_observation()
    root_filesystem = _root_filesystem_observation()
    tmpfs = _tmpfs_observation()
    environment = os.environ.copy()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *CANONICAL_SELECTORS,
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit}",
        ],
        cwd="/workspace",
        env=environment,
        check=False,
        capture_output=True,
        timeout=1200,
    )
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    junit_content = junit.read_bytes()
    summary = _junit_summary(junit_content)
    observation = {
        "schema": "ai-auto-lrc/canonical-container-observation",
        "schema_version": 1,
        "run_id": run_id,
        "scope": installed["scope"],
        "runtime": {
            "network": network,
            "root_filesystem": root_filesystem,
            "tmpfs": tmpfs,
            **installed["runtime"],
            "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
            "mkl_num_threads": os.environ.get("MKL_NUM_THREADS"),
            "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
            "harness_import_scope": "workspace-source-snapshot",
        },
        "installation": installed["installation"],
        "execution": {
            "command_id": "canonical-golden-verify-v1",
            "selectors": list(CANONICAL_SELECTORS),
            "pytest_exit_code": result.returncode,
            "input_junit_sha256": hashlib.sha256(junit_content).hexdigest(),
            **summary,
        },
    }
    _write_observation(output, observation)
    return result.returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    return observe_and_run(
        output=arguments.output,
        junit=arguments.junit,
        run_id=arguments.run_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
