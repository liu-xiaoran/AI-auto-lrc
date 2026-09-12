"""Frozen LegacyV1 checkpoint loading and CPU inference adapter.

The adapter is intentionally adjacent to, rather than a rewrite of, the
historic model classes.  Their module names, state-dict keys, tensor shapes,
and unusual LSTM axis semantics are part of the checkpoint contract.
"""

from __future__ import annotations

import hashlib
import io
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
import torchaudio

from t2l.adapters.assets import AssetLocator, AssetSpec
from t2l.contracts import (
    AlignmentOutcome,
    AudioBuffer,
    FrameSpan,
    LyricsPlan,
    Timebase,
    TokenAlignment,
)
from t2l.errors import (
    AlignmentInputError,
    IncompleteAlignmentError,
    T2LError,
    create_registered_error,
)
from t2l.model_profiles import (
    ArchitectureSpec,
    CheckpointSpec,
    LegacyV1Profile,
    load_legacy_v1_profile,
)
from t2l.mtl import utils as legacy_alignment
from t2l.mtl.model import AcousticModel, BoundaryDetection

_LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"


def _failure(
    code: str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> T2LError:
    return create_registered_error(code, message, details=details)


def state_dict_signature(state_dict: Mapping[str, torch.Tensor]) -> str:
    """Return the manifest signature of ordered state keys, shapes, and dtypes."""

    lines = []
    for key, value in state_dict.items():
        if not isinstance(key, str) or not isinstance(value, torch.Tensor):
            raise _failure(
                "CHECKPOINT_STATE_INVALID",
                "model_state_dict must map string keys to tensors",
            )
        lines.append(f"{key}|{tuple(value.shape)}|{value.dtype}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _verified_checkpoint_snapshot(
    path: str | Path, spec: CheckpointSpec | None
) -> tuple[Path, bytes]:
    """Return manifest-verified immutable bytes from one filesystem read."""

    checkpoint = Path(path)
    if spec is None:
        raise _failure(
            "CHECKPOINT_NOT_ALLOWLISTED",
            f"checkpoint {checkpoint.name!r} has no manifest entry",
        )
    try:
        snapshot = checkpoint.read_bytes()
    except FileNotFoundError as exc:
        raise _failure(
            "ASSET_NOT_FOUND",
            f"checkpoint {spec.logical_name!r} was not found at {checkpoint}",
        ) from exc
    except OSError as exc:
        raise _failure(
            "ASSET_READ_FAILED",
            f"checkpoint {spec.logical_name!r} cannot be read: {exc}",
        ) from exc

    if snapshot.startswith(_LFS_POINTER_PREFIX):
        raise _failure(
            "ASSET_LFS_POINTER",
            f"checkpoint {spec.logical_name!r} is a Git LFS pointer; run git lfs pull",
        )
    actual_hash = hashlib.sha256(snapshot).hexdigest()
    if actual_hash != spec.sha256:
        raise _failure(
            "ASSET_HASH_MISMATCH",
            f"checkpoint {spec.logical_name!r} sha256 does not match its manifest",
        )
    actual_size = len(snapshot)
    if actual_size != spec.size_bytes:
        raise _failure(
            "ASSET_SIZE_MISMATCH",
            f"checkpoint {spec.logical_name!r} has size {actual_size}, expected {spec.size_bytes}",
        )
    return checkpoint, snapshot


def validate_checkpoint(path: str | Path, spec: CheckpointSpec | None) -> Path:
    """Validate an allowlisted checkpoint without deserializing it."""

    checkpoint, _snapshot = _verified_checkpoint_snapshot(path, spec)
    return checkpoint


def load_checkpoint_state(
    path: str | Path, spec: CheckpointSpec | None
) -> Mapping[str, torch.Tensor]:
    """Validate and load the exact same immutable checkpoint bytes."""

    _checkpoint, snapshot = _verified_checkpoint_snapshot(path, spec)
    assert spec is not None  # narrowed by _verified_checkpoint_snapshot
    try:
        payload = torch.load(io.BytesIO(snapshot), map_location="cpu", weights_only=True)
    except Exception as exc:
        raise _failure(
            "CHECKPOINT_DESERIALIZE_FAILED",
            f"checkpoint {spec.logical_name!r} could not be read as weights",
        ) from exc
    if not isinstance(payload, Mapping) or not isinstance(
        payload.get("model_state_dict"), Mapping
    ):
        raise _failure(
            "CHECKPOINT_STATE_INVALID",
            f"checkpoint {spec.logical_name!r} has no model_state_dict mapping",
        )
    state = payload["model_state_dict"]
    if len(state) != spec.state_dict_key_count:
        raise _failure(
            "CHECKPOINT_KEY_COUNT_MISMATCH",
            f"checkpoint {spec.logical_name!r} has {len(state)} model keys, "
            f"expected {spec.state_dict_key_count}",
        )
    signature = state_dict_signature(state)
    if signature != spec.state_dict_signature_sha256:
        raise _failure(
            "CHECKPOINT_STRUCTURE_MISMATCH",
            f"checkpoint {spec.logical_name!r} key/shape signature does not match manifest",
        )
    return state


def strict_load_model_state(
    model: torch.nn.Module,
    state: Mapping[str, torch.Tensor],
    *,
    logical_name: str,
) -> None:
    """Diagnose key/shape drift, then enforce PyTorch strict loading."""

    expected = model.state_dict()
    expected_keys = set(expected)
    actual_keys = set(state)
    missing = sorted(expected_keys - actual_keys)
    if missing:
        raise _failure(
            "CHECKPOINT_MISSING_KEYS",
            f"checkpoint {logical_name!r} is missing model keys",
            details={"logical_name": logical_name, "missing_keys": missing},
        )
    unexpected = sorted(actual_keys - expected_keys)
    if unexpected:
        raise _failure(
            "CHECKPOINT_UNEXPECTED_KEYS",
            f"checkpoint {logical_name!r} has unexpected model keys",
            details={"logical_name": logical_name, "unexpected_keys": unexpected},
        )
    shape_mismatches = {
        key: {
            "expected": tuple(expected[key].shape),
            "actual": tuple(state[key].shape),
        }
        for key in expected
        if tuple(expected[key].shape) != tuple(state[key].shape)
    }
    if shape_mismatches:
        raise _failure(
            "CHECKPOINT_SHAPE_MISMATCH",
            f"checkpoint {logical_name!r} has incompatible tensor shapes",
            details={
                "logical_name": logical_name,
                "shape_mismatches": shape_mismatches,
            },
        )
    try:
        model.load_state_dict(state, strict=True)
    except RuntimeError as exc:
        raise _failure(
            "CHECKPOINT_STRICT_LOAD_FAILED",
            f"checkpoint {logical_name!r} failed strict state loading: {exc}",
        ) from exc


def _create_model(architecture: ArchitectureSpec) -> torch.nn.Module:
    output_classes: int | tuple[int, int]
    if len(architecture.output_classes) == 1:
        output_classes = architecture.output_classes[0]
    elif len(architecture.output_classes) == 2:
        output_classes = (
            architecture.output_classes[0],
            architecture.output_classes[1],
        )
    else:
        raise _failure(
            "MODEL_ARCHITECTURE_INVALID",
            f"unsupported output shape {architecture.output_classes!r}",
        )
    common = (
        architecture.n_cnn_layers,
        architecture.rnn_dim,
        output_classes,
        architecture.n_feats,
        architecture.stride,
        architecture.dropout,
    )
    if architecture.kind == "acoustic":
        return AcousticModel(*common)
    if architecture.kind == "boundary" and output_classes == 1:
        return BoundaryDetection(*common)
    raise _failure(
        "MODEL_ARCHITECTURE_INVALID",
        f"unsupported architecture kind {architecture.kind!r}",
    )


class LegacyV1Inference:
    """Manifest-pinned LegacyV1 model loader and inference implementation.

    One instance serializes model initialization and inference.  This protects
    the legacy model/runtime state until safe shared-model concurrency is
    independently established.
    """

    def __init__(
        self,
        *,
        asset_root: str | Path | None = None,
        asset_locator: AssetLocator | None = None,
        profile: LegacyV1Profile | None = None,
        device: str | torch.device = "cpu",
    ) -> None:
        self.profile = profile or load_legacy_v1_profile()
        self._asset_locator = asset_locator or AssetLocator(asset_root)
        requested_device = str(device)
        if requested_device == "auto":
            requested_device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(requested_device)
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise _failure("MODEL_DEVICE_UNAVAILABLE", "CUDA was requested but is unavailable")
        self._models: dict[str, torch.nn.Module] = {}
        self._model_failures: dict[str, Exception] = {}
        self._lock = threading.RLock()
        feature = self.profile.feature
        self._mel = torchaudio.transforms.MelSpectrogram(
            sample_rate=feature.sample_rate,
            n_fft=feature.n_fft,
            win_length=feature.win_length,
            hop_length=feature.hop_length,
            n_mels=feature.n_mels,
            power=feature.power,
            center=feature.center,
            pad_mode=feature.pad_mode,
            normalized=feature.normalized,
            mel_scale=feature.mel_scale,
        ).to(self.device)

    @staticmethod
    def _asset_spec(spec: CheckpointSpec) -> AssetSpec:
        return AssetSpec.from_manifest_entry(spec)

    def load_model(self, logical_name: str) -> torch.nn.Module:
        """Load once, validating bytes and structure before model construction."""

        with self._lock:
            if logical_name in self._models:
                return self._models[logical_name]
            if logical_name in self._model_failures:
                raise self._model_failures[logical_name]
            try:
                try:
                    spec = self.profile.checkpoints[logical_name]
                except KeyError as exc:
                    raise _failure(
                        "CHECKPOINT_NOT_ALLOWLISTED",
                        f"unknown LegacyV1 model {logical_name!r}",
                    ) from exc
                resolved = self._asset_locator.resolve(self._asset_spec(spec))
                # AssetLocator guarantees LFS, size, and hash verification before
                # this separately structure-validating checkpoint load.
                state = load_checkpoint_state(resolved.path, spec)
                architecture = self.profile.architectures[spec.architecture_id]
                # Module constructors initialize parameters using global RNG.  The
                # checkpoint overwrites them, so preserve the caller's RNG state.
                with torch.random.fork_rng(devices=[]):
                    model = _create_model(architecture)
                strict_load_model_state(model, state, logical_name=logical_name)
                model = model.to(self.device)
                model.eval()
            except Exception as exc:
                # A runtime is an immutable owner of lazy resources.  Cache
                # initialization failure so concurrent waiters observe one
                # attempt and one stable result; a new runtime is the retry API.
                self._model_failures[logical_name] = exc
                raise
            self._models[logical_name] = model
            return model

    def extract_features(self, audio: Any) -> torch.Tensor:
        """Create `[1, 1, 128, frames]` Mel input from the first channel."""

        samples = audio if isinstance(audio, torch.Tensor) else torch.as_tensor(audio)
        if samples.ndim == 1:
            samples = samples.unsqueeze(0)
        if samples.ndim != 2 or samples.shape[0] < 1 or samples.shape[1] < 1:
            raise _failure(
                "MODEL_AUDIO_SHAPE_INVALID",
                "audio must have shape [samples] or [channels, samples]",
            )
        samples = samples[:1].to(device=self.device, dtype=torch.float32)
        if not torch.isfinite(samples).all():
            raise _failure("MODEL_AUDIO_NONFINITE", "audio contains NaN or infinity")
        with torch.inference_mode():
            mel = self._mel(samples)
        return mel.unsqueeze(0)

    def predict(
        self,
        audio: Any,
        *,
        acoustic_model: str = "MTL",
        seed: int = 0,
    ) -> tuple[torch.Tensor, torch.Tensor | None]:
        """Return CPU phoneme log-posterior and optional BDR log curve."""

        if acoustic_model.endswith("_BDR"):
            model_name = acoustic_model[:-4]
            with_boundary = True
        else:
            model_name = acoustic_model
            with_boundary = False
        if model_name not in ("Baseline", "MTL"):
            raise _failure(
                "MODEL_PROFILE_UNKNOWN",
                f"unsupported LegacyV1 acoustic model {acoustic_model!r}",
            )

        with self._lock, torch.inference_mode():
            features = self.extract_features(audio)
            acoustic = self.load_model(model_name)
            raw = acoustic(features)
            expected = self.profile.checkpoints[model_name].output_classes
            expected_shape = (1, raw.shape[1], *expected)
            if tuple(raw.shape) != expected_shape:
                raise _failure(
                    "MODEL_OUTPUT_SHAPE_MISMATCH",
                    f"{model_name} returned {tuple(raw.shape)}, expected {expected_shape}",
                )
            if model_name == "MTL":
                raw = torch.sum(raw, dim=3)
            posterior = F.log_softmax(raw, dim=2).reshape(-1, 41)

            generator = torch.Generator(device=self.device.type)
            generator.manual_seed(int(seed))
            noise = torch.rand(
                posterior.shape,
                dtype=posterior.dtype,
                device=posterior.device,
                generator=generator,
            )
            noise = noise * (1e-10 - 1e-11) + 1e-11
            posterior = torch.log(torch.exp(posterior) + noise)

            boundary: torch.Tensor | None = None
            if with_boundary:
                boundary_model = self.load_model("BDR")
                boundary_raw = boundary_model(features)
                expected_boundary = (1, posterior.shape[0], 1)
                if tuple(boundary_raw.shape) != expected_boundary:
                    raise _failure(
                        "MODEL_OUTPUT_SHAPE_MISMATCH",
                        f"BDR returned {tuple(boundary_raw.shape)}, expected {expected_boundary}",
                    )
                boundary = torch.log(boundary_raw.reshape(-1)) * 0.8

            return posterior.detach().cpu(), (
                boundary.detach().cpu() if boundary is not None else None
            )

    def align(
        self,
        lyrics: LyricsPlan,
        audio: AudioBuffer,
        *,
        acoustic_model: str = "MTL",
        device: str = "cpu",
        seed: int = 0,
        max_alignment_bytes: int = 512 * 1024 * 1024,
    ) -> AlignmentOutcome:
        """Implement the v2 InferencePort using frozen LegacyV1 behavior."""

        requested_device = self.device if device == "auto" else torch.device(device)
        if requested_device != self.device:
            raise _failure(
                "MODEL_DEVICE_MISMATCH",
                f"adapter uses {self.device}, request asked for {device}",
            )
        if not isinstance(lyrics, LyricsPlan) or not isinstance(audio, AudioBuffer):
            raise _failure(
                "MODEL_INPUT_CONTRACT_INVALID",
                "align expects LyricsPlan and AudioBuffer",
            )
        if audio.sample_rate != self.profile.feature.sample_rate:
            raise _failure(
                "MODEL_SAMPLE_RATE_MISMATCH",
                f"LegacyV1 expects {self.profile.feature.sample_rate} Hz, "
                f"received {audio.sample_rate} Hz",
            )
        payload = lyrics.payload
        phones = _first_attribute(payload, "phones", "phonemes", "lyrics_p")
        if acoustic_model in ("Baseline", "MTL", "Baseline_BDR", "MTL_BDR"):
            # Even a one-frame posterior would exceed this budget, so no model
            # execution can make the request admissible.  This lower-bound gate
            # is intentionally derived from the existing alignment-memory
            # contract; it does not invent a separate phone/audio size policy.
            minimum_estimated = _estimate_alignment_bytes(
                audio_frames=1,
                phoneme_count=len(phones),
                posterior_itemsize=np.dtype(np.float32).itemsize,
                boundary=acoustic_model.endswith("_BDR"),
            )
            _enforce_alignment_budget(minimum_estimated, max_alignment_bytes)
        word_spans = np.asarray(
            _first_attribute(payload, "word_spans", "idx_word_p"), dtype=np.int64
        )
        line_spans = np.asarray(
            _first_attribute(payload, "line_spans", "idx_line_p"), dtype=np.int64
        )
        posterior, boundary = self.predict(
            audio.samples, acoustic_model=acoustic_model, seed=seed
        )
        estimated = _estimate_alignment_bytes(
            audio_frames=posterior.shape[0],
            phoneme_count=len(phones),
            posterior_itemsize=posterior.element_size(),
            boundary=boundary is not None,
        )
        _enforce_alignment_budget(estimated, max_alignment_bytes)
        try:
            if boundary is None:
                spans, score = legacy_alignment.alignment(
                    posterior, phones, word_spans
                )
            else:
                line_starts = line_spans[:, 0]
                spans, score = legacy_alignment.alignment_bdr(
                    posterior.numpy(),
                    phones,
                    word_spans,
                    boundary.numpy(),
                    line_starts,
                )
        except legacy_alignment.AlignmentValueError as exc:
            raise AlignmentInputError(
                "LegacyV1 alignment inputs cannot form a valid DTW path.",
                details={
                    "backend": "bdr" if boundary is not None else "dtw",
                    "reason": str(exc),
                },
                cause=exc,
            ) from exc
        except IndexError as exc:
            if boundary is not None and _is_bdr_backtrack_exhaustion(exc):
                raise IncompleteAlignmentError(
                    "LegacyV1 alignment backtracking exhausted before the first token.",
                    details={
                        "expected": lyrics.expected_token_count,
                        "aligned": 0,
                        "first_gap": 0,
                    },
                    cause=exc,
                ) from exc
            raise
        del score  # v2's public outcome intentionally does not expose legacy score
        spans = _nonempty_span_prefix(spans)
        token_spans = tuple(
            TokenAlignment(
                token_index=token.token_index,
                line_index=token.line_index,
                text=token.text,
                frame_span=FrameSpan(int(span[0]), int(span[1])),
            )
            for token, span in zip(lyrics.tokens, spans, strict=False)
        )
        return AlignmentOutcome(
            spans=token_spans,
            expected_token_count=lyrics.expected_token_count,
            diagnostics=lyrics.diagnostics,
            model_profile=self.profile.profile_id,
            timebase=Timebase(
                sample_rate=self.profile.frame_clock_denominator,
                hop_length=self.profile.feature.hop_length,
                time_pooling=(
                    self.profile.frame_clock_numerator
                    // self.profile.feature.hop_length
                ),
            ),
        )


def _first_attribute(instance: Any, *names: str) -> Any:
    for name in names:
        if hasattr(instance, name):
            return getattr(instance, name)
    raise _failure(
        "MODEL_INPUT_CONTRACT_INVALID",
        f"input is missing one of the required attributes: {', '.join(names)}",
    )


def _nonempty_span_prefix(spans: Any) -> tuple[Any, ...]:
    """Drop a missing/zero-length tail without inventing replacement frames."""

    prefix: list[Any] = []
    for span in spans:
        if len(span) != 2:
            break
        start, end = int(span[0]), int(span[1])
        if end == start:
            break
        prefix.append((start, end))
    return tuple(prefix)


def _is_bdr_backtrack_exhaustion(error: IndexError) -> bool:
    """Recognize only the frozen BDR backtracker's negative state overrun."""

    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        if frame.f_code is legacy_alignment.alignment_bdr.__code__:
            local = frame.f_locals
            path = local.get("path")
            opt = local.get("opt")
            x, y = local.get("x"), local.get("y")
            shape = getattr(opt, "shape", ())
            return (
                isinstance(path, list)
                and isinstance(x, (int, np.integer))
                and isinstance(y, (int, np.integer))
                and len(shape) == 2
                and (x < -shape[0] or y < -shape[1])
            )
        traceback = traceback.tb_next
    return False


def _estimate_alignment_bytes(
    *,
    audio_frames: int,
    phoneme_count: int,
    posterior_itemsize: int,
    boundary: bool,
) -> int:
    """Estimate the persistent DP matrices allocated by a LegacyV1 backend."""

    if boundary:
        # alignment_bdr creates both score and option matrices with NumPy's
        # default float64 dtype and the same [frames, 2*phones+1] shape.
        cells = audio_frames * (2 * phoneme_count + 1)
        return cells * (np.dtype(np.float64).itemsize * 2)
    score_cells = audio_frames * (2 * phoneme_count + 2)
    option_cells = audio_frames * (2 * phoneme_count + 1)
    return score_cells * posterior_itemsize + option_cells * np.dtype(np.int8).itemsize


def _enforce_alignment_budget(estimated: int, limit: int) -> None:
    if estimated > limit:
        raise _failure(
            "ALIGNMENT_MEMORY_LIMIT",
            f"estimated {estimated} bytes exceeds limit {limit}",
            details={"estimated": estimated, "limit": limit},
        )
