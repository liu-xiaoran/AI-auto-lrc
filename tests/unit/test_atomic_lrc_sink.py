from __future__ import annotations

import errno
import os
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.mark.parametrize("lrc", ["line", "line\n", "line\n\n\n", "line\r\n"])
def test_serializer_emits_exactly_one_trailing_newline(lrc):
    """OUT-009: serialization always emits exactly one trailing LF."""

    from t2l.adapters.output import serialize_lrc

    assert serialize_lrc(lrc) == b"line\n"


def test_atomic_sink_creates_parent_and_replaces_in_same_directory(tmp_path, monkeypatch):
    from t2l.adapters import output

    target = tmp_path / "new" / "lyrics.lrc"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"OLD")
    calls = []
    real_replace = os.replace

    def recording_replace(source, destination):
        calls.append((source, destination))
        return real_replace(source, destination)

    monkeypatch.setattr(output.os, "replace", recording_replace)

    written = output.AtomicLrcSink().write(target, "NEW")

    assert written == b"NEW\n"
    assert target.read_bytes() == b"NEW\n"
    assert len(calls) == 1
    assert os.path.dirname(calls[0][0]) == str(target.parent)
    assert os.fspath(calls[0][1]) == str(target)
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


def test_atomic_sink_creates_a_missing_parent_directory(tmp_path):
    from t2l.adapters.output import AtomicLrcSink

    target = tmp_path / "missing" / "nested" / "lyrics.lrc"

    AtomicLrcSink().write(target, "NEW")

    assert target.read_bytes() == b"NEW\n"


@pytest.mark.parametrize("failure_point", ["write", "flush", "fsync", "replace"])
def test_failure_preserves_old_target_and_cause(tmp_path, monkeypatch, failure_point):
    from t2l.adapters import output

    target = tmp_path / "lyrics.lrc"
    target.write_bytes(b"OLD")
    injected = OSError(
        errno.EIO if failure_point == "fsync" else errno.EACCES,
        failure_point,
    )
    replace_calls = 0

    if failure_point in {"write", "flush"}:
        real_fdopen = output.os.fdopen

        class FailingFile:
            def __init__(self, descriptor, mode):
                self._file = real_fdopen(descriptor, mode)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self._file.__exit__(*args)

            def write(self, payload):
                if failure_point == "write":
                    raise injected
                return self._file.write(payload)

            def flush(self):
                if failure_point == "flush":
                    raise injected
                return self._file.flush()

            def fileno(self):
                return self._file.fileno()

        monkeypatch.setattr(output.os, "fdopen", FailingFile)
    elif failure_point == "fsync":
        monkeypatch.setattr(output.os, "fsync", lambda _fd: (_ for _ in ()).throw(injected))
    else:
        def fail_replace(_source, _destination):
            nonlocal replace_calls
            replace_calls += 1
            raise injected

        monkeypatch.setattr(output.os, "replace", fail_replace)

    with pytest.raises(Exception) as exc_info:
        output.AtomicLrcSink().write(target, "NEW")

    assert exc_info.value.code == "T2L_OUTPUT_WRITE_FAILED"
    assert exc_info.value.__cause__ is injected
    assert target.read_bytes() == b"OLD"
    if failure_point != "replace":
        assert replace_calls == 0
    else:
        assert replace_calls == 1
    assert not list(tmp_path.glob(f".{target.name}.*.tmp"))


@pytest.mark.parametrize("failure_point", ["write", "flush", "fsync", "replace"])
def test_failure_without_an_existing_target_leaves_no_partial_file(
    tmp_path, monkeypatch, failure_point
):
    """OUT-006: every pre-commit failure leaves a missing target missing."""

    from t2l.adapters import output

    target = tmp_path / "lyrics.lrc"
    injected = OSError(
        errno.ENOSPC if failure_point != "replace" else errno.EACCES,
        failure_point,
    )
    replace_calls = 0

    if failure_point in {"write", "flush"}:
        real_fdopen = output.os.fdopen

        class FailingFile:
            def __init__(self, descriptor, mode):
                self._file = real_fdopen(descriptor, mode)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self._file.__exit__(*args)

            def write(self, payload):
                if failure_point == "write":
                    raise injected
                return self._file.write(payload)

            def flush(self):
                if failure_point == "flush":
                    raise injected
                return self._file.flush()

            def fileno(self):
                return self._file.fileno()

        monkeypatch.setattr(output.os, "fdopen", FailingFile)
    elif failure_point == "fsync":
        monkeypatch.setattr(
            output.os,
            "fsync",
            lambda _fd: (_ for _ in ()).throw(injected),
        )
    else:

        def fail_replace(_source, _destination):
            nonlocal replace_calls
            replace_calls += 1
            raise injected

        monkeypatch.setattr(output.os, "replace", fail_replace)

    with pytest.raises(output.OutputWriteError) as exc_info:
        output.AtomicLrcSink().write(target, "NEW")

    assert exc_info.value.__cause__ is injected
    assert not target.exists()
    assert replace_calls == (1 if failure_point == "replace" else 0)
    assert not list(tmp_path.glob(f".{target.name}.*.tmp"))


def test_symlink_target_is_rejected_without_touching_link_target(tmp_path):
    """OUT-007: a symlink target is rejected without following it."""

    from t2l.adapters.output import AtomicLrcSink

    link_target = tmp_path / "outside.lrc"
    link_target.write_bytes(b"OLD")
    target = tmp_path / "lyrics.lrc"
    target.symlink_to(link_target)

    with pytest.raises(Exception) as exc_info:
        AtomicLrcSink().write(target, "NEW")

    assert exc_info.value.code == "T2L_OUTPUT_WRITE_FAILED"
    assert target.is_symlink()
    assert link_target.read_bytes() == b"OLD"
    assert not list(tmp_path.glob(f".{target.name}.*.tmp"))


def test_concurrent_writes_never_produce_partial_or_mixed_bytes(tmp_path):
    """OUT-008: concurrent writers commit one complete candidate."""

    from t2l.adapters.output import AtomicLrcSink, serialize_lrc

    target = tmp_path / "lyrics.lrc"
    candidates = ("A" * 50_000, "B" * 50_000)
    sink = AtomicLrcSink()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda content: sink.write(target, content), candidates))

    assert target.read_bytes() in {serialize_lrc(value) for value in candidates}
    assert not list(tmp_path.glob(f".{target.name}.*.tmp"))


def test_keyboard_interrupt_is_not_wrapped_and_cleans_temp(tmp_path, monkeypatch):
    from t2l.adapters import output

    target = tmp_path / "lyrics.lrc"
    target.write_bytes(b"OLD")
    monkeypatch.setattr(
        output.os,
        "fsync",
        lambda _fd: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        output.AtomicLrcSink().write(target, "NEW")

    assert target.read_bytes() == b"OLD"
    assert not list(tmp_path.glob(f".{target.name}.*.tmp"))
