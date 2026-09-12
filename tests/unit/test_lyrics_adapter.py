import numpy as np
import pytest

from t2l.adapters.lyrics import LegacyV1LyricsAdapter
from t2l.errors import LyricsInputError


def _phone_encoder(phonetics):
    assert phonetics == [["hello", "world"]]
    return (
        ["HH", " ", "W"],
        [["HH"], ["W"]],
        np.array([[0, 1], [2, 3]]),
        np.array([[0, 3]]),
    )


def test_prepare_cleans_tags_and_builds_tokens():
    adapter = LegacyV1LyricsAdapter(
        phonetizer=lambda line: [(word, word) for word in line.split()],
        phone_encoder=_phone_encoder,
    )

    plan = adapter.prepare(("[00:01.000] hello world",))

    assert [(t.token_index, t.line_index, t.text) for t in plan.tokens] == [
        (0, 0, "hello"),
        (1, 0, "world"),
    ]
    assert plan.payload.lines == (("hello", "world"),)
    assert plan.payload.phones == ("HH", " ", "W")
    assert plan.payload.word_spans == ((0, 1), (2, 3))
    assert plan.payload.line_spans == ((0, 3),)


def test_prepare_keeps_legacy_greedy_metadata_behavior():
    seen = []
    adapter = LegacyV1LyricsAdapter(
        phonetizer=lambda line: seen.append(line) or [(line, line)],
        phone_encoder=lambda _: (
            ["AA"], [["AA"]], np.array([[0, 1]]), np.array([[0, 1]])
        ),
    )

    adapter.prepare(("[ar:first][ti:second]actual",))

    assert seen == ["actual"]


def test_prepare_rejects_lyrics_without_alignable_tokens():
    adapter = LegacyV1LyricsAdapter(
        phonetizer=lambda _: [],
        phone_encoder=lambda _: (_ for _ in ()).throw(
            AssertionError("phone encoding must not run")
        ),
    )

    with pytest.raises(LyricsInputError) as exc_info:
        adapter.prepare(("[ar:only metadata]", "   "))

    assert exc_info.value.code == "T2L_LYRICS_INVALID"
    assert exc_info.value.stage == "lyrics"


def test_prepare_records_unknown_phones_without_changing_them():
    adapter = LegacyV1LyricsAdapter(
        phonetizer=lambda line: [(line, "mystery")],
        phone_encoder=lambda _: (
            ["NOT_A_PHONE"],
            [["NOT_A_PHONE"]],
            np.array([[0, 1]]),
            np.array([[0, 1]]),
        ),
    )

    plan = adapter.prepare(("mystery",))

    assert plan.payload.phones == ("NOT_A_PHONE",)
    assert plan.diagnostics[0].code == "T2L_UNKNOWN_PHONE"
    assert plan.diagnostics[0].details == {"count": 1}

