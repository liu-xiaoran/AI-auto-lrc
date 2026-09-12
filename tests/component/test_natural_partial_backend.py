"""Evidence for the frozen backend's natural incomplete boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import torch

from t2l.adapters import legacy_v1_inference as legacy
from t2l.application.align_lyrics import CompletenessPolicy
from t2l.contracts import (
    AlignmentRequest,
    AudioBuffer,
    LyricsPlan,
    LyricsToken,
)
from t2l.errors import AlignmentInputError, IncompleteAlignmentError
from t2l.mtl import utils as reference

pytestmark = pytest.mark.component


@dataclass(frozen=True)
class _Payload:
    phones: tuple[str, ...]
    word_spans: tuple[tuple[int, int], ...]
    line_spans: tuple[tuple[int, int], ...]


class _UnusedLocator:
    def resolve(self, spec):
        raise AssertionError("fixed posterior tests must not load checkpoints")


def _adapter(monkeypatch, posterior, boundary=None):
    adapter = legacy.LegacyV1Inference(
        asset_locator=_UnusedLocator(),
        profile=legacy.load_legacy_v1_profile(),
        device="cpu",
    )
    monkeypatch.setattr(
        adapter,
        "predict",
        lambda samples, *, acoustic_model, seed: (posterior, boundary),
    )
    return adapter


def _lyrics(*tokens: str) -> LyricsPlan:
    phones_list: list[str] = []
    for index in range(len(tokens)):
        phones_list.append("AA" if index % 2 == 0 else "B")
        if index < len(tokens) - 1:
            phones_list.append(" ")
    phones = tuple(phones_list)
    word_spans = tuple((2 * index, 2 * index + 1) for index in range(len(tokens)))
    return LyricsPlan(
        tokens=tuple(LyricsToken(index, 0, token) for index, token in enumerate(tokens)),
        payload=_Payload(phones, word_spans, ((0, len(phones)),)),
    )


@pytest.mark.parametrize("with_boundary", (False, True))
def test_reference_backend_forces_the_full_terminal_state(with_boundary):
    """A legal path stays complete even when token evidence is strongly rejected."""

    phones = ("AA", " ", "B")
    word_spans = np.asarray(((0, 1), (2, 3)), dtype=np.int64)
    posterior = np.full((5, 41), -100.0, dtype=np.float64)
    posterior[:, 40] = 0.0
    posterior[:, 0] = -50.0
    posterior[:, 6] = -1000.0

    if with_boundary:
        spans, _ = reference.alignment_bdr(
            posterior,
            phones,
            word_spans,
            np.zeros(5),
            word_spans[:, 0],
        )
    else:
        spans, _ = reference.alignment(
            torch.tensor(posterior), phones, word_spans
        )

    assert spans == [[1, 2], [3, 4]]


def test_aln_021_natural_bdr_backtrack_exhaustion_is_structured(monkeypatch):
    """ALN-021: a fixed finite posterior reaches natural zero-prefix exhaustion."""

    posterior = np.zeros((7, 41), dtype=np.float64)
    boundary = np.zeros(7, dtype=np.float64)
    adapter = _adapter(
        monkeypatch,
        torch.tensor(posterior),
        torch.tensor(boundary),
    )

    with pytest.raises(IncompleteAlignmentError) as exc_info:
        adapter.align(
            _lyrics("only"),
            AudioBuffer(np.zeros((1, 1)), sample_rate=22_050),
            acoustic_model="MTL_BDR",
        )

    assert exc_info.value.code == "T2L_ALIGNMENT_PARTIAL"
    assert exc_info.value.details == {
        "expected": 1,
        "aligned": 0,
        "first_gap": 0,
    }
    assert isinstance(exc_info.value.__cause__, IndexError)


@pytest.mark.parametrize("with_boundary", (False, True))
def test_api_010_unknown_index_error_is_not_misclassified_as_partial(
    monkeypatch,
    with_boundary,
):
    """API-010: an unrelated backend IndexError remains an unknown failure."""

    boundary = torch.zeros(3) if with_boundary else None
    adapter = _adapter(monkeypatch, torch.zeros((3, 41)), boundary)
    failure = IndexError("unrelated reference-backend defect")
    monkeypatch.setattr(
        legacy.legacy_alignment,
        "alignment_bdr" if with_boundary else "alignment",
        lambda posterior, phones, word_spans: (_ for _ in ()).throw(failure),
    )

    if with_boundary:
        monkeypatch.setattr(
            legacy.legacy_alignment,
            "alignment_bdr",
            lambda *args: (_ for _ in ()).throw(failure),
        )

    with pytest.raises(IndexError) as exc_info:
        adapter.align(
            _lyrics("only"),
            AudioBuffer(np.zeros((1, 1)), sample_rate=22_050),
            acoustic_model="MTL_BDR" if with_boundary else "MTL",
        )

    assert exc_info.value is failure


@pytest.mark.parametrize("with_boundary", (False, True))
def test_frozen_alignment_value_error_maps_to_stable_alignment_error(
    monkeypatch,
    with_boundary,
):
    """A shape-valid but too-short posterior is a known code-7 boundary error."""

    boundary = torch.zeros(2) if with_boundary else None
    adapter = _adapter(monkeypatch, torch.zeros((2, 41)), boundary)

    with pytest.raises(AlignmentInputError) as exc_info:
        adapter.align(
            _lyrics("only"),
            AudioBuffer(np.zeros((1, 1)), sample_rate=22_050),
            acoustic_model="MTL_BDR" if with_boundary else "MTL",
        )

    assert exc_info.value.code == "T2L_ALIGNMENT_INVALID"
    assert exc_info.value.stage == "alignment"
    assert exc_info.value.details["backend"] == (
        "bdr" if with_boundary else "dtw"
    )
    assert isinstance(exc_info.value.__cause__, reference.AlignmentValueError)


@pytest.mark.parametrize(
    "raw_spans",
    (
        [[1, 2]],
        [[1, 2], [4, 4]],
    ),
)
def test_adapter_converts_missing_or_zero_length_tail_to_incomplete_prefix(
    monkeypatch,
    raw_spans,
):
    """Boundary normalization is not presented as a natural backend fixture."""

    adapter = _adapter(monkeypatch, torch.zeros((5, 41)))
    monkeypatch.setattr(
        legacy.legacy_alignment,
        "alignment",
        lambda posterior, phones, word_spans: (raw_spans, torch.tensor(0.0)),
    )
    lyrics = _lyrics("first", "second")
    outcome = adapter.align(
        lyrics,
        AudioBuffer(np.zeros((1, 1)), sample_rate=22_050),
    )

    assert [span.token_index for span in outcome.spans] == [0]
    strict = AlignmentRequest(lyrics=("first second",), audio_path=Path("song.wav"))
    with pytest.raises(IncompleteAlignmentError) as exc_info:
        CompletenessPolicy().validate(strict, lyrics, outcome)
    assert exc_info.value.details == {
        "expected": 2,
        "aligned": 1,
        "first_gap": 1,
    }

    partial = AlignmentRequest(
        lyrics=("first second",),
        audio_path=Path("song.wav"),
        allow_partial=True,
    )
    decision = CompletenessPolicy().validate(partial, lyrics, outcome)
    assert decision.status == "partial"
    assert decision.diagnostics[-1].details == {
        "expected": 2,
        "aligned": 1,
        "first_gap": 1,
    }
