# CLAUDE.md

[English (primary)](CLAUDE.md) · [简体中文](CLAUDE.zh-CN.md)

Repository guidance for AI coding agents working on AI-auto-lrc v2.

## Current delivery decision (2026-09-12)

Read `docs/README.md` and `docs/PROJECT_STATUS.md` for current use and scope. The user explicitly authorized documentation updates and pushing the development snapshot, then requested merging and pushing it to `main`. The current installation entrypoint is `main`; preserve both histories with a normal merge. That authorization satisfies the commit/push approval requirement for this delivery; do not ask again. Exhaustive abnormal-scenario coverage is deferred, not passed. Preserve existing checks and frozen evidence; no release tag, force push, or main-branch rewrite is authorized.

## Source of truth

Read these before changing public behavior or LegacyV1 numerics:

1. `docs/AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md` — v2 contracts, milestones, test IDs, and Go/No-go gates.
2. `docs/AI_REFACTOR_HANDOFF.zh-CN.md` — frozen `legacy-v1` behavior and evidence snapshot.
3. `docs/BASELINE_PROVENANCE.md` — recovery and asset provenance.

The handoff is historical evidence. Do not rewrite it to look like v2 current state. Do not describe a planned or host-only check as release qualification.

## Locked v2 decisions

- Python `>=3.10,<3.12`; `pyproject.toml + uv.lock` are the only dependency facts.
- Public API: `AlignmentRequest`, `AlignmentResult`, `RuntimeConfig`, `create_runtime`, and `process(request, *, runtime=None)`.
- Default line LRC, MTL, strict completeness, offline mode, torchaudio decoder, and Demucs off.
- Partial output requires explicit opt-in and the CLI returns `3`.
- CLI stdout XOR atomic output file; Python API does not write LRC or print its own progress; runtime asset preparation can create private copies and dependencies can emit warnings.
- No public v1 CLI, old scattered-argument `process()`, five-element model tuple, or compatibility shim.
- No implicit torchaudio-to-librosa fallback. `librosa-mono` is explicit.
- No runtime CWD asset search or core implicit downloads. Optional Demucs may download weights and its offline enforcement remains unqualified.
- Preserve LegacyV1 checkpoint architecture and numerics: 22,050 Hz, Mel 128/512/256, pooling 3, frame clock `768/22050`, first channel, LSTM `batch_first=True/False/False`, MTL reduction order, and BDR alpha 0.8.
- X01-X03, training, and old evaluation are outside the v2 distribution.

## Architecture boundaries

```text
t2l.api / CLI
  -> application.AlignLyricsUseCase
       -> LyricsPreparationPort
       -> AudioPreparationPort
       -> InferencePort
       -> completeness policy
       -> LrcRendererPort
```

`t2l.composition` is the sole default wiring root. Domain/application code must not import adapters, torch, torchaudio, librosa, Demucs, fastText, or the output sink. Posterior/Mel/boundary tensors stay inside the LegacyV1 adapter. CLI owns lyric-file decoding and LRC output; the Python API may read audio and configured local assets through its runtime and prepare private asset copies, but does not write LRC or actively print progress. The default core path is offline; optional Demucs has an unresolved offline-enforcement gap.

## Environment and commands

```bash
git lfs install
git lfs pull
uv sync --frozen --python 3.11 --group dev
```

Basic unit and component tests (full selected core suite: `docs/TECHNICAL_GUIDE.md`):

```bash
uv run --offline --frozen --no-sync python -m pytest tests/unit -q -p no:cacheprovider
uv run python -m pytest tests/component -q -p no:cacheprovider
```

Validation:

```bash
uv lock --check
uv run ruff check .
uv run python -m compileall t2l tests
uv build
```

Do not install an undeclared package during a test to make it pass. Package tests must work with the declared test/build toolchain. Do not add Demucs back to core to satisfy deleted v1 tests.

## Test rules

- Follow RED -> GREEN -> REFACTOR for changed behavior.
- Keep stable specification IDs from the execution plan in test names, docstrings, or parameter IDs.
- Unit tests are offline and asset-light; the contract directory also contains heavyweight security/process fixtures. Mark real assets/codecs as `component`, canonical comparisons as `golden`, and process/platform isolation checks as `system`; use only registered markers.
- Use `Barrier`/`Event`, not `sleep()`, for concurrency tests.
- Posterior arrays may use the approved tolerance; phone IDs, frame pairs, completeness status, and LRC bytes are exact.
- A fake-only test does not qualify a real decoder, checkpoint path, natural partial outcome, installed wheel, offline build, or recovery process.
- Never update golden data, widen tolerance, enable partial, or change decoder to conceal a regression.
- Unexpected exceptions remain unexpected in the Python API; CLI maps them to code 1. Do not wrap `KeyboardInterrupt`, `SystemExit`, or `GeneratorExit` as domain failures.

## Change and commit gates

The approved execution plan is Gate 1. Continue implementing and validating in small slices. Before a commit, provide the intended file set, validation evidence, unresolved gates, and Conventional Commit message, then wait for explicit Gate 2 approval only when authorization is still missing. Do not push or rewrite Git history without separate explicit authorization.

The verified Git bundle does not include LFS objects or current untracked changes. Preserve user changes, inspect `git status`, and do not claim disaster recovery until the plan's independent LFS/dirty-state archive and offline restore drill pass.

## Documentation language convention

English is primary for current explanatory documentation and uses default filenames without a language suffix. Chinese companions use `.zh-CN.md`, except the root `README_zh.md`. Keep commands, parameters, defaults, and validation limits synchronized across both versions. Each page provides a language switch and navigation in its own language. Preserve historical execution plans, team reviews, and evidence as original records; translations or summaries do not constitute fresh acceptance evidence.
