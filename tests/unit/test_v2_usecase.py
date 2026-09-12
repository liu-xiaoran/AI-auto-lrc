from inspect import signature
from pathlib import Path

import pytest

from t2l.api import AlignmentRuntime, process
from t2l.application.align_lyrics import AlignLyricsUseCase
from t2l.application.ports import ProgressEvent
from t2l.contracts import (
    AlignmentOutcome,
    AlignmentRequest,
    AudioBuffer,
    Diagnostic,
    FrameSpan,
    LyricsPlan,
    LyricsToken,
    RuntimeConfig,
    Timebase,
    TokenAlignment,
)
from t2l.errors import AlignmentInputError, IncompleteAlignmentError, LyricsInputError


def _token(index: int) -> LyricsToken:
    return LyricsToken(token_index=index, line_index=0, text=f"token-{index}")


def _span(index: int) -> TokenAlignment:
    return TokenAlignment(
        token_index=index,
        line_index=0,
        text=f"token-{index}",
        frame_span=FrameSpan(index + 1, index + 2),
    )


class FakeLyrics:
    def __init__(self, events, *, error=None):
        self.events = events
        self.error = error
        self.calls = 0

    def prepare(self, lyrics):
        self.calls += 1
        self.events.append("lyrics")
        if self.error is not None:
            raise self.error
        return LyricsPlan(tokens=tuple(_token(i) for i, _ in enumerate(lyrics)))


class FakeAudio:
    def __init__(self, events):
        self.events = events
        self.calls = 0

    def prepare(self, audio_path, *, vocal_separation, decoder):
        self.calls += 1
        self.events.append("audio")
        return AudioBuffer(samples=object(), sample_rate=22050)


class FakeInference:
    def __init__(self, events, outcome=None, *, error=None):
        self.events = events
        self.outcome = outcome
        self.error = error
        self.calls = 0

    def align(
        self,
        lyrics,
        audio,
        *,
        acoustic_model,
        device,
        seed,
        max_alignment_bytes,
    ):
        self.calls += 1
        self.events.append("inference")
        if self.error is not None:
            raise self.error
        return self.outcome


class FakeRenderer:
    def __init__(self, events):
        self.events = events
        self.calls = 0

    def render(self, lyrics, spans, *, timestamp_mode, timebase):
        self.calls += 1
        self.events.append("render")
        return "[00:00.034]rendered"


class RecordingPolicy:
    def __init__(self, events):
        self.events = events

    def validate(self, request, lyrics, outcome):
        self.events.append("validate")
        from t2l.application.align_lyrics import CompletenessPolicy

        return CompletenessPolicy().validate(request, lyrics, outcome)


def _outcome(aligned: int, expected: int = 2, *, indices=None) -> AlignmentOutcome:
    indices = tuple(range(aligned)) if indices is None else tuple(indices)
    return AlignmentOutcome(
        spans=tuple(_span(index) for index in indices),
        expected_token_count=expected,
        timebase=Timebase(),
    )


def _request(*, allow_partial=False, lyrics=("a", "b")) -> AlignmentRequest:
    return AlignmentRequest(
        lyrics=lyrics,
        audio_path=Path("song.wav"),
        allow_partial=allow_partial,
    )


def _use_case(
    outcome,
    events=None,
    *,
    lyrics_error=None,
    inference_error=None,
    progress_observer=None,
):
    events = [] if events is None else events
    lyrics = FakeLyrics(events, error=lyrics_error)
    audio = FakeAudio(events)
    inference = FakeInference(events, outcome, error=inference_error)
    renderer = FakeRenderer(events)
    policy = RecordingPolicy(events)
    use_case = AlignLyricsUseCase(
        lyrics=lyrics,
        audio=audio,
        inference=inference,
        renderer=renderer,
        completeness_policy=policy,
        progress_observer=progress_observer,
    )
    return use_case, lyrics, audio, inference, renderer


def test_use_case_stage_order_and_complete_result():
    events = []
    use_case, _, _, _, renderer = _use_case(_outcome(2), events)

    result = use_case.execute(_request())

    assert events == ["lyrics", "audio", "inference", "validate", "render"]
    assert renderer.calls == 1
    assert result.status == "complete"
    assert result.aligned_token_count == result.expected_token_count == 2


def test_use_case_emits_stable_alignment_progress_events():
    emitted = []

    class RecordingObserver:
        def emit(self, event):
            emitted.append(event)

    use_case, *_ = _use_case(
        _outcome(2),
        progress_observer=RecordingObserver(),
    )

    result = use_case.execute(_request())

    assert emitted == [
        ProgressEvent(stage="alignment", status="started"),
        ProgressEvent(
            stage="alignment",
            status="completed",
            result=result.status,
        ),
    ]


def test_failed_use_case_does_not_report_alignment_completed():
    emitted = []

    class RecordingObserver:
        def emit(self, event):
            emitted.append(event)

    use_case, *_ = _use_case(
        _outcome(2),
        lyrics_error=LyricsInputError("fixture failure"),
        progress_observer=RecordingObserver(),
    )

    with pytest.raises(LyricsInputError):
        use_case.execute(_request())

    assert emitted == [ProgressEvent(stage="alignment", status="started")]


def test_strict_request_rejects_partial_before_renderer():
    use_case, _, _, _, renderer = _use_case(_outcome(1))

    with pytest.raises(IncompleteAlignmentError) as exc_info:
        use_case.execute(_request())

    assert renderer.calls == 0
    assert exc_info.value.details == {
        "expected": 2,
        "aligned": 1,
        "first_gap": 1,
    }


def test_explicit_partial_reports_first_gap_and_renders():
    use_case, _, _, _, renderer = _use_case(_outcome(1))

    result = use_case.execute(_request(allow_partial=True))

    assert renderer.calls == 1
    assert result.status == "partial"
    diagnostic = result.diagnostics[-1]
    assert diagnostic.stage == "alignment"
    assert diagnostic.details == {"expected": 2, "aligned": 1, "first_gap": 1}


def test_api_015_diagnostics_from_each_source_appear_exactly_once():
    """API-015: lyrics, inference, and policy diagnostics are not duplicated."""

    events = []
    lyrics_diagnostic = Diagnostic(
        code="T2L_LYRICS_NOTE",
        stage="lyrics",
        message="lyrics fixture",
    )
    inference_diagnostic = Diagnostic(
        code="T2L_INFERENCE_NOTE",
        stage="model_inference",
        message="inference fixture",
    )

    class LyricsWithDiagnostic(FakeLyrics):
        def prepare(self, lyrics):
            plan = super().prepare(lyrics)
            return LyricsPlan(
                tokens=plan.tokens,
                diagnostics=(lyrics_diagnostic,),
            )

    outcome = AlignmentOutcome(
        spans=(_span(0),),
        expected_token_count=2,
        diagnostics=(lyrics_diagnostic, inference_diagnostic),
        timebase=Timebase(),
    )
    use_case = AlignLyricsUseCase(
        lyrics=LyricsWithDiagnostic(events),
        audio=FakeAudio(events),
        inference=FakeInference(events, outcome),
        renderer=FakeRenderer(events),
    )

    result = use_case.execute(_request(allow_partial=True))

    assert tuple(item.code for item in result.diagnostics) == (
        "T2L_LYRICS_NOTE",
        "T2L_INFERENCE_NOTE",
        "T2L_ALIGNMENT_PARTIAL",
    )


def test_allow_partial_does_not_downgrade_zero_spans():
    use_case, _, _, _, renderer = _use_case(_outcome(0))

    with pytest.raises(IncompleteAlignmentError):
        use_case.execute(_request(allow_partial=True))

    assert renderer.calls == 0


def test_allow_partial_does_not_downgrade_extra_spans():
    use_case, _, _, _, renderer = _use_case(_outcome(3, expected=2))

    with pytest.raises(AlignmentInputError, match="more spans"):
        use_case.execute(_request(allow_partial=True))

    assert renderer.calls == 0


def test_allow_partial_does_not_downgrade_non_prefix_spans():
    use_case, _, _, _, renderer = _use_case(_outcome(1, indices=(1,)))

    with pytest.raises(AlignmentInputError, match="contiguous prefix"):
        use_case.execute(_request(allow_partial=True))

    assert renderer.calls == 0


def test_allow_partial_does_not_downgrade_overlapping_frame_spans():
    outcome = AlignmentOutcome(
        spans=(
            TokenAlignment(0, 0, "token-0", FrameSpan(1, 3)),
            TokenAlignment(1, 0, "token-1", FrameSpan(2, 4)),
        ),
        expected_token_count=3,
    )
    use_case, _, _, _, renderer = _use_case(outcome)

    with pytest.raises(AlignmentInputError, match="overlap"):
        use_case.execute(_request(allow_partial=True, lyrics=("a", "b", "c")))

    assert renderer.calls == 0


def test_lyrics_failure_stops_pipeline():
    error = LyricsInputError("empty lyrics")
    use_case, lyrics, audio, inference, renderer = _use_case(
        _outcome(2), lyrics_error=error
    )

    with pytest.raises(LyricsInputError) as exc_info:
        use_case.execute(_request())

    assert exc_info.value is error
    assert lyrics.calls == 1
    assert audio.calls == inference.calls == renderer.calls == 0


def test_unknown_inference_error_is_not_reclassified():
    class BackendCrashed(RuntimeError):
        pass

    error = BackendCrashed("boom")
    use_case, _, _, _, renderer = _use_case(_outcome(2), inference_error=error)

    with pytest.raises(BackendCrashed) as exc_info:
        use_case.execute(_request())

    assert exc_info.value is error
    assert renderer.calls == 0


def test_top_level_api_has_v2_only_signature_and_no_io(tmp_path, monkeypatch, capsys):
    use_case, _, _, _, _ = _use_case(_outcome(2))
    runtime = AlignmentRuntime(config=RuntimeConfig(), use_case=use_case)
    monkeypatch.chdir(tmp_path)
    before = tuple(tmp_path.iterdir())

    result = process(_request(), runtime=runtime)

    assert str(signature(process)) == "(request, *, runtime=None)"
    assert result.status == "complete"
    assert capsys.readouterr() == ("", "")
    assert tuple(tmp_path.iterdir()) == before
