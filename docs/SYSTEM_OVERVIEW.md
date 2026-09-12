# System overview

[English (primary)](SYSTEM_OVERVIEW.md) · [简体中文](SYSTEM_OVERVIEW.zh-CN.md) · [Documentation index](README.md)

## Purpose

AI-auto-lrc takes existing lyrics and the corresponding song audio, aligns the lyrics to the recording, and produces an LRC file for music players. Supply accurate lyrics for the same recording version. The system does not transcribe or write lyrics from audio, and does not provide a web page, HTTP service, or background scheduler.

The current version is `2.0.0a0` Alpha. The local core flow has been exercised with real input; exhaustive abnormal scenarios and release qualification remain incomplete. See [project status](PROJECT_STATUS.md).

## Inputs and outputs

| Item | Behavior |
|---|---|
| Lyrics | UTF-8 plain text, one phrase per line, is recommended; the CLI supports BOM and controlled encoding fallback; the API accepts a tuple of strings |
| Audio | A local file; real WAV/MP3 cases have been tested, while other formats depend on decoder capabilities |
| Default processing | MTL, torchaudio, strict completeness, no vocal separation; auto selects CUDA when available, otherwise CPU |
| Default output | Line tags such as `[mm:ss.mmm]lyrics`; explicit word mode adds `<mm:ss.mmm>` token tags within lines |
| CLI file output | `-o` selects a file; parents are created and an existing regular file is replaced atomically |
| CLI stdout | Without `-o`, only LRC with one trailing newline; progress and diagnostics go to stderr |
| API | Returns a structured result; the caller decides how to display, save, and consume it |

Phonetic routes exist for Chinese, English, Japanese, Korean, and Russian. Their presence does not establish accuracy for every language or mixed-language input. Word timestamps correspond to internal tokens, which may differ from natural-language words.

## Processing flow

```text
Lyrics -> decode text -> clean / identify language / prepare phones --+
                                                                      +-> inference -> DTW / optional BDR
Audio -> torchaudio -> first channel / resample / Mel -----------------+
  -> completeness check -> LRC rendering -> structured result -> CLI stdout or atomic file
```

The Python API and CLI share an application use case. The model adapter preserves LegacyV1 numerical behavior; the application coordinates processing and strict/partial policy. Dependencies and assets must be prepared before execution. The default core path does not download models.

## Requirements and assets

Supported Python versions are `>=3.10,<3.12`; start with Python 3.11 and CPU. Local records exist for macOS arm64 / Python 3.11.4. MPS is not an available device option. On Linux x86_64, locked dependencies select PyTorch CPU wheels by default, so the existence of `--device cuda` does not establish GPU support in that installation.

Install from `pyproject.toml + uv.lock`, fetch model files with Git LFS, and prepare the NLTK data. Dependency installation and LFS downloads may need network access. “Offline” describes core execution after provisioning. See the [user guide](USER_GUIDE.md) for all assets and installation commands.

## Operational limits

- `--allow-partial` is an explicit opt-in, accepts only a non-empty contiguous prefix, and returns exit code 3. Failures do not automatically become partial successes.
- Output must not equal or alias an input. Symlink ancestors and non-regular targets are rejected. On macOS, use canonical paths such as `/private/var/...` for temporary output.
- The API does not write LRC or print its own progress. Runtime preparation still reads inputs and creates private asset copies; third-party libraries may emit warnings.
- Runtimes can be reused; model loading and inference are serialized within one runtime. There is no public `close()` or context-manager protocol yet. Full cleanup and concurrency capacity for long-running services are unqualified.
- `max_alignment_bytes` constrains estimated DTW allocation, not total process RAM. Long recordings still need capacity assessment.
- Optional Demucs is experimental and may download weights. The separator does not fully enforce `offline=True`; that setting is not a network-isolation guarantee for this path.

Training, old evaluation scripts, and v1 conversion extensions are outside the v2 public interface. For integration, read the [technical guide](TECHNICAL_GUIDE.md); update old callers using the [migration guide](V1_TO_V2_MIGRATION.md).
