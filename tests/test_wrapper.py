import numpy as np
import torch
from torch import nn

from t2l.mtl import wrapper


class RecordingTransform(nn.Module):
    def __init__(self):
        super().__init__()
        self.waveform = None

    def forward(self, waveform):
        self.waveform = waveform.detach().cpu().clone()
        return torch.zeros((waveform.shape[0], 128, 9), device=waveform.device)


class FakeAcousticModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.inference_mode = False

    def forward(self, features):
        self.inference_mode = torch.is_inference_mode_enabled()
        return torch.zeros((1, 3, 41), device=features.device)


class FakeBoundaryModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.inference_mode = False

    def forward(self, features):
        self.inference_mode = torch.is_inference_mode_enabled()
        return torch.full((1, 3), 0.5, device=features.device)


def test_align_uses_left_channel_and_inference_mode(monkeypatch, capsys):
    transform = RecordingTransform()
    acoustic_model = FakeAcousticModel()
    audio = torch.stack((torch.arange(2304), torch.arange(2304) + 10000)).float()
    captured = {}

    def fake_alignment(song_pred, lyrics, idx):
        captured["shape"] = song_pred.shape
        return [[0, 1]], 0.0

    monkeypatch.setattr(wrapper, "train_audio_transforms", transform)
    monkeypatch.setattr(wrapper.utils, "alignment", fake_alignment)

    word_align, _ = wrapper.align(
        audio,
        ["word"],
        ["AA"],
        np.array([[0, 0]]),
        np.array([[0, 0]]),
        method=(acoustic_model, None, "Baseline", False, "cpu"),
        verbose=False,
    )

    assert word_align == [[0, 1]]
    assert torch.equal(transform.waveform, audio[:1])
    assert acoustic_model.inference_mode
    assert captured["shape"] == (3, 41)
    assert capsys.readouterr().out == ""


def test_align_uses_full_model_output_for_frame_count(monkeypatch):
    transform = RecordingTransform()
    acoustic_model = FakeAcousticModel()
    captured = {}

    def fake_alignment(song_pred, lyrics, idx):
        captured["shape"] = song_pred.shape
        return [[0, 1]], 0.0

    monkeypatch.setattr(wrapper, "train_audio_transforms", transform)
    monkeypatch.setattr(wrapper.utils, "alignment", fake_alignment)

    wrapper.align(
        torch.zeros((1, 1280)),
        ["word"],
        ["AA"],
        np.array([[0, 0]]),
        np.array([[0, 0]]),
        method=(acoustic_model, None, "Baseline", False, "cpu"),
        verbose=False,
    )

    assert captured["shape"] == (3, 41)


def test_align_converts_numpy_audio_to_float32(monkeypatch):
    transform = RecordingTransform()
    acoustic_model = FakeAcousticModel()

    monkeypatch.setattr(wrapper, "train_audio_transforms", transform)
    monkeypatch.setattr(
        wrapper.utils,
        "alignment",
        lambda *args, **kwargs: ([[0, 1]], 0.0),
    )

    wrapper.align(
        np.zeros((1, 2304)),
        ["word"],
        ["AA"],
        np.array([[0, 0]]),
        np.array([[0, 0]]),
        method=(acoustic_model, None, "Baseline", False, "cpu"),
        verbose=False,
    )

    assert transform.waveform.dtype == torch.float32


def test_bdr_alignment_receives_cpu_numpy_predictions(monkeypatch):
    transform = RecordingTransform()
    acoustic_model = FakeAcousticModel()
    boundary_model = FakeBoundaryModel()
    captured = {}

    def fake_alignment_bdr(song_pred, lyrics, idx, bdr_pred, line_start):
        captured["song_pred"] = song_pred
        captured["bdr_pred"] = bdr_pred
        return [[0, 1]], 0.0

    monkeypatch.setattr(wrapper, "train_audio_transforms", transform)
    monkeypatch.setattr(wrapper.utils, "alignment_bdr", fake_alignment_bdr)

    wrapper.align(
        torch.zeros((1, 2304)),
        ["word"],
        ["AA"],
        np.array([[0, 0]]),
        np.array([[0, 0]]),
        method=(acoustic_model, boundary_model, "Baseline", True, "cpu"),
        verbose=False,
    )

    assert boundary_model.inference_mode
    assert isinstance(captured["song_pred"], np.ndarray)
    assert isinstance(captured["bdr_pred"], np.ndarray)


def test_align_accepts_one_dimensional_audio(monkeypatch):
    transform = RecordingTransform()
    acoustic_model = FakeAcousticModel()

    monkeypatch.setattr(wrapper, "train_audio_transforms", transform)
    monkeypatch.setattr(
        wrapper.utils,
        "alignment",
        lambda *args, **kwargs: ([[0, 1]], 0.0),
    )

    wrapper.align(
        torch.arange(2304).float(),
        ["word"],
        ["AA"],
        np.array([[0, 0]]),
        np.array([[0, 0]]),
        method=(acoustic_model, None, "Baseline", False, "cpu"),
        verbose=False,
    )

    assert transform.waveform.shape == (1, 2304)


def test_align_rejects_empty_or_invalid_audio_dimensions():
    model = FakeAcousticModel()
    method = (model, None, "Baseline", False, "cpu")

    for audio in (torch.zeros((0, 10)), torch.zeros((1, 0)), torch.zeros((1, 2, 3))):
        try:
            wrapper.align(
                audio, [], ["AA"], np.array([[0, 0]]), np.array([[0, 0]]),
                method=method, verbose=False,
            )
        except ValueError as error:
            assert "audio" in str(error).lower()
        else:
            raise AssertionError("invalid audio shape was accepted")
