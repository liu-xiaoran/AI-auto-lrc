from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from t2l.errors import LyricsInputError

EncodingDetector = Callable[[bytes], str | None]


def _detect_encoding(data: bytes) -> str | None:
    from chardet.universaldetector import UniversalDetector

    detector = UniversalDetector()
    lines = data.splitlines(keepends=True)
    for count, line in enumerate(lines, start=1):
        detector.feed(line)
        if detector.done and count > 3:
            break
    detector.close()
    return detector.result.get("encoding")


class LyricsFileReader:
    def __init__(self, *, detector: EncodingDetector | None = None) -> None:
        self._prefer_utf8 = detector is None
        self._detector = detector or _detect_encoding

    def read(self, path: Path) -> tuple[str, ...]:
        try:
            data = path.read_bytes()
        except (OSError, ValueError) as cause:
            raise LyricsInputError(
                "Unable to read lyrics file.", details={"path": str(path)}
            ) from cause

        if self._prefer_utf8:
            try:
                return tuple(data.decode("utf-8-sig", errors="strict").splitlines())
            except UnicodeDecodeError:
                pass

        encoding = self._detector(data) or "utf-8"
        if encoding.upper() == "GB2312":
            encoding = "GBK"
        try:
            text = data.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError) as cause:
            raise LyricsInputError(
                "Unable to decode lyrics file.",
                details={"path": str(path), "encoding": encoding},
            ) from cause
        return tuple(text.splitlines())
