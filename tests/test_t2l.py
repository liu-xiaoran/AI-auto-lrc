import numpy as np
import pytest
import torch

from t2l import t2l


def test_process_rejects_unsupported_format_before_audio_work(monkeypatch):
    monkeypatch.setattr(
        t2l,
        "preprocess_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("audio loading should not run")
        ),
    )

    with pytest.raises(ValueError, match="only 'lrc'"):
        t2l.process(["hello"], "song.mp3", format="srt", vocalize=False)


def test_preprocess_audio_falls_back_to_librosa(monkeypatch):
    monkeypatch.setattr(
        t2l.ta,
        "load",
        lambda path: (_ for _ in ()).throw(OSError("unsupported codec")),
    )
    monkeypatch.setattr(
        t2l.librosa,
        "load",
        lambda path, sr, res_type: (np.arange(8, dtype=np.float32), 22050),
    )

    audio, sample_rate = t2l.preprocess_audio("song.xyz", sr=22050)

    assert audio.shape == (1, 8)
    assert sample_rate == 22050


def test_preprocess_audio_reports_both_decoder_failures(monkeypatch):
    monkeypatch.setattr(
        t2l.ta,
        "load",
        lambda path: (_ for _ in ()).throw(RuntimeError("torchaudio failed")),
    )
    monkeypatch.setattr(
        t2l.librosa,
        "load",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("librosa failed")),
    )

    with pytest.raises(t2l.AudioValueError, match="torchaudio and librosa") as exc_info:
        t2l.preprocess_audio("broken.mp3")

    assert isinstance(exc_info.value.__cause__, OSError)


@pytest.mark.parametrize(
    "decoder_error",
    [t2l.audioread.exceptions.DecodeError(), EOFError("truncated stream")],
)
def test_preprocess_audio_wraps_decoder_errors(monkeypatch, decoder_error):
    monkeypatch.setattr(
        t2l.ta,
        "load",
        lambda path: (_ for _ in ()).throw(RuntimeError("torchaudio failed")),
    )
    monkeypatch.setattr(
        t2l.librosa,
        "load",
        lambda *args, **kwargs: (_ for _ in ()).throw(decoder_error),
    )

    with pytest.raises(t2l.AudioValueError, match="torchaudio and librosa"):
        t2l.preprocess_audio("broken.mp3")


def test_separate_vocals_does_not_reclassify_model_errors(monkeypatch):
    monkeypatch.setattr(t2l, "preprocess_audio", lambda path: (torch.zeros((1, 8)), 22050))
    monkeypatch.setattr(
        t2l,
        "__vocalize",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("CUDA out of memory")
        ),
    )

    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        t2l.separate_vocals("song.mp3", verbose=False)


def test_demucs_apply_runs_in_inference_mode(monkeypatch):
    class FakeModel:
        samplerate = 22050
        sources = ["vocals"]

    seen = {}

    def fake_apply(model, batch, device, progress):
        seen["inference_mode"] = torch.is_inference_mode_enabled()
        return torch.zeros((1, 1, 2, batch.shape[-1]))

    monkeypatch.setattr(t2l, "demucs_apply_model", fake_apply)

    vocals, sample_rate = t2l.__vocalize(
        torch.zeros((2, 8)), 22050, 22050, FakeModel(), -1, False
    )

    assert seen["inference_mode"]
    assert vocals.shape == (2, 8)
    assert sample_rate == 22050


def test_process_writes_utf8_output(monkeypatch, tmp_path):
    monkeypatch.setattr(t2l, "phonetize", lambda line: [(line, "hello")])
    monkeypatch.setattr(t2l, "preprocess_audio", lambda *args, **kwargs: (torch.zeros((1, 8)), 22050))
    monkeypatch.setattr(
        t2l.mtl_utils,
        "gen_phone_gt_opt",
        lambda phonetics: (["AA"], [], np.array([[0, 1]]), np.array([[0, 1]])),
    )
    monkeypatch.setattr(
        t2l,
        "align",
        lambda *args, **kwargs: ([[0, 1]], None),
    )
    output = tmp_path / "歌词.lrc"

    result = t2l.process(
        ["你好"],
        "song.mp3",
        out_file=output,
        vocalize=False,
        verbose=False,
    )

    assert output.read_text(encoding="utf-8") == result
