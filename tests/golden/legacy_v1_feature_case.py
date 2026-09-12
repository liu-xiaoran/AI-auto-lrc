"""Shared deterministic case for the LegacyV1 feature golden."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch

CANONICAL_ENVIRONMENT_VARIABLE = "AI_AUTO_LRC_CANONICAL_GOLDEN"
CANONICAL_BASE_IMAGE = (
    "python@sha256:8c97ebedc32fd60935cdf5992e935753e2a0f98231830028050e1e04bd3c13c2"
)
CANONICAL_MACHINE = "x86_64"
CANONICAL_PYTHON = (3, 10)
PINNED_PACKAGES = {
    "numpy": "1.26.3",
    "torch": "2.1.2+cpu",
    "torchaudio": "2.1.2+cpu",
}
PINNED_CPU_WHEELS = {
    "torch": {
        "url": "https://download-r2.pytorch.org/whl/cpu/torch-2.1.2%2Bcpu-cp310-cp310-linux_x86_64.whl",
        "sha256": "bf3ca897f8c7c218dd6c4b1cc5eec57b4f4e71106b0b8120e92f5fdaf4acf6cd",
    },
    "torchaudio": {
        "url": "https://download-r2.pytorch.org/whl/cpu/torchaudio-2.1.2%2Bcpu-cp310-cp310-linux_x86_64.whl",
        "sha256": "a3f8dab87bc638add9d74d5a6c2e647bdd2e4dabc4caf5213c698e0242a9cab9",
    },
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ORACLE_PATH = Path(__file__).with_name("legacy_v1_feature_manifest.json")
SAMPLE_RATE = 22_050
SEED = 0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def raw_float32_sha256(value: np.ndarray | torch.Tensor) -> str:
    if isinstance(value, torch.Tensor):
        value = value.detach().cpu().numpy()
    canonical = np.ascontiguousarray(value, dtype="<f4")
    return hashlib.sha256(canonical.tobytes(order="C")).hexdigest()


def deterministic_waveform() -> np.ndarray:
    """Return exactly one second of non-trivial stereo float32 audio."""

    generator = np.random.Generator(np.random.PCG64(SEED))
    pcm = generator.integers(-32_768, 32_768, size=SAMPLE_RATE, dtype=np.int32)
    left = pcm.astype(np.float32) / np.float32(32_768)
    left[0], left[-1] = np.float32(1.0), np.float32(-1.0)
    right = np.roll(left, 17) * np.float32(-0.5)
    return np.ascontiguousarray(np.stack((left, right)), dtype=np.float32)


def frozen_v1_features(waveform: np.ndarray) -> torch.Tensor:
    """Run the frozen v1 transform and preserve its historical tensor layout."""

    from t2l.mtl.model import train_audio_transforms

    samples = torch.as_tensor(waveform, dtype=torch.float32)[:1]
    with torch.inference_mode():
        transformed = train_audio_transforms.to("cpu")(samples)
        return torch.nn.utils.rnn.pad_sequence(
            transformed, batch_first=True
        ).unsqueeze(1)


def v2_features(waveform: np.ndarray) -> torch.Tensor:
    from t2l.adapters.legacy_v1_inference import LegacyV1Inference

    return LegacyV1Inference(device="cpu").extract_features(waveform)


def environment_mismatches() -> list[str]:
    mismatches: list[str] = []
    if platform.system() != "Linux":
        mismatches.append(f"system is {platform.system()!r}, expected 'Linux'")
    if platform.machine() != CANONICAL_MACHINE:
        mismatches.append(
            f"machine is {platform.machine()!r}, expected {CANONICAL_MACHINE!r}"
        )
    if sys.version_info[:2] != CANONICAL_PYTHON:
        mismatches.append(
            f"Python is {platform.python_version()}, expected {CANONICAL_PYTHON[0]}."
            f"{CANONICAL_PYTHON[1]}.x"
        )
    for package, expected in PINNED_PACKAGES.items():
        actual = importlib.metadata.version(package)
        if actual != expected:
            mismatches.append(f"{package} is {actual!r}, expected {expected!r}")
    if torch.cuda.is_available() or torch.version.cuda is not None:
        mismatches.append(
            "torch must be a CPU-only build with CUDA unavailable and no CUDA build version"
        )
    if torch.get_num_threads() != 1:
        mismatches.append(
            f"torch intra-op threads is {torch.get_num_threads()}, expected 1"
        )
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        if os.environ.get(name) != "1":
            mismatches.append(f"{name} is {os.environ.get(name)!r}, expected '1'")
    return mismatches


def build_candidate() -> dict[str, Any]:
    torch.set_num_threads(1)
    mismatches = environment_mismatches()
    if mismatches:
        raise RuntimeError("non-canonical environment: " + "; ".join(mismatches))

    waveform = deterministic_waveform()
    reference = frozen_v1_features(waveform)
    current = v2_features(waveform)
    left = v2_features(waveform[0])
    right = v2_features(waveform[1])

    if not torch.equal(reference, current):
        raise RuntimeError("v2 features differ from the frozen v1 transform")
    if not torch.equal(current, left):
        raise RuntimeError("v2 stereo features do not equal left-channel features")
    if torch.equal(current, right):
        raise RuntimeError("test waveform does not distinguish left from right channel")
    if current.dtype != torch.float32 or current.device.type != "cpu":
        raise RuntimeError(
            f"unexpected feature dtype/device: {current.dtype}/{current.device.type}"
        )
    if not torch.isfinite(current).all():
        raise RuntimeError("feature tensor contains non-finite values")

    return {
        "schema_version": 1,
        "status": "canonical",
        "case_id": "NUM-001-NUM-002-legacy-v1-feature",
        "oracle_id": "legacy-v1-feature-linux-x86_64-cpython310",
        "scope": "feature-only",
        "generated_from_commit": "db8e714eceb73e88496f0f705a56cd8c571e0278",
        "provenance": {
            "baseline_commit": "db8e714eceb73e88496f0f705a56cd8c571e0278",
            "frozen_source": "t2l/mtl/model.py",
            "frozen_source_sha256": sha256_file(REPOSITORY_ROOT / "t2l/mtl/model.py"),
            "profile_manifest": "t2l/_assets/legacy_v1_manifest.json",
            "profile_manifest_sha256": sha256_file(
                REPOSITORY_ROOT / "t2l/_assets/legacy_v1_manifest.json"
            ),
            "uv_lock_sha256": sha256_file(REPOSITORY_ROOT / "uv.lock"),
        },
        "environment": {
            "base_image": CANONICAL_BASE_IMAGE,
            "system": platform.system(),
            "machine": platform.machine(),
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "packages": {
                package: importlib.metadata.version(package)
                for package in sorted(PINNED_PACKAGES)
            },
            "cpu_wheels": PINNED_CPU_WHEELS,
            "device": "cpu",
            "torch_cuda_version": torch.version.cuda,
            "torch_intraop_threads": torch.get_num_threads(),
            "omp_num_threads": os.environ["OMP_NUM_THREADS"],
            "mkl_num_threads": os.environ["MKL_NUM_THREADS"],
        },
        "case": {
            "seed": SEED,
            "generator": "numpy.random.PCG64",
            "sample_rate": SAMPLE_RATE,
            "duration_samples": SAMPLE_RATE,
            "repeat_count": 3,
            "waveform_shape": list(waveform.shape),
            "waveform_dtype": str(waveform.dtype),
            "waveform_raw_little_endian_f32_sha256": raw_float32_sha256(waveform),
            "rights_source": "repository-generated deterministic synthetic waveform",
            "allowed_uses": ["development", "testing", "redistribution"],
            "decoder": "none",
            "channel_policy": "first",
            "separation": "none",
        },
        "expected": {
            "feature_spec_id": "legacy-v1-mel-22050-128-512-256",
            "serialization": "C-contiguous little-endian float32 raw bytes",
            "feature_shape": list(current.shape),
            "feature_dtype": str(current.detach().cpu().numpy().dtype),
            "feature_device": current.device.type,
            "feature_finite": True,
            "feature_raw_little_endian_f32_sha256": raw_float32_sha256(current),
            "right_channel_feature_raw_little_endian_f32_sha256": raw_float32_sha256(
                right
            ),
            "frozen_v1_and_v2_exactly_equal": True,
            "stereo_and_left_channel_exactly_equal": True,
        },
    }


def load_oracle() -> dict[str, Any]:
    return json.loads(ORACLE_PATH.read_text(encoding="utf-8"))
