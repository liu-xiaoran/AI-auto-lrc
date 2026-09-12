from __future__ import annotations

import argparse
import os
import re
import sys
import traceback
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import TextIO

from t2l.adapters.lyrics_io import LyricsFileReader
from t2l.adapters.output import AtomicLrcSink, serialize_lrc
from t2l.application.ports import (
    NullProgressObserver,
    ProgressEvent,
    ProgressObserverPort,
)
from t2l.contracts import AlignmentRequest, RuntimeConfig, VocalSeparationOptions
from t2l.errors import (
    ERROR_REGISTRY,
    ConfigurationError,
    T2LError,
    registration_for,
)

RuntimeFactory = Callable[[RuntimeConfig, ProgressObserverPort], object]
_SENSITIVE_ENVIRONMENT_NAME = re.compile(
    r"(?:AUTH|CREDENTIAL|KEY|PASSWORD|PRIVATE|SECRET|TOKEN)", re.IGNORECASE
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|auth|credential|password|private[_-]?key|secret|token)"
    r"\s*[:=]\s*[^\s,;]+"
)
_SENTINEL_SECRET = re.compile(
    r"(?i)\bsentinel[-_ ]?secret(?:[-_:= ][^\s,;]*)?"
)
_QUOTED_ABSOLUTE_PATH = re.compile(r"(?P<quote>['\"])/(?:[^\r\n'\"]+)")
_UNQUOTED_ABSOLUTE_PATH = re.compile(
    r"(?<![\w.])/(?:[^/\s\x00-\x1f]+/)+[^\s\x00-\x1f]*"
)


class _StderrObserver:
    """Serialize structured progress events to the CLI stderr stream."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def emit(self, event: ProgressEvent) -> None:
        suffix = "".join(
            f" {key}={_safe_message(value)}"
            for key, value in (
                ("result", event.result),
                ("target", event.target),
                ("code", event.code),
            )
            if value is not None
        )
        self._stream.write(
            f"T2L_PROGRESS: stage={event.stage} status={event.status}{suffix}\n"
        )


def _package_version() -> str:
    try:
        return distribution_version("ai-auto-lrc")
    except PackageNotFoundError:
        from t2l import __version__

        return __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-auto-lrc", description="Align decoded lyrics to an audio file."
    )
    parser.add_argument("lyrics_file", type=Path)
    parser.add_argument("audio_file", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--timestamps", choices=("line", "word"), default="line")
    parser.add_argument(
        "--acoustic-model",
        choices=("Baseline", "MTL", "Baseline_BDR", "MTL_BDR"),
        default="MTL",
    )
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument(
        "--decoder", choices=("torchaudio", "librosa-mono"), default="torchaudio"
    )
    parser.add_argument("--separate-vocals", action="store_true")
    parser.add_argument(
        "--demucs-model", choices=("mdx", "mdx_extra", "mdx_q", "mdx_extra_q")
    )
    parser.add_argument("--demucs-index", type=int, choices=(-1, 0, 1, 2, 3))
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_package_version()}",
    )
    return parser


def _default_runtime_factory(
    config: RuntimeConfig,
    progress_observer: ProgressObserverPort,
):
    from t2l.composition import create_default_runtime

    return create_default_runtime(
        config,
        progress_observer=progress_observer,
    )


def _redact_text(value: object, *, multiline: bool) -> str:
    text = str(value)
    sensitive_values = {
        environment_value
        for name, environment_value in os.environ.items()
        if environment_value
        and _SENSITIVE_ENVIRONMENT_NAME.search(name)
    }
    for sensitive_value in sorted(sensitive_values, key=len, reverse=True):
        text = text.replace(sensitive_value, "<redacted-secret>")
    text = _SENSITIVE_ASSIGNMENT.sub("<redacted-secret>", text)
    text = _SENTINEL_SECRET.sub("<redacted-secret>", text)
    text = _QUOTED_ABSOLUTE_PATH.sub(
        lambda match: f"{match.group('quote')}<redacted-path>", text
    )
    text = _UNQUOTED_ABSOLUTE_PATH.sub("<redacted-path>", text)

    sanitized = []
    for character in text:
        if character == "\n" and multiline:
            sanitized.append(character)
        elif character == "\n":
            sanitized.append("\\n")
        elif character == "\r":
            sanitized.append("\\r")
        elif character == "\t" and multiline:
            sanitized.append("    ")
        elif ord(character) < 32 or ord(character) == 127:
            sanitized.append(f"\\x{ord(character):02x}")
        else:
            sanitized.append(character)
    return "".join(sanitized)


def _safe_message(value: object) -> str:
    return _redact_text(value, multiline=False)


def _write_stdout(payload: bytes, stream: TextIO) -> None:
    """Write canonical UTF-8 bytes and surface a closed downstream pipe."""

    binary = getattr(stream, "buffer", None)
    if binary is not None:
        binary.write(payload)
        binary.flush()
        return
    stream.write(payload.decode("utf-8"))
    stream.flush()


def _silence_broken_pipe(stream: TextIO) -> None:
    """Prevent interpreter shutdown from reporting a second pipe failure."""

    try:
        descriptor = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, descriptor)
        finally:
            os.close(devnull)
    except OSError:
        return


def _safe_traceback(error: BaseException) -> str:
    sections = []
    visited = set()

    def append_exception(current: BaseException) -> None:
        if id(current) in visited:
            return
        visited.add(id(current))
        if current.__cause__ is not None:
            append_exception(current.__cause__)
            sections.append(
                "\nThe above exception was the direct cause of the following "
                "exception:\n\n"
            )
        elif current.__context__ is not None and not current.__suppress_context__:
            append_exception(current.__context__)
            sections.append(
                "\nDuring handling of the above exception, another exception "
                "occurred:\n\n"
            )

        if current.__traceback__ is not None:
            sections.append("Traceback (most recent call last):\n")
            sections.extend(
                _redact_text(frame, multiline=True)
                for frame in traceback.format_tb(current.__traceback__)
            )
        exception_name = type(current).__qualname__
        sections.append(f"{exception_name}: {_safe_message(current)}\n")

    append_exception(error)
    return "".join(sections)


def _partial_details(result: object) -> tuple[int, int, int]:
    expected = result.expected_token_count
    aligned = len(result.spans)
    return expected, aligned, aligned


def _paths_alias(left: Path, right: Path) -> bool:
    """Return true when two CLI paths identify the same filesystem object."""

    try:
        if left.resolve(strict=False) == right.resolve(strict=False):
            return True
        if left.exists() and right.exists():
            return os.path.samefile(left, right)
    except OSError:
        # A later, stage-specific read/write operation will report inaccessible paths.
        return False
    return False


def _validate_output_target(args: argparse.Namespace) -> None:
    if args.output is None:
        return
    for label, source in (
        ("lyrics", args.lyrics_file),
        ("audio", args.audio_file),
    ):
        if _paths_alias(args.output, source):
            raise ConfigurationError(
                f"Output path must not replace the {label} input.",
                details={"field": "output", "conflict": label},
            )


def main(
    argv: Sequence[str] | None = None,
    *,
    runtime_factory: RuntimeFactory | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    factory = runtime_factory or _default_runtime_factory
    args = build_parser().parse_args(argv)
    observer: ProgressObserverPort = (
        _StderrObserver(stderr) if args.verbose else NullProgressObserver()
    )

    if not args.separate_vocals and (
        args.demucs_model is not None or args.demucs_index is not None
    ):
        error = ConfigurationError(
            "--demucs-model/--demucs-index require --separate-vocals."
        )
        stderr.write(f"{error.code}: {error}\n")
        return 2

    try:
        _validate_output_target(args)
        observer.emit(ProgressEvent(stage="lyrics_read", status="started"))
        lyrics = LyricsFileReader().read(args.lyrics_file)
        observer.emit(ProgressEvent(stage="lyrics_read", status="completed"))
        asset_root = args.asset_root.resolve() if args.asset_root is not None else None
        config = RuntimeConfig(
            asset_root=asset_root,
            device=args.device,
            offline=True,
            decoder=args.decoder,
        )
        separation = None
        if args.separate_vocals:
            separation = VocalSeparationOptions(
                demucs_model=args.demucs_model or "mdx_extra",
                demucs_index=(
                    args.demucs_index if args.demucs_index is not None else -1
                ),
            )
        request = AlignmentRequest(
            lyrics=lyrics,
            audio_path=args.audio_file,
            timestamp_mode=args.timestamps,
            acoustic_model=args.acoustic_model,
            allow_partial=args.allow_partial,
            vocal_separation=separation,
        )
        observer.emit(ProgressEvent(stage="runtime_create", status="started"))
        runtime = factory(config, observer)
        observer.emit(ProgressEvent(stage="runtime_create", status="completed"))
        result = runtime.process(request)
        payload = serialize_lrc(result.lrc)
        output_target = "stdout" if args.output is None else "file"
        observer.emit(
            ProgressEvent(
                stage="output",
                status="started",
                target=output_target,
            )
        )
        if args.output is None:
            _write_stdout(payload, stdout)
        else:
            AtomicLrcSink().write(args.output, result.lrc)
        observer.emit(
            ProgressEvent(
                stage="output",
                status="completed",
                target=output_target,
            )
        )
        if result.status == "partial":
            expected, aligned, first_gap = _partial_details(result)
            stderr.write(
                "T2L_ALIGNMENT_PARTIAL: alignment output is incomplete "
                f"expected={expected} aligned={aligned} first_gap={first_gap}\n"
            )
            return 3
        return 0
    except BrokenPipeError:
        _silence_broken_pipe(stdout)
        return 141
    except KeyboardInterrupt:
        return 130
    except T2LError as error:
        registration = registration_for(error)
        observer.emit(
            ProgressEvent(
                stage="error",
                status="failed",
                code=registration.code,
            )
        )
        message = (
            _safe_message(error)
            if registration.safe_message_policy == "redact"
            else "unexpected failure"
        )
        stderr.write(f"{registration.code}: {message}\n")
        return registration.cli_exit_code
    except Exception as error:
        registration = ERROR_REGISTRY["T2L_INTERNAL_ERROR"]
        observer.emit(
            ProgressEvent(
                stage="error",
                status="failed",
                code=registration.code,
            )
        )
        if args.debug:
            stderr.write(_safe_traceback(error))
        else:
            stderr.write(f"{registration.code}: unexpected failure\n")
        return registration.cli_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
