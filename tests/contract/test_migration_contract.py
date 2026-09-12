"""Executable governance for the documented v1 to v2 migration."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

from t2l import AlignmentRequest, RuntimeConfig, VocalSeparationOptions, process
from t2l.adapters.cli import build_parser
from t2l.model_profiles import load_legacy_v1_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPOSITORY_ROOT / "docs" / "V1_TO_V2_MIGRATION.zh-CN.md"


def _migration_rows() -> dict[str, tuple[str, str, str, str]]:
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    table = text.split("<!-- v1-cli-migration-start -->", 1)[1].split(
        "<!-- v1-cli-migration-end -->", 1
    )[0]
    rows: dict[str, tuple[str, str, str, str]] = {}
    for line in table.splitlines():
        if not line.startswith("|") or line.startswith("|---") or "v1 参数" in line:
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        assert len(cells) == 5, line
        rows[cells[0].strip("`")] = cells[1:]
    return rows


def _find_spec(name: str):
    try:
        return importlib.util.find_spec(name)
    except ModuleNotFoundError:
        return None


def test_mig_001_every_v1_cli_argument_has_one_explicit_disposition():
    """MIG-001: every v1 CLI parameter has a deletion or replacement decision."""

    rows = _migration_rows()
    assert set(rows) == {
        "lrc_file",
        "music_file",
        "-f/--format",
        "-l/--line_only",
        "-v/--vocalize",
        "-m/--model",
        "-i/--idx",
        "-o/--out_dir",
    }
    assert all(all(cell for cell in row) for row in rows.values())
    assert rows["-f/--format"][1] == "无"
    assert "删除" in rows["-f/--format"][3]
    for name in set(rows) - {"-f/--format"}:
        assert rows[name][1] != "无", name
        assert any(
            action in rows[name][3]
            for action in ("重命名", "替换", "目录变成")
        ), name


def test_mig_003_documented_defaults_match_cli_and_public_dataclasses():
    """MIG-003: migration defaults match argparse and the public v2 contracts."""

    args = build_parser().parse_args(["lyrics.txt", "audio.wav"])
    assert vars(args) == {
        "acoustic_model": "MTL",
        "allow_partial": False,
        "asset_root": None,
        "audio_file": Path("audio.wav"),
        "debug": False,
        "decoder": "torchaudio",
        "demucs_index": None,
        "demucs_model": None,
        "device": "auto",
        "lyrics_file": Path("lyrics.txt"),
        "output": None,
        "separate_vocals": False,
        "timestamps": "line",
        "verbose": False,
    }

    request = AlignmentRequest(lyrics=("a",), audio_path=Path("audio.wav"))
    assert request.timestamp_mode == "line"
    assert request.acoustic_model == "MTL"
    assert request.allow_partial is False
    assert request.vocal_separation is None

    config = RuntimeConfig()
    assert config.device == "auto"
    assert config.offline is True
    assert config.decoder == "torchaudio"
    assert config.seed == 0
    assert config.max_alignment_bytes == 536_870_912

    separation = VocalSeparationOptions()
    assert separation.demucs_model == "mdx_extra"
    assert separation.demucs_index == -1

    text = MIGRATION_PATH.read_text(encoding="utf-8")
    for literal in (
        '默认 acoustic model 为 `MTL`',
        'decoder 为 `torchaudio`',
        'device 为 `auto`',
        'timestamps 为 `line`',
        '`max_alignment_bytes=536870912`',
    ):
        assert literal in text


def test_mig_004_removed_v1_modules_fail_and_document_v2_replacements():
    """MIG-004: removed v1 imports stay absent and the guide names replacements."""

    removed = {
        "main": ("`main.py`", "`ai-auto-lrc` console script"),
        "t2l.t2l": ("`t2l.t2l.process`", "`t2l.process(AlignmentRequest, runtime=...)`"),
        "t2l.init_model": ("`t2l.init_model`", "`create_runtime(RuntimeConfig(...))`"),
        "t2l.mtl.wrapper": ("`t2l.mtl.wrapper`", "`AlignmentRequest.acoustic_model`"),
        "ext.lrc2json": ("`ext.lrc2json`", "不在 v2 core 范围内"),
        "ext.traditional_to_simplified": (
            "`ext.traditional_to_simplified`",
            "不在 v2 core 范围内",
        ),
    }
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    for module, (documented_name, replacement) in removed.items():
        assert _find_spec(module) is None, module
        assert documented_name in text
        assert replacement in text

    signature = inspect.signature(process)
    assert tuple(signature.parameters) == ("request", "runtime")
    assert signature.parameters["runtime"].kind is inspect.Parameter.KEYWORD_ONLY


def test_doc_003_readmes_migration_defaults_and_profile_stay_aligned():
    """DOC-003: CLI/API defaults and the manifest profile agree with documentation."""

    args = build_parser().parse_args(["lyrics.txt", "audio.wav"])
    profile = load_legacy_v1_profile()
    assert profile.profile_id == "legacy-v1"

    documents = {
        name: (REPOSITORY_ROOT / name).read_text(encoding="utf-8")
        for name in (
            "README.md",
            "README_zh.md",
            "docs/V1_TO_V2_MIGRATION.zh-CN.md",
        )
    }
    for text in documents.values():
        assert "legacy-v1" in text
        assert "MTL" in text
        assert "torchaudio" in text
        assert "line" in text
        assert "Demucs" in text

    assert args.acoustic_model == "MTL"
    assert args.decoder == "torchaudio"
    assert args.timestamps == "line"
    assert args.allow_partial is False
    assert args.separate_vocals is False
    assert RuntimeConfig().offline is True
