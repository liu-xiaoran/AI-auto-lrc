
import pytest

from t2l.adapters.lyrics_io import LyricsFileReader
from t2l.errors import LyricsInputError


def test_utf8_bom_and_crlf_are_normalized_to_logical_lines(tmp_path):
    source = tmp_path / "歌词.txt"
    source.write_bytes(b"\xef\xbb\xbfhello\r\nworld\r\n")

    result = LyricsFileReader(detector=lambda _: "UTF-8-SIG").read(source)

    assert result == ("hello", "world")


def test_gb2312_detector_result_is_normalized_to_gbk(tmp_path):
    source = tmp_path / "歌词.txt"
    source.write_bytes("中文歌词".encode("gbk"))

    result = LyricsFileReader(detector=lambda _: "GB2312").read(source)

    assert result == ("中文歌词",)


def test_missing_detector_result_falls_back_to_strict_utf8(tmp_path):
    source = tmp_path / "lyrics.txt"
    source.write_bytes(b"hello")

    assert LyricsFileReader(detector=lambda _: None).read(source) == ("hello",)


def test_decode_failure_is_a_lyrics_error_with_cause(tmp_path):
    source = tmp_path / "broken.txt"
    source.write_bytes(b"\xff")

    with pytest.raises(LyricsInputError) as exc_info:
        LyricsFileReader(detector=lambda _: "utf-8").read(source)

    assert isinstance(exc_info.value.__cause__, UnicodeDecodeError)
    assert exc_info.value.details["path"] == str(source)


def test_missing_file_fails_in_lyrics_stage(tmp_path):
    source = tmp_path / "missing.txt"

    with pytest.raises(LyricsInputError) as exc_info:
        LyricsFileReader().read(source)

    assert isinstance(exc_info.value.__cause__, FileNotFoundError)

