"""Stable application-port boundary evidence."""

from __future__ import annotations

from dataclasses import fields
from io import StringIO
from typing import get_type_hints

from t2l.adapters.cli import _StderrObserver
from t2l.adapters.lyrics import LegacyLyricsPayload, LegacyV1LyricsAdapter
from t2l.application.align_lyrics import AlignLyricsUseCase
from t2l.application.ports import (
    LyricsPreparationPort,
    NullProgressObserver,
    ProgressEvent,
    ProgressObserverPort,
)
from t2l.contracts import LyricsPlan


def test_port_005_lyrics_port_returns_one_self_contained_plan():
    """PORT-005: lyrics preparation returns one plan, never a side tuple."""

    adapter = LegacyV1LyricsAdapter(
        phonetizer=lambda _line: (("hello", "hello"),),
        phone_encoder=lambda _phonetics: (
            ("HH", "AH"),
            (("HH", "AH"),),
            ((0, 2),),
            ((0, 2),),
        ),
    )

    plan = adapter.prepare(("hello",))

    assert get_type_hints(LyricsPreparationPort.prepare)["return"] is LyricsPlan
    assert isinstance(plan, LyricsPlan)
    assert not isinstance(plan, tuple)
    assert isinstance(plan.payload, LegacyLyricsPayload)
    assert plan.payload.phones == ("HH", "AH")
    assert plan.payload.word_spans == ((0, 2),)
    assert plan.payload.line_spans == ((0, 2),)


def test_port_008_null_is_silent_and_cli_serializes_only_stable_events(capsys):
    """PORT-008: API default is null; CLI observer writes structured stderr."""

    use_case = AlignLyricsUseCase(
        lyrics=object(),
        audio=object(),
        inference=object(),
        renderer=object(),
    )
    assert isinstance(use_case._progress, NullProgressObserver)
    assert isinstance(use_case._progress, ProgressObserverPort)
    assert tuple(field.name for field in fields(ProgressEvent)) == (
        "stage",
        "status",
        "result",
        "target",
        "code",
    )

    use_case._progress.emit(
        ProgressEvent(stage="alignment", status="started")
    )
    assert capsys.readouterr() == ("", "")

    stderr = StringIO()
    observer = _StderrObserver(stderr)
    observer.emit(ProgressEvent(stage="alignment", status="started"))
    observer.emit(
        ProgressEvent(
            stage="alignment",
            status="completed",
            result="complete",
        )
    )

    assert stderr.getvalue().splitlines() == [
        "T2L_PROGRESS: stage=alignment status=started",
        "T2L_PROGRESS: stage=alignment status=completed result=complete",
    ]
    assert capsys.readouterr() == ("", "")
