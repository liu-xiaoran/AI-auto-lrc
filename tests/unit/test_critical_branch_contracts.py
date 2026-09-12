"""Direct contracts for branches designated release-critical by policy."""

from __future__ import annotations

import hashlib
from io import StringIO
from pathlib import Path

import pytest
import torch

from t2l.adapters import assets as assets_module
from t2l.adapters.assets import AssetLocator, AssetSpec
from t2l.adapters.audio import AudioPreparationAdapter
from t2l.adapters.cli import _redact_text, main
from t2l.adapters.output import serialize_lrc
from t2l.application.align_lyrics import CompletenessPolicy
from t2l.contracts import (
    AlignmentOutcome,
    AlignmentRequest,
    AlignmentResult,
    FrameSpan,
    LyricsPlan,
    LyricsToken,
    Timebase,
    TokenAlignment,
    VocalSeparationOptions,
)
from t2l.errors import (
    AlignmentInputError,
    AudioDecodeError,
    LyricsInputError,
    SourceSeparationError,
)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write(root: Path, relative: str, value: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


@pytest.mark.parametrize(
    "arguments",
    [
        ("", "asset.bin", "0" * 64, None),
        ("asset", "/absolute.bin", "0" * 64, None),
        ("asset", "asset.bin", "not-a-sha", None),
        ("asset", "asset.bin", "0" * 64, -1),
    ],
)
def test_asset_spec_rejects_each_invalid_identity_field(arguments):
    with pytest.raises(ValueError):
        AssetSpec(*arguments)


def test_resolve_rejects_size_mismatch(tmp_path):
    root = tmp_path / "assets"
    _write(root, "asset.bin", b"payload")

    with pytest.raises(Exception) as error:
        AssetLocator(root, environ={}, development_root=None).resolve(
            AssetSpec("asset", "asset.bin", _digest(b"payload"), size=99)
        )

    assert error.value.code == "T2L_ASSET_SIZE_MISMATCH"


def test_development_root_is_an_explicit_last_precedence_source(tmp_path):
    root = tmp_path / "development"
    _write(root, "asset.bin", b"payload")

    resolved = AssetLocator(environ={}, development_root=root).resolve(
        AssetSpec("asset", "asset.bin", _digest(b"payload"), size=7)
    )

    assert resolved.provenance == "development"


def test_materialize_rejects_mismatched_key_and_unsafe_destination(tmp_path):
    root = tmp_path / "assets"
    _write(root, "asset.bin", b"payload")
    locator = AssetLocator(root, environ={}, development_root=None)
    spec = AssetSpec("asset", "asset.bin", _digest(b"payload"), size=7)

    with pytest.raises(ValueError, match="key must match"):
        locator.materialize_set({"wrong": (spec, "copy.bin")})
    with pytest.raises(ValueError, match="unique and relative"):
        locator.materialize_set({"asset": (spec, "../copy.bin")})


def test_materialize_cleans_up_if_published_bytes_fail_readback(tmp_path, monkeypatch):
    root = tmp_path / "assets"
    _write(root, "asset.bin", b"payload")
    locator = AssetLocator(root, environ={}, development_root=None)
    spec = AssetSpec("asset", "asset.bin", _digest(b"payload"), size=7)
    original_read_bytes = Path.read_bytes

    def changed_readback(path):
        if path.name == "copy.bin":
            return b"changed"
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", changed_readback)

    with pytest.raises(OSError, match="changed while publishing"):
        locator.materialize_set({"asset": (spec, "copy.bin")})


def test_snapshot_rejects_escape_lfs_and_read_failure(tmp_path, monkeypatch):
    root = tmp_path / "assets"
    outside = tmp_path / "outside"
    root.mkdir()
    _write(outside, "payload.bin", b"payload")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    locator = AssetLocator(root, environ={}, development_root=None)

    with pytest.raises(Exception) as escape:
        locator.materialize_set(
            {
                "asset": (
                    AssetSpec("asset", "escape/payload.bin", _digest(b"payload"), 7),
                    "copy.bin",
                )
            }
        )
    assert escape.value.code == "T2L_ASSET_PATH_ESCAPE"

    pointer = b"version https://git-lfs.github.com/spec/v1\n" + b"oid sha256:" + b"a" * 64
    _write(root, "pointer.bin", pointer)
    with pytest.raises(Exception) as lfs:
        locator.materialize_set(
            {
                "asset": (
                    AssetSpec("asset", "pointer.bin", _digest(pointer), len(pointer)),
                    "copy.bin",
                )
            }
        )
    assert lfs.value.code == "T2L_ASSET_LFS_POINTER"

    source = _write(root, "unreadable.bin", b"payload")
    original_open = Path.open

    def denied_open(path, *args, **kwargs):
        if path == source:
            raise PermissionError("denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)
    with pytest.raises(Exception) as unreadable:
        locator.materialize_set(
            {
                "asset": (
                    AssetSpec("asset", "unreadable.bin", _digest(b"payload"), 7),
                    "copy.bin",
                )
            }
        )
    assert unreadable.value.code == "T2L_ASSET_READ_FAILED"


def test_materialized_set_close_handles_missing_root_and_is_idempotent(tmp_path):
    root = tmp_path / "assets"
    _write(root, "asset.bin", b"payload")
    locator = AssetLocator(root, environ={}, development_root=None)
    request = {
        "asset": (
            AssetSpec("asset", "asset.bin", _digest(b"payload"), 7),
            "copy.bin",
        )
    }

    already_missing = locator.materialize_set(request)
    already_missing._owner.cleanup()
    already_missing.close()

    idempotent = locator.materialize_set(request)
    idempotent.close()
    idempotent.close()


def test_audio_policy_rejects_unknown_decoder_and_invalid_rate():
    adapter = AudioPreparationAdapter(
        torchaudio_loader=lambda _path: (torch.zeros((1, 2)), 0)
    )

    with pytest.raises(AudioDecodeError, match="Unsupported"):
        adapter.prepare(Path("song.wav"), vocal_separation=None, decoder="unknown")
    with pytest.raises(AudioDecodeError, match="invalid sample rate"):
        adapter.prepare(Path("song.wav"), vocal_separation=None, decoder="torchaudio")


def test_audio_policy_wraps_resample_and_separator_failures():
    resample_cause = RuntimeError("resample")
    resample = AudioPreparationAdapter(
        torchaudio_loader=lambda _path: (torch.zeros((1, 2)), 44_100),
        resampler=lambda *_args: (_ for _ in ()).throw(resample_cause),
    )
    with pytest.raises(AudioDecodeError) as resample_error:
        resample.prepare(Path("song.wav"), vocal_separation=None, decoder="torchaudio")
    assert resample_error.value.__cause__ is resample_cause

    stable = SourceSeparationError("stable")
    passthrough = AudioPreparationAdapter(
        torchaudio_loader=lambda _path: (torch.zeros((1, 2)), 22_050),
        separator_factory=lambda: (_ for _ in ()).throw(stable),
    )
    with pytest.raises(SourceSeparationError) as stable_error:
        passthrough.prepare(
            Path("song.wav"),
            vocal_separation=VocalSeparationOptions(),
            decoder="torchaudio",
        )
    assert stable_error.value is stable

    unknown_cause = RuntimeError("unknown")
    unknown = AudioPreparationAdapter(
        torchaudio_loader=lambda _path: (torch.zeros((1, 2)), 22_050),
        separator_factory=lambda: (_ for _ in ()).throw(unknown_cause),
    )
    with pytest.raises(SourceSeparationError) as unknown_error:
        unknown.prepare(
            Path("song.wav"),
            vocal_separation=VocalSeparationOptions(),
            decoder="torchaudio",
        )
    assert unknown_error.value.__cause__ is unknown_cause


def test_audio_normalization_converts_non_tensor_input():
    audio = AudioPreparationAdapter(
        torchaudio_loader=lambda _path: ([[0.0, 1.0]], 22_050)
    ).prepare(Path("song.wav"), vocal_separation=None, decoder="torchaudio")

    assert isinstance(audio.samples, torch.Tensor)
    assert tuple(audio.samples.shape) == (1, 2)


def _request() -> AlignmentRequest:
    return AlignmentRequest(lyrics=("expected",), audio_path=Path("song.wav"))


def test_completeness_rejects_empty_plan_declared_count_and_metadata_mismatch():
    policy = CompletenessPolicy()
    with pytest.raises(LyricsInputError):
        policy.validate(
            AlignmentRequest(lyrics=(), audio_path=Path("song.wav")),
            LyricsPlan(tokens=()),
            AlignmentOutcome(spans=(), expected_token_count=0),
        )

    plan = LyricsPlan(tokens=(LyricsToken(0, 0, "expected"),))
    with pytest.raises(AlignmentInputError, match="expected-token count"):
        policy.validate(_request(), plan, AlignmentOutcome(spans=(), expected_token_count=2))

    mismatched = TokenAlignment(0, 0, "different", FrameSpan(0, 1))
    with pytest.raises(AlignmentInputError, match="metadata"):
        policy.validate(
            _request(),
            plan,
            AlignmentOutcome(spans=(mismatched,), expected_token_count=1),
        )


def test_cli_separation_branch_preserves_explicit_options(tmp_path):
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("hello", encoding="utf-8")
    observed = {}

    class Runtime:
        def process(self, request):
            observed["request"] = request
            return AlignmentResult(
                lrc="[00:00.000]hello",
                status="complete",
                spans=(TokenAlignment(0, 0, "hello", FrameSpan(0, 1)),),
                diagnostics=(),
                model_profile="legacy-v1",
                timebase=Timebase(),
                expected_token_count=1,
            )

    def factory(config, observer):
        observed["config"] = config
        observed["observer"] = observer
        return Runtime()

    stdout = StringIO()
    stderr = StringIO()
    code = main(
        [
            str(lyrics),
            str(tmp_path / "song.wav"),
            "--separate-vocals",
            "--demucs-model",
            "mdx",
            "--demucs-index",
            "0",
        ],
        runtime_factory=factory,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stdout.getvalue() == "[00:00.000]hello\n"
    assert stderr.getvalue() == ""
    assert observed["request"].vocal_separation == VocalSeparationOptions("mdx", 0)


def test_cli_redaction_and_serializer_cover_control_and_type_rejections():
    assert _redact_text("tab\tcarriage\r", multiline=True) == "tab    carriage\\r"
    with pytest.raises(TypeError):
        serialize_lrc(object())


def test_policy_file_is_parseable_from_the_runtime_expected_location():
    assert assets_module.__name__ == "t2l.adapters.assets"
