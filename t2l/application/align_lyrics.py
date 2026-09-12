"""The v2 align-lyrics application use case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..contracts import (
    AlignmentOutcome,
    AlignmentRequest,
    AlignmentResult,
    AlignmentStatus,
    Diagnostic,
    LyricsPlan,
    RuntimeConfig,
)
from ..errors import (
    AlignmentInputError,
    ConfigurationError,
    IncompleteAlignmentError,
    LyricsInputError,
)
from .ports import (
    AudioPreparationPort,
    InferencePort,
    LrcRendererPort,
    LyricsPreparationPort,
    NullProgressObserver,
    ProgressEvent,
    ProgressObserverPort,
)


@dataclass(frozen=True, slots=True)
class CompletenessDecision:
    status: AlignmentStatus
    diagnostics: tuple[Diagnostic, ...]


class CompletenessPolicyPort(Protocol):
    def validate(
        self,
        request: AlignmentRequest,
        lyrics: LyricsPlan,
        outcome: AlignmentOutcome,
    ) -> CompletenessDecision:
        """Validate outcome integrity and decide complete versus partial."""


def _count_details(expected: int, aligned: int) -> dict[str, int]:
    return {"expected": expected, "aligned": aligned, "first_gap": aligned}


def _merge_diagnostics(
    *groups: tuple[Diagnostic, ...],
) -> tuple[Diagnostic, ...]:
    """Preserve source order while emitting each diagnostic exactly once."""

    merged: list[Diagnostic] = []
    for group in groups:
        for diagnostic in group:
            if diagnostic not in merged:
                merged.append(diagnostic)
    return tuple(merged)


class CompletenessPolicy:
    """Fail-closed completeness policy shared by every rendering path."""

    def validate(
        self,
        request: AlignmentRequest,
        lyrics: LyricsPlan,
        outcome: AlignmentOutcome,
    ) -> CompletenessDecision:
        expected = lyrics.expected_token_count
        declared_expected = outcome.expected_token_count
        aligned = len(outcome.spans)

        if expected == 0:
            raise LyricsInputError(
                "Lyrics preparation produced no alignable tokens.",
                details={"expected": 0},
            )
        if declared_expected != expected:
            raise AlignmentInputError(
                "Inference expected-token count does not match the lyrics plan.",
                details={
                    "lyrics_expected": expected,
                    "inference_expected": declared_expected,
                },
            )
        if aligned > expected:
            raise AlignmentInputError(
                "Inference returned more spans than expected.",
                details={"expected": expected, "aligned": aligned},
            )

        indexes = tuple(span.token_index for span in outcome.spans)
        if indexes != tuple(range(aligned)):
            raise AlignmentInputError(
                "Aligned spans must be a contiguous prefix starting at token zero.",
                details={"token_indexes": indexes},
            )

        for previous, current in zip(
            outcome.spans, outcome.spans[1:], strict=False
        ):
            if current.frame_span.start < previous.frame_span.end:
                raise AlignmentInputError(
                    "Aligned frame spans must be monotonic and must not overlap.",
                    details={
                        "previous_token_index": previous.token_index,
                        "current_token_index": current.token_index,
                        "previous_end": previous.frame_span.end,
                        "current_start": current.frame_span.start,
                    },
                )

        for position, span in enumerate(outcome.spans):
            token = lyrics.tokens[position]
            if span.line_index != token.line_index or span.text != token.text:
                raise AlignmentInputError(
                    "Aligned span metadata does not match its lyrics token.",
                    details={
                        "token_index": position,
                        "expected_line_index": token.line_index,
                        "actual_line_index": span.line_index,
                    },
                )

        if aligned == expected:
            return CompletenessDecision("complete", ())

        details = _count_details(expected, aligned)
        if aligned == 0 or not request.allow_partial:
            raise IncompleteAlignmentError(
                "Alignment returned fewer token spans than expected.",
                details=details,
            )

        diagnostic = Diagnostic(
            code="T2L_ALIGNMENT_PARTIAL",
            stage="alignment",
            message="Alignment returned fewer token spans than expected.",
            details=details,
        )
        return CompletenessDecision(
            "partial",
            (diagnostic,),
        )


class AlignLyricsUseCase:
    """Orchestrate pure contracts through injected infrastructure ports."""

    def __init__(
        self,
        *,
        lyrics: LyricsPreparationPort,
        audio: AudioPreparationPort,
        inference: InferencePort,
        renderer: LrcRendererPort,
        completeness_policy: CompletenessPolicyPort | None = None,
        progress_observer: ProgressObserverPort | None = None,
    ) -> None:
        self._lyrics = lyrics
        self._audio = audio
        self._inference = inference
        self._renderer = renderer
        self._completeness = completeness_policy or CompletenessPolicy()
        self._progress = (
            NullProgressObserver()
            if progress_observer is None
            else progress_observer
        )

    def execute(
        self,
        request: AlignmentRequest,
        config: RuntimeConfig = RuntimeConfig(),
    ) -> AlignmentResult:
        if not isinstance(request, AlignmentRequest):
            raise ConfigurationError("request must be an AlignmentRequest")
        if not isinstance(config, RuntimeConfig):
            raise ConfigurationError("config must be a RuntimeConfig")

        self._progress.emit(ProgressEvent(stage="alignment", status="started"))
        lyrics = self._lyrics.prepare(request.lyrics)
        audio = self._audio.prepare(
            request.audio_path,
            vocal_separation=request.vocal_separation,
            decoder=config.decoder,
        )
        outcome = self._inference.align(
            lyrics,
            audio,
            acoustic_model=request.acoustic_model,
            device=config.device,
            seed=config.seed,
            max_alignment_bytes=config.max_alignment_bytes,
        )
        decision = self._completeness.validate(request, lyrics, outcome)
        lrc = self._renderer.render(
            lyrics,
            outcome.spans,
            timestamp_mode=request.timestamp_mode,
            timebase=outcome.timebase,
        )
        result = AlignmentResult(
            lrc=lrc,
            status=decision.status,
            spans=outcome.spans,
            diagnostics=_merge_diagnostics(
                lyrics.diagnostics,
                outcome.diagnostics,
                decision.diagnostics,
            ),
            model_profile=outcome.model_profile,
            timebase=outcome.timebase,
            expected_token_count=lyrics.expected_token_count,
            allow_partial=request.allow_partial,
        )
        self._progress.emit(
            ProgressEvent(
                stage="alignment",
                status="completed",
                result=result.status,
            )
        )
        return result

    __call__ = execute


__all__ = [
    "AlignLyricsUseCase",
    "CompletenessDecision",
    "CompletenessPolicy",
    "CompletenessPolicyPort",
]
