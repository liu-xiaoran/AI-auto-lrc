"""LRC byte serialization and durable atomic filesystem output."""

from __future__ import annotations

import errno
import os
import stat
import tempfile
from contextlib import suppress
from pathlib import Path

from t2l.errors import OutputWriteError


def _validate_destination(destination: Path) -> None:
    """Reject symlink traversal and non-regular output targets."""

    for candidate in (destination, *destination.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise OSError(errno.ELOOP, "refusing an output path containing a symlink")

    try:
        metadata = destination.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError(
            errno.EINVAL,
            "refusing to replace a non-regular output target",
        )


def serialize_lrc(lrc: str) -> bytes:
    """Encode UTF-8 LRC with exactly one trailing LF byte."""

    if not isinstance(lrc, str):
        raise TypeError("lrc must be a string")
    return (lrc.rstrip("\r\n") + "\n").encode("utf-8")


class AtomicLrcSink:
    """Atomically replace an LRC file without exposing partial content."""

    def write(self, target: str | os.PathLike[str], lrc: str) -> bytes:
        destination = Path(target)
        temporary_path: Path | None = None
        try:
            payload = serialize_lrc(lrc)
            _validate_destination(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            _validate_destination(destination)

            descriptor, temporary_name = tempfile.mkstemp(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            _validate_destination(destination)
            os.replace(temporary_path, destination)
            temporary_path = None
            return payload
        except Exception as error:
            raise OutputWriteError(
                f"Could not write LRC output {os.fspath(destination)!r}",
                code="T2L_OUTPUT_WRITE_FAILED",
                stage="output",
                details={"path": os.fspath(destination)},
            ) from error
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)


__all__ = ["AtomicLrcSink", "serialize_lrc"]
