#!/usr/bin/env python3
"""Inspect sealed evidence locally without enabling export or destruction."""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

if __package__:
    from . import capture_test_gate
else:  # pragma: no cover - subprocess CLI
    import capture_test_gate

RULES_SCHEMA = "ai-auto-lrc/evidence-secret-rules"
ASSESSMENT_SCHEMA = "ai-auto-lrc/retention-assessment"
SCAN_SCHEMA = "ai-auto-lrc/secret-scan"
EVENT_SCHEMA = "ai-auto-lrc/evidence-lifecycle-event"
SCHEMA_VERSION = 1
SCANNER_ID = "ai-auto-lrc-byte-scanner-v1"

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES = REPOSITORY_ROOT / "packaging/evidence-secret-rules.json"
DEFAULT_ASSESSMENT = REPOSITORY_ROOT / "packaging/evidence-retention-assessment.json"
DEFAULT_RULES_SHA256 = "ab396187f0e53e26d9eb63cd3d4051a3103233b0cc4154d1199248247398df3c"
DEFAULT_ASSESSMENT_SHA256 = "78f67c28156916d443f45a246ddfef2d693a3319f28ffb5e185e6fdf6a7a54f3"

SHA256 = re.compile(r"^[0-9a-f]{64}$")
EVENT_NAME = re.compile(r"^(?P<sequence>[0-9]{8})-(?P<sha256>[0-9a-f]{64})\.json$")
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
RULE_ID = re.compile(r"^[A-Z0-9_-]{1,128}$")
CATEGORY = re.compile(r"^[a-z0-9-]{1,64}$")
ACTOR = re.compile(r"^[A-Za-z0-9._:@/-]{1,128}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
MATCHERS = {
    "literal-ascii",
    "literal-ascii-ci",
    "scheme-value-ascii-ci",
    "assignment-value-ascii-ci",
}
CLASSIFICATIONS = {
    "metadata",
    "captured-input",
    "test-evidence",
    "source-raw",
    "log-raw",
    "checkpoint",
    "unknown",
}
ASSESSMENT_DECISIONS = {
    "approval_count",
    "approval_ttl_seconds",
    "archive_provider",
    "checkpoint_strategy",
    "destruction",
    "evidence_owner",
    "export_classes",
    "export_purposes",
    "key_custody",
    "key_rotation",
    "release_owner",
    "retention_by_class",
    "rpo_hours",
    "rto_hours",
    "security_owner",
    "tombstone_days",
}
INSPECTION_FILES = {
    "secret-scan.json",
    "secret-rules.json",
    "retention-assessment.json",
    "COMPLETE",
}
MAX_CONFIG_BYTES = 1024 * 1024
MAX_WHITESPACE = 64
MAX_RUN_ENTRIES = 4096
MAX_RUN_FILES = 4096
MAX_RUN_BYTES = 1024 * 1024 * 1024
MAX_RUN_SNAPSHOT_METADATA_BYTES = 512 * 1024
MAX_TOTAL_HITS = 2048
MAX_REPORT_METADATA_BYTES = 512 * 1024
MAX_REPORT_BYTES = 1024 * 1024
SENSITIVE_LABELS = (
    "access_key",
    "api_key",
    "apikey",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


class RetentionError(RuntimeError):
    """Stable error whose code is safe to expose at the CLI boundary."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SecretRule:
    rule_id: str
    category: str
    matcher: str
    terms: tuple[bytes, ...]
    max_value_bytes: int


@dataclass(frozen=True, slots=True)
class SecretRules:
    rule_set_id: str
    scanner_id: str
    chunk_bytes: int
    rules: tuple[SecretRule, ...]
    content: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class RetentionAssessment:
    assessment_id: str
    max_file_bytes: int
    content: bytes
    sha256: str
    document: dict[str, Any]


@dataclass(frozen=True, slots=True)
class InspectionResult:
    inspection_path: Path
    control_event_path: Path
    state: Literal["SCANNED_PASS", "SCANNED_BLOCKED"]
    run_id: str
    inspection_id: str

    @property
    def report_path(self) -> Path:
        return self.inspection_path / "secret-scan.json"

    @property
    def control_directory(self) -> Path:
        return self.inspection_path.parents[1]

    @property
    def status(self) -> str:
        return self.state


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _compact_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_mode,
        value.st_nlink,
    )


def _same_open_directory(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare an opened directory without treating child-count churn as replacement."""
    return _directory_identity(left)[:4] == _directory_identity(right)[:4]


@dataclass(slots=True)
class _SnapshotBudget:
    entries: int = 0
    regular_files: int = 0
    declared_bytes: int = 0
    snapshot_metadata_bytes: int = 2

    def reserve(
        self,
        relative: str,
        identity: tuple[int, int, int, int, int, int, int, int],
        *,
        is_root: bool = False,
    ) -> None:
        regular = not is_root and stat.S_ISREG(identity[3])
        entries = self.entries + (0 if is_root else 1)
        regular_files = self.regular_files + int(regular)
        declared_bytes = self.declared_bytes + (identity[5] if regular else 0)
        metadata_increment = (
            len(_compact_bytes(relative))
            + 1
            + len(_compact_bytes(identity))
            + int(self.snapshot_metadata_bytes > 2)
        )
        snapshot_metadata_bytes = self.snapshot_metadata_bytes + metadata_increment
        if (
            entries > MAX_RUN_ENTRIES
            or regular_files > MAX_RUN_FILES
            or declared_bytes > MAX_RUN_BYTES
            or snapshot_metadata_bytes > MAX_RUN_SNAPSHOT_METADATA_BYTES
        ):
            raise RetentionError("SCAN_RUN_LIMIT_EXCEEDED")
        self.entries = entries
        self.regular_files = regular_files
        self.declared_bytes = declared_bytes
        self.snapshot_metadata_bytes = snapshot_metadata_bytes


@dataclass(frozen=True, slots=True)
class _ControlDirectoryContext:
    run_control: Path
    run_control_fd: int
    inspections_fd: int
    events_fd: int
    run_control_identity: tuple[int, int, int, int, int]
    inspections_identity: tuple[int, int, int, int, int]
    events_identity: tuple[int, int, int, int, int]

    def anchor(self, path: Path) -> tuple[int, tuple[str, ...]] | None:
        for root, descriptor in (
            (self.run_control / "inspections", self.inspections_fd),
            (self.run_control / "events", self.events_fd),
            (self.run_control, self.run_control_fd),
        ):
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            return descriptor, relative.parts
        return None


@dataclass(slots=True)
class _RenameCommitState:
    committed: bool = False
    source_identity: tuple[int, int, int, int, int] | None = None


_ACTIVE_CONTROL_CONTEXT: ContextVar[_ControlDirectoryContext | None] = ContextVar(
    "active_retention_control_context",
    default=None,
)
_ACTIVE_RENAME_COMMIT: ContextVar[_RenameCommitState | None] = ContextVar(
    "active_retention_rename_commit",
    default=None,
)


def _exact(value: object, keys: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RetentionError(code)
    return value


def _timestamp(value: object) -> bool:
    if not isinstance(value, str) or UTC_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return False
    return True


def _hash(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _safe_id(value: object) -> bool:
    return isinstance(value, str) and SAFE_ID.fullmatch(value) is not None


def _actor(value: object) -> bool:
    return (
        isinstance(value, str)
        and ACTOR.fullmatch(value) is not None
        and not value.startswith("/")
        and not any(ord(character) < 32 or character.isspace() for character in value)
        and str(Path.home()) not in value
        and "/Users/" not in value
        and "/home/" not in value
        and not any(label in value.lower() for label in SENSITIVE_LABELS)
    )


def _report_path(relative: str) -> str:
    parts = PurePosixPath(relative).parts
    sanitized = [
        f"redacted-{_sha256(part.encode())[:16]}"
        if any(label in part.lower() for label in SENSITIVE_LABELS)
        else part
        for part in parts
    ]
    return PurePosixPath(*sanitized).as_posix()


def _absolute(path: Path, code: str) -> Path:
    if not path.is_absolute():
        raise RetentionError(code)
    return path


def _assert_no_symlink_components(
    path: Path,
    code: str,
    *,
    missing_leaf: bool = False,
) -> None:
    absolute = _absolute(path, code)
    current = Path(absolute.anchor)
    parts = absolute.parts[1:]
    for index, part in enumerate(parts):
        current /= part
        try:
            item_stat = current.lstat()
        except FileNotFoundError:
            if missing_leaf and index == len(parts) - 1:
                return
            raise RetentionError(code) from None
        except OSError as error:
            raise RetentionError(code) from error
        if stat.S_ISLNK(item_stat.st_mode):
            raise RetentionError("SYMLINK_FORBIDDEN")


@contextmanager
def _path_directory_fd(path: Path, code: str) -> Iterator[int]:
    """Resolve an absolute directory root-to-leaf without following symlinks."""
    absolute = _absolute(path, code)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(absolute.anchor, flags)
    except OSError as error:
        raise RetentionError(code) from error
    try:
        for part in absolute.parts[1:]:
            if part in {"", ".", ".."}:
                raise RetentionError(code)
            child: int | None = None
            try:
                before = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                if not stat.S_ISDIR(before.st_mode):
                    if stat.S_ISLNK(before.st_mode):
                        raise RetentionError("SYMLINK_FORBIDDEN")
                    raise RetentionError(code)
                child = os.open(part, flags, dir_fd=descriptor)
                opened = os.fstat(child)
            except OSError as error:
                if child is not None:
                    with suppress(OSError):
                        os.close(child)
                raise RetentionError(code) from error
            if not _same_open_directory(before, opened):
                os.close(child)
                raise RetentionError(code)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _anchored_directory_fd(
    descriptor: int,
    parts: tuple[str, ...],
    code: str,
) -> Iterator[int]:
    current = os.dup(descriptor)
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        for part in parts:
            if part in {"", ".", ".."}:
                raise RetentionError(code)
            child: int | None = None
            try:
                before = os.stat(part, dir_fd=current, follow_symlinks=False)
                if not stat.S_ISDIR(before.st_mode):
                    if stat.S_ISLNK(before.st_mode):
                        raise RetentionError("SYMLINK_FORBIDDEN")
                    raise RetentionError(code)
                child = os.open(part, flags, dir_fd=current)
                opened = os.fstat(child)
            except OSError as error:
                if child is not None:
                    with suppress(OSError):
                        os.close(child)
                raise RetentionError(code) from error
            if not _same_open_directory(before, opened):
                os.close(child)
                raise RetentionError(code)
            os.close(current)
            current = child
        yield current
    finally:
        os.close(current)


@contextmanager
def _private_child_directory_fd(
    parent_fd: int,
    name: str,
    code: str,
) -> Iterator[int]:
    if name in {"", ".", ".."} or "/" in name:
        raise RetentionError(code)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor: int | None = None
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode):
            raise RetentionError("SYMLINK_FORBIDDEN")
        if not stat.S_ISDIR(before.st_mode) or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o700:
            raise RetentionError(code)
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        opened = os.fstat(descriptor)
    except OSError as error:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        raise RetentionError(code) from error
    if not _same_open_directory(before, opened):
        os.close(descriptor)
        raise RetentionError(code)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _directory_fd(path: Path, code: str) -> Iterator[int]:
    """Open a directory, anchored to the locked control tree when active."""
    absolute = _absolute(path, code)
    context = _ACTIVE_CONTROL_CONTEXT.get()
    anchored = None if context is None else context.anchor(absolute)
    if anchored is None:
        with _path_directory_fd(absolute, code) as descriptor:
            yield descriptor
        return
    with _anchored_directory_fd(*anchored, code) as descriptor:
        yield descriptor


@contextmanager
def _control_directory_context(
    run_control: Path,
    inspections: Path,
    events: Path,
) -> Iterator[_ControlDirectoryContext]:
    if inspections != run_control / "inspections" or events != run_control / "events":
        raise RetentionError("CONTROL_PUBLICATION_FAILED")
    with _path_directory_fd(run_control, "CONTROL_PUBLICATION_FAILED") as run_fd:
        run_stat = os.fstat(run_fd)
        if not stat.S_ISDIR(run_stat.st_mode) or run_stat.st_uid != os.getuid() or stat.S_IMODE(run_stat.st_mode) != 0o700:
            raise RetentionError("CONTROL_PUBLICATION_FAILED")
        with (
            _private_child_directory_fd(run_fd, "inspections", "CONTROL_PUBLICATION_FAILED") as inspections_fd,
            _private_child_directory_fd(run_fd, "events", "CONTROL_PUBLICATION_FAILED") as events_fd,
        ):
            context = _ControlDirectoryContext(
                run_control=run_control,
                run_control_fd=run_fd,
                inspections_fd=inspections_fd,
                events_fd=events_fd,
                run_control_identity=_directory_identity(run_stat),
                inspections_identity=_directory_identity(os.fstat(inspections_fd)),
                events_identity=_directory_identity(os.fstat(events_fd)),
            )
            token = _ACTIVE_CONTROL_CONTEXT.set(context)
            try:
                yield context
            finally:
                _ACTIVE_CONTROL_CONTEXT.reset(token)


def _assert_control_namespace(context: _ControlDirectoryContext) -> None:
    try:
        with (
            _path_directory_fd(context.run_control, "CONTROL_PUBLICATION_FAILED") as run_fd,
            _private_child_directory_fd(run_fd, "inspections", "CONTROL_PUBLICATION_FAILED") as inspections_fd,
            _private_child_directory_fd(run_fd, "events", "CONTROL_PUBLICATION_FAILED") as events_fd,
        ):
            current_identities = (
                _directory_identity(os.fstat(run_fd)),
                _directory_identity(os.fstat(inspections_fd)),
                _directory_identity(os.fstat(events_fd)),
            )
    except (OSError, RetentionError) as error:
        raise RetentionError("CONTROL_PUBLICATION_FAILED") from error
    expected_identities = (
        context.run_control_identity,
        context.inspections_identity,
        context.events_identity,
    )
    if any(current[:4] != expected[:4] for current, expected in zip(current_identities, expected_identities, strict=True)):
        raise RetentionError("CONTROL_PUBLICATION_FAILED")


def _stable_bytes(path: Path, code: str, *, limit: int = MAX_CONFIG_BYTES) -> bytes:
    _assert_no_symlink_components(path, code)
    with _directory_fd(path.parent, code) as parent_fd:
        try:
            before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as error:
            raise RetentionError(code) from error
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid():
            raise RetentionError(code)
        if before.st_size > limit:
            raise RetentionError(code)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(path.name, flags, dir_fd=parent_fd)
        except OSError as error:
            raise RetentionError(code) from error
        chunks: list[bytes] = []
        total = 0
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(before):
                raise RetentionError(code)
            while chunk := os.read(descriptor, min(65536, limit + 1)):
                total += len(chunk)
                if total > limit:
                    raise RetentionError(code)
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        try:
            current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as error:
            raise RetentionError(code) from error
        if any(_identity(item) != _identity(before) for item in (opened, after, current)):
            raise RetentionError(code)
        content = b"".join(chunks)
        if len(content) != before.st_size:
            raise RetentionError(code)
        return content


def _load_json_bytes(path: Path, code: str) -> tuple[dict[str, Any], bytes]:
    content = _stable_bytes(path, code)
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RetentionError(code) from error
    if not isinstance(value, dict):
        raise RetentionError(code)
    return value, content


def _expected_digest(value: object) -> str:
    if not _hash(value):
        raise RetentionError("EXPECTED_DIGEST_INVALID")
    return value


def _expected_for_path(
    path: Path,
    expected: str | None,
    *,
    default_path: Path,
    default_digest: str,
) -> str:
    if path == default_path:
        if expected is None:
            return default_digest
        if _expected_digest(expected) != default_digest:
            raise RetentionError("EXPECTED_DIGEST_INVALID")
        return default_digest
    if expected is None:
        raise RetentionError("EXPECTED_DIGEST_INVALID")
    return _expected_digest(expected)


def load_secret_rules(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> SecretRules:
    expected = _expected_for_path(
        path,
        expected_sha256,
        default_path=DEFAULT_RULES,
        default_digest=DEFAULT_RULES_SHA256,
    )
    document, content = _load_json_bytes(path, "RULE_SCHEMA_INVALID")
    content_sha256 = _sha256(content)
    if content_sha256 != expected:
        raise RetentionError("RULE_TRUST_MISMATCH")
    _exact(
        document,
        {"schema", "schema_version", "rule_set_id", "scanner_id", "chunk_bytes", "rules"},
        "RULE_SCHEMA_INVALID",
    )
    version = document["schema_version"]
    chunk_bytes = document["chunk_bytes"]
    raw_rules = document["rules"]
    if (
        document["schema"] != RULES_SCHEMA
        or version != 1
        or isinstance(version, bool)
        or not _safe_id(document["rule_set_id"])
        or document["scanner_id"] != SCANNER_ID
        or not isinstance(chunk_bytes, int)
        or isinstance(chunk_bytes, bool)
        or not 64 <= chunk_bytes <= 1024 * 1024
        or not isinstance(raw_rules, list)
        or not raw_rules
    ):
        raise RetentionError("RULE_SCHEMA_INVALID")
    parsed: list[SecretRule] = []
    for raw in raw_rules:
        item = _exact(
            raw,
            {"rule_id", "category", "matcher", "terms", "max_value_bytes"},
            "RULE_SCHEMA_INVALID",
        )
        terms = item["terms"]
        maximum = item["max_value_bytes"]
        if (
            not isinstance(item["rule_id"], str)
            or RULE_ID.fullmatch(item["rule_id"]) is None
            or not isinstance(item["category"], str)
            or CATEGORY.fullmatch(item["category"]) is None
            or not isinstance(item["matcher"], str)
            or item["matcher"] not in MATCHERS
            or not isinstance(terms, list)
            or not terms
            or not all(isinstance(term, str) for term in terms)
            or terms != sorted(set(terms))
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
        ):
            raise RetentionError("RULE_SCHEMA_INVALID")
        encoded: list[bytes] = []
        for term in terms:
            try:
                raw_term = term.encode("ascii")
            except UnicodeEncodeError as error:
                raise RetentionError("RULE_SCHEMA_INVALID") from error
            if not 1 <= len(raw_term) <= 128 or any(byte < 32 or byte > 126 for byte in raw_term):
                raise RetentionError("RULE_SCHEMA_INVALID")
            encoded.append(raw_term)
        if len({term.lower() for term in encoded}) != len(encoded):
            raise RetentionError("RULE_SCHEMA_INVALID")
        if item["matcher"].startswith("literal-"):
            if maximum != 0:
                raise RetentionError("RULE_SCHEMA_INVALID")
        elif not 1 <= maximum <= 4096:
            raise RetentionError("RULE_SCHEMA_INVALID")
        parsed.append(SecretRule(item["rule_id"], item["category"], item["matcher"], tuple(encoded), maximum))
    identifiers = [rule.rule_id for rule in parsed]
    if identifiers != sorted(set(identifiers)):
        raise RetentionError("RULE_SCHEMA_INVALID")
    return SecretRules(document["rule_set_id"], document["scanner_id"], chunk_bytes, tuple(parsed), content, content_sha256)


def load_retention_assessment(
    path: Path,
    *,
    rules: SecretRules,
    expected_sha256: str | None = None,
) -> RetentionAssessment:
    expected = _expected_for_path(
        path,
        expected_sha256,
        default_path=DEFAULT_ASSESSMENT,
        default_digest=DEFAULT_ASSESSMENT_SHA256,
    )
    document, content = _load_json_bytes(path, "ASSESSMENT_SCHEMA_INVALID")
    content_sha256 = _sha256(content)
    if content_sha256 != expected:
        raise RetentionError("ASSESSMENT_TRUST_MISMATCH")
    _exact(
        document,
        {
            "schema",
            "schema_version",
            "assessment_id",
            "created_at_utc",
            "mode",
            "decision_state",
            "capabilities",
            "classifications",
            "decisions",
            "scanner",
        },
        "ASSESSMENT_SCHEMA_INVALID",
    )
    version = document["schema_version"]
    if document["mode"] != "assessment-only":
        raise RetentionError("ASSESSMENT_NOT_SAFE")
    if (
        document["schema"] != ASSESSMENT_SCHEMA
        or version != SCHEMA_VERSION
        or isinstance(version, bool)
        or not _safe_id(document["assessment_id"])
        or not _timestamp(document["created_at_utc"])
        or document["decision_state"] != "pending-human-approval"
    ):
        raise RetentionError("ASSESSMENT_SCHEMA_INVALID")
    capabilities = _exact(
        document["capabilities"],
        {"archive", "destroy", "expire", "inspect", "prepare_export", "scan"},
        "ASSESSMENT_SCHEMA_INVALID",
    )
    if capabilities != {
        "archive": False,
        "destroy": False,
        "expire": False,
        "inspect": True,
        "prepare_export": False,
        "scan": True,
    }:
        raise RetentionError("ASSESSMENT_NOT_SAFE")
    classifications = document["classifications"]
    if (
        not isinstance(classifications, list)
        or classifications != sorted(CLASSIFICATIONS)
        or classifications != sorted(set(classifications))
    ):
        raise RetentionError("ASSESSMENT_SCHEMA_INVALID")
    decisions = _exact(document["decisions"], ASSESSMENT_DECISIONS, "ASSESSMENT_SCHEMA_INVALID")
    for raw in decisions.values():
        item = _exact(raw, {"decision_id", "status", "value"}, "ASSESSMENT_SCHEMA_INVALID")
        if item != {"decision_id": None, "status": "unresolved", "value": None}:
            raise RetentionError("ASSESSMENT_NOT_SAFE")
    scanner = _exact(document["scanner"], {"rule_set_id", "rule_set_sha256", "max_file_bytes", "on_error"}, "ASSESSMENT_SCHEMA_INVALID")
    maximum = scanner["max_file_bytes"]
    if (
        not _safe_id(scanner["rule_set_id"])
        or not _hash(scanner["rule_set_sha256"])
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or maximum <= 0
        or scanner["on_error"] != "block"
    ):
        raise RetentionError("ASSESSMENT_SCHEMA_INVALID")
    if scanner["rule_set_id"] != rules.rule_set_id:
        raise RetentionError("RULE_SET_ID_MISMATCH")
    if scanner["rule_set_sha256"] != rules.sha256:
        raise RetentionError("RULE_BINDING_MISMATCH")
    return RetentionAssessment(document["assessment_id"], maximum, content, content_sha256, document)


def _walk_retention_tree(
    descriptor: int,
    prefix: PurePosixPath | None,
    *,
    budget: _SnapshotBudget,
    snapshot: dict[str, tuple[int, int, int, int, int, int, int, int]],
) -> None:
    """Walk only through an already pinned directory descriptor."""
    items: list[
        tuple[
            str,
            os.stat_result,
            PurePosixPath,
            tuple[int, int, int, int, int, int, int, int],
        ]
    ] = []
    try:
        with os.scandir(descriptor) as entries:
            for entry in entries:
                if entry.name in {"", ".", ".."} or "/" in entry.name:
                    raise RetentionError("UNSAFE_FILE_TYPE")
                try:
                    item_stat = os.stat(
                        entry.name,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                except OSError as error:
                    raise RetentionError("UNSAFE_FILE_TYPE") from error
                if stat.S_ISLNK(item_stat.st_mode):
                    raise RetentionError("SYMLINK_FORBIDDEN")
                if item_stat.st_uid != os.getuid() or item_stat.st_mode & 0o222:
                    raise RetentionError("UNSAFE_FILE_TYPE")
                if stat.S_ISREG(item_stat.st_mode):
                    if item_stat.st_nlink != 1:
                        raise RetentionError("HARDLINK_FORBIDDEN")
                elif not stat.S_ISDIR(item_stat.st_mode):
                    raise RetentionError("UNSAFE_FILE_TYPE")
                relative = (
                    PurePosixPath(entry.name)
                    if prefix is None
                    else prefix / entry.name
                )
                item_identity = _identity(item_stat)
                budget.reserve(relative.as_posix(), item_identity)
                items.append((entry.name, item_stat, relative, item_identity))
    except OSError as error:
        raise RetentionError("UNSAFE_FILE_TYPE") from error
    for name, item_stat, relative, item_identity in sorted(items):
        snapshot[relative.as_posix()] = item_identity
        if stat.S_ISREG(item_stat.st_mode):
            continue
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        child_fd: int | None = None
        try:
            child_fd = os.open(name, flags, dir_fd=descriptor)
            opened = os.fstat(child_fd)
        except OSError as error:
            if child_fd is not None:
                with suppress(OSError):
                    os.close(child_fd)
            raise RetentionError("UNSAFE_FILE_TYPE") from error
        if not _same_open_directory(opened, item_stat):
            os.close(child_fd)
            raise RetentionError("FILE_CHANGED_DURING_SCAN")
        try:
            _walk_retention_tree(
                child_fd,
                relative,
                budget=budget,
                snapshot=snapshot,
            )
        finally:
            os.close(child_fd)


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int, int, int, int, int, int, int]]:
    _assert_no_symlink_components(root, "SYMLINK_FORBIDDEN")
    result: dict[str, tuple[int, int, int, int, int, int, int, int]] = {}
    budget = _SnapshotBudget()

    with _directory_fd(root, "SYMLINK_FORBIDDEN") as root_fd:
        try:
            root_stat = os.fstat(root_fd)
        except OSError as error:
            raise RetentionError("UNSAFE_FILE_TYPE") from error
        if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_uid != os.getuid() or root_stat.st_mode & 0o222:
            raise RetentionError("UNSAFE_FILE_TYPE")
        root_identity = _identity(root_stat)
        budget.reserve(".", root_identity, is_root=True)
        result["."] = root_identity
        _walk_retention_tree(root_fd, None, budget=budget, snapshot=result)
    return result


@contextmanager
def _relative_parent_fd(root_fd: int, relative: str, code: str) -> Iterator[tuple[int, str]]:
    path = PurePosixPath(relative)
    if path.is_absolute() or path.as_posix() != relative or any(part in {"", ".", ".."} for part in path.parts):
        raise RetentionError(code)
    descriptor = os.dup(root_fd)
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        for part in path.parts[:-1]:
            child_fd: int | None = None
            try:
                before = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                child_fd = os.open(part, flags, dir_fd=descriptor)
                opened = os.fstat(child_fd)
            except OSError as error:
                if child_fd is not None:
                    with suppress(OSError):
                        os.close(child_fd)
                raise RetentionError(code) from error
            if not stat.S_ISDIR(before.st_mode) or not _same_open_directory(before, opened):
                os.close(child_fd)
                raise RetentionError(code)
            os.close(descriptor)
            descriptor = child_fd
        yield descriptor, path.name
    finally:
        os.close(descriptor)


def _assert_same_tree(root: Path, expected: dict[str, tuple[int, int, int, int, int, int, int, int]]) -> None:
    if _tree_snapshot(root) != expected:
        raise RetentionError("FILE_CHANGED_DURING_SCAN")


def _classify(relative: str) -> str:
    path = PurePosixPath(relative)
    if relative in {"receipt.json", "SEALED"}:
        return "metadata"
    if not path.parts:
        return "unknown"
    return {"inputs": "captured-input", "artifacts": "test-evidence", "source": "source-raw", "logs": "log-raw", "checkpoints": "checkpoint"}.get(path.parts[0], "unknown")


def _ascii_space(byte: int) -> bool:
    return byte in b" \t\r\n\v\f"


def _token_byte(byte: int) -> bool:
    return 48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122 or byte == 95


def _window_hits(
    content: bytes,
    base: int,
    rules: SecretRules,
    *,
    seen: set[tuple[str, int, int]],
    limit: int,
) -> tuple[set[tuple[str, int, int]], bool]:
    lowered = content.lower()
    hits: set[tuple[str, int, int]] = set()

    def add(hit: tuple[str, int, int]) -> bool:
        if hit in seen or hit in hits:
            return True
        if len(seen) + len(hits) >= limit:
            return False
        hits.add(hit)
        return True

    for rule in rules.rules:
        for term in rule.terms:
            needle = term if rule.matcher == "literal-ascii" else term.lower()
            haystack = content if rule.matcher == "literal-ascii" else lowered
            start = 0
            while True:
                index = haystack.find(needle, start)
                if index < 0:
                    break
                end = index + len(needle)
                if rule.matcher.startswith("literal-"):
                    if not add((rule.rule_id, base + index, base + end)):
                        return hits, True
                elif rule.matcher == "scheme-value-ascii-ci":
                    cursor = end
                    spaces = 0
                    while cursor < len(content) and _ascii_space(content[cursor]) and spaces < MAX_WHITESPACE:
                        cursor += 1
                        spaces += 1
                    value_start = cursor
                    while cursor < len(content) and not _ascii_space(content[cursor]) and 32 <= content[cursor] <= 126 and cursor - value_start < rule.max_value_bytes:
                        cursor += 1
                    if spaces and cursor > value_start and not add((rule.rule_id, base + index, base + cursor)):
                        return hits, True
                else:
                    before_ok = index == 0 or not _token_byte(content[index - 1])
                    cursor = end
                    after_ok = cursor == len(content) or not _token_byte(content[cursor])
                    spaces = 0
                    while cursor < len(content) and _ascii_space(content[cursor]) and spaces < MAX_WHITESPACE:
                        cursor += 1
                        spaces += 1
                    if cursor < len(content) and content[cursor] in b":=":
                        cursor += 1
                        spaces = 0
                        while cursor < len(content) and _ascii_space(content[cursor]) and spaces < MAX_WHITESPACE:
                            cursor += 1
                            spaces += 1
                        quote = content[cursor] if cursor < len(content) and content[cursor] in b"\"'" else None
                        if quote is not None:
                            cursor += 1
                        value_start = cursor
                        while cursor < len(content) and not _ascii_space(content[cursor]) and 32 <= content[cursor] <= 126 and (quote is None or content[cursor] != quote) and cursor - value_start < rule.max_value_bytes:
                            cursor += 1
                        if before_ok and after_ok and cursor > value_start and not add((rule.rule_id, base + index, base + cursor)):
                            return hits, True
                start = index + max(1, len(needle))
    return hits, False


def _scan_file(root_fd: int, relative: str, expected: tuple[int, int, int, int, int, int, int, int], rules: SecretRules, maximum: int, hit_limit: int) -> tuple[dict[str, object], list[dict[str, object]], bool]:
    reported_path = _report_path(relative)
    classification = _classify(relative)
    errors: list[dict[str, object]] = []
    if classification == "unknown":
        errors.append({"code": "CLASSIFICATION_UNKNOWN", "path": reported_path})
    size = expected[5]
    if size > maximum:
        errors.append({"code": "SCAN_LIMIT_EXCEEDED", "path": reported_path})
        return {"path": reported_path, "size": size, "sha256": None, "classification": classification, "hits": []}, errors, False
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = -1
    current: os.stat_result | None = None
    with _relative_parent_fd(root_fd, relative, "FILE_CHANGED_DURING_SCAN") as (parent_fd, leaf):
        try:
            before = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            descriptor = os.open(leaf, flags, dir_fd=parent_fd)
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid() or opened.st_nlink != 1 or _identity(opened) != expected or _identity(before) != expected:
                raise RetentionError("FILE_CHANGED_DURING_SCAN")
            digest = hashlib.sha256()
            count = 0
            overlap = max(len(term) + rule.max_value_bytes + 2 * MAX_WHITESPACE + 4 for rule in rules.rules for term in rule.terms)
            tail = b""
            findings: set[tuple[str, int, int]] = set()
            hit_limit_exceeded = False
            while chunk := os.read(descriptor, rules.chunk_bytes):
                digest.update(chunk)
                window = tail + chunk
                if not hit_limit_exceeded:
                    window_hits, hit_limit_exceeded = _window_hits(
                        window,
                        count - len(tail),
                        rules,
                        seen=findings,
                        limit=hit_limit,
                    )
                    findings.update(window_hits)
                count += len(chunk)
                tail = window[-overlap:]
            after = os.fstat(descriptor)
            current = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except (OSError, RetentionError):
            errors.append({"code": "FILE_CHANGED_DURING_SCAN", "path": reported_path})
            return {"path": reported_path, "size": size, "sha256": None, "classification": classification, "hits": []}, errors, False
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    if current is None or any(_identity(value) != expected for value in (opened, after, current)) or count != size:
        errors.append({"code": "FILE_CHANGED_DURING_SCAN", "path": reported_path})
        return {"path": reported_path, "size": size, "sha256": None, "classification": classification, "hits": []}, errors, False
    hits = [{"rule_id": rule_id, "start_byte": start, "end_byte": end} for rule_id, start, end in sorted(findings) if 0 <= start < end <= size]
    if hits or hit_limit_exceeded:
        errors.append({"code": "SECRET_MATCHED", "path": reported_path})
    return {"path": reported_path, "size": size, "sha256": digest.hexdigest(), "classification": classification, "hits": hits}, errors, hit_limit_exceeded


def _scan_tree(root: Path, snapshot: dict[str, tuple[int, int, int, int, int, int, int, int]], rules: SecretRules, maximum: int) -> tuple[list[dict[str, object]], list[dict[str, object]], str]:
    files: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    if len(snapshot) - int("." in snapshot) > MAX_RUN_ENTRIES:
        raise RetentionError("SCAN_RUN_LIMIT_EXCEEDED")
    budget = _SnapshotBudget()
    regular_items: list[
        tuple[str, tuple[int, int, int, int, int, int, int, int]]
    ] = []
    for relative, identity in sorted(snapshot.items()):
        budget.reserve(relative, identity, is_root=relative == ".")
        if relative != "." and stat.S_ISREG(identity[3]):
            regular_items.append((relative, identity))
    if len(regular_items) > MAX_RUN_FILES or sum(identity[5] for _, identity in regular_items) > MAX_RUN_BYTES:
        raise RetentionError("SCAN_RUN_LIMIT_EXCEEDED")
    remaining_hits = MAX_TOTAL_HITS
    hit_limit_exceeded = False
    with _directory_fd(root, "FILE_CHANGED_DURING_SCAN") as root_fd:
        if _identity(os.fstat(root_fd)) != snapshot["."]:
            raise RetentionError("FILE_CHANGED_DURING_SCAN")
        for relative, identity in regular_items:
            record, file_errors, file_hit_limit = _scan_file(
                root_fd,
                relative,
                identity,
                rules,
                maximum,
                remaining_hits,
            )
            files.append(record)
            errors.extend(file_errors)
            remaining_hits -= len(record["hits"])
            if file_hit_limit:
                hit_limit_exceeded = True
                remaining_hits = 0
    if hit_limit_exceeded:
        errors.append({"code": "SCAN_HIT_LIMIT_EXCEEDED", "path": None})
    unique_errors = sorted({("" if item["path"] is None else str(item["path"]), str(item["code"])) for item in errors})
    errors = [{"code": code, "path": None if path == "" else path} for path, code in unique_errors]
    metadata = _compact_bytes({"files": [{**record, "hits": []} for record in files], "errors": errors})
    if len(metadata) > MAX_REPORT_METADATA_BYTES:
        raise RetentionError("SCAN_RUN_LIMIT_EXCEEDED")
    aggregate = hashlib.sha256(b"ai-auto-lrc/secret-scan/v1\0" + _compact_bytes({"files": files, "errors": errors})).hexdigest()
    return files, errors, aggregate


def _state(report: dict[str, Any]) -> Literal["SCANNED_PASS", "SCANNED_BLOCKED"]:
    return "SCANNED_BLOCKED" if report["errors"] or any(item["hits"] for item in report["files"]) else "SCANNED_PASS"


def _build_report(*, document: dict[str, Any], receipt_content: bytes, sealed_content: bytes, inspection_id: str, created_at: str, rules: SecretRules, assessment: RetentionAssessment, files: list[dict[str, object]], errors: list[dict[str, object]], aggregate: str) -> dict[str, Any]:
    return {"schema": SCAN_SCHEMA, "schema_version": 1, "run_id": document["run_id"], "layer": document["claim"]["layer"], "inspection_id": inspection_id, "receipt_sha256": _sha256(receipt_content), "sealed_sha256": _sha256(sealed_content), "rules_sha256": rules.sha256, "assessment_sha256": assessment.sha256, "scanner_id": rules.scanner_id, "mode": "assessment", "files": files, "errors": errors, "export_allowed": False, "created_at": created_at, "aggregate_sha256": aggregate}


def _validate_report(report: dict[str, Any], rules: SecretRules, assessment: RetentionAssessment) -> None:
    _exact(report, {"schema", "schema_version", "run_id", "layer", "inspection_id", "receipt_sha256", "sealed_sha256", "rules_sha256", "assessment_sha256", "scanner_id", "mode", "files", "errors", "export_allowed", "created_at", "aggregate_sha256"}, "INSPECTION_INVALID")
    version = report["schema_version"]
    if report["schema"] != SCAN_SCHEMA or version != 1 or isinstance(version, bool) or not _safe_id(report["run_id"]) or not _safe_id(report["inspection_id"]) or report["layer"] not in capture_test_gate.LAYERS or not all(_hash(report[key]) for key in ("receipt_sha256", "sealed_sha256", "rules_sha256", "assessment_sha256", "aggregate_sha256")) or report["rules_sha256"] != rules.sha256 or report["assessment_sha256"] != assessment.sha256 or report["scanner_id"] != rules.scanner_id or report["mode"] != "assessment" or report["export_allowed"] is not False or not _timestamp(report["created_at"]) or not isinstance(report["files"], list) or not isinstance(report["errors"], list):
        raise RetentionError("INSPECTION_INVALID")
    known_rules = {rule.rule_id for rule in rules.rules}
    paths: list[str] = []
    for record in report["files"]:
        _exact(record, {"path", "size", "sha256", "classification", "hits"}, "INSPECTION_INVALID")
        relative = record["path"]
        path = PurePosixPath(relative) if isinstance(relative, str) else None
        size = record["size"]
        if path is None or path.is_absolute() or path.as_posix() != relative or any(part in {"", ".", ".."} for part in path.parts) or not isinstance(record["classification"], str) or record["classification"] != _classify(relative) or record["classification"] not in CLASSIFICATIONS or not isinstance(size, int) or isinstance(size, bool) or size < 0 or (record["sha256"] is not None and not _hash(record["sha256"])) or not isinstance(record["hits"], list):
            raise RetentionError("INSPECTION_INVALID")
        hits: list[tuple[str, int, int]] = []
        for hit in record["hits"]:
            _exact(hit, {"rule_id", "start_byte", "end_byte"}, "INSPECTION_INVALID")
            values = (hit["rule_id"], hit["start_byte"], hit["end_byte"])
            if not isinstance(values[0], str) or values[0] not in known_rules or not isinstance(values[1], int) or isinstance(values[1], bool) or not isinstance(values[2], int) or isinstance(values[2], bool) or not 0 <= values[1] < values[2] <= size:
                raise RetentionError("INSPECTION_INVALID")
            hits.append(values)
        if hits != sorted(set(hits)):
            raise RetentionError("INSPECTION_INVALID")
        paths.append(relative)
    if paths != sorted(set(paths)):
        raise RetentionError("INSPECTION_INVALID")
    valid_codes = {"CLOSURE_MISMATCH", "UNSAFE_FILE_TYPE", "SYMLINK_FORBIDDEN", "HARDLINK_FORBIDDEN", "CLASSIFICATION_UNKNOWN", "FILE_CHANGED_DURING_SCAN", "SCAN_RULE_ERROR", "SCAN_LIMIT_EXCEEDED", "SCAN_HIT_LIMIT_EXCEEDED", "SECRET_MATCHED"}
    errors: list[tuple[str, str]] = []
    for item in report["errors"]:
        _exact(item, {"code", "path"}, "INSPECTION_INVALID")
        if not isinstance(item["code"], str) or item["code"] not in valid_codes or (item["path"] is not None and (not isinstance(item["path"], str) or item["path"] not in paths)):
            raise RetentionError("INSPECTION_INVALID")
        errors.append(("" if item["path"] is None else item["path"], item["code"]))
    if errors != sorted(set(errors)):
        raise RetentionError("INSPECTION_INVALID")
    expected = hashlib.sha256(b"ai-auto-lrc/secret-scan/v1\0" + _compact_bytes({"files": report["files"], "errors": report["errors"]})).hexdigest()
    if report["aggregate_sha256"] != expected:
        raise RetentionError("INSPECTION_INVALID")


def _private_dir(path: Path) -> None:
    _assert_no_symlink_components(path.parent, "SYMLINK_FORBIDDEN")
    with _directory_fd(path.parent, "SYMLINK_FORBIDDEN") as parent_fd:
        with suppress(FileExistsError):
            os.mkdir(path.name, mode=0o700, dir_fd=parent_fd)
        child_fd: int | None = None
        try:
            item = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            child_fd = os.open(path.name, flags, dir_fd=parent_fd)
            opened = os.fstat(child_fd)
            os.close(child_fd)
        except OSError as error:
            if child_fd is not None:
                with suppress(OSError):
                    os.close(child_fd)
            raise RetentionError("CONTROL_PUBLICATION_FAILED") from error
        if not _same_open_directory(item, opened) or not stat.S_ISDIR(item.st_mode) or stat.S_IMODE(item.st_mode) != 0o700 or item.st_uid != os.getuid():
            raise RetentionError("CONTROL_PUBLICATION_FAILED")


def _create_private_dir(path: Path) -> None:
    _assert_no_symlink_components(path.parent, "SYMLINK_FORBIDDEN")
    with _directory_fd(path.parent, "CONTROL_PUBLICATION_FAILED") as parent_fd:
        try:
            os.mkdir(path.name, mode=0o700, dir_fd=parent_fd)
        except OSError as error:
            raise RetentionError("CONTROL_PUBLICATION_FAILED") from error
    _private_dir(path)


def _directory_entries(path: Path, code: str) -> dict[str, os.stat_result]:
    with _directory_fd(path, code) as descriptor:
        try:
            names = os.listdir(descriptor)
            return {
                name: os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                for name in names
            }
        except OSError as error:
            raise RetentionError(code) from error


def _unlink_control_file(path: Path) -> None:
    with _directory_fd(path.parent, "CONTROL_PUBLICATION_FAILED") as parent_fd, suppress(FileNotFoundError):
        os.unlink(path.name, dir_fd=parent_fd)


def _private_file(path: Path) -> None:
    with _directory_fd(path.parent, "INSPECTION_INVALID") as parent_fd:
        try:
            item = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as error:
            raise RetentionError("INSPECTION_INVALID") from error
        if not stat.S_ISREG(item.st_mode) or item.st_nlink != 1 or item.st_uid != os.getuid() or stat.S_IMODE(item.st_mode) != 0o600:
            raise RetentionError("INSPECTION_INVALID")


def _write_exclusive(path: Path, content: bytes) -> None:
    with _directory_fd(path.parent, "CONTROL_PUBLICATION_FAILED") as parent_fd:
        descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=parent_fd)
        try:
            created = os.fstat(descriptor)
            if not stat.S_ISREG(created.st_mode) or created.st_nlink != 1 or created.st_uid != os.getuid() or stat.S_IMODE(created.st_mode) != 0o600:
                raise RetentionError("CONTROL_PUBLICATION_FAILED")
            offset = 0
            while offset < len(content):
                offset += os.write(descriptor, content[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _fsync_dir(path: Path) -> None:
    with _directory_fd(path, "CONTROL_PUBLICATION_FAILED") as descriptor:
        os.fsync(descriptor)


def _rename_noreplace(source: Path, target: Path) -> None:
    with _directory_fd(source.parent, "CONTROL_PUBLICATION_FAILED") as source_fd, _directory_fd(target.parent, "CONTROL_PUBLICATION_FAILED") as target_fd:
        try:
            source_stat = os.stat(source.name, dir_fd=source_fd, follow_symlinks=False)
        except OSError as error:
            raise RetentionError("CONTROL_PUBLICATION_FAILED") from error
        if not (stat.S_ISREG(source_stat.st_mode) or stat.S_ISDIR(source_stat.st_mode)):
            raise RetentionError("CONTROL_PUBLICATION_FAILED")
        try:
            os.stat(target.name, dir_fd=target_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise RetentionError("CONTROL_PUBLICATION_FAILED") from error
        else:
            raise FileExistsError(target)
        library = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin" and hasattr(library, "renameatx_np"):
            renameatx = library.renameatx_np
            renameatx.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            renameatx.restype = ctypes.c_int
            result = renameatx(source_fd, os.fsencode(source.name), target_fd, os.fsencode(target.name), 0x00000004)
        elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
            renameat2 = library.renameat2
            renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            renameat2.restype = ctypes.c_int
            result = renameat2(source_fd, os.fsencode(source.name), target_fd, os.fsencode(target.name), 1)
        else:
            raise RetentionError("NO_REPLACE_UNSUPPORTED")
        if result != 0:
            value = ctypes.get_errno()
            if value in {errno.EEXIST, errno.ENOTEMPTY}:
                raise FileExistsError(target)
            if value in {errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
                raise RetentionError("NO_REPLACE_UNSUPPORTED")
            raise OSError(value, os.strerror(value), os.fspath(target))
        commit_state = _ACTIVE_RENAME_COMMIT.get()
        if commit_state is not None:
            commit_state.committed = True
            commit_state.source_identity = _directory_identity(source_stat)
            return
        try:
            target_stat = os.stat(target.name, dir_fd=target_fd, follow_symlinks=False)
        except OSError as error:
            raise RetentionError("CONTROL_PUBLICATION_FAILED") from error
        source_identity = _directory_identity(source_stat)
        target_identity = _directory_identity(target_stat)
        if target_identity != source_identity:
            raise RetentionError("CONTROL_PUBLICATION_FAILED")


def _post_rename_identity(
    target: Path,
    expected: tuple[int, int, int, int, int] | None,
) -> None:
    with _directory_fd(target.parent, "CONTROL_PUBLICATION_FAILED") as target_fd:
        try:
            target_stat = os.stat(
                target.name,
                dir_fd=target_fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise RetentionError("CONTROL_PUBLICATION_FAILED") from error
    if expected is not None and _directory_identity(target_stat) != expected:
        raise RetentionError("CONTROL_PUBLICATION_FAILED")


def _cleanup_uncommitted_event(temporary: Path) -> None:
    with suppress(OSError, RetentionError):
        _unlink_control_file(temporary)


def _teardown_failure(operation: Callable[[], object]) -> Exception | None:
    try:
        operation()
    except Exception as error:  # noqa: BLE001 - teardown must preserve a primary error
        return error
    return None


def _publish_event(events: Path, content: bytes, sequence: int) -> Path:
    target = events / f"{sequence:08d}-{_sha256(content)}.json"
    temporary = events / f".incomplete-{uuid.uuid4().hex}"
    try:
        _write_exclusive(temporary, content)
    except (OSError, RetentionError):
        _cleanup_uncommitted_event(temporary)
        raise
    commit_state = _RenameCommitState()
    token = _ACTIVE_RENAME_COMMIT.set(commit_state)
    try:
        _rename_noreplace(temporary, target)
        commit_state.committed = True
    except (OSError, RetentionError) as error:
        if commit_state.committed:
            raise RetentionError("CONTROL_COMMIT_UNCERTAIN") from error
        _cleanup_uncommitted_event(temporary)
        raise
    finally:
        _ACTIVE_RENAME_COMMIT.reset(token)
    try:
        _post_rename_identity(target, commit_state.source_identity)
        _unlink_control_file(temporary)
        _private_file(target)
        _fsync_dir(events)
    except (OSError, RetentionError) as error:
        raise RetentionError("CONTROL_COMMIT_UNCERTAIN") from error
    return target


def _control_paths(receipt: Path, run_id: str) -> tuple[Path, Path, Path, Path]:
    control_root = receipt.parent.parent / ".control"
    run_control = control_root / run_id
    return control_root, run_control, run_control / "inspections", run_control / "events"


def _open_lock(run_control: Path) -> int:
    with _directory_fd(run_control, "CONTROL_PUBLICATION_FAILED") as run_fd:
        base_flags = (
            os.O_RDWR
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            descriptor = os.open(
                "LOCK",
                base_flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=run_fd,
            )
        except FileExistsError:
            try:
                descriptor = os.open("LOCK", base_flags, dir_fd=run_fd)
            except OSError as error:
                raise RetentionError("CONTROL_PUBLICATION_FAILED") from error
        except OSError as error:
            raise RetentionError("CONTROL_PUBLICATION_FAILED") from error
        try:
            item = os.fstat(descriptor)
            named_item = os.stat("LOCK", dir_fd=run_fd, follow_symlinks=False)
        except OSError as error:
            os.close(descriptor)
            raise RetentionError("CONTROL_PUBLICATION_FAILED") from error
        if (
            item.st_dev != named_item.st_dev
            or item.st_ino != named_item.st_ino
            or not stat.S_ISREG(item.st_mode)
            or item.st_nlink != 1
            or item.st_uid != os.getuid()
            or stat.S_IMODE(item.st_mode) != 0o600
        ):
            os.close(descriptor)
            raise RetentionError("CONTROL_PUBLICATION_FAILED")
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RetentionError("CONTROL_LOCKED") from None
        with _directory_fd(run_control, "CONTROL_PUBLICATION_FAILED") as run_fd:
            named_item = os.stat("LOCK", dir_fd=run_fd, follow_symlinks=False)
        item = os.fstat(descriptor)
        if item.st_dev != named_item.st_dev or item.st_ino != named_item.st_ino:
            raise RetentionError("CONTROL_PUBLICATION_FAILED")
        return descriptor
    except OSError as error:
        os.close(descriptor)
        raise RetentionError("CONTROL_PUBLICATION_FAILED") from error
    except BaseException:
        os.close(descriptor)
        raise


def _verify_receipt(receipt: Path, mode: str, repo_root: Path | None) -> dict[str, Any]:
    if mode == "current-source":
        if repo_root is None:
            raise RetentionError("RECEIPT_INVALID")
        _assert_no_symlink_components(repo_root, "SYMLINK_FORBIDDEN")
    elif mode != "archived-integrity" or repo_root is not None:
        raise RetentionError("RECEIPT_INVALID")
    if receipt.name != "receipt.json":
        raise RetentionError("RECEIPT_INVALID")
    try:
        with _directory_fd(receipt.parent, "RECEIPT_INVALID") as run_fd:
            if repo_root is None:
                document = capture_test_gate.verify_receipt_at(
                    run_fd,
                    receipt.name,
                    mode,
                )
            else:
                with _directory_fd(repo_root, "RECEIPT_INVALID") as repo_root_fd:
                    document = capture_test_gate.verify_receipt_at(
                        run_fd,
                        receipt.name,
                        mode,
                        repo_root_fd,
                    )
    except (capture_test_gate.CaptureError, OSError, ValueError) as error:
        raise RetentionError("RECEIPT_INVALID") from error
    if document.get("run_id") != receipt.parent.name:
        raise RetentionError("RECEIPT_INVALID")
    return document


def _remove_owned_staging(path: Path) -> None:
    if not path.name.startswith(".incomplete-"):
        return
    try:
        with _directory_fd(path.parent, "CONTROL_PUBLICATION_FAILED") as parent_fd:
            item = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISDIR(item.st_mode) or item.st_uid != os.getuid():
                return
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            child_fd = os.open(path.name, flags, dir_fd=parent_fd)
            try:
                names = os.listdir(child_fd)
                if not set(names).issubset(INSPECTION_FILES):
                    return
                for name in names:
                    child = os.stat(name, dir_fd=child_fd, follow_symlinks=False)
                    if not stat.S_ISREG(child.st_mode) or child.st_uid != os.getuid() or child.st_nlink != 1:
                        return
                for name in names:
                    os.unlink(name, dir_fd=child_fd)
                os.fsync(child_fd)
            finally:
                os.close(child_fd)
            os.rmdir(path.name, dir_fd=parent_fd)
            os.fsync(parent_fd)
    except (OSError, RetentionError):
        return


def _ledger_state(
    *,
    receipt: Path,
    inspections: Path,
    events: Path,
    rules_path: Path,
    assessment_path: Path,
    expected_rules_sha256: str,
    expected_assessment_sha256: str,
    mode: Literal["archived-integrity", "current-source"],
    repo_root: Path | None,
) -> str:
    inspection_entries = _directory_entries(inspections, "CONTROL_RECOVERY_REQUIRED")
    event_entries = _directory_entries(events, "CONTROL_RECOVERY_REQUIRED")
    if not inspection_entries and not event_entries:
        return "EMPTY"
    if any(name.startswith(".incomplete-") for name in [*inspection_entries, *event_entries]):
        return "STAGING_PRESENT"
    if inspection_entries and not event_entries:
        return "ORPHAN_INSPECTION"
    if len(inspection_entries) != 1 or len(event_entries) != 1:
        return "LEDGER_INVALID"
    inspection_name, inspection_stat = next(iter(inspection_entries.items()))
    event_name, event_stat = next(iter(event_entries.items()))
    if not stat.S_ISDIR(inspection_stat.st_mode) or not stat.S_ISREG(event_stat.st_mode):
        return "LEDGER_INVALID"
    inspection = inspections / inspection_name
    event = events / event_name
    try:
        verify_inspection(
            receipt=receipt,
            inspection=inspection,
            control_event=event,
            rules_path=rules_path,
            assessment_path=assessment_path,
            expected_rules_sha256=expected_rules_sha256,
            expected_assessment_sha256=expected_assessment_sha256,
            mode=mode,
            repo_root=repo_root,
        )
    except RetentionError:
        return "LEDGER_INVALID"
    return "COMMITTED_VALID"


def inspect_run(*, receipt: Path, rules_path: Path = DEFAULT_RULES, assessment_path: Path = DEFAULT_ASSESSMENT, expected_rules_sha256: str | None = None, expected_assessment_sha256: str | None = None, actor: str, mode: Literal["archived-integrity", "current-source"] = "archived-integrity", repo_root: Path | None = None) -> InspectionResult:
    if not _actor(actor):
        raise RetentionError("ASSESSMENT_SCHEMA_INVALID")
    if mode == "current-source":
        if repo_root is None:
            raise RetentionError("RECEIPT_INVALID")
        raise RetentionError("CURRENT_SOURCE_DIAGNOSTIC_ONLY")
    receipt = _absolute(receipt, "RECEIPT_INVALID")
    rules_path = _absolute(rules_path, "RULE_SCHEMA_INVALID")
    assessment_path = _absolute(assessment_path, "ASSESSMENT_SCHEMA_INVALID")
    for path, code in ((receipt, "RECEIPT_INVALID"), (rules_path, "RULE_SCHEMA_INVALID"), (assessment_path, "ASSESSMENT_SCHEMA_INVALID")):
        _assert_no_symlink_components(path, code)
    if repo_root is not None:
        _assert_no_symlink_components(repo_root, "SYMLINK_FORBIDDEN")
    rules = load_secret_rules(rules_path, expected_sha256=expected_rules_sha256)
    assessment = load_retention_assessment(assessment_path, rules=rules, expected_sha256=expected_assessment_sha256)
    source_root = receipt.parent
    initial_source = _tree_snapshot(source_root)
    document = _verify_receipt(receipt, mode, repo_root)
    _assert_same_tree(source_root, initial_source)
    run_id = document["run_id"]
    control_root, run_control, inspections, events = _control_paths(receipt, run_id)
    _assert_no_symlink_components(control_root, "SYMLINK_FORBIDDEN", missing_leaf=True)
    for directory in (control_root, run_control, inspections, events):
        _private_dir(directory)
    control_context_manager = _control_directory_context(
        run_control,
        inspections,
        events,
    )
    control_context = control_context_manager.__enter__()
    try:
        lock_descriptor = _open_lock(run_control)
    except BaseException:
        primary_info = sys.exc_info()
        with suppress(BaseException):
            control_context_manager.__exit__(*primary_info)
        raise
    staging: Path | None = None
    event_visible = False
    try:
        _assert_control_namespace(control_context)
        locked_source = _tree_snapshot(source_root)
        locked_rules = load_secret_rules(rules_path, expected_sha256=expected_rules_sha256)
        locked_assessment = load_retention_assessment(assessment_path, rules=locked_rules, expected_sha256=expected_assessment_sha256)
        locked_document = _verify_receipt(receipt, mode, repo_root)
        if locked_document != document or locked_rules.content != rules.content or locked_assessment.content != assessment.content:
            raise RetentionError("FILE_CHANGED_DURING_SCAN")
        ledger_state = _ledger_state(
            receipt=receipt,
            inspections=inspections,
            events=events,
            rules_path=rules_path,
            assessment_path=assessment_path,
            expected_rules_sha256=expected_rules_sha256,
            expected_assessment_sha256=expected_assessment_sha256,
            mode=mode,
            repo_root=repo_root,
        )
        if ledger_state == "COMMITTED_VALID":
            raise RetentionError("INSPECTION_ALREADY_COMMITTED")
        if ledger_state != "EMPTY":
            raise RetentionError("CONTROL_RECOVERY_REQUIRED")
        _assert_control_namespace(control_context)
        receipt_content = _stable_bytes(receipt, "FILE_CHANGED_DURING_SCAN", limit=64 * 1024 * 1024)
        sealed_content = _stable_bytes(source_root / "SEALED", "FILE_CHANGED_DURING_SCAN")
        files, errors, aggregate = _scan_tree(source_root, locked_source, locked_rules, locked_assessment.max_file_bytes)
        _assert_same_tree(source_root, locked_source)
        inspection_id = uuid.uuid4().hex
        created_at = _utc_now()
        report = _build_report(document=locked_document, receipt_content=receipt_content, sealed_content=sealed_content, inspection_id=inspection_id, created_at=created_at, rules=locked_rules, assessment=locked_assessment, files=files, errors=errors, aggregate=aggregate)
        _validate_report(report, locked_rules, locked_assessment)
        report_content = _json_bytes(report)
        if len(report_content) > MAX_REPORT_BYTES:
            raise RetentionError("REPORT_LIMIT_EXCEEDED")
        state = _state(report)
        marker_content = _json_bytes({"inspection_id": inspection_id, "inspection_sha256": _sha256(report_content), "state": state})
        staging = inspections / f".incomplete-{inspection_id}"
        _create_private_dir(staging)
        _write_exclusive(staging / "secret-scan.json", report_content)
        _write_exclusive(staging / "secret-rules.json", locked_rules.content)
        _write_exclusive(staging / "retention-assessment.json", locked_assessment.content)
        _write_exclusive(staging / "COMPLETE", marker_content)
        _fsync_dir(staging)
        _assert_same_tree(source_root, locked_source)
        _assert_control_namespace(control_context)
        published = inspections / inspection_id
        _rename_noreplace(staging, published)
        staging = None
        _fsync_dir(inspections)
        _assert_same_tree(source_root, locked_source)
        _assert_control_namespace(control_context)
        if (
            _stable_bytes(published / "secret-scan.json", "INSPECTION_INVALID", limit=MAX_REPORT_BYTES) != report_content
            or _stable_bytes(published / "secret-rules.json", "INSPECTION_INVALID") != locked_rules.content
            or _stable_bytes(published / "retention-assessment.json", "INSPECTION_INVALID") != locked_assessment.content
            or _stable_bytes(published / "COMPLETE", "INSPECTION_INVALID") != marker_content
        ):
            raise RetentionError("INSPECTION_INVALID")
        error_codes = sorted({item["code"] for item in errors})
        matched_rule_ids = sorted({hit["rule_id"] for record in files for hit in record["hits"]})
        event = {"schema": EVENT_SCHEMA, "schema_version": 1, "sequence": 1, "previous_event_sha256": None, "event_type": "INSPECTION_COMMITTED", "from_state": "LOCAL_SEALED", "to_state": state, "run_id": run_id, "receipt_sha256": _sha256(receipt_content), "assessment_sha256": locked_assessment.sha256, "actor_claim": actor, "actor_assurance": "self-asserted-local", "occurred_at": created_at, "details": {"inspection_id": inspection_id, "inspection_sha256": _sha256(report_content), "completion_sha256": _sha256(marker_content), "rules_sha256": locked_rules.sha256, "error_codes": error_codes, "matched_rule_ids": matched_rule_ids}}
        event_path = _publish_event(events, _json_bytes(event), 1)
        event_visible = True
        try:
            _assert_control_namespace(control_context)
            _fsync_dir(run_control)
            _assert_same_tree(source_root, locked_source)
            result = verify_inspection(receipt=receipt, inspection=published, control_event=event_path, rules_path=rules_path, assessment_path=assessment_path, expected_rules_sha256=expected_rules_sha256, expected_assessment_sha256=expected_assessment_sha256, mode=mode, repo_root=repo_root)
            _assert_same_tree(source_root, locked_source)
            _assert_control_namespace(control_context)
        except (OSError, RetentionError) as error:
            raise RetentionError("CONTROL_COMMIT_UNCERTAIN") from error
        return result
    except RetentionError:
        if staging is not None:
            _remove_owned_staging(staging)
        raise
    except (OSError, ValueError, TypeError) as error:
        if staging is not None:
            _remove_owned_staging(staging)
        raise RetentionError("CONTROL_PUBLICATION_FAILED") from error
    finally:
        primary_info = sys.exc_info()
        primary_error = primary_info[1]
        teardown_error: Exception | None = None
        for operation in (
            lambda: fcntl.flock(lock_descriptor, fcntl.LOCK_UN),
            lambda: os.close(lock_descriptor),
            lambda: control_context_manager.__exit__(*primary_info),
        ):
            error = _teardown_failure(operation)
            if teardown_error is None and error is not None:
                teardown_error = error
        if primary_error is None and teardown_error is not None:
            code = "CONTROL_COMMIT_UNCERTAIN" if event_visible else "CONTROL_PUBLICATION_FAILED"
            raise RetentionError(code) from teardown_error


def _load_control_json(path: Path, *, limit: int = MAX_CONFIG_BYTES) -> tuple[dict[str, Any], bytes]:
    content = _stable_bytes(path, "INSPECTION_INVALID", limit=limit)
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RetentionError("INSPECTION_INVALID") from error
    if not isinstance(value, dict):
        raise RetentionError("INSPECTION_INVALID")
    return value, content


def _validate_private_tree(run_control: Path, inspection: Path, event: Path) -> None:
    for directory in {
        run_control.parent,
        run_control,
        run_control / "inspections",
        run_control / "events",
        inspection,
    }:
        _assert_no_symlink_components(directory, "SYMLINK_FORBIDDEN")
        item = directory.lstat()
        if not stat.S_ISDIR(item.st_mode) or item.st_uid != os.getuid() or stat.S_IMODE(item.st_mode) != 0o700:
            raise RetentionError("INSPECTION_INVALID")
    for file_path in [run_control / "LOCK", event, *(inspection / name for name in INSPECTION_FILES)]:
        _private_file(file_path)
    if set(_directory_entries(run_control, "INSPECTION_INVALID")) != {"LOCK", "inspections", "events"} or set(_directory_entries(inspection, "INSPECTION_INVALID")) != INSPECTION_FILES or set(_directory_entries(run_control / "inspections", "INSPECTION_INVALID")) != {inspection.name} or set(_directory_entries(run_control / "events", "INSPECTION_INVALID")) != {event.name}:
        raise RetentionError("INSPECTION_INVALID")


def verify_inspection(*, receipt: Path, inspection: Path, control_event: Path, rules_path: Path = DEFAULT_RULES, assessment_path: Path = DEFAULT_ASSESSMENT, expected_rules_sha256: str | None = None, expected_assessment_sha256: str | None = None, mode: Literal["archived-integrity", "current-source"] = "archived-integrity", repo_root: Path | None = None) -> InspectionResult:
    receipt = _absolute(receipt, "RECEIPT_INVALID")
    inspection = _absolute(inspection, "INSPECTION_INVALID")
    control_event = _absolute(control_event, "EVENT_SEQUENCE_INVALID")
    rules_path = _absolute(rules_path, "RULE_SCHEMA_INVALID")
    assessment_path = _absolute(assessment_path, "ASSESSMENT_SCHEMA_INVALID")
    for path, code in ((receipt, "RECEIPT_INVALID"), (inspection, "INSPECTION_INVALID"), (control_event, "EVENT_SEQUENCE_INVALID"), (rules_path, "RULE_SCHEMA_INVALID"), (assessment_path, "ASSESSMENT_SCHEMA_INVALID")):
        _assert_no_symlink_components(path, code)
    rules = load_secret_rules(rules_path, expected_sha256=expected_rules_sha256)
    assessment = load_retention_assessment(assessment_path, rules=rules, expected_sha256=expected_assessment_sha256)
    source_root = receipt.parent
    before = _tree_snapshot(source_root)
    document = _verify_receipt(receipt, mode, repo_root)
    _assert_same_tree(source_root, before)
    run_id = document["run_id"]
    control_root, run_control, inspections, events = _control_paths(receipt, run_id)
    if inspection.parent != inspections or control_event.parent != events or run_control.parent != control_root:
        raise RetentionError("INSPECTION_INVALID")
    _validate_private_tree(run_control, inspection, control_event)
    report, report_content = _load_control_json(
        inspection / "secret-scan.json",
        limit=MAX_REPORT_BYTES,
    )
    marker, marker_content = _load_control_json(inspection / "COMPLETE")
    if _stable_bytes(inspection / "secret-rules.json", "INSPECTION_INVALID") != rules.content:
        raise RetentionError("RULE_BINDING_MISMATCH")
    if _stable_bytes(inspection / "retention-assessment.json", "INSPECTION_INVALID") != assessment.content:
        raise RetentionError("INSPECTION_INVALID")
    if _hash(report.get("rules_sha256")) and report["rules_sha256"] != rules.sha256:
        raise RetentionError("RULE_BINDING_MISMATCH")
    _validate_report(report, rules, assessment)
    state = _state(report)
    if marker != {"inspection_id": inspection.name, "inspection_sha256": _sha256(report_content), "state": state}:
        raise RetentionError("INSPECTION_INVALID")
    event, event_content = _load_control_json(control_event)
    name_match = EVENT_NAME.fullmatch(control_event.name)
    if name_match is None:
        raise RetentionError("EVENT_SEQUENCE_INVALID")
    if name_match.group("sha256") != _sha256(event_content):
        raise RetentionError("EVENT_HASH_CHAIN_INVALID")
    _exact(event, {"schema", "schema_version", "sequence", "previous_event_sha256", "event_type", "from_state", "to_state", "run_id", "receipt_sha256", "assessment_sha256", "actor_claim", "actor_assurance", "occurred_at", "details"}, "EVENT_SEQUENCE_INVALID")
    details = _exact(event["details"], {"inspection_id", "inspection_sha256", "completion_sha256", "rules_sha256", "error_codes", "matched_rule_ids"}, "EVENT_SEQUENCE_INVALID")
    receipt_content = _stable_bytes(receipt, "FILE_CHANGED_DURING_SCAN", limit=64 * 1024 * 1024)
    sealed_content = _stable_bytes(source_root / "SEALED", "FILE_CHANGED_DURING_SCAN")
    expected_errors = sorted({item["code"] for item in report["errors"]})
    expected_rules = sorted({hit["rule_id"] for record in report["files"] for hit in record["hits"]})
    version = event["schema_version"]
    sequence = event["sequence"]
    if (
        event["schema"] != EVENT_SCHEMA
        or version != SCHEMA_VERSION
        or isinstance(version, bool)
        or sequence != 1
        or isinstance(sequence, bool)
        or int(name_match.group("sequence")) != sequence
        or event["event_type"] != "INSPECTION_COMMITTED"
        or event["from_state"] != "LOCAL_SEALED"
        or not isinstance(event["to_state"], str)
        or event["to_state"] not in ("SCANNED_PASS", "SCANNED_BLOCKED")
        or not _safe_id(event["run_id"])
        or not _hash(event["receipt_sha256"])
        or not _hash(event["assessment_sha256"])
        or not _actor(event["actor_claim"])
        or event["actor_assurance"] != "self-asserted-local"
        or not _timestamp(event["occurred_at"])
    ):
        raise RetentionError("EVENT_SEQUENCE_INVALID")
    if event["previous_event_sha256"] is not None:
        raise RetentionError("EVENT_HASH_CHAIN_INVALID")
    if (
        event["run_id"] != run_id
        or event["receipt_sha256"] != _sha256(receipt_content)
        or event["assessment_sha256"] != assessment.sha256
        or event["to_state"] != state
        or event["occurred_at"] != report["created_at"]
    ):
        raise RetentionError("INSPECTION_INVALID")
    if (
        not isinstance(details["error_codes"], list)
        or not all(isinstance(item, str) for item in details["error_codes"])
        or details["error_codes"] != sorted(set(details["error_codes"]))
        or not isinstance(details["matched_rule_ids"], list)
        or not all(isinstance(item, str) for item in details["matched_rule_ids"])
        or details["matched_rule_ids"] != sorted(set(details["matched_rule_ids"]))
    ):
        raise RetentionError("EVENT_SEQUENCE_INVALID")
    if details != {
        "inspection_id": inspection.name,
        "inspection_sha256": _sha256(report_content),
        "completion_sha256": _sha256(marker_content),
        "rules_sha256": rules.sha256,
        "error_codes": expected_errors,
        "matched_rule_ids": expected_rules,
    }:
        raise RetentionError("INSPECTION_INVALID")
    if (
        report["run_id"] != run_id
        or report["layer"] != document["claim"]["layer"]
        or report["inspection_id"] != inspection.name
        or report["receipt_sha256"] != _sha256(receipt_content)
        or report["sealed_sha256"] != _sha256(sealed_content)
    ):
        raise RetentionError("INSPECTION_INVALID")
    files, errors, aggregate = _scan_tree(
        source_root,
        before,
        rules,
        assessment.max_file_bytes,
    )
    _assert_same_tree(source_root, before)
    if (
        report["files"] != files
        or report["errors"] != errors
        or report["aggregate_sha256"] != aggregate
        or _state(report) != state
    ):
        raise RetentionError("INSPECTION_INVALID")
    final_document = _verify_receipt(receipt, mode, repo_root)
    _assert_same_tree(source_root, before)
    if final_document != document:
        raise RetentionError("RECEIPT_INVALID")
    return InspectionResult(
        inspection_path=inspection,
        control_event_path=control_event,
        state=state,
        run_id=run_id,
        inspection_id=inspection.name,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect sealed local evidence without enabling lifecycle actions."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--receipt", required=True, type=Path)
    inspect_parser.add_argument("--rules", type=Path)
    inspect_parser.add_argument("--assessment", type=Path)
    inspect_parser.add_argument("--expected-rules-sha256")
    inspect_parser.add_argument("--expected-assessment-sha256")
    inspect_parser.add_argument("--actor", required=True)
    inspect_parser.add_argument(
        "--mode",
        choices=("archived-integrity", "current-source"),
        default="archived-integrity",
    )
    inspect_parser.add_argument("--repo-root", type=Path)

    verify_parser = commands.add_parser("verify-inspection")
    verify_parser.add_argument("--receipt", required=True, type=Path)
    verify_parser.add_argument("--inspection", required=True, type=Path)
    verify_parser.add_argument("--control-event", required=True, type=Path)
    verify_parser.add_argument("--rules", type=Path)
    verify_parser.add_argument("--assessment", type=Path)
    verify_parser.add_argument("--expected-rules-sha256")
    verify_parser.add_argument("--expected-assessment-sha256")
    verify_parser.add_argument(
        "--mode",
        choices=("archived-integrity", "current-source"),
        default="archived-integrity",
    )
    verify_parser.add_argument("--repo-root", type=Path)
    return parser


def _resolve_cli_arguments(
    parser: argparse.ArgumentParser,
    arguments: argparse.Namespace,
) -> None:
    if arguments.rules is not None and arguments.expected_rules_sha256 is None:
        parser.error("custom --rules requires --expected-rules-sha256")
    if arguments.rules is None and arguments.expected_rules_sha256 is not None:
        parser.error("--expected-rules-sha256 requires custom --rules")
    if arguments.assessment is not None and arguments.expected_assessment_sha256 is None:
        parser.error("custom --assessment requires --expected-assessment-sha256")
    if arguments.assessment is None and arguments.expected_assessment_sha256 is not None:
        parser.error("--expected-assessment-sha256 requires custom --assessment")
    if arguments.mode == "current-source" and arguments.repo_root is None:
        parser.error("--mode current-source requires --repo-root")
    if arguments.mode == "archived-integrity" and arguments.repo_root is not None:
        parser.error("--repo-root requires --mode current-source")
    arguments.rules = arguments.rules or DEFAULT_RULES
    arguments.assessment = arguments.assessment or DEFAULT_ASSESSMENT
    arguments.expected_rules_sha256 = arguments.expected_rules_sha256 or DEFAULT_RULES_SHA256
    arguments.expected_assessment_sha256 = (
        arguments.expected_assessment_sha256 or DEFAULT_ASSESSMENT_SHA256
    )


def _output(result: InspectionResult) -> int:
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "inspection_id": result.inspection_id,
                "state": result.state,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 3 if result.state == "SCANNED_BLOCKED" else 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    _resolve_cli_arguments(parser, arguments)
    try:
        if arguments.command == "inspect":
            result = inspect_run(
                receipt=arguments.receipt,
                rules_path=arguments.rules,
                assessment_path=arguments.assessment,
                expected_rules_sha256=arguments.expected_rules_sha256,
                expected_assessment_sha256=arguments.expected_assessment_sha256,
                actor=arguments.actor,
                mode=arguments.mode,
                repo_root=arguments.repo_root,
            )
        else:
            result = verify_inspection(
                receipt=arguments.receipt,
                inspection=arguments.inspection,
                control_event=arguments.control_event,
                rules_path=arguments.rules,
                assessment_path=arguments.assessment,
                expected_rules_sha256=arguments.expected_rules_sha256,
                expected_assessment_sha256=arguments.expected_assessment_sha256,
                mode=arguments.mode,
                repo_root=arguments.repo_root,
            )
    except RetentionError as error:
        print(f"{error.code}: request rejected", file=sys.stderr)
        return 1
    except (OSError, TypeError, ValueError):
        print("CONTROL_PUBLICATION_FAILED: request rejected", file=sys.stderr)
        return 1
    return _output(result)


if __name__ == "__main__":
    raise SystemExit(main())
