"""Checkout subprocess coverage; installed-console qualification lives in package tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "t2l.adapters.cli", *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )


def test_checkout_subprocess_argparse_failure_uses_real_process_streams():
    result = _run_cli()

    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr.startswith(b"usage: ai-auto-lrc")
    assert b"Traceback" not in result.stderr


def test_checkout_subprocess_verbose_failure_keeps_progress_on_stderr(tmp_path):
    result = _run_cli(
        str(tmp_path / "missing-lyrics.txt"),
        str(tmp_path / "audio.wav"),
        "--verbose",
    )

    assert result.returncode == 4
    assert result.stdout == b""
    assert result.stderr.decode("utf-8").splitlines() == [
        "T2L_PROGRESS: stage=lyrics_read status=started",
        "T2L_PROGRESS: stage=error status=failed code=T2L_LYRICS_INVALID",
        "T2L_LYRICS_INVALID: Unable to read lyrics file.",
    ]


def test_checkout_subprocess_default_failure_emits_no_progress(tmp_path):
    result = _run_cli(
        str(tmp_path / "missing-lyrics.txt"),
        str(tmp_path / "audio.wav"),
    )

    assert result.returncode == 4
    assert result.stdout == b""
    assert result.stderr == b"T2L_LYRICS_INVALID: Unable to read lyrics file.\n"


def test_cli_023_sigint_before_replace_returns_130_and_preserves_target(tmp_path):
    """CLI-023: SIGINT before replace preserves OLD and removes the temp file."""

    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("hello", encoding="utf-8")
    target = tmp_path / "result.lrc"
    target.write_bytes(b"OLD")
    script = r"""
import os
import signal
import sys
from types import SimpleNamespace

from t2l.adapters import output
from t2l.adapters.cli import main

def interrupt_before_replace(_source, _destination):
    os.kill(os.getpid(), signal.SIGINT)
    raise AssertionError('SIGINT did not interrupt replace')

output.os.replace = interrupt_before_replace
result = SimpleNamespace(lrc='NEW', status='complete')
runtime = SimpleNamespace(process=lambda _request: result)
raise SystemExit(
    main(sys.argv[1:], runtime_factory=lambda _config, _observer: runtime)
)
"""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(lyrics),
            str(tmp_path / "audio.wav"),
            "-o",
            str(target),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 130
    assert completed.stdout == b""
    assert completed.stderr == b""
    assert target.read_bytes() == b"OLD"
    assert not list(tmp_path.glob(f".{target.name}.*.tmp"))


def test_cli_024_closed_stdout_returns_141_without_secondary_error(tmp_path):
    """CLI-024: a closed stdout pipe exits 141 without traceback noise."""

    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("hello", encoding="utf-8")
    script = r"""
import sys
from types import SimpleNamespace

from t2l.adapters.cli import main

result = SimpleNamespace(lrc='[00:00.000]hello', status='complete')
runtime = SimpleNamespace(process=lambda _request: result)
raise SystemExit(
    main(sys.argv[1:], runtime_factory=lambda _config, _observer: runtime)
)
"""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    read_descriptor, write_descriptor = os.pipe()
    os.close(read_descriptor)
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(lyrics),
                str(tmp_path / "audio.wav"),
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdout=write_descriptor,
            stderr=subprocess.PIPE,
        )
    finally:
        os.close(write_descriptor)
    _stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 141
    assert stderr == b""


def test_cli_027_c_locale_preserves_unicode_paths_lyrics_and_stdout(tmp_path):
    """CLI-027: C locale does not change UTF-8 input or output bytes."""

    unicode_root = tmp_path / "歌词路径"
    unicode_root.mkdir()
    lyrics = unicode_root / "歌词.txt"
    lyrics.write_text("世界\n", encoding="utf-8")
    script = r"""
import sys
from types import SimpleNamespace

from t2l.adapters.cli import main

class Runtime:
    def process(self, request):
        assert request.lyrics == ('\u4e16\u754c',)
        return SimpleNamespace(lrc='[00:00.000]\u4e16\u754c', status='complete')

raise SystemExit(
    main(sys.argv[1:], runtime_factory=lambda _config, _observer: Runtime())
)
"""
    environment = os.environ.copy()
    environment.pop("PYTHONIOENCODING", None)
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "LC_ALL": "C",
            "PYTHONCOERCECLOCALE": "0",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "0",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(lyrics),
            str(unicode_root / "音频.wav"),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode(
        "utf-8", errors="replace"
    )
    assert completed.stdout == "[00:00.000]世界\n".encode()
    assert completed.stderr == b""
