from t2l.adapters.lyrics import LegacyLyricsPayload
from t2l.contracts import FrameSpan, LyricsPlan, LyricsToken, Timebase, TokenAlignment
from t2l.domain.lrc import LrcRenderer


def _lyrics_plan():
    tokens = (
        LyricsToken(0, 0, "Hello"),
        LyricsToken(1, 0, " world"),
        LyricsToken(2, 1, "Again"),
    )
    return LyricsPlan(
        tokens=tokens,
        payload=LegacyLyricsPayload(
            lines=(("Hello", " world"), ("Again",)),
            phonetics=(("hello", "world"), ("again",)),
            phones=("HH",),
            word_spans=((0, 1),),
            line_spans=((0, 1),),
        ),
    )


def _spans():
    return (
        TokenAlignment(0, 0, "Hello", FrameSpan(0, 1)),
        TokenAlignment(1, 0, " world", FrameSpan(1, 2)),
        TokenAlignment(2, 1, "Again", FrameSpan(1723, 1724)),
    )


def test_line_renderer_uses_first_token_and_has_no_trailing_newline():
    result = LrcRenderer().render(
        _lyrics_plan(), _spans(), timestamp_mode="line", timebase=Timebase()
    )

    assert result == "[00:00.000]Hello world\n[01:00.011]Again"


def test_word_renderer_adds_word_timestamps():
    result = LrcRenderer().render(
        _lyrics_plan(), _spans(), timestamp_mode="word", timebase=Timebase()
    )

    assert result == (
        "[00:00.000]<00:00.000>Hello<00:00.034> world\n"
        "[01:00.011]<01:00.011>Again"
    )


def test_partial_renderer_keeps_missing_text_without_fabricating_timestamp():
    result = LrcRenderer().render(
        _lyrics_plan(), _spans()[:2], timestamp_mode="line", timebase=Timebase()
    )

    assert result == "[00:00.000]Hello world\nAgain"


def test_renderer_supports_minutes_longer_than_two_digits():
    lyrics = LyricsPlan(tokens=(LyricsToken(0, 0, "Long song"),))
    spans = (TokenAlignment(0, 0, "Long song", FrameSpan(172266, 172267)),)

    result = LrcRenderer().render(
        lyrics, spans, timestamp_mode="line", timebase=Timebase()
    )

    assert result == "[100:00.013]Long song"
