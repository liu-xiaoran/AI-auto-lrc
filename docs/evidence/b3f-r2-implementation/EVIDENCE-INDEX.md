# B3f-R2 implementation evidence index

This index records implementation-side evidence only. It is not independent QA acceptance and does not authorize R3/R4, the real security dual-lane runner, final67, a platform matrix, CI, upload, commit, or push.

## Frozen implementation snapshot

- Nine-file hashes: `/private/tmp/ai-auto-lrc-b3f-r2-static-final.NdMCMw/nine-files.sha256`
- Nine-file Git status: `/private/tmp/ai-auto-lrc-b3f-r2-static-final.NdMCMw/nine-files-git-status.txt`
- All nine paths are currently untracked in Git; `git diff --check` therefore does not validate their untracked contents by itself.
- Final static evidence root: `/private/tmp/ai-auto-lrc-b3f-r2-static-final.NdMCMw`
- Static exits: bash-n 0, py-compile 0, AST parse 0, Ruff check 0, git diff check 0, runner-mode check 0; runner mode is 0755.
- Ruff format check is intentionally reported separately: exit 1, `7 files would be reformatted`, 3821 output lines. No bulk formatter was run.

## Final current-snapshot executions

| Selection | Evidence | Result | JUnit SHA-256 |
| --- | --- | --- | --- |
| R2 exact15 after final lint fix | `/private/tmp/ai-auto-lrc-b3f-r2-exact15-post-lint-final.P7gVNM` | 15 passed in 62.32s; exit 0; stderr empty | `9124c6212c700e694c0e1ef8bbedd25cf9247178526220d6f9427c8aa357f13a` |
| affected32 | `/private/tmp/ai-auto-lrc-b3f-r2-affected32-final.fAqxad` | 32 passed in 3.65s; exit 0; stderr empty | `ee9f7a6c05ed141449f988a8feecb6979bec1299c20c3c53b4d08a2964a59e76` |
| R1a10 | `/private/tmp/ai-auto-lrc-b3f-r2-r1a10-final.aIfaPr` | 10 passed in 0.15s; exit 0; stderr empty | `3690366ab56cb0de06cfb820cf1e0bd7ad32e94b3401370cdfab85ebed40966c` |
| R1b15 | `/private/tmp/ai-auto-lrc-b3f-r2-r1b15-final.g4I2gV` | 15 passed in 0.65s; exit 0; stderr empty | `9b5db13767a05e30a2411a71d42e24b89a23c0f45fa2f20c21f94699d00062c5` |
| legacy10 | `/private/tmp/ai-auto-lrc-b3f-r2-legacy10-final.QrDCmq` | 10 passed in 0.24s; exit 0; stderr empty | `9523835ee7fb7dc1263fe37f8e63ef8c57f2c9090bad2fb1f504e8aedf9d0ca2` |

The affected32 collection is `/private/tmp/ai-auto-lrc-b3f-r2-affected32-collect-final.5wIB81` and contains exactly 32 expanded node IDs. It is the previous affected 31 plus `test_s18_gate_rejects_missing_pytest_events_with_stable_code`. Combined with the separately run exact15 it covers the prior history46 selection and the new missing-events consumer, but it must be described as `exact15 + affected32`, not as one fresh history46 process.

R1a10, R1b15, legacy10, affected32, and exact15 overlap. In particular, affected32 overlaps R1b15 in the two loader-failure nodes and overlaps legacy10 in the record-field node. Counts must not be summed as unique tests.

## R2 node to counterexample and fresh-result map

All node names below are from the exact 15-node collection. The final current-snapshot result for every row is the exact15 result in `P7gVNM`; focused evidence is additional diagnostic evidence, not a replacement.

| R2 node | Principal counterexamples/oracles | Focused fresh evidence |
| --- | --- | --- |
| `existing_root_rejects_before_uv_resolution` | Existing root and invalid input helper; helper nonzero secret stderr suppression; mkdir EEXIST/EACCES/ENOSPC; validation ENOENT/ENOTDIR/EACCES/EIO; exact argv recognition | Final current snapshot in exact15; earlier implementation GREEN `/private/tmp/ai-auto-lrc-b3f-r2-input-validation-green.0QL8WD` |
| `runner_resolves_one_absolute_uv_and_reuses_final_prefix` | One absolute uv, stable canonical path/version/SHA, no poisoned fallback, final prefix reused | Final current snapshot in exact15 |
| `bootstrap_accepts_only_exact_uv_observation_argv` | Exact five observation options and separator positions; reordered/malformed arguments reject | Final current snapshot in exact15 |
| `prepared_runtime_publishes_v2_without_live_reread` | Real prepare/capture/local-events/builder/guard/exclusive-writer chain; tripwires after capture; mode 0600, one link, no temp, bounded raw size | `/private/tmp/ai-auto-lrc-b3f-r2-prepared-final.MjzCN6`: 1 passed; JUnit `6dae6eec7c206d1c3feef4a3122f16efe36b6be113119dcb9be23057922213ae` |
| `timestamp_has_one_authority_and_cross_binding` | One timestamp authority across environment, command, manifest, identity scope, and gate | Final current snapshot in exact15 |
| `artifact_versions_are_exact_and_old_versions_fail_closed` | Exact current environment/command/manifest versions; old, float, bool, duplicate, unknown, and cross-binding drift rejection | `/private/tmp/ai-auto-lrc-b3f-r2-artifact-oracles-final.fCAPb0` (part of 3 passed); JUnit `3aa24e942b3bdf296ae5ad12c225a1d41b9f39daaccd6641dbb3dfa5a4da2d4f` |
| `identity_read_mode_and_envelope_failures_are_runtime_invalid` | Independent invalid-summary literal; pathname disappearance; empty versus missing; oversize; controlled EACCES; retained raw SHA after complete read; null raw SHA when unread; NaN/Infinity/-Infinity rejection | `/private/tmp/ai-auto-lrc-b3f-r2-read-null-final.MQ1bgA`: 1 passed; JUnit `75c29f50fa49399d333e896cbd228934eb88bcb411e73aa43c3e713a7210a92b` |
| `failure_classes_are_not_collapsed` | Independent RUNTIME/PLUGIN/TOOLCHAIN/CONFIG; unions; malformed command CONFIG-only; same uv bytes at a different canonical path; invalid identity uv; live mismatch; observation index preservation; scope failure does not hide valid facts; single-pass endpoint reuse after late failure | `/private/tmp/ai-auto-lrc-b3f-r2-failure-matrix-final.ARrEV1`: 1 passed; JUnit `94746ca5ef5e979a0df5dab1dea5c7b08941241e765901c65d39053ecb77ff65` |
| `environment_uses_nullable_identity_observation_without_version_subprocess` | Nullable raw/semantic/tool observations and no identity-derived version subprocess | Final current snapshot in exact15 |
| `manifest_cross_binds_identity_without_hash_cycle` | Raw/semantic identity binding across environment and manifest without a self-hash cycle | `/private/tmp/ai-auto-lrc-b3f-r2-artifact-oracles-final.fCAPb0` (part of 3 passed) |
| `gate_runtime_summary_is_exact_bounded_and_path_free` | Exact bounded summary, no local paths or raw metadata/RECORD/canonical package bytes | Final current snapshot in exact15 |
| `identity_limit_accepts_representative_and_rejects_plus_one` | Total 4 MiB boundary plus exact/+1 METADATA 256 KiB, RECORD 256 KiB, required entry 1 MiB, and pyvenv.cfg 16 KiB | `/private/tmp/ai-auto-lrc-b3f-r2-nested-caps-final-retry.3yWLMM`: 1 passed; JUnit `da813b4cd83c259ad0ee979608a9e7d42ee2c368c03a64aa661d101fcd42e9aa` |
| `verifier_recomputes_identity_without_producer_validator` | Consumer recomputation is independent of producer validation helper | Final current snapshot in exact15 |
| `artifact_profiles_preserve_early_no_events_and_malformed_identity` | Valid extractable tools; deep duplicate/non-finite candidate rejection; absent/oversize/EACCES identity profiles; required-raw EARLY; NO_EVENTS; malformed identity; real copied verifier baseline PASS and exact consumer failures | `/private/tmp/ai-auto-lrc-b3f-r2-profile-final.KaQl4T`: 1 passed; JUnit `ec267cb5d658fc558408cdd5cd96a83bc26bd554e690580fca2ac4a05449ffad`; raw profile copy under `profile-artifacts/` |
| `policy_and_gate_have_exact_current_schema` | Exact policy top/nested keys and types; missing/unknown/duplicate/value drift; exact Gate v5 top/nested keys and artifact hash key set | `/private/tmp/ai-auto-lrc-b3f-r2-artifact-oracles-final.fCAPb0` (part of 3 passed) |

The profile evidence uses synthetic valid coverage/JUnit/events raw. The copied runner creates environment/command/manifest and the copied real verifier evaluates them. This is writer/consumer contract evidence, not an actual security dual-lane execution or R3 integration proof.

## Product RED evidence retained

| Defect exposed | RED evidence | Repair-side GREEN |
| --- | --- | --- |
| Input helper leaked secret stderr and misclassified mkdir/validation failures | `/private/tmp/ai-auto-lrc-b3f-r2-p1-red-final.CXz0YH`; JUnit `2308cd8eaaa45cb85d1816ea98fdb3fd5c3c0abe6b0b65bea31d172ef9cf8ae8` | `/private/tmp/ai-auto-lrc-b3f-r2-p1-green.8BgkXx`; JUnit `2718adb25927c57d1c9515d2984769d0792e248d401caa6bba567ed889a4f061` |
| Validation EACCES/EIO collapsed to input failure | `/private/tmp/ai-auto-lrc-b3f-r2-input-validation-red.RFtaBD`; JUnit `8a010cc5c7ddb9ad9e33002612453527815850850d81ded27f135aa079e06f06` | `/private/tmp/ai-auto-lrc-b3f-r2-input-validation-green.0QL8WD`; JUnit `3c5dde31425a4d982a57f7d6bcaa4826b606e8a25c8cd7e4d857d89bc6424bd9` |
| Valid pytest-cov entry was read twice after late distribution failure | `/private/tmp/ai-auto-lrc-b3f-r2-single-pass-red.HJ15ch`; JUnit `7af0ed89a9db13362f4b60d7e23b010cea6f658b7613bf6605b2e0d1b9e79992` | `/private/tmp/ai-auto-lrc-b3f-r2-single-pass-green.NMzgHN`; JUnit `f92cb26f12b7ee6e1c6f03502de6e7243a550fdcacbc6c46fb766183e09b8597` |
| Entry-binding failure caused a second live read | `/private/tmp/ai-auto-lrc-b3f-r2-single-pass-entry-red.eYh1T1`; JUnit `4e0b8b41c795aad4f7528aafd2a43dfb00728fbdc089f957e36d8939ca8992ff` | `/private/tmp/ai-auto-lrc-b3f-r2-single-pass-entry-green.84H88u`; JUnit `99271e1002022dfdecedddacc491e1b1d6d2fa8ad2db04559b1126ac3e01e785` |
| Strict JSON accepted NaN/Infinity/-Infinity | `/private/tmp/ai-auto-lrc-b3f-r2-strict-json-red.NO12Sl`; JUnit `08efc48d376c1c06b1c3fdb9cfa9d4c41ec5359b2184b18b43dc27e3eebf9a5f` | `/private/tmp/ai-auto-lrc-b3f-r2-strict-json-green.ty2aHV`; JUnit `5aa5f356cc2da3a2f073805cf91845e2e3585bbef6093e4b36bdd597b1c93abd` |

## Fixture or execution-invalid attempts retained and not counted as product RED

- `/private/tmp/ai-auto-lrc-b3f-r2-p1-red.aZvR1I`: invalid command/import-path attempt.
- `/private/tmp/ai-auto-lrc-b3f-r2-artifact-oracles-first.VdN8JQ`: missing helper root caused three fixture `FileNotFoundError` failures.
- `/private/tmp/ai-auto-lrc-b3f-r2-prepared-publication-first.p0Qzi3`: fake pytest wiring was not installed, so real pytest reached duplicate plugin registration before collection.
- `/private/tmp/ai-auto-lrc-b3f-r2-nested-caps-first.ViqV1G`: metadata fixture used one oversized header.
- `/private/tmp/ai-auto-lrc-b3f-r2-nested-caps-retry.AOMLQy`: RECORD fixture used one CSV field over the parser cap.
- `/private/tmp/ai-auto-lrc-b3f-r2-nested-caps-label.P1wnQi`: diagnostic retry localized the same RECORD fixture error.
- `/private/tmp/ai-auto-lrc-b3f-r2-nested-caps-final.AM10mI`: pytest console entry omitted the repository import path, and the zsh wrapper also attempted to assign the read-only `status` variable. The target node did not collect; this is not product RED.

The earlier exact15 directory `/private/tmp/ai-auto-lrc-b3f-r2-exact15-final.jU4pqi` is valid GREEN, not an invalid attempt: it naturally completed with 15 passed in 63.65s, exit 0, and JUnit `18e0872d3bc51f0cf6cf10ce6bc49dfefe83704fec4b5a09ee241ac6e4b60b09`. An intermediate observation of 13 progress dots occurred before its wrapper wrote the final files; no rerun was started at that point.
