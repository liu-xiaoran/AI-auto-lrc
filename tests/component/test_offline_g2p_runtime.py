"""Offline runtime-asset and real G2P wiring checks."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from t2l.adapters.assets import AssetLocator
from t2l.adapters.lyrics import OfflineG2PProvider
from t2l.api import create_runtime
from t2l.composition import _prepare_g2p_resources, _prepare_lid_resource
from t2l.contracts import RuntimeConfig
from t2l.errors import AssetNotFoundError, CheckpointError
from t2l.model_profiles import load_legacy_v1_profile
from t2l.phonetic import PhoneticConverter

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.component
EXPECTED_RUNTIME_ASSETS = {
    "nltk-averaged-perceptron-tagger": {
        "relative_path": "assets/nltk_data/taggers/averaged_perceptron_tagger.zip",
        "sha256": "e1f13cf2532daadfd6f3bc481a49859f0b8ea6432ccdcd83e6a49a5f19008de9",
        "size_bytes": 2_526_731,
        "source": "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/taggers/averaged_perceptron_tagger.zip",
        "license": "MIT License",
    },
    "nltk-cmudict": {
        "relative_path": "assets/nltk_data/corpora/cmudict.zip",
        "sha256": "d07cca47fd72ad32ea9d8ad1219f85301eeaf4568f8b6b73747506a71fb5afd6",
        "size_bytes": 896_069,
        "source": "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/cmudict.zip",
        "license": (
            "CMU Pronouncing Dictionary: unrestricted research/commercial use; "
            "acknowledgement requested"
        ),
    },
}
EXPECTED_LID_ASSET = {
    "relative_path": "lid.176.ftz",
    "sha256": "8f3472cfe8738a7b6099e8e999c3cbfae0dcd15696aac7d7738a8039db603e83",
    "size_bytes": 938_013,
    "source": "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz",
    "license": (
        "CC-BY-SA 3.0 per upstream fastText model page; "
        "redistribution review pending"
    ),
}


def _copy_asset(root: Path, relative_path: str) -> Path:
    source = REPOSITORY_ROOT / relative_path
    destination = root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _runtime_root(tmp_path: Path, *, include_runtime_assets: bool) -> Path:
    root = tmp_path / "runtime-root"
    _copy_asset(root, "lid.176.ftz")
    if include_runtime_assets:
        for expected in EXPECTED_RUNTIME_ASSETS.values():
            _copy_asset(root, expected["relative_path"])
    return root


def _forbid_unverified_g2p_factory(monkeypatch) -> None:
    from t2l.adapters import lyrics

    monkeypatch.setattr(
        lyrics,
        "_create_g2p",
        lambda: (_ for _ in ()).throw(
            AssertionError("G2P construction must follow asset verification")
        ),
    )


def test_ast_024_manifest_pins_complete_offline_g2p_assets():
    """AST-024: logical identity, path, hash, size, source, and license are pinned."""

    runtime_assets = load_legacy_v1_profile().runtime_assets

    assert set(EXPECTED_RUNTIME_ASSETS) < set(runtime_assets)
    for logical_name, expected in EXPECTED_RUNTIME_ASSETS.items():
        spec = runtime_assets[logical_name]
        path = REPOSITORY_ROOT / spec.relative_path
        assert spec.logical_name == logical_name
        assert str(spec.relative_path) == expected["relative_path"]
        assert spec.sha256 == expected["sha256"]
        assert spec.size_bytes == expected["size_bytes"]
        assert spec.source == expected["source"]
        assert spec.license == expected["license"]
        assert path.stat().st_size == spec.size_bytes
        assert hashlib.sha256(path.read_bytes()).hexdigest() == spec.sha256


def test_ast_018_lid_is_pinned_by_the_package_manifest():
    """AST-018: LID identity, path, hash, size, source, and license are pinned."""

    spec = load_legacy_v1_profile().runtime_assets["lid-fasttext-176"]
    path = REPOSITORY_ROOT / spec.relative_path

    assert spec.logical_name == "lid-fasttext-176"
    assert str(spec.relative_path) == EXPECTED_LID_ASSET["relative_path"]
    assert spec.sha256 == EXPECTED_LID_ASSET["sha256"]
    assert spec.size_bytes == EXPECTED_LID_ASSET["size_bytes"]
    assert spec.source == EXPECTED_LID_ASSET["source"]
    assert spec.license == EXPECTED_LID_ASSET["license"]
    assert path.stat().st_size == spec.size_bytes
    assert hashlib.sha256(path.read_bytes()).hexdigest() == spec.sha256


def test_lid_fasttext_consumes_a_private_runtime_owned_snapshot(tmp_path):
    root = _runtime_root(tmp_path, include_runtime_assets=True)
    locator = AssetLocator(asset_root=root, environ={}, development_root=None)
    snapshot = _prepare_lid_resource(locator, load_legacy_v1_profile())
    private_path = snapshot.path("lid-fasttext-176")
    calls = 0

    class Model:
        @staticmethod
        def predict(_text, *, k):
            assert k == 1
            return (("__label__en",), (1.0,))

    def loader(path):
        nonlocal calls
        calls += 1
        assert path == private_path
        assert private_path != root / "lid.176.ftz"
        assert private_path.stat().st_mode & stat.S_IWUSR == 0
        with pytest.raises(PermissionError):
            private_path.write_bytes(b"in-place overwrite")
        with pytest.raises(PermissionError):
            private_path.with_suffix(".replacement").write_bytes(b"replacement")
        return Model()

    converter = PhoneticConverter(
        private_path,
        fasttext_loader=loader,
        asset_owner=snapshot,
    )

    assert converter.detect_language("hello") == "__label__en"
    assert calls == 1
    assert converter._asset_owner is snapshot
    snapshot.close()


def test_nltk_consumes_two_archives_from_one_private_runtime_owned_set(tmp_path):
    root = _runtime_root(tmp_path, include_runtime_assets=True)
    locator = AssetLocator(asset_root=root, environ={}, development_root=None)
    snapshot = _prepare_g2p_resources(locator, load_legacy_v1_profile())
    expected_paths = {
        "nltk-averaged-perceptron-tagger": snapshot.root
        / "taggers/averaged_perceptron_tagger.zip",
        "nltk-cmudict": snapshot.root / "corpora/cmudict.zip",
    }

    def factory():
        assert snapshot.root.stat().st_mode & stat.S_IWUSR == 0
        for logical_name, path in expected_paths.items():
            assert snapshot.path(logical_name) == path
            assert path.stat().st_mode & stat.S_IWUSR == 0
            with pytest.raises(PermissionError):
                path.write_bytes(b"in-place overwrite")
            with pytest.raises(PermissionError):
                path.with_suffix(".replacement").write_bytes(b"replacement")
        return lambda text: (text.upper(),)

    provider = OfflineG2PProvider(
        prepare_resources=lambda: snapshot,
        resource_finder=lambda _name: True,
        g2p_factory=factory,
    )

    assert provider("hello") == ("HELLO",)
    assert provider._resource_assets is snapshot
    snapshot.close()


def test_ast_017_explicit_root_missing_g2p_asset_fails_on_first_prepare(
    tmp_path, monkeypatch
):
    """AST-017: an explicit incomplete root never falls back to dev assets."""

    root = _runtime_root(tmp_path, include_runtime_assets=False)
    _forbid_unverified_g2p_factory(monkeypatch)
    runtime = create_runtime(RuntimeConfig(asset_root=root, device="cpu"))

    with pytest.raises(AssetNotFoundError) as error:
        runtime.use_case._lyrics.prepare(("hello",))

    assert error.value.code == "T2L_ASSET_NOT_FOUND"
    assert error.value.stage == "asset_resolution"
    assert error.value.details["logical_name"] == "nltk-averaged-perceptron-tagger"
    assert error.value.details["checked_roots"] == [str(root.resolve())]


def test_ast_006_explicit_root_bad_g2p_hash_fails_before_g2p(
    tmp_path, monkeypatch
):
    """AST-006: corrupt configured G2P bytes fail before import or fallback."""

    root = _runtime_root(tmp_path, include_runtime_assets=True)
    corrupt = root / EXPECTED_RUNTIME_ASSETS["nltk-cmudict"]["relative_path"]
    payload = bytearray(corrupt.read_bytes())
    payload[-1] ^= 0x01
    corrupt.write_bytes(payload)
    _forbid_unverified_g2p_factory(monkeypatch)
    runtime = create_runtime(RuntimeConfig(asset_root=root, device="cpu"))

    with pytest.raises(CheckpointError) as error:
        runtime.use_case._lyrics.prepare(("hello",))

    assert error.value.code == "T2L_ASSET_HASH_MISMATCH"
    assert error.value.stage == "asset_resolution"
    assert error.value.details["logical_name"] == "nltk-cmudict"


def test_off_005_real_g2p_succeeds_with_empty_caches_and_network_fuses(tmp_path):
    """OFF-005: verified local zips support first-use G2P without downloads."""

    empty_home = tmp_path / "home"
    empty_nltk = tmp_path / "empty-nltk"
    empty_cache = tmp_path / "cache"
    for directory in (empty_home, empty_nltk, empty_cache):
        directory.mkdir()
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "HOME": str(empty_home),
            "NLTK_DATA": str(empty_nltk),
            "XDG_CACHE_HOME": str(empty_cache),
        }
    )
    probe = """
import nltk
import socket

def blocked(*_args, **_kwargs):
    raise AssertionError("offline G2P attempted network or nltk.download")

nltk.download = blocked
socket.create_connection = blocked
socket.socket.connect = blocked

from pathlib import Path
from t2l.api import create_runtime
from t2l.contracts import RuntimeConfig

runtime = create_runtime(RuntimeConfig(asset_root=Path(__import__('sys').argv[1]), device='cpu'))
plan = runtime.use_case._lyrics.prepare(('hello world',))
assert plan.payload.phones == ('HH', 'AH', 'L', 'OW', ' ', 'W', 'ER', 'L', 'D')
assert tuple(token.text for token in plan.tokens) == ('hello', ' world')
"""

    result = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(REPOSITORY_ROOT)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
