"""Pre-allocation alignment resource gates."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from t2l.adapters import legacy_v1_inference as legacy
from t2l.contracts import AudioBuffer, LyricsPlan, LyricsToken
from t2l.errors import AlignmentInputError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _inputs():
    lyrics = LyricsPlan(
        tokens=(LyricsToken(0, 0, "word"),),
        payload=SimpleNamespace(
            phones=("AA", "B"),
            word_spans=((0, 2),),
            line_spans=((0, 2),),
        ),
    )
    audio = AudioBuffer(torch.zeros((1, 16)), sample_rate=22_050)
    return lyrics, audio


def _runtime(monkeypatch, *, boundary):
    runtime = legacy.LegacyV1Inference(
        asset_root=REPOSITORY_ROOT,
        profile=legacy.load_legacy_v1_profile(),
    )
    posterior = torch.zeros((5, 41), dtype=torch.float32)
    boundary_curve = torch.zeros(5) if boundary else None
    monkeypatch.setattr(
        runtime,
        "predict",
        lambda audio, *, acoustic_model, seed: (posterior, boundary_curve),
    )
    return runtime


def test_res_001_exact_torch_dtw_budget_passes_and_one_byte_less_fails(
    monkeypatch,
):
    """RES-001: budget comparison is exact and precedes torch DP allocation."""

    runtime = _runtime(monkeypatch, boundary=False)
    lyrics, audio = _inputs()
    calls = 0

    def alignment(posterior, phones, spans):
        nonlocal calls
        calls += 1
        return [[1, 2]], 0.0

    monkeypatch.setattr(legacy.legacy_alignment, "alignment", alignment)
    # score matrix: 5*(2*2+2)*4 = 120; option matrix: 5*(2*2+1)*1 = 25
    exact_budget = 145

    outcome = runtime.align(
        lyrics,
        audio,
        acoustic_model="Baseline",
        max_alignment_bytes=exact_budget,
    )
    assert len(outcome.spans) == 1
    assert calls == 1

    with pytest.raises(AlignmentInputError) as caught:
        runtime.align(
            lyrics,
            audio,
            acoustic_model="Baseline",
            max_alignment_bytes=exact_budget - 1,
        )
    assert caught.value.code == "T2L_ALIGNMENT_MEMORY_LIMIT"
    assert caught.value.details == {"estimated": exact_budget, "limit": 144}
    assert calls == 1


def test_res_002_exact_numpy_bdr_budget_rejects_before_dp_allocation(monkeypatch):
    """RES-002: BDR accounts for two float64 DP matrices before allocation."""

    runtime = _runtime(monkeypatch, boundary=True)
    lyrics, audio = _inputs()
    calls = 0

    def alignment_bdr(*args, **kwargs):
        nonlocal calls
        calls += 1
        return [[1, 2]], 0.0

    monkeypatch.setattr(legacy.legacy_alignment, "alignment_bdr", alignment_bdr)
    # BDR allocates score + option as NumPy float64: 5*(2*2+1)*(8+8) = 400.
    exact_budget = 400

    with pytest.raises(AlignmentInputError) as caught:
        runtime.align(
            lyrics,
            audio,
            acoustic_model="Baseline_BDR",
            max_alignment_bytes=exact_budget - 1,
        )
    assert caught.value.code == "T2L_ALIGNMENT_MEMORY_LIMIT"
    assert caught.value.details == {"estimated": exact_budget, "limit": 399}
    assert calls == 0

    outcome = runtime.align(
        lyrics,
        audio,
        acoustic_model="Baseline_BDR",
        max_alignment_bytes=exact_budget,
    )
    assert len(outcome.spans) == 1
    assert calls == 1


def test_alignment_budget_lower_bound_rejects_before_model_and_dp(monkeypatch):
    """An impossible alignment-memory budget fails before costly work."""

    class HugePhoneSequence:
        def __len__(self):
            return 100_000_000

        def __iter__(self):
            raise AssertionError("huge phone sequence must not be materialized")

    lyrics = LyricsPlan(
        tokens=(LyricsToken(0, 0, "word"),),
        payload=SimpleNamespace(
            phones=HugePhoneSequence(),
            word_spans=((0, 1),),
            line_spans=((0, 1),),
        ),
    )
    audio = AudioBuffer(torch.zeros((1, 1)), sample_rate=22_050)
    runtime = legacy.LegacyV1Inference(
        asset_root=REPOSITORY_ROOT,
        profile=legacy.load_legacy_v1_profile(),
    )
    predict_calls = 0
    dp_calls = 0

    def predict(*_args, **_kwargs):
        nonlocal predict_calls
        predict_calls += 1
        raise AssertionError("model inference must not run")

    def allocate_dp(*_args, **_kwargs):
        nonlocal dp_calls
        dp_calls += 1
        raise AssertionError("DP allocation must not run")

    monkeypatch.setattr(runtime, "predict", predict)
    monkeypatch.setattr(legacy.legacy_alignment, "alignment", allocate_dp)
    monkeypatch.setattr(legacy.legacy_alignment, "alignment_bdr", allocate_dp)

    for route in ("Baseline", "Baseline_BDR"):
        with pytest.raises(AlignmentInputError) as caught:
            runtime.align(
                lyrics,
                audio,
                acoustic_model=route,
                max_alignment_bytes=512 * 1024 * 1024,
            )
        assert caught.value.code == "T2L_ALIGNMENT_MEMORY_LIMIT"
        assert caught.value.details["estimated"] > caught.value.details["limit"]

    assert predict_calls == 0
    assert dp_calls == 0
