from types import MappingProxyType

import pytest

from t2l.errors import (
    AlignmentInputError,
    AssetNotFoundError,
    AudioDecodeError,
    CheckpointError,
    ConfigurationError,
    IncompleteAlignmentError,
    LyricsInputError,
    ModelRuntimeError,
    OutputWriteError,
    SourceSeparationError,
    T2LError,
)


@pytest.mark.parametrize(
    ("error_type", "code", "stage"),
    [
        (ConfigurationError, "T2L_CONFIG_INVALID", "configuration"),
        (LyricsInputError, "T2L_LYRICS_INVALID", "lyrics"),
        (AudioDecodeError, "T2L_AUDIO_DECODE_FAILED", "audio_decode"),
        (SourceSeparationError, "T2L_VOCALS_FAILED", "source_separation"),
        (AssetNotFoundError, "T2L_ASSET_NOT_FOUND", "asset_resolution"),
        (CheckpointError, "T2L_MODEL_LOAD_FAILED", "model_load"),
        (ModelRuntimeError, "T2L_MODEL_RUNTIME_FAILED", "model_inference"),
        (AlignmentInputError, "T2L_ALIGNMENT_INVALID", "alignment"),
        (IncompleteAlignmentError, "T2L_ALIGNMENT_PARTIAL", "alignment"),
        (OutputWriteError, "T2L_OUTPUT_WRITE_FAILED", "output"),
    ],
)
def test_error_types_expose_stable_code_and_stage(error_type, code, stage):
    error = error_type("safe message", details={"item": "value"})

    assert isinstance(error, T2LError)
    assert error.code == code
    assert error.stage == stage
    assert str(error) == "safe message"
    assert error.details == {"item": "value"}
    assert isinstance(error.details, MappingProxyType)


def test_known_error_preserves_original_cause_identity():
    cause = EOFError("truncated stream")

    error = AudioDecodeError("could not decode", cause=cause)

    assert error.__cause__ is cause


def test_error_details_are_not_mutable_after_construction():
    original = {"expected": 2}
    error = IncompleteAlignmentError("partial", details=original)
    original["expected"] = 99

    assert error.details["expected"] == 2
    with pytest.raises(TypeError):
        error.details["expected"] = 3
