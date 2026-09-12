"""Stable public error types for the v2 API.

The error hierarchy deliberately records *where* a known failure happened.  It
does not attempt to translate arbitrary backend exceptions: adapters may wrap
known boundary failures and preserve their original cause, while unexpected
exceptions continue to propagate unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal


class T2LError(Exception):
    """Base class for known v2 failures with machine-readable metadata."""

    default_code = "T2L_ERROR"
    default_stage = "unknown"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        stage: str | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or self.default_code
        self.stage = stage or self.default_stage
        self.details = MappingProxyType(dict(details or {}))
        if cause is not None:
            self.__cause__ = cause


class ConfigurationError(T2LError):
    default_code = "T2L_CONFIG_INVALID"
    default_stage = "configuration"


class LyricsInputError(T2LError):
    default_code = "T2L_LYRICS_INVALID"
    default_stage = "lyrics"


class AudioDecodeError(T2LError):
    default_code = "T2L_AUDIO_DECODE_FAILED"
    default_stage = "audio_decode"


class SourceSeparationError(T2LError):
    default_code = "T2L_VOCALS_FAILED"
    default_stage = "source_separation"


class AssetNotFoundError(T2LError):
    default_code = "T2L_ASSET_NOT_FOUND"
    default_stage = "asset_resolution"


class CheckpointError(T2LError):
    default_code = "T2L_MODEL_LOAD_FAILED"
    default_stage = "model_load"


class ModelRuntimeError(T2LError):
    default_code = "T2L_MODEL_RUNTIME_FAILED"
    default_stage = "model_inference"


class AlignmentInputError(T2LError):
    default_code = "T2L_ALIGNMENT_INVALID"
    default_stage = "alignment"


class IncompleteAlignmentError(T2LError):
    default_code = "T2L_ALIGNMENT_PARTIAL"
    default_stage = "alignment"


class OutputWriteError(T2LError):
    default_code = "T2L_OUTPUT_WRITE_FAILED"
    default_stage = "output"


CausePolicy = Literal["optional-preserved", "propagate-unchanged"]
SafeMessagePolicy = Literal["redact", "generic"]


@dataclass(frozen=True, slots=True)
class ErrorRegistration:
    """One stable error's complete public and CLI behavior contract."""

    code: str
    exception_type: type[BaseException]
    stage: str
    required_details: tuple[str, ...]
    cause_policy: CausePolicy
    cli_exit_code: int
    safe_message_policy: SafeMessagePolicy

    def __post_init__(self) -> None:
        if not self.code.startswith("T2L_") or self.code != self.code.upper():
            raise ValueError(f"invalid stable error code: {self.code!r}")
        if not issubclass(self.exception_type, BaseException):
            raise TypeError("exception_type must derive from BaseException")
        if not self.stage:
            raise ValueError("error stage must not be empty")
        if len(set(self.required_details)) != len(self.required_details):
            raise ValueError(f"duplicate required detail for {self.code}")
        if not 1 <= self.cli_exit_code <= 255:
            raise ValueError(f"invalid CLI exit code for {self.code}")


def _registration(
    code: str,
    exception_type: type[BaseException],
    stage: str,
    cli_exit_code: int,
    *,
    required_details: tuple[str, ...] = (),
    cause_policy: CausePolicy = "optional-preserved",
    safe_message_policy: SafeMessagePolicy = "redact",
) -> ErrorRegistration:
    return ErrorRegistration(
        code=code,
        exception_type=exception_type,
        stage=stage,
        required_details=required_details,
        cause_policy=cause_policy,
        cli_exit_code=cli_exit_code,
        safe_message_policy=safe_message_policy,
    )


_ERROR_REGISTRATIONS = (
    _registration("T2L_ERROR", T2LError, "unknown", 1),
    _registration("T2L_CONFIG_INVALID", ConfigurationError, "configuration", 2),
    _registration(
        "T2L_ASSET_ROOT_INVALID",
        ConfigurationError,
        "configuration",
        2,
        required_details=("source",),
    ),
    _registration("T2L_LYRICS_INVALID", LyricsInputError, "lyrics", 4),
    _registration(
        "T2L_G2P_ASSET_MISSING",
        LyricsInputError,
        "lyrics",
        4,
        required_details=("resources",),
    ),
    _registration("T2L_AUDIO_DECODE_FAILED", AudioDecodeError, "audio_decode", 5),
    _registration(
        "T2L_AUDIO_SHAPE_INVALID",
        AudioDecodeError,
        "audio_decode",
        5,
        required_details=("path", "shape"),
    ),
    _registration(
        "T2L_AUDIO_EMPTY",
        AudioDecodeError,
        "audio_decode",
        5,
        required_details=("path", "shape"),
    ),
    _registration(
        "T2L_AUDIO_NONFINITE",
        AudioDecodeError,
        "audio_decode",
        5,
        required_details=("path", "shape"),
    ),
    _registration("T2L_VOCALS_FAILED", SourceSeparationError, "source_separation", 5),
    _registration(
        "T2L_VOCALS_DEPENDENCY_MISSING",
        SourceSeparationError,
        "source_separation",
        5,
        required_details=("extra",),
    ),
    _registration(
        "T2L_ASSET_NOT_FOUND", AssetNotFoundError, "asset_resolution", 6
    ),
    _registration(
        "T2L_ASSET_PATH_ESCAPE",
        CheckpointError,
        "asset_resolution",
        6,
        required_details=("logical_name", "root"),
    ),
    _registration(
        "T2L_ASSET_SIZE_MISMATCH", CheckpointError, "asset_resolution", 6
    ),
    _registration(
        "T2L_ASSET_HASH_MISMATCH", CheckpointError, "asset_resolution", 6
    ),
    _registration(
        "T2L_ASSET_LFS_POINTER", CheckpointError, "asset_resolution", 6
    ),
    _registration(
        "T2L_ASSET_SYMLINK_REJECTED",
        CheckpointError,
        "asset_resolution",
        6,
        required_details=("logical_name", "path"),
    ),
    _registration(
        "T2L_ASSET_CHANGED_DURING_READ",
        CheckpointError,
        "asset_resolution",
        6,
        required_details=("logical_name", "path"),
    ),
    _registration("T2L_ASSET_READ_FAILED", CheckpointError, "asset_resolution", 6),
    _registration(
        "T2L_ASSET_MANIFEST_INVALID",
        CheckpointError,
        "asset_resolution",
        6,
        required_details=("profile",),
    ),
    _registration(
        "T2L_G2P_ASSET_LAYOUT_INVALID",
        CheckpointError,
        "asset_resolution",
        6,
        required_details=("logical_names",),
    ),
    _registration("T2L_MODEL_LOAD_FAILED", CheckpointError, "model_load", 6),
    _registration("T2L_CHECKPOINT_STATE_INVALID", CheckpointError, "model_load", 6),
    _registration(
        "T2L_CHECKPOINT_NOT_ALLOWLISTED", CheckpointError, "model_load", 6
    ),
    _registration(
        "T2L_CHECKPOINT_DESERIALIZE_FAILED", CheckpointError, "model_load", 6
    ),
    _registration(
        "T2L_CHECKPOINT_KEY_COUNT_MISMATCH", CheckpointError, "model_load", 6
    ),
    _registration(
        "T2L_CHECKPOINT_STRUCTURE_MISMATCH", CheckpointError, "model_load", 6
    ),
    _registration(
        "T2L_CHECKPOINT_MISSING_KEYS",
        CheckpointError,
        "model_load",
        6,
        required_details=("logical_name", "missing_keys"),
    ),
    _registration(
        "T2L_CHECKPOINT_UNEXPECTED_KEYS",
        CheckpointError,
        "model_load",
        6,
        required_details=("logical_name", "unexpected_keys"),
    ),
    _registration(
        "T2L_CHECKPOINT_SHAPE_MISMATCH",
        CheckpointError,
        "model_load",
        6,
        required_details=("logical_name", "shape_mismatches"),
    ),
    _registration(
        "T2L_CHECKPOINT_STRICT_LOAD_FAILED", CheckpointError, "model_load", 6
    ),
    _registration(
        "T2L_MODEL_RUNTIME_FAILED", ModelRuntimeError, "model_inference", 6
    ),
    _registration(
        "T2L_MODEL_ARCHITECTURE_INVALID", ModelRuntimeError, "model_inference", 6
    ),
    _registration(
        "T2L_MODEL_DEVICE_UNAVAILABLE", ModelRuntimeError, "model_inference", 6
    ),
    _registration(
        "T2L_MODEL_AUDIO_SHAPE_INVALID", ModelRuntimeError, "model_inference", 6
    ),
    _registration(
        "T2L_MODEL_AUDIO_NONFINITE", ModelRuntimeError, "model_inference", 6
    ),
    _registration(
        "T2L_MODEL_PROFILE_UNKNOWN", ModelRuntimeError, "model_inference", 6
    ),
    _registration(
        "T2L_MODEL_OUTPUT_SHAPE_MISMATCH",
        ModelRuntimeError,
        "model_inference",
        6,
    ),
    _registration(
        "T2L_MODEL_DEVICE_MISMATCH", ModelRuntimeError, "model_inference", 6
    ),
    _registration(
        "T2L_MODEL_SAMPLE_RATE_MISMATCH", ModelRuntimeError, "model_inference", 6
    ),
    _registration("T2L_ALIGNMENT_INVALID", AlignmentInputError, "alignment", 7),
    _registration(
        "T2L_MODEL_INPUT_CONTRACT_INVALID", AlignmentInputError, "alignment", 7
    ),
    _registration(
        "T2L_ALIGNMENT_MEMORY_LIMIT",
        AlignmentInputError,
        "alignment",
        7,
        required_details=("estimated", "limit"),
    ),
    _registration(
        "T2L_ALIGNMENT_PARTIAL",
        IncompleteAlignmentError,
        "alignment",
        7,
        required_details=("expected", "aligned", "first_gap"),
    ),
    _registration(
        "T2L_OUTPUT_WRITE_FAILED",
        OutputWriteError,
        "output",
        8,
        required_details=("path",),
    ),
    _registration(
        "T2L_INTERNAL_ERROR",
        Exception,
        "internal",
        1,
        cause_policy="propagate-unchanged",
        safe_message_policy="generic",
    ),
)


def _build_registry() -> Mapping[str, ErrorRegistration]:
    registrations: dict[str, ErrorRegistration] = {}
    for registration in _ERROR_REGISTRATIONS:
        if registration.code in registrations:
            raise RuntimeError(
                f"duplicate stable error registration: {registration.code}"
            )
        registrations[registration.code] = registration
    return MappingProxyType(registrations)


ERROR_REGISTRY = _build_registry()
DIAGNOSTIC_CODES = frozenset({"T2L_UNKNOWN_PHONE"})


def registration_for(error: T2LError) -> ErrorRegistration:
    """Resolve a known error, falling back closed for unregistered/mismatched values."""

    registration = ERROR_REGISTRY.get(error.code)
    if (
        registration is None
        or not isinstance(error, registration.exception_type)
        or error.stage != registration.stage
    ):
        return ERROR_REGISTRY[T2LError.default_code]
    return registration


def create_registered_error(
    code: str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
    cause: BaseException | None = None,
) -> T2LError:
    """Construct a registered domain error without duplicating type/stage routing."""

    stable_code = code if code.startswith("T2L_") else f"T2L_{code}"
    try:
        registration = ERROR_REGISTRY[stable_code]
    except KeyError as error:
        raise ValueError(f"unregistered stable error code: {stable_code}") from error
    if not issubclass(registration.exception_type, T2LError):
        raise ValueError(f"{stable_code} is not a constructible domain error")
    return registration.exception_type(
        message,
        code=registration.code,
        stage=registration.stage,
        details=details,
        cause=cause,
    )


__all__ = [
    "DIAGNOSTIC_CODES",
    "ERROR_REGISTRY",
    "AlignmentInputError",
    "AssetNotFoundError",
    "AudioDecodeError",
    "CausePolicy",
    "CheckpointError",
    "ConfigurationError",
    "ErrorRegistration",
    "IncompleteAlignmentError",
    "LyricsInputError",
    "ModelRuntimeError",
    "OutputWriteError",
    "SafeMessagePolicy",
    "SourceSeparationError",
    "T2LError",
    "create_registered_error",
    "registration_for",
]
