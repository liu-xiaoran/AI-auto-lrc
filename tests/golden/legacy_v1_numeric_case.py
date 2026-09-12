"""Canonical full-checkpoint differential case for LegacyV1 inference."""

from __future__ import annotations

import gc
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from legacy_v1_feature_case import (
    CANONICAL_BASE_IMAGE,
    PINNED_CPU_WHEELS,
    PINNED_PACKAGES,
    REPOSITORY_ROOT,
    SAMPLE_RATE,
    SEED,
    deterministic_waveform,
    environment_mismatches,
    frozen_v1_features,
    raw_float32_sha256,
    sha256_file,
)
from legacy_v1_feature_case import (
    ORACLE_PATH as FEATURE_ORACLE_PATH,
)

from t2l.adapters.legacy_v1_inference import LegacyV1Inference
from t2l.adapters.lyrics import LegacyLyricsPayload
from t2l.contracts import AudioBuffer, FrameSpan, LyricsPlan, LyricsToken, TokenAlignment
from t2l.domain.lrc import LrcRenderer
from t2l.model_profiles import load_legacy_v1_profile
from t2l.mtl import utils as frozen_alignment
from t2l.mtl.model import AcousticModel, BoundaryDetection

NUMERIC_ORACLE_PATH = Path(__file__).with_name("legacy_v1_numeric_manifest.json")
ROUTES = ("Baseline", "MTL", "Baseline_BDR", "MTL_BDR")
RTOL = 1e-5
ATOL = 1e-6


def _lyrics_plan() -> LyricsPlan:
    tokens = (
        LyricsToken(0, 0, "Alpha"),
        LyricsToken(1, 0, " beta"),
        LyricsToken(2, 1, "Gamma"),
    )
    phones = (
        "AA",
        "L",
        "F",
        "AH",
        " ",
        "B",
        "EY",
        "T",
        "AH",
        " ",
        "G",
        "AE",
        "M",
        "AH",
    )
    payload = LegacyLyricsPayload(
        lines=(("Alpha", " beta"), ("Gamma",)),
        phonetics=(("alpha", "beta"), ("gamma",)),
        phones=phones,
        word_spans=((0, 4), (5, 9), (10, 14)),
        line_spans=((0, 9), (10, 14)),
    )
    return LyricsPlan(tokens=tokens, payload=payload)


def _load_frozen_model(logical_name: str) -> torch.nn.Module:
    profile = load_legacy_v1_profile()
    spec = profile.checkpoints[logical_name]
    checkpoint = REPOSITORY_ROOT / spec.relative_path
    if checkpoint.stat().st_size != spec.size_bytes:
        raise RuntimeError(f"{logical_name} checkpoint size differs from manifest")
    if sha256_file(checkpoint) != spec.sha256:
        raise RuntimeError(f"{logical_name} checkpoint hash differs from manifest")

    architecture = profile.architectures[spec.architecture_id]
    output_classes: int | tuple[int, int]
    if len(architecture.output_classes) == 1:
        output_classes = architecture.output_classes[0]
    else:
        output_classes = (
            architecture.output_classes[0],
            architecture.output_classes[1],
        )
    constructor = AcousticModel if architecture.kind == "acoustic" else BoundaryDetection
    with torch.random.fork_rng(devices=[]):
        model = constructor(
            architecture.n_cnn_layers,
            architecture.rnn_dim,
            output_classes,
            architecture.n_feats,
            architecture.stride,
            architecture.dropout,
        )
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(payload["model_state_dict"], strict=True)
    model.eval()
    return model


def _frozen_smoothing(reduced: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    posterior = F.log_softmax(reduced, dim=2).reshape(-1, 41)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(SEED)
        noise = torch.empty_like(posterior).uniform_(1e-11, 1e-10)
    return posterior, torch.log(torch.exp(posterior) + noise)


def _reference_tensors(features: torch.Tensor) -> dict[str, torch.Tensor]:
    tensors: dict[str, torch.Tensor] = {}
    for logical_name in ("Baseline", "MTL", "BDR"):
        model = _load_frozen_model(logical_name)
        with torch.inference_mode():
            raw = model(features).detach().cpu()
        tensors[f"{logical_name.lower()}_raw"] = raw
        del model
        gc.collect()

    baseline_unsmoothed, baseline_posterior = _frozen_smoothing(
        tensors["baseline_raw"]
    )
    mtl_reduced = torch.sum(tensors["mtl_raw"], dim=3)
    mtl_unsmoothed, mtl_posterior = _frozen_smoothing(mtl_reduced)
    tensors.update(
        {
            "baseline_unsmoothed_posterior": baseline_unsmoothed,
            "baseline_posterior": baseline_posterior,
            "mtl_reduced": mtl_reduced,
            "mtl_unsmoothed_posterior": mtl_unsmoothed,
            "mtl_posterior": mtl_posterior,
            "boundary_curve": torch.log(tensors["bdr_raw"].reshape(-1)) * 0.8,
        }
    )
    return tensors


def _v2_tensors(
    adapter: LegacyV1Inference, features: torch.Tensor
) -> dict[str, torch.Tensor]:
    tensors: dict[str, torch.Tensor] = {}
    with torch.inference_mode():
        tensors["baseline_raw"] = adapter.load_model("Baseline")(features).cpu()
        tensors["mtl_raw"] = adapter.load_model("MTL")(features).cpu()
        tensors["bdr_raw"] = adapter.load_model("BDR")(features).cpu()
    tensors["mtl_reduced"] = torch.sum(tensors["mtl_raw"], dim=3)
    tensors["baseline_unsmoothed_posterior"] = F.log_softmax(
        tensors["baseline_raw"], dim=2
    ).reshape(-1, 41)
    tensors["mtl_unsmoothed_posterior"] = F.log_softmax(
        tensors["mtl_reduced"], dim=2
    ).reshape(-1, 41)
    tensors["baseline_posterior"], _ = adapter.predict(
        deterministic_waveform(), acoustic_model="Baseline", seed=SEED
    )
    tensors["mtl_posterior"], _ = adapter.predict(
        deterministic_waveform(), acoustic_model="MTL", seed=SEED
    )
    tensors["boundary_curve"] = torch.log(tensors["bdr_raw"].reshape(-1)) * 0.8
    return tensors


def _tensor_record(reference: torch.Tensor, current: torch.Tensor) -> dict[str, Any]:
    reference = reference.detach().cpu().contiguous()
    current = current.detach().cpu().contiguous()
    if not torch.isfinite(reference).all() or not torch.isfinite(current).all():
        raise RuntimeError("numeric golden tensor contains non-finite values")
    torch.testing.assert_close(current, reference, rtol=RTOL, atol=ATOL)
    if reference.shape != current.shape or reference.dtype != current.dtype:
        raise RuntimeError("v1/v2 tensor metadata differs")
    max_abs_diff = float(torch.max(torch.abs(reference - current)).item())
    return {
        "shape": list(reference.shape),
        "dtype": str(reference.numpy().dtype),
        "layout": "C-contiguous little-endian float32 raw bytes",
        "finite": True,
        "rtol": RTOL,
        "atol": ATOL,
        "max_abs_diff": max_abs_diff,
        "exactly_equal": torch.equal(reference, current),
        "frozen_v1_sha256": raw_float32_sha256(reference),
        "v2_sha256": raw_float32_sha256(current),
    }


def _run_alignment(
    posterior: torch.Tensor,
    boundary: torch.Tensor | None,
    lyrics: LyricsPlan,
) -> tuple[list[list[int]], float]:
    payload = lyrics.payload
    word_spans = np.asarray(payload.word_spans, dtype=np.int64)
    if boundary is None:
        spans, score = frozen_alignment.alignment(
            posterior, payload.phones, word_spans
        )
    else:
        line_starts = np.asarray(payload.line_spans, dtype=np.int64)[:, 0]
        spans, score = frozen_alignment.alignment_bdr(
            posterior.numpy(),
            payload.phones,
            word_spans,
            boundary.numpy(),
            line_starts,
        )
    return [[int(start), int(end)] for start, end in spans], float(score)


def _token_alignments(lyrics: LyricsPlan, spans: list[list[int]]) -> tuple[TokenAlignment, ...]:
    return tuple(
        TokenAlignment(
            token.token_index,
            token.line_index,
            token.text,
            FrameSpan(span[0], span[1]),
        )
        for token, span in zip(lyrics.tokens, spans, strict=True)
    )


def _line_frame_spans(alignments: tuple[TokenAlignment, ...]) -> list[list[int]]:
    line_indexes = sorted({alignment.line_index for alignment in alignments})
    return [
        [
            min(
                alignment.frame_span.start
                for alignment in alignments
                if alignment.line_index == line_index
            ),
            max(
                alignment.frame_span.end
                for alignment in alignments
                if alignment.line_index == line_index
            ),
        ]
        for line_index in line_indexes
    ]


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _frozen_v1_render(
    word_align: list[list[int]],
    lines: tuple[tuple[str, ...], ...],
    *,
    line_only: bool,
) -> str:
    """Execute the baseline commit's ``gen_lrc`` timestamp algorithm."""

    def timestamp(seconds: float) -> str:
        minutes = int(seconds / 60)
        whole_seconds = int(seconds - minutes * 60)
        milliseconds = int(1000 * (seconds - int(seconds)))
        return f"{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"

    result = ""
    index = 0
    resolution = 256 / 22_050 * 3
    for line in lines:
        line_timestamp = f"[{timestamp(word_align[index][0] * resolution)}]"
        line_text = ""
        for text in line:
            if text:
                if not line_only:
                    text = f"<{timestamp(word_align[index][0] * resolution)}>{text}"
                line_text += text
            index += 1
        if line_text:
            line_text = line_timestamp + line_text
        result += line_text + "\n"
    return result[:-1]


def build_numeric_candidate() -> dict[str, Any]:
    torch.set_num_threads(1)
    mismatches = environment_mismatches()
    if mismatches:
        raise RuntimeError("non-canonical environment: " + "; ".join(mismatches))

    feature_oracle = json.loads(FEATURE_ORACLE_PATH.read_text(encoding="utf-8"))
    if feature_oracle["status"] != "canonical":
        raise RuntimeError("feature oracle must be canonical before numeric generation")

    waveform = deterministic_waveform()
    lyrics = _lyrics_plan()
    audio = AudioBuffer(samples=waveform, sample_rate=SAMPLE_RATE)
    reference_features = frozen_v1_features(waveform)
    reference = _reference_tensors(reference_features)

    adapter = LegacyV1Inference(asset_root=REPOSITORY_ROOT, device="cpu")
    current_features = adapter.extract_features(waveform)
    current = _v2_tensors(adapter, current_features)
    tensor_records = {
        "feature": _tensor_record(reference_features, current_features),
        **{
            name: _tensor_record(reference[name], current[name])
            for name in sorted(reference)
        },
    }

    renderer = LrcRenderer()
    route_records: dict[str, Any] = {}
    for route in ROUTES:
        model_name = route.removesuffix("_BDR")
        with_boundary = route.endswith("_BDR")
        reference_posterior = reference[f"{model_name.lower()}_posterior"]
        reference_boundary = reference["boundary_curve"] if with_boundary else None
        frozen_spans, frozen_score = _run_alignment(
            reference_posterior, reference_boundary, lyrics
        )

        v2_posterior, v2_boundary = adapter.predict(
            waveform, acoustic_model=route, seed=SEED
        )
        if (v2_boundary is not None) != with_boundary:
            raise RuntimeError(f"{route} boundary routing differs")
        _tensor_record(reference_posterior, v2_posterior)
        if with_boundary:
            assert reference_boundary is not None and v2_boundary is not None
            _tensor_record(reference_boundary, v2_boundary)
        current_spans, current_score = _run_alignment(
            v2_posterior, v2_boundary, lyrics
        )
        if current_spans != frozen_spans or current_score != frozen_score:
            raise RuntimeError(f"{route} v1/v2 alignment differs")

        outcome = adapter.align(
            lyrics,
            audio,
            acoustic_model=route,
            device="cpu",
            seed=SEED,
        )
        outcome_spans = [
            [alignment.frame_span.start, alignment.frame_span.end]
            for alignment in outcome.spans
        ]
        if outcome_spans != frozen_spans or len(outcome.spans) != len(lyrics.tokens):
            raise RuntimeError(f"{route} did not return the complete frozen frame sequence")

        frozen_line_lrc = _frozen_v1_render(
            frozen_spans,
            lyrics.payload.lines,
            line_only=True,
        )
        frozen_word_lrc = _frozen_v1_render(
            frozen_spans,
            lyrics.payload.lines,
            line_only=False,
        )
        current_line_lrc = renderer.render(
            lyrics,
            outcome.spans,
            timestamp_mode="line",
            timebase=outcome.timebase,
        )
        current_word_lrc = renderer.render(
            lyrics,
            outcome.spans,
            timestamp_mode="word",
            timebase=outcome.timebase,
        )
        if (current_line_lrc, current_word_lrc) != (
            frozen_line_lrc,
            frozen_word_lrc,
        ):
            raise RuntimeError(f"{route} v1/v2 rendering differs")

        route_records[route] = {
            "model_name": model_name,
            "architecture_id": adapter.profile.checkpoints[
                model_name
            ].architecture_id,
            "checkpoint_sha256": adapter.profile.checkpoints[model_name].sha256,
            "boundary_checkpoint_sha256": (
                adapter.profile.checkpoints["BDR"].sha256 if with_boundary else None
            ),
            "posterior_tensor": f"{model_name.lower()}_posterior",
            "boundary_tensor": "boundary_curve" if with_boundary else None,
            "alignment_score": frozen_score,
            "word_frame_spans": frozen_spans,
            "line_frame_spans": _line_frame_spans(outcome.spans),
            "line_lrc": current_line_lrc,
            "line_lrc_sha256": _text_sha256(current_line_lrc),
            "word_lrc": current_word_lrc,
            "word_lrc_sha256": _text_sha256(current_word_lrc),
            "status": "complete",
        }

    profile = adapter.profile
    return {
        "schema_version": 1,
        "status": "canonical",
        "case_id": "NUM-015-NUM-016-GOL-011-GOL-012-legacy-v1-numeric",
        "oracle_id": "legacy-v1-numeric-linux-x86_64-cpython310",
        "scope": "checkpoint-numeric-and-rendering",
        "generated_from_commit": "db8e714eceb73e88496f0f705a56cd8c571e0278",
        "environment": {
            "base_image": CANONICAL_BASE_IMAGE,
            "system": "Linux",
            "machine": "x86_64",
            "python_version": "3.10.21",
            "packages": PINNED_PACKAGES,
            "cpu_wheels": PINNED_CPU_WHEELS,
            "device": "cpu",
            "torch_cuda_version": None,
            "torch_intraop_threads": 1,
            "omp_num_threads": "1",
            "mkl_num_threads": "1",
        },
        "provenance": {
            "provenance_scope": "canonical functional evidence; not clean release provenance",
            "candidate_worktree_state": "dirty",
            "candidate_source_sha256": sha256_file(Path(__file__)),
            "v2_adapter_sha256": sha256_file(
                REPOSITORY_ROOT / "t2l/adapters/legacy_v1_inference.py"
            ),
            "v2_renderer_sha256": sha256_file(REPOSITORY_ROOT / "t2l/domain/lrc.py"),
            "baseline_reference_commit": "db8e714eceb73e88496f0f705a56cd8c571e0278",
            "frozen_wrapper_sha256": "4305db04b815943cf3bb853ffbdeab6b38cf03f3d234fcd3aa11ad9fcbdb433c",
            "frozen_lrc_source_sha256": "571ea2a7294e485311ec63061c22ad277016532d8ee7fa69ac874145a9a37515",
            "frozen_model_sha256": sha256_file(REPOSITORY_ROOT / "t2l/mtl/model.py"),
            "profile_manifest_sha256": sha256_file(
                REPOSITORY_ROOT / "t2l/_assets/legacy_v1_manifest.json"
            ),
            "feature_oracle_sha256": sha256_file(FEATURE_ORACLE_PATH),
            "uv_lock_sha256": sha256_file(REPOSITORY_ROOT / "uv.lock"),
        },
        "input": {
            "audio_sha256": raw_float32_sha256(waveform),
            "audio_encoding": "C-contiguous little-endian float32 raw bytes",
            "waveform_shape": list(waveform.shape),
            "sample_rate": SAMPLE_RATE,
            "seed": SEED,
            "repeat_count": 3,
            "decoder": "none",
            "channel_policy": "first",
            "separation": "none",
            "rights_source": "repository-generated deterministic synthetic waveform",
            "allowed_uses": ["development", "testing", "redistribution"],
            "tokens": [token.text for token in lyrics.tokens],
            "phones": list(lyrics.payload.phones),
            "word_spans": [list(span) for span in lyrics.payload.word_spans],
            "line_spans": [list(span) for span in lyrics.payload.line_spans],
        },
        "profile": {
            "profile_id": profile.profile_id,
            "feature_spec_id": profile.feature.spec_id,
            "phone_inventory_id": profile.phone_inventory_id,
            "frame_clock": [
                profile.frame_clock_numerator,
                profile.frame_clock_denominator,
            ],
            "mtl_reduction": "sum dim=3 before log_softmax",
            "boundary_alpha": 0.8,
            "posterior_rtol": RTOL,
            "posterior_atol": ATOL,
        },
        "tensors": tensor_records,
        "routes": route_records,
    }


def load_numeric_oracle() -> dict[str, Any]:
    return json.loads(NUMERIC_ORACLE_PATH.read_text(encoding="utf-8"))
