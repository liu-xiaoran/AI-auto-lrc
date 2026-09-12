import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from t2l.adapters.audio import AudioPreparationAdapter
from t2l.contracts import VocalSeparationOptions
from t2l.errors import AudioDecodeError, ConfigurationError, SourceSeparationError


def test_torchaudio_policy_preserves_channels_and_resamples():
    """Explicit torchaudio input is resampled once to 22.05 kHz."""
    calls = []

    def resample(samples, source_rate, target_rate):
        calls.append((source_rate, target_rate))
        return samples[:, ::2]

    adapter = AudioPreparationAdapter(
        torchaudio_loader=lambda _: (torch.arange(16).reshape(2, 8), 44100),
        resampler=resample,
    )

    audio = adapter.prepare(
        Path("song.wav"), vocal_separation=None, decoder="torchaudio"
    )

    assert audio.samples.shape == (2, 4)
    assert audio.samples.dtype == torch.float32
    assert audio.sample_rate == 22050
    assert audio.metadata["decoder"] == "torchaudio"
    assert calls == [(44100, 22050)]


def test_torchaudio_failure_does_not_implicitly_fallback():
    """AUD-005/API-009: decoder failure preserves type, cause, and no fallback."""
    called = False

    def librosa_loader(_):
        nonlocal called
        called = True
        return torch.zeros((1, 8)), 22050

    cause = ImportError("TorchCodec is required")
    adapter = AudioPreparationAdapter(
        torchaudio_loader=lambda _: (_ for _ in ()).throw(cause),
        librosa_loader=librosa_loader,
    )

    with pytest.raises(AudioDecodeError) as exc_info:
        adapter.prepare(
            Path("song.mp3"), vocal_separation=None, decoder="torchaudio"
        )

    assert exc_info.value.__cause__ is cause
    assert exc_info.value.code == "T2L_AUDIO_DECODE_FAILED"
    assert not called


def test_librosa_mono_is_explicit_and_normalizes_rank():
    """AUD-006: librosa mono behavior exists only behind its explicit policy."""
    adapter = AudioPreparationAdapter(
        librosa_loader=lambda _: (torch.arange(8), 22050)
    )

    audio = adapter.prepare(
        Path("song.mp3"), vocal_separation=None, decoder="librosa-mono"
    )

    assert audio.samples.shape == (1, 8)
    assert audio.metadata["decoder"] == "librosa-mono"
    assert audio.metadata["channel_policy"] == "mono"


@pytest.mark.parametrize(
    ("samples", "expected_code"),
    [
        pytest.param(torch.zeros((1, 0)), "T2L_AUDIO_EMPTY", id="AUD-007"),
        pytest.param(
            torch.tensor([[float("nan")]]),
            "T2L_AUDIO_NONFINITE",
            id="AUD-008",
        ),
        pytest.param(
            torch.zeros((1, 2, 3)),
            "T2L_AUDIO_SHAPE_INVALID",
            id="invalid-rank",
        ),
    ],
)
def test_invalid_audio_fails_before_inference(samples, expected_code):
    adapter = AudioPreparationAdapter(
        torchaudio_loader=lambda _: (samples, 22050)
    )

    with pytest.raises(AudioDecodeError) as error:
        adapter.prepare(
            Path("broken.wav"), vocal_separation=None, decoder="torchaudio"
        )

    assert error.value.code == expected_code


def test_missing_demucs_extra_is_a_stable_domain_error():
    """AUD-010: a missing Demucs extra has a dedicated stable error code."""
    cause = ModuleNotFoundError("No module named 'demucs'", name="demucs")
    adapter = AudioPreparationAdapter(
        torchaudio_loader=lambda _: (torch.zeros((1, 8)), 22050),
        separator_factory=lambda: (_ for _ in ()).throw(cause),
    )

    with pytest.raises(SourceSeparationError) as exc_info:
        adapter.prepare(
            Path("song.wav"),
            vocal_separation=VocalSeparationOptions(),
            decoder="torchaudio",
        )

    assert exc_info.value.code == "T2L_VOCALS_DEPENDENCY_MISSING"
    assert exc_info.value.__cause__ is cause


def test_demucs_internal_import_error_is_not_misreported_as_missing_extra():
    cause = ImportError("backend import failed")
    adapter = AudioPreparationAdapter(
        torchaudio_loader=lambda _: (torch.zeros((1, 8)), 22050),
        separator_factory=lambda: (_ for _ in ()).throw(cause),
    )

    with pytest.raises(SourceSeparationError) as exc_info:
        adapter.prepare(
            Path("song.wav"),
            vocal_separation=VocalSeparationOptions(),
            decoder="torchaudio",
        )

    assert exc_info.value.code == "T2L_VOCALS_FAILED"
    assert exc_info.value.__cause__ is cause


def test_demucs_adapter_uses_eval_and_inference_mode(monkeypatch):
    """AUD-013: Demucs runs eval-only on CPU without progress output."""
    observed = {}

    class FakeModel:
        samplerate = 22050
        sources = ("vocals",)

        def to(self, device):
            observed["device"] = device
            return self

        def eval(self):
            observed["eval"] = True
            return self

    def apply_model(model, batch, *, device, progress):
        observed["inference_mode"] = torch.is_inference_mode_enabled()
        observed["progress"] = progress
        return torch.zeros((1, 1, 2, batch.shape[-1]))

    monkeypatch.setitem(
        sys.modules,
        "demucs",
        SimpleNamespace(pretrained=SimpleNamespace(get_model=lambda _: FakeModel())),
    )
    monkeypatch.setitem(
        sys.modules,
        "demucs.apply",
        SimpleNamespace(apply_model=apply_model),
    )
    adapter = AudioPreparationAdapter(
        torchaudio_loader=lambda _: (torch.zeros((1, 8)), 22050)
    )

    audio = adapter.prepare(
        Path("song.wav"),
        vocal_separation=VocalSeparationOptions(),
        decoder="torchaudio",
    )

    assert audio.samples.shape == (2, 8)
    assert observed == {
        "device": "cpu",
        "eval": True,
        "inference_mode": True,
        "progress": False,
    }


def test_aud_011_missing_vocals_fails_before_final_resample(monkeypatch):
    """AUD-011: a missing vocals source fails before output resampling."""

    resample_calls = []

    class FakeModel:
        samplerate = 48_000
        sources = ("drums", "bass")

        def to(self, _device):
            return self

        def eval(self):
            return self

    def resample_frac(samples, source_rate, target_rate):
        resample_calls.append((source_rate, target_rate))
        return samples

    def apply_model(_model, batch, *, device, progress):
        assert device == "cpu"
        assert progress is False
        return torch.zeros((1, 2, 2, batch.shape[-1]))

    monkeypatch.setitem(
        sys.modules,
        "julius",
        SimpleNamespace(resample_frac=resample_frac),
    )
    monkeypatch.setitem(
        sys.modules,
        "demucs",
        SimpleNamespace(pretrained=SimpleNamespace(get_model=lambda _: FakeModel())),
    )
    monkeypatch.setitem(
        sys.modules,
        "demucs.apply",
        SimpleNamespace(apply_model=apply_model),
    )

    adapter = AudioPreparationAdapter(
        torchaudio_loader=lambda _: (torch.zeros((1, 8)), 44_100)
    )

    with pytest.raises(SourceSeparationError, match="vocals source") as exc_info:
        adapter.prepare(
            Path("song.wav"),
            vocal_separation=VocalSeparationOptions(),
            decoder="torchaudio",
        )

    assert exc_info.value.code == "T2L_VOCALS_FAILED"
    assert resample_calls == [(44_100, 48_000)]


def test_aud_012_demucs_bag_index_selection_and_validation(monkeypatch):
    """AUD-012: -1 selects the bag, 0/3 select members, and 4/short bags fail."""

    selected = []

    class FakeModel:
        samplerate = 22_050
        sources = ("vocals",)

        def __init__(self, name):
            self.name = name

        def to(self, _device):
            return self

        def eval(self):
            return self

    class FakeBag(FakeModel):
        def __init__(self, count=4):
            super().__init__("bag")
            self.models = [FakeModel(f"member-{index}") for index in range(count)]

    current_bag = [FakeBag()]

    def apply_model(model, batch, *, device, progress):
        assert device == "cpu"
        assert progress is False
        selected.append(model.name)
        return torch.zeros((1, 1, 2, batch.shape[-1]))

    monkeypatch.setitem(
        sys.modules,
        "demucs",
        SimpleNamespace(
            pretrained=SimpleNamespace(get_model=lambda _: current_bag[0])
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "demucs.apply",
        SimpleNamespace(apply_model=apply_model),
    )
    adapter = AudioPreparationAdapter(
        torchaudio_loader=lambda _: (torch.zeros((1, 8)), 22_050)
    )

    for index in (-1, 0, 3):
        adapter.prepare(
            Path("song.wav"),
            vocal_separation=VocalSeparationOptions(demucs_index=index),
            decoder="torchaudio",
        )

    assert selected == ["bag", "member-0", "member-3"]
    with pytest.raises(ConfigurationError, match="expected -1 through 3"):
        VocalSeparationOptions(demucs_index=4)

    current_bag[0] = FakeBag(count=2)
    with pytest.raises(ConfigurationError, match="outside the available model bag") as error:
        adapter.prepare(
            Path("song.wav"),
            vocal_separation=VocalSeparationOptions(demucs_index=3),
            decoder="torchaudio",
        )
    assert error.value.details == {"index": 3, "available": 2}


def test_demucs_resamples_decoder_rate_to_model_rate_then_to_22050(monkeypatch):
    """Separation receives decoder output before the final 22.05 kHz policy."""

    resample_calls = []

    class FakeModel:
        samplerate = 44_100
        sources = ("vocals",)

        def to(self, _device):
            return self

        def eval(self):
            return self

    def resample_frac(samples, source_rate, target_rate):
        resample_calls.append((source_rate, target_rate))
        return samples

    monkeypatch.setitem(
        sys.modules,
        "julius",
        SimpleNamespace(resample_frac=resample_frac),
    )
    monkeypatch.setitem(
        sys.modules,
        "demucs",
        SimpleNamespace(pretrained=SimpleNamespace(get_model=lambda _: FakeModel())),
    )
    monkeypatch.setitem(
        sys.modules,
        "demucs.apply",
        SimpleNamespace(
            apply_model=lambda _model, batch, **_kwargs: torch.zeros(
                (1, 1, 2, batch.shape[-1])
            )
        ),
    )
    adapter = AudioPreparationAdapter(
        torchaudio_loader=lambda _: (torch.zeros((1, 8)), 48_000)
    )

    audio = adapter.prepare(
        Path("song.wav"),
        vocal_separation=VocalSeparationOptions(),
        decoder="torchaudio",
    )

    assert audio.sample_rate == 22_050
    assert resample_calls == [(48_000, 44_100), (44_100, 22_050)]


def test_aud_009_default_audio_path_never_imports_demucs(monkeypatch):
    """AUD-009: no separation request means no Demucs import or factory call."""

    calls = []
    adapter = AudioPreparationAdapter(
        torchaudio_loader=lambda _: (torch.zeros((1, 8)), 22050),
        separator_factory=lambda: calls.append("separator") or object(),
    )

    audio = adapter.prepare(
        Path("song.wav"), vocal_separation=None, decoder="torchaudio"
    )

    assert audio.metadata["separated_vocals"] is False
    assert calls == []
