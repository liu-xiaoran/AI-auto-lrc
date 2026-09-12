# User guide

[English (primary)](USER_GUIDE.md) · [简体中文](USER_GUIDE.zh-CN.md) · [Documentation index](README.md)

## 1. Get the current development version

Prepare Git, Git LFS, uv, and Python 3.11. The first dependency and model downloads may need network access. For restricted networks, provision dependency caches and complete assets beforehand.

```bash
git clone --branch main https://github.com/liu-xiaoran/AI-auto-lrc.git
cd AI-auto-lrc
git lfs install
git lfs pull
uv sync --frozen --python 3.11 --group test
uv run --frozen --no-sync ai-auto-lrc --help
```

For an existing checkout, preserve local changes before switching or pulling a branch; do not discard uncommitted work just to follow these commands. v2 is integrated into `main`, the installation entrypoint for this guide. Use only `pyproject.toml` and `uv.lock` as installation inputs; do not restore legacy `requirements.txt` or `Pipfile`.

The asset root must contain all six files below. Downloaded files must not remain Git LFS pointers:

```text
checkpoints/checkpoint_Baseline
checkpoints/checkpoint_MTL
checkpoints/checkpoint_BDR
lid.176.ftz
assets/nltk_data/corpora/cmudict.zip
assets/nltk_data/taggers/averaged_perceptron_tagger.zip
```

The three checkpoints and fastText file are managed by LFS; the NLTK zip files accompany the source. The runtime checks sizes and SHA-256 against the bundled manifest. Do not substitute unknown models with the same filenames or edit the manifest to bypass errors. Wheels contain the manifest, but these runtime assets must be provisioned separately with an explicit asset-root path.

## 2. Run the repository example

Run this from the repository root. `pwd -P` avoids symlink directories. The output uses a regular directory inside the repository; an existing file at that path will be replaced.

```bash
PROJECT_ROOT="$(pwd -P)"
uv run --offline --frozen --no-sync ai-auto-lrc \
  "$PROJECT_ROOT/demofile/original_txt.txt" \
  "$PROJECT_ROOT/demofile/original_track.mp3" \
  --asset-root "$PROJECT_ROOT" --device cpu \
  -o "$PROJECT_ROOT/output/demo.lrc"
```

Terminal progress is not completion. Check for exit code 0 and open the generated file. The recorded example produced 58 lines with monotonic timestamps. Correct line counts and formatting do not replace listening to assess alignment accuracy.

## 3. Process your own recording

Prepare lyrics that exactly match the recording. Prefer UTF-8 with one phrase per line, excluding titles, credits, and other text that is not sung. Live versions, edits, intros, or different lyric versions can affect results. The CLI removes existing time tags, but is not a general parser for complex LRC documents.

Replace the placeholders with actual paths, retaining quotes around paths with spaces:

```bash
uv run --offline --frozen --no-sync ai-auto-lrc \
  "/absolute/path/lyrics.txt" "/absolute/path/song.wav" \
  --asset-root "/absolute/path/AI-auto-lrc" --device cpu \
  -o "/absolute/path/output/song.lrc"
```

Outside the repository, use the installed environment's executable directly, for example `/absolute/path/AI-auto-lrc/.venv/bin/ai-auto-lrc`, and supply the asset root explicitly. Do not rely on arbitrary working directories to locate models. Output ancestors must not be symlinks. On macOS, `/var` often points to `/private/var`; use the real path.

Common choices:

| Need | Option/method |
|---|---|
| Standard line LRC for players | Default, or `--timestamps line` |
| Token timestamps | `--timestamps word`; verify player compatibility |
| Acoustic route | `--acoustic-model Baseline`, `MTL`, `Baseline_BDR`, or `MTL_BDR` |
| Reproduce the local CPU path | `--device cpu` |
| Write to stdout | Omit `-o`; shell `>` redirection does not provide the program's atomic output protections |
| More diagnostics | `--verbose`; use `--debug` for internal errors, and inspect paths/content before sharing logs |
| Explicitly accept incomplete output | `--allow-partial`; a non-empty contiguous prefix returns 3; do not use it as a general failure-retry policy |

Do not automatically switch decoder, accept partial, or add vocal separation to hide failures. For batches, record an exit code per song and use distinct output files. Start by reusing a runtime serially to assess capacity; do not assume threads scale linearly.

## 4. Python integration

Run the following in an environment with the project installed. Replace the paths. API `lyrics` is a tuple of decoded strings, not a lyric filename.

```python
from pathlib import Path
from t2l import AlignmentRequest, RuntimeConfig, create_runtime

asset_root = Path("/absolute/path/AI-auto-lrc").resolve()
lyrics_path = Path("/absolute/path/lyrics.txt")
audio_path = Path("/absolute/path/song.wav")
lines = tuple(lyrics_path.read_text(encoding="utf-8-sig").splitlines())
runtime = create_runtime(RuntimeConfig(asset_root=asset_root, device="cpu"))
result = runtime.process(AlignmentRequest(lyrics=lines, audio_path=audio_path))
print(result.status)
print(result.lrc)
# The caller saves output. Path.write_text lacks the CLI sink's full protections.
```

Reuse the runtime for multiple recordings. See the [technical guide](TECHNICAL_GUIDE.md) for structured results and error types.

## 5. Exit codes and troubleshooting

“Output” below refers to the current run. A file from a previous run may remain after failure, so file existence alone does not establish current success.

| Exit code | Meaning | Action |
|---:|---|---|
| 0 | Complete success | Check text, line count, monotonic times, and listen |
| 1 | Unexpected internal error | Retain the command and stderr; use debug diagnostics |
| 2 | Invalid command/configuration | Check help, paths, and parameter combinations |
| 3 | Explicitly allowed partial result | Label it incomplete; do not claim complete success |
| 4 | Lyric input error | Check encoding, empty text, and lyric content |
| 5 | Decode/separation error | Check readability, format support, and unintended separation |
| 6 | Asset/model/device error | Check LFS, all six assets, manifest, and Python/device environment |
| 7 | Alignment failure or strict rejection of partial | Check lyric/recording versions and retain the failure |
| 8 | Output write failure | Check canonical paths, permissions, symlinks, input aliases, and target type |

Install optional Demucs dependencies with `uv sync --frozen --extra vocals --group test`, and explicitly pass `--separate-vocals` to use them. This path may download weights and lacks full offline and quality qualification. `RuntimeConfig.offline=True` does not guarantee that this optional path avoids networking. The default workflow in this guide does not require it.

## 6. Updating and verification

After updating source, run `uv sync --frozen --python 3.11 --group test` again and repeat the example. Do not infer model readiness from `--help`, import success, or green unit tests alone. See [project status](PROJECT_STATUS.md) for completed and deferred scope, and the [technical guide](TECHNICAL_GUIDE.md) for developer checks.
