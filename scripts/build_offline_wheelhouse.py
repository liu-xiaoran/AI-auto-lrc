#!/usr/bin/env python3
"""Build a hashed, platform-specific core wheelhouse from the frozen lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sysconfig
import tempfile
import venv
from datetime import UTC, datetime
from pathlib import Path

from packaging.tags import sys_tags

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 script support
    import tomli as tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPOSITORY_ROOT / "packaging/offline-wheelhouse-policy.toml"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _find_sdist(downloads: Path, name: str, version: str) -> Path:
    expected = _canonical_name(f"{name}-{version}")
    matches = []
    for candidate in downloads.iterdir():
        if candidate.suffix == ".whl":
            continue
        filename = candidate.name
        for suffix in (".tar.gz", ".tar.bz2", ".tar.xz", ".zip"):
            if filename.endswith(suffix):
                filename = filename[: -len(suffix)]
                break
        if _canonical_name(filename) == expected:
            matches.append(candidate)
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one sdist for {name}=={version}, found {matches!r}"
        )
    return matches[0]


def _file_record(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _load_policy() -> dict[str, object]:
    return tomllib.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _prepare_release_source(staging: Path) -> Path:
    """Copy only publishable inputs so building never mutates the checkout."""

    release_source = staging / "release-source"
    release_source.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(REPOSITORY_ROOT / name, release_source / name)
    shutil.copytree(
        REPOSITORY_ROOT / "t2l",
        release_source / "t2l",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return release_source


def build(output: Path) -> None:
    output = output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to replace existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent)
    )
    try:
        policy = _load_policy()
        approved = policy["approved_sdists"]
        approved_names = ",".join(entry["name"] for entry in approved)
        requirements = staging / "runtime-requirements.txt"
        downloads = staging / "downloads"
        built = staging / "built"
        runtime = staging / "runtime"
        build_system = staging / "build-system"
        artifacts = staging / "artifacts"
        for directory in (downloads, built, runtime, build_system, artifacts):
            directory.mkdir()
        release_source = _prepare_release_source(staging)

        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError("uv is required")
        _run(
            [
                uv,
                "export",
                "--frozen",
                "--no-dev",
                "--no-emit-project",
                "--emit-index-url",
                "--format",
                "requirements.txt",
                "--output-file",
                str(requirements),
            ],
            cwd=REPOSITORY_ROOT,
        )
        _run(
            [
                uv,
                "build",
                "--sdist",
                "--no-python-downloads",
                "--no-create-gitignore",
                "--out-dir",
                str(artifacts),
                str(release_source),
            ],
            cwd=staging,
        )

        builder = staging / "builder"
        venv.EnvBuilder(with_pip=True, clear=True).create(builder)
        builder_python = builder / "bin" / "python"
        pip = [str(builder_python), "-m", "pip"]
        _run(
            [
                *pip,
                "download",
                "--dest",
                str(downloads),
                "--require-hashes",
                "--only-binary=:all:",
                f"--no-binary={approved_names}",
                "-r",
                str(requirements),
            ],
            cwd=staging,
        )
        _run(
            [
                *pip,
                "download",
                "--dest",
                str(build_system),
                "--only-binary=:all:",
                "--no-deps",
                *policy["build_system"]["requirements"],
            ],
            cwd=staging,
        )

        located_sdists = []
        for entry in approved:
            sdist = _find_sdist(downloads, entry["name"], entry["version"])
            located_sdists.append(sdist)
            _run(
                [
                    *pip,
                    "wheel",
                    "--no-index",
                    "--find-links",
                    str(build_system),
                    "--no-deps",
                    "--wheel-dir",
                    str(built),
                    str(sdist),
                ],
                cwd=staging,
            )

        unexpected_sdists = {
            path.name
            for path in downloads.iterdir()
            if path.suffix != ".whl" and path not in located_sdists
        }
        if unexpected_sdists:
            raise RuntimeError(
                f"downloaded unapproved source distributions: {unexpected_sdists}"
            )
        for wheel in (*downloads.glob("*.whl"), *built.glob("*.whl")):
            shutil.copy2(wheel, runtime / wheel.name)

        shutil.rmtree(downloads)
        shutil.rmtree(built)
        shutil.rmtree(builder)
        shutil.rmtree(release_source)
        first_tag = next(sys_tags())
        manifest = {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "target": {
                "implementation": platform.python_implementation(),
                "python_version": platform.python_version(),
                "machine": platform.machine(),
                "platform": sysconfig.get_platform(),
                "primary_wheel_tag": str(first_tag),
            },
            "inputs": {
                "pyproject_sha256": _sha256(REPOSITORY_ROOT / "pyproject.toml"),
                "uv_lock_sha256": _sha256(REPOSITORY_ROOT / "uv.lock"),
                "policy_sha256": _sha256(POLICY_PATH),
            },
            "approved_sdists": approved,
            "files": {
                "requirements": [_file_record(requirements, staging)],
                "runtime": [
                    _file_record(path, staging)
                    for path in sorted(runtime.glob("*.whl"))
                ],
                "build_system": [
                    _file_record(path, staging)
                    for path in sorted(build_system.glob("*.whl"))
                ],
                "artifacts": [
                    _file_record(path, staging)
                    for path in sorted(artifacts.iterdir())
                ],
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, output)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
