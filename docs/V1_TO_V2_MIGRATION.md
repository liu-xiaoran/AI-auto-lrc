# AI-auto-lrc v1 to v2 migration guide

[English (primary)](V1_TO_V2_MIGRATION.md) · [简体中文](V1_TO_V2_MIGRATION.zh-CN.md) · [Documentation index](README.md)

This guide is for integrations using the v1 CLI or Python `process()`. v2 is an explicitly breaking version. The `legacy-v1` profile preserves the LegacyV1 model numerical protocol, but v2 does not ship old modules or signatures, five-element model tuples, default Demucs, implicit decoder fallback, or the old combination of enhanced LRC on stdout plus an automatically written standard LRC file.

Migration is complete when callers use v2 structured requests/results, an explicit asset root and output policy, and distinguish complete results, explicitly accepted partial results, and strict failures. Keeping an old command running is not the acceptance criterion.

## 1. CLI parameter migration matrix

<!-- v1-cli-migration-start -->
| v1 parameter | v1 default | v2 replacement | v2 default | Disposition |
|---|---|---|---|---|
| `lrc_file` | Required | `lyrics_file` positional argument | Required | Renamed; CLI still owns file decoding |
| `music_file` | Required | `audio_file` positional argument | Required | Renamed; no longer determines an implicit output filename |
| `-f/--format` | `lrc` | None | LRC | Removed; this v2 scope only ships LRC, without a single-value switch |
| `-l/--line_only` | `0` | `--timestamps` with `line` or `word` | `line` | Replaced; v1 `0` maps to `word`, v1 `1` to `line`; default changes from word to line |
| `-v/--vocalize` | `1` | `--separate-vocals` | Off | Replaced by a boolean flag; default changes from on to off |
| `-m/--model` | `mdx_extra` | `--demucs-model` | `mdx_extra` | Renamed; valid only with `--separate-vocals`; distinct from `--acoustic-model` |
| `-i/--idx` | `-1` | `--demucs-index` | `-1` | Renamed; valid only with `--separate-vocals` |
| `-o/--out_dir` | `demofile` | `-o/--output` | None | Directory becomes a full file path; omission writes only stdout, without an automatic standard-LRC copy |
<!-- v1-cli-migration-end -->

v2 adds `--acoustic-model`, `--allow-partial`, `--device`, `--asset-root`, `--decoder`, `--verbose`, and `--debug`. Each expresses an independent policy; do not infer one implicitly from the environment or available dependencies. Defaults are acoustic model `MTL`, decoder `torchaudio`, device `auto`, timestamps `line`, partial off, and vocal separation off.

### 1.1 CLI output changes

v1 wrote enhanced LRC and progress to stdout and overwrote a standard LRC file in `out_dir`. v2 uses exactly one output destination:

- Without `-o`: stdout contains only UTF-8 LRC and exactly one trailing newline; logs, progress, and errors go to stderr.
- With `-o FILE`: stdout is empty and LRC atomically replaces the full target path.
- Output must not alias the lyric/audio input or be a directory, FIFO, device, or symlink; symlink ancestors are also rejected.
- `--timestamps line` directly generates standard line LRC; `--timestamps word` directly generates token timestamp LRC. There is no separate enhanced-to-standard conversion step.

Before:

```bash
python main.py lyrics.txt song.mp3 --line_only 1 --vocalize 0 --out_dir output
```

After:

```bash
uv run ai-auto-lrc lyrics.txt song.mp3 \
  --asset-root /absolute/path/to/assets \
  --timestamps line \
  --decoder torchaudio \
  --acoustic-model MTL \
  -o output/song.lrc
```

## 2. Python API parameter migration matrix

| v1 `process()` parameter | v2 replacement | Migration notes |
|---|---|---|
| `txt_lines` | `AlignmentRequest.lyrics` | Must be a tuple of decoded strings |
| `audio_file` | `AlignmentRequest.audio_path` | Must be a `pathlib.Path` |
| `mtl_model` | `AlignmentRequest.acoustic_model` | Accepts only the four public route names, not a five-element preloaded tuple |
| `demucs_model` | `VocalSeparationOptions.demucs_model` | Construct options only for explicit vocal separation |
| `demucs_idx` | `VocalSeparationOptions.demucs_index` | Accepts only `-1..3`, validated at construction |
| `line_only` | `AlignmentRequest.timestamp_mode` | `True -> "line"`, `False -> "word"`; v2 defaults to `line` |
| `out_file` | Caller-managed output or v2 CLI `-o` | API does not write LRC; consume `AlignmentResult.lrc` after success |
| `verbose` | CLI `--verbose` or a custom observer boundary | Top-level API does not actively print progress; dependencies may emit warnings |
| `vocalize` | `AlignmentRequest.vocal_separation` | `None` means off; Demucs is no longer on by default |
| `format` | None | Removed; this v2 scope returns a structured LRC result |

v1 returned a bare LRC string. v2 returns `AlignmentResult`; callers must inspect at least `status`, `lrc`, `spans`, `expected_token_count`, `model_profile`, `timebase`, and `diagnostics`. Runtime configuration is separate in `RuntimeConfig`: `asset_root` must be a controlled absolute root; `offline` is fixed to `True`; defaults are `decoder="torchaudio"`, `device="auto"`, `seed=0`, and `max_alignment_bytes=536870912`.

Runtime preparation still reads inputs and creates private asset copies. Optional Demucs does not fully enforce offline configuration and may download weights. See the [technical guide](TECHNICAL_GUIDE.md) for these limits.

Migrated Python example:

```python
from pathlib import Path

from t2l import AlignmentRequest, RuntimeConfig, create_runtime

runtime = create_runtime(
    RuntimeConfig(
        asset_root=Path("/absolute/path/to/assets"),
        decoder="torchaudio",
        offline=True,
    )
)
result = runtime.process(
    AlignmentRequest(
        lyrics=("First line", "Second line"),
        audio_path=Path("song.mp3"),
        timestamp_mode="line",
        acoustic_model="MTL",
    )
)
if result.status != "complete":
    raise RuntimeError("alignment was not complete")
print(result.lrc)
```

## 3. Retired entrypoints

These old modules and symbols were deliberately removed without compatibility shims:

| v1 entrypoint | v2 handling |
|---|---|
| `main.py` | Use the installed `ai-auto-lrc` console script |
| `t2l.t2l.process` | Use top-level `t2l.process(AlignmentRequest, runtime=...)` or `runtime.process(request)` |
| `t2l.init_model` | Use `create_runtime(RuntimeConfig(...))`; models remain private lazy runtime resources |
| `t2l.mtl.wrapper` | No longer a public API; select `AlignmentRequest.acoustic_model` |
| `ext.lrc2json` | Outside v2 core scope |
| `ext.traditional_to_simplified` | Outside v2 core scope |

If imports fail, update the caller. Do not add old source paths to `PYTHONPATH` or copy deleted files into a wheel to bypass migration.

## 4. Exit codes and automation

Callers must distinguish these outcomes:

| Exit code | Meaning | Consumable LRC |
|---:|---|---|
| `0` | Complete | Yes |
| `3` | Explicit `--allow-partial` with a non-empty contiguous prefix | Yes, but label it incomplete |
| `7` | Alignment failure or strict rejection of partial | No |

The frozen LegacyV1 backend does not yet have approved natural non-empty partial generation semantics. `3` is reserved by the public contract, not proof that the real backend reliably produces such results. Keep strict behavior as the automation default; accept both `0` and `3` only when the application explicitly accepts incomplete output.

```bash
set +e
ai-auto-lrc lyrics.txt song.mp3 --asset-root /absolute/path/to/assets -o output.lrc
status=$?
set -e

case "$status" in
  0) echo "complete" ;;
  3) echo "partial output requires explicit downstream handling" >&2 ;;
  7) echo "strict alignment failure; no output may be consumed" >&2; exit 7 ;;
  *) exit "$status" ;;
esac
```

## 5. Migration acceptance checklist

1. Stop importing retired modules and persisting five-element model tuples across processes or versions.
2. Supply a controlled absolute asset root per call; do not rely on CWD, user caches, or online downloads for the core path.
3. Explicitly select or accept documented defaults for timestamps, decoder, acoustic model, partial, and vocal separation.
4. Inspect structured API status; consume only one CLI output destination and distinguish exit codes `0`, `3`, and `7`.
5. Run the installed console script outside the source tree with empty `PYTHONPATH`.
6. Before release, satisfy the original plan's two-platform cold-wheelhouse, complete resource-budget, recovery, signing, and rollback gates. A passing migration smoke test is not Release Go.
