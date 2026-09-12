import os
import stat
from io import StringIO
from pathlib import Path

import pytest

from t2l.adapters.cli import main
from t2l.application.ports import ProgressEvent
from t2l.contracts import (
    AlignmentResult,
    Diagnostic,
    FrameSpan,
    Timebase,
    TokenAlignment,
)
from t2l.errors import (
    AlignmentInputError,
    AssetNotFoundError,
    AudioDecodeError,
    CheckpointError,
    LyricsInputError,
    OutputWriteError,
)


def _result(*, partial=False):
    span = TokenAlignment(0, 0, "hello", FrameSpan(0, 1))
    diagnostic = Diagnostic(
        code="T2L_ALIGNMENT_PARTIAL",
        stage="alignment",
        message="one token is missing",
        details={"expected": 2, "aligned": 1, "first_gap": 1},
    )
    return AlignmentResult(
        lrc="[00:00.000]hello",
        status="partial" if partial else "complete",
        spans=(span,),
        diagnostics=(diagnostic,) if partial else (),
        model_profile="legacy-v1",
        timebase=Timebase(),
        expected_token_count=2 if partial else 1,
        allow_partial=partial,
    )


class FakeRuntime:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.requests = []
        self.progress_observer = None

    def process(self, request):
        self.requests.append(request)
        self.progress_observer.emit(
            ProgressEvent(stage="alignment", status="started")
        )
        if self.error is not None:
            raise self.error
        self.progress_observer.emit(
            ProgressEvent(
                stage="alignment",
                status="completed",
                result=self.result.status,
            )
        )
        return self.result


def _invoke(tmp_path, runtime, *extra):
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("hello", encoding="utf-8")
    stdout, stderr = StringIO(), StringIO()
    configs = []

    def factory(config, progress_observer):
        configs.append(config)
        runtime.progress_observer = progress_observer
        return runtime

    code = main(
        [str(lyrics), str(tmp_path / "song.wav"), *extra],
        runtime_factory=factory,
        stdout=stdout,
        stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue(), configs


def test_complete_without_output_writes_only_canonical_lrc_to_stdout(tmp_path):
    code, stdout, stderr, configs = _invoke(tmp_path, FakeRuntime(_result()))

    assert code == 0
    assert stdout == "[00:00.000]hello\n"
    assert stderr == ""
    assert configs[0].decoder == "torchaudio"
    assert configs[0].offline is True


def test_complete_with_output_writes_file_and_keeps_stdout_empty(tmp_path):
    output = tmp_path / "nested" / "result.lrc"
    code, stdout, stderr, _ = _invoke(
        tmp_path, FakeRuntime(_result()), "-o", str(output)
    )

    assert code == 0
    assert stdout == ""
    assert stderr == ""
    assert output.read_bytes() == b"[00:00.000]hello\n"


def test_explicit_partial_writes_result_and_returns_three(tmp_path):
    runtime = FakeRuntime(_result(partial=True))
    code, stdout, stderr, _ = _invoke(
        tmp_path, runtime, "--allow-partial"
    )

    assert code == 3
    assert stdout == "[00:00.000]hello\n"
    assert stderr == (
        "T2L_ALIGNMENT_PARTIAL: alignment output is incomplete "
        "expected=2 aligned=1 first_gap=1\n"
    )
    assert runtime.requests[0].allow_partial is True


def test_cli_003_verbose_reports_stable_observer_events_only_to_stderr(
    tmp_path,
):
    """CLI-003: verbose observer events never contaminate stdout."""

    code, stdout, stderr, _ = _invoke(
        tmp_path, FakeRuntime(_result()), "--verbose"
    )

    assert code == 0
    assert stdout == "[00:00.000]hello\n"
    assert stderr.splitlines() == [
        "T2L_PROGRESS: stage=lyrics_read status=started",
        "T2L_PROGRESS: stage=lyrics_read status=completed",
        "T2L_PROGRESS: stage=runtime_create status=started",
        "T2L_PROGRESS: stage=runtime_create status=completed",
        "T2L_PROGRESS: stage=alignment status=started",
        "T2L_PROGRESS: stage=alignment status=completed result=complete",
        "T2L_PROGRESS: stage=output status=started target=stdout",
        "T2L_PROGRESS: stage=output status=completed target=stdout",
    ]


def test_cli_012_debug_traceback_redacts_secrets_control_characters_and_paths(
    tmp_path, monkeypatch
):
    """CLI-012: debug preserves the chain after secret/path sanitization."""

    secret = "sentinel-secret-value-5f4dcc3b"
    sensitive_path = tmp_path / "private" / "credentials.txt"
    monkeypatch.setenv("T2L_TEST_SECRET", secret)
    failure = RuntimeError(
        f"failure token={secret} at {sensitive_path}\x1b[31m\nforged-line"
    )
    failure.__cause__ = ValueError(f"credential={secret}")

    code, stdout, stderr, _ = _invoke(
        tmp_path,
        FakeRuntime(error=failure),
        "--debug",
    )

    assert code == 1
    assert stdout == ""
    assert "Traceback (most recent call last):" in stderr
    assert "direct cause of the following exception" in stderr
    assert "ValueError:" in stderr
    assert "RuntimeError:" in stderr
    assert "<redacted-secret>" in stderr
    assert "<redacted-path>" in stderr
    assert secret not in stderr
    assert str(tmp_path) not in stderr
    assert str(Path(__file__).resolve()) not in stderr
    assert "\x1b" not in stderr
    assert "\\x1b" in stderr
    assert "\nforged-line" not in stderr
    assert "\\nforged-line" in stderr


def test_cli_011_unknown_exception_uses_generic_code_one_message(tmp_path):
    """CLI-011: unknown Exception is code 1 without traceback or raw message."""

    failure = RuntimeError("sentinel-secret internal detail")

    code, stdout, stderr, _ = _invoke(tmp_path, FakeRuntime(error=failure))

    assert code == 1
    assert stdout == ""
    assert stderr == "T2L_INTERNAL_ERROR: unexpected failure\n"
    assert "sentinel-secret" not in stderr
    assert "Traceback" not in stderr


@pytest.mark.parametrize("failure", [SystemExit(23), GeneratorExit("stop")])
def test_non_exception_base_exceptions_propagate_unchanged(tmp_path, failure):
    runtime = FakeRuntime(error=failure)

    with pytest.raises(type(failure)) as exc_info:
        _invoke(tmp_path, runtime)

    assert exc_info.value is failure


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (LyricsInputError("bad lyrics"), 4),
        (AudioDecodeError("bad audio"), 5),
        (AssetNotFoundError("missing model"), 6),
        (
            CheckpointError(
                "bad manifest",
                code="T2L_ASSET_MANIFEST_INVALID",
                stage="asset_resolution",
            ),
            6,
        ),
        (AlignmentInputError("bad posterior"), 7),
        (OutputWriteError("disk full"), 8),
    ],
)
def test_known_errors_have_stable_exit_codes_and_no_stdout(
    tmp_path, error, expected_code
):
    code, stdout, stderr, _ = _invoke(tmp_path, FakeRuntime(error=error))

    assert code == expected_code
    assert stdout == ""
    assert stderr == f"{error.code}: {error}\n"


def test_demucs_options_without_separation_fail_before_runtime(tmp_path):
    runtime = FakeRuntime(_result())
    code, stdout, stderr, configs = _invoke(
        tmp_path, runtime, "--demucs-model", "mdx"
    )

    assert code == 2
    assert stdout == ""
    assert stderr.startswith("T2L_CONFIG_INVALID:")
    assert configs == []


def test_asset_root_is_resolved_once_against_starting_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, _, _, configs = _invoke(
        tmp_path, FakeRuntime(_result()), "--asset-root", "assets"
    )

    assert code == 0
    assert configs[0].asset_root == tmp_path / "assets"


def test_cli_020_output_cannot_replace_lyrics_input(tmp_path):
    """CLI-020: an output alias must never overwrite the lyrics input."""

    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("hello", encoding="utf-8")
    runtime = FakeRuntime(_result())
    stdout, stderr = StringIO(), StringIO()
    factories = []

    code = main(
        [str(lyrics), str(tmp_path / "song.wav"), "-o", str(lyrics)],
        runtime_factory=lambda config, _observer: factories.append(config) or runtime,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue().startswith("T2L_CONFIG_INVALID:")
    assert lyrics.read_text(encoding="utf-8") == "hello"
    assert factories == []
    assert runtime.requests == []

    alias = tmp_path / "lyrics-hardlink.lrc"
    os.link(lyrics, alias)
    code = main(
        [str(lyrics), str(tmp_path / "song.wav"), "-o", str(alias)],
        runtime_factory=lambda config, _observer: factories.append(config) or runtime,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert lyrics.read_text(encoding="utf-8") == "hello"
    assert alias.read_text(encoding="utf-8") == "hello"
    assert factories == []
    assert runtime.requests == []


def test_cli_021_output_cannot_replace_audio_input(tmp_path):
    """CLI-021: an output alias must never overwrite the audio input."""

    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("hello", encoding="utf-8")
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF-not-a-real-wave")
    runtime = FakeRuntime(_result())
    stdout, stderr = StringIO(), StringIO()
    factories = []

    code = main(
        [str(lyrics), str(audio), "-o", str(audio)],
        runtime_factory=lambda config, _observer: factories.append(config) or runtime,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue().startswith("T2L_CONFIG_INVALID:")
    assert audio.read_bytes() == b"RIFF-not-a-real-wave"
    assert factories == []
    assert runtime.requests == []

    alias = tmp_path / "audio-hardlink.lrc"
    os.link(audio, alias)
    code = main(
        [str(lyrics), str(audio), "-o", str(alias)],
        runtime_factory=lambda config, _observer: factories.append(config) or runtime,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert audio.read_bytes() == b"RIFF-not-a-real-wave"
    assert alias.read_bytes() == b"RIFF-not-a-real-wave"
    assert factories == []
    assert runtime.requests == []


def test_cli_022_partial_file_output_is_atomic_and_stdout_is_empty(tmp_path):
    """CLI-022: partial output keeps stdout XOR file semantics and exit 3."""

    output = tmp_path / "partial.lrc"
    code, stdout, stderr, _ = _invoke(
        tmp_path,
        FakeRuntime(_result(partial=True)),
        "--allow-partial",
        "-o",
        str(output),
    )

    assert code == 3
    assert stdout == ""
    assert stderr == (
        "T2L_ALIGNMENT_PARTIAL: alignment output is incomplete "
        "expected=2 aligned=1 first_gap=1\n"
    )
    assert output.read_bytes() == b"[00:00.000]hello\n"


def test_cli_025_output_mode_is_secure_for_new_and_replaced_files(tmp_path):
    """CLI-025: a fixed umask yields mode 0600, including replacements."""

    output = tmp_path / "mode.lrc"
    previous_umask = os.umask(0o077)
    try:
        code, stdout, stderr, _ = _invoke(
            tmp_path,
            FakeRuntime(_result()),
            "-o",
            str(output),
        )
        created_mode = stat.S_IMODE(output.stat().st_mode)
        output.chmod(0o640)
        second_code, _, _, _ = _invoke(
            tmp_path,
            FakeRuntime(_result()),
            "-o",
            str(output),
        )
        replaced_mode = stat.S_IMODE(output.stat().st_mode)
    finally:
        os.umask(previous_umask)

    assert (code, second_code) == (0, 0)
    assert stdout == ""
    assert stderr == ""
    assert created_mode == 0o600
    assert replaced_mode == 0o600


@pytest.mark.parametrize(
    "target_kind",
    ["directory", "fifo", "device", "symlink", "symlink-parent"],
)
def test_cli_026_non_regular_and_symlink_outputs_are_rejected(
    tmp_path, target_kind
):
    """CLI-026: unsafe target types and symlink traversal fail closed."""

    outside = tmp_path / "outside"
    outside.mkdir()
    expected_kind = target_kind
    if target_kind == "directory":
        target = tmp_path / "directory.lrc"
        target.mkdir()
    elif target_kind == "fifo":
        target = tmp_path / "fifo.lrc"
        os.mkfifo(target)
    elif target_kind == "device":
        target = Path(os.devnull)
    elif target_kind == "symlink":
        linked_file = outside / "linked.lrc"
        linked_file.write_bytes(b"OLD")
        target = tmp_path / "symlink.lrc"
        target.symlink_to(linked_file)
    else:
        linked_parent = tmp_path / "linked-parent"
        linked_parent.symlink_to(outside, target_is_directory=True)
        target = linked_parent / "result.lrc"

    code, stdout, stderr, _ = _invoke(
        tmp_path,
        FakeRuntime(_result()),
        "-o",
        str(target),
    )

    assert code == 8
    assert stdout == ""
    assert stderr.startswith("T2L_OUTPUT_WRITE_FAILED:")
    if expected_kind == "directory":
        assert target.is_dir()
    elif expected_kind == "fifo":
        assert stat.S_ISFIFO(target.lstat().st_mode)
    elif expected_kind == "device":
        assert stat.S_ISCHR(target.stat().st_mode)
    elif expected_kind == "symlink":
        assert target.is_symlink()
        assert linked_file.read_bytes() == b"OLD"
    else:
        assert not (outside / "result.lrc").exists()
