"""Explicit macOS R3 system baseline, outside the portable contract layer."""

from __future__ import annotations

import json
import sys

import pytest
from security_runtime_r3_baseline import _prepare_baseline, run_baseline

pytestmark = [
    pytest.mark.system,
    pytest.mark.skipif(sys.platform != "darwin", reason="R3 baseline requires macOS sandbox"),
]


def test_s18_b3f_r3_isolation_accepts_long_socket_paths(tmp_path):
    root = tmp_path.resolve() / ("long-evidence-" + "x" * 80)
    root.mkdir()
    assert len(str(root / "tmpdir/probe.sock").encode()) > 108
    _, _, observed, _, _ = _prepare_baseline(root)
    assert observed == {
        "network_denied": True,
        "writes_denied": [True, True, True],
        "local_socket_bound": True,
        "ip_bind_denied": True,
    }


def test_s18_b3f_r3_real_dual_lane_binds_one_runtime(tmp_path):
    result = run_baseline(tmp_path.resolve())
    assert result["network_denied"] is True
    assert result["ip_bind_denied"] is True
    assert result["local_socket_bound"] is True
    assert result["checkout_write_denied"] is True
    assert result["before"] == result["after"]
    assert result["returncode"] == 0, result["evidence_root"]
    semantic_hashes = set()
    for target in ("capture", "retention"):
        directory = tmp_path.resolve() / "attempt" / target

        def read(name, directory=directory):
            return json.loads((directory / name).read_text())

        gate = read("gate.json")
        assert gate["schema_version"] == 5
        assert gate["passed"] is True
        assert gate["failures"] == []
        assert gate["runtime_identity"]["status"] == "valid"
        identity = read("plugin-identity.json")
        environment = read("environment.json")
        manifest = read("run-manifest.json")
        command = read("command.json")
        events = read("pytest-events.json")
        assert identity["schema_version"] == 2
        assert environment["schema_version"] == manifest["schema_version"] == 5
        assert command["schema_version"] == 4
        assert events["schema_version"] == 3
        semantic = identity["semantic_runtime_sha256"]
        assert environment["runtime_identity"]["semantic_runtime_sha256"] == semantic
        assert manifest["semantic_runtime_sha256"] == semantic
        assert gate["runtime_identity"]["semantic_runtime_sha256"] == semantic
        semantic_hashes.add(semantic)
        assert identity["scope"]["timestamp"] == command["started_at"]
        for name in (
            "coverage.json",
            "junit.xml",
            "stdout.log",
            "stderr.log",
            "verifier.stderr.log",
        ):
            assert (directory / name).is_file(), name
        assert (directory / f".coverage-{target}").is_file()
    assert len(semantic_hashes) == 1
