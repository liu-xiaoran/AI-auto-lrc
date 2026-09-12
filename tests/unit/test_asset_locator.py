from __future__ import annotations

import hashlib
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_asset(root: Path, relative_path: str, data: bytes) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_asset_root_precedence_is_config_then_env_then_development(tmp_path):
    from t2l.adapters.assets import AssetLocator, AssetSpec

    relative = "checkpoints/model.bin"
    config_root = tmp_path / "config"
    env_root = tmp_path / "env"
    development_root = tmp_path / "development"
    expected = b"configured"
    _write_asset(config_root, relative, expected)
    _write_asset(env_root, relative, b"environment")
    _write_asset(development_root, relative, b"development")

    locator = AssetLocator(
        asset_root=config_root,
        environ={"T2L_ASSET_ROOT": str(env_root)},
        development_root=development_root,
    )
    resolved = locator.resolve(
        AssetSpec("model", relative, sha256=_digest(expected), size=len(expected))
    )

    assert resolved.path == (config_root / relative).resolve()
    assert resolved.provenance == "config"


def test_environment_root_precedes_development_root(tmp_path):
    from t2l.adapters.assets import AssetLocator, AssetSpec

    relative = "lid.176.ftz"
    env_root = tmp_path / "env"
    development_root = tmp_path / "development"
    expected = b"environment"
    _write_asset(env_root, relative, expected)
    _write_asset(development_root, relative, b"development")

    resolved = AssetLocator(
        environ={"T2L_ASSET_ROOT": str(env_root)},
        development_root=development_root,
    ).resolve(AssetSpec("lid", relative, sha256=_digest(expected)))

    assert resolved.path == (env_root / relative).resolve()
    assert resolved.provenance == "environment"


@pytest.mark.parametrize("source", ["config", "environment"])
def test_relative_configured_roots_are_rejected_without_using_cwd(
    tmp_path, monkeypatch, source
):
    from t2l.adapters.assets import AssetLocator, AssetSpec

    monkeypatch.chdir(tmp_path)
    kwargs = (
        {"asset_root": "relative-assets", "environ": {}}
        if source == "config"
        else {"environ": {"T2L_ASSET_ROOT": "relative-assets"}}
    )

    with pytest.raises(Exception) as exc_info:
        AssetLocator(development_root=None, **kwargs).resolve(
            AssetSpec("model", "model.bin", sha256="0" * 64)
        )

    assert exc_info.value.code == "T2L_ASSET_ROOT_INVALID"
    assert exc_info.value.stage == "configuration"


def test_cwd_is_never_used_as_an_asset_root(tmp_path, monkeypatch):
    from t2l.adapters import assets
    from t2l.adapters.assets import AssetLocator, AssetSpec

    relative = "checkpoints/model.bin"
    cwd = tmp_path / "hostile-cwd"
    data = b"malicious"
    _write_asset(cwd, relative, data)
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(assets, "_discover_development_root", lambda: None)

    with pytest.raises(Exception) as exc_info:
        AssetLocator(environ={}).resolve(
            AssetSpec("model", relative, sha256=_digest(data))
        )

    assert exc_info.value.code == "T2L_ASSET_NOT_FOUND"
    assert str(cwd) not in exc_info.value.details["checked_roots"]


def test_symlink_escape_is_rejected(tmp_path):
    from t2l.adapters.assets import AssetLocator, AssetSpec

    root = tmp_path / "assets"
    outside = tmp_path / "outside"
    outside_file = _write_asset(outside, "model.bin", b"payload")
    root.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(Exception) as exc_info:
        AssetLocator(asset_root=root, environ={}, development_root=None).resolve(
            AssetSpec("model", "escape/model.bin", sha256=_digest(b"payload"))
        )

    assert outside_file.exists()
    assert exc_info.value.code == "T2L_ASSET_PATH_ESCAPE"


@pytest.mark.parametrize("failure", ["hash", "lfs"])
def test_invalid_asset_is_rejected_before_loader(tmp_path, failure):
    from t2l.adapters.assets import AssetLocator, AssetSpec

    root = tmp_path / "assets"
    expected = b"trusted"
    if failure == "lfs":
        actual = (
            b"version https://git-lfs.github.com/spec/v1\n"
            b"oid sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
            b"size 100\n"
        )
        code = "T2L_ASSET_LFS_POINTER"
    else:
        actual = b"tampered"
        code = "T2L_ASSET_HASH_MISMATCH"
    _write_asset(root, "model.bin", actual)
    calls = 0

    def loader(_path: Path):
        nonlocal calls
        calls += 1
        return object()

    with pytest.raises(Exception) as exc_info:
        AssetLocator(asset_root=root, environ={}, development_root=None).load(
            AssetSpec("model", "model.bin", sha256=_digest(expected)), loader
        )

    assert exc_info.value.code == code
    assert calls == 0


def test_resolved_asset_retains_manifest_metadata(tmp_path):
    from t2l.adapters.assets import AssetLocator, AssetSpec

    root = tmp_path / "assets"
    data = b"checkpoint"
    _write_asset(root, "model.bin", data)
    spec = AssetSpec(
        "mtl",
        "model.bin",
        sha256=_digest(data),
        size=len(data),
        architecture_id="legacy-v1-mtl",
        feature_spec_id="mel-22050-v1",
        phone_inventory_id="arpabet-41-v1",
        source="upstream",
        license="MIT",
    )

    resolved = AssetLocator(
        asset_root=root, environ={}, development_root=None
    ).resolve(spec)

    assert resolved.spec is spec
    assert resolved.provenance == "config"


def test_checkpoint_manifest_entry_can_be_adapted_without_loading_torch():
    from t2l.adapters.assets import AssetSpec
    from t2l.model_profiles import load_legacy_v1_profile

    checkpoint = load_legacy_v1_profile().checkpoints["MTL"]

    spec = AssetSpec.from_manifest_entry(checkpoint)

    assert spec.logical_name == checkpoint.logical_name
    assert spec.relative_path == str(checkpoint.relative_path)
    assert spec.size == checkpoint.size_bytes
    assert spec.architecture_id == checkpoint.architecture_id


def test_materialized_asset_sets_close_independently_and_idempotently(tmp_path):
    """The existing owner primitive can release one runtime without another."""

    from t2l.adapters.assets import AssetLocator, AssetSpec

    root = tmp_path / "assets"
    content = b"runtime-owned"
    _write_asset(root, "runtime.bin", content)
    locator = AssetLocator(asset_root=root, environ={}, development_root=None)
    requested = {
        "runtime": (
            AssetSpec(
                "runtime", "runtime.bin", sha256=_digest(content), size=len(content)
            ),
            "runtime.bin",
        )
    }

    first = locator.materialize_set(requested)
    second = locator.materialize_set(requested)
    first_root = first.root
    second_root = second.root

    assert first_root != second_root
    assert first.path("runtime").read_bytes() == content
    assert second.path("runtime").read_bytes() == content

    workers = 16
    start = threading.Barrier(workers + 1)

    def close_first():
        start.wait()
        first.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(close_first) for _ in range(workers)]
        start.wait()
        for future in futures:
            future.result(timeout=2)

    first.close()

    assert not first_root.exists()
    assert second_root.exists()
    assert second.path("runtime").read_bytes() == content

    second.close()
    assert not second_root.exists()


def test_ast_020_materialized_asset_set_publishes_only_complete_versions(
    tmp_path, monkeypatch
):
    """AST-020: interrupted updates never publish a mixed runtime asset set."""

    from t2l.adapters import assets as assets_module
    from t2l.adapters.assets import AssetLocator, AssetSpec
    from t2l.errors import CheckpointError

    root = tmp_path / "assets"
    first = _write_asset(root, "first.bin", b"old-first")
    second = _write_asset(root, "second.bin", b"old-second")
    locator = AssetLocator(asset_root=root, environ={}, development_root=None)

    def specs(first_bytes: bytes, second_bytes: bytes):
        return {
            "first": (
                AssetSpec("first", "first.bin", _digest(first_bytes), len(first_bytes)),
                "set/first.bin",
            ),
            "second": (
                AssetSpec("second", "second.bin", _digest(second_bytes), len(second_bytes)),
                "set/second.bin",
            ),
        }

    with locator.materialize_set(specs(b"old-first", b"old-second")) as old_set:
        assert old_set.path("first").read_bytes() == b"old-first"
        assert old_set.path("second").read_bytes() == b"old-second"
        assert old_set.root != root
        assert old_set.root.stat().st_mode & stat.S_IWUSR == 0
        assert all(path.stat().st_mode & stat.S_IWUSR == 0 for path in old_set.paths.values())
        old_root = old_set.root
    assert not old_root.exists()

    original_snapshot = locator._verified_snapshot
    original_temporary_directory = assets_module.tempfile.TemporaryDirectory
    publications = 0

    def tracking_temporary_directory(*args, **kwargs):
        nonlocal publications
        publications += 1
        return original_temporary_directory(*args, **kwargs)

    def interrupt_after_first(spec):
        snapshot = original_snapshot(spec)
        if spec.logical_name == "first":
            second.write_bytes(b"next-second")
        return snapshot

    monkeypatch.setattr(assets_module.tempfile, "TemporaryDirectory", tracking_temporary_directory)
    monkeypatch.setattr(locator, "_verified_snapshot", interrupt_after_first)
    with pytest.raises(CheckpointError) as error:
        locator.materialize_set(specs(b"old-first", b"old-second"))
    assert error.value.code == "T2L_ASSET_SIZE_MISMATCH"
    assert publications == 0

    first.write_bytes(b"next-first")
    monkeypatch.setattr(locator, "_verified_snapshot", original_snapshot)
    with locator.materialize_set(specs(b"next-first", b"next-second")) as next_set:
        assert next_set.path("first").read_bytes() == b"next-first"
        assert next_set.path("second").read_bytes() == b"next-second"
    assert publications == 1


def test_materialized_asset_set_rejects_symlink_sources(tmp_path):
    from t2l.adapters.assets import AssetLocator, AssetSpec
    from t2l.errors import CheckpointError

    root = tmp_path / "assets"
    target = _write_asset(root, "target.bin", b"trusted")
    source = root / "source.bin"
    source.symlink_to(target)

    with pytest.raises(CheckpointError) as error:
        AssetLocator(asset_root=root, environ={}, development_root=None).materialize_set(
            {
                "source": (
                    AssetSpec("source", "source.bin", _digest(b"trusted"), 7),
                    "source.bin",
                )
            }
        )

    assert error.value.code == "T2L_ASSET_SYMLINK_REJECTED"


def test_materialized_asset_set_rejects_in_place_changes_during_read(
    tmp_path, monkeypatch
):
    from t2l.adapters.assets import AssetLocator, AssetSpec
    from t2l.errors import CheckpointError

    root = tmp_path / "assets"
    source = _write_asset(root, "source.bin", b"trusted")
    original_open = Path.open

    class MutatingReader:
        def __init__(self):
            self._stream = original_open(source, "rb")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._stream.close()

        def fileno(self):
            return self._stream.fileno()

        def read(self):
            content = self._stream.read()
            source.write_bytes(b"changed-during-read")
            return content

    def racing_open(path, mode="r", *args, **kwargs):
        if path == source and mode == "rb":
            return MutatingReader()
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", racing_open)

    with pytest.raises(CheckpointError) as error:
        AssetLocator(asset_root=root, environ={}, development_root=None).materialize_set(
            {
                "source": (
                    AssetSpec("source", "source.bin", _digest(b"trusted"), 7),
                    "source.bin",
                )
            }
        )

    assert error.value.code == "T2L_ASSET_CHANGED_DURING_READ"
