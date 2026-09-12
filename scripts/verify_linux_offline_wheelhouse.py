#!/usr/bin/env python3
"""Verify a Linux x86_64 wheelhouse without network or source imports."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import stat
import subprocess
import sys
import sysconfig
import tempfile
import venv
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

try:
    from packaging.tags import sys_tags
    from packaging.utils import parse_wheel_filename
except ModuleNotFoundError:  # pragma: no cover - bootstrap image uses pip's vendor copy
    from pip._vendor.packaging.tags import sys_tags
    from pip._vendor.packaging.utils import parse_wheel_filename


DIRECT_IMPORT_NAMES = tuple(
    sorted(
        {
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
            "torch",
            "torchaudio",
            "t2l",
        }
    )
)
EXPECTED_CLI_STDOUT = "[00:00.034]hello\n"
RUN_ID_ENV = "AI_AUTO_LRC_EVIDENCE_RUN_ID"


@dataclass(frozen=True)
class _FileIdentity:
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class _VerifiedArtifact:
    relative_path: str
    sha256: str
    size: int
    identity: _FileIdentity


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _text_sha256(content: str) -> str:
    return _bytes_sha256(content.encode("utf-8"))


def _safe_relative_name(name: str, *, label: str) -> PurePosixPath:
    posix_path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or posix_path.is_absolute()
        or posix_path.as_posix() != name
        or any(part in {".", ".."} for part in posix_path.parts)
    ):
        raise AssertionError(f"unsafe {label}: {name!r}")
    return posix_path


def _artifact_record(path: Path, *, name: str | None = None) -> dict[str, object]:
    record_name = path.name if name is None else name
    _safe_relative_name(record_name, label="artifact record name")
    file_stat = path.stat()
    if not path.is_file() or path.is_symlink():
        raise AssertionError(f"artifact record is not a regular file: {record_name}")
    return {
        "name": record_name,
        "size": file_stat.st_size,
        "sha256": _sha256(path),
    }


def _wheel_tag_records(paths: list[Path]) -> list[str]:
    tags = set()
    for path in paths:
        _name, _version, _build, wheel_tags = parse_wheel_filename(path.name)
        tags.update(str(tag) for tag in wheel_tags)
    return sorted(tags)


def _wheelhouse_aggregate_sha256(manifest: dict[str, object]) -> str:
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise AssertionError("manifest files must be an object")
    flattened = []
    for group, records in files.items():
        if not isinstance(group, str) or not isinstance(records, list):
            raise AssertionError("manifest file groups must map strings to lists")
        for record in records:
            if not isinstance(record, dict):
                raise AssertionError("manifest record must be an object")
            flattened.append(
                {
                    "group": group,
                    "path": record["path"],
                    "size": record["size"],
                    "sha256": record["sha256"],
                }
            )
    flattened.sort(key=lambda record: (record["group"], record["path"]))
    canonical = json.dumps(
        flattened,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _bytes_sha256(canonical)


def _pth_records(
    installation: Path,
    snapshot: dict[str, str],
) -> list[dict[str, object]]:
    records = []
    for name, expected_sha256 in sorted(snapshot.items()):
        relative_path = _safe_relative_name(name, label=".pth path")
        record = _artifact_record(
            installation.joinpath(*relative_path.parts),
            name=name,
        )
        if record["sha256"] != expected_sha256:
            raise AssertionError(f".pth snapshot hash mismatch: {name}")
        records.append(record)
    return records


def _validate_direct_imports(names: object) -> list[str]:
    if not isinstance(names, (list, tuple)) or not all(
        isinstance(name, str) for name in names
    ):
        raise AssertionError("direct import set must be a string array")
    normalized = sorted(set(names))
    if len(normalized) != len(names) or tuple(normalized) != DIRECT_IMPORT_NAMES:
        raise AssertionError("direct import set does not match policy")
    return normalized


def _build_observation(
    *,
    run_id: str,
    scope: dict[str, str],
    network_result: int,
    manifest: dict[str, object],
    manifest_path: Path,
    runtime_wheels: list[Path],
    build_wheels: list[Path],
    source_distribution: Path,
    project_wheel: Path,
    installation: Path,
    pth_before: dict[str, str],
    pth_after: dict[str, str],
    pip_check_result: subprocess.CompletedProcess[str],
    direct_imports: object,
    installed_package_path: Path,
    installed_package_name: str,
    cli_result: subprocess.CompletedProcess[str],
    expected_cli_stdout: str,
) -> dict[str, object]:
    if not run_id:
        raise AssertionError("evidence run ID is required")
    if pth_before != pth_after:
        raise AssertionError(".pth snapshots differ before and after installation")
    if pip_check_result.returncode != 0:
        raise AssertionError("pip check did not succeed")
    if cli_result.returncode != 0:
        raise AssertionError("installed CLI did not succeed")
    installation_root = installation.resolve()
    if not installed_package_path.resolve().is_relative_to(installation_root):
        raise AssertionError("installed package is outside the installation")
    _safe_relative_name(installed_package_name, label="installed package path")

    files = manifest["files"]
    if not isinstance(files, dict):
        raise AssertionError("manifest files must be an object")
    artifact_records = files.get("artifacts")
    if not isinstance(artifact_records, list):
        raise AssertionError("manifest artifact group must be a list")

    return {
        "schema": "ai-auto-lrc/linux-package-observation",
        "schema_version": 1,
        "run_id": run_id,
        "scope": dict(scope),
        "network": {
            "policy": "denied",
            "probe": "connect_ex",
            "blocked": network_result != 0,
            "result_code": network_result,
        },
        "wheelhouse": {
            "manifest_sha256": _sha256(manifest_path),
            "runtime_wheel_count": len(runtime_wheels),
            "build_wheel_count": len(build_wheels),
            "artifact_count": len(artifact_records),
            "aggregate_sha256": _wheelhouse_aggregate_sha256(manifest),
        },
        "build": {
            "source": "sdist",
            "sdist": _artifact_record(source_distribution),
            "project_wheel": _artifact_record(project_wheel),
            "runtime_wheel_tags": _wheel_tag_records(runtime_wheels),
            "build_wheel_tags": _wheel_tag_records(build_wheels),
            "project_wheel_tags": _wheel_tag_records([project_wheel]),
        },
        "installation": {
            "pip_check_exit_code": pip_check_result.returncode,
            "pip_check_stdout_sha256": _text_sha256(pip_check_result.stdout),
            "pip_check_stderr_sha256": _text_sha256(pip_check_result.stderr),
            "pth_before": _pth_records(installation, pth_before),
            "pth_after": _pth_records(installation, pth_after),
            "direct_imports": _validate_direct_imports(direct_imports),
            "installed_package_origin_scope": "site-packages",
            "installed_package": _artifact_record(
                installed_package_path,
                name=installed_package_name,
            ),
        },
        "cli": {
            "command_id": "installed-public-e2e-v1",
            "exit_code": cli_result.returncode,
            "stdout_sha256": _text_sha256(cli_result.stdout),
            "stderr_sha256": _text_sha256(cli_result.stderr),
            "expected_stdout_sha256": _text_sha256(expected_cli_stdout),
        },
    }


def _identity(file_stat: os.stat_result) -> _FileIdentity:
    return _FileIdentity(
        device=file_stat.st_dev,
        inode=file_stat.st_ino,
        mode=file_stat.st_mode,
        size=file_stat.st_size,
        mtime_ns=file_stat.st_mtime_ns,
        ctime_ns=file_stat.st_ctime_ns,
    )


def _open_readonly_no_follow(path: Path) -> BinaryIO:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.fdopen(os.open(path, flags), "rb")


def _stable_sha256(
    path: Path,
    expected_identity: _FileIdentity,
    *,
    phase: str,
) -> str:
    with _open_readonly_no_follow(path) as stream:
        opened_identity = _identity(os.fstat(stream.fileno()))
        if opened_identity != expected_identity:
            raise AssertionError(f"artifact changed {phase}: {path}")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        final_identity = _identity(os.fstat(stream.fileno()))
    try:
        current_identity = _identity(path.lstat())
    except FileNotFoundError as error:
        raise AssertionError(f"artifact changed {phase}: {path}") from error
    if final_identity != opened_identity or current_identity != opened_identity:
        raise AssertionError(f"artifact changed {phase}: {path}")
    return digest.hexdigest()


def _read_stable_regular_bytes(path: Path, *, label: str) -> bytes:
    """Read one regular non-symlink file without changing its path identity."""

    try:
        path_identity = _identity(path.lstat())
    except FileNotFoundError as error:
        raise AssertionError(f"{label} is missing: {path}") from error
    if stat.S_ISLNK(path_identity.mode) or not stat.S_ISREG(path_identity.mode):
        raise AssertionError(f"{label} is not a regular non-symlink file: {path}")
    with _open_readonly_no_follow(path) as stream:
        opened_identity = _identity(os.fstat(stream.fileno()))
        if opened_identity != path_identity:
            raise AssertionError(f"{label} changed before reading: {path}")
        content = stream.read()
        final_identity = _identity(os.fstat(stream.fileno()))
    try:
        current_identity = _identity(path.lstat())
    except FileNotFoundError as error:
        raise AssertionError(f"{label} changed while reading: {path}") from error
    if final_identity != opened_identity or current_identity != opened_identity:
        raise AssertionError(f"{label} changed while reading: {path}")
    if len(content) != opened_identity.size:
        raise AssertionError(f"{label} size changed while reading: {path}")
    return content


def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _verify_manifest(
    wheelhouse: Path,
    manifest: dict[str, object],
) -> tuple[_VerifiedArtifact, ...]:
    recorded_paths: set[str] = set()
    verified_artifacts = []
    files = manifest["files"]
    if not isinstance(files, dict):
        raise AssertionError("manifest files must be an object")
    for records in files.values():
        if not isinstance(records, list):
            raise AssertionError("manifest file group must be a list")
        for record in records:
            if not isinstance(record, dict):
                raise AssertionError("manifest record must be an object")
            relative_path = record.get("path")
            if not isinstance(relative_path, str):
                raise AssertionError("manifest path must be a string")
            posix_path = PurePosixPath(relative_path)
            if (
                not relative_path
                or "\\" in relative_path
                or posix_path.is_absolute()
                or posix_path.as_posix() != relative_path
                or any(part in {".", ".."} for part in posix_path.parts)
            ):
                raise AssertionError(f"unsafe manifest path: {relative_path!r}")
            if relative_path in recorded_paths:
                raise AssertionError(f"duplicate manifest path: {relative_path}")

            artifact = wheelhouse
            artifact_stat = None
            for index, part in enumerate(posix_path.parts):
                artifact /= part
                try:
                    artifact_stat = artifact.lstat()
                except FileNotFoundError as error:
                    raise AssertionError(
                        f"manifest artifact is missing: {relative_path}"
                    ) from error
                if stat.S_ISLNK(artifact_stat.st_mode):
                    raise AssertionError(f"manifest artifact uses symlink: {relative_path}")
                if index < len(posix_path.parts) - 1 and not stat.S_ISDIR(
                    artifact_stat.st_mode
                ):
                    raise AssertionError(
                        f"manifest artifact parent is not a directory: {relative_path}"
                    )
            if artifact_stat is None or not stat.S_ISREG(artifact_stat.st_mode):
                raise AssertionError(
                    f"manifest artifact is not a regular file: {relative_path}"
                )
            size = record.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise AssertionError(f"invalid manifest size: {relative_path}")
            expected_sha256 = record.get("sha256")
            if (
                not isinstance(expected_sha256, str)
                or len(expected_sha256) != 64
                or any(character not in "0123456789abcdef" for character in expected_sha256)
            ):
                raise AssertionError(f"invalid manifest sha256: {relative_path}")
            identity = _identity(artifact_stat)
            if identity.size != size:
                raise AssertionError(f"size mismatch: {relative_path}")
            if (
                _stable_sha256(
                    artifact,
                    identity,
                    phase="during manifest validation",
                )
                != expected_sha256
            ):
                raise AssertionError(f"hash mismatch: {relative_path}")
            recorded_paths.add(relative_path)
            verified_artifacts.append(
                _VerifiedArtifact(
                    relative_path=relative_path,
                    sha256=expected_sha256,
                    size=size,
                    identity=identity,
                )
            )

    actual_paths = set()
    manifest_path = wheelhouse / "manifest.json"
    for path in wheelhouse.rglob("*"):
        if path == manifest_path:
            continue
        path_stat = path.lstat()
        if stat.S_ISLNK(path_stat.st_mode):
            raise AssertionError(
                f"wheelhouse contains symlink: {path.relative_to(wheelhouse).as_posix()}"
            )
        if stat.S_ISDIR(path_stat.st_mode):
            continue
        if not stat.S_ISREG(path_stat.st_mode):
            raise AssertionError(
                "wheelhouse contains non-regular file: "
                f"{path.relative_to(wheelhouse).as_posix()}"
            )
        actual_paths.add(path.relative_to(wheelhouse).as_posix())
    if actual_paths != recorded_paths:
        raise AssertionError("wheelhouse manifest does not cover exactly all files")
    return tuple(verified_artifacts)


def _copy_stream(source: BinaryIO, destination: BinaryIO) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        destination.write(chunk)
        digest.update(chunk)
        size += len(chunk)
    return size, digest.hexdigest()


def _copy_verified_artifact(
    source: Path,
    destination: Path,
    record: _VerifiedArtifact,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _open_readonly_no_follow(source) as source_stream:
        opened_identity = _identity(os.fstat(source_stream.fileno()))
        if opened_identity != record.identity:
            raise AssertionError(
                f"artifact changed after manifest validation: {record.relative_path}"
            )
        with destination.open("xb") as destination_stream:
            copied_size, copied_sha256 = _copy_stream(
                source_stream,
                destination_stream,
            )
        final_identity = _identity(os.fstat(source_stream.fileno()))
    try:
        current_identity = _identity(source.lstat())
    except FileNotFoundError as error:
        raise AssertionError(
            f"artifact changed during snapshot copy: {record.relative_path}"
        ) from error
    if final_identity != opened_identity or current_identity != opened_identity:
        raise AssertionError(
            f"artifact changed during snapshot copy: {record.relative_path}"
        )
    if copied_size != record.size:
        raise AssertionError(f"snapshot size mismatch: {record.relative_path}")
    if copied_sha256 != record.sha256:
        raise AssertionError(f"snapshot hash mismatch: {record.relative_path}")


def _materialize_verified_snapshot(
    wheelhouse: Path,
    snapshot: Path,
    manifest: dict[str, object],
    verified_artifacts: tuple[_VerifiedArtifact, ...],
    manifest_bytes: bytes,
) -> Path:
    if json.loads(manifest_bytes.decode("utf-8")) != manifest:
        raise AssertionError("manifest bytes do not match the validated document")
    if snapshot.exists():
        raise AssertionError(f"refusing to replace existing snapshot: {snapshot}")
    snapshot.mkdir(mode=0o700)
    try:
        for record in verified_artifacts:
            relative_path = PurePosixPath(record.relative_path)
            _copy_verified_artifact(
                wheelhouse.joinpath(*relative_path.parts),
                snapshot.joinpath(*relative_path.parts),
                record,
            )
        (snapshot / "manifest.json").write_bytes(manifest_bytes)
        _verify_manifest(snapshot, manifest)
    except BaseException:
        shutil.rmtree(snapshot)
        raise
    return snapshot


def _verify_wheel_tags(paths: list[Path]) -> None:
    supported = set(sys_tags())
    for path in paths:
        _name, _version, _build, tags = parse_wheel_filename(path.name)
        if tags.isdisjoint(supported):
            raise AssertionError(f"incompatible wheel tags: {path.name}")


def _snapshot_pth_files(installation: Path) -> dict[str, str]:
    """Lock every baseline .pth file by installation-relative path and hash."""

    installation = installation.resolve()
    snapshot = {}
    for pth_path in installation.rglob("*.pth"):
        if pth_path.is_symlink():
            raise AssertionError(f"symlinked .pth file is forbidden: {pth_path}")
        relative_path = pth_path.relative_to(installation).as_posix()
        snapshot[relative_path] = _sha256(pth_path)
    return snapshot


def _verify_no_external_pth(
    installation: Path,
    baseline: dict[str, str],
) -> None:
    """Reject changed .pth state and paths that escape the fresh installation."""

    installation = installation.resolve()
    actual = _snapshot_pth_files(installation)
    if actual != baseline:
        added = sorted(actual.keys() - baseline.keys())
        removed = sorted(baseline.keys() - actual.keys())
        modified = sorted(
            path for path in actual.keys() & baseline.keys() if actual[path] != baseline[path]
        )
        raise AssertionError(
            ".pth inventory changed during wheel installation: "
            f"added={added!r}, removed={removed!r}, modified={modified!r}"
        )
    for relative_path in sorted(actual):
        pth_path = installation / relative_path
        for line_number, line in enumerate(
            pth_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            entry = line.strip()
            if not entry or entry.startswith("#") or entry.startswith(("import ", "import\t")):
                continue
            candidate = Path(entry)
            if not candidate.is_absolute():
                candidate = pth_path.parent / candidate
            if not candidate.resolve().is_relative_to(installation):
                raise AssertionError(
                    "external path from .pth is forbidden: "
                    f"{pth_path}:{line_number}: {entry!r}"
                )


def _cold_environment(work: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "DEMUCS_CACHE": str(work / "empty-demucs-cache"),
            "HF_HOME": str(work / "empty-hf-cache"),
            "HOME": str(work / "empty-home"),
            "NLTK_DATA": str(work / "empty-nltk-cache"),
            "PIP_CACHE_DIR": str(work / "empty-pip-cache"),
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_CACHE_DIR": "1",
            "PIP_NO_INDEX": "1",
            "PYTHONNOUSERSITE": "1",
            "TORCH_HOME": str(work / "empty-torch-cache"),
            "UV_CACHE_DIR": str(work / "empty-uv-cache"),
            "UV_NO_CACHE": "1",
            "UV_OFFLINE": "1",
            "XDG_CACHE_HOME": str(work / "empty-xdg-cache"),
        }
    )
    for name in (
        "DEMUCS_CACHE",
        "HF_HOME",
        "HOME",
        "NLTK_DATA",
        "PIP_CACHE_DIR",
        "TORCH_HOME",
        "UV_CACHE_DIR",
        "XDG_CACHE_HOME",
    ):
        directory = Path(environment[name])
        directory.mkdir()
        if list(directory.iterdir()):
            raise AssertionError(f"cache directory was not empty: {directory}")
    return environment


def _copy_runtime_assets(source: Path, destination: Path) -> None:
    for relative_path in (
        "lid.176.ftz",
        "checkpoints/checkpoint_MTL",
        "assets/nltk_data/taggers/averaged_perceptron_tagger.zip",
        "assets/nltk_data/corpora/cmudict.zip",
    ):
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative_path, target)


def verify(wheelhouse: Path, evidence_source: Path) -> dict[str, object]:
    source_wheelhouse = wheelhouse.resolve()
    evidence_source = evidence_source.resolve()
    if platform.python_implementation() != "CPython":
        raise AssertionError("CPython is required")
    if platform.machine() != "x86_64" or sysconfig.get_platform() != "linux-x86_64":
        raise AssertionError("Linux x86_64 interpreter is required")
    if sys.flags.isolated != 1:
        raise AssertionError("verifier must run with python -I")
    run_id = os.environ.get(RUN_ID_ENV)
    if not run_id:
        raise AssertionError(f"{RUN_ID_ENV} is required")

    network_probe = socket.socket()
    try:
        network_result = network_probe.connect_ex(("1.1.1.1", 443))
    finally:
        network_probe.close()
    if network_result == 0:
        raise AssertionError("network namespace unexpectedly permits outbound traffic")

    source_manifest_path = source_wheelhouse / "manifest.json"
    manifest_bytes = _read_stable_regular_bytes(
        source_manifest_path,
        label="wheelhouse manifest",
    )
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    verified_artifacts = _verify_manifest(source_wheelhouse, manifest)
    target = manifest["target"]
    expected_target = {
        "implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "machine": platform.machine(),
        "platform": sysconfig.get_platform(),
    }
    for key, expected in expected_target.items():
        if target[key] != expected:
            raise AssertionError(f"target {key} mismatch: {target[key]!r} != {expected!r}")

    work = Path(tempfile.mkdtemp(prefix="ai-auto-lrc-cold-gate-", dir="/tmp"))
    wheelhouse = _materialize_verified_snapshot(
        source_wheelhouse,
        work / "wheelhouse-snapshot",
        manifest,
        verified_artifacts,
        manifest_bytes,
    )
    manifest_path = wheelhouse / "manifest.json"
    runtime_wheels = sorted((wheelhouse / "runtime").glob("*.whl"))
    build_wheels = sorted((wheelhouse / "build-system").glob("*.whl"))
    _verify_wheel_tags([*runtime_wheels, *build_wheels])

    environment = _cold_environment(work)
    outside = work / "outside-source-tree"
    distribution = work / "distribution"
    outside.mkdir()
    distribution.mkdir()

    artifact_records = manifest["files"]["artifacts"]
    if len(artifact_records) != 1:
        raise AssertionError("wheelhouse must contain exactly one release sdist")
    source_distribution = wheelhouse / artifact_records[0]["path"]
    _run(
        [
            sys.executable,
            "-I",
            "-m",
            "pip",
            "wheel",
            "--no-index",
            "--no-cache-dir",
            "--find-links",
            str(wheelhouse / "build-system"),
            "--no-deps",
            "--wheel-dir",
            str(distribution),
            str(source_distribution),
        ],
        cwd=outside,
        environment=environment,
    )
    project_wheels = list(distribution.glob("*.whl"))
    if len(project_wheels) != 1:
        raise AssertionError("sdist build did not produce exactly one wheel")
    _verify_wheel_tags(project_wheels)

    installation = work / "installation"
    venv.EnvBuilder(with_pip=True, clear=True).create(installation)
    pth_before = _snapshot_pth_files(installation)
    venv_python = installation / "bin" / "python"
    _run(
        [
            str(venv_python),
            "-I",
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-cache-dir",
            "--find-links",
            str(wheelhouse / "runtime"),
            str(project_wheels[0]),
        ],
        cwd=outside,
        environment=environment,
    )
    _verify_no_external_pth(installation, pth_before)
    pth_after = _snapshot_pth_files(installation)
    pip_check_result = _run(
        [str(venv_python), "-I", "-m", "pip", "check"],
        cwd=outside,
        environment=environment,
    )

    dependency_probe = """
import importlib
import json
import pathlib
import sys
import sysconfig

modules = json.loads(sys.argv[2])
for name in modules:
    importlib.import_module(name)
package = pathlib.Path(importlib.import_module("t2l").__file__).resolve()
source = pathlib.Path(sys.argv[1]).resolve()
prefix = pathlib.Path(sys.prefix).resolve()
site_packages = pathlib.Path(sysconfig.get_path("purelib")).resolve()
assert not package.is_relative_to(source), (package, source)
assert site_packages.is_relative_to(prefix), (site_packages, prefix)
assert package.is_relative_to(site_packages), (package, site_packages)
assert not list(prefix.rglob("locked-host-dependencies.pth"))
print(json.dumps({
    "direct_imports": modules,
    "installed_package": package.relative_to(site_packages).as_posix(),
    "site_packages": site_packages.relative_to(prefix).as_posix(),
}))
"""
    import_result = _run(
        [
            str(venv_python),
            "-I",
            "-c",
            dependency_probe,
            str(evidence_source),
            json.dumps(DIRECT_IMPORT_NAMES),
        ],
        cwd=outside,
        environment=environment,
    )
    import_evidence = json.loads(import_result.stdout.splitlines()[-1])
    direct_imports = _validate_direct_imports(import_evidence["direct_imports"])
    site_packages_relative = _safe_relative_name(
        import_evidence["site_packages"],
        label="site-packages path",
    )
    installed_package_name = import_evidence["installed_package"]
    installed_package_relative = _safe_relative_name(
        installed_package_name,
        label="installed package path",
    )
    installed_package_path = installation.joinpath(
        *site_packages_relative.parts,
        *installed_package_relative.parts,
    )

    assets = work / "external-assets"
    _copy_runtime_assets(evidence_source, assets)
    lyrics = outside / "lyrics.txt"
    lyrics.write_text("hello\n", encoding="utf-8")
    audio = outside / "input.mp3"
    shutil.copy2(
        evidence_source
        / "tests/fixtures/audio/sine-440hz-250ms-mono-22050.mp3",
        audio,
    )
    cli_result = _run(
        [
            str(installation / "bin" / "ai-auto-lrc"),
            str(lyrics),
            str(audio),
            "--asset-root",
            str(assets),
            "--device",
            "cpu",
        ],
        cwd=outside,
        environment=environment,
    )
    if cli_result.stdout != EXPECTED_CLI_STDOUT:
        raise AssertionError(f"unexpected CLI output: {cli_result.stdout!r}")

    return _build_observation(
        run_id=run_id,
        scope={
            "os": "linux",
            "arch": platform.machine(),
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform": sysconfig.get_platform(),
        },
        network_result=network_result,
        manifest=manifest,
        manifest_path=manifest_path,
        runtime_wheels=runtime_wheels,
        build_wheels=build_wheels,
        source_distribution=source_distribution,
        project_wheel=project_wheels[0],
        installation=installation,
        pth_before=pth_before,
        pth_after=pth_after,
        pip_check_result=pip_check_result,
        direct_imports=direct_imports,
        installed_package_path=installed_package_path,
        installed_package_name=installed_package_name,
        cli_result=cli_result,
        expected_cli_stdout=EXPECTED_CLI_STDOUT,
    )


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_linux_offline_wheelhouse.py WHEELHOUSE EVIDENCE_SOURCE")
    result = verify(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
