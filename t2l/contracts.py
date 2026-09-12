"""Dependency-free value objects shared by the v2 API and its adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from .errors import AlignmentInputError, ConfigurationError

TimestampMode = Literal["line", "word"]
AcousticModel = Literal["Baseline", "MTL", "Baseline_BDR", "MTL_BDR"]
AlignmentStatus = Literal["complete", "partial"]
DevicePolicy = Literal["auto", "cpu", "cuda"]
DecoderPolicy = Literal["torchaudio", "librosa-mono"]

_TIMESTAMP_MODES = frozenset(("line", "word"))
_ACOUSTIC_MODELS = frozenset(("Baseline", "MTL", "Baseline_BDR", "MTL_BDR"))
_DEVICES = frozenset(("auto", "cpu", "cuda"))
_DECODERS = frozenset(("torchaudio", "librosa-mono"))
_DEMUCS_MODELS = frozenset(("mdx", "mdx_extra", "mdx_q", "mdx_extra_q"))


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class VocalSeparationOptions:
    demucs_model: str = "mdx_extra"
    demucs_index: int = -1

    def __post_init__(self) -> None:
        if self.demucs_model not in _DEMUCS_MODELS:
            raise ConfigurationError(
                f"Invalid demucs_model {self.demucs_model!r}.",
                details={"field": "demucs_model", "value": self.demucs_model},
            )
        if not _is_plain_int(self.demucs_index) or not -1 <= self.demucs_index <= 3:
            raise ConfigurationError(
                f"Invalid demucs_index {self.demucs_index!r}; expected -1 through 3.",
                details={"field": "demucs_index", "value": self.demucs_index},
            )


@dataclass(frozen=True, slots=True)
class AlignmentRequest:
    lyrics: tuple[str, ...]
    audio_path: Path
    timestamp_mode: TimestampMode = "line"
    acoustic_model: AcousticModel = "MTL"
    allow_partial: bool = False
    vocal_separation: VocalSeparationOptions | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.lyrics, tuple) or not all(
            isinstance(line, str) for line in self.lyrics
        ):
            raise ConfigurationError(
                "lyrics must be a tuple of decoded strings.",
                details={"field": "lyrics"},
            )
        if not isinstance(self.audio_path, Path):
            raise ConfigurationError(
                "audio_path must be a pathlib.Path.",
                details={"field": "audio_path"},
            )
        if self.timestamp_mode not in _TIMESTAMP_MODES:
            raise ConfigurationError(
                f"Invalid timestamp_mode {self.timestamp_mode!r}.",
                details={"field": "timestamp_mode", "value": self.timestamp_mode},
            )
        if self.acoustic_model not in _ACOUSTIC_MODELS:
            raise ConfigurationError(
                f"Invalid acoustic_model {self.acoustic_model!r}.",
                details={"field": "acoustic_model", "value": self.acoustic_model},
            )
        if not isinstance(self.allow_partial, bool):
            raise ConfigurationError(
                "allow_partial must be a bool.",
                details={"field": "allow_partial", "value": self.allow_partial},
            )
        if self.vocal_separation is not None and not isinstance(
            self.vocal_separation, VocalSeparationOptions
        ):
            raise ConfigurationError(
                "vocal_separation must be VocalSeparationOptions or None.",
                details={"field": "vocal_separation"},
            )


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    asset_root: Path | None = None
    device: DevicePolicy = "auto"
    offline: bool = True
    decoder: DecoderPolicy = "torchaudio"
    seed: int = 0
    max_alignment_bytes: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.asset_root is not None and not isinstance(self.asset_root, Path):
            raise ConfigurationError(
                "asset_root must be a pathlib.Path or None.",
                details={"field": "asset_root"},
            )
        if self.device not in _DEVICES:
            raise ConfigurationError(
                f"Invalid device policy {self.device!r}.",
                details={"field": "device", "value": self.device},
            )
        if not isinstance(self.offline, bool):
            raise ConfigurationError(
                "offline must be a bool.",
                details={"field": "offline", "value": self.offline},
            )
        if self.offline is False:
            raise ConfigurationError(
                "Online runtime mode is not supported.",
                details={"field": "offline", "value": False},
            )
        if self.decoder not in _DECODERS:
            raise ConfigurationError(
                f"Invalid decoder policy {self.decoder!r}.",
                details={"field": "decoder", "value": self.decoder},
            )
        if not _is_plain_int(self.seed) or self.seed < 0:
            raise ConfigurationError(
                "seed must be a non-negative integer.",
                details={"field": "seed", "value": self.seed},
            )
        if not _is_plain_int(self.max_alignment_bytes) or self.max_alignment_bytes <= 0:
            raise ConfigurationError(
                "max_alignment_bytes must be a positive integer.",
                details={
                    "field": "max_alignment_bytes",
                    "value": self.max_alignment_bytes,
                },
            )


@dataclass(frozen=True, slots=True)
class FrameSpan:
    start: int
    end: int

    def __post_init__(self) -> None:
        if not _is_plain_int(self.start) or not _is_plain_int(self.end):
            raise AlignmentInputError(
                "Frame span boundaries must be integers (bool is not accepted).",
                details={"start": self.start, "end": self.end},
            )
        if self.start < 0 or self.end <= self.start:
            raise AlignmentInputError(
                "Frame span must be a non-empty [start, end) range with start >= 0.",
                details={"start": self.start, "end": self.end},
            )


@dataclass(frozen=True, slots=True)
class PhoneSpan:
    start: int
    end: int
    length: int | None = None

    def __post_init__(self) -> None:
        if not _is_plain_int(self.start) or not _is_plain_int(self.end):
            raise AlignmentInputError(
                "Phone span boundaries must be integers (bool is not accepted).",
                details={"start": self.start, "end": self.end},
            )
        if self.start < 0 or self.end <= self.start:
            raise AlignmentInputError(
                "Phone span must be a non-empty [start, end) range with start >= 0.",
                details={"start": self.start, "end": self.end},
            )
        if self.length is not None:
            if not _is_plain_int(self.length) or self.length <= 0:
                raise AlignmentInputError(
                    "Phone span length must be a positive integer.",
                    details={"length": self.length},
                )
            if self.end > self.length:
                raise AlignmentInputError(
                    "Phone span end exceeds its sequence length.",
                    details={
                        "start": self.start,
                        "end": self.end,
                        "length": self.length,
                    },
                )


@dataclass(frozen=True, slots=True)
class LyricsToken:
    token_index: int
    line_index: int
    text: str

    def __post_init__(self) -> None:
        if (
            not _is_plain_int(self.token_index)
            or self.token_index < 0
            or not _is_plain_int(self.line_index)
            or self.line_index < 0
            or not isinstance(self.text, str)
        ):
            raise AlignmentInputError(
                "LyricsToken requires non-negative integer indexes and string text.",
                details={
                    "token_index": self.token_index,
                    "line_index": self.line_index,
                },
            )


@dataclass(frozen=True, slots=True)
class TokenAlignment:
    token_index: int
    line_index: int
    text: str
    frame_span: FrameSpan

    def __post_init__(self) -> None:
        if (
            not _is_plain_int(self.token_index)
            or self.token_index < 0
            or not _is_plain_int(self.line_index)
            or self.line_index < 0
            or not isinstance(self.text, str)
            or not isinstance(self.frame_span, FrameSpan)
        ):
            raise AlignmentInputError(
                "TokenAlignment contains invalid token metadata or frame span.",
                details={
                    "token_index": self.token_index,
                    "line_index": self.line_index,
                },
            )


@dataclass(frozen=True, slots=True)
class Timebase:
    sample_rate: int = 22050
    hop_length: int = 256
    time_pooling: int = 3
    frame_offset: int = 0

    def __post_init__(self) -> None:
        for field_name in ("sample_rate", "hop_length", "time_pooling"):
            value = getattr(self, field_name)
            if not _is_plain_int(value) or value <= 0:
                raise AlignmentInputError(
                    f"{field_name} must be a positive integer.",
                    details={"field": field_name, "value": value},
                )
        if not _is_plain_int(self.frame_offset) or self.frame_offset < 0:
            raise AlignmentInputError(
                "frame_offset must be a non-negative integer.",
                details={"field": "frame_offset", "value": self.frame_offset},
            )

    @property
    def seconds_per_frame(self) -> float:
        return self.hop_length * self.time_pooling / self.sample_rate

    def frame_to_seconds(self, frame: int) -> float:
        if not _is_plain_int(frame) or frame < 0:
            raise AlignmentInputError(
                "frame must be a non-negative integer.", details={"frame": frame}
            )
        return (frame + self.frame_offset) * self.seconds_per_frame


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    stage: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.code, self.stage)):
            raise AlignmentInputError("Diagnostic code and stage must be non-empty strings.")
        if not isinstance(self.message, str):
            raise AlignmentInputError("Diagnostic message must be a string.")
        object.__setattr__(self, "details", _freeze_mapping(self.details))


@dataclass(frozen=True, slots=True)
class LyricsPlan:
    tokens: tuple[LyricsToken, ...]
    payload: object | None = None
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.tokens, tuple) or not all(
            isinstance(token, LyricsToken) for token in self.tokens
        ):
            raise AlignmentInputError("LyricsPlan.tokens must be LyricsToken objects.")
        indexes = tuple(token.token_index for token in self.tokens)
        if indexes != tuple(range(len(self.tokens))):
            raise AlignmentInputError(
                "LyricsPlan token indexes must be a contiguous zero-based sequence.",
                details={"token_indexes": indexes},
            )
        if not isinstance(self.diagnostics, tuple) or not all(
            isinstance(item, Diagnostic) for item in self.diagnostics
        ):
            raise AlignmentInputError("LyricsPlan.diagnostics must be Diagnostic objects.")

    @property
    def expected_token_count(self) -> int:
        return len(self.tokens)


@dataclass(frozen=True, slots=True)
class AudioBuffer:
    """An opaque audio carrier at the application boundary.

    Shape, dtype and finite-value checks belong to the audio adapter, so the
    dependency-free contracts module does not import NumPy or torch.
    """

    samples: object
    sample_rate: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _is_plain_int(self.sample_rate) or self.sample_rate <= 0:
            raise AlignmentInputError(
                "AudioBuffer.sample_rate must be a positive integer.",
                details={"sample_rate": self.sample_rate},
            )
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class AlignmentOutcome:
    spans: tuple[TokenAlignment, ...]
    expected_token_count: int
    diagnostics: tuple[Diagnostic, ...] = ()
    model_profile: str = "legacy-v1"
    timebase: Timebase = field(default_factory=Timebase)

    def __post_init__(self) -> None:
        if not isinstance(self.spans, tuple) or not all(
            isinstance(span, TokenAlignment) for span in self.spans
        ):
            raise AlignmentInputError(
                "AlignmentOutcome.spans must be TokenAlignment objects."
            )
        if not _is_plain_int(self.expected_token_count) or self.expected_token_count < 0:
            raise AlignmentInputError(
                "expected_token_count must be a non-negative integer.",
                details={"expected": self.expected_token_count},
            )
        if not isinstance(self.diagnostics, tuple) or not all(
            isinstance(item, Diagnostic) for item in self.diagnostics
        ):
            raise AlignmentInputError(
                "AlignmentOutcome.diagnostics must be Diagnostic objects."
            )
        if not isinstance(self.model_profile, str) or not self.model_profile:
            raise AlignmentInputError("model_profile must be a non-empty string.")
        if not isinstance(self.timebase, Timebase):
            raise AlignmentInputError("timebase must be a Timebase object.")


def _validate_prefix(spans: tuple[TokenAlignment, ...]) -> None:
    indexes = tuple(span.token_index for span in spans)
    if indexes != tuple(range(len(spans))):
        raise AlignmentInputError(
            "Aligned token indexes must form a contiguous prefix starting at zero.",
            details={"token_indexes": indexes},
        )
    for previous, current in pairwise(spans):
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


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    lrc: str
    status: AlignmentStatus
    spans: tuple[TokenAlignment, ...]
    diagnostics: tuple[Diagnostic, ...]
    model_profile: str
    timebase: Timebase
    expected_token_count: int
    allow_partial: InitVar[bool] = False

    def __post_init__(self, allow_partial: bool) -> None:
        if not isinstance(self.lrc, str):
            raise AlignmentInputError("lrc must be a string.")
        if self.lrc.endswith(("\n", "\r")):
            raise AlignmentInputError("API lrc must not contain a trailing newline.")
        if self.status not in ("complete", "partial"):
            raise AlignmentInputError(
                f"Unknown alignment status {self.status!r}.",
                details={"status": self.status},
            )
        if not isinstance(self.spans, tuple) or not all(
            isinstance(span, TokenAlignment) for span in self.spans
        ):
            raise AlignmentInputError("spans must be TokenAlignment objects.")
        if not isinstance(self.diagnostics, tuple) or not all(
            isinstance(item, Diagnostic) for item in self.diagnostics
        ):
            raise AlignmentInputError("diagnostics must be Diagnostic objects.")
        if not _is_plain_int(self.expected_token_count) or self.expected_token_count < 0:
            raise AlignmentInputError("expected_token_count must be non-negative.")
        if not isinstance(self.timebase, Timebase):
            raise AlignmentInputError("timebase must be a Timebase object.")
        if not isinstance(self.model_profile, str) or not self.model_profile:
            raise AlignmentInputError("model_profile must be a non-empty string.")

        _validate_prefix(self.spans)
        aligned = len(self.spans)
        if self.status == "complete":
            if aligned != self.expected_token_count:
                raise AlignmentInputError(
                    "A complete result requires one span for every expected token.",
                    details={"expected": self.expected_token_count, "aligned": aligned},
                )
            return

        if allow_partial is not True:
            raise AlignmentInputError(
                "A partial result requires explicit allow_partial opt-in."
            )
        if not 0 < aligned < self.expected_token_count:
            raise AlignmentInputError(
                "A partial result requires 0 < aligned < expected.",
                details={"expected": self.expected_token_count, "aligned": aligned},
            )
        required = {
            "expected": self.expected_token_count,
            "aligned": aligned,
            "first_gap": aligned,
        }
        if not any(
            diagnostic.stage == "alignment"
            and all(diagnostic.details.get(key) == value for key, value in required.items())
            for diagnostic in self.diagnostics
        ):
            raise AlignmentInputError(
                "A partial result requires an alignment diagnostic with count and gap details.",
                details=required,
            )

    @property
    def aligned_token_count(self) -> int:
        return len(self.spans)


__all__ = [
    "AcousticModel",
    "AlignmentOutcome",
    "AlignmentRequest",
    "AlignmentResult",
    "AlignmentStatus",
    "AudioBuffer",
    "DecoderPolicy",
    "DevicePolicy",
    "Diagnostic",
    "FrameSpan",
    "LyricsPlan",
    "LyricsToken",
    "PhoneSpan",
    "RuntimeConfig",
    "Timebase",
    "TimestampMode",
    "TokenAlignment",
    "VocalSeparationOptions",
]
