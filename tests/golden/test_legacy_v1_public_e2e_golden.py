"""Canonical real-decoder public Python API and installed CLI golden tests."""

from __future__ import annotations

import os

import pytest
from legacy_v1_feature_case import CANONICAL_ENVIRONMENT_VARIABLE, environment_mismatches
from legacy_v1_public_e2e_case import (
    ROUTES,
    build_public_e2e_candidate,
    load_public_e2e_oracle,
)

pytestmark = pytest.mark.golden


@pytest.fixture(scope="module")
def public_e2e_oracle() -> dict:
    oracle = load_public_e2e_oracle()
    assert oracle["schema_version"] == 1
    assert oracle["status"] == "canonical"
    assert oracle["scope"] == "real-decoder-public-api-installed-cli"
    if os.environ.get(CANONICAL_ENVIRONMENT_VARIABLE) != "1":
        pytest.skip(
            "canonical oracle runs only through scripts/run_canonical_legacy_v1_golden.sh"
        )
    assert environment_mismatches() == []
    candidates = [build_public_e2e_candidate() for _ in range(3)]
    assert candidates == [oracle, oracle, oracle]
    return oracle


def _route(oracle: dict, name: str) -> dict:
    return oracle["routes"][name]


def test_gol_001_real_mp3_baseline_public_api_is_exact(public_e2e_oracle: dict) -> None:
    """GOL-001: Baseline freezes the real decode, phones, tensors, frames and LRC."""

    route = _route(public_e2e_oracle, "Baseline")
    api = route["python_api"]
    assert api["lyrics_plan"]["tokens"] == [
        {"line_index": 0, "text": "a", "token_index": 0}
    ]
    assert api["lyrics_plan"]["phones"] == ["AH"]
    assert api["features"]["shape"] == [1, 1, 128, 28]
    assert api["posterior"]["shape"] == [9, 41]
    assert api["boundary"] is None
    assert api["result"]["status"] == "complete"
    assert api["result"]["lrc"] == "[00:00.069]a"


def test_gol_002_real_mp3_mtl_public_api_is_exact(public_e2e_oracle: dict) -> None:
    """GOL-002: default MTL freezes the same real public pipeline."""

    route = _route(public_e2e_oracle, "MTL")
    api = route["python_api"]
    assert api["request"]["acoustic_model"] == "MTL"
    assert api["features"]["shape"] == [1, 1, 128, 28]
    assert api["posterior"]["shape"] == [9, 41]
    assert api["boundary"] is None
    assert api["result"]["status"] == "complete"


def test_gol_003_real_mp3_mtl_bdr_public_api_is_exact(public_e2e_oracle: dict) -> None:
    """GOL-003: MTL_BDR freezes its real boundary curve and public result."""

    route = _route(public_e2e_oracle, "MTL_BDR")
    api = route["python_api"]
    assert api["posterior"]["shape"] == [9, 41]
    assert api["boundary"]["shape"] == [9]
    assert route["boundary_checkpoint_sha256"] is not None
    assert api["result"]["status"] == "complete"


def test_gol_007_real_mp3_decode_is_pinned_and_offline(public_e2e_oracle: dict) -> None:
    """GOL-007: canonical MP3 bytes decode exactly with no network or Demucs."""

    assert public_e2e_oracle["input"]["encoded_sha256"] == (
        "55bfeaa909966bef5f8c74ab9e01ac13d2b4e8b17d41bf07ccc44536df250ab8"
    )
    assert public_e2e_oracle["decoder"] == {
        "dispatcher_available_backends": ["soundfile"],
        "effective_backend": "soundfile (only available dispatcher backend)",
        "libsndfile_version": "1.2.0",
        "policy": "torchaudio",
        "soundfile_version": "0.12.1",
        "torchaudio_version": "2.1.2+cpu",
    }
    decoded = _route(public_e2e_oracle, "Baseline")["python_api"]["decoded_audio"]
    assert decoded["sample_rate"] == 22_050
    assert decoded["shape"] == [1, 6912]
    assert decoded["raw_little_endian_f32_sha256"] == (
        "7fd29c3be04ae2bda8f86ad5eae90d46235b7e09e19d0d767aaf4f2772be0367"
    )
    assert decoded["metadata"] == {
        "channel_policy": "preserve",
        "decoder": "torchaudio",
        "separated_vocals": False,
    }
    assert public_e2e_oracle["demucs"]["modules_after"] == []
    assert all(
        not route["installed_cli"]["network_attempted"]
        for route in public_e2e_oracle["routes"].values()
    )


def test_gol_008_installed_cli_is_cwd_independent(public_e2e_oracle: dict) -> None:
    """GOL-008: installed CLI stdout is byte-exact outside the repository."""

    assert public_e2e_oracle["cwd_independence"] == {
        "route": "MTL",
        "repository_root_stdout_sha256": public_e2e_oracle["cwd_independence"][
            "outside_repository_stdout_sha256"
        ],
        "outside_repository_stdout_sha256": public_e2e_oracle["cwd_independence"][
            "outside_repository_stdout_sha256"
        ],
        "exactly_equal": True,
    }


def test_gol_011_real_mp3_baseline_bdr_public_route_is_exact(
    public_e2e_oracle: dict,
) -> None:
    """GOL-011: Baseline_BDR traverses both checkpoints through public API/CLI."""

    route = _route(public_e2e_oracle, "Baseline_BDR")
    api = route["python_api"]
    cli = route["installed_cli"]
    api_word = route["python_api_word"]
    cli_word = route["installed_cli_word"]
    assert route["model_name"] == "Baseline"
    assert route["boundary_checkpoint_sha256"] is not None
    assert api["boundary"]["shape"] == [9]
    assert api["result"]["spans"] == [
        {
            "frame_span": [2, 8],
            "line_index": 0,
            "text": "a",
            "token_index": 0,
        }
    ]
    assert api["result"]["lrc"] == "[00:00.069]a"
    assert cli["exit_code"] == 0
    assert cli["stdout"] == "[00:00.069]a\n"
    assert cli["stderr"] == ""
    assert api_word["request"]["timestamp_mode"] == "word"
    assert api_word["result"]["spans"] == api["result"]["spans"]
    assert api_word["result"]["lrc"] == "[00:00.069]<00:00.069>a"
    assert cli_word["exit_code"] == 0
    assert cli_word["stdout"] == "[00:00.069]<00:00.069>a\n"
    assert cli_word["stderr"] == ""
    assert cli_word["t2l_imported_from_installed_site_packages"] is True


def test_gol_012_all_real_public_routes_match_installed_cli(
    public_e2e_oracle: dict,
) -> None:
    """GOL-012: every real public model route matches the installed CLI bytes."""

    assert set(public_e2e_oracle["routes"]) == set(ROUTES)
    for route in public_e2e_oracle["routes"].values():
        api = route["python_api"]
        cli = route["installed_cli"]
        assert api["result"]["status"] == "complete"
        assert cli["stdout"] == f"{api['result']['lrc']}\n"
        assert cli["stdout_sha256"] == _sha256(cli["stdout"])
        assert cli["exit_code"] == 0
        assert cli["stderr"] == ""
        assert cli["t2l_imported_from_installed_site_packages"] is True
        assert cli["t2l_import_origin"] == (
            "/workspace/.venv/lib/python3.10/site-packages/t2l/__init__.py"
        )


def _sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
