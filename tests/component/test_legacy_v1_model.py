from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from t2l.adapters.legacy_v1_inference import LegacyV1Inference
from t2l.application.ports import InferencePort
from t2l.contracts import AlignmentOutcome, AudioBuffer, LyricsPlan, LyricsToken
from t2l.errors import AlignmentInputError, AssetNotFoundError
from t2l.model_profiles import load_legacy_v1_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.component


@pytest.fixture(scope="module")
def adapter():
    return LegacyV1Inference(
        asset_root=REPOSITORY_ROOT,
        profile=load_legacy_v1_profile(),
        device="cpu",
    )


@pytest.mark.parametrize(
    ("name", "expected_shape", "layers_attr"),
    [
        ("Baseline", (1, 3, 41), "bilstm"),
        ("MTL", (1, 3, 41, 47), "bilstm"),
        ("BDR", (1, 3, 1), "bilstm_layers"),
    ],
)
def test_three_checkpoints_strict_load_and_forward_shape(
    adapter, name, expected_shape, layers_attr
):
    model = adapter.load_model(name)
    layers = getattr(model, layers_attr)

    assert tuple(layer.BiLSTM.batch_first for layer in layers) == (
        True,
        False,
        False,
    )
    with torch.inference_mode():
        output = model(torch.zeros((1, 1, 128, 9), dtype=torch.float32))
    assert tuple(output.shape) == expected_shape
    assert torch.isfinite(output).all()


def test_cpu_predict_runs_all_forwards_in_inference_mode_and_without_grad(monkeypatch, adapter):
    observed = []
    original_forward = torch.nn.Module._call_impl

    def observing_call(module, *args, **kwargs):
        if module.__class__.__name__ in {"AcousticModel", "BoundaryDetection"}:
            observed.append(torch.is_inference_mode_enabled())
        return original_forward(module, *args, **kwargs)

    monkeypatch.setattr(torch.nn.Module, "_call_impl", observing_call)
    posterior, boundary = adapter.predict(
        torch.zeros((1, 2_205), dtype=torch.float32),
        acoustic_model="MTL_BDR",
        seed=0,
    )

    assert observed == [True, True]
    assert posterior.ndim == 2 and posterior.shape[1] == 41
    assert boundary is not None and boundary.ndim == 1
    assert posterior.requires_grad is False
    assert boundary.requires_grad is False
    assert torch.isfinite(posterior).all()
    assert torch.isfinite(boundary).all()


def test_predict_preserves_torch_global_rng_state(adapter):
    before = torch.random.get_rng_state().clone()
    adapter.predict(
        torch.zeros((1, 2_205), dtype=torch.float32),
        acoustic_model="Baseline",
        seed=17,
    )
    after = torch.random.get_rng_state()

    assert torch.equal(after, before)


def _numpy_rng_snapshot():
    algorithm, state, position, has_gaussian, cached_gaussian = np.random.get_state()
    return (
        algorithm,
        state.tobytes(),
        position,
        has_gaussian,
        cached_gaussian,
    )


def _rng_snapshot():
    return _numpy_rng_snapshot(), torch.random.get_rng_state().clone()


def _assert_rng_snapshot_unchanged(before):
    numpy_before, torch_before = before
    assert _numpy_rng_snapshot() == numpy_before
    assert torch.equal(torch.random.get_rng_state(), torch_before)


def test_num_018_success_and_known_failures_preserve_caller_rng(tmp_path, adapter):
    """NUM-018: success, checkpoint failure, and alignment failure preserve RNG."""

    waveform = torch.zeros((1, 2_205), dtype=torch.float32)
    np.random.seed(18)
    torch.manual_seed(18)

    before = _rng_snapshot()
    adapter.predict(waveform, acoustic_model="MTL_BDR", seed=18)
    _assert_rng_snapshot_unchanged(before)

    missing_assets = LegacyV1Inference(
        asset_root=tmp_path,
        profile=load_legacy_v1_profile(),
        device="cpu",
    )
    before = _rng_snapshot()
    with pytest.raises(AssetNotFoundError):
        missing_assets.predict(waveform, acoustic_model="Baseline", seed=18)
    _assert_rng_snapshot_unchanged(before)

    lyrics = LyricsPlan(
        tokens=(LyricsToken(token_index=0, line_index=0, text="a"),),
        payload=SimpleNamespace(
            phones=("AA",),
            word_spans=((0, 1),),
            line_spans=((0, 1),),
        ),
    )
    before = _rng_snapshot()
    with pytest.raises(AlignmentInputError, match="exceeds limit"):
        adapter.align(
            lyrics,
            AudioBuffer(samples=waveform, sample_rate=22_050),
            acoustic_model="MTL",
            device="cpu",
            seed=18,
            max_alignment_bytes=0,
        )
    _assert_rng_snapshot_unchanged(before)


def test_feature_extraction_uses_only_left_channel(adapter):
    left = torch.linspace(-0.25, 0.25, 2_205)
    stereo = torch.stack((left, torch.ones_like(left)))

    stereo_features = adapter.extract_features(stereo)
    left_features = adapter.extract_features(left)
    right_features = adapter.extract_features(stereo[1])

    torch.testing.assert_close(stereo_features, left_features)
    assert not torch.allclose(stereo_features, right_features)


def test_adapter_implements_inference_port_and_returns_contract_outcome(adapter):
    lyrics = LyricsPlan(
        tokens=(LyricsToken(token_index=0, line_index=0, text="a"),),
        payload=SimpleNamespace(
            phones=("AA",),
            word_spans=((0, 1),),
            line_spans=((0, 1),),
        ),
    )
    audio = AudioBuffer(
        samples=torch.zeros((1, 2_205), dtype=torch.float32),
        sample_rate=22_050,
    )

    outcome = adapter.align(
        lyrics,
        audio,
        acoustic_model="Baseline",
        device="auto",
        seed=0,
        max_alignment_bytes=1024 * 1024,
    )

    assert isinstance(adapter, InferencePort)
    assert isinstance(outcome, AlignmentOutcome)
    assert outcome.expected_token_count == 1
    assert len(outcome.spans) == 1
    assert outcome.spans[0].text == "a"
    assert outcome.model_profile == "legacy-v1"
    assert outcome.timebase.seconds_per_frame == pytest.approx(768 / 22_050)
