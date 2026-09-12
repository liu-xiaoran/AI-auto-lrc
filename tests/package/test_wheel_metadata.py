from __future__ import annotations

import email.parser
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 job
    import tomli as tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.package
UV = shutil.which("uv")
FORBIDDEN_WHEEL_PATHS = {
    "ext/lrc2json.py",  # X02
    "ext/traditional_to_simplified.py",  # X03
    "t2l/slid.py",  # X01
    "t2l/mtl/data.py",  # training-only data pipeline
    "t2l/mtl/eval.py",
    "t2l/mtl/eval_bdr.py",
    "t2l/mtl/train.py",
    "t2l/init_model.py",  # old five-element tuple loader
    "t2l/mtl/wrapper.py",  # old tuple/string alignment API
}
FORBIDDEN_INSTALLED_MODULES = {
    "t2l.init_model",
    "t2l.mtl.data",
    "t2l.mtl.eval",
    "t2l.mtl.eval_bdr",
    "t2l.mtl.train",
    "t2l.mtl.wrapper",
    "t2l.slid",
}
FORBIDDEN_PUBLIC_NAMES = {
    "data",
    "eval",
    "eval_bdr",
    "init_model",
    "lrc2json",
    "slid",
    "traditional_to_simplified",
    "train",
    "wrapper",
}


def _run_uv(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    assert UV is not None, "the package verification suite requires the canonical uv tool"
    return subprocess.run(
        [UV, *args],
        check=True,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _build_distributions(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(REPOSITORY_ROOT / name, source / name)
    shutil.copytree(
        REPOSITORY_ROOT / "t2l",
        source / "t2l",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (source / "checkpoints").mkdir()
    (source / "checkpoints" / "must-not-ship").write_bytes(b"sentinel")
    (source / "demofile").mkdir()
    (source / "demofile" / "must-not-ship.mp3").write_bytes(b"sentinel")
    distribution = tmp_path / "dist"
    _run_uv(
        "build",
        "--no-python-downloads",
        "--out-dir",
        str(distribution),
        str(source),
        cwd=tmp_path,
    )
    wheels = list(distribution.glob("*.whl"))
    sdists = list(distribution.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1
    return wheels[0], sdists[0]


def _site_packages(python: Path | str, *, cwd: Path) -> Path:
    result = subprocess.run(
        [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        check=True,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _install_wheel_with_locked_host_dependencies(
    tmp_path: Path,
    wheel: Path,
    *,
    name: str,
) -> tuple[Path, Path]:
    installation = tmp_path / name
    _run_uv(
        "venv",
        "--python",
        sys.executable,
        "--no-python-downloads",
        str(installation),
        cwd=tmp_path,
    )
    venv_python = installation / "bin" / "python"
    _run_uv(
        "pip",
        "install",
        "--python",
        str(venv_python),
        "--no-python-downloads",
        "--no-deps",
        str(wheel),
        cwd=tmp_path,
    )

    # Reuse the lock-synchronized host environment for this behavioral gate.
    # A cold no-index install remains the separate PKG-012/OFF-003 gate.
    source_site = _site_packages(sys.executable, cwd=tmp_path)
    target_site = _site_packages(venv_python, cwd=tmp_path)
    (target_site / "locked-host-dependencies.pth").write_text(
        str(source_site) + "\n", encoding="utf-8"
    )
    return installation, target_site


def _copy_runtime_assets(tmp_path: Path) -> Path:
    asset_root = tmp_path / "external-assets"
    for relative_path in (
        "lid.176.ftz",
        "checkpoints/checkpoint_MTL",
        "assets/nltk_data/taggers/averaged_perceptron_tagger.zip",
        "assets/nltk_data/corpora/cmudict.zip",
    ):
        destination = asset_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative_path, destination)
    return asset_root


def _offline_guard_events(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def test_wheel_metadata_and_asset_exclusions(tmp_path):
    """PKG-002/PKG-010/PKG-011: metadata and publishable contents are exact."""

    wheel, sdist = _build_distributions(tmp_path)

    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        wheel_name = next(name for name in names if name.endswith(".dist-info/WHEEL"))
        metadata = email.parser.BytesParser().parsebytes(archive.read(metadata_name))
        wheel_metadata = email.parser.BytesParser().parsebytes(archive.read(wheel_name))

    assert SpecifierSet(metadata["Requires-Python"]) == SpecifierSet(">=3.10,<3.12")
    assert metadata.get_all("Provides-Extra") == ["vocals"]
    assert any(value.startswith("demucs==4.0.1;") for value in metadata.get_all("Requires-Dist"))
    assert "g2p-en==2.1.0" in metadata.get_all("Requires-Dist")
    assert "nltk==3.8.1" in metadata.get_all("Requires-Dist")
    assert wheel_metadata["Root-Is-Purelib"] == "true"
    assert wheel.name.endswith("-py3-none-any.whl")
    assert not any(name.startswith(("checkpoints/", "demofile/")) for name in names)
    assert FORBIDDEN_WHEEL_PATHS.isdisjoint(names)
    assert "t2l/_assets/legacy_v1_manifest.json" in names

    with tarfile.open(sdist, "r:gz") as archive:
        source_names = {
            "/".join(Path(name).parts[1:]) for name in archive.getnames()
        }

    assert FORBIDDEN_WHEEL_PATHS.isdisjoint(source_names)
    assert not any(
        name.startswith(("checkpoints/", "demofile/")) for name in source_names
    )

    installation = tmp_path / "namespace-install"
    _run_uv(
        "pip",
        "install",
        "--target",
        str(installation),
        "--no-python-downloads",
        "--no-deps",
        str(wheel),
        cwd=tmp_path,
    )
    outside = tmp_path / "outside-namespace"
    outside.mkdir()
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    probe = """
import importlib.util
import pathlib
import pkgutil
import sys

sys.path.insert(0, sys.argv[1])
import t2l

forbidden_modules = set(sys.argv[2].split(','))
forbidden_public_names = set(sys.argv[3].split(','))
installed_root = pathlib.Path(sys.argv[1]).resolve()
assert pathlib.Path(t2l.__file__).resolve().is_relative_to(installed_root)
assert importlib.util.find_spec('ext') is None
for module_name in forbidden_modules:
    assert importlib.util.find_spec(module_name) is None, module_name
discovered = {
    module.name for module in pkgutil.walk_packages(t2l.__path__, prefix='t2l.')
}
assert forbidden_modules.isdisjoint(discovered), discovered & forbidden_modules
assert forbidden_public_names.isdisjoint(t2l.__all__)
assert forbidden_public_names.isdisjoint(vars(t2l))
"""
    namespace_result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            probe,
            str(installation),
            ",".join(sorted(FORBIDDEN_INSTALLED_MODULES)),
            ",".join(sorted(FORBIDDEN_PUBLIC_NAMES)),
        ],
        check=False,
        cwd=outside,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert namespace_result.returncode == 0, namespace_result.stderr


def test_pkg_021_tree_and_sdist_wheels_have_equivalent_publishable_contents(tmp_path):
    """PKG-021: tree and sdist builds have equal metadata and package payloads."""

    tree_wheel, source_distribution = _build_distributions(tmp_path)
    sdist_output = tmp_path / "sdist-wheel"
    _run_uv(
        "build",
        "--wheel",
        "--no-python-downloads",
        "--out-dir",
        str(sdist_output),
        str(source_distribution),
        cwd=tmp_path,
    )
    sdist_wheels = list(sdist_output.glob("*.whl"))
    assert len(sdist_wheels) == 1

    def publishable(archive: zipfile.ZipFile) -> dict[str, bytes]:
        result = {}
        for name in archive.namelist():
            if name.endswith((".dist-info/RECORD", ".dist-info/WHEEL")):
                continue
            result[name] = archive.read(name)
        return result

    with (
        zipfile.ZipFile(tree_wheel) as tree_archive,
        zipfile.ZipFile(sdist_wheels[0]) as sdist_archive,
    ):
        tree_contents = publishable(tree_archive)
        sdist_contents = publishable(sdist_archive)

    assert tree_contents.keys() == sdist_contents.keys()
    assert tree_contents == sdist_contents
    manifest_name = "t2l/_assets/legacy_v1_manifest.json"
    assert tree_contents[manifest_name] == sdist_contents[manifest_name]
    entry_point_name = next(
        name for name in tree_contents if name.endswith(".dist-info/entry_points.txt")
    )
    assert tree_contents[entry_point_name] == (
        b"[console_scripts]\nai-auto-lrc = t2l.adapters.cli:main\n"
    )


def test_pkg_022_repeated_builds_have_identical_normalized_contents(tmp_path):
    """PKG-022: repeated builds keep wheel and sdist content manifests stable."""

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first_wheel, first_sdist = _build_distributions(first_root)
    second_wheel, second_sdist = _build_distributions(second_root)

    def wheel_payload(path: Path) -> dict[str, bytes]:
        with zipfile.ZipFile(path) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def sdist_payload(path: Path) -> dict[str, bytes]:
        with tarfile.open(path, "r:gz") as archive:
            result = {}
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                stream = archive.extractfile(member)
                assert stream is not None
                relative = "/".join(Path(member.name).parts[1:])
                result[relative] = stream.read()
            return result

    assert wheel_payload(first_wheel) == wheel_payload(second_wheel)
    assert sdist_payload(first_sdist) == sdist_payload(second_sdist)


def test_wheel_installs_and_cli_help_runs_outside_the_source_tree(tmp_path):
    """PKG-003/PKG-004/CLI-028: installed CLI help and version work outside checkout."""

    wheel, _sdist = _build_distributions(tmp_path)
    installation = tmp_path / "installation-venv"
    _run_uv(
        "venv",
        "--python",
        sys.executable,
        "--no-python-downloads",
        str(installation),
        cwd=tmp_path,
    )
    venv_python = installation / "bin" / "python"
    _run_uv(
        "pip",
        "install",
        "--python",
        str(venv_python),
        "--no-python-downloads",
        "--no-deps",
        str(wheel),
        cwd=tmp_path,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"

    imported = subprocess.run(
        [
            str(venv_python),
            "-I",
            "-c",
            (
                "import pathlib, sys, t2l; "
                "from t2l.model_profiles import load_legacy_v1_profile; "
                "assert pathlib.Path(t2l.__file__).resolve().is_relative_to("
                "pathlib.Path(sys.argv[1]).resolve()); "
                "assert load_legacy_v1_profile().profile_id == 'legacy-v1'"
            ),
            str(installation),
        ],
        check=False,
        cwd=outside,
        env=environment,
        capture_output=True,
        text=True,
    )
    help_command = subprocess.run(
        [str(installation / "bin" / "ai-auto-lrc"), "--help"],
        check=False,
        cwd=outside,
        env=environment,
        capture_output=True,
        text=True,
    )
    metadata_version = subprocess.run(
        [
            str(venv_python),
            "-I",
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('ai-auto-lrc'))",
        ],
        check=False,
        cwd=outside,
        env=environment,
        capture_output=True,
        text=True,
    )
    version_command = subprocess.run(
        [str(installation / "bin" / "ai-auto-lrc"), "--version"],
        check=False,
        cwd=outside,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert imported.returncode == 0, imported.stderr
    assert help_command.returncode == 0, help_command.stderr
    assert help_command.stdout.startswith("usage: ai-auto-lrc")
    assert metadata_version.returncode == 0, metadata_version.stderr
    assert version_command.returncode == 0, version_command.stderr
    assert version_command.stdout == f"ai-auto-lrc {metadata_version.stdout.strip()}\n"
    assert version_command.stderr == ""


def test_pkg_023_isolated_import_uses_installed_wheel_from_read_only_cwd(tmp_path):
    """PKG-023: python -I imports only the installed wheel from a read-only CWD."""

    wheel, _sdist = _build_distributions(tmp_path)
    installation = tmp_path / "isolated-installation"
    _run_uv(
        "venv",
        "--python",
        sys.executable,
        "--no-python-downloads",
        str(installation),
        cwd=tmp_path,
    )
    venv_python = installation / "bin" / "python"
    _run_uv(
        "pip",
        "install",
        "--python",
        str(venv_python),
        "--no-python-downloads",
        "--no-deps",
        str(wheel),
        cwd=tmp_path,
    )

    outside = tmp_path / "read-only-cwd"
    outside.mkdir()
    outside.chmod(0o555)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    probe = (
        "import pathlib, sys, t2l; "
        "origin=pathlib.Path(t2l.__file__).resolve(); "
        "root=pathlib.Path(sys.argv[1]).resolve(); "
        "cwd=pathlib.Path.cwd().resolve(); "
        "assert origin.is_relative_to(root), (origin, root); "
        "assert not origin.is_relative_to(cwd), (origin, cwd); "
        "assert not (cwd / 'write-probe').exists()"
    )
    try:
        result = subprocess.run(
            [str(venv_python), "-I", "-c", probe, str(installation)],
            check=False,
            cwd=outside,
            env=environment,
            capture_output=True,
            text=True,
        )
    finally:
        outside.chmod(0o755)

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


def test_pkg_024_hostile_cwd_cannot_override_installed_wheel_or_assets(tmp_path):
    """PKG-024: hostile CWD names cannot change the installed real result."""

    wheel, _sdist = _build_distributions(tmp_path)
    installation, _target_site = _install_wheel_with_locked_host_dependencies(
        tmp_path,
        wheel,
        name="hostile-cwd-venv",
    )
    asset_root = tmp_path / "explicit-assets"
    for relative_path in (
        "lid.176.ftz",
        "checkpoints/checkpoint_Baseline",
        "checkpoints/checkpoint_MTL",
        "checkpoints/checkpoint_BDR",
        "assets/nltk_data/taggers/averaged_perceptron_tagger.zip",
        "assets/nltk_data/corpora/cmudict.zip",
    ):
        destination = asset_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative_path, destination)

    audio = tmp_path / "real-short-input.mp3"
    shutil.copy2(
        REPOSITORY_ROOT / "tests/fixtures/audio/sine-440hz-250ms-mono-22050.mp3",
        audio,
    )
    clean_cwd = tmp_path / "clean-cwd"
    hostile_cwd = tmp_path / "hostile-cwd"
    clean_cwd.mkdir()
    hostile_cwd.mkdir()

    hostile_package = hostile_cwd / "t2l"
    hostile_package.mkdir()
    (hostile_package / "__init__.py").write_text(
        "raise AssertionError('hostile CWD t2l package imported')\n",
        encoding="utf-8",
    )
    hostile_manifest = hostile_package / "_assets/legacy_v1_manifest.json"
    hostile_manifest.parent.mkdir()
    hostile_manifest.write_text('{"schema_version": 999}\n', encoding="utf-8")
    for relative_path in (
        "lid.176.ftz",
        "checkpoints/checkpoint_Baseline",
        "checkpoints/checkpoint_MTL",
        "checkpoints/checkpoint_BDR",
        "legacy_v1_manifest.json",
    ):
        destination = hostile_cwd / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"hostile-cwd-sentinel")

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "HOME": str(tmp_path / "empty-home"),
            "NLTK_DATA": str(tmp_path / "empty-nltk"),
            "PYTHONNOUSERSITE": "1",
            "XDG_CACHE_HOME": str(tmp_path / "empty-cache"),
        }
    )
    for name in ("HOME", "NLTK_DATA", "XDG_CACHE_HOME"):
        Path(environment[name]).mkdir()

    probe = r"""
import json
import pathlib
import socket
import sys

import nltk
import t2l
from t2l.contracts import AlignmentRequest, RuntimeConfig

def blocked(*_args, **_kwargs):
    raise AssertionError('PKG-024 attempted network or nltk.download')

nltk.download = blocked
socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.socket.connect = blocked
socket.socket.connect_ex = blocked

installation = pathlib.Path(sys.argv[1]).resolve()
origin = pathlib.Path(t2l.__file__).resolve()
assert origin.is_relative_to(installation), (origin, installation)
assert not origin.is_relative_to(pathlib.Path.cwd().resolve()), origin

runtime = t2l.create_runtime(
    RuntimeConfig(asset_root=pathlib.Path(sys.argv[2]), device='cpu', seed=0)
)
result = runtime.process(
    AlignmentRequest(lyrics=('hello',), audio_path=pathlib.Path(sys.argv[3]))
)
payload = {
    'diagnostics': [item.code for item in result.diagnostics],
    'expected_token_count': result.expected_token_count,
    'lrc': result.lrc,
    'model_profile': result.model_profile,
    'origin': str(origin),
    'spans': [
        {
            'end': item.frame_span.end,
            'line_index': item.line_index,
            'start': item.frame_span.start,
            'text': item.text,
            'token_index': item.token_index,
        }
        for item in result.spans
    ],
    'status': result.status,
    'timebase': {
        'frame_offset': result.timebase.frame_offset,
        'hop_length': result.timebase.hop_length,
        'sample_rate': result.timebase.sample_rate,
        'time_pooling': result.timebase.time_pooling,
    },
}
print(json.dumps(payload, sort_keys=True, separators=(',', ':')))
"""

    def run_from(cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                str(installation / "bin" / "python"),
                "-I",
                "-c",
                probe,
                str(installation),
                str(asset_root),
                str(audio),
            ],
            check=False,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
        )

    clean = run_from(clean_cwd)
    hostile = run_from(hostile_cwd)

    assert clean.returncode == 0, clean.stderr
    assert hostile.returncode == 0, hostile.stderr
    assert clean.stderr == hostile.stderr
    assert "hostile-cwd" not in hostile.stderr
    assert "Traceback" not in hostile.stderr
    assert clean.stdout == hostile.stdout
    payload = json.loads(clean.stdout)
    assert payload["lrc"] == "[00:00.034]hello"
    assert payload["status"] == "complete"
    assert payload["spans"] == [
        {
            "end": 7,
            "line_index": 0,
            "start": 1,
            "text": "hello",
            "token_index": 0,
        }
    ]
    assert Path(payload["origin"]).is_relative_to(installation)


def test_installed_wheel_rejects_manifest_from_an_incompatible_package_version(
    tmp_path,
):
    """Installed metadata is an active manifest compatibility boundary."""

    wheel, _sdist = _build_distributions(tmp_path)
    installation = tmp_path / "compatibility-venv"
    _run_uv(
        "venv",
        "--python",
        sys.executable,
        "--no-python-downloads",
        str(installation),
        cwd=tmp_path,
    )
    venv_python = installation / "bin" / "python"
    _run_uv(
        "pip",
        "install",
        "--python",
        str(venv_python),
        "--no-python-downloads",
        "--no-deps",
        str(wheel),
        cwd=tmp_path,
    )
    site_packages = _site_packages(venv_python, cwd=tmp_path)
    manifest = site_packages / "t2l" / "_assets" / "legacy_v1_manifest.json"
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["compatibility"]["package_version"] = "2.0.0a1"
    manifest.write_text(json.dumps(document), encoding="utf-8")

    outside = tmp_path / "outside-compatibility"
    outside.mkdir()
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(
        [
            str(venv_python),
            "-I",
            "-c",
            (
                "import sys; "
                "from t2l.model_profiles import ManifestValidationError, "
                "load_legacy_v1_profile; "
                "\ntry:\n load_legacy_v1_profile()"
                "\nexcept ManifestValidationError as exc:\n"
                " assert 'package_version' in str(exc), exc"
                "\nelse:\n raise AssertionError('incompatible manifest was accepted')"
                "\nassert 'torch' not in sys.modules"
                "\nassert 'fasttext' not in sys.modules"
                "\nassert 'g2p_en' not in sys.modules"
            ),
        ],
        check=False,
        cwd=outside,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_pkg_025_installed_wheel_prepares_real_lyrics_from_external_asset_root(
    tmp_path,
):
    """PKG-025: installed wheel uses an external root for offline real G2P."""

    wheel, _sdist = _build_distributions(tmp_path)
    installation = tmp_path / "g2p-wheel-target"
    _run_uv(
        "pip",
        "install",
        "--target",
        str(installation),
        "--no-python-downloads",
        "--no-deps",
        str(wheel),
        cwd=tmp_path,
    )
    asset_root = tmp_path / "external-assets"
    for relative_path in (
        "lid.176.ftz",
        "assets/nltk_data/taggers/averaged_perceptron_tagger.zip",
        "assets/nltk_data/corpora/cmudict.zip",
    ):
        destination = asset_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative_path, destination)
    outside = tmp_path / "outside-g2p"
    empty_home = tmp_path / "wheel-home"
    empty_nltk = tmp_path / "wheel-empty-nltk"
    outside.mkdir()
    empty_home.mkdir()
    empty_nltk.mkdir()
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "HOME": str(empty_home),
            "NLTK_DATA": str(empty_nltk),
            "PYTHONNOUSERSITE": "1",
            "XDG_CACHE_HOME": str(tmp_path / "wheel-cache"),
        }
    )
    probe = """
import pathlib
import socket
import sys

sys.path.insert(0, sys.argv[1])

import nltk
import t2l

def blocked(*_args, **_kwargs):
    raise AssertionError('installed wheel attempted network or nltk.download')

nltk.download = blocked
socket.create_connection = blocked
socket.socket.connect = blocked

from t2l.contracts import RuntimeConfig

assert pathlib.Path(t2l.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
runtime = t2l.create_runtime(RuntimeConfig(asset_root=pathlib.Path(sys.argv[2]), device='cpu'))
plan = runtime.use_case._lyrics.prepare(('hello world',))
assert plan.payload.phones == ('HH', 'AH', 'L', 'OW', ' ', 'W', 'ER', 'L', 'D')
"""

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            probe,
            str(installation),
            str(asset_root),
        ],
        cwd=outside,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_cli_001_cli_002_installed_console_script_uses_one_output_target(tmp_path):
    """CLI-001/CLI-002: installed real pipeline preserves stdout XOR file."""

    wheel, _sdist = _build_distributions(tmp_path)
    installation = tmp_path / "real-cli-venv"
    _run_uv(
        "venv",
        "--python",
        sys.executable,
        "--no-python-downloads",
        str(installation),
        cwd=tmp_path,
    )
    venv_python = installation / "bin" / "python"
    _run_uv(
        "pip",
        "install",
        "--python",
        str(venv_python),
        "--no-python-downloads",
        "--no-deps",
        str(wheel),
        cwd=tmp_path,
    )

    # Keep this gate fast while still executing installed wheel code: expose the
    # already lock-synchronized host dependencies through a .pth file. Cold,
    # no-index dependency installation remains the separate PKG-012/OFF-003 gate.
    source_site = _site_packages(sys.executable, cwd=tmp_path)
    target_site = _site_packages(venv_python, cwd=tmp_path)
    (target_site / "locked-host-dependencies.pth").write_text(
        str(source_site) + "\n", encoding="utf-8"
    )

    asset_root = tmp_path / "external-assets"
    for relative_path in (
        "lid.176.ftz",
        "checkpoints/checkpoint_MTL",
        "assets/nltk_data/taggers/averaged_perceptron_tagger.zip",
        "assets/nltk_data/corpora/cmudict.zip",
    ):
        destination = asset_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative_path, destination)

    outside = tmp_path / "outside-real-cli"
    outside.mkdir()
    lyrics = outside / "lyrics.txt"
    lyrics.write_text("hello\n", encoding="utf-8")
    audio = outside / "input.mp3"
    shutil.copy2(
        REPOSITORY_ROOT / "tests/fixtures/audio/sine-440hz-250ms-mono-22050.mp3",
        audio,
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"

    result = subprocess.run(
        [
            str(installation / "bin" / "ai-auto-lrc"),
            str(lyrics),
            str(audio),
            "--asset-root",
            str(asset_root),
            "--device",
            "cpu",
            "--verbose",
        ],
        check=False,
        cwd=outside,
        env=environment,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout == b"[00:00.034]hello\n"
    assert b"[00:00.034]hello" not in result.stderr
    progress = [
        line
        for line in result.stderr.decode("utf-8").splitlines()
        if line.startswith("T2L_PROGRESS:")
    ]
    assert progress == [
        "T2L_PROGRESS: stage=lyrics_read status=started",
        "T2L_PROGRESS: stage=lyrics_read status=completed",
        "T2L_PROGRESS: stage=runtime_create status=started",
        "T2L_PROGRESS: stage=runtime_create status=completed",
        "T2L_PROGRESS: stage=alignment status=started",
        "T2L_PROGRESS: stage=alignment status=completed result=complete",
        "T2L_PROGRESS: stage=output status=started target=stdout",
        "T2L_PROGRESS: stage=output status=completed target=stdout",
    ]

    output = outside / "result.lrc"
    file_result = subprocess.run(
        [
            str(installation / "bin" / "ai-auto-lrc"),
            str(lyrics),
            str(audio),
            "--asset-root",
            str(asset_root),
            "--device",
            "cpu",
            "--output",
            str(output),
        ],
        check=False,
        cwd=outside,
        env=environment,
        capture_output=True,
    )

    assert file_result.returncode == 0, file_result.stderr.decode(
        "utf-8", errors="replace"
    )
    assert file_result.stdout == b""
    assert output.read_bytes() == result.stdout


def test_pyproject_declares_separate_test_and_dev_groups(tmp_path):
    """PKG-001/PKG-005: dependency groups and installed optional behavior differ."""

    config = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text("utf-8"))

    assert config["project"]["requires-python"] == ">=3.10,<3.12"
    assert "fasttext-wheel==0.9.2" in config["project"]["dependencies"]
    assert "fasttext==0.9.2" not in config["project"]["dependencies"]
    assert "g2p-en==2.1.0" in config["project"]["dependencies"]
    assert "nltk==3.8.1" in config["project"]["dependencies"]
    assert set(config["project"]["optional-dependencies"]) == {"vocals"}
    assert config["dependency-groups"]["test"]
    dev_includes = {
        item["include-group"]
        for item in config["dependency-groups"]["dev"]
        if isinstance(item, dict)
    }
    assert dev_includes == {"test"}

    wheel, _sdist = _build_distributions(tmp_path)
    installation, target_site = _install_wheel_with_locked_host_dependencies(
        tmp_path,
        wheel,
        name="optional-vocals-venv",
    )
    guard_source = r"""
import builtins
import os
import socket
import sys

_event_log = os.environ.get('T2L_OFFLINE_GUARD_LOG')
_real_import = builtins.__import__

def _record(event):
    if _event_log:
        with open(_event_log, 'a', encoding='utf-8') as stream:
            stream.write(event + '\n')

def _blocked_network(*_args, **_kwargs):
    _record('network')
    raise AssertionError('installed wheel attempted network access')

def _blocked_nltk_download(*_args, **_kwargs):
    _record('nltk.download')
    raise AssertionError('installed wheel attempted nltk.download')

def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'demucs' or name.startswith('demucs.'):
        _record('demucs-import:' + name)
        raise ModuleNotFoundError(
            'offline package test blocked optional Demucs import',
            name=name,
        )
    module = _real_import(name, globals, locals, fromlist, level)
    if name == 'nltk' or name.startswith('nltk.'):
        nltk_module = sys.modules.get('nltk')
        if nltk_module is not None:
            nltk_module.download = _blocked_nltk_download
    return module

builtins.__import__ = _guarded_import
socket.create_connection = _blocked_network
socket.getaddrinfo = _blocked_network
socket.socket.connect = _blocked_network
socket.socket.connect_ex = _blocked_network
"""
    (target_site / "sitecustomize.py").write_text(guard_source, encoding="utf-8")

    asset_root = _copy_runtime_assets(tmp_path)
    outside = tmp_path / "outside-optional-vocals"
    empty_home = tmp_path / "empty-home"
    outside.mkdir()
    empty_home.mkdir()
    lyrics = outside / "lyrics.txt"
    lyrics.write_text("hello\n", encoding="utf-8")
    audio = outside / "input.mp3"
    shutil.copy2(
        REPOSITORY_ROOT / "tests/fixtures/audio/sine-440hz-250ms-mono-22050.mp3",
        audio,
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "DEMUCS_CACHE": str(tmp_path / "empty-demucs-cache"),
            "HF_HOME": str(tmp_path / "empty-hf-cache"),
            "HOME": str(empty_home),
            "PYTHONNOUSERSITE": "1",
            "TORCH_HOME": str(tmp_path / "empty-torch-cache"),
            "XDG_CACHE_HOME": str(tmp_path / "empty-xdg-cache"),
        }
    )
    venv_python = installation / "bin" / "python"
    console = installation / "bin" / "ai-auto-lrc"

    commands = (
        (
            "import",
            [
                str(venv_python),
                "-I",
                "-c",
                (
                    "import importlib.util, pathlib, sys, t2l; "
                    "assert importlib.util.find_spec('demucs') is None; "
                    "assert pathlib.Path(t2l.__file__).resolve().is_relative_to("
                    "pathlib.Path(sys.argv[1]).resolve())"
                ),
                str(installation),
            ],
        ),
        ("help", [str(console), "--help"]),
        (
            "pipeline",
            [
                str(console),
                str(lyrics),
                str(audio),
                "--asset-root",
                str(asset_root),
                "--device",
                "cpu",
            ],
        ),
    )
    for label, command in commands:
        event_log = tmp_path / f"{label}-offline-events.log"
        environment["T2L_OFFLINE_GUARD_LOG"] = str(event_log)
        result = subprocess.run(
            command,
            check=False,
            cwd=outside,
            env=environment,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr.decode(
            "utf-8", errors="replace"
        )
        assert _offline_guard_events(event_log) == []
        if label == "pipeline":
            assert result.stdout == b"[00:00.034]hello\n"

    separation_log = tmp_path / "separation-offline-events.log"
    environment["T2L_OFFLINE_GUARD_LOG"] = str(separation_log)
    separation = subprocess.run(
        [
            str(console),
            str(lyrics),
            str(audio),
            "--asset-root",
            str(asset_root),
            "--device",
            "cpu",
            "--separate-vocals",
        ],
        check=False,
        cwd=outside,
        env=environment,
        capture_output=True,
    )

    assert separation.returncode == 5
    assert separation.stdout == b""
    assert separation.stderr.endswith(
        b"T2L_VOCALS_DEPENDENCY_MISSING: "
        b"Demucs source separation requires the vocals extra.\n"
    )
    events = _offline_guard_events(separation_log)
    assert events == ["demucs-import:demucs"]
