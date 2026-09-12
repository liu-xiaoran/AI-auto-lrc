#!/usr/bin/env python3
"""Run one local test gate and seal capture-bound diagnostic evidence."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import platform
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "ai-auto-lrc/capture-receipt"
SCHEMA_VERSION = 1
CAPTURE_ERROR_EXIT = 70
SOURCE_OBSERVATION_LIMIT = (
    "before-and-after identity; transient restored changes may be unobserved"
)
PRIVATE_DIRECTORY_MODE = 0o500
PRIVATE_FILE_MODE = 0o400
MAX_RECEIPT_CLOSURE_ENTRIES = 10_000
CLOSURE_ENTRY_METADATA_OVERHEAD = 128
MAX_RECEIPT_CLOSURE_METADATA_BYTES = 8 * 1024 * 1024
MAX_RECEIPT_CLOSURE_BYTES = 512 * 1024 * 1024
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LAYERS = ("portable", "package", "canonical")
ARTIFACT_CLOSURES = {
    "portable": (
        "coverage-gate.json",
        "coverage.json",
        "portable-gate.json",
        "portable.xml",
    ),
    "package": (
        "package-gate.json",
        "package-platform.json",
        "package.xml",
        "wheelhouse-manifest.json",
    ),
    "canonical": (
        "canonical-Dockerfile",
        "canonical-feature-oracle.json",
        "canonical-fixture-metadata.json",
        "canonical-gate.json",
        "canonical-numeric-oracle.json",
        "canonical-observer.py",
        "canonical-producer.py",
        "canonical-profile-manifest.json",
        "canonical-public-e2e-oracle.json",
        "canonical-runner.sh",
        "canonical-runtime.json",
        "canonical.xml",
    ),
}
COMMAND_IDS = {
    "portable": "run-test-gate-portable-v1",
    "package": "run-test-gate-package-v1",
    "canonical": "run-test-gate-canonical-v1",
}
SELECTORS = {
    "portable": ("tests/unit", "tests/contract", "tests/component"),
    "package": ("tests/package",),
    "canonical": (
        "tests/golden/test_legacy_v1_feature_golden.py",
        "tests/golden/test_legacy_v1_numeric_golden.py",
        "tests/golden/test_legacy_v1_public_e2e_golden.py",
    ),
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[0-9A-Za-z._-]{1,128}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
REPO_DIGEST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$")
PYTHON_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9.+-]*)?$")
PACKAGE_IMPORTS = (
    "audioread",
    "chardet",
    "cyrtranslit",
    "fasttext",
    "g2p_en",
    "julius",
    "kroman",
    "librosa",
    "nltk",
    "numpy",
    "pykakasi",
    "pypinyin",
    "soundfile",
    "t2l",
    "torch",
    "torchaudio",
)
CANONICAL_ORACLES = {
    "feature": (
        "canonical-feature-oracle.json",
        "legacy-v1-feature-linux-x86_64-cpython310",
        "feature-only",
    ),
    "numeric": (
        "canonical-numeric-oracle.json",
        "legacy-v1-numeric-linux-x86_64-cpython310",
        "checkpoint-numeric-and-rendering",
    ),
    "public-e2e": (
        "canonical-public-e2e-oracle.json",
        "legacy-v1-real-mp3-public-api-installed-cli-linux-x86_64-cpython310",
        "real-decoder-public-api-installed-cli",
    ),
}
CANONICAL_CHECKPOINTS = ("BDR", "Baseline", "MTL")
CANONICAL_PROVENANCE_SCOPE = "canonical-functional-not-release"
ORACLE_PROVENANCE_SCOPE = "canonical functional evidence; not clean release provenance"
JUNIT_PREFIXES = {
    "portable": ("tests.unit.", "tests.contract.", "tests.component."),
    "package": ("tests.package.",),
    "canonical": ("tests.golden.",),
}


class CaptureError(RuntimeError):
    """Raised when a capture or receipt is unsafe or malformed."""


@dataclass(frozen=True, slots=True)
class CaptureResult:
    exit_code: int
    run_directory: Path | None
    sealed: bool


@dataclass(slots=True)
class _ReceiptClosureState:
    files: set[str]
    entry_count: int = 0
    metadata_bytes: int = 0


def _walk_receipt_closure(
    directory_fd: int,
    prefix: PurePosixPath | None,
    *,
    state: _ReceiptClosureState,
    max_entries: int,
    max_metadata_bytes: int,
    entry_metadata_overhead: int,
    directory_flags: Callable[[], int],
    validate_directory: Callable[[os.stat_result, str | None], None],
    validate_file: Callable[[os.stat_result, str], None],
) -> None:
    """Enumerate one pinned sealed directory without resolving mutable paths."""

    try:
        before = os.fstat(directory_fd)
        validate_directory(before, None if prefix is None else prefix.as_posix())
        stats_by_name: dict[str, os.stat_result] = {}
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                relative = (
                    PurePosixPath(entry.name)
                    if prefix is None
                    else prefix / entry.name
                )
                state.entry_count += 1
                if state.entry_count > max_entries:
                    raise CaptureError("sealed run closure entry limit exceeded")
                state.metadata_bytes += entry_metadata_overhead + len(
                    os.fsencode(relative.as_posix())
                )
                if state.metadata_bytes > max_metadata_bytes:
                    raise CaptureError("sealed run closure metadata limit exceeded")
                stats_by_name[entry.name] = entry.stat(follow_symlinks=False)
        names_before = sorted(stats_by_name)
        for name in names_before:
            relative = PurePosixPath(name) if prefix is None else prefix / name
            entry_stat = stats_by_name[name]
            if stat.S_ISLNK(entry_stat.st_mode):
                raise CaptureError(
                    f"sealed run contains a symlink: {relative.as_posix()}"
                )
            if stat.S_ISREG(entry_stat.st_mode):
                validate_file(entry_stat, relative.as_posix())
                state.files.add(relative.as_posix())
                continue
            if not stat.S_ISDIR(entry_stat.st_mode):
                raise CaptureError(
                    f"sealed run contains a special file: {relative.as_posix()}"
                )
            child_fd = os.open(
                name,
                directory_flags(),
                dir_fd=directory_fd,
            )
            try:
                opened = os.fstat(child_fd)
                if _identity(opened) != _identity(entry_stat):
                    raise CaptureError("sealed run changed during closure traversal")
                validate_directory(opened, relative.as_posix())
                _walk_receipt_closure(
                    child_fd,
                    relative,
                    state=state,
                    max_entries=max_entries,
                    max_metadata_bytes=max_metadata_bytes,
                    entry_metadata_overhead=entry_metadata_overhead,
                    directory_flags=directory_flags,
                    validate_directory=validate_directory,
                    validate_file=validate_file,
                )
                current = os.stat(
                    name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if _identity(current) != _identity(opened):
                    raise CaptureError("sealed run changed during closure traversal")
                validate_directory(current, relative.as_posix())
            finally:
                os.close(child_fd)
        after = os.fstat(directory_fd)
        names_after: list[str] = []
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                names_after.append(entry.name)
                if len(names_after) > len(names_before):
                    raise CaptureError("sealed run changed during closure traversal")
        if _identity(after) != _identity(before) or sorted(names_after) != names_before:
            raise CaptureError("sealed run changed during closure traversal")
        validate_directory(after, None if prefix is None else prefix.as_posix())
    except CaptureError:
        raise
    except OSError as error:
        raise CaptureError("sealed run closure could not be read safely") from error


class _DirFdReceiptIO:
    """Read and enumerate one sealed run relative to an already-open directory."""

    def __init__(self, run_fd: int) -> None:
        try:
            self._root_fd = os.dup(run_fd)
        except OSError as error:
            raise CaptureError("run_fd is not a valid open directory") from error
        try:
            root_stat = os.fstat(self._root_fd)
            if not stat.S_ISDIR(root_stat.st_mode):
                raise CaptureError("run_fd must refer to a directory")
            if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
                raise CaptureError("directory-relative safe verification is unsupported")
            self._validate_directory(root_stat, None)
            self.root_stat = root_stat
            self._bytes_read = 0
        except BaseException:
            os.close(self._root_fd)
            raise

    def __enter__(self) -> _DirFdReceiptIO:
        return self

    def __exit__(self, *_exc: object) -> None:
        os.close(self._root_fd)

    @staticmethod
    def _directory_flags() -> int:
        return (
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )

    @staticmethod
    def _validate_directory(value: os.stat_result, relative: str | None) -> None:
        field = "sealed run root" if relative is None else "sealed run directory"
        suffix = "" if relative is None else f": {relative}"
        if value.st_uid != os.geteuid():
            raise CaptureError(f"{field} owner is invalid{suffix}")
        if stat.S_IMODE(value.st_mode) != PRIVATE_DIRECTORY_MODE:
            raise CaptureError(f"{field} must use mode 0500{suffix}")

    @staticmethod
    def _validate_file(value: os.stat_result, field: str) -> None:
        if value.st_uid != os.geteuid():
            raise CaptureError(f"{field} owner is invalid")
        if stat.S_IMODE(value.st_mode) != PRIVATE_FILE_MODE:
            raise CaptureError(f"{field} must use mode 0400")
        if value.st_nlink != 1:
            raise CaptureError(f"{field} must have link count 1")

    def _open_parent(self, relative: PurePosixPath, field: str) -> tuple[int, str]:
        descriptor = os.dup(self._root_fd)
        try:
            for index, part in enumerate(relative.parts[:-1]):
                before = os.stat(
                    part,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
                parent_relative = PurePosixPath(*relative.parts[: index + 1])
                if stat.S_ISDIR(before.st_mode):
                    self._validate_directory(before, parent_relative.as_posix())
                child: int | None = None
                try:
                    child = os.open(part, self._directory_flags(), dir_fd=descriptor)
                    opened = os.fstat(child)
                except OSError:
                    if child is not None:
                        with suppress(OSError):
                            os.close(child)
                    raise
                if not stat.S_ISDIR(opened.st_mode):
                    os.close(child)
                    raise CaptureError(f"{field} parent changed during verification")
                try:
                    self._validate_directory(opened, parent_relative.as_posix())
                except CaptureError:
                    os.close(child)
                    raise
                if _identity(opened) != _identity(before):
                    os.close(child)
                    raise CaptureError(f"{field} parent changed during verification")
                os.close(descriptor)
                descriptor = child
            return descriptor, relative.parts[-1]
        except (FileNotFoundError, NotADirectoryError) as error:
            os.close(descriptor)
            raise CaptureError(f"{field} is missing") from error
        except OSError as error:
            os.close(descriptor)
            raise CaptureError(f"{field} could not be opened safely") from error
        except BaseException:
            os.close(descriptor)
            raise

    def read(self, value: object, field: str) -> bytes:
        relative = _canonical_relative(value, f"{field}.path")
        parent_fd, name = self._open_parent(relative, field)
        descriptor: int | None = None
        try:
            flags = (
                os.O_RDONLY
                | os.O_NOFOLLOW
                | os.O_NONBLOCK
                | getattr(os, "O_CLOEXEC", 0)
            )
            descriptor = os.open(name, flags, dir_fd=parent_fd)
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise CaptureError(f"{field} must be a regular non-symlink file")
            self._validate_file(before, field)
            chunks: list[bytes] = []
            while True:
                remaining = MAX_RECEIPT_CLOSURE_BYTES - self._bytes_read
                chunk = os.read(descriptor, min(1024 * 1024, max(1, remaining + 1)))
                if not chunk:
                    break
                if self._bytes_read + len(chunk) > MAX_RECEIPT_CLOSURE_BYTES:
                    raise CaptureError("sealed run closure byte limit exceeded")
                self._bytes_read += len(chunk)
                chunks.append(chunk)
            after = os.fstat(descriptor)
            try:
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError as error:
                raise CaptureError(f"{field} changed during verification") from error
            self._validate_file(after, field)
            self._validate_file(current, field)
            if any(_identity(item) != _identity(before) for item in (after, current)):
                raise CaptureError(f"{field} changed during verification")
            content = b"".join(chunks)
            if len(content) != before.st_size:
                raise CaptureError(f"{field} changed size during verification")
            return content
        except FileNotFoundError as error:
            raise CaptureError(f"{field} is missing") from error
        except CaptureError:
            raise
        except OSError as error:
            raise CaptureError(f"{field} could not be opened safely") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent_fd)

    def file_closure(self) -> set[str]:
        state = _ReceiptClosureState(files=set())
        _walk_receipt_closure(
            self._root_fd,
            None,
            state=state,
            max_entries=MAX_RECEIPT_CLOSURE_ENTRIES,
            max_metadata_bytes=MAX_RECEIPT_CLOSURE_METADATA_BYTES,
            entry_metadata_overhead=CLOSURE_ENTRY_METADATA_OVERHEAD,
            directory_flags=self._directory_flags,
            validate_directory=self._validate_directory,
            validate_file=self._validate_file,
        )
        return state.files


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the stable SHA-256 of one regular file."""

    return _sha256(_read_stable_regular(path, "file"))


def _write_exclusive(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_stable_regular(path: Path, field: str) -> bytes:
    try:
        before = path.lstat()
    except FileNotFoundError as error:
        raise CaptureError(f"{field} is missing") from error
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise CaptureError(f"{field} must be a regular non-symlink file")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CaptureError(f"{field} could not be opened safely") from error
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _identity(opened) != _identity(before):
            raise CaptureError(f"{field} changed before capture")
        content = stream.read()
        after = os.fstat(stream.fileno())
    try:
        current = path.lstat()
    except FileNotFoundError as error:
        raise CaptureError(f"{field} changed during capture") from error
    if any(_identity(value) != _identity(before) for value in (opened, after, current)):
        raise CaptureError(f"{field} changed during capture")
    if len(content) != before.st_size:
        raise CaptureError(f"{field} changed size during capture")
    return content


def _record(root: Path, path: Path, field: str) -> dict[str, object]:
    content = _read_stable_regular(path, field)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as error:
        raise CaptureError(f"{field} must be inside the run directory") from error
    return {
        "path": relative,
        "sha256": _sha256(content),
        "size": len(content),
    }


def _canonical_relative(value: object, field: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise CaptureError(f"{field} must be a canonical relative path")
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise CaptureError(f"{field} must be a canonical relative path")
    return path


def _safe_run_file(root: Path, value: object, field: str) -> Path:
    relative = _canonical_relative(value, f"{field}.path")
    current = root
    for index, part in enumerate(relative.parts):
        current /= part
        try:
            item_stat = current.lstat()
        except FileNotFoundError as error:
            raise CaptureError(f"{field} is missing") from error
        if stat.S_ISLNK(item_stat.st_mode):
            raise CaptureError(f"{field} must not use a symlink")
        if index < len(relative.parts) - 1:
            if not stat.S_ISDIR(item_stat.st_mode):
                raise CaptureError(f"{field} parent must be a directory")
        elif not stat.S_ISREG(item_stat.st_mode):
            raise CaptureError(f"{field} must be a regular file")
    return current


def _verify_record(
    root: Path,
    value: object,
    field: str,
    *,
    read_file: Callable[[Path, str], bytes] | None = None,
) -> bytes:
    if not isinstance(value, dict):
        raise CaptureError(f"{field} must be a file record")
    if set(value) != {"path", "sha256", "size"}:
        raise CaptureError(f"{field} must contain path, sha256, and size")
    if not isinstance(value["sha256"], str) or SHA256.fullmatch(value["sha256"]) is None:
        raise CaptureError(f"{field}.sha256 must be lowercase SHA-256")
    if (
        not isinstance(value["size"], int)
        or isinstance(value["size"], bool)
        or value["size"] < 0
    ):
        raise CaptureError(f"{field}.size must be a non-negative integer")
    relative = _canonical_relative(value["path"], f"{field}.path")
    path = root.joinpath(*relative.parts)
    if read_file is None:
        path = _safe_run_file(root, value["path"], field)
        content = _read_stable_regular(path, field)
    else:
        content = read_file(path, field)
    if len(content) != value["size"]:
        raise CaptureError(f"{field} size mismatch")
    if _sha256(content) != value["sha256"]:
        raise CaptureError(f"{field} hash mismatch")
    return content


def _git(
    repo_root: Path,
    *arguments: str,
    pass_fds: tuple[int, ...] = (),
) -> bytes:
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "LANG": "C"})
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *arguments],
        cwd=repo_root,
        check=False,
        capture_output=True,
        env=environment,
        pass_fds=pass_fds,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise CaptureError(message or f"git {' '.join(arguments)} failed")
    return result.stdout


def _source_material(
    repo_root: Path,
    *,
    repo_root_fd: int | None = None,
) -> tuple[dict[str, Any], bytes, bytes, list[tuple[str, bytes]]]:
    pass_fds = () if repo_root_fd is None else (repo_root_fd,)
    head = _git(repo_root, "rev-parse", "HEAD", pass_fds=pass_fds).decode(
        "ascii"
    ).strip()
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise CaptureError("source.head must be a 40-character commit")
    patch = _git(
        repo_root,
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-color",
        "HEAD",
        "--",
        pass_fds=pass_fds,
    )
    status_bytes = _git(
        repo_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        pass_fds=pass_fds,
    )
    untracked_bytes = _git(
        repo_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        pass_fds=pass_fds,
    )
    ledger: list[dict[str, object]] = []
    snapshots: list[tuple[str, bytes]] = []
    safe = True
    for raw_path in sorted(item for item in untracked_bytes.split(b"\0") if item):
        relative_text = os.fsdecode(raw_path)
        relative = _canonical_relative(relative_text, "source.untracked.path")
        path = repo_root.joinpath(*relative.parts)
        path_stat = path.lstat()
        entry: dict[str, object] = {
            "path": relative.as_posix(),
            "mode": stat.S_IMODE(path_stat.st_mode),
        }
        if stat.S_ISREG(path_stat.st_mode):
            content = _read_stable_regular(path, f"source.untracked[{relative.as_posix()}]")
            entry.update(
                kind="regular",
                size=len(content),
                sha256=_sha256(content),
            )
            snapshots.append((relative.as_posix(), content))
        elif stat.S_ISLNK(path_stat.st_mode):
            before = _identity(path_stat)
            target = os.readlink(os.fsencode(path))
            if _identity(path.lstat()) != before:
                raise CaptureError("source untracked symlink changed during capture")
            entry.update(
                kind="symlink",
                size=len(target),
                target_base64=base64.b64encode(target).decode("ascii"),
                sha256=_sha256(target),
            )
        else:
            entry.update(kind="special", size=path_stat.st_size, sha256=None)
            safe = False
        ledger.append(entry)
    recorded_paths = {entry["path"] for entry in ledger}
    special_entries: list[dict[str, object]] = []
    for directory, directory_names, file_names in os.walk(repo_root, followlinks=False):
        directory_path = Path(directory)
        if directory_path == repo_root:
            directory_names[:] = [name for name in directory_names if name != ".git"]
        for name in (*directory_names, *file_names):
            candidate = directory_path / name
            candidate_stat = candidate.lstat()
            if stat.S_ISREG(candidate_stat.st_mode) or stat.S_ISDIR(
                candidate_stat.st_mode
            ) or stat.S_ISLNK(candidate_stat.st_mode):
                continue
            relative = candidate.relative_to(repo_root).as_posix()
            if relative in recorded_paths:
                continue
            special_entries.append(
                {
                    "path": relative,
                    "mode": stat.S_IMODE(candidate_stat.st_mode),
                    "kind": "special",
                    "size": candidate_stat.st_size,
                    "sha256": None,
                }
            )
            safe = False
    ledger.extend(special_entries)
    ledger.sort(key=lambda entry: str(entry["path"]))
    identity_basis = {
        "head": head,
        "patch_sha256": _sha256(patch),
        "status_sha256": _sha256(status_bytes),
        "untracked": ledger,
        "safe": safe,
    }
    aggregate = hashlib.sha256(b"ai-auto-lrc/source-snapshot/v1\0")
    encoded_basis = json.dumps(
        identity_basis,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    aggregate.update(len(encoded_basis).to_bytes(8, "big"))
    aggregate.update(encoded_basis)
    summary = {
        **identity_basis,
        "aggregate_sha256": aggregate.hexdigest(),
        "dirty": bool(status_bytes),
    }
    return summary, patch, status_bytes, snapshots


def _capture_source(repo_root: Path, run_root: Path, phase: str) -> tuple[dict[str, Any], dict[str, object]]:
    summary, patch, status_bytes, snapshots = _source_material(repo_root)
    source_root = run_root / "source"
    _write_exclusive(source_root / f"{phase}.patch", patch)
    _write_exclusive(source_root / f"{phase}-status.bin", status_bytes)
    for relative, content in snapshots:
        _write_exclusive(source_root / phase / "untracked" / relative, content)
    summary["captured_at_utc"] = _utc_now()
    summary["patch"] = _record(run_root, source_root / f"{phase}.patch", "source.patch")
    summary["status"] = _record(
        run_root,
        source_root / f"{phase}-status.bin",
        "source.status",
    )
    summary_path = source_root / f"{phase}.json"
    _write_exclusive(summary_path, _json_bytes(summary))
    return summary, _record(run_root, summary_path, f"source.{phase}")


def _assert_no_symlink_components(path: Path, field: str) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if not current.exists() and not current.is_symlink():
            raise CaptureError(f"{field} does not exist")
        if current.is_symlink():
            raise CaptureError(f"{field} must not use a symlink")


def _preflight(repo_root: Path, retention_root: Path, layer: str) -> tuple[Path, Path]:
    if layer not in LAYERS:
        raise CaptureError(f"unknown layer: {layer!r}")
    _assert_no_symlink_components(repo_root, "repo_root")
    _assert_no_symlink_components(retention_root, "retention_root")
    repository = repo_root.resolve(strict=True)
    retention = retention_root.resolve(strict=True)
    if not repository.is_dir() or not retention.is_dir():
        raise CaptureError("repo_root and retention_root must be directories")
    if retention == repository or retention.is_relative_to(repository):
        raise CaptureError("retention_root must be outside repository")
    runner = repository / "scripts/run_test_gate.sh"
    _read_stable_regular(runner, "runner")
    return repository, retention


def _new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{uuid.uuid4().hex}"


def _normalize_returncode(raw_returncode: int | None) -> tuple[int, int | None]:
    if raw_returncode is None:
        return CAPTURE_ERROR_EXIT, None
    if raw_returncode < 0:
        caught_signal = -raw_returncode
        return 128 + caught_signal, caught_signal
    return raw_returncode, None


def _run_gate_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    stdout: Any,
    stderr: Any,
) -> tuple[int, int | None]:
    """Run a gate in its own process group and forward handled terminal signals."""

    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
    forwarded_signal: int | None = None
    previous_handlers: dict[int, Any] = {}

    def forward(signum: int, _frame: object) -> None:
        nonlocal forwarded_signal
        forwarded_signal = signum
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signum)

    install_handlers = threading.current_thread() is threading.main_thread()
    if install_handlers:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, forward)
    try:
        return process.wait(), forwarded_signal
    finally:
        if install_handlers:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)


def _snapshot_artifacts(
    run_root: Path,
    artifact_root: Path,
    layer: str,
) -> tuple[dict[str, dict[str, object]], list[str], list[str]]:
    required = set(ARTIFACT_CLOSURES[layer])
    if artifact_root.exists() and not artifact_root.is_dir():
        return {}, sorted(required), ["ARTIFACT_LAYER_MISMATCH"]
    actual = {
        path.relative_to(artifact_root).as_posix()
        for path in artifact_root.rglob("*")
        if path.is_file() or path.is_symlink()
    } if artifact_root.is_dir() else set()
    missing = sorted(required - actual)
    unknown = sorted(actual - required)
    reasons: list[str] = []
    if missing:
        reasons.append("REQUIRED_ARTIFACT_MISSING")
    if unknown:
        reasons.append("ARTIFACT_LAYER_MISMATCH")
    records: dict[str, dict[str, object]] = {}
    for name in sorted(required & actual):
        try:
            records[name] = _record(
                run_root,
                artifact_root / name,
                f"artifacts.{name}",
            )
        except (CaptureError, OSError):
            reasons.append("ARTIFACT_CHANGED_DURING_CAPTURE")
    return records, missing, sorted(set(reasons))


def _portable_binding_reasons(
    artifact_root: Path,
    *,
    run_id: str,
    policy_sha256: str | None,
    base_ref: str,
    read_file: Callable[[Path, str], bytes] = _read_stable_regular,
) -> list[str]:
    """Cross-check the minimal same-run portable evidence bindings."""

    if policy_sha256 is None:
        return ["POLICY_HASH_MISMATCH"]
    try:
        junit_content = read_file(artifact_root / "portable.xml", "portable.junit")
        junit_root = ET.fromstring(junit_content)
        cases = junit_root.findall(".//testcase")
        if not cases:
            return ["JUNIT_INVALID_OR_EMPTY"]
        if any(
            not (case.get("classname") or "").startswith(JUNIT_PREFIXES["portable"])
            for case in cases
        ):
            return ["ARTIFACT_LAYER_MISMATCH"]
        skipped = sum(case.find("skipped") is not None for case in cases)
        failed = sum(case.find("failure") is not None for case in cases)
        errors = sum(case.find("error") is not None for case in cases)
        passed = len(cases) - skipped - failed - errors
        gate = json.loads(
            read_file(
                artifact_root / "portable-gate.json",
                "portable.gate_json",
            )
        )
        coverage_content = read_file(
            artifact_root / "coverage.json",
            "portable.coverage",
        )
        coverage = json.loads(coverage_content)
        coverage_gate = json.loads(
            read_file(
                artifact_root / "coverage-gate.json",
                "portable.coverage_gate",
            )
        )
    except (CaptureError, ET.ParseError, UnicodeDecodeError, json.JSONDecodeError):
        return ["JUNIT_INVALID_OR_EMPTY"]

    reasons: list[str] = []
    expected_gate = {
        "schema_version": 1,
        "gate": "pytest-layer",
        "layer": "portable",
        "passed": failed == errors == skipped == 0,
        "tests": len(cases),
        "skipped": skipped,
        "failures_or_errors": failed + errors,
        "run_id": run_id,
        "input_junit_sha256": _sha256(junit_content),
        "policy_sha256": policy_sha256,
    }
    for key, expected in expected_gate.items():
        if not isinstance(gate, dict) or gate.get(key) != expected:
            reasons.append("RUN_ARTIFACT_BINDING_INVALID")
            break
    expected_coverage_gate = {
        "schema_version": 1,
        "gate": "coverage",
        "passed": True,
        "run_id": run_id,
        "input_coverage_sha256": _sha256(coverage_content),
        "policy_sha256": policy_sha256,
        "base_ref": base_ref,
    }
    for key, expected in expected_coverage_gate.items():
        if not isinstance(coverage_gate, dict) or coverage_gate.get(key) != expected:
            reasons.append("RUN_ARTIFACT_BINDING_INVALID")
            break
    if (
        not isinstance(coverage, dict)
        or not isinstance(coverage.get("meta"), dict)
        or coverage["meta"].get("branch_coverage") is not True
    ):
        reasons.append("RUN_ARTIFACT_BINDING_INVALID")
    if failed or errors:
        reasons.append("JUNIT_FAILURE_OR_ERROR")
    if skipped:
        reasons.append("REQUIRED_TEST_SKIPPED")
    if not gate.get("passed") or not coverage_gate.get("passed"):
        reasons.append("RUN_ARTIFACT_BINDING_INVALID")
    if passed < 1:
        reasons.append("JUNIT_INVALID_OR_EMPTY")
    return sorted(set(reasons))


def _strict_json_object(content: bytes, field: str) -> dict[str, Any]:
    """Decode one JSON object while rejecting duplicate object keys."""

    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CaptureError(f"{field} contains a duplicate field")
            result[key] = value
        return result

    try:
        value = json.loads(content, object_pairs_hook=strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureError(f"{field} must be valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise CaptureError(f"{field} must be an object")
    return value


def _exact_object(
    value: object,
    keys: set[str],
    field: str,
    *,
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CaptureError(f"{field} must be an object")
    optional = optional or set()
    if not keys <= set(value) or not set(value) <= keys | optional:
        raise CaptureError(f"{field} has an invalid shape")
    return value


def _package_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CaptureError(f"{field} must be lowercase SHA-256")
    return value


def _package_integer(
    value: object,
    field: str,
    *,
    minimum: int = 0,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise CaptureError(f"{field} must be an integer")
    return value


def _package_artifact_record(value: object, field: str) -> dict[str, Any]:
    record = _exact_object(value, {"name", "size", "sha256"}, field)
    name = record["name"]
    if not isinstance(name, str):
        raise CaptureError(f"{field}.name must be a basename")
    path = _canonical_relative(name, f"{field}.name")
    if len(path.parts) != 1 or path.name != name:
        raise CaptureError(f"{field}.name must be a basename")
    _package_integer(record["size"], f"{field}.size", minimum=1)
    _package_sha256(record["sha256"], f"{field}.sha256")
    return record


def _package_path_record(value: object, field: str) -> dict[str, Any]:
    record = _exact_object(value, {"name", "size", "sha256"}, field)
    _canonical_relative(record["name"], f"{field}.name")
    _package_integer(record["size"], f"{field}.size", minimum=1)
    _package_sha256(record["sha256"], f"{field}.sha256")
    return record


def _manifest_record(value: object, field: str) -> dict[str, Any]:
    record = _exact_object(value, {"path", "size", "sha256"}, field)
    _canonical_relative(record["path"], f"{field}.path")
    _package_integer(record["size"], f"{field}.size", minimum=1)
    _package_sha256(record["sha256"], f"{field}.sha256")
    return record


def _wheel_tags_from_name(name: str, field: str) -> list[str]:
    if not name.endswith(".whl"):
        raise CaptureError(f"{field} must be a wheel")
    parts = name[:-4].rsplit("-", 3)
    if len(parts) != 4 or not parts[0]:
        raise CaptureError(f"{field} has an invalid wheel filename")
    python_tags, abi_tags, platform_tags = parts[1:]
    components = [part.split(".") for part in (python_tags, abi_tags, platform_tags)]
    if any(
        not values
        or any(re.fullmatch(r"[A-Za-z0-9_]+", value) is None for value in values)
        for values in components
    ):
        raise CaptureError(f"{field} has an invalid wheel filename")
    return sorted(
        f"{python_tag}-{abi_tag}-{platform_tag}"
        for python_tag in components[0]
        for abi_tag in components[1]
        for platform_tag in components[2]
    )


def _package_tag_is_compatible(tag: str, python_version: str) -> bool:
    match = re.fullmatch(
        r"(?P<python>[A-Za-z0-9_]+)-(?P<abi>[A-Za-z0-9_]+)-(?P<platform>[A-Za-z0-9_]+)",
        tag,
    )
    if match is None:
        return False
    major_text, minor_text, *_rest = python_version.split(".")
    major = int(major_text)
    minor = int(minor_text)
    interpreter = match.group("python")
    abi = match.group("abi")
    wheel_platform = match.group("platform")
    pure_python = interpreter in {f"py{major}", f"py{major}{minor}"} and abi == "none"
    current_cpython = interpreter == f"cp{major}{minor}" and abi in {
        "abi3",
        "none",
        f"cp{major}{minor}",
    }
    older_abi3 = (
        interpreter.startswith(f"cp{major}")
        and interpreter[len(f"cp{major}") :].isdigit()
        and int(interpreter[len(f"cp{major}") :]) <= minor
        and abi == "abi3"
    )
    if not (pure_python or current_cpython or older_abi3):
        return False
    return wheel_platform == "any" or (
        wheel_platform.endswith("_x86_64")
        and wheel_platform.startswith(("linux", "manylinux", "musllinux"))
    )


def _package_tag_array(
    value: object,
    field: str,
    *,
    expected: list[str],
    python_version: str,
) -> None:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(tag, str) for tag in value)
        or value != sorted(set(value))
        or value != expected
    ):
        raise CaptureError(f"{field} must be sorted, unique, and scope-compatible")
    if not any(_package_tag_is_compatible(tag, python_version) for tag in value):
        raise CaptureError(f"{field} must include a scope-compatible tag")


def _package_manifest_summary(
    manifest: dict[str, Any],
    *,
    scope: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], str]:
    allowed_top = {
        "schema_version",
        "generated_at",
        "target",
        "inputs",
        "approved_sdists",
        "files",
    }
    if not {"schema_version", "target", "files"} <= set(manifest) or not set(
        manifest
    ) <= allowed_top:
        raise CaptureError("package.manifest has an invalid shape")
    if manifest["schema_version"] != 1:
        raise CaptureError("package.manifest schema_version 1 is required")
    target = manifest["target"]
    if not isinstance(target, dict):
        raise CaptureError("package.manifest.target must be an object")
    expected_target = {
        "implementation": scope["python_implementation"],
        "python_version": scope["python_version"],
        "machine": scope["arch"],
        "platform": scope["platform"],
    }
    if any(target.get(key) != expected for key, expected in expected_target.items()):
        raise CaptureError("package.manifest.target does not match scope")
    files = _exact_object(
        manifest["files"],
        {"requirements", "runtime", "build_system", "artifacts"},
        "package.manifest.files",
    )
    flattened: list[dict[str, Any]] = []
    normalized: dict[str, list[dict[str, Any]]] = {}
    all_paths: list[str] = []
    for group in ("requirements", "runtime", "build_system", "artifacts"):
        records = files[group]
        if not isinstance(records, list):
            raise CaptureError(f"package.manifest.files.{group} must be an array")
        checked = [
            _manifest_record(record, f"package.manifest.files.{group}[{index}]")
            for index, record in enumerate(records)
        ]
        paths = [record["path"] for record in checked]
        if paths != sorted(set(paths)):
            raise CaptureError(f"package.manifest.files.{group} must be sorted and unique")
        normalized[group] = checked
        all_paths.extend(paths)
        flattened.extend({"group": group, **record} for record in checked)
    if len(all_paths) != len(set(all_paths)):
        raise CaptureError("package.manifest paths must be unique")
    flattened.sort(key=lambda record: (record["group"], record["path"]))
    aggregate_bytes = json.dumps(
        flattened,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return normalized, _sha256(aggregate_bytes)


def _validate_package_sidecar(
    sidecar: dict[str, Any],
    manifest: dict[str, Any],
    manifest_bytes: bytes,
    *,
    run_id: str,
) -> None:
    sidecar = _exact_object(
        sidecar,
        {
            "schema",
            "schema_version",
            "run_id",
            "layer",
            "scope",
            "image",
            "network",
            "wheelhouse",
            "build",
            "installation",
            "cli",
        },
        "package.sidecar",
    )
    if (
        sidecar["schema"] != "ai-auto-lrc/package-platform"
        or sidecar["schema_version"] != 1
        or sidecar["run_id"] != run_id
        or sidecar["layer"] != "package"
    ):
        raise CaptureError("package.sidecar identity is invalid")
    scope = _exact_object(
        sidecar["scope"],
        {"os", "arch", "python_implementation", "python_version", "platform"},
        "package.sidecar.scope",
    )
    if (
        scope["os"] != "linux"
        or scope["arch"] != "x86_64"
        or scope["python_implementation"] != "CPython"
        or scope["platform"] != "linux-x86_64"
        or not isinstance(scope["python_version"], str)
        or PYTHON_VERSION.fullmatch(scope["python_version"]) is None
    ):
        raise CaptureError("package.sidecar.scope must be Linux x86_64 CPython")

    image = _exact_object(
        sidecar["image"],
        {"image_id", "repo_digest"},
        "package.sidecar.image",
        optional={"display_tag"},
    )
    if not isinstance(image["image_id"], str) or IMAGE_ID.fullmatch(image["image_id"]) is None:
        raise CaptureError("package.sidecar.image.image_id is invalid")
    if (
        not isinstance(image["repo_digest"], str)
        or REPO_DIGEST.fullmatch(image["repo_digest"]) is None
    ):
        raise CaptureError("package.sidecar.image.repo_digest is invalid")
    if "display_tag" in image and (
        not isinstance(image["display_tag"], str)
        or not image["display_tag"]
        or any(ord(character) < 32 for character in image["display_tag"])
    ):
        raise CaptureError("package.sidecar.image.display_tag is invalid")

    network = _exact_object(
        sidecar["network"],
        {"policy", "probe", "blocked", "result_code"},
        "package.sidecar.network",
    )
    if (
        network["policy"] != "denied"
        or network["probe"] != "connect_ex"
        or network["blocked"] is not True
        or _package_integer(
            network["result_code"],
            "package.sidecar.network.result_code",
            minimum=1,
        )
        < 1
    ):
        raise CaptureError("package.sidecar.network does not prove denial")

    wheelhouse = _exact_object(
        sidecar["wheelhouse"],
        {
            "manifest_path",
            "manifest_sha256",
            "runtime_wheel_count",
            "build_wheel_count",
            "artifact_count",
            "aggregate_sha256",
        },
        "package.sidecar.wheelhouse",
    )
    if wheelhouse["manifest_path"] != "wheelhouse-manifest.json":
        raise CaptureError("package.sidecar.wheelhouse.manifest_path is invalid")
    _package_sha256(wheelhouse["manifest_sha256"], "package.sidecar.wheelhouse.manifest_sha256")
    _package_sha256(wheelhouse["aggregate_sha256"], "package.sidecar.wheelhouse.aggregate_sha256")
    manifest_files, aggregate_sha256 = _package_manifest_summary(manifest, scope=scope)
    expected_wheelhouse = {
        "manifest_path": "wheelhouse-manifest.json",
        "manifest_sha256": _sha256(manifest_bytes),
        "runtime_wheel_count": len(manifest_files["runtime"]),
        "build_wheel_count": len(manifest_files["build_system"]),
        "artifact_count": len(manifest_files["artifacts"]),
        "aggregate_sha256": aggregate_sha256,
    }
    if wheelhouse != expected_wheelhouse:
        raise CaptureError("package.sidecar.wheelhouse does not match manifest copy")

    build = _exact_object(
        sidecar["build"],
        {
            "source",
            "sdist",
            "project_wheel",
            "runtime_wheel_tags",
            "build_wheel_tags",
            "project_wheel_tags",
        },
        "package.sidecar.build",
    )
    if build["source"] != "sdist" or len(manifest_files["artifacts"]) != 1:
        raise CaptureError("package.sidecar.build must use the unique manifest sdist")
    sdist = _package_artifact_record(build["sdist"], "package.sidecar.build.sdist")
    manifest_sdist = manifest_files["artifacts"][0]
    if sdist != {
        "name": PurePosixPath(manifest_sdist["path"]).name,
        "size": manifest_sdist["size"],
        "sha256": manifest_sdist["sha256"],
    }:
        raise CaptureError("package.sidecar.build.sdist does not match manifest")
    project_wheel = _package_artifact_record(
        build["project_wheel"],
        "package.sidecar.build.project_wheel",
    )
    runtime_tag_groups = [
        _wheel_tags_from_name(
                PurePosixPath(record["path"]).name,
                "package.manifest runtime wheel",
            )
        for record in manifest_files["runtime"]
    ]
    build_tag_groups = [
        _wheel_tags_from_name(
                PurePosixPath(record["path"]).name,
                "package.manifest build wheel",
            )
        for record in manifest_files["build_system"]
    ]
    project_tags = _wheel_tags_from_name(
        project_wheel["name"],
        "package.sidecar.build.project_wheel.name",
    )
    if any(
        not any(
            _package_tag_is_compatible(tag, scope["python_version"])
            for tag in tags
        )
        for tags in (*runtime_tag_groups, *build_tag_groups, project_tags)
    ):
        raise CaptureError("package wheel is incompatible with declared scope")
    runtime_tags = sorted({tag for tags in runtime_tag_groups for tag in tags})
    build_tags = sorted({tag for tags in build_tag_groups for tag in tags})
    _package_tag_array(
        build["runtime_wheel_tags"],
        "package.sidecar.build.runtime_wheel_tags",
        expected=runtime_tags,
        python_version=scope["python_version"],
    )
    _package_tag_array(
        build["build_wheel_tags"],
        "package.sidecar.build.build_wheel_tags",
        expected=build_tags,
        python_version=scope["python_version"],
    )
    _package_tag_array(
        build["project_wheel_tags"],
        "package.sidecar.build.project_wheel_tags",
        expected=project_tags,
        python_version=scope["python_version"],
    )

    installation = _exact_object(
        sidecar["installation"],
        {
            "pip_check_exit_code",
            "pip_check_stdout_sha256",
            "pip_check_stderr_sha256",
            "pth_before",
            "pth_after",
            "direct_imports",
            "installed_package_origin_scope",
            "installed_package",
        },
        "package.sidecar.installation",
    )
    if installation["pip_check_exit_code"] != 0:
        raise CaptureError("package.sidecar.installation pip check failed")
    _package_sha256(
        installation["pip_check_stdout_sha256"],
        "package.sidecar.installation.pip_check_stdout_sha256",
    )
    _package_sha256(
        installation["pip_check_stderr_sha256"],
        "package.sidecar.installation.pip_check_stderr_sha256",
    )

    def pth_snapshot(value: object, field: str) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise CaptureError(f"{field} must be an array")
        records = [
            _package_path_record(record, f"{field}[{index}]")
            for index, record in enumerate(value)
        ]
        names = [record["name"] for record in records]
        if names != sorted(set(names)) or any(
            not record["name"].endswith(".pth")
            or "site-packages" not in PurePosixPath(record["name"]).parts
            for record in records
        ):
            raise CaptureError(f"{field} must be a sorted internal .pth snapshot")
        return records

    pth_before = pth_snapshot(
        installation["pth_before"],
        "package.sidecar.installation.pth_before",
    )
    pth_after = pth_snapshot(
        installation["pth_after"],
        "package.sidecar.installation.pth_after",
    )
    if pth_before != pth_after:
        raise CaptureError("package.sidecar.installation .pth snapshot changed")
    direct_imports = installation["direct_imports"]
    if direct_imports != list(PACKAGE_IMPORTS):
        raise CaptureError("package.sidecar.installation direct import set is invalid")
    if installation["installed_package_origin_scope"] != "site-packages":
        raise CaptureError("package.sidecar.installation origin is invalid")
    installed_package = _package_path_record(
        installation["installed_package"],
        "package.sidecar.installation.installed_package",
    )
    installed_path = PurePosixPath(installed_package["name"])
    if len(installed_path.parts) < 2 or installed_path.parts[0] != "t2l":
        raise CaptureError("package.sidecar.installation package path is invalid")

    cli = _exact_object(
        sidecar["cli"],
        {
            "command_id",
            "exit_code",
            "stdout_sha256",
            "stderr_sha256",
            "expected_stdout_sha256",
        },
        "package.sidecar.cli",
    )
    if cli["command_id"] != "installed-public-e2e-v1" or cli["exit_code"] != 0:
        raise CaptureError("package.sidecar.cli execution is invalid")
    stdout_sha256 = _package_sha256(cli["stdout_sha256"], "package.sidecar.cli.stdout_sha256")
    _package_sha256(cli["stderr_sha256"], "package.sidecar.cli.stderr_sha256")
    expected_stdout_sha256 = _package_sha256(
        cli["expected_stdout_sha256"],
        "package.sidecar.cli.expected_stdout_sha256",
    )
    if stdout_sha256 != expected_stdout_sha256:
        raise CaptureError("package.sidecar.cli stdout does not match expectation")


def _package_binding_reasons(
    artifact_root: Path,
    *,
    run_id: str,
    policy_sha256: str | None,
    read_file: Callable[[Path, str], bytes] = _read_stable_regular,
) -> list[str]:
    """Independently validate the final package evidence closure."""

    if policy_sha256 is None:
        return ["POLICY_HASH_MISMATCH"]
    try:
        junit_content = read_file(artifact_root / "package.xml", "package.junit")
        junit_root = ET.fromstring(junit_content)
        cases = junit_root.findall(".//testcase")
    except (CaptureError, ET.ParseError):
        return ["JUNIT_INVALID_OR_EMPTY"]
    if not cases:
        return ["JUNIT_INVALID_OR_EMPTY"]
    if any(
        not (case.get("classname") or "").startswith(JUNIT_PREFIXES["package"])
        for case in cases
    ):
        return ["ARTIFACT_LAYER_MISMATCH"]
    skipped = sum(case.find("skipped") is not None for case in cases)
    failed = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    reasons: list[str] = []
    if failed or errors:
        reasons.append("JUNIT_FAILURE_OR_ERROR")
    if skipped:
        reasons.append("REQUIRED_TEST_SKIPPED")
    try:
        gate = _strict_json_object(
            read_file(artifact_root / "package-gate.json", "package.gate_json"),
            "package.gate_json",
        )
        sidecar = _strict_json_object(
            read_file(
                artifact_root / "package-platform.json",
                "package.sidecar",
            ),
            "package.sidecar",
        )
        manifest_bytes = read_file(
            artifact_root / "wheelhouse-manifest.json",
            "package.manifest",
        )
        manifest = _strict_json_object(manifest_bytes, "package.manifest")
        expected_gate_core = {
            "schema_version": 1,
            "gate": "pytest-layer",
            "layer": "package",
            "passed": failed == errors == skipped == 0,
            "tests": len(cases),
            "skipped": skipped,
            "failures_or_errors": failed + errors,
            "run_id": run_id,
            "input_junit_sha256": _sha256(junit_content),
            "policy_sha256": policy_sha256,
        }
        core_matches = all(
            gate.get(key) == expected
            for key, expected in expected_gate_core.items()
        )
        standard_diagnostics_match = (
            gate.get("required_markers") == ["package"]
            and gate.get("outside_layer") == []
            and gate.get("failures") == []
        )
        if (
            not core_matches
            or not standard_diagnostics_match
            or gate.get("passed") is not True
        ):
            raise CaptureError("package gate does not match JUnit, run, and policy")
        _validate_package_sidecar(
            sidecar,
            manifest,
            manifest_bytes,
            run_id=run_id,
        )
    except (CaptureError, KeyError, TypeError, ValueError):
        reasons.append("RUN_ARTIFACT_BINDING_INVALID")
    return sorted(set(reasons))


def _canonical_record_matches(
    value: object,
    *,
    expected_name: str,
    content: bytes,
    field: str,
) -> dict[str, Any]:
    record = _package_path_record(value, field)
    if record != {
        "name": expected_name,
        "size": len(content),
        "sha256": _sha256(content),
    }:
        raise CaptureError(f"{field} does not match its formal copy")
    return record


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _canonical_oracle_records(
    sidecar_oracles: object,
    oracle_contents: dict[str, bytes],
    *,
    profile_sha256: str,
    fixture_sha256: str,
    uv_lock_sha256: str,
    base_repo_digest: str,
    checkpoints: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(sidecar_oracles, list):
        raise CaptureError("canonical.inputs.oracles must be an array")
    records: list[dict[str, Any]] = []
    documents: dict[str, dict[str, Any]] = {}
    for index, raw_record in enumerate(sidecar_oracles):
        field = f"canonical.inputs.oracles[{index}]"
        record = _exact_object(
            raw_record,
            {"role", "name", "size", "sha256", "oracle_id", "status", "scope"},
            field,
        )
        role = record["role"]
        if role not in CANONICAL_ORACLES:
            raise CaptureError(f"{field}.role is invalid")
        name, oracle_id, oracle_scope = CANONICAL_ORACLES[role]
        content = oracle_contents[role]
        base_record = _canonical_record_matches(
            {
                "name": record["name"],
                "size": record["size"],
                "sha256": record["sha256"],
            },
            expected_name=name,
            content=content,
            field=field,
        )
        expected = {
            "role": role,
            **base_record,
            "oracle_id": oracle_id,
            "status": "canonical",
            "scope": oracle_scope,
        }
        if record != expected:
            raise CaptureError(f"{field} identity is invalid")
        document = _strict_json_object(content, f"canonical oracle {role}")
        if (
            document.get("schema_version") != 1
            or document.get("oracle_id") != oracle_id
            or document.get("status") != "canonical"
            or document.get("scope") != oracle_scope
        ):
            raise CaptureError(f"canonical oracle {role} identity is invalid")
        environment = document.get("environment")
        if not isinstance(environment, dict) or any(
            environment.get(key) != expected_value
            for key, expected_value in {
                "base_image": base_repo_digest,
                "system": "Linux",
                "machine": "x86_64",
            }.items()
        ):
            raise CaptureError(f"canonical oracle {role} environment is invalid")
        python_version = environment.get("python_version")
        if not isinstance(python_version, str) or not python_version.startswith("3.10."):
            raise CaptureError(f"canonical oracle {role} Python is invalid")
        provenance = document.get("provenance")
        if (
            not isinstance(provenance, dict)
            or provenance.get("profile_manifest_sha256") != profile_sha256
            or provenance.get("uv_lock_sha256") != uv_lock_sha256
        ):
            raise CaptureError(f"canonical oracle {role} provenance is invalid")
        if role in {"numeric", "public-e2e"} and provenance.get(
            "provenance_scope"
        ) != ORACLE_PROVENANCE_SCOPE:
            raise CaptureError(f"canonical oracle {role} provenance scope is invalid")
        documents[role] = document
        records.append(expected)
    roles = [record["role"] for record in records]
    if roles != sorted(CANONICAL_ORACLES):
        raise CaptureError("canonical.inputs.oracles must have exact sorted roles")
    if documents["numeric"]["provenance"].get("feature_oracle_sha256") != _sha256(
        oracle_contents["feature"]
    ):
        raise CaptureError("numeric oracle does not bind feature oracle")
    if documents["public-e2e"]["provenance"].get(
        "fixture_metadata_sha256"
    ) != fixture_sha256:
        raise CaptureError("public-e2e oracle does not bind fixture metadata")
    expected_checkpoint_hashes = {
        role: checkpoints[role]["sha256"] for role in CANONICAL_CHECKPOINTS
    }
    for role in ("numeric", "public-e2e"):
        routes = documents[role].get("routes")
        if not isinstance(routes, dict) or set(routes) != {
            "Baseline",
            "Baseline_BDR",
            "MTL",
            "MTL_BDR",
        }:
            raise CaptureError(f"canonical oracle {role} routes are invalid")
        for route_name, route in routes.items():
            if not isinstance(route, dict):
                raise CaptureError(f"canonical oracle {role} route is invalid")
            checkpoint_role = "MTL" if route_name.startswith("MTL") else "Baseline"
            expected_boundary = (
                expected_checkpoint_hashes["BDR"] if route_name.endswith("_BDR") else None
            )
            if (
                route.get("checkpoint_sha256")
                != expected_checkpoint_hashes[checkpoint_role]
                or route.get("boundary_checkpoint_sha256") != expected_boundary
            ):
                raise CaptureError(f"canonical oracle {role} checkpoint binding is invalid")
    return records


def _validate_canonical_sidecar(
    sidecar: dict[str, Any],
    artifacts: dict[str, bytes],
    *,
    run_id: str,
    policy_sha256: str,
    source_sha256: str,
    uv_lock_sha256: str,
    junit_sha256: str,
    tests: int,
) -> None:
    sidecar = _exact_object(
        sidecar,
        {
            "schema",
            "schema_version",
            "run_id",
            "layer",
            "scope",
            "image",
            "inputs",
            "runtime",
            "installation",
            "execution",
            "provenance",
        },
        "canonical.sidecar",
    )
    if (
        sidecar["schema"] != "ai-auto-lrc/canonical-runtime"
        or sidecar["schema_version"] != 1
        or sidecar["run_id"] != run_id
        or sidecar["layer"] != "canonical"
    ):
        raise CaptureError("canonical.sidecar identity is invalid")
    scope = _exact_object(
        sidecar["scope"],
        {"os", "arch", "platform", "python_implementation", "python_version", "device"},
        "canonical.scope",
    )
    if (
        scope["os"] != "linux"
        or scope["arch"] != "x86_64"
        or scope["platform"] != "linux-x86_64"
        or scope["python_implementation"] != "CPython"
        or scope["device"] != "cpu"
        or not isinstance(scope["python_version"], str)
        or re.fullmatch(r"3\.10\.[0-9]+", scope["python_version"]) is None
    ):
        raise CaptureError("canonical.scope is invalid")

    image = _exact_object(sidecar["image"], {"base", "build"}, "canonical.image")
    base = _exact_object(image["base"], {"repo_digest", "image_id"}, "canonical.image.base")
    if (
        not isinstance(base["repo_digest"], str)
        or REPO_DIGEST.fullmatch(base["repo_digest"]) is None
        or not isinstance(base["image_id"], str)
        or IMAGE_ID.fullmatch(base["image_id"]) is None
    ):
        raise CaptureError("canonical.image.base is invalid")
    build = _exact_object(
        image["build"],
        {"image_id", "run_id", "source_sha256", "input_aggregate_sha256"},
        "canonical.image.build",
        optional={"display_tag"},
    )
    if (
        not isinstance(build["image_id"], str)
        or IMAGE_ID.fullmatch(build["image_id"]) is None
        or build["run_id"] != run_id
        or build["source_sha256"] != source_sha256
    ):
        raise CaptureError("canonical.image.build is invalid")
    if "display_tag" in build and (
        not isinstance(build["display_tag"], str) or not build["display_tag"]
    ):
        raise CaptureError("canonical.image.build.display_tag is invalid")

    inputs = _exact_object(
        sidecar["inputs"],
        {
            "dockerfile",
            "oracles",
            "profile_manifest",
            "fixture_metadata",
            "checkpoints",
            "uv_lock_sha256",
            "oracle_aggregate_sha256",
            "input_aggregate_sha256",
        },
        "canonical.inputs",
    )
    dockerfile_record = _canonical_record_matches(
        inputs["dockerfile"],
        expected_name="canonical-Dockerfile",
        content=artifacts["canonical-Dockerfile"],
        field="canonical.inputs.dockerfile",
    )
    try:
        dockerfile_text = artifacts["canonical-Dockerfile"].decode("utf-8")
    except UnicodeDecodeError as error:
        raise CaptureError("canonical Dockerfile must be UTF-8") from error
    from_values = [
        match.group(1)
        for line in dockerfile_text.splitlines()
        if (match := re.fullmatch(r"\s*FROM\s+(\S+)(?:\s+AS\s+\S+)?\s*", line, re.I))
    ]
    if from_values != [base["repo_digest"]]:
        raise CaptureError("canonical Dockerfile FROM does not match base digest")
    profile_record = _canonical_record_matches(
        inputs["profile_manifest"],
        expected_name="canonical-profile-manifest.json",
        content=artifacts["canonical-profile-manifest.json"],
        field="canonical.inputs.profile_manifest",
    )
    fixture_record = _canonical_record_matches(
        inputs["fixture_metadata"],
        expected_name="canonical-fixture-metadata.json",
        content=artifacts["canonical-fixture-metadata.json"],
        field="canonical.inputs.fixture_metadata",
    )
    profile = _strict_json_object(
        artifacts["canonical-profile-manifest.json"],
        "canonical profile manifest",
    )
    profile_checkpoints = profile.get("checkpoints")
    if not isinstance(profile_checkpoints, dict) or set(profile_checkpoints) != set(
        CANONICAL_CHECKPOINTS
    ):
        raise CaptureError("canonical profile checkpoint roles are invalid")
    raw_checkpoints = inputs["checkpoints"]
    if not isinstance(raw_checkpoints, list):
        raise CaptureError("canonical.inputs.checkpoints must be an array")
    checkpoints: dict[str, dict[str, Any]] = {}
    normalized_checkpoints: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_checkpoints):
        field = f"canonical.inputs.checkpoints[{index}]"
        record = _exact_object(raw, {"role", "path", "size", "sha256"}, field)
        role = record["role"]
        if role not in CANONICAL_CHECKPOINTS:
            raise CaptureError(f"{field}.role is invalid")
        _canonical_relative(record["path"], f"{field}.path")
        _package_integer(record["size"], f"{field}.size", minimum=1)
        _package_sha256(record["sha256"], f"{field}.sha256")
        profile_record_value = profile_checkpoints[role]
        if not isinstance(profile_record_value, dict) or record != {
            "role": role,
            "path": profile_record_value.get("relative_path"),
            "size": profile_record_value.get("size_bytes"),
            "sha256": profile_record_value.get("sha256"),
        }:
            raise CaptureError(f"{field} does not match profile manifest")
        checkpoints[role] = record
        normalized_checkpoints.append(record)
    if [record["role"] for record in normalized_checkpoints] != list(
        CANONICAL_CHECKPOINTS
    ):
        raise CaptureError("canonical.inputs.checkpoints must have exact sorted roles")
    oracle_contents = {
        role: artifacts[name]
        for role, (name, _oracle_id, _scope) in CANONICAL_ORACLES.items()
    }
    oracle_records = _canonical_oracle_records(
        inputs["oracles"],
        oracle_contents,
        profile_sha256=profile_record["sha256"],
        fixture_sha256=fixture_record["sha256"],
        uv_lock_sha256=uv_lock_sha256,
        base_repo_digest=base["repo_digest"],
        checkpoints=checkpoints,
    )
    oracle_aggregate = _sha256(_canonical_json_bytes(oracle_records))
    if inputs["uv_lock_sha256"] != uv_lock_sha256 or inputs[
        "oracle_aggregate_sha256"
    ] != oracle_aggregate:
        raise CaptureError("canonical input lock or oracle aggregate is invalid")
    input_basis = {
        "dockerfile": dockerfile_record,
        "oracles": oracle_records,
        "profile_manifest": profile_record,
        "fixture_metadata": fixture_record,
        "checkpoints": normalized_checkpoints,
        "uv_lock_sha256": uv_lock_sha256,
        "oracle_aggregate_sha256": oracle_aggregate,
    }
    input_aggregate = _sha256(_canonical_json_bytes(input_basis))
    if (
        inputs["input_aggregate_sha256"] != input_aggregate
        or build["input_aggregate_sha256"] != input_aggregate
    ):
        raise CaptureError("canonical input aggregate is invalid")

    runtime = _exact_object(
        sidecar["runtime"],
        {
            "network",
            "root_filesystem",
            "tmpfs",
            "cuda_available",
            "torch_cuda_version",
            "torch_intraop_threads",
            "omp_num_threads",
            "mkl_num_threads",
            "pythonhashseed",
            "harness_import_scope",
        },
        "canonical.runtime",
    )
    network = _exact_object(
        runtime["network"],
        {"policy", "probe", "blocked", "result_code"},
        "canonical.runtime.network",
    )
    if (
        network["policy"] != "denied"
        or network["probe"] != "connect_ex"
        or network["blocked"] is not True
        or _package_integer(network["result_code"], "network.result_code", minimum=1)
        < 1
    ):
        raise CaptureError("canonical runtime network proof is invalid")
    root_filesystem = _exact_object(
        runtime["root_filesystem"],
        {"policy", "probe", "blocked", "errno"},
        "canonical.runtime.root_filesystem",
    )
    if root_filesystem != {
        "policy": "read-only",
        "probe": "create",
        "blocked": True,
        "errno": 30,
    }:
        raise CaptureError("canonical root filesystem proof is invalid")
    tmpfs = _exact_object(
        runtime["tmpfs"],
        {"path", "writable", "options"},
        "canonical.runtime.tmpfs",
    )
    if tmpfs != {
        "path": "/tmp",
        "writable": True,
        "options": "rw,noexec,nosuid,size=64m",
    }:
        raise CaptureError("canonical tmpfs proof is invalid")
    if any(
        (
            runtime["cuda_available"] is not False,
            runtime["torch_cuda_version"] is not None,
            runtime["torch_intraop_threads"] != 1,
            runtime["omp_num_threads"] != "1",
            runtime["mkl_num_threads"] != "1",
            runtime["pythonhashseed"] != "0",
            runtime["harness_import_scope"] != "workspace-source-snapshot",
        )
    ):
        raise CaptureError("canonical runtime environment is invalid")

    installation = _exact_object(
        sidecar["installation"],
        {
            "distribution_name",
            "distribution_version",
            "console_entry_point",
            "origin_scope",
            "installed_package",
        },
        "canonical.installation",
    )
    if (
        installation["distribution_name"] != "ai-auto-lrc"
        or installation["distribution_version"] != "2.0.0a0"
        or installation["console_entry_point"] != "t2l.adapters.cli:main"
        or installation["origin_scope"] != "site-packages"
    ):
        raise CaptureError("canonical installed distribution is invalid")
    installed = _package_path_record(
        installation["installed_package"],
        "canonical.installation.installed_package",
    )
    installed_path = PurePosixPath(installed["name"])
    if len(installed_path.parts) < 2 or installed_path.parts[0] != "t2l":
        raise CaptureError("canonical installed package path is invalid")

    execution = _exact_object(
        sidecar["execution"],
        {
            "command_id",
            "selectors",
            "pytest_exit_code",
            "input_junit_sha256",
            "tests",
            "skipped",
            "failures_or_errors",
        },
        "canonical.execution",
    )
    if execution != {
        "command_id": "canonical-golden-verify-v1",
        "selectors": list(SELECTORS["canonical"]),
        "pytest_exit_code": 0,
        "input_junit_sha256": junit_sha256,
        "tests": tests,
        "skipped": 0,
        "failures_or_errors": 0,
    }:
        raise CaptureError("canonical execution does not match JUnit")

    provenance = _exact_object(
        sidecar["provenance"],
        {
            "scope",
            "producer_sha256",
            "observer_sha256",
            "runner_sha256",
            "policy_sha256",
            "source_sha256",
            "input_aggregate_sha256",
        },
        "canonical.provenance",
    )
    expected_provenance = {
        "scope": CANONICAL_PROVENANCE_SCOPE,
        "producer_sha256": _sha256(artifacts["canonical-producer.py"]),
        "observer_sha256": _sha256(artifacts["canonical-observer.py"]),
        "runner_sha256": _sha256(artifacts["canonical-runner.sh"]),
        "policy_sha256": policy_sha256,
        "source_sha256": source_sha256,
        "input_aggregate_sha256": input_aggregate,
    }
    if provenance != expected_provenance:
        raise CaptureError("canonical provenance is invalid")


def _canonical_binding_reasons(
    artifact_root: Path,
    *,
    run_id: str,
    policy_sha256: str | None,
    source_sha256: str | None,
    uv_lock_sha256: str | None,
    read_file: Callable[[Path, str], bytes] = _read_stable_regular,
) -> list[str]:
    """Independently verify the canonical flat closure and cross-bindings."""

    if policy_sha256 is None:
        return ["POLICY_HASH_MISMATCH"]
    if source_sha256 is None or uv_lock_sha256 is None:
        return ["RUN_ARTIFACT_BINDING_INVALID"]
    try:
        junit_content = read_file(artifact_root / "canonical.xml", "canonical.junit")
        junit_root = ET.fromstring(junit_content)
        cases = junit_root.findall(".//testcase")
    except (CaptureError, ET.ParseError):
        return ["JUNIT_INVALID_OR_EMPTY"]
    if not cases:
        return ["JUNIT_INVALID_OR_EMPTY"]
    if any(
        not (case.get("classname") or "").startswith(JUNIT_PREFIXES["canonical"])
        for case in cases
    ):
        return ["ARTIFACT_LAYER_MISMATCH"]
    skipped = sum(case.find("skipped") is not None for case in cases)
    failed = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    reasons: list[str] = []
    if failed or errors:
        reasons.append("JUNIT_FAILURE_OR_ERROR")
    if skipped:
        reasons.append("REQUIRED_TEST_SKIPPED")
    try:
        gate = _strict_json_object(
            read_file(artifact_root / "canonical-gate.json", "canonical.gate"),
            "canonical.gate",
        )
        sidecar = _strict_json_object(
            read_file(
                artifact_root / "canonical-runtime.json",
                "canonical.sidecar",
            ),
            "canonical.sidecar",
        )
        formal_names = set(ARTIFACT_CLOSURES["canonical"]) - {
            "canonical.xml",
            "canonical-gate.json",
            "canonical-runtime.json",
        }
        artifacts = {
            name: read_file(artifact_root / name, f"canonical.{name}")
            for name in formal_names
        }
        expected_gate_core = {
            "schema_version": 1,
            "gate": "pytest-layer",
            "layer": "canonical",
            "passed": failed == errors == skipped == 0,
            "tests": len(cases),
            "skipped": skipped,
            "failures_or_errors": failed + errors,
            "run_id": run_id,
            "input_junit_sha256": _sha256(junit_content),
            "policy_sha256": policy_sha256,
        }
        if (
            not all(gate.get(key) == value for key, value in expected_gate_core.items())
            or gate.get("required_markers") != ["golden"]
            or gate.get("outside_layer") != []
            or gate.get("failures") != []
            or gate.get("passed") is not True
        ):
            raise CaptureError("canonical gate does not match JUnit, run, and policy")
        _validate_canonical_sidecar(
            sidecar,
            artifacts,
            run_id=run_id,
            policy_sha256=policy_sha256,
            source_sha256=source_sha256,
            uv_lock_sha256=uv_lock_sha256,
            junit_sha256=_sha256(junit_content),
            tests=len(cases),
        )
    except (CaptureError, KeyError, TypeError, ValueError):
        reasons.append("RUN_ARTIFACT_BINDING_INVALID")
    return sorted(set(reasons))


def _verify_source_summary(
    root: Path,
    phase: str,
    summary: object,
    *,
    read_file: Callable[[Path, str], bytes] | None = None,
) -> dict[str, Any]:
    if not isinstance(summary, dict):
        raise CaptureError(f"source.{phase} must be an object")
    if not isinstance(summary.get("head"), str) or re.fullmatch(
        r"[0-9a-f]{40}", summary["head"]
    ) is None:
        raise CaptureError(f"source.{phase}.head must be a 40-character commit")
    if not isinstance(summary.get("safe"), bool):
        raise CaptureError(f"source.{phase}.safe must be boolean")
    patch = _verify_record(
        root,
        summary.get("patch"),
        f"source.{phase}.patch",
        read_file=read_file,
    )
    status_bytes = _verify_record(
        root,
        summary.get("status"),
        f"source.{phase}.status",
        read_file=read_file,
    )
    if summary.get("patch_sha256") != _sha256(patch):
        raise CaptureError(f"source.{phase}.patch_sha256 mismatch")
    if summary.get("status_sha256") != _sha256(status_bytes):
        raise CaptureError(f"source.{phase}.status_sha256 mismatch")
    if summary.get("dirty") is not bool(status_bytes):
        raise CaptureError(f"source.{phase}.dirty mismatch")
    ledger = summary.get("untracked")
    if not isinstance(ledger, list):
        raise CaptureError(f"source.{phase}.untracked must be an array")
    ledger_paths: list[str] = []
    for index, entry in enumerate(ledger):
        field = f"source.{phase}.untracked[{index}]"
        if not isinstance(entry, dict):
            raise CaptureError(f"{field} must be an object")
        relative = _canonical_relative(entry.get("path"), f"{field}.path")
        ledger_paths.append(relative.as_posix())
        if not isinstance(entry.get("mode"), int) or isinstance(entry.get("mode"), bool):
            raise CaptureError(f"{field}.mode must be an integer")
        if entry.get("kind") == "regular":
            archive_relative = PurePosixPath("source", phase, "untracked", *relative.parts)
            archive = root.joinpath(*archive_relative.parts)
            if read_file is None:
                archive = _safe_run_file(root, archive_relative.as_posix(), field)
                archived_bytes = _read_stable_regular(archive, field)
            else:
                archived_bytes = read_file(archive, field)
            if len(archived_bytes) != entry.get("size") or _sha256(
                archived_bytes
            ) != entry.get("sha256"):
                raise CaptureError(f"{field} archived snapshot mismatch")
        elif entry.get("kind") == "symlink":
            try:
                target = base64.b64decode(entry.get("target_base64"), validate=True)
            except (TypeError, ValueError) as error:
                raise CaptureError(f"{field}.target_base64 is invalid") from error
            if len(target) != entry.get("size") or _sha256(target) != entry.get("sha256"):
                raise CaptureError(f"{field} symlink target mismatch")
        elif entry.get("kind") != "special":
            raise CaptureError(f"{field}.kind is invalid")
    if ledger_paths != sorted(set(ledger_paths)):
        raise CaptureError(f"source.{phase}.untracked must be sorted and unique")
    identity_basis = {
        "head": summary.get("head"),
        "patch_sha256": summary.get("patch_sha256"),
        "status_sha256": summary.get("status_sha256"),
        "untracked": ledger,
        "safe": summary.get("safe"),
    }
    encoded_basis = json.dumps(
        identity_basis,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    aggregate = hashlib.sha256(b"ai-auto-lrc/source-snapshot/v1\0")
    aggregate.update(len(encoded_basis).to_bytes(8, "big"))
    aggregate.update(encoded_basis)
    if summary.get("aggregate_sha256") != aggregate.hexdigest():
        raise CaptureError(f"source.{phase}.aggregate_sha256 mismatch")
    return summary


def _seal_run(staging: Path, sealed: Path) -> None:
    for path in sorted(staging.rglob("*"), reverse=True):
        if path.is_symlink():
            raise CaptureError("run directory must not contain symlinks")
        path.chmod(0o500 if path.is_dir() else 0o400)
    staging.chmod(0o500)
    descriptor = os.open(staging, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if sealed.exists() or sealed.is_symlink():
        raise CaptureError("refusing to replace an existing sealed run")
    os.rename(staging, sealed)
    descriptor = os.open(sealed.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _best_effort_failure_marker(staging: Path, message: str) -> None:
    try:
        staging.chmod(0o700)
        marker = staging / "capture-failure.json"
        if marker.exists():
            marker.chmod(0o600)
            marker.unlink()
        _write_exclusive(
            marker,
            _json_bytes({"reason": "FINALIZATION_FAILED", "message": message}),
        )
    except OSError:
        pass


def _finalize_run(
    *,
    staging: Path,
    sealed: Path,
    artifact_root: Path,
    inputs_root: Path,
    stdout_path: Path,
    stderr_path: Path,
    layer: str,
    base_ref: str,
    run_id: str,
    policy_sha256: str | None,
    gate_started: bool,
    raw_returncode: int | None,
    observed_signal: int | None,
    gate_exception: str | None,
    before_summary: dict[str, Any] | None,
    after_summary: dict[str, Any] | None,
    before_record: dict[str, object] | None,
    after_record: dict[str, object] | None,
    reasons: list[str],
    started_at: str,
    started_ns: int,
) -> CaptureResult:
    """Build and seal a receipt without replacing an observed gate failure."""

    normalized_exit, child_signal = _normalize_returncode(raw_returncode)
    caught_signal = observed_signal if observed_signal is not None else child_signal
    if raw_returncode not in (None, 0):
        reasons.append("GATE_EXIT_NONZERO")
    if caught_signal is not None:
        reasons.append("GATE_TERMINATED_BY_SIGNAL")
    stable_source = bool(
        before_summary is not None
        and after_summary is not None
        and before_summary["aggregate_sha256"] == after_summary["aggregate_sha256"]
    )
    if before_summary is not None and not before_summary["safe"]:
        reasons.append("SOURCE_SNAPSHOT_UNSAFE")
    if after_summary is not None and not after_summary["safe"]:
        reasons.append("SOURCE_SNAPSHOT_UNSAFE")
    if before_summary is not None and after_summary is not None and not stable_source:
        reasons.append("SOURCE_CHANGED_DURING_RUN")

    try:
        artifact_records, missing, artifact_reasons = _snapshot_artifacts(
            staging,
            artifact_root,
            layer,
        )
        reasons.extend(artifact_reasons)
        if layer == "portable" and not missing:
            reasons.extend(
                _portable_binding_reasons(
                    artifact_root,
                    run_id=run_id,
                    policy_sha256=policy_sha256,
                    base_ref=base_ref,
                )
            )
        if layer == "package" and not missing:
            reasons.extend(
                _package_binding_reasons(
                    artifact_root,
                    run_id=run_id,
                    policy_sha256=policy_sha256,
                )
            )
        if layer == "canonical" and not missing:
            uv_lock_path = inputs_root / "uv.lock"
            reasons.extend(
                _canonical_binding_reasons(
                    artifact_root,
                    run_id=run_id,
                    policy_sha256=policy_sha256,
                    source_sha256=(
                        None
                        if before_summary is None
                        else before_summary["aggregate_sha256"]
                    ),
                    uv_lock_sha256=(
                        sha256_file(uv_lock_path) if uv_lock_path.is_file() else None
                    ),
                )
            )
        reasons = sorted(set(reasons))
        finished_at = _utc_now()
        receipt: dict[str, Any] = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "claim": {"layer": layer, "spec_ids": []},
            "source": {
                "before": before_record,
                "after": after_record,
                "before_aggregate_sha256": (
                    None if before_summary is None else before_summary["aggregate_sha256"]
                ),
                "after_aggregate_sha256": (
                    None if after_summary is None else after_summary["aggregate_sha256"]
                ),
                "stable_during_run": stable_source,
                "observation_limit": SOURCE_OBSERVATION_LIMIT,
            },
            "environment": {
                "capture_os": platform.system(),
                "capture_arch": platform.machine(),
                "capture_python": platform.python_version(),
            },
            "inputs": {
                "runner": _record(
                    staging,
                    inputs_root / "run_test_gate.sh",
                    "inputs.runner",
                )
                if (inputs_root / "run_test_gate.sh").is_file()
                else None,
                "uv_lock": _record(
                    staging,
                    inputs_root / "uv.lock",
                    "inputs.uv_lock",
                )
                if (inputs_root / "uv.lock").is_file()
                else None,
                "quality_policy": _record(
                    staging,
                    inputs_root / "quality-gates.toml",
                    "inputs.quality_policy",
                )
                if (inputs_root / "quality-gates.toml").is_file()
                else None,
                "base_ref": base_ref if layer == "portable" else None,
            },
            "run": {
                "gate_started": gate_started,
                "command_id": COMMAND_IDS[layer],
                "selectors": list(SELECTORS[layer]),
                "started_at_utc": started_at,
                "finished_at_utc": finished_at,
                "duration_ns": time.monotonic_ns() - started_ns,
                "raw_returncode": raw_returncode,
                "normalized_exit_code": normalized_exit,
                "signal": caught_signal,
                "exception": gate_exception,
            },
            "logs": {
                "stdout": _record(staging, stdout_path, "logs.stdout"),
                "stderr": _record(staging, stderr_path, "logs.stderr"),
            },
            "artifacts": artifact_records,
            "missing_artifacts": missing,
            "verification": {"passed": not reasons, "reason_codes": reasons},
            "qualification": {
                "level": "implemented-unqualified" if not reasons else "diagnostic",
                "derived": True,
            },
        }
        final_exit = normalized_exit
        if normalized_exit == 0 and reasons:
            final_exit = CAPTURE_ERROR_EXIT
        receipt["run"]["capture_exit_code"] = final_exit
        receipt_bytes = _json_bytes(receipt)
        _write_exclusive(staging / "receipt.json", receipt_bytes)
        _write_exclusive(
            staging / "SEALED",
            _json_bytes(
                {
                    "run_id": run_id,
                    "receipt_sha256": _sha256(receipt_bytes),
                }
            ),
        )
        _seal_run(staging, sealed)
        try:
            verify_receipt(sealed / "receipt.json", mode="archived-integrity")
        except (CaptureError, OSError, ValueError):
            os.rename(sealed, staging)
            raise
        return CaptureResult(final_exit, sealed, True)
    except (CaptureError, OSError, ValueError, TypeError, KeyError) as error:
        failure_root = staging if staging.exists() else sealed
        _best_effort_failure_marker(failure_root, type(error).__name__)
        final_exit = normalized_exit if normalized_exit != 0 else CAPTURE_ERROR_EXIT
        return CaptureResult(final_exit, failure_root, False)


def capture_gate(
    *,
    repo_root: Path,
    retention_root: Path,
    layer: str,
    base_ref: str = "HEAD",
) -> CaptureResult:
    """Run the repository gate and seal its observed result and artifacts."""

    repository, retention = _preflight(repo_root, retention_root, layer)
    run_id = _new_run_id()
    staging = retention / f".incomplete-{run_id}"
    sealed = retention / run_id
    staging.mkdir(mode=0o700, exist_ok=False)
    artifact_root = staging / "artifacts" / layer
    artifact_root.mkdir(mode=0o700, parents=True)
    logs_root = staging / "logs"
    logs_root.mkdir(mode=0o700)
    stdout_path = logs_root / "stdout.bin"
    stderr_path = logs_root / "stderr.bin"
    inputs_root = staging / "inputs"
    inputs_root.mkdir(mode=0o700)

    gate_started = False
    raw_returncode: int | None = None
    observed_signal: int | None = None
    gate_exception: str | None = None
    policy_sha256: str | None = None
    before_summary: dict[str, Any] | None = None
    after_summary: dict[str, Any] | None = None
    before_record: dict[str, object] | None = None
    after_record: dict[str, object] | None = None
    reasons: list[str] = []
    started_at = _utc_now()
    started_ns = time.monotonic_ns()
    result: CaptureResult | None = None

    try:
        try:
            before_summary, before_record = _capture_source(repository, staging, "before")
            runner_bytes = _read_stable_regular(
                repository / "scripts/run_test_gate.sh",
                "runner",
            )
            _write_exclusive(inputs_root / "run_test_gate.sh", runner_bytes)
            if (repository / "uv.lock").is_file():
                _write_exclusive(
                    inputs_root / "uv.lock",
                    _read_stable_regular(repository / "uv.lock", "inputs.uv_lock"),
                )
            policy_path = repository / "packaging/quality-gates.toml"
            if policy_path.is_file():
                policy_bytes = _read_stable_regular(
                    policy_path,
                    "inputs.quality_policy",
                )
                policy_sha256 = _sha256(policy_bytes)
                _write_exclusive(inputs_root / "quality-gates.toml", policy_bytes)
        except (CaptureError, OSError) as error:
            reasons.append("SOURCE_SNAPSHOT_UNSAFE")
            gate_exception = type(error).__name__

        _write_exclusive(stdout_path, b"")
        _write_exclusive(stderr_path, b"")
        if before_summary is not None:
            command = [os.fspath(repository / "scripts/run_test_gate.sh"), layer]
            if layer == "portable":
                command.append(base_ref)
            environment = os.environ.copy()
            environment["AI_AUTO_LRC_GATE_ARTIFACT_DIR"] = os.fspath(artifact_root)
            environment["AI_AUTO_LRC_EVIDENCE_RUN_ID"] = run_id
            environment["AI_AUTO_LRC_EVIDENCE_BASE_REF"] = base_ref
            environment["AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256"] = before_summary[
                "aggregate_sha256"
            ]
            if policy_sha256 is not None:
                environment["AI_AUTO_LRC_EVIDENCE_POLICY_SHA256"] = policy_sha256
            else:
                environment.pop("AI_AUTO_LRC_EVIDENCE_POLICY_SHA256", None)
            try:
                stdout_path.chmod(0o600)
                stderr_path.chmod(0o600)
                with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                    gate_started = True
                    raw_returncode, observed_signal = _run_gate_process(
                        command,
                        cwd=repository,
                        environment=environment,
                        stdout=stdout,
                        stderr=stderr,
                    )
                    stdout.flush()
                    stderr.flush()
                    os.fsync(stdout.fileno())
                    os.fsync(stderr.fileno())
            except OSError as error:
                gate_started = False
                gate_exception = type(error).__name__
                reasons.append("GATE_NOT_STARTED")
        else:
            reasons.append("GATE_NOT_STARTED")

        try:
            after_summary, after_record = _capture_source(repository, staging, "after")
        except (CaptureError, OSError) as error:
            reasons.append("SOURCE_SNAPSHOT_UNSAFE")
            gate_exception = gate_exception or type(error).__name__
    except KeyboardInterrupt:
        observed_signal = signal.SIGINT
        raw_returncode = -signal.SIGINT
        gate_exception = "KeyboardInterrupt"
    except (CaptureError, OSError, ValueError) as error:
        reasons.append("CAPTURE_INTERNAL_ERROR")
        gate_exception = type(error).__name__
    finally:
        result = _finalize_run(
            staging=staging,
            sealed=sealed,
            artifact_root=artifact_root,
            inputs_root=inputs_root,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            layer=layer,
            base_ref=base_ref,
            run_id=run_id,
            policy_sha256=policy_sha256,
            gate_started=gate_started,
            raw_returncode=raw_returncode,
            observed_signal=observed_signal,
            gate_exception=gate_exception,
            before_summary=before_summary,
            after_summary=after_summary,
            before_record=before_record,
            after_record=after_record,
            reasons=reasons,
            started_at=started_at,
            started_ns=started_ns,
        )
    if result is None:  # pragma: no cover - defensive invariant
        raise CaptureError("capture finalizer did not return a result")
    return result


def _verify_receipt_from_io(
    receipt_io: _DirFdReceiptIO,
    receipt_name: str,
    mode: str,
    repo_root_fd: int | None,
    *,
    expected_run_name: str | None,
) -> dict[str, Any]:
    """Verify archived bytes through one already-anchored run directory."""

    if mode not in {"archived-integrity", "current-source"}:
        raise CaptureError("mode must be archived-integrity or current-source")
    relative_receipt = _canonical_relative(receipt_name, "receipt.path")
    if len(relative_receipt.parts) != 1 or relative_receipt.name != "receipt.json":
        raise CaptureError("receipt_name must be receipt.json")
    content = receipt_io.read(receipt_name, "receipt")
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureError("receipt must be valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise CaptureError("receipt must be a JSON object")
    if document.get("schema") != SCHEMA or document.get("schema_version") != SCHEMA_VERSION:
        raise CaptureError("receipt schema_version 1 is required")
    run_id = document.get("run_id")
    if not isinstance(run_id, str) or RUN_ID.fullmatch(run_id) is None:
        raise CaptureError("run_id is invalid")
    qualification = document.get("qualification")
    if not isinstance(qualification, dict) or qualification.get("level") not in {
        "diagnostic",
        "implemented-unqualified",
    }:
        raise CaptureError("schema_version 1 forbids qualified-canonical and qualified-release")
    root = Path("/__ai_auto_lrc_sealed_run__")
    if expected_run_name is not None and expected_run_name != run_id:
        raise CaptureError("sealed run directory must match run_id")
    if receipt_io.root_stat.st_mode & 0o222:
        raise CaptureError("sealed run root must be read-only")
    expected_files = {receipt_name, "SEALED"}

    def read_file(path: Path, field: str) -> bytes:
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as error:
            raise CaptureError(f"{field} must be inside the run directory") from error
        return receipt_io.read(relative, field)

    def verify_named(record: object, field: str) -> bytes:
        if not isinstance(record, dict):
            raise CaptureError(f"{field} must be a file record")
        relative = _canonical_relative(record.get("path"), f"{field}.path")
        expected_files.add(relative.as_posix())
        return _verify_record(root, record, field, read_file=read_file)

    marker_content = read_file(root / "SEALED", "SEALED")
    try:
        marker = json.loads(marker_content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureError("SEALED must be valid UTF-8 JSON") from error
    if not isinstance(marker, dict) or marker != {
        "run_id": document.get("run_id"),
        "receipt_sha256": _sha256(content),
    }:
        raise CaptureError("SEALED does not bind this receipt")
    logs = document.get("logs")
    if not isinstance(logs, dict) or set(logs) != {"stdout", "stderr"}:
        raise CaptureError("logs must contain stdout and stderr")
    for name, record in logs.items():
        verify_named(record, f"logs.{name}")
    source = document.get("source")
    if not isinstance(source, dict):
        raise CaptureError("source must be an object")
    if source.get("observation_limit") != SOURCE_OBSERVATION_LIMIT:
        raise CaptureError("source.observation_limit is invalid")
    if set(source) != {
        "before",
        "after",
        "before_aggregate_sha256",
        "after_aggregate_sha256",
        "stable_during_run",
        "observation_limit",
    }:
        raise CaptureError("source has an invalid shape")
    summaries: dict[str, dict[str, Any]] = {}
    for phase in ("before", "after"):
        raw = verify_named(source.get(phase), f"source.{phase}")
        try:
            parsed_summary = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CaptureError(f"source.{phase} must be JSON") from error
        summaries[phase] = _verify_source_summary(
            root,
            phase,
            parsed_summary,
            read_file=read_file,
        )
        for record_name in ("patch", "status"):
            record = summaries[phase].get(record_name)
            if not isinstance(record, dict):
                raise CaptureError(f"source.{phase}.{record_name} is required")
            relative = _canonical_relative(
                record.get("path"),
                f"source.{phase}.{record_name}.path",
            )
            expected_files.add(relative.as_posix())
        for entry in summaries[phase]["untracked"]:
            if entry["kind"] == "regular":
                relative = _canonical_relative(
                    entry["path"],
                    f"source.{phase}.untracked.path",
                )
                expected_files.add(
                    PurePosixPath(
                        "source", phase, "untracked", *relative.parts
                    ).as_posix()
                )
        if summaries[phase].get("aggregate_sha256") != source.get(
            f"{phase}_aggregate_sha256"
        ):
            raise CaptureError(f"source.{phase} aggregate mismatch")
    if source.get("stable_during_run") is not (
        summaries["before"]["aggregate_sha256"]
        == summaries["after"]["aggregate_sha256"]
    ):
        raise CaptureError("source.stable_during_run mismatch")
    inputs = document.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != {
        "runner",
        "uv_lock",
        "quality_policy",
        "base_ref",
    }:
        raise CaptureError("inputs has an invalid shape")
    for name in ("runner", "uv_lock", "quality_policy"):
        if inputs.get(name) is None:
            raise CaptureError(f"inputs.{name} is required")
        verify_named(inputs[name], f"inputs.{name}")
    claim = document.get("claim")
    if not isinstance(claim, dict) or set(claim) != {"layer", "spec_ids"}:
        raise CaptureError("claim has an invalid shape")
    if not isinstance(claim["spec_ids"], list) or not all(
        isinstance(item, str) for item in claim["spec_ids"]
    ):
        raise CaptureError("claim.spec_ids must be a string array")
    layer = claim["layer"]
    if layer not in LAYERS:
        raise CaptureError("claim.layer is invalid")
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict):
        raise CaptureError("artifacts must be an object")
    required_artifacts = set(ARTIFACT_CLOSURES[layer])
    if not set(artifacts) <= required_artifacts:
        raise CaptureError("artifacts contain a cross-layer or unknown file")
    missing = document.get("missing_artifacts")
    if (
        not isinstance(missing, list)
        or not all(isinstance(item, str) for item in missing)
        or missing != sorted(set(missing))
        or set(missing) != required_artifacts - set(artifacts)
    ):
        raise CaptureError("missing_artifacts does not match the layer closure")
    for name, record in artifacts.items():
        verify_named(record, f"artifacts.{name}")

    verification = document.get("verification")
    if not isinstance(verification, dict) or set(verification) != {
        "passed",
        "reason_codes",
    }:
        raise CaptureError("verification has an invalid shape")
    reason_codes = verification["reason_codes"]
    if (
        not isinstance(reason_codes, list)
        or not all(isinstance(item, str) and item for item in reason_codes)
        or reason_codes != sorted(set(reason_codes))
        or verification["passed"] is not (not reason_codes)
    ):
        raise CaptureError("verification reason codes are inconsistent")
    if missing and "REQUIRED_ARTIFACT_MISSING" not in reason_codes:
        raise CaptureError("missing layer artifacts are not reflected in verification")
    if not source["stable_during_run"] and "SOURCE_CHANGED_DURING_RUN" not in reason_codes:
        raise CaptureError("source change is not reflected in verification")
    if layer == "portable" and not missing:
        policy = inputs.get("quality_policy")
        if not isinstance(policy, dict):
            raise CaptureError("inputs.quality_policy is required for portable evidence")
        binding_reasons = _portable_binding_reasons(
            root / "artifacts/portable",
            run_id=document.get("run_id"),
            policy_sha256=policy.get("sha256"),
            base_ref=inputs.get("base_ref"),
            read_file=read_file,
        )
        for reason in binding_reasons:
            if reason not in reason_codes:
                raise CaptureError("portable artifact binding does not match receipt")
    if layer == "package":
        if claim["spec_ids"]:
            raise CaptureError("package schema_version 1 claim.spec_ids must be empty")
        if "LAYER_CLOSURE_UNIMPLEMENTED" in reason_codes:
            raise CaptureError("package layer closure is implemented in schema_version 1")
        if not missing:
            policy = inputs.get("quality_policy")
            if not isinstance(policy, dict):
                raise CaptureError("inputs.quality_policy is required for package evidence")
            package_binding_reasons = _package_binding_reasons(
                root / "artifacts/package",
                run_id=run_id,
                policy_sha256=policy.get("sha256"),
                read_file=read_file,
            )
            for reason in package_binding_reasons:
                if reason not in reason_codes:
                    raise CaptureError("package artifact binding does not match receipt")
    if layer == "canonical":
        if claim["spec_ids"]:
            raise CaptureError("canonical schema_version 1 claim.spec_ids must be empty")
        if "LAYER_CLOSURE_UNIMPLEMENTED" in reason_codes:
            raise CaptureError("canonical layer closure is implemented in schema_version 1")
        if not missing:
            policy = inputs.get("quality_policy")
            uv_lock = inputs.get("uv_lock")
            if not isinstance(policy, dict) or not isinstance(uv_lock, dict):
                raise CaptureError("canonical evidence inputs are required")
            canonical_binding_reasons = _canonical_binding_reasons(
                root / "artifacts/canonical",
                run_id=run_id,
                policy_sha256=policy.get("sha256"),
                source_sha256=source.get("before_aggregate_sha256"),
                uv_lock_sha256=uv_lock.get("sha256"),
                read_file=read_file,
            )
            for reason in canonical_binding_reasons:
                if reason not in reason_codes:
                    raise CaptureError("canonical artifact binding does not match receipt")

    run = document.get("run")
    if not isinstance(run, dict):
        raise CaptureError("run must be an object")
    if run.get("command_id") != COMMAND_IDS[layer] or run.get("selectors") != list(
        SELECTORS[layer]
    ):
        raise CaptureError("run command identity is invalid")
    if not isinstance(run.get("gate_started"), bool):
        raise CaptureError("run.gate_started must be boolean")
    raw_returncode = run.get("raw_returncode")
    if raw_returncode is not None and (
        not isinstance(raw_returncode, int) or isinstance(raw_returncode, bool)
    ):
        raise CaptureError("run.raw_returncode must be an integer or null")
    expected_normalized, child_signal = _normalize_returncode(raw_returncode)
    if run.get("normalized_exit_code") != expected_normalized:
        raise CaptureError("run.normalized_exit_code is inconsistent")
    observed_signal = run.get("signal")
    if observed_signal is not None and (
        not isinstance(observed_signal, int)
        or isinstance(observed_signal, bool)
        or observed_signal <= 0
    ):
        raise CaptureError("run.signal must be a positive integer or null")
    if child_signal is not None and observed_signal != child_signal:
        raise CaptureError("run.signal does not match the child return code")
    if observed_signal is not None and "GATE_TERMINATED_BY_SIGNAL" not in reason_codes:
        raise CaptureError("gate signal is not reflected in verification")
    if raw_returncode not in (None, 0) and "GATE_EXIT_NONZERO" not in reason_codes:
        raise CaptureError("gate failure is not reflected in verification")
    expected_capture_exit = expected_normalized
    if expected_capture_exit == 0 and reason_codes:
        expected_capture_exit = CAPTURE_ERROR_EXIT
    if run.get("capture_exit_code") != expected_capture_exit:
        raise CaptureError("run.capture_exit_code is inconsistent")
    exception_name = run.get("exception")
    if exception_name is not None and (
        not isinstance(exception_name, str)
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", exception_name) is None
    ):
        raise CaptureError("run.exception must not contain a path or message")

    expected_level = "implemented-unqualified" if not reason_codes else "diagnostic"
    if qualification != {"level": expected_level, "derived": True}:
        raise CaptureError("qualification does not match verified evidence")

    actual_files = receipt_io.file_closure()
    unrecorded = sorted(actual_files - expected_files)
    if unrecorded:
        raise CaptureError(f"sealed run contains an unrecorded file: {unrecorded[0]}")
    if actual_files != expected_files:
        raise CaptureError("sealed run file closure is incomplete")

    if mode == "current-source":
        if repo_root_fd is None:
            raise CaptureError("repo_root_fd is required for current-source verification")
        first_observation = _source_material_at(repo_root_fd)
        second_observation = _source_material_at(repo_root_fd)
        if first_observation != second_observation:
            raise CaptureError("CURRENT_SOURCE_OBSERVATION_UNSTABLE")
        if first_observation["aggregate_sha256"] != summaries["before"]["aggregate_sha256"]:
            raise CaptureError("current source does not match captured source")
    return document


def _fd_anchor_path(descriptor: int, field: str) -> Path:
    expected = os.fstat(descriptor)
    for base in (Path("/proc/self/fd"),):
        candidate = base / str(descriptor)
        try:
            observed = candidate.stat()
        except OSError:
            continue
        if (observed.st_dev, observed.st_ino) == (expected.st_dev, expected.st_ino):
            return candidate
    get_path = getattr(fcntl, "F_GETPATH", None)
    if get_path is not None:
        try:
            raw_path = fcntl.fcntl(descriptor, get_path, b"\0" * 1024)
            candidate = Path(os.fsdecode(raw_path.split(b"\0", 1)[0]))
            anchor_fd = _open_directory_anchor(candidate, field)
            try:
                observed = os.fstat(anchor_fd)
                if (observed.st_dev, observed.st_ino) == (
                    expected.st_dev,
                    expected.st_ino,
                ):
                    return candidate
            finally:
                os.close(anchor_fd)
        except (OSError, ValueError):
            pass
    raise CaptureError(f"{field} cannot be exposed as a verified fd anchor")


def _source_material_at(repo_root_fd: int) -> dict[str, Any]:
    try:
        descriptor = os.dup(repo_root_fd)
    except OSError as error:
        raise CaptureError("repo_root_fd is not a valid open directory") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISDIR(before.st_mode):
            raise CaptureError("repo_root_fd must refer to a directory")
        anchor = _fd_anchor_path(descriptor, "repo_root_fd")
        current, _patch, _status, _snapshots = _source_material(
            anchor,
            repo_root_fd=descriptor,
        )
        after = os.fstat(descriptor)
        if (after.st_dev, after.st_ino, after.st_mode) != (
            before.st_dev,
            before.st_ino,
            before.st_mode,
        ):
            raise CaptureError("repo_root_fd anchor changed during verification")
        anchored = anchor.stat()
        if (anchored.st_dev, anchored.st_ino) != (after.st_dev, after.st_ino):
            raise CaptureError("repo_root_fd anchor changed during verification")
        return current
    finally:
        os.close(descriptor)


def verify_receipt_at(
    run_fd: int,
    receipt_name: str,
    mode: str,
    repo_root_fd: int | None = None,
) -> dict[str, Any]:
    """Verify a receipt relative to caller-opened run and repository anchors."""

    with _DirFdReceiptIO(run_fd) as receipt_io:
        return _verify_receipt_from_io(
            receipt_io,
            receipt_name,
            mode,
            repo_root_fd,
            expected_run_name=None,
        )


def _open_directory_anchor(path: Path, field: str) -> int:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise CaptureError("directory-relative safe verification is unsupported")
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    absolute = path.absolute()
    descriptor: int | None = None
    try:
        descriptor = os.open(absolute.anchor, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise CaptureError(f"{field} must be a directory")
        for part in absolute.parts[1:]:
            if part in {"", ".", ".."}:
                raise CaptureError(f"{field} could not be opened safely")
            before = os.stat(
                part,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise CaptureError(f"{field} could not be opened safely")
            child: int | None = None
            try:
                child = os.open(part, flags, dir_fd=descriptor)
                opened = os.fstat(child)
            except OSError:
                if child is not None:
                    with suppress(OSError):
                        os.close(child)
                raise
            if not stat.S_ISDIR(opened.st_mode) or _identity(opened) != _identity(
                before
            ):
                os.close(child)
                raise CaptureError(f"{field} could not be opened safely")
            previous = descriptor
            descriptor = child
            os.close(previous)
        result = descriptor
        descriptor = None
        return result
    except CaptureError:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        raise
    except OSError as error:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        raise CaptureError(f"{field} could not be opened safely") from error


def verify_receipt(
    receipt_path: Path,
    *,
    mode: str,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Verify archived bytes, optionally matching them to the current checkout."""

    absolute_receipt = receipt_path.absolute()
    run_root = absolute_receipt.parent
    run_fd = _open_directory_anchor(run_root, "sealed run root")
    repo_root_fd: int | None = None
    try:
        if mode == "current-source":
            if repo_root is None:
                raise CaptureError("repo_root is required for current-source verification")
            repo_root_fd = _open_directory_anchor(repo_root.absolute(), "repo_root")
        with _DirFdReceiptIO(run_fd) as receipt_io:
            return _verify_receipt_from_io(
                receipt_io,
                absolute_receipt.name,
                mode,
                repo_root_fd,
                expected_run_name=run_root.name,
            )
    finally:
        if repo_root_fd is not None:
            os.close(repo_root_fd)
        os.close(run_fd)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--layer", choices=LAYERS, required=True)
    run.add_argument("--base-ref", default="HEAD")
    run.add_argument("--retention-root", type=Path, required=True)
    run.add_argument("--repo-root", type=Path, default=REPOSITORY_ROOT)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument(
        "--mode",
        choices=("archived-integrity", "current-source"),
        required=True,
    )
    verify.add_argument("--repo-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "run":
        try:
            result = capture_gate(
                repo_root=arguments.repo_root,
                retention_root=arguments.retention_root,
                layer=arguments.layer,
                base_ref=arguments.base_ref,
            )
        except (CaptureError, OSError, ValueError) as error:
            sys.stderr.write(f"evidence capture failed: {error}\n")
            return CAPTURE_ERROR_EXIT
        if result.run_directory is not None:
            sys.stdout.write(os.fspath(result.run_directory) + "\n")
        return result.exit_code
    try:
        verify_receipt(
            arguments.receipt,
            mode=arguments.mode,
            repo_root=arguments.repo_root,
        )
    except (CaptureError, OSError, ValueError) as error:
        sys.stderr.write(f"evidence receipt verification failed: {error}\n")
        return 1
    output: dict[str, object] = {
        "valid": True,
        "mode": arguments.mode,
        "effective_qualification": "diagnostic-historical-integrity",
    }
    if arguments.mode == "current-source":
        output.update(
            {
                "effective_qualification": "diagnostic-current-source-observation",
                "transactional": False,
                "aba_excluded": False,
                "observation_model": "sequential-double-observation",
            }
        )
    sys.stdout.write(
        json.dumps(
            output,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
