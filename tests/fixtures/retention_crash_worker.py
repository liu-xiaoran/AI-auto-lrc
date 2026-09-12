#!/usr/bin/env python3
"""Subprocess-only crash checkpoint worker for retention contract tests."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if os.fspath(_ROOT) not in sys.path:
    sys.path.insert(0, os.fspath(_ROOT))

manager = importlib.import_module("scripts.manage_evidence_retention")


PHASES = (
    "before-start",
    "lock-held",
    "staging-fsynced",
    "inspection-fsynced",
    "event-renamed",
    "events-fsynced",
    "run-fsynced",
    "teardown-entered",
)


class _Checkpoint:
    def __init__(self, phase: str, ready_fd: int, release_fd: int) -> None:
        self.phase = phase
        self.ready_fd = ready_fd
        self.release_fd = release_fd
        self.triggered = False

    def reach(self, phase: str) -> None:
        if self.triggered or phase != self.phase:
            return
        self.triggered = True
        token = f"{phase}\n".encode("ascii")
        offset = 0
        while offset < len(token):
            offset += os.write(self.ready_fd, token[offset:])
        while True:
            try:
                os.read(self.release_fd, 1)
                return
            except InterruptedError:
                continue


def _install_crash_wrappers(
    *,
    receipt: Path,
    checkpoint: _Checkpoint,
) -> None:
    run_control = receipt.parent.parent / ".control" / receipt.parent.name
    inspections = run_control / "inspections"
    events = run_control / "events"
    original_open_lock = manager._open_lock
    original_fsync_dir = manager._fsync_dir
    original_rename_noreplace = manager._rename_noreplace
    original_flock = manager.fcntl.flock
    lock_fd: int | None = None
    inspection_renamed = False

    def open_lock(path: Path) -> int:
        nonlocal lock_fd
        lock_fd = original_open_lock(path)
        checkpoint.reach("lock-held")
        return lock_fd

    def fsync_dir(path: Path) -> None:
        original_fsync_dir(path)
        if path.parent == inspections and path.name.startswith(".incomplete-"):
            checkpoint.reach("staging-fsynced")
        elif path == inspections and inspection_renamed:
            checkpoint.reach("inspection-fsynced")
        elif path == events:
            checkpoint.reach("events-fsynced")
        elif path == run_control:
            checkpoint.reach("run-fsynced")

    def rename_noreplace(source: Path, destination: Path) -> None:
        nonlocal inspection_renamed
        original_rename_noreplace(source, destination)
        if destination.parent == inspections:
            inspection_renamed = True
        elif destination.parent == events:
            checkpoint.reach("event-renamed")

    def flock(descriptor: int, operation: int) -> None:
        if descriptor == lock_fd and operation == manager.fcntl.LOCK_UN:
            checkpoint.reach("teardown-entered")
        original_flock(descriptor, operation)

    manager._open_lock = open_lock
    manager._fsync_dir = fsync_dir
    manager._rename_noreplace = rename_noreplace
    manager.fcntl.flock = flock


def _classify(receipt: Path) -> int:
    _control_root, _run_control, inspections, events = manager._control_paths(
        receipt,
        receipt.parent.name,
    )
    state = manager._ledger_state(
        receipt=receipt,
        inspections=inspections,
        events=events,
        rules_path=manager.DEFAULT_RULES,
        assessment_path=manager.DEFAULT_ASSESSMENT,
        expected_rules_sha256=manager.DEFAULT_RULES_SHA256,
        expected_assessment_sha256=manager.DEFAULT_ASSESSMENT_SHA256,
        mode="archived-integrity",
        repo_root=None,
    )
    print(json.dumps({"state": state}, separators=(",", ":"), sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("inspect", "classify"), required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--actor")
    parser.add_argument("--phase", choices=PHASES)
    parser.add_argument("--ready-fd", type=int)
    parser.add_argument("--release-fd", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    receipt = arguments.receipt.absolute()
    if arguments.mode == "classify":
        return _classify(receipt)
    if arguments.phase is None:
        return 0
    if arguments.actor is None:
        parser.error("--actor is required for inspect mode")
    if arguments.ready_fd is None or arguments.release_fd is None:
        parser.error("--ready-fd and --release-fd are required with --phase")
    checkpoint = _Checkpoint(
        arguments.phase,
        arguments.ready_fd,
        arguments.release_fd,
    )
    if arguments.phase == "before-start":
        checkpoint.reach("before-start")
    else:
        _install_crash_wrappers(receipt=receipt, checkpoint=checkpoint)
    return manager.main(
        [
            "inspect",
            "--receipt",
            os.fspath(receipt),
            "--actor",
            arguments.actor,
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
