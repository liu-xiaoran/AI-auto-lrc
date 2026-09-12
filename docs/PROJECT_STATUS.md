# Current project status

[English (primary)](PROJECT_STATUS.md) · [简体中文](PROJECT_STATUS.zh-CN.md) · [Documentation index](README.md)

Updated: 2026-09-12. Version: `2.0.0a0`; current main branch: `main`; merged from: `improve-inference-reliability`.

## Current conclusion and delivery scope

The project has a working CLI, Python API, and real local lyrics-to-audio alignment flow. It is suitable for trials in an environment with dependencies and model assets prepared. It is not a production release and does not claim coverage of all abnormal scenarios, platforms, or recording quality.

On 2026-09-12, the user explicitly deferred exhaustive abnormal scenarios and prioritized technical documentation, system explanations, usage instructions, AI prompts at the top of the READMEs, and a remote push. Existing protections and failure semantics remain in place. This scope does not expand the full abnormal matrix, modify the frozen numerical protocol, or relax validation thresholds. Committing and pushing code and documentation does not establish release qualification.

## Existing evidence and its limits

| Scope | Evidence date and result | Supported conclusion |
|---|---|---|
| Local core flow | 2026-09-09, macOS arm64 / Python 3.11.4, CPU / MTL; demo file and stdout outputs matched; 58 lines, 2158 bytes, monotonic times; 250 basic tests passed | The configured host can complete real alignment; no listening-based, full-catalog, or cross-platform quality conclusion |
| R2 deeply nested JSON | 2026-09-09, [independent QA (Chinese original)](evidence/b3f-r2-independent-qa-20260909/EVIDENCE-INDEX.md); 79 unique test nodes and frozen-file checks passed | Independent acceptance of the frozen R2 contract only |
| R3 macOS normal control | 2026-09-09, [evidence index (Chinese original)](evidence/b3f-r3-baseline-20260909/EVIDENCE-INDEX.md): 2 system tests passed; capture 282 passed, retention 257 passed / 1 declared Linux-only skip; both Gates PASS | Dynamic execution by the primary agent, with separate independent source/artifact review; not an independent dynamic rerun or full R3 acceptance |

The R3 index records temporary raw artifact paths. Pushing indexes, summaries, and reviews does not archive all temporary raw artifacts. Further platform/installation evidence in historical execution plans must be read within its original scope, not inherited as certification of the current release.

Actual checks for the 2026-09-12 delivery appear below. Historical results outside that record must not be described as rerun during this delivery.

## Deferred and unverified work

- R3 adversarial/abnormal matrix, Linux and two-platform security aggregation, disposable runtime, subsequent replay and final-schema validation.
- Natural non-empty partial product semantics; full process resource limits, long-audio stress, cancellation and cleanup lifecycle.
- macOS cold installation, two-platform install aggregation, offline Demucs weights and separation quality.
- Multilingual/mixed-language and full-catalog timestamp accuracy, CUDA, and other untested environments.
- Clean signed provenance, dependency/asset redistribution review, SBOM/attestation, independent recovery and rollback drills.

These remain deferred/unverified. S18 / W1b-5b / Release remains No-go. Any later release requires the original acceptance checks; this push cannot replace them.

## Delivery and usage entrypoint

Development snapshot `9657745` was pushed to `origin/improve-inference-reliability`. The user then requested merging and pushing to the main branch. Merge commit `540d04c` preserved both histories and was pushed to `main`; local and remote hashes were verified equal. Installation now uses `main`. Merging into main does not change Alpha status or release gates.

See the [user guide](USER_GUIDE.md), [system overview](SYSTEM_OVERVIEW.md), and [technical guide](TECHNICAL_GUIDE.md).

## Delivery validation (2026-09-12)

Executed on the existing configured macOS arm64 / Python 3.11.4 environment:

| Check | Result |
|---|---|
| Core, component, CLI, migration, documentation, and spec-index tests listed in the technical guide | 292 passed in 16.04 seconds; 22 existing Mel filterbank / TypedStorage warnings retained |
| `tests/package/test_wheel_metadata.py` and `tests/contract/test_dependency_sources.py` | 12 passed in 35.10 seconds; `UV_OFFLINE=1`; includes build and installed behavior using host locked dependencies, not a cold-install proof |
| `uv lock --check --offline` and CLI `--help` | Passed |
| Local links and anchors in both READMEs | Passed |
| Nine frozen R2 files, SHA-256 | 9/9 matched; historical accepted implementation unchanged |
| Real CPU / MTL demo from outside the repository | Both file and stdout modes exited 0; identical bytes; 58 lines, 2158 bytes; matching input text and monotonic times |

Demo output SHA-256: `1c4d88896b09f790f85923497230d0e717c933152975b3adb8e395b36d7a07f6`. Local diagnostics/results are in `/private/var/folders/jv/nkvs539n5757cl4j0405cdhh0000gn/T/lrc-delivery-20260912-zpcgrfgb`. These are temporary validation artifacts, not shipped with the snapshot and not a permanent raw-evidence archive.

The full security abnormal matrix, golden canonical checks, and cross-platform installation were not rerun for that delivery. No listening-based accuracy acceptance was performed. Repository-wide static checks listed in the technical guide were not reported as passing checks for that delivery.

## Bilingual documentation

English is the primary version for current documentation; the corresponding Chinese version is available from each page's language link. Default filenames have no language suffix, with `.zh-CN.md` for Chinese companions. The root Chinese README retains `README_zh.md`. Keep both versions synchronized when commands, parameters, defaults, results, or limits change. Historical plans, team reviews, and raw evidence remain clearly labeled original records; translation does not create fresh validation evidence.

## Bilingual update validation (2026-09-12)

Documentation links, migration contracts, and the spec index: 46 passed in 19.55 seconds. All 9 documentation pairs passed language-link and local-anchor checks; translated guide commands matched, and Python/shell examples passed syntax checks. This update changes documentation only; it does not rerun or expand model, audio-quality, security, or cross-platform acceptance.
