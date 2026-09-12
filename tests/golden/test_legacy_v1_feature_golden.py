"""Canonical LegacyV1 feature golden and differential checks."""

from __future__ import annotations

import os

import pytest
import torch
from legacy_v1_feature_case import (
    CANONICAL_ENVIRONMENT_VARIABLE,
    build_candidate,
    deterministic_waveform,
    environment_mismatches,
    load_oracle,
    raw_float32_sha256,
    v2_features,
)

pytestmark = pytest.mark.golden


def _load_canonical_oracle() -> dict:
    oracle = load_oracle()
    assert oracle["schema_version"] == 1
    assert oracle["status"] == "canonical"
    assert oracle["scope"] == "feature-only"
    return oracle


def _require_canonical_environment() -> None:
    if os.environ.get(CANONICAL_ENVIRONMENT_VARIABLE) != "1":
        pytest.skip(
            "canonical oracle runs only through scripts/run_canonical_legacy_v1_golden.sh"
        )
    assert environment_mismatches() == []


def test_num_001_canonical_mel_matches_frozen_v1_oracle() -> None:
    """NUM-001: exact Mel bytes come from pinned Linux CPython 3.10 CPU."""

    oracle = _load_canonical_oracle()
    _require_canonical_environment()
    candidates = [build_candidate() for _ in range(3)]
    assert candidates == [oracle, oracle, oracle]


def test_num_002_canonical_mel_uses_only_first_channel() -> None:
    """NUM-002: stereo input is exactly left-channel input, not right/mean."""

    oracle = _load_canonical_oracle()
    _require_canonical_environment()
    waveform = deterministic_waveform()
    stereo = v2_features(waveform)
    left = v2_features(waveform[0])
    right = v2_features(waveform[1])
    mean = v2_features(waveform.mean(axis=0, dtype=waveform.dtype))

    assert torch.equal(stereo, left)
    assert not torch.equal(stereo, right)
    assert not torch.equal(stereo, mean)
    assert raw_float32_sha256(stereo) == oracle["expected"][
        "feature_raw_little_endian_f32_sha256"
    ]
    assert raw_float32_sha256(right) == oracle["expected"][
        "right_channel_feature_raw_little_endian_f32_sha256"
    ]
