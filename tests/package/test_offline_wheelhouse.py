from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

from scripts import verify_linux_offline_wheelhouse as linux_verifier

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 job
    import tomli as tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPOSITORY_ROOT / "packaging" / "offline-wheelhouse-policy.toml"
WHEELHOUSE_ENV = "AI_AUTO_LRC_WHEELHOUSE"
PACKAGE_IMAGE_ENV = "AI_AUTO_LRC_PACKAGE_IMAGE"
EVIDENCE_RUN_ID_ENV = "AI_AUTO_LRC_EVIDENCE_RUN_ID"
UV = shutil.which("uv")
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
DOCKER = shutil.which("docker")
LINUX_VERIFY_SCRIPT = REPOSITORY_ROOT / "scripts" / "verify_linux_offline_wheelhouse.py"

pytestmark = pytest.mark.package


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_wheelhouse() -> tuple[Path, dict[str, object]]:
    configured = os.environ.get(WHEELHOUSE_ENV)
    if configured is None:
        pytest.skip(f"set {WHEELHOUSE_ENV} to run the cold wheelhouse gate")
    wheelhouse = Path(configured).resolve()
    manifest_path = wheelhouse / "manifest.json"
    assert wheelhouse.is_dir(), wheelhouse
    assert manifest_path.is_file(), manifest_path
    return wheelhouse, json.loads(manifest_path.read_text(encoding="utf-8"))


def _manifest_records(manifest: dict[str, object]):
    files = manifest["files"]
    assert isinstance(files, dict)
    for group, records in files.items():
        assert isinstance(group, str)
        assert isinstance(records, list)
        for record in records:
            assert isinstance(record, dict)
            yield group, record


def _verify_manifest(wheelhouse: Path, manifest: dict[str, object]) -> None:
    recorded_paths = set()
    for _group, record in _manifest_records(manifest):
        relative_path = record["path"]
        assert isinstance(relative_path, str)
        path = wheelhouse / relative_path
        assert path.is_file(), path
        assert path.stat().st_size == record["size"]
        assert _sha256(path) == record["sha256"]
        recorded_paths.add(relative_path)

    actual_paths = {
        path.relative_to(wheelhouse).as_posix()
        for path in wheelhouse.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    assert actual_paths == recorded_paths


def _small_manifest(wheelhouse: Path, relative_path: str) -> dict[str, object]:
    artifact = wheelhouse / relative_path
    return {
        "files": {
            "requirements": [],
            "runtime": [
                {
                    "path": relative_path,
                    "sha256": _sha256(artifact),
                    "size": artifact.stat().st_size,
                }
            ],
            "build_system": [],
            "artifacts": [],
        }
    }


def _manifest_bytes(manifest: dict[str, object]) -> bytes:
    return (json.dumps(manifest, sort_keys=True) + "\n").encode()


def _all_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _all_strings(key)
            yield from _all_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _all_strings(item)


def _cold_environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "DEMUCS_CACHE": str(tmp_path / "empty-demucs-cache"),
            "HF_HOME": str(tmp_path / "empty-hf-cache"),
            "HOME": str(tmp_path / "empty-home"),
            "PIP_CACHE_DIR": str(tmp_path / "empty-pip-cache"),
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
            "PYTHONNOUSERSITE": "1",
            "TORCH_HOME": str(tmp_path / "empty-torch-cache"),
            "UV_CACHE_DIR": str(tmp_path / "empty-uv-cache"),
            "UV_NO_CACHE": "1",
            "UV_OFFLINE": "1",
            "UV_PYTHON_DOWNLOADS": "never",
            "XDG_CACHE_HOME": str(tmp_path / "empty-xdg-cache"),
        }
    )
    for name in (
        "DEMUCS_CACHE",
        "HF_HOME",
        "HOME",
        "PIP_CACHE_DIR",
        "TORCH_HOME",
        "UV_CACHE_DIR",
        "XDG_CACHE_HOME",
    ):
        directory = Path(environment[name])
        directory.mkdir()
        assert list(directory.iterdir()) == []
    return environment


def _run_denied(
    profile: Path,
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(SANDBOX_EXEC), "-f", str(profile), *command],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"command failed: {command!r}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def test_pkg_018_wheelhouse_policy_and_manifest_are_complete():
    """PKG-018: every source build is approved and final directories contain wheels."""

    wheelhouse, manifest = _load_wheelhouse()
    policy = tomllib.loads(POLICY_PATH.read_text(encoding="utf-8"))
    approved = policy["approved_sdists"]
    assert approved
    assert manifest["approved_sdists"] == approved
    assert manifest["inputs"] == {
        "policy_sha256": _sha256(POLICY_PATH),
        "pyproject_sha256": _sha256(REPOSITORY_ROOT / "pyproject.toml"),
        "uv_lock_sha256": _sha256(REPOSITORY_ROOT / "uv.lock"),
    }

    approved_names = set()
    for entry in approved:
        assert set(entry) == {
            "expires",
            "name",
            "owner",
            "reason",
            "rebuild_command",
            "version",
        }
        assert all(str(entry[field]).strip() for field in ("owner", "reason", "rebuild_command"))
        assert date.fromisoformat(entry["expires"]) >= date.today()
        approved_names.add(canonicalize_name(entry["name"]))

    _verify_manifest(wheelhouse, manifest)
    runtime_records = manifest["files"]["runtime"]
    build_records = manifest["files"]["build_system"]
    assert runtime_records and build_records
    assert all(record["path"].endswith(".whl") for record in runtime_records + build_records)
    assert not list((wheelhouse / "runtime").glob("*.tar.*"))
    assert not list((wheelhouse / "runtime").glob("*.zip"))
    assert not list((wheelhouse / "build-system").glob("*.tar.*"))
    assert not list((wheelhouse / "build-system").glob("*.zip"))

    runtime_names = {
        canonicalize_name(str(parse_wheel_filename(Path(record["path"]).name)[0]))
        for record in runtime_records
    }
    assert approved_names <= runtime_names


@pytest.mark.parametrize(
    "spec_id",
    ("PKG-013", "PKG-014", "PKG-015"),
    ids=("PKG-013", "PKG-014", "PKG-015"),
)
def test_pkg_013_pkg_014_pkg_015_cold_offline_sdist_build(tmp_path, spec_id):
    """Run each cold network-denied sdist build contract as its own JUnit case."""

    assert spec_id in {"PKG-013", "PKG-014", "PKG-015"}

    if sys.platform != "darwin" or not SANDBOX_EXEC.is_file():
        pytest.skip("this evidence node requires the macOS system sandbox")
    if UV is None:
        pytest.fail("the cold wheelhouse gate requires the canonical uv tool")

    wheelhouse, manifest = _load_wheelhouse()
    _verify_manifest(wheelhouse, manifest)
    target = manifest["target"]
    if target["machine"] != "arm64" or not target["platform"].startswith("macosx-"):
        pytest.skip("this evidence node requires a macOS arm64 wheelhouse")
    assert target["implementation"] == "CPython"
    assert target["python_version"] == sys.version.split()[0]
    assert target["machine"] == "arm64"
    assert target["platform"].endswith("-arm64")

    artifact_records = manifest["files"]["artifacts"]
    assert len(artifact_records) == 1
    source_distribution = wheelhouse / artifact_records[0]["path"]
    assert source_distribution.name.endswith(".tar.gz")

    outside = tmp_path / "outside-source-tree"
    outside.mkdir()
    distribution = tmp_path / "distribution"
    profile = tmp_path / "network-deny.sb"
    profile.write_text(
        "(version 1)\n(allow default)\n(deny network*)\n",
        encoding="utf-8",
    )
    environment = _cold_environment(tmp_path)

    network_probe = (
        "import errno, socket; "
        "sock = socket.socket(); "
        "result = sock.connect_ex(('1.1.1.1', 443)); "
        "assert result in {errno.EPERM, errno.EACCES}, result"
    )
    _run_denied(
        profile,
        [sys.executable, "-I", "-c", network_probe],
        cwd=outside,
        environment=environment,
    )
    _run_denied(
        profile,
        [
            UV,
            "build",
            "--wheel",
            "--offline",
            "--no-index",
            "--find-links",
            str(wheelhouse / "build-system"),
            "--no-cache",
            "--no-python-downloads",
            "--out-dir",
            str(distribution),
            str(source_distribution),
        ],
        cwd=outside,
        environment=environment,
    )
    wheels = list(distribution.glob("*.whl"))
    assert len(wheels) == 1


def test_pkg_012_pkg_017_macos_cold_install_and_tags(tmp_path: Path):
    """PKG-012 and PKG-017: install compatible wheels with network denied."""

    if sys.platform != "darwin" or not SANDBOX_EXEC.is_file():
        pytest.skip("this evidence node requires the macOS system sandbox")
    if UV is None:
        pytest.fail("the cold wheelhouse gate requires the canonical uv tool")

    wheelhouse, manifest = _load_wheelhouse()
    _verify_manifest(wheelhouse, manifest)
    target = manifest["target"]
    if target["machine"] != "arm64" or not target["platform"].startswith(
        "macosx-"
    ):
        pytest.skip("this evidence node requires a macOS arm64 wheelhouse")
    assert target["implementation"] == "CPython"
    assert target["python_version"] == sys.version.split()[0]

    compatible_tags = set(sys_tags())
    runtime_records = manifest["files"]["runtime"]
    assert runtime_records
    for record in runtime_records:
        wheel = wheelhouse / record["path"]
        _name, _version, _build, tags = parse_wheel_filename(wheel.name)
        assert tags & compatible_tags, f"incompatible macOS wheel: {wheel.name}"

    artifact_records = manifest["files"]["artifacts"]
    assert len(artifact_records) == 1
    source_distribution = wheelhouse / artifact_records[0]["path"]
    outside = tmp_path / "outside-source-tree"
    outside.mkdir()
    distribution = tmp_path / "distribution"
    installation = tmp_path / "installation"
    profile = tmp_path / "network-deny.sb"
    profile.write_text(
        "(version 1)\n(allow default)\n(deny network*)\n",
        encoding="utf-8",
    )
    environment = _cold_environment(tmp_path)

    _run_denied(
        profile,
        [
            UV,
            "build",
            "--wheel",
            "--offline",
            "--no-index",
            "--find-links",
            str(wheelhouse / "build-system"),
            "--no-cache",
            "--no-python-downloads",
            "--out-dir",
            str(distribution),
            str(source_distribution),
        ],
        cwd=outside,
        environment=environment,
    )
    project_wheels = list(distribution.glob("*.whl"))
    assert len(project_wheels) == 1

    _run_denied(
        profile,
        [sys.executable, "-I", "-m", "venv", str(installation)],
        cwd=outside,
        environment=environment,
    )
    installed_python = installation / "bin/python"
    installed_cli = installation / "bin/ai-auto-lrc"
    _run_denied(
        profile,
        [
            str(installed_python),
            "-I",
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(wheelhouse / "runtime"),
            str(project_wheels[0]),
        ],
        cwd=outside,
        environment=environment,
    )
    _run_denied(
        profile,
        [str(installed_python), "-I", "-m", "pip", "check"],
        cwd=outside,
        environment=environment,
    )
    probe = _run_denied(
        profile,
        [
            str(installed_python),
            "-I",
            "-c",
            (
                "import pathlib,t2l; "
                "p=pathlib.Path(t2l.__file__).resolve(); "
                "assert 'site-packages' in p.parts, p; "
                "print(p.name)"
            ),
        ],
        cwd=outside,
        environment=environment,
    )
    assert probe.stdout == "__init__.py\n"
    help_result = _run_denied(
        profile,
        [str(installed_cli), "--help"],
        cwd=outside,
        environment=environment,
    )
    assert "usage:" in help_result.stdout


def test_pkg_019_linux_cold_install(tmp_path):
    """PKG-019: Linux cold install passes with empty caches and denied network."""

    # Wheel-tag assertions below are Linux-side evidence for the dual-platform
    # install/tag matrix, but cannot qualify that matrix while macOS is blocked.

    wheelhouse, manifest = _load_wheelhouse()
    target = manifest["target"]
    if target["machine"] != "x86_64" or target["platform"] != "linux-x86_64":
        pytest.skip("this evidence node requires a Linux x86_64 wheelhouse")
    if DOCKER is None:
        pytest.skip("this evidence node requires Docker")

    evidence_source = tmp_path / "evidence-source"
    evidence_source.mkdir()
    shutil.copy2(LINUX_VERIFY_SCRIPT, evidence_source / LINUX_VERIFY_SCRIPT.name)
    for relative_path in (
        "lid.176.ftz",
        "checkpoints/checkpoint_MTL",
        "assets/nltk_data/taggers/averaged_perceptron_tagger.zip",
        "assets/nltk_data/corpora/cmudict.zip",
        "tests/fixtures/audio/sine-440hz-250ms-mono-22050.mp3",
    ):
        destination = evidence_source / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative_path, destination)

    result = subprocess.run(
        [
            DOCKER,
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,exec,nosuid,size=4g",
            "-e",
            "HOME=/tmp/bootstrap-home",
            "-e",
            "PIP_CACHE_DIR=/tmp/bootstrap-pip-cache",
            "-e",
            "PIP_CONFIG_FILE=/dev/null",
            "-e",
            "PIP_NO_INDEX=1",
            "-e",
            "PYTHONNOUSERSITE=1",
            "-e",
            f"AI_AUTO_LRC_EVIDENCE_RUN_ID={os.environ.get(EVIDENCE_RUN_ID_ENV, 'package-test-run')}",
            "-v",
            f"{wheelhouse}:/wheelhouse:ro",
            "-v",
            f"{evidence_source}:/evidence-source:ro",
            "-w",
            "/tmp",
            os.environ.get(PACKAGE_IMAGE_ENV, "python:3.11.9-slim-bookworm"),
            "python",
            "-I",
            f"/evidence-source/{LINUX_VERIFY_SCRIPT.name}",
            "/wheelhouse",
            "/evidence-source",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.splitlines()[-1])
    assert set(evidence) == {
        "build",
        "cli",
        "installation",
        "network",
        "run_id",
        "schema",
        "schema_version",
        "scope",
        "wheelhouse",
    }
    assert evidence["schema"] == "ai-auto-lrc/linux-package-observation"
    assert evidence["schema_version"] == 1
    assert evidence["run_id"] == os.environ.get(
        EVIDENCE_RUN_ID_ENV,
        "package-test-run",
    )
    assert evidence["scope"] == {
        "arch": "x86_64",
        "os": "linux",
        "platform": "linux-x86_64",
        "python_implementation": "CPython",
        "python_version": "3.11.9",
    }
    assert evidence["network"]["blocked"] is True
    assert evidence["network"]["result_code"] != 0
    assert evidence["wheelhouse"]["runtime_wheel_count"] == len(
        manifest["files"]["runtime"]
    )
    assert evidence["wheelhouse"]["build_wheel_count"] == len(
        manifest["files"]["build_system"]
    )
    assert evidence["wheelhouse"]["artifact_count"] == 1
    assert evidence["installation"]["pip_check_exit_code"] == 0
    assert evidence["installation"]["pth_before"] == evidence["installation"][
        "pth_after"
    ]
    assert evidence["installation"]["direct_imports"] == list(
        linux_verifier.DIRECT_IMPORT_NAMES
    )
    assert evidence["installation"]["installed_package_origin_scope"] == (
        "site-packages"
    )
    assert evidence["cli"]["command_id"] == "installed-public-e2e-v1"
    assert evidence["cli"]["stdout_sha256"] == evidence["cli"][
        "expected_stdout_sha256"
    ]
    assert not any(value.startswith("/") for value in _all_strings(evidence))


@pytest.mark.parametrize(
    ("field", "bad_value", "message"),
    (
        ("size", 1, "size mismatch"),
        ("sha256", "0" * 64, "hash mismatch"),
    ),
    ids=("size", "sha256"),
)
def test_linux_verifier_rejects_manifest_integrity_mismatch(
    tmp_path: Path,
    field: str,
    bad_value: object,
    message: str,
):
    wheelhouse = tmp_path / "wheelhouse"
    artifact = wheelhouse / "runtime/example-1-py3-none-any.whl"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"small deterministic wheel payload")
    manifest = _small_manifest(wheelhouse, "runtime/example-1-py3-none-any.whl")
    manifest["files"]["runtime"][0][field] = bad_value

    with pytest.raises(AssertionError, match=message):
        linux_verifier._verify_manifest(wheelhouse, manifest)


def test_linux_verifier_rejects_unregistered_wheelhouse_file(tmp_path: Path):
    wheelhouse = tmp_path / "wheelhouse"
    artifact = wheelhouse / "runtime/example-1-py3-none-any.whl"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"registered")
    manifest = _small_manifest(wheelhouse, "runtime/example-1-py3-none-any.whl")
    (wheelhouse / "runtime/unregistered-1-py3-none-any.whl").write_bytes(
        b"unregistered"
    )

    with pytest.raises(AssertionError, match="does not cover exactly all files"):
        linux_verifier._verify_manifest(wheelhouse, manifest)


@pytest.mark.parametrize(
    "relative_path",
    (
        "../outside.whl",
        "/tmp/absolute.whl",
        "runtime/../outside.whl",
        "runtime//example.whl",
        "runtime\\example.whl",
    ),
    ids=("parent", "absolute", "dot-segment", "double-slash", "backslash"),
)
def test_linux_verifier_rejects_noncanonical_manifest_paths_before_access(
    tmp_path: Path,
    relative_path: str,
):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    manifest = {
        "files": {
            "requirements": [],
            "runtime": [
                {"path": relative_path, "sha256": "0" * 64, "size": 0}
            ],
            "build_system": [],
            "artifacts": [],
        }
    }

    with pytest.raises(AssertionError, match="unsafe manifest path"):
        linux_verifier._verify_manifest(wheelhouse, manifest)


@pytest.mark.parametrize("link_kind", ("file", "parent"))
def test_linux_verifier_rejects_symlinked_manifest_artifacts(
    tmp_path: Path,
    link_kind: str,
):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_artifact = outside / "example-1-py3-none-any.whl"
    outside_artifact.write_bytes(b"outside")
    if link_kind == "file":
        runtime = wheelhouse / "runtime"
        runtime.mkdir()
        artifact = runtime / outside_artifact.name
        artifact.symlink_to(outside_artifact)
    else:
        runtime = wheelhouse / "runtime"
        runtime.symlink_to(outside, target_is_directory=True)
        artifact = runtime / outside_artifact.name
    relative_path = artifact.relative_to(wheelhouse).as_posix()
    manifest = {
        "files": {
            "requirements": [],
            "runtime": [
                {
                    "path": relative_path,
                    "sha256": _sha256(outside_artifact),
                    "size": outside_artifact.stat().st_size,
                }
            ],
            "build_system": [],
            "artifacts": [],
        }
    }

    with pytest.raises(AssertionError, match="symlink"):
        linux_verifier._verify_manifest(wheelhouse, manifest)


def test_linux_verifier_rejects_duplicate_manifest_paths(tmp_path: Path):
    wheelhouse = tmp_path / "wheelhouse"
    artifact = wheelhouse / "runtime/example-1-py3-none-any.whl"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"small deterministic wheel payload")
    manifest = _small_manifest(wheelhouse, "runtime/example-1-py3-none-any.whl")
    manifest["files"]["runtime"].append(dict(manifest["files"]["runtime"][0]))

    with pytest.raises(AssertionError, match="duplicate manifest path"):
        linux_verifier._verify_manifest(wheelhouse, manifest)


def test_linux_verifier_rejects_incompatible_wheel_tag():
    incompatible = Path("example-1.0-cp27-cp27m-win32.whl")

    with pytest.raises(AssertionError, match="incompatible wheel tags"):
        linux_verifier._verify_wheel_tags([incompatible])


def test_linux_verifier_rejects_host_dependency_pth(tmp_path: Path):
    installation = tmp_path / "installation"
    site_packages = installation / "lib/python3.11/site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "locked-host-dependencies.pth").write_text(
        "/host/checkout/.venv/lib/python3.11/site-packages\n",
        encoding="utf-8",
    )
    baseline = linux_verifier._snapshot_pth_files(installation)

    with pytest.raises(AssertionError, match=r"external path from \.pth"):
        linux_verifier._verify_no_external_pth(installation, baseline)


def test_linux_verifier_rejects_new_executable_pth_after_install(tmp_path: Path):
    installation = tmp_path / "installation"
    site_packages = installation / "lib/python3.11/site-packages"
    site_packages.mkdir(parents=True)
    baseline_pth = site_packages / "distutils-precedence.pth"
    baseline_pth.write_text(
        "import _distutils_hack; _distutils_hack.add_shim()\n",
        encoding="utf-8",
    )
    baseline = linux_verifier._snapshot_pth_files(installation)
    (site_packages / "inject-host-dependencies.pth").write_text(
        "import sys; sys.path.insert(0, '/host/checkout/.venv/site-packages')\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match=r"\.pth inventory changed"):
        linux_verifier._verify_no_external_pth(installation, baseline)


def test_linux_verifier_allows_unchanged_fresh_venv_pth_baseline(tmp_path: Path):
    installation = tmp_path / "installation"
    site_packages = installation / "lib/python3.11/site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "distutils-precedence.pth").write_text(
        "import _distutils_hack; _distutils_hack.add_shim()\n",
        encoding="utf-8",
    )
    baseline = linux_verifier._snapshot_pth_files(installation)

    linux_verifier._verify_no_external_pth(installation, baseline)


def test_linux_verifier_rejects_source_path_replacement_after_validation(
    tmp_path: Path,
):
    wheelhouse = tmp_path / "wheelhouse"
    artifact = wheelhouse / "runtime/example-1-py3-none-any.whl"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"manifest-approved bytes")
    manifest = _small_manifest(wheelhouse, "runtime/example-1-py3-none-any.whl")
    verified = linux_verifier._verify_manifest(wheelhouse, manifest)
    replacement = tmp_path / "replacement.whl"
    replacement.write_bytes(b"manifest-approved bytes")
    os.replace(replacement, artifact)

    with pytest.raises(AssertionError, match="changed after manifest validation"):
        linux_verifier._materialize_verified_snapshot(
            wheelhouse,
            tmp_path / "snapshot",
            manifest,
            verified,
            _manifest_bytes(manifest),
        )


def test_linux_verifier_rejects_symlinked_manifest(tmp_path: Path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    outside_manifest = tmp_path / "outside-manifest.json"
    outside_manifest.write_text('{"files": {}}', encoding="utf-8")
    (wheelhouse / "manifest.json").symlink_to(outside_manifest)

    with pytest.raises(AssertionError, match="regular non-symlink file"):
        linux_verifier._read_stable_regular_bytes(
            wheelhouse / "manifest.json",
            label="wheelhouse manifest",
        )


def test_linux_verifier_rejects_in_place_source_change_during_snapshot_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    wheelhouse = tmp_path / "wheelhouse"
    artifact = wheelhouse / "runtime/example-1-py3-none-any.whl"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"A" * 64)
    manifest = _small_manifest(wheelhouse, "runtime/example-1-py3-none-any.whl")
    verified = linux_verifier._verify_manifest(wheelhouse, manifest)

    def mutate_during_copy(source, destination):
        first = source.read(16)
        destination.write(first)
        artifact.write_bytes(b"B" * 64)
        remainder = source.read()
        destination.write(remainder)
        copied = first + remainder
        return len(copied), hashlib.sha256(copied).hexdigest()

    monkeypatch.setattr(linux_verifier, "_copy_stream", mutate_during_copy)

    with pytest.raises(AssertionError, match="changed during snapshot copy"):
        linux_verifier._materialize_verified_snapshot(
            wheelhouse,
            tmp_path / "snapshot",
            manifest,
            verified,
            _manifest_bytes(manifest),
        )


def test_linux_verifier_post_copy_validation_rejects_snapshot_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    wheelhouse = tmp_path / "wheelhouse"
    artifact = wheelhouse / "runtime/example-1-py3-none-any.whl"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"manifest-approved bytes")
    manifest = _small_manifest(wheelhouse, "runtime/example-1-py3-none-any.whl")
    verified = linux_verifier._verify_manifest(wheelhouse, manifest)
    original_copy = linux_verifier._copy_verified_artifact

    def copy_then_mutate(source, destination, record):
        original_copy(source, destination, record)
        destination.write_bytes(b"post-copy mutation")

    monkeypatch.setattr(linux_verifier, "_copy_verified_artifact", copy_then_mutate)

    with pytest.raises(AssertionError, match="mismatch"):
        linux_verifier._materialize_verified_snapshot(
            wheelhouse,
            tmp_path / "snapshot",
            manifest,
            verified,
            _manifest_bytes(manifest),
        )


def test_linux_verifier_snapshot_is_independent_of_later_source_changes(
    tmp_path: Path,
):
    wheelhouse = tmp_path / "wheelhouse"
    payloads = {
        "requirements": {
            "runtime-requirements.txt": b"example==1 --hash=sha256:00\n"
        },
        "runtime": {
            "runtime/example-1-py3-none-any.whl": b"runtime wheel bytes"
        },
        "build_system": {
            "build-system/setuptools-1-py3-none-any.whl": b"build wheel bytes"
        },
        "artifacts": {
            "artifacts/ai_auto_lrc-1.tar.gz": b"release sdist bytes"
        },
    }
    manifest_files = {}
    for group, files in payloads.items():
        records = []
        for relative_path, content in files.items():
            artifact = wheelhouse / relative_path
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(content)
            records.append(
                {
                    "path": relative_path,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                }
            )
        manifest_files[group] = records
    manifest = {"files": manifest_files}
    verified = linux_verifier._verify_manifest(wheelhouse, manifest)
    snapshot = tmp_path / "snapshot"

    linux_verifier._materialize_verified_snapshot(
        wheelhouse,
        snapshot,
        manifest,
        verified,
        _manifest_bytes(manifest),
    )
    for files in payloads.values():
        for relative_path in files:
            (wheelhouse / relative_path).write_bytes(b"changed original bytes")
    (wheelhouse / "runtime/unregistered.whl").write_bytes(b"late addition")

    linux_verifier._verify_manifest(snapshot, manifest)
    for files in payloads.values():
        for relative_path, content in files.items():
            assert (snapshot / relative_path).read_bytes() == content


def test_linux_container_observation_is_complete_stable_and_path_free(tmp_path: Path):
    wheelhouse = tmp_path / "wheelhouse-snapshot"
    runtime_wheel = wheelhouse / "runtime/example-1-py3-none-any.whl"
    build_wheel = wheelhouse / "build-system/setuptools-1-py3-none-any.whl"
    source_distribution = wheelhouse / "artifacts/ai_auto_lrc-1.tar.gz"
    for path, content in (
        (runtime_wheel, b"runtime"),
        (build_wheel, b"build"),
        (source_distribution, b"sdist"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = {
        "files": {
            "requirements": [],
            "runtime": [
                {
                    "path": "runtime/example-1-py3-none-any.whl",
                    "size": runtime_wheel.stat().st_size,
                    "sha256": _sha256(runtime_wheel),
                }
            ],
            "build_system": [
                {
                    "path": "build-system/setuptools-1-py3-none-any.whl",
                    "size": build_wheel.stat().st_size,
                    "sha256": _sha256(build_wheel),
                }
            ],
            "artifacts": [
                {
                    "path": "artifacts/ai_auto_lrc-1.tar.gz",
                    "size": source_distribution.stat().st_size,
                    "sha256": _sha256(source_distribution),
                }
            ],
        }
    }
    manifest_path = wheelhouse / "manifest.json"
    manifest_path.write_bytes(_manifest_bytes(manifest))
    project_wheel = tmp_path / "distribution/ai_auto_lrc-1-py3-none-any.whl"
    project_wheel.parent.mkdir()
    project_wheel.write_bytes(b"project wheel")
    installation = tmp_path / "installation"
    pth = installation / "lib/python3.11/site-packages/distutils-precedence.pth"
    pth.parent.mkdir(parents=True)
    pth.write_text("import _distutils_hack\n", encoding="utf-8")
    installed_package = pth.parent / "t2l/__init__.py"
    installed_package.parent.mkdir()
    installed_package.write_bytes(b'__version__ = "1"\n')
    pth_snapshot = {pth.relative_to(installation).as_posix(): _sha256(pth)}

    observation = linux_verifier._build_observation(
        run_id="20260905T120000000000Z-33333333333333333333333333333333",
        scope={
            "arch": "x86_64",
            "os": "linux",
            "platform": "linux-x86_64",
            "python_implementation": "CPython",
            "python_version": "3.11.9",
        },
        network_result=101,
        manifest=manifest,
        manifest_path=manifest_path,
        runtime_wheels=[runtime_wheel],
        build_wheels=[build_wheel],
        source_distribution=source_distribution,
        project_wheel=project_wheel,
        installation=installation,
        pth_before=pth_snapshot,
        pth_after=pth_snapshot,
        pip_check_result=subprocess.CompletedProcess(
            args=["python", "-m", "pip", "check"],
            returncode=0,
            stdout="No broken requirements found.\n",
            stderr="",
        ),
        direct_imports=linux_verifier.DIRECT_IMPORT_NAMES,
        installed_package_path=installed_package,
        installed_package_name="t2l/__init__.py",
        cli_result=subprocess.CompletedProcess(
            args=["ai-auto-lrc"],
            returncode=0,
            stdout="[00:00.034]hello\n",
            stderr="",
        ),
        expected_cli_stdout="[00:00.034]hello\n",
    )

    assert set(observation) == {
        "build",
        "cli",
        "installation",
        "network",
        "run_id",
        "schema",
        "schema_version",
        "scope",
        "wheelhouse",
    }
    assert observation["schema"] == "ai-auto-lrc/linux-package-observation"
    assert observation["schema_version"] == 1
    assert observation["wheelhouse"] == {
        "aggregate_sha256": linux_verifier._wheelhouse_aggregate_sha256(manifest),
        "artifact_count": 1,
        "build_wheel_count": 1,
        "manifest_sha256": _sha256(manifest_path),
        "runtime_wheel_count": 1,
    }
    assert observation["build"]["source"] == "sdist"
    assert observation["build"]["sdist"]["name"] == source_distribution.name
    assert observation["build"]["project_wheel"]["name"] == project_wheel.name
    assert observation["installation"]["pth_before"] == [
        {
            "name": "lib/python3.11/site-packages/distutils-precedence.pth",
            "sha256": _sha256(pth),
            "size": pth.stat().st_size,
        }
    ]
    assert observation["installation"]["installed_package"] == {
        "name": "t2l/__init__.py",
        "sha256": _sha256(installed_package),
        "size": installed_package.stat().st_size,
    }
    assert observation["installation"]["direct_imports"] == list(
        linux_verifier.DIRECT_IMPORT_NAMES
    )
    assert observation["installation"]["installed_package_origin_scope"] == (
        "site-packages"
    )
    assert observation["cli"]["stdout_sha256"] == observation["cli"][
        "expected_stdout_sha256"
    ]
    assert not any(value.startswith("/") for value in _all_strings(observation))


def test_linux_container_observation_rejects_incomplete_direct_import_set(tmp_path):
    package = tmp_path / "t2l/__init__.py"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"package")

    with pytest.raises(AssertionError, match="direct import set"):
        linux_verifier._validate_direct_imports(
            linux_verifier.DIRECT_IMPORT_NAMES[:-1]
        )
