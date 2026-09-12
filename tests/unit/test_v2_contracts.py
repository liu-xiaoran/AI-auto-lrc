from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from t2l.contracts import (
    AlignmentRequest,
    AlignmentResult,
    Diagnostic,
    FrameSpan,
    PhoneSpan,
    RuntimeConfig,
    Timebase,
    TokenAlignment,
    VocalSeparationOptions,
)
from t2l.errors import AlignmentInputError, ConfigurationError


def _alignment(index: int) -> TokenAlignment:
    return TokenAlignment(
        token_index=index,
        line_index=0,
        text=f"token-{index}",
        frame_span=FrameSpan(index + 1, index + 2),
    )


def _partial_diagnostic(expected: int, aligned: int) -> Diagnostic:
    return Diagnostic(
        code="T2L_ALIGNMENT_PARTIAL",
        stage="alignment",
        message="Alignment returned fewer token spans than expected.",
        details={
            "expected": expected,
            "aligned": aligned,
            "first_gap": aligned,
        },
    )


def test_defaults_are_locked_and_request_is_frozen():
    request = AlignmentRequest(
        lyrics=("hello",),
        audio_path=Path("song.wav"),
    )

    assert request.timestamp_mode == "line"
    assert request.acoustic_model == "MTL"
    assert request.allow_partial is False
    assert request.vocal_separation is None
    with pytest.raises(FrozenInstanceError):
        request.allow_partial = True


def test_runtime_defaults_are_offline_and_deterministic():
    config = RuntimeConfig()

    assert config.asset_root is None
    assert config.device == "auto"
    assert config.offline is True
    assert config.decoder == "torchaudio"
    assert config.seed == 0
    assert config.max_alignment_bytes == 512 * 1024 * 1024


def test_runtime_rejects_online_mode_without_defined_semantics():
    with pytest.raises(ConfigurationError) as exc_info:
        RuntimeConfig(offline=False)

    assert exc_info.value.code == "T2L_CONFIG_INVALID"
    assert exc_info.value.stage == "configuration"
    assert exc_info.value.details == {"field": "offline", "value": False}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"timestamp_mode": "sentence"}, "timestamp_mode"),
        ({"acoustic_model": "unknown"}, "acoustic_model"),
    ],
)
def test_request_rejects_unknown_policies(kwargs, message):
    with pytest.raises(ConfigurationError, match=message):
        AlignmentRequest(
            lyrics=("hello",),
            audio_path=Path("song.wav"),
            **kwargs,
        )


@pytest.mark.parametrize("start,end", [(True, 2), (0.0, 2), (-1, 2), (2, 2), (3, 2)])
def test_frame_span_is_a_strict_nonempty_half_open_integer_range(start, end):
    with pytest.raises(AlignmentInputError):
        FrameSpan(start, end)


def test_phone_span_checks_optional_sequence_bound():
    assert PhoneSpan(0, 2, length=2) == PhoneSpan(0, 2, length=2)
    with pytest.raises(AlignmentInputError, match="length"):
        PhoneSpan(0, 3, length=2)


def test_vocal_separation_defaults_and_validation():
    options = VocalSeparationOptions()

    assert options.demucs_model == "mdx_extra"
    assert options.demucs_index == -1
    with pytest.raises(ConfigurationError):
        VocalSeparationOptions(demucs_index=4)


def test_complete_result_invariants():
    spans = (_alignment(0), _alignment(1))

    result = AlignmentResult(
        lrc="[00:00.034]hello",
        status="complete",
        spans=spans,
        diagnostics=(),
        model_profile="legacy-v1",
        timebase=Timebase(),
        expected_token_count=2,
    )

    assert result.status == "complete"
    assert result.aligned_token_count == result.expected_token_count == 2
    assert result.timebase.seconds_per_frame == pytest.approx(768 / 22050)


def test_complete_result_rejects_missing_span_before_rendering_contract_can_escape():
    with pytest.raises(AlignmentInputError):
        AlignmentResult(
            lrc="incomplete",
            status="complete",
            spans=(_alignment(0),),
            diagnostics=(),
            model_profile="legacy-v1",
            timebase=Timebase(),
            expected_token_count=2,
        )


def test_partial_result_requires_explicit_opt_in():
    kwargs = dict(
        lrc="partial",
        status="partial",
        spans=(_alignment(0),),
        diagnostics=(_partial_diagnostic(2, 1),),
        model_profile="legacy-v1",
        timebase=Timebase(),
        expected_token_count=2,
    )

    with pytest.raises(AlignmentInputError, match="opt-in"):
        AlignmentResult(**kwargs)
    assert AlignmentResult(**kwargs, allow_partial=True).status == "partial"


@pytest.mark.parametrize("spans,expected", [((), 2), ((_alignment(0), _alignment(1)), 2)])
def test_partial_result_never_accepts_zero_or_complete_span_counts(spans, expected):
    with pytest.raises(AlignmentInputError):
        AlignmentResult(
            lrc="partial",
            status="partial",
            spans=spans,
            diagnostics=(_partial_diagnostic(expected, len(spans)),),
            model_profile="legacy-v1",
            timebase=Timebase(),
            expected_token_count=expected,
            allow_partial=True,
        )


def test_api_lrc_has_no_trailing_newline():
    with pytest.raises(AlignmentInputError, match="trailing newline"):
        AlignmentResult(
            lrc="[00:00.000]hello\n",
            status="complete",
            spans=(_alignment(0),),
            diagnostics=(),
            model_profile="legacy-v1",
            timebase=Timebase(),
            expected_token_count=1,
        )


def test_complete_result_rejects_overlapping_frame_spans():
    overlapping = (
        TokenAlignment(0, 0, "a", FrameSpan(1, 3)),
        TokenAlignment(1, 0, "b", FrameSpan(2, 4)),
    )
    with pytest.raises(AlignmentInputError, match="overlap"):
        AlignmentResult(
            lrc="bad",
            status="complete",
            spans=overlapping,
            diagnostics=(),
            model_profile="legacy-v1",
            timebase=Timebase(),
            expected_token_count=2,
        )
