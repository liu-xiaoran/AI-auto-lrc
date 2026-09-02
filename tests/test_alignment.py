import numpy as np
import pytest
import torch

from t2l.mtl import utils


def test_alignment_rejects_two_frames_for_one_phoneme():
    song_pred = torch.zeros((2, 41))

    with pytest.raises(utils.AlignmentValueError, match=r"1 phonemes.*2 audio frames.*3"):
        utils.alignment(song_pred, ["AA"], np.array([[0, 1]]))


def test_alignment_rejects_lyrics_longer_than_available_path():
    song_pred = torch.zeros((4, 41))

    with pytest.raises(utils.AlignmentValueError, match=r"3 phonemes.*4 audio frames.*5"):
        utils.alignment(song_pred, ["AA", "B", "K"], np.array([[0, 2]]))


def test_alignment_bdr_rejects_short_boundary_prediction():
    song_pred = torch.zeros((3, 41))

    with pytest.raises(utils.AlignmentValueError, match="Boundary prediction"):
        utils.alignment_bdr(
            song_pred,
            ["AA"],
            np.array([[0, 1]]),
            torch.zeros(2),
            np.array([0]),
        )


def test_alignment_rejects_empty_word_indices():
    with pytest.raises(utils.AlignmentValueError, match="non-empty"):
        utils.alignment(
            torch.zeros((3, 41)),
            ["AA"],
            np.empty((0, 2), dtype=int),
        )


def test_alignment_rejects_unordered_or_overlapping_word_indices():
    song_pred = torch.zeros((5, 41))
    lyrics = ["AA", "B", "K"]

    invalid_indices = (
        np.array([[1, 2], [0, 1]]),
        np.array([[0, 2], [1, 3]]),
    )
    for idx in invalid_indices:
        with pytest.raises(utils.AlignmentValueError, match="ordered and non-overlapping"):
            utils.alignment(song_pred, lyrics, idx)


def test_alignment_rejects_invalid_posterior_shape():
    for song_pred in (torch.zeros(3), torch.zeros((3, 40))):
        with pytest.raises(utils.AlignmentValueError, match="at least 41 classes"):
            utils.alignment(
                song_pred,
                ["AA"],
                np.array([[0, 1]]),
            )


def test_generated_half_open_word_indices_are_accepted(monkeypatch):
    monkeypatch.setattr(utils, "g2p", lambda word: ["AA"])
    lyrics, _, word_indices, _ = utils.gen_phone_gt_opt(
        [["hello"], ["world"]]
    )
    song_pred = torch.full((len(lyrics) + 2, 41), -10.0)
    song_pred[:, 40] = -1.0
    song_pred[1, 0] = 0.0
    song_pred[3, 0] = 0.0

    word_align, _ = utils.alignment(song_pred, lyrics, word_indices)

    assert word_indices.tolist() == [[0, 1], [2, 3]]
    assert len(word_align) == 2


def test_generated_half_open_word_indices_are_accepted_by_bdr(monkeypatch):
    monkeypatch.setattr(utils, "g2p", lambda word: ["AA"])
    lyrics, _, word_indices, line_indices = utils.gen_phone_gt_opt(
        [["hello"], ["world"]]
    )
    frame_count = len(lyrics) + 2
    song_pred = np.full((frame_count, 41), -10.0)
    song_pred[:, 40] = -1.0
    song_pred[1, 0] = 0.0
    song_pred[3, 0] = 0.0

    word_align, _ = utils.alignment_bdr(
        song_pred,
        lyrics,
        word_indices,
        np.zeros(frame_count),
        line_indices[:, 0],
    )

    assert word_indices.tolist() == [[0, 1], [2, 3]]
    assert len(word_align) == 2


def test_alignment_minimum_valid_input_is_quiet(capsys):
    song_pred = torch.full((3, 41), -10.0)
    song_pred[:, 40] = -1.0
    song_pred[1, 0] = 0.0

    word_align, _ = utils.alignment(
        song_pred, ["AA"], np.array([[0, 1]])
    )

    assert word_align == [[1, 2]]
    assert capsys.readouterr().out == ""
