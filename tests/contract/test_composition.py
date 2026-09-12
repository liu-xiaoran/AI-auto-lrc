import builtins
import json
import sys
import zipfile
from pathlib import Path

import pytest

from t2l import composition
from t2l.api import AlignmentRuntime, create_runtime
from t2l.contracts import RuntimeConfig
from t2l.errors import CheckpointError
from t2l.model_profiles import ManifestValidationError, load_legacy_v1_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_default_runtime_constructs_without_loading_language_or_models(monkeypatch):
    import sys

    sys.modules.pop("fasttext", None)
    runtime = create_runtime(RuntimeConfig(asset_root=REPOSITORY_ROOT, device="cpu"))

    assert isinstance(runtime, AlignmentRuntime)
    inference = runtime.use_case._inference
    lyrics = runtime.use_case._lyrics
    assert inference._models == {}
    assert lyrics._phonetizer.__self__._fasttext_model is None
    assert "fasttext" not in sys.modules


def test_off_004_runtime_creation_does_not_import_g2p_or_read_nltk_archives(
    monkeypatch,
):
    """OFF-004: composition keeps G2P code and verified zip bytes lazy."""

    sys.modules.pop("g2p_en", None)
    real_import = builtins.__import__
    real_path_open = Path.open

    def guarded_import(name, *args, **kwargs):
        if name == "g2p_en" or name.startswith("g2p_en."):
            raise AssertionError("create_runtime must not import g2p_en")
        return real_import(name, *args, **kwargs)

    def guarded_path_open(path, *args, **kwargs):
        if path.name in {"averaged_perceptron_tagger.zip", "cmudict.zip"}:
            raise AssertionError("create_runtime must not read NLTK zip bytes")
        return real_path_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    monkeypatch.setattr(
        zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("create_runtime must not open NLTK zip archives")
        ),
    )

    runtime = create_runtime(RuntimeConfig(asset_root=REPOSITORY_ROOT, device="cpu"))

    assert isinstance(runtime, AlignmentRuntime)
    assert "g2p_en" not in sys.modules


def test_public_package_exports_only_v2_entry_points():
    import t2l

    assert t2l.__version__ == "2.0.0a0"
    assert t2l.process.__module__ == "t2l.api"
    assert "legacy_process" not in t2l.__all__


def test_manifest_incompatibility_is_a_stable_public_runtime_error(monkeypatch):
    cause = ManifestValidationError("fixture package/profile mismatch")
    monkeypatch.setattr(
        composition,
        "load_legacy_v1_profile",
        lambda: (_ for _ in ()).throw(cause),
    )

    with pytest.raises(CheckpointError) as exc_info:
        create_runtime(RuntimeConfig())

    assert exc_info.value.code == "T2L_ASSET_MANIFEST_INVALID"
    assert exc_info.value.stage == "asset_resolution"
    assert exc_info.value.details == {"profile": "legacy-v1"}
    assert exc_info.value.__cause__ is cause


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("package_version", "2.0.0a1"),
        ("profile_contract_version", 2),
    ),
)
def test_ast_019_compatibility_fails_before_asset_or_model_loading(
    tmp_path, monkeypatch, field, value
):
    """AST-019: package/profile incompatibility fails before asset/model loading."""

    source = composition.load_legacy_v1_profile().manifest_path
    document = json.loads(source.read_text(encoding="utf-8"))
    document["compatibility"][field] = value
    incompatible = tmp_path / "incompatible-manifest.json"
    incompatible.write_text(json.dumps(document), encoding="utf-8")

    monkeypatch.setattr(
        composition,
        "load_legacy_v1_profile",
        lambda: load_legacy_v1_profile(incompatible),
    )
    monkeypatch.setattr(
        composition,
        "_prepare_lid_resource",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("asset materialization must not start")
        ),
    )
    monkeypatch.setattr(
        composition,
        "LegacyV1Inference",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("model adapter construction must not start")
        ),
    )

    with pytest.raises(CheckpointError) as exc_info:
        create_runtime(RuntimeConfig(asset_root=tmp_path))

    assert exc_info.value.code == "T2L_ASSET_MANIFEST_INVALID"
    assert exc_info.value.stage == "asset_resolution"
    assert isinstance(exc_info.value.__cause__, ManifestValidationError)
