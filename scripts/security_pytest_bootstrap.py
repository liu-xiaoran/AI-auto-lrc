#!/usr/bin/env python3
"""Load the two S18 pytest plugins from bound sources before collection."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.machinery
import importlib.metadata
import importlib.util
import io
import json
import os
import platform
import re
import stat
import sys
import types
from collections import namedtuple
from datetime import datetime
from email import policy as email_policy
from email.errors import MessageDefect
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - qualification uses Python 3.11
    import tomli as tomllib


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PLUGIN_NAMES = ("pytest_cov.plugin", "scripts.pytest_security_events")
_MAX_SOURCE_BYTES = 1024 * 1024
_MAX_PYVENV_CFG_BYTES = 16 * 1024
_MAX_DISTRIBUTION_RECORD_BYTES = 256 * 1024
_MAX_DISTRIBUTION_METADATA_BYTES = 256 * 1024
_MAX_RUNTIME_EXECUTABLE_BYTES = 64 * 1024 * 1024
_MAX_UV_LOCK_BYTES = 512 * 1024
_MAX_EXECUTABLE_SYMLINKS = 16
_MAX_PYTHON_VERSION_COMPONENT = 999
_MAX_DISTRIBUTION_RECORD_SIZE = 2**63 - 1
_BOUND_RUNTIME_MODULES = (
    "pluggy",
    "coverage",
    "pytest",
    "pytest_cov",
    "pytest_cov.plugin",
)
_BOUND_RUNTIME_PATH_SUFFIXES = {
    "pluggy": ("pluggy", "__init__.py"),
    "coverage": ("coverage", "__init__.py"),
    "pytest": ("pytest", "__init__.py"),
    "pytest_cov": ("pytest_cov", "__init__.py"),
    "pytest_cov.plugin": ("pytest_cov", "plugin.py"),
}
_BOUND_RUNTIME_ENTRY_KEYS = frozenset(
    {"module", "path", "is_package", "expected_sha256", "expected_size"}
)
_PYVENV_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_PYTHON_VERSION = re.compile(r"^([0-9]+)\.([0-9]+)(?:\.([0-9]+))?$")
_DIST_INFO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.dist-info$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[A-Za-z0-9._+-]*)?$")
_RUNTIME_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
_SHA256_URLSAFE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_DECIMAL_SIZE = re.compile(r"^(?:0|[1-9][0-9]*)$")
_PEP503_RUN = re.compile(r"[-_.]+")
_RUNTIME_LAYOUT_KEYS = frozenset(
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
_INSTALLED_DISTRIBUTION_KEYS = frozenset(
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
_LOCK_PACKAGE_KEYS = frozenset(
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
_PLUGIN_IDENTITY_KEYS = frozenset({"file", "sha256", "distribution", "entry"})
_RUNTIME_REQUIRED_PATHS = {
    "coverage": ("coverage/__init__.py",),
    "pluggy": ("pluggy/__init__.py",),
    "pytest": ("pytest/__init__.py",),
    "pytest-cov": ("pytest_cov/__init__.py", "pytest_cov/plugin.py"),
}
_RUNTIME_REQUIRED_DEPENDENCIES = {
    "coverage": (),
    "pluggy": (),
    "pytest": ("pluggy",),
    "pytest-cov": ("coverage", "pluggy", "pytest"),
}
_RUNTIME_DISTRIBUTIONS = ("coverage", "pluggy", "pytest", "pytest-cov")
_REQUIRED_ENTRY_TO_MODULE = {
    "pluggy/__init__.py": ("pluggy", True),
    "coverage/__init__.py": ("coverage", True),
    "pytest/__init__.py": ("pytest", True),
    "pytest_cov/__init__.py": ("pytest_cov", True),
    "pytest_cov/plugin.py": ("pytest_cov.plugin", False),
}


class BootstrapError(RuntimeError):
    """Raised when the trusted plugin bootstrap cannot prove its inputs."""


PreparedBoundRuntime = namedtuple(
    "PreparedBoundRuntime",
    (
        "runtime_layout",
        "uv_identity",
        "uv_lock_sha256",
        "distributions",
        "loaded_modules",
        "pytest_cov_plugin_identity",
    ),
)


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        stat.S_IFMT(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _stable_read(path: Path, *, field: str, limit: int = _MAX_SOURCE_BYTES) -> bytes:
    """Read one canonical regular file without following its leaf."""

    try:
        canonical = path.resolve(strict=True)
        if path != canonical:
            raise BootstrapError(f"{field} path is not canonical")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise BootstrapError(f"{field} is not a single-link regular file")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if _identity(before) != _identity(opened):
                raise BootstrapError(f"{field} changed before open")
            chunks: list[bytes] = []
            length = 0
            while True:
                chunk = os.read(descriptor, min(65536, limit + 1 - length))
                if not chunk:
                    break
                chunks.append(chunk)
                length += len(chunk)
                if length > limit:
                    raise BootstrapError(f"{field} exceeds its byte limit")
            after = os.fstat(descriptor)
            if _identity(opened) != _identity(after):
                raise BootstrapError(f"{field} changed during read")
        finally:
            os.close(descriptor)
    except BootstrapError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BootstrapError(f"{field} cannot be read safely") from exc
    return b"".join(chunks)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _lexically_canonical_absolute(path: Path) -> bool:
    return path.is_absolute() and path == Path(os.path.normpath(os.fspath(path)))


def _validate_executable_alias(executable: Path) -> Path:
    current = executable
    seen: set[tuple[int, int]] = set()
    symlink_count = 0
    while True:
        try:
            value = current.lstat()
        except OSError as exc:
            raise BootstrapError("runtime executable chain is invalid") from exc
        if stat.S_ISLNK(value.st_mode):
            symlink_count += 1
            if symlink_count > _MAX_EXECUTABLE_SYMLINKS:
                raise BootstrapError("runtime executable symlink chain is excessive")
            identity = (value.st_dev, value.st_ino)
            if identity in seen:
                raise BootstrapError("runtime executable symlink chain contains a cycle")
            seen.add(identity)
            try:
                target = Path(os.readlink(current))
            except OSError as exc:
                raise BootstrapError("runtime executable symlink cannot be read") from exc
            if not target.is_absolute():
                target = current.parent / target
            current = Path(os.path.normpath(os.fspath(target)))
            if not current.is_absolute():
                raise BootstrapError("runtime executable symlink target is invalid")
            continue
        if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
            raise BootstrapError("runtime executable target is not a single-link regular file")
        try:
            if current.resolve(strict=True) != current:
                raise BootstrapError("runtime executable target is not canonical")
        except (OSError, RuntimeError) as exc:
            raise BootstrapError("runtime executable target is not canonical") from exc
        return current


def _snapshot_executable_chain(executable: Path) -> tuple[tuple[object, ...], ...]:
    current = executable
    result: list[tuple[object, ...]] = []
    symlink_count = 0
    seen: set[tuple[int, int]] = set()
    while True:
        try:
            value = current.lstat()
        except OSError as exc:
            raise BootstrapError("runtime executable chain cannot be snapshotted") from exc
        link_target: str | None = None
        if stat.S_ISLNK(value.st_mode):
            symlink_count += 1
            if symlink_count > _MAX_EXECUTABLE_SYMLINKS:
                raise BootstrapError("runtime executable symlink chain is excessive")
            inode = (value.st_dev, value.st_ino)
            if inode in seen:
                raise BootstrapError("runtime executable symlink chain contains a cycle")
            seen.add(inode)
            try:
                link_target = os.readlink(current)
            except OSError as exc:
                raise BootstrapError("runtime executable symlink cannot be read") from exc
        result.append((os.fspath(current), _identity(value), link_target))
        if link_target is None:
            return tuple(result)
        following = Path(link_target)
        if not following.is_absolute():
            following = current.parent / following
        current = Path(os.path.normpath(os.fspath(following)))


def _validated_python_version(
    python_major_minor: tuple[int, int],
) -> tuple[int, int]:
    if (
        type(python_major_minor) is not tuple
        or len(python_major_minor) != 2
        or any(
            type(value) is not int
            or value < 0
            or value > _MAX_PYTHON_VERSION_COMPONENT
            for value in python_major_minor
        )
        or python_major_minor[0] == 0
    ):
        raise BootstrapError("runtime Python version input is invalid")
    return python_major_minor


def _runtime_venv_root(executable: Path) -> Path:
    if (
        not isinstance(executable, Path)
        or not _lexically_canonical_absolute(executable)
        or executable.parent.name != "bin"
    ):
        raise BootstrapError("runtime executable alias is invalid")
    venv_root = executable.parent.parent
    try:
        if venv_root.resolve(strict=True) != venv_root:
            raise BootstrapError("runtime venv root is not canonical")
    except BootstrapError:
        raise
    except (OSError, RuntimeError) as exc:
        raise BootstrapError("runtime venv root is not canonical") from exc
    return venv_root


def _validated_runtime_site_context(
    executable: Path,
    *,
    python_major_minor: tuple[int, int],
    pyvenv_content: bytes,
) -> tuple[Path, Path, Path, dict[str, str]]:
    major, minor = _validated_python_version(python_major_minor)
    venv_root = _runtime_venv_root(executable)
    executable_target = _validate_executable_alias(executable)
    values = _parse_pyvenv_cfg(pyvenv_content)
    home = Path(values["home"])
    try:
        home_value = home.lstat()
        if (
            not _lexically_canonical_absolute(home)
            or not stat.S_ISDIR(home_value.st_mode)
            or home.resolve(strict=True) != home
            or home != executable_target.parent
        ):
            raise BootstrapError("pyvenv.cfg home does not bind the runtime executable")
    except BootstrapError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BootstrapError("pyvenv.cfg home is not a canonical directory") from exc
    version_key = "version" if "version" in values else "version_info"
    match = _PYTHON_VERSION.fullmatch(values[version_key])
    if match is None:
        raise BootstrapError("pyvenv.cfg runtime version does not match Python")
    version_components = tuple(
        _parse_bounded_ascii_decimal(
            component,
            field="pyvenv.cfg runtime version component",
            maximum=_MAX_PYTHON_VERSION_COMPONENT,
        )
        for component in match.groups()
        if component is not None
    )
    if version_components[:2] != (major, minor):
        raise BootstrapError("pyvenv.cfg runtime version does not match Python")
    expected = venv_root / "lib" / f"python{major}.{minor}" / "site-packages"
    try:
        candidates = tuple((venv_root / "lib").glob("python*/site-packages"))
    except OSError as exc:
        raise BootstrapError("runtime site-packages cannot be enumerated") from exc
    if candidates != (expected,):
        raise BootstrapError("runtime site-packages is not unique")
    try:
        value = expected.lstat()
        if not stat.S_ISDIR(value.st_mode) or expected.resolve(strict=True) != expected:
            raise BootstrapError("runtime site-packages is not a canonical directory")
    except BootstrapError:
        raise
    except (OSError, RuntimeError) as exc:
        raise BootstrapError("runtime site-packages is not a canonical directory") from exc
    return executable_target, venv_root, expected, values


def _parse_bounded_ascii_decimal(
    value: str,
    *,
    field: str,
    maximum: int,
) -> int:
    maximum_text = str(maximum)
    if (
        not isinstance(value, str)
        or _DECIMAL_SIZE.fullmatch(value) is None
        or len(value) > len(maximum_text)
        or (len(value) == len(maximum_text) and value > maximum_text)
    ):
        raise BootstrapError(f"{field} is invalid")
    return int(value)


def _parse_pyvenv_cfg(content: bytes) -> dict[str, str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BootstrapError("pyvenv.cfg is not UTF-8") from exc
    if "\x00" in text:
        raise BootstrapError("pyvenv.cfg contains NUL")
    values: dict[str, str] = {}
    for line in text.splitlines():
        if " = " not in line:
            raise BootstrapError("pyvenv.cfg contains a malformed entry")
        key, value = line.split(" = ", 1)
        if _PYVENV_KEY.fullmatch(key) is None or not value:
            raise BootstrapError("pyvenv.cfg contains a malformed entry")
        if key in values:
            raise BootstrapError("pyvenv.cfg contains a duplicate key")
        values[key] = value
    if not values or "home" not in values or not values["home"]:
        raise BootstrapError("pyvenv.cfg is missing home")
    if values.get("include-system-site-packages") != "false":
        raise BootstrapError("pyvenv.cfg must disable system site packages")
    version_keys = [key for key in ("version", "version_info") if key in values]
    if len(version_keys) != 1:
        raise BootstrapError("pyvenv.cfg runtime version is not unique")
    return values


def _derive_runtime_site_packages(
    executable: Path,
    *,
    python_major_minor: tuple[int, int],
) -> Path:
    """Derive one venv site root without resolving away its executable alias."""

    _validated_python_version(python_major_minor)
    venv_root = _runtime_venv_root(executable)
    config = venv_root / "pyvenv.cfg"
    content = _stable_read(config, field="pyvenv.cfg", limit=_MAX_PYVENV_CFG_BYTES)
    _target, _root, site_packages, _values = _validated_runtime_site_context(
        executable,
        python_major_minor=python_major_minor,
        pyvenv_content=content,
    )
    return site_packages


def _capture_runtime_layout(
    executable: Path,
    *,
    python_major_minor: tuple[int, int],
    base_prefix: Path,
) -> dict[str, object]:
    """Capture one stable runtime layout without resolving away the venv alias."""

    _validated_python_version(python_major_minor)
    venv_root = _runtime_venv_root(executable)
    if not isinstance(base_prefix, Path) or not _lexically_canonical_absolute(base_prefix):
        raise BootstrapError("runtime base prefix is invalid")
    try:
        base_value = base_prefix.lstat()
        if (
            not stat.S_ISDIR(base_value.st_mode)
            or base_prefix.resolve(strict=True) != base_prefix
        ):
            raise BootstrapError("runtime base prefix is not a canonical directory")
    except BootstrapError:
        raise
    except (OSError, RuntimeError) as exc:
        raise BootstrapError("runtime base prefix is not a canonical directory") from exc

    config = venv_root / "pyvenv.cfg"
    chain_before = _snapshot_executable_chain(executable)
    target_before = _validate_executable_alias(executable)
    try:
        target_identity_before = _identity(target_before.lstat())
        config_identity_before = _identity(config.lstat())
    except OSError as exc:
        raise BootstrapError("runtime layout endpoints cannot be snapshotted") from exc
    executable_bytes = _stable_read(
        target_before,
        field="runtime Python executable",
        limit=_MAX_RUNTIME_EXECUTABLE_BYTES,
    )
    pyvenv_bytes = _stable_read(
        config,
        field="pyvenv.cfg",
        limit=_MAX_PYVENV_CFG_BYTES,
    )
    target_after, confirmed_root, site_packages, values = _validated_runtime_site_context(
        executable,
        python_major_minor=python_major_minor,
        pyvenv_content=pyvenv_bytes,
    )
    chain_after = _snapshot_executable_chain(executable)
    try:
        target_identity_after = _identity(target_after.lstat())
        config_identity_after = _identity(config.lstat())
    except OSError as exc:
        raise BootstrapError("runtime layout endpoints cannot be resnapshotted") from exc
    if (
        chain_before != chain_after
        or target_before != target_after
        or target_identity_before != target_identity_after
        or config_identity_before != config_identity_after
        or confirmed_root != venv_root
    ):
        raise BootstrapError("runtime layout changed during capture")
    home = Path(values["home"])
    if home.parent != base_prefix:
        raise BootstrapError("runtime home is not bound to base prefix")
    return {
        "executable": os.fspath(executable),
        "executable_realpath": os.fspath(target_after),
        "executable_size": len(executable_bytes),
        "executable_sha256": _sha256(executable_bytes),
        "venv_root": os.fspath(venv_root),
        "base_prefix": os.fspath(base_prefix),
        "site_packages": os.fspath(site_packages),
        "home": os.fspath(home),
        "pyvenv_cfg_path": os.fspath(config),
        "pyvenv_cfg_bytes": pyvenv_bytes,
        "pyvenv_cfg_size": len(pyvenv_bytes),
        "pyvenv_cfg_sha256": _sha256(pyvenv_bytes),
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "cache_tag": sys.implementation.cache_tag,
        "system": platform.system(),
        "machine": platform.machine(),
        "isolated": bool(sys.flags.isolated),
        "no_site": bool(sys.flags.no_site),
        "dont_write_bytecode": bool(sys.flags.dont_write_bytecode),
    }


def _validate_bound_runtime_entries(
    entries: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    if not isinstance(entries, tuple) or len(entries) != len(_BOUND_RUNTIME_MODULES):
        raise BootstrapError("bound runtime entries are invalid")
    validated: list[dict[str, object]] = []
    site_root: Path | None = None
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or frozenset(entry) != _BOUND_RUNTIME_ENTRY_KEYS:
            raise BootstrapError("bound runtime entry schema is invalid")
        name = entry["module"]
        path = entry["path"]
        is_package = entry["is_package"]
        expected_sha256 = entry["expected_sha256"]
        expected_size = entry["expected_size"]
        expected_name = _BOUND_RUNTIME_MODULES[index]
        if (
            name != expected_name
            or not isinstance(path, Path)
            or not _lexically_canonical_absolute(path)
            or tuple(path.parts[-2:]) != _BOUND_RUNTIME_PATH_SUFFIXES[expected_name]
            or type(is_package) is not bool
            or is_package is (expected_name == "pytest_cov.plugin")
            or not isinstance(expected_sha256, str)
            or _SHA256_HEX.fullmatch(expected_sha256) is None
            or type(expected_size) is not int
            or expected_size < 0
            or expected_size > _MAX_SOURCE_BYTES
        ):
            raise BootstrapError("bound runtime entry is invalid")
        current_site_root = path.parents[1]
        if site_root is None:
            site_root = current_site_root
        elif current_site_root != site_root:
            raise BootstrapError("bound runtime entries do not share one site root")
        validated.append(entry)
    if any(name in sys.modules for name in _BOUND_RUNTIME_MODULES):
        raise BootstrapError("bound runtime module name is already registered")
    return tuple(validated)


def _load_bound_runtime_modules(
    entries: tuple[dict[str, object], ...],
) -> tuple[dict[str, types.ModuleType], dict[str, dict[str, object]]]:
    """Stable-read legacy descriptors once, then delegate to the no-I/O core."""

    validated = _validate_bound_runtime_entries(entries)
    captured_sources = tuple(
        _stable_read(
            entry["path"],
            field=f"bound runtime entry {entry['module']}",
        )
        for entry in validated
    )
    return _load_captured_runtime_modules(validated, captured_sources)


def _load_captured_runtime_modules(
    entries: tuple[dict[str, object], ...],
    captured_sources: tuple[bytes, ...],
) -> tuple[dict[str, types.ModuleType], dict[str, dict[str, object]]]:
    """Load ordered runtime modules using only already-captured source bytes."""

    validated = _validate_bound_runtime_entries(entries)
    if (
        type(captured_sources) is not tuple
        or len(captured_sources) != len(validated)
        or any(type(content) is not bytes for content in captured_sources)
        or any(len(content) > _MAX_SOURCE_BYTES for content in captured_sources)
    ):
        raise BootstrapError("captured runtime sources are invalid")
    modules: dict[str, types.ModuleType] = {}
    identities: dict[str, dict[str, object]] = {}
    inserted: list[tuple[str, types.ModuleType]] = []
    parent_attributes: list[tuple[types.ModuleType, str, types.ModuleType]] = []
    try:
        for entry, content in zip(validated, captured_sources, strict=True):
            name = str(entry["module"])
            path = entry["path"]
            assert isinstance(path, Path)
            is_package = bool(entry["is_package"])
            digest = _sha256(content)
            if digest != entry["expected_sha256"] or len(content) != entry["expected_size"]:
                raise BootstrapError(f"bound runtime entry differs for {name}")
            specification = importlib.machinery.ModuleSpec(
                name,
                loader=None,
                origin=os.fspath(path),
                is_package=is_package,
            )
            if is_package:
                specification.submodule_search_locations = [os.fspath(path.parent)]
            module = types.ModuleType(name)
            module.__file__ = os.fspath(path)
            module.__loader__ = None
            module.__package__ = name if is_package else name.rpartition(".")[0]
            module.__spec__ = specification
            if is_package:
                module.__path__ = [os.fspath(path.parent)]
            code = compile(content, os.fspath(path), "exec", dont_inherit=True)
            sys.modules[name] = module
            inserted.append((name, module))
            exec(code, module.__dict__)
            if "." in name:
                parent_name, _, attribute = name.rpartition(".")
                parent = modules[parent_name]
                setattr(parent, attribute, module)
                parent_attributes.append((parent, attribute, module))
            modules[name] = module
            identities[name] = {
                "path": os.fspath(path),
                "sha256": digest,
                "size": len(content),
            }
    except BaseException as exc:
        for parent, attribute, module in reversed(parent_attributes):
            if getattr(parent, attribute, None) is module:
                delattr(parent, attribute)
        for name, module in reversed(inserted):
            if sys.modules.get(name) is module:
                del sys.modules[name]
        if isinstance(exc, BootstrapError):
            raise
        raise BootstrapError("bound runtime modules cannot be loaded") from exc
    return modules, identities


def _canonical_required_record_path(path: str) -> bool:
    if not path or "\x00" in path or "\\" in path:
        return False
    value = PurePosixPath(path)
    return (
        not value.is_absolute()
        and value.as_posix() == path
        and all(part not in {"", ".", ".."} for part in value.parts)
    )


def _decode_record_digest(value: str) -> str:
    if _SHA256_URLSAFE.fullmatch(value) is None:
        raise BootstrapError("distribution RECORD digest is invalid")
    try:
        decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise BootstrapError("distribution RECORD digest is invalid") from exc
    if (
        len(decoded) != 32
        or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value
    ):
        raise BootstrapError("distribution RECORD digest is invalid")
    return decoded.hex()


def _parse_distribution_record(
    record_bytes: bytes,
    *,
    dist_info: str,
    required_paths: tuple[str, ...],
) -> tuple[dict[str, object], ...]:
    """Parse one bounded RECORD while retaining parent rows as opaque text."""

    if (
        not isinstance(record_bytes, bytes)
        or len(record_bytes) > _MAX_DISTRIBUTION_RECORD_BYTES
        or not isinstance(dist_info, str)
        or _DIST_INFO.fullmatch(dist_info) is None
        or type(required_paths) is not tuple
        or not required_paths
    ):
        raise BootstrapError("distribution RECORD inputs are invalid")
    if any(
        not isinstance(path, str) or not _canonical_required_record_path(path)
        for path in required_paths
    ):
        raise BootstrapError("distribution RECORD inputs are invalid")
    if len(required_paths) != len(set(required_paths)):
        raise BootstrapError("distribution RECORD inputs are invalid")
    try:
        text = record_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BootstrapError("distribution RECORD is not UTF-8") from exc
    if "\x00" in text:
        raise BootstrapError("distribution RECORD contains NUL")
    try:
        rows = tuple(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (csv.Error, TypeError) as exc:
        raise BootstrapError("distribution RECORD CSV is invalid") from exc
    if not rows:
        raise BootstrapError("distribution RECORD is empty")
    required = set(required_paths)
    found_required: set[str] = set()
    seen: set[str] = set()
    self_path = f"{dist_info}/RECORD"
    self_count = 0
    result: list[dict[str, object]] = []
    for row in rows:
        if len(row) != 3:
            raise BootstrapError("distribution RECORD row must have three columns")
        path, digest_field, size_field = row
        if not path or path in seen or "\x00" in path or "\\" in path:
            raise BootstrapError("distribution RECORD path is invalid")
        seen.add(path)
        if path == self_path:
            if digest_field or size_field:
                raise BootstrapError("distribution RECORD self row is invalid")
            self_count += 1
            result.append({"kind": "self", "path": path, "sha256": None, "size": None})
            continue
        if not digest_field.startswith("sha256="):
            raise BootstrapError("distribution RECORD hash or size is invalid")
        size = _parse_bounded_ascii_decimal(
            size_field,
            field="distribution RECORD size",
            maximum=_MAX_DISTRIBUTION_RECORD_SIZE,
        )
        digest = _decode_record_digest(digest_field.removeprefix("sha256="))
        value = PurePosixPath(path)
        if value.is_absolute() or value.as_posix() != path:
            raise BootstrapError("distribution RECORD path is not canonical")
        if path in required:
            if not _canonical_required_record_path(path):
                raise BootstrapError("required distribution RECORD path is unsafe")
            kind = "required"
            found_required.add(path)
        elif ".." in value.parts:
            kind = "opaque"
        elif not _canonical_required_record_path(path):
            raise BootstrapError("distribution RECORD path is not canonical")
        else:
            kind = "entry"
        result.append(
            {
                "kind": kind,
                "path": path,
                "sha256": digest,
                "size": size,
            }
        )
    if self_count != 1 or found_required != required:
        raise BootstrapError("distribution RECORD closure is incomplete")
    return tuple(result)


def _pep503_name(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise BootstrapError("runtime package name is invalid")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise BootstrapError("runtime package name is invalid") from exc
    normalized = _PEP503_RUN.sub("-", value).lower()
    if not normalized or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized) is None:
        raise BootstrapError("runtime package name is invalid")
    return normalized


def _metadata_name_version(content: bytes) -> tuple[str, str]:
    try:
        text = content.decode("utf-8")
        if "\x00" in text:
            raise BootstrapError("distribution METADATA contains NUL")
        message = Parser(policy=email_policy.strict).parsestr(text)
        names = message.get_all("Name", [])
        versions = message.get_all("Version", [])
    except BootstrapError:
        raise
    except (UnicodeDecodeError, ValueError, MessageDefect) as exc:
        raise BootstrapError("distribution METADATA is invalid") from exc
    if (
        message.defects
        or len(names) != 1
        or len(versions) != 1
        or not isinstance(names[0], str)
        or not isinstance(versions[0], str)
        or not names[0]
        or not versions[0]
        or names[0].strip() != names[0]
        or versions[0].strip() != versions[0]
    ):
        raise BootstrapError("distribution METADATA identity is invalid")
    return str(names[0]), str(versions[0])


def _dist_info_name_version(name: str) -> tuple[str, str] | None:
    if not name.endswith(".dist-info"):
        return None
    stem = name.removesuffix(".dist-info")
    distribution_name, separator, version = stem.rpartition("-")
    if not separator or not distribution_name or not version:
        return None
    return _pep503_name(distribution_name), version


def _capture_named_distribution(
    site_packages: Path,
    *,
    canonical_name: str,
    required_paths: tuple[str, ...],
) -> tuple[
    dict[str, object],
    tuple[dict[str, object], ...],
    tuple[bytes, ...],
]:
    """Capture one direct-child installed distribution and its required sources."""

    if (
        not isinstance(site_packages, Path)
        or not _lexically_canonical_absolute(site_packages)
        or _pep503_name(canonical_name) != canonical_name
        or type(required_paths) is not tuple
        or not required_paths
        or any(
            type(path) is not str
            or not _canonical_required_record_path(path)
            or path not in _REQUIRED_ENTRY_TO_MODULE
            for path in required_paths
        )
        or len(required_paths) != len(set(required_paths))
    ):
        raise BootstrapError("distribution capture inputs are invalid")
    try:
        site_value = site_packages.lstat()
        if (
            not stat.S_ISDIR(site_value.st_mode)
            or site_packages.resolve(strict=True) != site_packages
        ):
            raise BootstrapError("distribution site root is not canonical")
        candidates = []
        for child in site_packages.iterdir():
            parsed = _dist_info_name_version(child.name)
            if parsed is not None and parsed[0] == canonical_name:
                candidates.append((child, parsed[1]))
    except BootstrapError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BootstrapError("distribution site root cannot be enumerated") from exc
    if len(candidates) != 1:
        raise BootstrapError("distribution direct-child resolution is not unique")
    dist_info, filename_version = candidates[0]
    metadata_path = dist_info / "METADATA"
    record_path = dist_info / "RECORD"
    try:
        dist_before = _identity(dist_info.lstat())
        metadata_before = _identity(metadata_path.lstat())
        record_before = _identity(record_path.lstat())
        if (
            not stat.S_ISDIR(dist_before[3])
            or dist_info.resolve(strict=True) != dist_info
        ):
            raise BootstrapError("distribution dist-info is not canonical")
    except BootstrapError:
        raise
    except (OSError, RuntimeError) as exc:
        raise BootstrapError("distribution dist-info endpoints are invalid") from exc
    metadata_bytes = _stable_read(
        metadata_path,
        field=f"distribution {canonical_name} METADATA",
        limit=_MAX_DISTRIBUTION_METADATA_BYTES,
    )
    record_bytes = _stable_read(
        record_path,
        field=f"distribution {canonical_name} RECORD",
        limit=_MAX_DISTRIBUTION_RECORD_BYTES,
    )
    metadata_name, metadata_version = _metadata_name_version(metadata_bytes)
    if metadata_name != canonical_name or metadata_version != filename_version:
        raise BootstrapError("distribution METADATA does not match dist-info")
    rows = _parse_distribution_record(
        record_bytes,
        dist_info=dist_info.name,
        required_paths=required_paths,
    )
    rows_by_path = {str(row["path"]): row for row in rows}
    required_entries: dict[str, dict[str, object]] = {}
    descriptors: list[dict[str, object]] = []
    sources: list[bytes] = []
    endpoint_snapshots: list[tuple[Path, tuple[int, int, int, int, int, int, int]]] = []
    for relative in required_paths:
        path = site_packages.joinpath(*PurePosixPath(relative).parts)
        try:
            before = _identity(path.lstat())
        except OSError as exc:
            raise BootstrapError("distribution required entry is missing") from exc
        content = _stable_read(
            path,
            field=f"distribution {canonical_name} required entry {relative}",
        )
        try:
            after = _identity(path.lstat())
        except OSError as exc:
            raise BootstrapError("distribution required entry changed") from exc
        if before != after:
            raise BootstrapError("distribution required entry changed during capture")
        row = rows_by_path[relative]
        digest = _sha256(content)
        if row["kind"] != "required" or row["sha256"] != digest or row["size"] != len(content):
            raise BootstrapError("distribution required entry differs from RECORD")
        module_name, is_package = _REQUIRED_ENTRY_TO_MODULE[relative]
        required_entries[relative] = {
            "bytes": content,
            "size": len(content),
            "sha256": digest,
        }
        descriptors.append(
            {
                "module": module_name,
                "path": path,
                "is_package": is_package,
                "expected_sha256": digest,
                "expected_size": len(content),
            }
        )
        sources.append(content)
        endpoint_snapshots.append((path, before))
    try:
        if (
            dist_before != _identity(dist_info.lstat())
            or metadata_before != _identity(metadata_path.lstat())
            or record_before != _identity(record_path.lstat())
            or any(before != _identity(path.lstat()) for path, before in endpoint_snapshots)
        ):
            raise BootstrapError("distribution endpoints changed during capture")
    except BootstrapError:
        raise
    except OSError as exc:
        raise BootstrapError("distribution endpoints cannot be resnapshotted") from exc
    return (
        {
            "name": canonical_name,
            "version": metadata_version,
            "dist_info": dist_info.name,
            "metadata_bytes": metadata_bytes,
            "metadata_size": len(metadata_bytes),
            "metadata_sha256": _sha256(metadata_bytes),
            "record_bytes": record_bytes,
            "record_size": len(record_bytes),
            "record_sha256": _sha256(record_bytes),
            "record_rows": rows,
            "required_entries": required_entries,
        },
        tuple(descriptors),
        tuple(sources),
    )


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise BootstrapError("runtime identity value is not canonical JSON") from exc


def _lock_dependency_names(package: dict[str, object]) -> tuple[str, ...]:
    dependencies = package.get("dependencies", [])
    if type(dependencies) is not list:
        raise BootstrapError("lock package dependencies are invalid")
    names: list[str] = []
    for dependency in dependencies:
        if type(dependency) is not dict or type(dependency.get("name")) is not str:
            raise BootstrapError("lock package dependency is invalid")
        names.append(_pep503_name(str(dependency["name"])))
    if len(names) != len(set(names)):
        raise BootstrapError("lock package dependencies are not unique")
    return tuple(names)


def _capture_lock_package(
    lock_path: Path,
    *,
    canonical_name: str,
    required_dependencies: tuple[str, ...],
) -> dict[str, object]:
    """Capture one exact PEP 503 package object from a stable uv.lock read."""

    if (
        not isinstance(lock_path, Path)
        or not _lexically_canonical_absolute(lock_path)
        or _pep503_name(canonical_name) != canonical_name
        or type(required_dependencies) is not tuple
        or any(
            type(name) is not str or _pep503_name(name) != name
            for name in required_dependencies
        )
        or len(required_dependencies) != len(set(required_dependencies))
    ):
        raise BootstrapError("lock package capture inputs are invalid")
    try:
        lock_identity_before = _identity(lock_path.lstat())
    except (OSError, RuntimeError, ValueError) as exc:
        raise BootstrapError("uv.lock endpoint cannot be captured") from exc
    raw = _stable_read(lock_path, field="uv.lock", limit=_MAX_UV_LOCK_BYTES)
    try:
        document = tomllib.loads(raw.decode("utf-8"))
        packages = document["package"]
    except (UnicodeDecodeError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise BootstrapError("uv.lock package list is invalid") from exc
    if type(packages) is not list:
        raise BootstrapError("uv.lock package list is invalid")
    matches = [
        package
        for package in packages
        if type(package) is dict
        and type(package.get("name")) is str
        and _pep503_name(str(package["name"])) == canonical_name
    ]
    if len(matches) != 1:
        raise BootstrapError("uv.lock package resolution is not unique")
    package = matches[0]
    version = package.get("version")
    if type(version) is not str or not version:
        raise BootstrapError("uv.lock package version is invalid")
    dependency_names = _lock_dependency_names(package)
    if any(name not in dependency_names for name in required_dependencies):
        raise BootstrapError("uv.lock package dependency closure is incomplete")
    canonical = _canonical_json_bytes(package)
    canonical_sha256 = _sha256(canonical)
    lock_file_sha256 = _sha256(raw)
    try:
        lock_identity_after = _identity(lock_path.lstat())
    except (OSError, RuntimeError, ValueError) as exc:
        raise BootstrapError("uv.lock endpoint cannot be resnapshotted") from exc
    if lock_identity_after != lock_identity_before:
        raise BootstrapError("uv.lock endpoint changed during capture")
    return {
        "name": canonical_name,
        "version": version,
        "exact_package_object": package,
        "canonical_package_bytes": canonical,
        "lock_package_sha256": canonical_sha256,
        "lock_file_sha256": lock_file_sha256,
        "required_dependencies": required_dependencies,
    }


def _exact_dict(value: object, keys: frozenset[str], *, field: str) -> dict[str, object]:
    if type(value) is not dict or frozenset(value) != keys:
        raise BootstrapError(f"{field} schema is invalid")
    return value


def _validated_sha256(value: object, *, field: str) -> str:
    if type(value) is not str or _SHA256_HEX.fullmatch(value) is None:
        raise BootstrapError(f"{field} digest is invalid")
    return value


def _validated_absolute_text(value: object, *, field: str) -> str:
    if (
        type(value) is not str
        or "\x00" in value
        or not _lexically_canonical_absolute(Path(value))
    ):
        raise BootstrapError(f"{field} path is invalid")
    return value


def _validated_file_leaf_text(value: object, *, field: str) -> str:
    validated = _validated_absolute_text(value, field=field)
    if not Path(validated).name:
        raise BootstrapError(f"{field} path is not a file leaf")
    return validated


def _json_boundary_value(value: object) -> object:
    if type(value) is bytes:
        return base64.b64encode(value).decode("ascii")
    if type(value) is tuple:
        return [_json_boundary_value(item) for item in value]
    if type(value) is list:
        return [_json_boundary_value(item) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise BootstrapError("runtime identity JSON key is invalid")
        return {key: _json_boundary_value(item) for key, item in value.items()}
    if value is None or type(value) in {str, int, bool, float}:
        return value
    raise BootstrapError("runtime identity value cannot enter JSON")


def _validate_runtime_identity_layout(runtime_layout: object) -> dict[str, object]:
    runtime = _exact_dict(runtime_layout, _RUNTIME_LAYOUT_KEYS, field="runtime layout")
    file_path_fields = (
        "executable",
        "executable_realpath",
        "pyvenv_cfg_path",
    )
    directory_path_fields = (
        "venv_root",
        "base_prefix",
        "site_packages",
        "home",
    )
    for field in file_path_fields:
        _validated_file_leaf_text(runtime[field], field=f"runtime {field}")
    for field in directory_path_fields:
        _validated_absolute_text(runtime[field], field=f"runtime {field}")
    for field in ("executable_size", "pyvenv_cfg_size"):
        if type(runtime[field]) is not int or int(runtime[field]) < 0:
            raise BootstrapError(f"runtime {field} is invalid")
    _validated_sha256(runtime["executable_sha256"], field="runtime executable")
    _validated_sha256(runtime["pyvenv_cfg_sha256"], field="runtime pyvenv.cfg")
    pyvenv_bytes = runtime["pyvenv_cfg_bytes"]
    if (
        type(pyvenv_bytes) is not bytes
        or len(pyvenv_bytes) > _MAX_PYVENV_CFG_BYTES
        or runtime["pyvenv_cfg_size"] != len(pyvenv_bytes)
        or runtime["pyvenv_cfg_sha256"] != _sha256(pyvenv_bytes)
    ):
        raise BootstrapError("runtime pyvenv.cfg binding is invalid")
    values = _parse_pyvenv_cfg(pyvenv_bytes)
    if values["home"] != runtime["home"]:
        raise BootstrapError("runtime home differs from pyvenv.cfg")
    version = runtime["version"]
    if type(version) is not str:
        raise BootstrapError("runtime version is invalid")
    runtime_match = _PYTHON_VERSION.fullmatch(version)
    version_key = "version" if "version" in values else "version_info"
    config_match = _PYTHON_VERSION.fullmatch(values[version_key])
    if runtime_match is None or config_match is None or runtime_match.groups() != config_match.groups():
        raise BootstrapError("runtime version differs from pyvenv.cfg")
    for component in runtime_match.groups():
        if component is not None:
            _parse_bounded_ascii_decimal(
                component,
                field="runtime version component",
                maximum=_MAX_PYTHON_VERSION_COMPONENT,
            )
    major_text, minor_text = runtime_match.groups()[:2]
    major = _parse_bounded_ascii_decimal(
        major_text,
        field="runtime major version",
        maximum=_MAX_PYTHON_VERSION_COMPONENT,
    )
    minor = _parse_bounded_ascii_decimal(
        minor_text,
        field="runtime minor version",
        maximum=_MAX_PYTHON_VERSION_COMPONENT,
    )
    if (
        runtime["implementation"] != "CPython"
        or type(runtime["cache_tag"]) is not str
        or not runtime["cache_tag"]
        or type(runtime["system"]) is not str
        or runtime["system"] not in {"Darwin", "Linux"}
        or type(runtime["machine"]) is not str
        or not runtime["machine"]
        or any(runtime[field] is not True for field in ("isolated", "no_site", "dont_write_bytecode"))
    ):
        raise BootstrapError("runtime implementation fields are invalid")
    venv_root = Path(str(runtime["venv_root"]))
    if (
        Path(str(runtime["executable"])).parent != venv_root / "bin"
        or Path(str(runtime["pyvenv_cfg_path"])) != venv_root / "pyvenv.cfg"
        or Path(str(runtime["site_packages"]))
        != venv_root / "lib" / f"python{major}.{minor}" / "site-packages"
        or Path(str(runtime["executable_realpath"])).parent != Path(str(runtime["home"]))
        or Path(str(runtime["home"])).parent != Path(str(runtime["base_prefix"]))
    ):
        raise BootstrapError("runtime path relationships are invalid")
    return runtime


def _validate_builder_installed_distribution(
    name: str,
    value: object,
) -> dict[str, object]:
    installed = _exact_dict(value, _INSTALLED_DISTRIBUTION_KEYS, field=f"{name} installed")
    if installed["name"] != name or type(installed["version"]) is not str or not installed["version"]:
        raise BootstrapError(f"{name} installed identity is invalid")
    dist_info = installed["dist_info"]
    if type(dist_info) is not str or _DIST_INFO.fullmatch(dist_info) is None:
        raise BootstrapError(f"{name} dist-info is invalid")
    parsed_dist_info = _dist_info_name_version(dist_info)
    if (
        parsed_dist_info is None
        or parsed_dist_info[0] != name
        or parsed_dist_info[1] != installed["version"]
    ):
        raise BootstrapError(f"{name} dist-info identity is invalid")
    metadata = installed["metadata_bytes"]
    record = installed["record_bytes"]
    if (
        type(metadata) is not bytes
        or len(metadata) > _MAX_DISTRIBUTION_METADATA_BYTES
        or type(installed["metadata_size"]) is not int
        or installed["metadata_size"] != len(metadata)
        or installed["metadata_sha256"] != _sha256(metadata)
        or type(record) is not bytes
        or len(record) > _MAX_DISTRIBUTION_RECORD_BYTES
        or type(installed["record_size"]) is not int
        or installed["record_size"] != len(record)
        or installed["record_sha256"] != _sha256(record)
    ):
        raise BootstrapError(f"{name} raw distribution binding is invalid")
    metadata_name, metadata_version = _metadata_name_version(metadata)
    if metadata_name != name or metadata_version != installed["version"]:
        raise BootstrapError(f"{name} METADATA binding is invalid")
    required_entries = installed["required_entries"]
    required_paths = _RUNTIME_REQUIRED_PATHS[name]
    if type(required_entries) is not dict or frozenset(required_entries) != frozenset(
        required_paths
    ):
        raise BootstrapError(f"{name} required entry set is invalid")
    parsed_rows = _parse_distribution_record(
        record,
        dist_info=dist_info,
        required_paths=required_paths,
    )
    supplied_rows = installed["record_rows"]
    if type(supplied_rows) is not tuple:
        raise BootstrapError(f"{name} normalized RECORD rows are invalid")
    for row in supplied_rows:
        if type(row) is not dict or frozenset(row) != frozenset(
            {"kind", "path", "sha256", "size"}
        ):
            raise BootstrapError(f"{name} normalized RECORD row schema is invalid")
        if (
            type(row["kind"]) is not str
            or row["kind"] not in {"required", "entry", "opaque", "self"}
            or type(row["path"]) is not str
            or (
                row["kind"] == "self"
                and (row["sha256"] is not None or row["size"] is not None)
            )
            or (
                row["kind"] != "self"
                and (
                    type(row["sha256"]) is not str
                    or _SHA256_HEX.fullmatch(row["sha256"]) is None
                    or type(row["size"]) is not int
                    or not 0 <= row["size"] <= _MAX_DISTRIBUTION_RECORD_SIZE
                )
            )
        ):
            raise BootstrapError(f"{name} normalized RECORD row value is invalid")
    if supplied_rows != parsed_rows:
        raise BootstrapError(f"{name} normalized RECORD rows are invalid")
    rows_by_path = {str(row["path"]): row for row in parsed_rows}
    for path in required_paths:
        entry = _exact_dict(
            required_entries[path],
            frozenset({"bytes", "size", "sha256"}),
            field=f"{name} required entry {path}",
        )
        content = entry["bytes"]
        if (
            type(content) is not bytes
            or len(content) > _MAX_SOURCE_BYTES
            or type(entry["size"]) is not int
            or entry["size"] != len(content)
            or entry["sha256"] != _sha256(content)
            or rows_by_path[path]["sha256"] != entry["sha256"]
            or rows_by_path[path]["size"] != entry["size"]
        ):
            raise BootstrapError(f"{name} required entry binding is invalid")
    return installed


def _validate_builder_lock_package(
    name: str,
    value: object,
    *,
    installed_version: object,
    uv_lock_sha256: str,
) -> dict[str, object]:
    lock = _exact_dict(value, _LOCK_PACKAGE_KEYS, field=f"{name} lock package")
    if (
        lock["name"] != name
        or lock["version"] != installed_version
        or lock["lock_file_sha256"] != uv_lock_sha256
        or type(lock["exact_package_object"]) is not dict
        or type(lock["canonical_package_bytes"]) is not bytes
        or type(lock["required_dependencies"]) is not tuple
        or lock["required_dependencies"] != _RUNTIME_REQUIRED_DEPENDENCIES[name]
    ):
        raise BootstrapError(f"{name} lock package binding is invalid")
    package = lock["exact_package_object"]
    if (
        type(package.get("name")) is not str
        or _pep503_name(str(package["name"])) != name
        or package.get("version") != installed_version
    ):
        raise BootstrapError(f"{name} exact lock package identity is invalid")
    canonical = _canonical_json_bytes(package)
    if (
        lock["canonical_package_bytes"] != canonical
        or lock["lock_package_sha256"] != _sha256(canonical)
    ):
        raise BootstrapError(f"{name} exact lock package digest is invalid")
    dependency_names = _lock_dependency_names(package)
    if any(required not in dependency_names for required in lock["required_dependencies"]):
        raise BootstrapError(f"{name} lock dependency closure is incomplete")
    return lock


def _build_runtime_identity_v2(
    *,
    scope: dict[str, object],
    runtime_layout: dict[str, object],
    uv_identity: dict[str, object],
    uv_lock_sha256: str,
    distributions: dict[str, object],
    plugins: dict[str, object],
) -> dict[str, object]:
    """Build the internal identity-v2 document as a strict no-I/O pure function."""

    scope_value = _exact_dict(
        scope,
        frozenset({"run_id", "target", "runner", "attempt", "timestamp"}),
        field="runtime scope",
    )
    if (
        type(scope_value["run_id"]) is not str
        or _RUN_ID.fullmatch(str(scope_value["run_id"])) is None
        or type(scope_value["target"]) is not str
        or scope_value["target"] not in {"capture", "retention"}
        or type(scope_value["runner"]) is not str
        or scope_value["runner"] not in {"macos", "linux"}
        or type(scope_value["attempt"]) is not int
        or int(scope_value["attempt"]) < 1
        or type(scope_value["timestamp"]) is not str
        or not scope_value["timestamp"]
    ):
        raise BootstrapError("runtime scope is invalid")
    runtime = _validate_runtime_identity_layout(runtime_layout)
    expected_system = "Darwin" if scope_value["runner"] == "macos" else "Linux"
    if runtime["system"] != expected_system:
        raise BootstrapError("runtime platform differs from scope runner")
    uv = _exact_dict(
        uv_identity,
        frozenset({"path", "version", "sha256"}),
        field="uv identity",
    )
    _validated_file_leaf_text(uv["path"], field="uv")
    if type(uv["version"]) is not str or not uv["version"]:
        raise BootstrapError("uv version is invalid")
    _validated_sha256(uv["sha256"], field="uv")
    _validated_sha256(uv_lock_sha256, field="uv.lock")
    if type(distributions) is not dict or frozenset(distributions) != frozenset(
        _RUNTIME_DISTRIBUTIONS
    ):
        raise BootstrapError("runtime distribution set is invalid")
    validated_distributions: dict[str, dict[str, object]] = {}
    for name in _RUNTIME_DISTRIBUTIONS:
        pair = _exact_dict(
            distributions[name],
            frozenset({"installed", "lock"}),
            field=f"{name} distribution",
        )
        installed = _validate_builder_installed_distribution(name, pair["installed"])
        lock = _validate_builder_lock_package(
            name,
            pair["lock"],
            installed_version=installed["version"],
            uv_lock_sha256=uv_lock_sha256,
        )
        validated_distributions[name] = {"installed": installed, "lock": lock}
    if type(plugins) is not dict or frozenset(plugins) != frozenset(
        {"pytest_cov.plugin", "scripts.pytest_security_events"}
    ):
        raise BootstrapError("runtime plugin set is invalid")
    validated_plugins: dict[str, dict[str, object]] = {}
    for plugin_name, plugin_value in plugins.items():
        plugin = _exact_dict(plugin_value, _PLUGIN_IDENTITY_KEYS, field=plugin_name)
        _validated_file_leaf_text(plugin["file"], field=plugin_name)
        _validated_sha256(plugin["sha256"], field=plugin_name)
        validated_plugins[plugin_name] = plugin
    cov_plugin = validated_plugins["pytest_cov.plugin"]
    cov_entry = validated_distributions["pytest-cov"]["installed"]["required_entries"][
        "pytest_cov/plugin.py"
    ]
    if (
        cov_plugin["distribution"] != "pytest-cov"
        or cov_plugin["entry"] != "pytest_cov/plugin.py"
        or cov_plugin["sha256"] != cov_entry["sha256"]
        or Path(str(cov_plugin["file"]))
        != Path(str(runtime["site_packages"])) / "pytest_cov/plugin.py"
    ):
        raise BootstrapError("pytest-cov plugin binding is invalid")
    events_plugin = validated_plugins["scripts.pytest_security_events"]
    if events_plugin["distribution"] is not None or events_plugin["entry"] is not None:
        raise BootstrapError("local events plugin distribution binding is invalid")
    document: dict[str, object] = {
        "schema_version": 2,
        "provenance": "installed-record-consistent",
        "scope": _json_boundary_value(scope_value),
        "runtime": _json_boundary_value(runtime),
        "uv": _json_boundary_value(uv),
        "uv_lock_sha256": uv_lock_sha256,
        "distributions": _json_boundary_value(validated_distributions),
        "plugins": _json_boundary_value(validated_plugins),
    }
    semantic = dict(document)
    semantic["scope"] = {"runner": scope_value["runner"]}
    document["semantic_runtime_sha256"] = _sha256(_canonical_json_bytes(semantic))
    return document


def _prepare_bound_runtime(
    executable: Path,
    *,
    python_major_minor: tuple[int, int],
    base_prefix: Path,
    lock_path: Path,
    uv_identity: dict[str, object],
) -> PreparedBoundRuntime:
    """Capture and load the current named runtime for the no-site main path."""

    if (
        executable != Path(sys.executable)
        or python_major_minor != (sys.version_info.major, sys.version_info.minor)
        or base_prefix != Path(sys.base_prefix)
        or not sys.flags.isolated
        or not sys.flags.no_site
        or not sys.flags.dont_write_bytecode
    ):
        raise BootstrapError("bound runtime does not describe the current process")
    uv = _exact_dict(
        uv_identity,
        frozenset({"path", "version", "sha256"}),
        field="uv identity",
    )
    _validated_file_leaf_text(uv["path"], field="uv")
    if (
        type(uv["version"]) is not str
        or len(uv["version"]) > 128
        or _RUNTIME_VERSION.fullmatch(uv["version"]) is None
    ):
        raise BootstrapError("uv version is invalid")
    _validated_sha256(uv["sha256"], field="uv")
    layout = _capture_runtime_layout(
        executable,
        python_major_minor=python_major_minor,
        base_prefix=base_prefix,
    )
    site_packages = Path(str(layout["site_packages"]))
    captured_distributions: dict[str, dict[str, object]] = {}
    descriptor_sources: dict[str, tuple[dict[str, object], bytes]] = {}
    lock_file_hashes: set[str] = set()
    for name in _RUNTIME_DISTRIBUTIONS:
        installed, descriptors, sources = _capture_named_distribution(
            site_packages,
            canonical_name=name,
            required_paths=_RUNTIME_REQUIRED_PATHS[name],
        )
        lock = _capture_lock_package(
            lock_path,
            canonical_name=name,
            required_dependencies=_RUNTIME_REQUIRED_DEPENDENCIES[name],
        )
        if installed["version"] != lock["version"]:
            raise BootstrapError(f"runtime distribution version differs for {name}")
        lock_file_hashes.add(str(lock["lock_file_sha256"]))
        captured_distributions[name] = {"installed": installed, "lock": lock}
        for descriptor, source in zip(descriptors, sources, strict=True):
            module_name = str(descriptor["module"])
            if module_name in descriptor_sources:
                raise BootstrapError("runtime loader descriptor is duplicated")
            descriptor_sources[module_name] = (descriptor, source)
    if len(lock_file_hashes) != 1:
        raise BootstrapError("runtime distributions came from different lock observations")
    if tuple(sorted(descriptor_sources)) != tuple(sorted(_BOUND_RUNTIME_MODULES)):
        raise BootstrapError("runtime loader descriptor closure is incomplete")
    entries = tuple(descriptor_sources[name][0] for name in _BOUND_RUNTIME_MODULES)
    sources = tuple(descriptor_sources[name][1] for name in _BOUND_RUNTIME_MODULES)
    site_text = os.fspath(site_packages)
    if site_text not in sys.path:
        sys.path.append(site_text)
    modules, _identities = _load_captured_runtime_modules(entries, sources)
    cov_distribution = captured_distributions["pytest-cov"]["installed"]
    cov_entry = cov_distribution["required_entries"]["pytest_cov/plugin.py"]
    return PreparedBoundRuntime(
        runtime_layout=layout,
        uv_identity=dict(uv),
        uv_lock_sha256=lock_file_hashes.pop(),
        distributions=captured_distributions,
        loaded_modules=modules,
        pytest_cov_plugin_identity={
            "file": os.fspath(entries[-1]["path"]),
            "sha256": cov_entry["sha256"],
            "distribution": "pytest-cov",
            "entry": "pytest_cov/plugin.py",
        },
    )


def _locked_pytest_cov_version(lock_path: Path) -> str:
    try:
        value = tomllib.loads(_stable_read(lock_path, field="uv.lock").decode("utf-8"))
        matches = [
            item
            for item in value["package"]
            if isinstance(item, dict) and item.get("name") == "pytest-cov"
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("version"), str):
            raise BootstrapError("uv.lock pytest-cov resolution is not unique")
        return matches[0]["version"]
    except (BootstrapError, KeyError, TypeError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        if isinstance(exc, BootstrapError):
            raise
        raise BootstrapError("uv.lock pytest-cov resolution is invalid") from exc


def _record_entry_digest(entry: importlib.metadata.PackagePath, *, field: str) -> bytes:
    """Decode one file digest declared by a RECORD entry, not the RECORD file hash."""

    if entry.hash is None or entry.hash.mode != "sha256" or entry.size is None:
        raise BootstrapError(f"{field} RECORD entry is invalid")
    try:
        padding = "=" * (-len(entry.hash.value) % 4)
        return base64.urlsafe_b64decode(entry.hash.value + padding)
    except (ValueError, TypeError) as exc:
        raise BootstrapError(f"{field} RECORD digest is invalid") from exc


def _pytest_cov_identity(lock_path: Path) -> tuple[types.ModuleType, dict[str, object]]:
    try:
        distribution = importlib.metadata.distribution("pytest-cov")
        name = distribution.metadata["Name"]
        version = distribution.version
        files = distribution.files or []
        plugin_matches = [item for item in files if item.as_posix() == "pytest_cov/plugin.py"]
        init_matches = [item for item in files if item.as_posix() == "pytest_cov/__init__.py"]
        if (
            name != "pytest-cov"
            or len(plugin_matches) != 1
            or len(init_matches) != 1
            or version != _locked_pytest_cov_version(lock_path)
        ):
            raise BootstrapError("pytest-cov distribution identity is invalid")

        entry = plugin_matches[0]
        init_entry = init_matches[0]
        path = Path(distribution.locate_file(entry)).resolve(strict=True)
        init_path = Path(distribution.locate_file(init_entry)).resolve(strict=True)
        content = _stable_read(path, field="pytest-cov plugin")
        init_content = _stable_read(init_path, field="pytest-cov package")
        digest = _sha256(content)
        record_entry_digest = _record_entry_digest(entry, field="pytest-cov plugin").hex()
        init_record_entry_digest = _record_entry_digest(
            init_entry, field="pytest-cov package"
        ).hex()
        if (
            digest != record_entry_digest
            or len(content) != entry.size
            or _sha256(init_content) != init_record_entry_digest
            or len(init_content) != init_entry.size
            or init_path.parent != path.parent
        ):
            raise BootstrapError("pytest-cov plugin does not match RECORD")

        for module_name in ("pytest_cov.plugin", "pytest_cov"):
            sys.modules.pop(module_name, None)
        package_spec = importlib.util.spec_from_file_location(
            "pytest_cov",
            init_path,
            submodule_search_locations=[os.fspath(init_path.parent)],
        )
        if package_spec is None:
            raise BootstrapError("pytest-cov package module spec cannot be created")
        package = importlib.util.module_from_spec(package_spec)
        sys.modules["pytest_cov"] = package
        try:
            package_code = compile(
                init_content, os.fspath(init_path), "exec", dont_inherit=True
            )
            exec(package_code, package.__dict__)
        except BaseException as exc:
            sys.modules.pop("pytest_cov", None)
            raise BootstrapError("pytest-cov package cannot be loaded") from exc

        module_spec = importlib.util.spec_from_file_location("pytest_cov.plugin", path)
        if module_spec is None:
            raise BootstrapError("pytest-cov plugin module spec cannot be created")
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module.__name__] = module
        try:
            code = compile(content, os.fspath(path), "exec", dont_inherit=True)
            exec(code, module.__dict__)
        except BaseException as exc:
            sys.modules.pop(module.__name__, None)
            raise BootstrapError("pytest-cov plugin cannot be loaded") from exc
        package.plugin = module
    except BootstrapError:
        raise
    except (ImportError, LookupError, OSError, ValueError) as exc:
        raise BootstrapError("pytest-cov plugin identity cannot be established") from exc
    return module, {
        "file": os.fspath(path),
        "sha256": digest,
        "distribution_name": "pytest-cov",
        "distribution_version": version,
        "record_sha256": record_entry_digest,
    }


def _local_events_plugin(
    repository_root: Path,
) -> tuple[types.ModuleType, dict[str, object]]:
    scripts_directory = repository_root / "scripts"
    path = (scripts_directory / "pytest_security_events.py").resolve(strict=True)
    content = _stable_read(path, field="pytest events plugin")

    for name in ("scripts.pytest_security_events", "scripts"):
        sys.modules.pop(name, None)
    parent_spec = importlib.util.spec_from_loader("scripts", loader=None, is_package=True)
    if parent_spec is None:
        raise BootstrapError("synthetic scripts package cannot be created")
    parent_spec.submodule_search_locations = [os.fspath(scripts_directory)]
    parent = importlib.util.module_from_spec(parent_spec)
    parent.__path__ = [os.fspath(scripts_directory)]
    sys.modules["scripts"] = parent

    module_spec = importlib.util.spec_from_file_location("scripts.pytest_security_events", path)
    if module_spec is None:
        raise BootstrapError("pytest events module spec cannot be created")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module.__name__] = module
    try:
        code = compile(content, os.fspath(path), "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except BaseException as exc:
        sys.modules.pop(module.__name__, None)
        raise BootstrapError("pytest events plugin cannot be loaded") from exc
    parent.pytest_security_events = module
    return module, {
        "file": os.fspath(path),
        "sha256": _sha256(content),
        "distribution": None,
        "entry": None,
    }


def _option(arguments: list[str], prefix: str) -> str:
    matches = [item.removeprefix(prefix) for item in arguments if item.startswith(prefix)]
    if len(matches) != 1 or not matches[0]:
        raise BootstrapError(f"pytest option {prefix} is not unique")
    return matches[0]


def _scope(pytest_arguments: list[str]) -> dict[str, object]:
    run_id = _option(pytest_arguments, "--security-run-id=")
    target = _option(pytest_arguments, "--security-target=")
    runner = _option(pytest_arguments, "--security-runner=")
    attempt_text = _option(pytest_arguments, "--security-attempt=")
    if (
        _RUN_ID.fullmatch(run_id) is None
        or target not in {"capture", "retention"}
        or runner not in {"macos", "linux"}
        or not attempt_text.isdecimal()
        or int(attempt_text) < 1
    ):
        raise BootstrapError("pytest security scope is invalid")
    return {
        "run_id": run_id,
        "target": target,
        "runner": runner,
        "attempt": int(attempt_text),
    }


def _write_exclusive(path: Path, value: dict[str, object]) -> None:
    if not path.is_absolute() or path != path.parent.resolve(strict=True) / path.name or path.exists():
        raise BootstrapError("plugin identity output path is invalid")
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        try:
            os.link(temporary, path, follow_symlinks=False)
        except OSError as exc:
            raise BootstrapError(
                "plugin identity cannot be published without replacement"
            ) from exc
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


class _IdentityGuard:
    def __init__(
        self,
        *,
        modules: dict[str, types.ModuleType],
        output: Path,
        repository_root: Path,
        document: dict[str, object],
    ) -> None:
        self._modules = modules
        self._output = output
        self._repository_root = repository_root
        self._document = document

    def pytest_configure(self, config: Any) -> None:
        manager = config.pluginmanager
        for name, module in self._modules.items():
            if manager.get_plugin(name) is not module or sys.modules.get(name) is not module:
                raise BootstrapError(f"pytest plugin registration differs for {name}")
        _write_exclusive(self._output, self._document)
        root = os.fspath(self._repository_root)
        if root not in sys.path:
            sys.path.insert(0, root)


def _arguments(
    argv: list[str],
) -> tuple[Path, dict[str, object], str, list[str]]:
    prefixes = (
        "--plugin-identity=",
        "--runtime-uv-path=",
        "--runtime-uv-version=",
        "--runtime-uv-sha256=",
        "--runtime-timestamp=",
    )
    if (
        len(argv) < 7
        or argv[5] != "--"
        or any(not argv[index].startswith(prefix) for index, prefix in enumerate(prefixes))
        or any(sum(item.startswith(prefix) for item in argv) != 1 for prefix in prefixes)
    ):
        raise BootstrapError("bootstrap arguments are invalid")
    values = tuple(argv[index].removeprefix(prefix) for index, prefix in enumerate(prefixes))
    output_text, uv_path, uv_version, uv_sha256, timestamp = values
    if (
        not output_text
        or not _lexically_canonical_absolute(Path(output_text))
        or not Path(output_text).name
    ):
        raise BootstrapError("plugin identity output is invalid")
    _validated_file_leaf_text(uv_path, field="uv")
    if (
        len(uv_version) > 128
        or _RUNTIME_VERSION.fullmatch(uv_version) is None
    ):
        raise BootstrapError("uv version is invalid")
    _validated_sha256(uv_sha256, field="uv")
    if _RUNTIME_TIMESTAMP.fullmatch(timestamp) is None:
        raise BootstrapError("runtime timestamp is invalid")
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise BootstrapError("runtime timestamp is invalid") from exc
    return (
        Path(output_text),
        {"path": uv_path, "version": uv_version, "sha256": uv_sha256},
        timestamp,
        argv[6:],
    )


def main(argv: list[str] | None = None) -> int:
    try:
        if (
            not sys.flags.isolated
            or not sys.flags.no_site
            or not sys.flags.dont_write_bytecode
        ):
            raise BootstrapError("python must run with -I -S -B")
        output, uv_identity, timestamp, pytest_arguments = _arguments(
            sys.argv[1:] if argv is None else argv
        )
        repository_root = Path(__file__).resolve(strict=True).parents[1]
        scope = _scope(pytest_arguments)
        scope["timestamp"] = timestamp
        prepared = _prepare_bound_runtime(
            Path(sys.executable),
            python_major_minor=(sys.version_info.major, sys.version_info.minor),
            base_prefix=Path(sys.base_prefix),
            lock_path=repository_root / "uv.lock",
            uv_identity=uv_identity,
        )
        events_module, events_identity = _local_events_plugin(repository_root)
        document = _build_runtime_identity_v2(
            scope=scope,
            runtime_layout=prepared.runtime_layout,
            uv_identity=prepared.uv_identity,
            uv_lock_sha256=prepared.uv_lock_sha256,
            distributions=prepared.distributions,
            plugins={
                "pytest_cov.plugin": prepared.pytest_cov_plugin_identity,
                "scripts.pytest_security_events": events_identity,
            },
        )
        modules = {
            "pytest_cov.plugin": prepared.loaded_modules["pytest_cov.plugin"],
            "scripts.pytest_security_events": events_module,
        }
        guard = _IdentityGuard(
            modules=modules,
            output=output,
            repository_root=repository_root,
            document=document,
        )
        import pytest

        return int(pytest.main(pytest_arguments, plugins=[*modules.values(), guard]))
    except (BootstrapError, OSError, ValueError) as exc:
        print(f"SECURITY_PYTEST_BOOTSTRAP_INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
