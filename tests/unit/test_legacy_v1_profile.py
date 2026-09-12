import json
from pathlib import Path

import pytest

from t2l.model_profiles import (
    DISTRIBUTION_NAME,
    LEGACY_V1_PROFILE_CONTRACT_VERSION,
    LEGACY_V1_PROFILE_ID,
    ManifestValidationError,
    load_legacy_v1_profile,
)


def test_legacy_v1_profile_freezes_feature_and_axis_semantics():
    profile = load_legacy_v1_profile()

    assert profile.profile_id == LEGACY_V1_PROFILE_ID == "legacy-v1"
    assert profile.compatibility.distribution == DISTRIBUTION_NAME == "ai-auto-lrc"
    assert profile.compatibility.package_version == "2.0.0a0"
    assert profile.compatibility.profile_id == LEGACY_V1_PROFILE_ID
    assert (
        profile.compatibility.profile_contract_version
        == LEGACY_V1_PROFILE_CONTRACT_VERSION
        == 1
    )
    assert profile.feature.sample_rate == 22_050
    assert profile.feature.n_mels == 128
    assert profile.feature.n_fft == 512
    assert profile.feature.win_length == 512
    assert profile.feature.hop_length == 256
    assert profile.feature.power == 2.0
    assert profile.feature.center is True
    assert profile.feature.pad_mode == "reflect"
    assert profile.feature.normalized is False
    assert profile.feature.mel_scale == "htk"
    assert profile.frame_clock_numerator == 768
    assert profile.frame_clock_denominator == 22_050
    assert profile.lstm_batch_first == (True, False, False)


def test_legacy_v1_profile_declares_all_three_checkpoint_shapes():
    profile = load_legacy_v1_profile()

    assert tuple(profile.checkpoints) == ("Baseline", "MTL", "BDR")
    assert profile.checkpoints["Baseline"].output_classes == (41,)
    assert profile.checkpoints["MTL"].output_classes == (41, 47)
    assert profile.checkpoints["BDR"].output_classes == (1,)
    assert profile.checkpoints["Baseline"].architecture_id == "legacy-v1-acoustic-baseline"
    assert profile.checkpoints["MTL"].architecture_id == "legacy-v1-acoustic-mtl"
    assert profile.checkpoints["BDR"].architecture_id == "legacy-v1-boundary"
    assert {spec.state_dict_key_count for spec in profile.checkpoints.values()} == {38}


def test_packaged_and_audit_manifest_copies_are_byte_identical():
    profile = load_legacy_v1_profile()
    repository_manifest = (
        Path(__file__).resolve().parents[2] / "assets" / "legacy_v1_manifest.json"
    )

    assert profile.manifest_path.read_bytes() == repository_manifest.read_bytes()


def test_manifest_rejects_profile_or_architecture_mismatch(tmp_path):
    source = load_legacy_v1_profile().manifest_path
    document = json.loads(source.read_text(encoding="utf-8"))
    document["checkpoints"]["Baseline"]["profile_id"] = "future-v2"
    path = tmp_path / "profile-mismatch.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ManifestValidationError, match="profile_id"):
        load_legacy_v1_profile(path)

    document = json.loads(source.read_text(encoding="utf-8"))
    document["checkpoints"]["MTL"]["architecture_id"] = "legacy-v1-acoustic-baseline"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ManifestValidationError, match="architecture_id"):
        load_legacy_v1_profile(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("distribution", "different-project", "distribution"),
        ("package_version", "2.0.0a1", "package_version"),
        ("profile_id", "future-v2", "profile_id"),
        ("profile_contract_version", 2, "profile_contract_version"),
    ),
)
def test_manifest_rejects_incompatible_package_and_profile_contract(
    tmp_path, field, value, message
):
    source = load_legacy_v1_profile().manifest_path
    document = json.loads(source.read_text(encoding="utf-8"))
    document["compatibility"][field] = value
    path = tmp_path / "incompatible-manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ManifestValidationError, match=message):
        load_legacy_v1_profile(path)
