# AI-auto-lrc v2

## Copyable prompt for an AI assistant

This prompt identifies the repository even when pasted into a new conversation.
Replace the input placeholders, or let the assistant ask for the missing files.
The assistant still needs repository access and a shell to execute the project;
a local path alone does not give a chat assistant access to your computer.

```text
Help me generate an LRC file with AI-auto-lrc v2.
Repository URL: https://github.com/liu-xiaoran/AI-auto-lrc
Clone URL: https://github.com/liu-xiaoran/AI-auto-lrc.git
Branch: main
Primary documentation language: English; Chinese companions are linked on each page.
Documentation index: https://github.com/liu-xiaoran/AI-auto-lrc/blob/main/docs/README.md
User guide: https://github.com/liu-xiaoran/AI-auto-lrc/blob/main/docs/USER_GUIDE.md
Project status: https://github.com/liu-xiaoran/AI-auto-lrc/blob/main/docs/PROJECT_STATUS.md

Local checkout (optional): <absolute repository path, or not cloned yet>
Lyrics: <absolute UTF-8 lyrics path>
Audio: <absolute path to the matching recording>
Output (optional): <absolute path to a new LRC file, or propose a new filename>

Identify the project using the exact URL above, not its name alone.
If a local checkout exists, verify its remote and branch and preserve local changes.
If it is not cloned and you have shell/network access, clone main into a new directory
and follow the user guide to prepare Git LFS, dependencies and runtime assets.
Read the documentation above, or the corresponding files in the verified checkout.
For integration or edits, also read docs/TECHNICAL_GUIDE.md and CLAUDE.md there.
If you cannot access the repository, inputs or shell, state the missing capability
and ask for the required material or provide commands I can run; do not claim execution.
Treat unfilled placeholders as missing information, not literal paths.
Check the branch, Python 3.10/3.11, pyproject.toml/uv.lock and all six runtime assets.
Use the v2 ai-auto-lrc CLI from the project's environment, with explicit paths.
Start with CPU, MTL, line timestamps, strict completeness and no vocal separation.
Use a canonical output path. Once dependencies and assets are ready, run offline.
Ask for missing required input paths; do not invent lyrics or timestamps.
Do not silently enable partial output, change decoder or download optional models.
Respect my overwrite intent or choose a new output file. Verify the actual exit
code, output content, line count and monotonic timestamps. Report the command,
output path and failures. Successful execution is not proof of alignment accuracy.
Exhaustive abnormal scenarios are deferred; do not claim unverified release gates pass.
```

[Documentation index](docs/README.md) · [Usage](docs/USER_GUIDE.md) · [System overview](docs/SYSTEM_OVERVIEW.md) · [Technical guide](docs/TECHNICAL_GUIDE.md) · [Current status](docs/PROJECT_STATUS.md)

> 2026-09-12: Exhaustive abnormal-scenario coverage is deferred by user decision. The v2 snapshot is now integrated into `main`, the installation entrypoint. It remains Alpha with incomplete release qualification. English is the primary documentation; every current guide has a Chinese companion.


Offline-first lyrics-to-audio alignment with standard line-level or optional word-level LRC output.

[English (primary)](README.md) · [简体中文](README_zh.md) · [Historical v2 execution plan (Chinese)](docs/AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md) · [Historical LegacyV1 handoff (Chinese)](docs/AI_REFACTOR_HANDOFF.zh-CN.md)

> Status: `2.0.0a0` development build. The v2 API and core adapters are implemented, but release qualification is still in progress. Do not treat the current checkout as a production release or as evidence of alignment quality.

## Locked v2 behavior

- Python `>=3.10,<3.12`.
- Default output is standard line-level LRC.
- Default acoustic route is `MTL` using the frozen `legacy-v1` profile.
- Vocal separation is off by default; Demucs is an optional extra and never loads on the default path.
- Core execution is offline. Runtime assets must already be present and pass the bundled manifest checks.
- Incomplete alignment fails by default. `--allow-partial` explicitly enables a contiguous-prefix result and returns exit code `3`.
- `torchaudio` is the default decoder. `librosa-mono` is an explicit policy, not an automatic fallback.
- Without `-o`, stdout contains only UTF-8 LRC. With `-o`, stdout is empty and the file is replaced atomically.
- The Python API returns a structured result and does not write LRC files or print its own progress. Runtime preparation still reads inputs and materializes private asset copies; dependencies may emit warnings.

## Installation for development

Model checkpoints and the fastText language-identification model are stored outside the wheel and must be available locally. A development checkout normally obtains them through Git LFS.

```bash
git lfs install
git lfs pull
uv sync --frozen --python 3.11 --group test
```

To install the optional vocal-separation stack:

```bash
uv sync --frozen --extra vocals --group test
```

`pyproject.toml` and `uv.lock` are the dependency sources of truth. The legacy `requirements.txt`, `Pipfile`, and `Pipfile.lock` have been retired and are not v2 installation inputs.

## Runtime assets

The asset root is resolved in this order:

1. `RuntimeConfig.asset_root` or CLI `--asset-root`;
2. `T2L_ASSET_ROOT`;
3. the repository root, only when running from a recognized development checkout.

The current LegacyV1 root contains:

```text
checkpoints/checkpoint_Baseline
checkpoints/checkpoint_MTL
checkpoints/checkpoint_BDR
lid.176.ftz
assets/nltk_data/corpora/cmudict.zip
assets/nltk_data/taggers/averaged_perceptron_tagger.zip
```

An explicit API asset root must be an absolute Path. The CLI resolves its input; absolute paths are recommended. Assets are checked for path escape, Git LFS pointer content, expected size, and SHA-256 before model deserialization. The current working directory is never searched for similarly named files.

## CLI

```bash
uv run ai-auto-lrc LYRICS_FILE AUDIO_FILE \
  --asset-root /absolute/path/to/assets
```

The default command writes one trailing newline to stdout and does not create an output file. To write a file instead:

```bash
uv run ai-auto-lrc lyrics.txt song.wav \
  --asset-root /absolute/path/to/assets \
  -o output/song.lrc
```

Important options:

```text
--timestamps line|word
--acoustic-model Baseline|MTL|Baseline_BDR|MTL_BDR
--allow-partial
--device auto|cpu|cuda
--asset-root ABSOLUTE_PATH
--decoder torchaudio|librosa-mono
--separate-vocals
--demucs-model mdx|mdx_extra|mdx_q|mdx_extra_q
--demucs-index -1|0|1|2|3
--verbose
--debug
```

`--demucs-model` and `--demucs-index` require `--separate-vocals`. The default path does not import or download Demucs. Optional separation may download weights; offline configuration is not fully enforced by that adapter and offline qualification is pending.

### Exit codes

| Code | Meaning | LRC may exist |
|---:|---|---|
| 0 | Complete result | Yes |
| 1 | Unexpected internal error | No |
| 2 | CLI/configuration error | No |
| 3 | Explicitly allowed partial result | Yes |
| 4 | Lyrics input error | No |
| 5 | Audio decode or vocal-separation error | No |
| 6 | Asset, checkpoint, model, or device error | No |
| 7 | Alignment error or strict rejection of a partial result | No |
| 8 | Output write error | No |

Progress and diagnostics go to stderr. Scripts that intentionally accept partial output should handle both `0` and `3`; treating only `0` as success preserves strict completeness.

## Python API

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
        audio_path=Path("song.wav"),
        timestamp_mode="line",
        acoustic_model="MTL",
    )
)

print(result.status)
print(result.lrc)
print(result.spans)
print(result.diagnostics)
```

Reuse one runtime for repeated calls when you want its lazy language/model resources to be reused. Different runtimes isolate their caches. The current LegacyV1 inference adapter serializes load and inference within one runtime.

## Architecture

```text
CLI / Python API
  -> AlignmentRequest
  -> AlignLyricsUseCase
       -> LyricsPreparationPort
       -> AudioPreparationPort
       -> InferencePort (LegacyV1 feature/model/DTW/BDR)
       -> strict/partial completeness policy
       -> LrcRendererPort
  -> AlignmentResult
  -> CLI only: stdout XOR atomic file sink
```

`t2l.composition` is the default composition root. Application and domain modules do not depend on torch, torchaudio, librosa, Demucs, fastText, or filesystem output. LegacyV1 preserves the existing checkpoint architecture, first-channel policy, timebase (`768 / 22050` seconds per frame), MTL reduction order, BDR alpha, and historical LSTM axis semantics.

## Tests

Lightweight unit tests (see the technical guide for the core validation suite):

```bash
uv run --offline --frozen --no-sync python -m pytest tests/unit -q -p no:cacheprovider
```

Local component tests, including the checked-in LegacyV1 checkpoints:

```bash
uv run python -m pytest tests/component -q -p no:cacheprovider
```

Build and static checks:

```bash
uv sync --frozen --group dev
uv lock --check
uv run ruff check .
uv run python -m compileall t2l tests
uv build
```

Linux CPython 3.10 functional canonical evidence, real WAV/MP3 cases, concurrent initialization, and a Linux x86_64 cold-cache offline install are now covered; they are still not release proof. The release plan still requires an approved natural non-empty partial contract, complete resource limits, macOS cold installation and a two-platform aggregator, offline Demucs coverage, clean signed provenance, SBOM/attestation, and recovery/rollback drills. A host-only or single-platform green suite does not replace those gates.

The macOS / Python 3.11 R3 security-runtime baseline has a separate, explicit system test
entrypoint (outside the portable contract layer). It takes several minutes:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --offline --frozen --no-sync python -m pytest \
  tests/system/test_security_runtime_identity_r3.py -q -p no:cacheprovider
```

It runs the original capture and retention suites and verifier serially, denies
IP networking and writes to the checkout/runtime, and permits Unix socket binding
only inside its temporary evidence directory. Raw artifacts and before/after
inventories remain in the pytest temporary directory. To preserve a specific path,
pass a new, unused `--basetemp`. This is a macOS baseline, not qualification of
adversarial scenarios, other platforms, or a release. See sections 36.41–36.42 of
the [historical S18 implementation plan (Chinese)](docs/S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)
for the original baseline record, and [project status](docs/PROJECT_STATUS.md) for current scope.

## Migration from v1

v2 intentionally does not publish the old `t2l.t2l.process(...)` signature, preloaded five-element model tuples, implicit decoder fallback, default Demucs behavior, or automatic enhanced-to-standard LRC conversion. Migrate callers to `AlignmentRequest`/`AlignmentResult` and choose output, decoder, partial, and vocal-separation policies explicitly.

Use the [v1-to-v2 migration guide](docs/V1_TO_V2_MIGRATION.md) for the parameter-by-parameter mapping and exit-code handling. The frozen v1 facts and exact behavior boundaries are retained in [the historical handoff (Chinese)](docs/AI_REFACTOR_HANDOFF.zh-CN.md); the executable validation gates are in [the historical v2 plan (Chinese)](docs/AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md).

## License and provenance

See [LICENSE](LICENSE) and [BASELINE_PROVENANCE.md](docs/BASELINE_PROVENANCE.md). Some language-processing dependencies and model assets have their own licenses. Internal test authorization is not the same as verified redistribution rights; release artifacts must pass the plan's license and provenance gates.
