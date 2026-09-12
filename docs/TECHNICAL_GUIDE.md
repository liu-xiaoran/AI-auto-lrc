# Technical guide

[English (primary)](TECHNICAL_GUIDE.md) · [简体中文](TECHNICAL_GUIDE.zh-CN.md) · [Documentation index](README.md)

## Structure and responsibilities

| Module | Responsibility |
|---|---|
| `t2l/api.py` | Public API, runtime wrapper, and process entrypoint |
| `t2l/contracts.py`, `t2l/errors.py` | Framework-independent value objects, validation, and domain errors |
| `t2l/composition.py` | Default wiring and construction of asset, device, language, and model resources |
| `t2l/application/align_lyrics.py`, `ports.py` | Use-case ordering, port protocols, and completeness policy |
| `t2l/domain/lrc.py` | LRC rendering and frame-to-time conversion |
| `t2l/adapters/lyrics_io.py`, `lyrics.py` | CLI text decoding, lyric cleaning, and preparation |
| `t2l/adapters/audio.py` | Decoders and audio preparation |
| `t2l/adapters/assets.py` | Asset location, verification, and private copies |
| `t2l/adapters/legacy_v1_inference.py` | Features, checkpoints, inference, DTW/BDR |
| `t2l/adapters/cli.py`, `output.py` | CLI arguments and error mapping; stdout/atomic file output |
| `t2l/mtl/model.py`, `utils.py` | Frozen LegacyV1 models and numerical logic |

Dependencies flow from CLI/API to application/domain and ports, with adapters injected by composition. Application/domain modules do not import torch, torchaudio, fastText, Demucs, or the output sink. Posterior and Mel tensors stay inside the inference adapter.

## Public API contracts

Import `AlignmentRequest`, `AlignmentResult`, `RuntimeConfig`, `create_runtime`, and `process` from `t2l`. `process(request, *, runtime=None)` can use a default runtime; create and reuse an explicit runtime for repeated work.

| AlignmentRequest field | Type/default | Meaning |
|---|---|---|
| lyrics | `tuple[str, ...]`, required | Decoded lyric lines |
| audio_path | `Path`, required | Audio input |
| timestamp_mode | `line` | `line` / `word` |
| acoustic_model | `MTL` | `Baseline` / `MTL` / `Baseline_BDR` / `MTL_BDR` |
| allow_partial | `False` | Explicit acceptance of a non-empty contiguous prefix |
| vocal_separation | `None` | Explicit `VocalSeparationOptions`; separation is off by default |

| RuntimeConfig field | Default | Constraint |
|---|---|---|
| asset_root | `None` | An explicit API root must be an absolute `Path`; CLI input is resolved first |
| device | `auto` | CUDA when available, otherwise CPU; no MPS |
| offline | `True` | `False` is rejected; offline enforcement remains incomplete in optional Demucs |
| decoder | `torchaudio` | `librosa-mono` requires explicit selection; no automatic fallback |
| seed | `0` | Non-negative integer |
| max_alignment_bytes | `536870912` | Estimated DTW allocation ceiling, not a process memory limit |

`AlignmentResult` exposes `status`, `lrc`, `spans`, `diagnostics`, and other structured data. See [contracts.py](../t2l/contracts.py) for exact fields. Incomplete alignment raises a domain error by default; partial results retain only a verifiable contiguous prefix. The API does not write LRC or print its own progress, but runtime preparation reads inputs and copies private assets, and dependencies may emit warnings.

Error classes and stable codes are defined in [errors.py](../t2l/errors.py). The API preserves unexpected exceptions outside the domain error hierarchy; the CLI maps them to exit code 1. Do not swallow KeyboardInterrupt/SystemExit/GeneratorExit. See the [user guide](USER_GUIDE.md) for exit codes and examples.

## Assets and runtime lifecycle

Resolution order: explicit configuration → `T2L_ASSET_ROOT` → recognized development checkout. Arbitrary CWD searches for matching filenames are forbidden. The bundled authority is `t2l/_assets/legacy_v1_manifest.json`; the development mirror is `assets/legacy_v1_manifest.json`. Runtime bytes are supplied separately. All six asset paths appear in the [user guide](USER_GUIDE.md). Size, hashes, paths, and LFS placeholders are checked before loading. Private copies avoid subsequent direct use of mutable source assets.

`create_runtime` validates the manifest, prepares language-identification assets, and constructs Mel resources eagerly. Checkpoints, the fastText object, and G2P load on demand. Caches are isolated across runtimes; a lock serializes model loading and inference within each runtime. There is no public close/context-manager contract. Cache reuse alone is not full service-lifecycle qualification.

Demucs is an optional extra whose `get_model` may download weights. The separator does not fully receive and enforce the offline configuration, so offline execution with pre-provisioned assets is qualified only to the documented core scope.

## Frozen numerical protocol

| Parameter | LegacyV1 convention |
|---|---|
| Sample rate | 22050 Hz |
| Mel | 128 bins, FFT 512, hop 256 |
| Time axis | Pooling 3; `768 / 22050` seconds per frame |
| Default multichannel policy | First channel; no silent change to averaged mixing |
| Phone inventory | 41 entries, space 39, blank 40 |
| MTL | Preserve 41×47 reduction order |
| BDR | Alpha 0.8 |
| LSTM | Historical `batch_first=True/False/False` |
| Timestamps | Millisecond truncation; line tags `[mm:ss.mmm]`, token tags `<mm:ss.mmm>` |

Do not change checkpoint architecture, golden data, numerical tolerances, or decoder to turn failures green. Natural partial behavior and cross-language quality still require separate product acceptance.

## Output consistency

Without `-o`, CLI stdout is UTF-8 LRC plus one trailing newline. With `-o`, stdout is empty and the atomic file sink is used. The sink creates parents, replaces an existing regular file, and rejects input aliases, non-regular files, and symlink ancestors at any level. A previous file may survive a failed run; callers must check the current exit code. Shell redirection and caller-managed Python file writes do not inherit these protections.

## Development and validation

```bash
uv sync --frozen --python 3.11 --group dev
uv lock --check --offline
```

Basic validation of the default core path, with dependencies and local assets prepared:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --offline --frozen --no-sync python -m pytest \
  tests/unit tests/component tests/test_alignment.py \
  tests/contract/test_cli_contract.py tests/contract/test_cli_subprocess.py \
  tests/contract/test_application_ports.py tests/contract/test_composition.py \
  tests/contract/test_dependency_boundaries.py tests/contract/test_migration_contract.py \
  tests/contract/test_error_registry.py tests/contract/test_document_links.py \
  tests/contract/test_spec_inventory.py -q -p no:cacheprovider
```

`tests/contract` also contains security, process, and evidence-runner tests; the entire directory should not be described as a fast suite. `component` needs local assets/codecs; `golden` needs the pinned canonical environment; `package` checks building/installing; `system` uses real processes and platform isolation. Running all pytest tests expands the scope. Exhaustive abnormal-scenario coverage is not required for this documentation delivery.

Run static checks and builds as appropriate to the change:

```bash
uv run --offline --frozen --no-sync ruff check .
uv run --offline --frozen --no-sync python -m pytest tests/package/test_wheel_metadata.py -q
uv build --offline
```

These are maintenance commands, not claims that every command passed in this delivery. Actual results are recorded in [project status](PROJECT_STATUS.md). Do not install undeclared dependencies during tests, regenerate golden data to conceal regressions, or substitute fakes, normal controls, or one-platform success for release acceptance.

Exhaustive abnormal scenarios are deferred by user decision. When security qualification resumes, continue from the frozen evidence in the [security plan (Chinese historical record)](W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) and [S18 implementation plan (Chinese historical record)](S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md).
