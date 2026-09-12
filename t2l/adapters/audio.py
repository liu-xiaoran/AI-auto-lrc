from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from t2l.contracts import AudioBuffer, VocalSeparationOptions
from t2l.errors import AudioDecodeError, ConfigurationError, SourceSeparationError

Loader = Callable[[Path], tuple[object, int]]
Resampler = Callable[[object, int, int], object]


def _is_missing_demucs(cause: ImportError) -> bool:
    missing = getattr(cause, "name", None)
    return (
        isinstance(cause, ModuleNotFoundError)
        and isinstance(missing, str)
        and (missing == "demucs" or missing.startswith("demucs."))
    )


def _torchaudio_load(path: Path):
    import torchaudio

    return torchaudio.load(str(path))


def _librosa_load(path: Path):
    import librosa

    samples, sample_rate = librosa.load(
        str(path), sr=None, mono=True, res_type="kaiser_fast"
    )
    return samples, sample_rate


def _resample(samples, source_rate: int, target_rate: int):
    import julius

    return julius.resample_frac(samples, source_rate, target_rate)


class _DemucsSeparator:
    def separate(
        self,
        samples,
        sample_rate: int,
        options: VocalSeparationOptions,
    ):
        import julius
        import torch
        from demucs import pretrained
        from demucs.apply import apply_model

        model = pretrained.get_model(options.demucs_model)
        if options.demucs_index >= 0:
            models = getattr(model, "models", None)
            if models is None or options.demucs_index >= len(models):
                raise ConfigurationError(
                    "Demucs model index is outside the available model bag.",
                    details={
                        "index": options.demucs_index,
                        "available": len(models or ()),
                    },
                )
            model = models[options.demucs_index]
        model.to("cpu")
        model.eval()
        working = samples
        if sample_rate != model.samplerate:
            working = julius.resample_frac(
                working, sample_rate, model.samplerate
            )
        if working.shape[0] == 1:
            working = working.expand((2, *working.shape[1:]))
        with torch.inference_mode():
            output = apply_model(
                model, working[None], device="cpu", progress=False
            )[0]
        vocals = None
        for name, source in zip(model.sources, output, strict=True):
            if name == "vocals":
                vocals = source
                break
        if vocals is None:
            raise SourceSeparationError(
                "Demucs output does not contain a vocals source."
            )
        if model.samplerate != 22050:
            vocals = julius.resample_frac(vocals, model.samplerate, 22050)
        return vocals, 22050


class AudioPreparationAdapter:
    def __init__(
        self,
        *,
        torchaudio_loader: Loader | None = None,
        librosa_loader: Loader | None = None,
        resampler: Resampler | None = None,
        separator_factory: Callable[[], object] | None = None,
    ) -> None:
        self._torchaudio_loader = torchaudio_loader or _torchaudio_load
        self._librosa_loader = librosa_loader or _librosa_load
        self._resampler = resampler or _resample
        self._separator_factory = separator_factory or _DemucsSeparator

    def prepare(
        self,
        audio_path: Path,
        *,
        vocal_separation: VocalSeparationOptions | None,
        decoder: str,
    ) -> AudioBuffer:
        if decoder == "torchaudio":
            loader = self._torchaudio_loader
            channel_policy = "preserve"
        elif decoder == "librosa-mono":
            loader = self._librosa_loader
            channel_policy = "mono"
        else:
            raise AudioDecodeError(
                "Unsupported audio decoder policy.", details={"decoder": decoder}
            )

        try:
            samples, sample_rate = loader(audio_path)
        except Exception as cause:
            raise AudioDecodeError(
                f"Unable to decode audio with {decoder}.",
                details={"decoder": decoder, "path": str(audio_path)},
            ) from cause

        samples = self._normalize(samples, audio_path)
        if sample_rate <= 0:
            raise AudioDecodeError(
                "Decoded audio has an invalid sample rate.",
                details={"sample_rate": sample_rate},
            )
        if vocal_separation is None and sample_rate != 22050:
            try:
                samples = self._resampler(samples, sample_rate, 22050)
            except Exception as cause:
                raise AudioDecodeError(
                    "Unable to resample audio to 22050 Hz.",
                    details={"source_rate": sample_rate},
                ) from cause
            sample_rate = 22050
            samples = self._normalize(samples, audio_path)

        if vocal_separation is not None:
            try:
                separator = self._separator_factory()
                samples, sample_rate = separator.separate(
                    samples, sample_rate, vocal_separation
                )
            except (ConfigurationError, SourceSeparationError):
                raise
            except ImportError as cause:
                if _is_missing_demucs(cause):
                    raise SourceSeparationError(
                        "Demucs source separation requires the vocals extra.",
                        code="T2L_VOCALS_DEPENDENCY_MISSING",
                        details={"extra": "vocals"},
                    ) from cause
                raise SourceSeparationError(
                    "Unable to initialize or run Demucs source separation.",
                    details={"extra": "vocals"},
                ) from cause
            except Exception as cause:
                raise SourceSeparationError(
                    "Unable to initialize or run Demucs source separation.",
                    details={"extra": "vocals"},
                ) from cause
            samples = self._normalize(samples, audio_path)

        return AudioBuffer(
            samples=samples,
            sample_rate=sample_rate,
            metadata={
                "decoder": decoder,
                "channel_policy": channel_policy,
                "separated_vocals": vocal_separation is not None,
            },
        )

    @staticmethod
    def _normalize(samples, path: Path):
        import torch

        if not isinstance(samples, torch.Tensor):
            samples = torch.as_tensor(samples)
        if samples.ndim == 1:
            samples = samples.unsqueeze(0)
        samples = samples.to(dtype=torch.float32)
        if samples.ndim != 2:
            raise AudioDecodeError(
                "Decoded audio must have [channels, samples] shape.",
                code="T2L_AUDIO_SHAPE_INVALID",
                details={"path": str(path), "shape": tuple(samples.shape)},
            )
        if samples.shape[0] < 1 or samples.shape[1] < 1:
            raise AudioDecodeError(
                "Decoded audio contains no samples.",
                code="T2L_AUDIO_EMPTY",
                details={"path": str(path), "shape": tuple(samples.shape)},
            )
        if not bool(torch.isfinite(samples).all()):
            raise AudioDecodeError(
                "Decoded audio contains NaN or infinity.",
                code="T2L_AUDIO_NONFINITE",
                details={"path": str(path), "shape": tuple(samples.shape)},
            )
        return samples
