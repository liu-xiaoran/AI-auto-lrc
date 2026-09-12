"""Real decoder and resampler component evidence."""

from __future__ import annotations

import hashlib
import json
import sys
import wave
from array import array
from pathlib import Path

import pytest
import torch

from t2l.adapters.audio import AudioPreparationAdapter

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "audio"
pytestmark = pytest.mark.component


def _write_pcm16(
    path: Path,
    *,
    sample_rate: int,
    frames: list[tuple[int, ...]],
) -> None:
    channels = len(frames[0])
    assert channels > 0
    assert all(len(frame) == channels for frame in frames)
    payload = array("h", (sample for frame in frames for sample in frame))
    if sys.byteorder != "little":
        payload.byteswap()
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(payload.tobytes())


def test_aud_001_real_mono_pcm16_wav_is_channel_first_float32(tmp_path):
    """AUD-001: real mono WAV decode is finite channel-first float32."""

    source = tmp_path / "mono.wav"
    frames = [(1_000,), (-2_000,), (3_000,), (-4_000,)]
    _write_pcm16(source, sample_rate=22_050, frames=frames)

    result = AudioPreparationAdapter().prepare(
        source,
        vocal_separation=None,
        decoder="torchaudio",
    )

    assert result.sample_rate == 22_050
    assert result.samples.dtype == torch.float32
    assert tuple(result.samples.shape) == (1, len(frames))
    assert torch.isfinite(result.samples).all()
    assert result.metadata == {
        "decoder": "torchaudio",
        "channel_policy": "preserve",
        "separated_vocals": False,
    }
    torch.testing.assert_close(
        result.samples[0],
        torch.tensor([sample[0] / 32_768 for sample in frames]),
        rtol=0,
        atol=1 / 32_768,
    )


def test_aud_002_real_stereo_pcm16_wav_preserves_channel_order(tmp_path):
    """AUD-002: real stereo WAV retains distinct channels in source order."""

    source = tmp_path / "stereo.wav"
    frames = [(1_000, -2_000), (2_000, -1_000), (3_000, 0), (4_000, 1_000)]
    _write_pcm16(source, sample_rate=22_050, frames=frames)

    result = AudioPreparationAdapter().prepare(
        source,
        vocal_separation=None,
        decoder="torchaudio",
    )

    assert result.sample_rate == 22_050
    assert result.samples.dtype == torch.float32
    assert tuple(result.samples.shape) == (2, len(frames))
    assert torch.isfinite(result.samples).all()
    torch.testing.assert_close(
        result.samples[:, 0],
        torch.tensor([1_000 / 32_768, -2_000 / 32_768]),
        rtol=0,
        atol=1 / 32_768,
    )
    assert result.metadata == {
        "decoder": "torchaudio",
        "channel_policy": "preserve",
        "separated_vocals": False,
    }


def test_aud_003_real_44100_wav_resamples_to_exact_half_length(tmp_path):
    """AUD-003: 44.1 kHz input has deterministic 2:1 resampling length."""

    source = tmp_path / "mono-44100.wav"
    frame_count = 4_410
    frames = [((index % 2_000) - 1_000,) for index in range(frame_count)]
    _write_pcm16(source, sample_rate=44_100, frames=frames)

    result = AudioPreparationAdapter().prepare(
        source,
        vocal_separation=None,
        decoder="torchaudio",
    )

    assert result.sample_rate == 22_050
    assert tuple(result.samples.shape) == (1, frame_count // 2)
    assert result.samples.dtype == torch.float32
    assert torch.isfinite(result.samples).all()


def test_aud_004_fixed_real_mp3_uses_torchaudio_without_librosa_fallback():
    """AUD-004: pinned local MP3 decodes through the explicit torchaudio policy."""

    metadata = json.loads(
        (FIXTURE_ROOT / "sine-440hz-250ms-mono-22050.json").read_text("utf-8")
    )
    source = FIXTURE_ROOT / metadata["file"]
    payload = source.read_bytes()
    assert len(payload) == metadata["size_bytes"]
    assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]

    def forbidden_librosa(_path):
        raise AssertionError("explicit torchaudio policy must never fall back to librosa")

    result = AudioPreparationAdapter(librosa_loader=forbidden_librosa).prepare(
        source,
        vocal_separation=None,
        decoder="torchaudio",
    )

    portable = metadata["portable_assertions"]
    assert result.sample_rate == portable["sample_rate"]
    assert tuple(result.samples.shape[:1]) == (portable["channels"],)
    assert portable["minimum_decoded_samples"] <= result.samples.shape[1]
    assert result.samples.shape[1] <= portable["maximum_decoded_samples"]
    assert str(result.samples.dtype) == portable["dtype"]
    assert bool(torch.isfinite(result.samples).all()) is portable["finite"]
    assert result.metadata == {
        "decoder": "torchaudio",
        "channel_policy": "preserve",
        "separated_vocals": False,
    }
