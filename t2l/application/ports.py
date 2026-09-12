"""Coarse-grained dependency ports used by the alignment application service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from ..contracts import (
    AcousticModel,
    AlignmentOutcome,
    AlignmentStatus,
    AudioBuffer,
    DecoderPolicy,
    DevicePolicy,
    LyricsPlan,
    Timebase,
    TimestampMode,
    TokenAlignment,
    VocalSeparationOptions,
)

ProgressStage = Literal[
    "lyrics_read",
    "runtime_create",
    "alignment",
    "output",
    "error",
]
ProgressStatus = Literal["started", "completed", "failed"]
ProgressTarget = Literal["stdout", "file"]


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """Stable, data-minimal progress event shared by application consumers."""

    stage: ProgressStage
    status: ProgressStatus
    result: AlignmentStatus | None = None
    target: ProgressTarget | None = None
    code: str | None = None


@runtime_checkable
class ProgressObserverPort(Protocol):
    def emit(self, event: ProgressEvent) -> None:
        """Observe one structured stage event without changing its meaning."""


class NullProgressObserver:
    """Default observer for side-effect-free Python API execution."""

    def emit(self, event: ProgressEvent) -> None:
        del event


@runtime_checkable
class LyricsPreparationPort(Protocol):
    def prepare(self, lyrics: tuple[str, ...]) -> LyricsPlan:
        """Parse and encode already-decoded lyric lines."""


@runtime_checkable
class AudioPreparationPort(Protocol):
    def prepare(
        self,
        audio_path: Path,
        *,
        vocal_separation: VocalSeparationOptions | None,
        decoder: DecoderPolicy,
    ) -> AudioBuffer:
        """Decode audio under an explicit decoder/separation policy."""


@runtime_checkable
class InferencePort(Protocol):
    def align(
        self,
        lyrics: LyricsPlan,
        audio: AudioBuffer,
        *,
        acoustic_model: AcousticModel,
        device: DevicePolicy,
        seed: int,
        max_alignment_bytes: int,
    ) -> AlignmentOutcome:
        """Return frame spans without deciding complete versus partial."""


@runtime_checkable
class LrcRendererPort(Protocol):
    def render(
        self,
        lyrics: LyricsPlan,
        spans: tuple[TokenAlignment, ...],
        *,
        timestamp_mode: TimestampMode,
        timebase: Timebase,
    ) -> str:
        """Render already-validated spans into newline-free LRC text."""


__all__ = [
    "AudioPreparationPort",
    "InferencePort",
    "LrcRendererPort",
    "LyricsPreparationPort",
    "NullProgressObserver",
    "ProgressEvent",
    "ProgressObserverPort",
    "ProgressStage",
    "ProgressStatus",
    "ProgressTarget",
]
