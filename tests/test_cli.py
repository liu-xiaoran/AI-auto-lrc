import pytest

from main import build_parser, to_standard_lrc


def test_to_standard_lrc_removes_word_timestamps_with_long_minutes():
    enhanced = "[100:01.234]<100:01.234>Hello<09:02.003> world"

    assert to_standard_lrc(enhanced) == "[100:01.234]Hello world"


def test_parser_defaults_and_integer_index():
    args = build_parser().parse_args(["lyrics.txt", "song.mp3", "-i", "2"])

    assert args.format == "lrc"
    assert args.line_only == 0
    assert args.vocalize == 1
    assert args.idx == 2


@pytest.mark.parametrize(
    "arguments",
    [
        ["lyrics.txt", "song.mp3", "--format", "srt"],
        ["lyrics.txt", "song.mp3", "--line_only", "2"],
        ["lyrics.txt", "song.mp3", "--vocalize", "-1"],
        ["lyrics.txt", "song.mp3", "--idx", "4"],
        ["lyrics.txt", "song.mp3", "--model", "unknown"],
    ],
)
def test_parser_rejects_unsupported_values(arguments):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(arguments)

    assert exc_info.value.code == 2
