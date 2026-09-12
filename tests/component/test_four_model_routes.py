"""Real-checkpoint coverage for all four public LegacyV1 route names."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import torch

from t2l.adapters.legacy_v1_inference import LegacyV1Inference
from t2l.model_profiles import load_legacy_v1_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.component


@pytest.fixture(scope="module")
def adapter() -> LegacyV1Inference:
    return LegacyV1Inference(
        asset_root=REPOSITORY_ROOT,
        profile=load_legacy_v1_profile(),
        device="cpu",
    )


@pytest.fixture(scope="module")
def nontrivial_waveform() -> torch.Tensor:
    sample_count = 2_205
    phase = torch.arange(sample_count, dtype=torch.float32) * (
        2 * math.pi * 440 / 22_050
    )
    return (0.1 * torch.sin(phase)).unsqueeze(0)


@pytest.mark.parametrize(
    ("route", "expects_boundary"),
    (
        pytest.param("Baseline", False, id="baseline"),
        pytest.param("MTL", False, id="mtl"),
        pytest.param("Baseline_BDR", True, id="baseline-bdr"),
        pytest.param("MTL_BDR", True, id="mtl-bdr"),
    ),
)
def test_all_public_routes_use_real_checkpoints_and_are_seed_deterministic(
    adapter: LegacyV1Inference,
    nontrivial_waveform: torch.Tensor,
    route: str,
    expects_boundary: bool,
) -> None:
    """Exercise four real routes; the API/CLI golden remains unqualified."""

    first_posterior, first_boundary = adapter.predict(
        nontrivial_waveform,
        acoustic_model=route,
        seed=0,
    )
    second_posterior, second_boundary = adapter.predict(
        nontrivial_waveform,
        acoustic_model=route,
        seed=0,
    )

    assert first_posterior.ndim == 2
    assert first_posterior.shape[1] == 41
    assert first_posterior.dtype == torch.float32
    assert torch.isfinite(first_posterior).all()
    assert torch.equal(first_posterior, second_posterior)
    if expects_boundary:
        assert first_boundary is not None
        assert second_boundary is not None
        assert tuple(first_boundary.shape) == (first_posterior.shape[0],)
        assert first_boundary.dtype == torch.float32
        assert torch.isfinite(first_boundary).all()
        assert torch.equal(first_boundary, second_boundary)
    else:
        assert first_boundary is None
        assert second_boundary is None
