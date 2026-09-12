import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from t2l.adapters import legacy_v1_inference as legacy
from t2l.errors import CheckpointError
from t2l.model_profiles import load_legacy_v1_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.component


def test_official_checkpoint_hashes_sizes_and_structure_match_manifest():
    profile = load_legacy_v1_profile()

    expected_hashes = {
        "Baseline": "b420ea97032691b3f51e271c0b688a85e168d7b7ee89baf6725f601ccd07bb45",
        "MTL": "826559e7e810bf8f90223d8fd5c66525c01ad4dd9cdc19d019f39f784e7ed3c1",
        "BDR": "a3955b290311bec16f04253eac328147d444f275f263315490ec5faf1a668fc9",
    }

    for name, spec in profile.checkpoints.items():
        checkpoint = REPOSITORY_ROOT / spec.relative_path
        assert checkpoint.stat().st_size == spec.size_bytes
        assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == expected_hashes[name]
        state = legacy.load_checkpoint_state(checkpoint, spec)
        assert len(state) == spec.state_dict_key_count == 38
        assert legacy.state_dict_signature(state) == spec.state_dict_signature_sha256


def test_lfs_pointer_is_rejected_before_deserialization(tmp_path, monkeypatch):
    spec = load_legacy_v1_profile().checkpoints["Baseline"]
    pointer = tmp_path / "checkpoint_Baseline"
    pointer.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:" + spec.sha256 + "\n"
        "size " + str(spec.size_bytes) + "\n",
        encoding="ascii",
    )
    calls = 0

    def forbidden_load(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("torch.load must not receive an LFS pointer")

    monkeypatch.setattr(legacy.torch, "load", forbidden_load)

    with pytest.raises(CheckpointError, match="Git LFS pointer") as caught:
        legacy.load_checkpoint_state(pointer, spec)
    assert caught.value.code == "T2L_ASSET_LFS_POINTER"
    assert calls == 0


def test_hash_mismatch_is_rejected_before_model_or_deserialization(tmp_path, monkeypatch):
    spec = load_legacy_v1_profile().checkpoints["MTL"]
    corrupt = tmp_path / "checkpoint_MTL"
    corrupt.write_bytes(b"not a trusted checkpoint")
    calls = 0

    def forbidden_load(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("torch.load must follow hash validation")

    monkeypatch.setattr(legacy.torch, "load", forbidden_load)

    with pytest.raises(CheckpointError) as caught:
        legacy.load_checkpoint_state(corrupt, spec)
    assert caught.value.code == "T2L_ASSET_HASH_MISMATCH"
    assert calls == 0


def test_non_manifest_checkpoint_is_never_deserialized(tmp_path, monkeypatch):
    unknown = tmp_path / "unknown.pkl"
    unknown.write_bytes(b"pickle-like bytes")
    calls = 0

    def forbidden_load(*args, **kwargs):
        nonlocal calls
        calls += 1

    monkeypatch.setattr(legacy.torch, "load", forbidden_load)

    with pytest.raises(CheckpointError) as caught:
        legacy.load_checkpoint_state(unknown, None)
    assert caught.value.code == "T2L_CHECKPOINT_NOT_ALLOWLISTED"
    assert calls == 0


def test_ast_016_checkpoint_snapshot_survives_replacement_and_in_place_races(
    tmp_path, monkeypatch
):
    """AST-016: torch.load consumes the immutable bytes that passed verification."""

    original_load = legacy.torch.load
    trusted_state = {
        "weight": legacy.torch.tensor([[1.0, 2.0]]),
        "bias": legacy.torch.tensor([3.0]),
    }

    for mutation in ("replace", "overwrite"):
        checkpoint = tmp_path / f"checkpoint-{mutation}"
        legacy.torch.save({"model_state_dict": trusted_state}, checkpoint)
        trusted_bytes = checkpoint.read_bytes()
        base_spec = load_legacy_v1_profile().checkpoints["Baseline"]
        spec = replace(
            base_spec,
            logical_name=f"fixture-{mutation}",
            sha256=hashlib.sha256(trusted_bytes).hexdigest(),
            size_bytes=len(trusted_bytes),
            state_dict_key_count=len(trusted_state),
            state_dict_signature_sha256=legacy.state_dict_signature(trusted_state),
        )

        def racing_load(
            source,
            *args,
            _mutation=mutation,
            _checkpoint=checkpoint,
            **kwargs,
        ):
            assert not isinstance(source, (str, Path))
            if _mutation == "replace":
                replacement = _checkpoint.with_suffix(".replacement")
                replacement.write_bytes(b"untrusted replacement")
                replacement.replace(_checkpoint)
            else:
                _checkpoint.write_bytes(b"untrusted overwrite")
            return original_load(source, *args, **kwargs)

        monkeypatch.setattr(legacy.torch, "load", racing_load)
        loaded = legacy.load_checkpoint_state(checkpoint, spec)

        assert checkpoint.read_bytes().startswith(b"untrusted")
        assert legacy.state_dict_signature(loaded) == spec.state_dict_signature_sha256


@pytest.mark.parametrize(
    ("mutation", "expected_code", "detail_key"),
    [
        ("missing", "T2L_CHECKPOINT_MISSING_KEYS", "missing_keys"),
        ("unexpected", "T2L_CHECKPOINT_UNEXPECTED_KEYS", "unexpected_keys"),
        ("shape", "T2L_CHECKPOINT_SHAPE_MISMATCH", "shape_mismatches"),
    ],
)
def test_strict_load_diagnoses_key_and_shape_drift(mutation, expected_code, detail_key):
    model = legacy.torch.nn.Linear(2, 1)
    state = dict(model.state_dict())
    if mutation == "missing":
        del state["bias"]
    elif mutation == "unexpected":
        state["extra"] = legacy.torch.zeros(1)
    else:
        state["weight"] = legacy.torch.zeros((1, 3))

    with pytest.raises(CheckpointError) as caught:
        legacy.strict_load_model_state(model, state, logical_name="fixture")

    assert caught.value.code == expected_code
    assert detail_key in caught.value.details


def test_model_state_loading_explicitly_uses_strict_true():
    class RecordingLinear(legacy.torch.nn.Linear):
        strict_value = None

        def load_state_dict(self, state_dict, strict=True, assign=False):
            self.strict_value = strict
            return super().load_state_dict(state_dict, strict=strict, assign=assign)

    model = RecordingLinear(2, 1)
    legacy.strict_load_model_state(
        model, dict(model.state_dict()), logical_name="fixture"
    )

    assert model.strict_value is True
