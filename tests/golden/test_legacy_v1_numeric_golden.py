"""Canonical LegacyV1 full-checkpoint differential tests."""

from __future__ import annotations

import os

import pytest
from legacy_v1_feature_case import CANONICAL_ENVIRONMENT_VARIABLE, environment_mismatches
from legacy_v1_numeric_case import ROUTES, build_numeric_candidate, load_numeric_oracle

pytestmark = pytest.mark.golden


@pytest.fixture(scope="module")
def numeric_oracle() -> dict:
    oracle = load_numeric_oracle()
    assert oracle["schema_version"] == 1
    assert oracle["status"] == "canonical"
    assert oracle["scope"] == "checkpoint-numeric-and-rendering"
    if os.environ.get(CANONICAL_ENVIRONMENT_VARIABLE) != "1":
        pytest.skip(
            "canonical oracle runs only through scripts/run_canonical_legacy_v1_golden.sh"
        )
    assert environment_mismatches() == []
    candidates = [build_numeric_candidate() for _ in range(3)]
    assert candidates == [oracle, oracle, oracle]
    return oracle


def test_num_015_frozen_v1_and_v2_match_at_all_numeric_extraction_points(
    numeric_oracle: dict,
) -> None:
    """NUM-015: feature, logits, reduction, posterior and BDR match v1."""

    assert all(
        record["max_abs_diff"] <= record["atol"] and record["exactly_equal"]
        for record in numeric_oracle["tensors"].values()
    )


def test_num_016_tensor_fingerprints_are_stable_and_explicit(
    numeric_oracle: dict,
) -> None:
    """NUM-016: fixed extraction points use explicit shapes/layouts/hashes."""

    assert numeric_oracle["input"]["repeat_count"] == 3
    for record in numeric_oracle["tensors"].values():
        assert record["layout"] == "C-contiguous little-endian float32 raw bytes"
        assert len(record["frozen_v1_sha256"]) == 64
        assert record["frozen_v1_sha256"] == record["v2_sha256"]


def test_gol_011_bdr_route_freezes_frames_and_both_lrc_modes(
    numeric_oracle: dict,
) -> None:
    """Auxiliary tensor-only BDR assertion; public evidence lives in e2e golden."""

    route = numeric_oracle["routes"]["Baseline_BDR"]
    assert route["status"] == "complete"
    assert len(route["word_frame_spans"]) == len(numeric_oracle["input"]["tokens"])
    assert len(route["line_lrc_sha256"]) == 64
    assert len(route["word_lrc_sha256"]) == 64


def test_gol_012_all_four_public_model_routes_are_golden(
    numeric_oracle: dict,
) -> None:
    """Auxiliary tensor-only route assertion; public evidence lives in e2e golden."""

    assert set(numeric_oracle["routes"]) == set(ROUTES)
    for route_name, route in numeric_oracle["routes"].items():
        expected_model = route_name.removesuffix("_BDR")
        assert route["model_name"] == expected_model
        assert (route["boundary_checkpoint_sha256"] is not None) == route_name.endswith(
            "_BDR"
        )
        assert route["status"] == "complete"
