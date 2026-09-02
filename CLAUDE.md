# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**track-lrc-align** is a Python inference CLI that aligns lyrics to audio and produces timestamped LRC output at word or line granularity. It supports Chinese, Japanese, Korean, English, and Russian.

The supported workflow is inference. Training/evaluation scripts under `t2l/mtl/` are not self-contained in this checkout: they reference missing modules and external data dependencies, so do not assume they are runnable.

## Setup and Commands

Use Python 3.9 or 3.10. Model checkpoints and the fastText language-identification model are stored with Git LFS.

```bash
git lfs install
git lfs pull
pip install -r requirements.txt
```

Run commands from the repository root. Both checkpoint paths and `lid.176.ftz` are resolved relative to the current working directory.

```bash
# Demo
python main.py demofile/original_txt.txt demofile/original_track.mp3

# General usage
python main.py <lyrics_file> <audio_file> \
  -f lrc \
  -l 0 \
  -v 1 \
  -m mdx_extra \
  -i -1 \
  -o output
```

CLI options:
- `-f/--format`: only `lrc` is accepted; SRT output is not implemented.
- `-l/--line_only`: `0` for enhanced word-timed LRC, `1` for line-level output.
- `-v/--vocalize`: `1` to separate vocals with Demucs, `0` to align the original audio directly.
- `-m/--model`: Demucs model (`mdx`, `mdx_extra`, `mdx_q`, or `mdx_extra_q`).
- `-i/--idx`: Demucs sub-model index; `-1` uses the ensemble, while `0`–`3` selects one sub-model.
- `-o/--out_dir`: output directory, created by the CLI when absent.

Tests use `pytest` and are designed to run without loading checkpoints, downloading Demucs models, or requiring a GPU.

```bash
# Full lightweight regression suite
python -m pytest -q

# Single test module or test
python -m pytest tests/test_alignment.py -q
python -m pytest tests/test_alignment.py::test_alignment_minimum_valid_input_is_quiet -q

# Syntax check
python -m compileall main.py t2l tests
```

There is no configured linter, formatter, type checker, build system, or CI workflow in this repository. Do not invent commands for these.

## Architecture

### Runtime Flow

```text
main.py
  -> detect lyrics-file encoding and read lines
  -> t2l/t2l.py: process()
       -> remove existing LRC/metadata tags and validate lyrics
       -> t2l/phonetic.py: detect language and romanize/transliterate words
       -> load audio (torchaudio, with librosa fallback)
       -> optionally isolate vocals with Demucs
       -> resample to 22,050 Hz
       -> t2l/mtl/utils.py: convert normalized words to model phoneme IDs with g2p_en
       -> t2l/mtl/wrapper.py: load acoustic model and compute mel features
       -> CNN-BiLSTM phoneme posterior prediction
       -> t2l/mtl/utils.py: DTW-style phoneme/word alignment
       -> gen_lrc(): convert frame starts to LRC timestamps
  -> print enhanced LRC and write a standard line-timestamp LRC file
```

`main.py` is the CLI boundary. It calls `process()` for enhanced output, prints that output, then writes `<audio-basename>.lrc` under `--out_dir` using one timestamp per lyric line.

`t2l/t2l.py` orchestrates input cleanup, audio loading, optional Demucs separation, alignment, and LRC generation. Its primary API is:

```python
process(txt_lines, audio_file, mtl_model='MTL', demucs_model='mdx_extra',
        demucs_idx=-1, line_only=False, out_file=None, verbose=True,
        vocalize=True, format='lrc')
```

`t2l/phonetic.py` loads `lid.176.ftz` at import time. Script regexes take precedence over fastText: Japanese kana, CJK ideographs, Hangul, and Cyrillic map directly to `ja`, `zh`, `ko`, and `ru`; remaining text uses fastText. Language-specific libraries then normalize, romanize, or transliterate the words. `gen_phone_gt_opt()` in `t2l/mtl/utils.py` subsequently uses `g2p_en` to convert those tokens into the phoneme IDs consumed by the acoustic model.

`t2l/mtl/wrapper.py` owns feature extraction, checkpoint loading, acoustic-model inference, and dispatch to alignment. It accepts mono `[samples]` or channel-first `[channels, samples]` audio; multichannel input uses the first channel rather than concatenating channels along the time axis. Acoustic and optional boundary-model forward passes run under `torch.inference_mode()`. `t2l/mtl/model.py` defines the CNN-BiLSTM model; `t2l/mtl/utils.py` contains the alignment algorithms.

### Models and Alignment

Runtime checkpoints live under `./checkpoints/`:
- `checkpoint_Baseline`: single-task acoustic model with 41 phoneme classes.
- `checkpoint_MTL`: multi-task model with 41- and 47-class outputs; this is the CLI default.
- `checkpoint_BDR`: boundary detector used by `*_BDR` alignment methods.

`align()` accepts `"Baseline"`, `"MTL"`, `"Baseline_BDR"`, or `"MTL_BDR"`. It also accepts the tuple returned by `load_mtl_model()` so callers can preload models and avoid repeated initialization. `t2l/init_model.py` re-exports the loader; its module globals are defaults, not preloaded model instances.

Important signal constants:
- sample rate: 22,050 Hz
- mel bins: 128
- FFT size: 512
- timestamp frame resolution: `256 / 22050 * 3` seconds (about 34.8 ms)

CUDA is used when available; both Demucs and the acoustic model fall back to CPU.

### Failure and Boundary Behavior

- `TxtValueError` indicates empty or invalid lyrics after parsing.
- `AudioValueError` indicates that both torchaudio and librosa failed to load usable audio; Demucs/model/CUDA failures retain their original exception type.
- `AlignmentValueError` indicates that the audio-frame/phoneme dimensions or word/line indices cannot form a valid DTW path.
- `gen_lrc()` truncates safely when alignment results contain fewer words than the parsed lyrics instead of indexing past `word_align`.
- `pykakasi`, used for Japanese romanization, is GPL-licensed; account for that when changing distribution or licensing.
