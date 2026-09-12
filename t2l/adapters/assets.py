"""Secure, CWD-independent asset resolution and integrity validation."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
import tempfile
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Any, Literal, TypeVar

from t2l.errors import AssetNotFoundError, CheckpointError, ConfigurationError

_AUTO_DEVELOPMENT_ROOT = object()
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
_LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"
_LOAD_RESULT = TypeVar("_LOAD_RESULT")


@dataclass(frozen=True, slots=True)
class AssetSpec:
    """A manifest entry for one local runtime asset."""

    logical_name: str
    relative_path: str
    sha256: str
    size: int | None = None
    architecture_id: str | None = None
    feature_spec_id: str | None = None
    phone_inventory_id: str | None = None
    source: str | None = None
    license: str | None = None

    def __post_init__(self) -> None:
        if not self.logical_name:
            raise ValueError("asset logical_name must not be empty")
        relative = PurePath(self.relative_path)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError("asset relative_path must stay below its asset root")
        if not _SHA256_RE.fullmatch(self.sha256):
            raise ValueError("asset sha256 must contain exactly 64 hexadecimal characters")
        if self.size is not None and self.size < 0:
            raise ValueError("asset size must be non-negative")

    @classmethod
    def from_manifest_entry(cls, entry: Any) -> AssetSpec:
        """Adapt a validated manifest value without importing its owner module."""

        return cls(
            logical_name=entry.logical_name,
            relative_path=os.fspath(entry.relative_path),
            sha256=entry.sha256,
            size=getattr(entry, "size", getattr(entry, "size_bytes", None)),
            architecture_id=getattr(entry, "architecture_id", None),
            feature_spec_id=getattr(entry, "feature_spec_id", None),
            phone_inventory_id=getattr(entry, "phone_inventory_id", None),
            source=getattr(entry, "source", None),
            license=getattr(entry, "license", None),
        )


@dataclass(frozen=True, slots=True)
class ResolvedAsset:
    """A verified path together with its resolution provenance."""

    path: Path
    provenance: Literal["config", "environment", "development"]
    spec: AssetSpec


class MaterializedAssetSet:
    """A private, read-only asset tree owned by one runtime instance."""

    def __init__(
        self,
        owner: tempfile.TemporaryDirectory,
        paths: Mapping[str, Path],
    ) -> None:
        self._owner = owner
        self.root = Path(owner.name).resolve()
        self.paths = MappingProxyType(dict(paths))
        self._closed = False
        self._close_lock = threading.Lock()

    def path(self, logical_name: str) -> Path:
        return self.paths[logical_name]

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            if self.root.exists():
                for path in sorted(
                    self.root.rglob("*"), key=lambda item: len(item.parts), reverse=True
                ):
                    path.chmod(0o700 if path.is_dir() else 0o600)
                self.root.chmod(0o700)
            self._owner.cleanup()
            self._closed = True

    def __enter__(self) -> MaterializedAssetSet:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class AssetLocator:
    """Resolve manifest assets without ever consulting the process CWD."""

    def __init__(
        self,
        asset_root: str | os.PathLike[str] | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        development_root: str | os.PathLike[str] | object | None = _AUTO_DEVELOPMENT_ROOT,
    ) -> None:
        self._asset_root = _normalized_root(asset_root, source="config")
        self._environ = os.environ if environ is None else environ
        if development_root is _AUTO_DEVELOPMENT_ROOT:
            self._development_root = _discover_development_root()
        else:
            self._development_root = _normalized_root(
                development_root, source="development"
            )

    def resolve(self, spec: AssetSpec) -> ResolvedAsset:
        root, provenance = self._selected_root(spec.logical_name)
        path = (root / spec.relative_path).resolve(strict=False)
        if not path.is_relative_to(root):
            raise CheckpointError(
                f"Asset {spec.logical_name!r} resolves outside its configured root",
                code="T2L_ASSET_PATH_ESCAPE",
                stage="asset_resolution",
                details={"logical_name": spec.logical_name, "root": str(root)},
            )
        if not path.is_file():
            raise AssetNotFoundError(
                f"Required asset {spec.logical_name!r} was not found",
                code="T2L_ASSET_NOT_FOUND",
                stage="asset_resolution",
                details={
                    "logical_name": spec.logical_name,
                    "relative_path": spec.relative_path,
                    "checked_roots": [str(root)],
                },
            )

        _reject_lfs_pointer(path, spec)
        actual_size = path.stat().st_size
        if spec.size is not None and actual_size != spec.size:
            raise CheckpointError(
                f"Asset {spec.logical_name!r} has an unexpected size",
                code="T2L_ASSET_SIZE_MISMATCH",
                stage="asset_resolution",
                details={
                    "logical_name": spec.logical_name,
                    "expected_size": spec.size,
                    "actual_size": actual_size,
                },
            )
        actual_hash = _sha256(path)
        if not hmac.compare_digest(actual_hash, spec.sha256.lower()):
            raise CheckpointError(
                f"Asset {spec.logical_name!r} failed SHA-256 verification",
                code="T2L_ASSET_HASH_MISMATCH",
                stage="asset_resolution",
                details={
                    "logical_name": spec.logical_name,
                    "expected_sha256": spec.sha256.lower(),
                    "actual_sha256": actual_hash,
                },
            )
        return ResolvedAsset(path=path, provenance=provenance, spec=spec)

    def load(
        self,
        spec: AssetSpec,
        loader: Callable[[Path], _LOAD_RESULT],
    ) -> _LOAD_RESULT:
        """Validate an asset completely before passing its path to a loader."""

        return loader(self.resolve(spec).path)

    def materialize_set(
        self,
        assets: Mapping[str, tuple[AssetSpec, str | os.PathLike[str]]],
    ) -> MaterializedAssetSet:
        """Publish a complete verified set at private, runtime-owned paths."""

        snapshots: dict[str, tuple[bytes, PurePath]] = {}
        destinations: set[PurePath] = set()
        for logical_name, (spec, destination_value) in assets.items():
            if logical_name != spec.logical_name:
                raise ValueError("asset-set key must match AssetSpec.logical_name")
            destination = PurePath(destination_value)
            if (
                destination.is_absolute()
                or not destination.parts
                or ".." in destination.parts
                or destination in destinations
            ):
                raise ValueError("materialized asset paths must be unique and relative")
            destinations.add(destination)
            snapshots[logical_name] = (self._verified_snapshot(spec), destination)

        owner = tempfile.TemporaryDirectory(prefix="ai-auto-lrc-assets-")
        root = Path(owner.name).resolve()
        materialized: dict[str, Path] = {}
        try:
            for logical_name, (content, destination) in snapshots.items():
                output = root.joinpath(*destination.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                if output.read_bytes() != content:
                    raise OSError(f"materialized asset {logical_name!r} changed while publishing")
                output.chmod(stat.S_IRUSR)
                materialized[logical_name] = output
            for directory in sorted(
                (path for path in root.rglob("*") if path.is_dir()),
                key=lambda item: len(item.parts),
                reverse=True,
            ):
                directory.chmod(stat.S_IRUSR | stat.S_IXUSR)
            root.chmod(stat.S_IRUSR | stat.S_IXUSR)
        except Exception:
            MaterializedAssetSet(owner, materialized).close()
            raise
        return MaterializedAssetSet(owner, materialized)

    def _verified_snapshot(self, spec: AssetSpec) -> bytes:
        """Read and validate one source through a single stable file handle."""

        root, _provenance = self._selected_root(spec.logical_name)
        lexical_path = root / spec.relative_path
        path = lexical_path.resolve(strict=False)
        if not path.is_relative_to(root):
            raise CheckpointError(
                f"Asset {spec.logical_name!r} resolves outside its configured root",
                code="T2L_ASSET_PATH_ESCAPE",
                stage="asset_resolution",
                details={"logical_name": spec.logical_name, "root": str(root)},
            )
        current = root
        for part in PurePath(spec.relative_path).parts:
            current /= part
            if current.is_symlink():
                raise CheckpointError(
                    f"Asset {spec.logical_name!r} uses a symlink",
                    code="T2L_ASSET_SYMLINK_REJECTED",
                    stage="asset_resolution",
                    details={"logical_name": spec.logical_name, "path": str(current)},
                )
        try:
            with lexical_path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                content = stream.read()
                after = os.fstat(stream.fileno())
                visible = lexical_path.lstat()
        except FileNotFoundError as exc:
            raise AssetNotFoundError(
                f"Required asset {spec.logical_name!r} was not found",
                code="T2L_ASSET_NOT_FOUND",
                stage="asset_resolution",
                details={
                    "logical_name": spec.logical_name,
                    "relative_path": spec.relative_path,
                    "checked_roots": [str(root)],
                },
            ) from exc
        except OSError as exc:
            raise CheckpointError(
                f"Asset {spec.logical_name!r} could not be read",
                code="T2L_ASSET_READ_FAILED",
                stage="asset_resolution",
                details={"logical_name": spec.logical_name, "path": str(path)},
            ) from exc
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        visible_identity = (
            visible.st_dev,
            visible.st_ino,
            visible.st_size,
            visible.st_mtime_ns,
        )
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(visible.st_mode)
            or before_identity != after_identity
            or after_identity != visible_identity
        ):
            raise CheckpointError(
                f"Asset {spec.logical_name!r} changed while being read",
                code="T2L_ASSET_CHANGED_DURING_READ",
                stage="asset_resolution",
                details={"logical_name": spec.logical_name, "path": str(path)},
            )
        if content.startswith(_LFS_HEADER):
            raise CheckpointError(
                f"Asset {spec.logical_name!r} is a Git LFS pointer, not the asset object",
                code="T2L_ASSET_LFS_POINTER",
                stage="asset_resolution",
                details={"logical_name": spec.logical_name, "path": str(path)},
            )
        actual_size = len(content)
        if spec.size is not None and actual_size != spec.size:
            raise CheckpointError(
                f"Asset {spec.logical_name!r} has an unexpected size",
                code="T2L_ASSET_SIZE_MISMATCH",
                stage="asset_resolution",
                details={
                    "logical_name": spec.logical_name,
                    "expected_size": spec.size,
                    "actual_size": actual_size,
                },
            )
        actual_hash = hashlib.sha256(content).hexdigest()
        if not hmac.compare_digest(actual_hash, spec.sha256.lower()):
            raise CheckpointError(
                f"Asset {spec.logical_name!r} failed SHA-256 verification",
                code="T2L_ASSET_HASH_MISMATCH",
                stage="asset_resolution",
                details={
                    "logical_name": spec.logical_name,
                    "expected_sha256": spec.sha256.lower(),
                    "actual_sha256": actual_hash,
                },
            )
        return content

    def _selected_root(
        self, logical_name: str
    ) -> tuple[Path, Literal["config", "environment", "development"]]:
        if self._asset_root is not None:
            return self._asset_root, "config"
        env_value = self._environ.get("T2L_ASSET_ROOT")
        if env_value:
            environment_root = _normalized_root(env_value, source="environment")
            assert environment_root is not None
            return environment_root, "environment"
        if self._development_root is not None:
            return self._development_root, "development"
        raise AssetNotFoundError(
            f"No asset root is configured for {logical_name!r}",
            code="T2L_ASSET_NOT_FOUND",
            stage="asset_resolution",
            details={"logical_name": logical_name, "checked_roots": []},
        )


def _normalized_root(
    value: str | os.PathLike[str] | None, *, source: str
) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ConfigurationError(
            f"The {source} asset root must be an absolute path",
            code="T2L_ASSET_ROOT_INVALID",
            stage="configuration",
            details={"source": source},
        )
    return path.resolve(strict=False)


def _discover_development_root() -> Path | None:
    """Find a source checkout relative to this module, never relative to CWD."""

    package_root = Path(__file__).resolve().parents[1]
    candidate = package_root.parent
    if (candidate / ".git").exists() and package_root == candidate / "t2l":
        return candidate
    return None


def _reject_lfs_pointer(path: Path, spec: AssetSpec) -> None:
    with path.open("rb") as handle:
        prefix = handle.read(256)
    if prefix.startswith(_LFS_HEADER):
        raise CheckpointError(
            f"Asset {spec.logical_name!r} is a Git LFS pointer, not the asset object",
            code="T2L_ASSET_LFS_POINTER",
            stage="asset_resolution",
            details={"logical_name": spec.logical_name, "path": str(path)},
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["AssetLocator", "AssetSpec", "MaterializedAssetSet", "ResolvedAsset"]
