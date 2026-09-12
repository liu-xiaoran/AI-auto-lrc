# B3f-R2 recursion repair implementation evidence

Implementation-side evidence only. Independent QA acceptance is still required.

## Test-first defect and repair

- Independent QA P1 source: `/private/tmp/ai-auto-lrc-b3f-r2-independent-final-qa.Wasltj/EVIDENCE-INDEX.md` and `recursion-probe.stdout.json`.
- Permanent-test RED: `/private/tmp/ai-auto-lrc-b3f-r2-recursion-permanent-red.md5wPu`; pytest exit 1; one failed in 17.40s; JUnit SHA-256 `5b100975754e77d2459dda057cde79a8216ce9f798c85583e06876b3d863c029`.
- RED failure: the 2000-level nested array caused both runner environment helpers to emit `RecursionError` tracebacks and prevented environment/manifest/Gate continuity.
- Minimal product repair: both identity-candidate JSON extractors in `scripts/run_security_coverage.sh` now classify `RecursionError` as a semantically unextractable candidate. No recursion limit was changed and the verifier/consumer was not modified.
- Focused GREEN: `/private/tmp/ai-auto-lrc-b3f-r2-recursion-runner-green-probe.2U2VmC`; pytest exit 0; one passed in 42.57s; stderr empty; JUnit SHA-256 `29a02676a86889ab09928ff43beca8d978dd3536053a8dfd3cd622e07cffdfb3`.

The existing R2 artifact-profile node now permanently proves:

- A same-shape `TOKEN=0` candidate still extracts semantic SHA and coverage/pytest/uv versions.
- Replacing only `TOKEN` with a 2000-level nested JSON array retains the real raw SHA while environment semantic/tools and manifest semantic are null.
- The copied real verifier produces exactly `RUNTIME_IDENTITY_INVALID` for both lanes, with no traceback and exactly two intercepted `bootstrap-stub` calls.
- Both stub-success Gate documents have `harness_stub=true` and `not_verification_evidence=true`.
- A direct unknown-program invocation is logged as `blocked-program`, exits 97, does not execute its marker target, and does not fall back to the poison uv.

## Current-snapshot regression

| Selection | Evidence | Result | JUnit SHA-256 |
| --- | --- | --- | --- |
| R2 exact15 | `/private/tmp/ai-auto-lrc-b3f-r2-recursion-exact15-final.WvvowB` | exit 0; 15 passed in 74.43s; stderr empty; XML 15/0/0/0 | `92cffd3e20defd05091d4c1a53a9377c23ae9ceab5af2ad130f20d4d189f6691` |
| affected32 | `/private/tmp/ai-auto-lrc-b3f-r2-recursion-affected32-final.A43sKb` | exit 0; 32 passed in 3.89s; stderr empty | `9bc96aed4eebae79c05fe39e02cf0fd01eaa67a20143ab62268595162b41f060` |

R1a10, full R1b15, and legacy10 were not rerun on this new two-file snapshot. The affected32 selection includes the two affected R1b loader nodes and the missing-events consumer. Earlier GREEN results for the larger overlapping groups are historical only; independent QA may rerun them on the frozen snapshot.

No complete `test_security_coverage_gate.py`, real security dual lane, final67, platform matrix, R3/R4, CI, upload, commit, or push was run.

## Static results and frozen hashes

Evidence root: `/private/tmp/ai-auto-lrc-b3f-r2-recursion-static-final.PIUe64`.

- `bash -n`: exit 0.
- Python AST parse across all seven Python files: exit 0.
- `py_compile` across all seven Python files: exit 0.
- Ruff check across all seven Python files: exit 0, `All checks passed!`.
- Ruff format check: exit 1, `7 files would be reformatted`; no bulk formatting was performed.
- `git diff --check`: exit 0. All nine paths are currently untracked, so this command does not by itself validate their untracked contents.
- Runner mode: 0755.
- `nine-files-before-static.sha256` and `nine-files-after-static.sha256` are byte-identical (`diff` exit 0).

Final nine-file hashes are in `nine-files-after-static.sha256`. The only hashes changed from the independent-QA input snapshot are:

- `scripts/run_security_coverage.sh`: `b8fdaf4abe6e2248ad3478ad68e2022b207e8174fe63138a960ecaee2df0ca96`
- `tests/contract/test_security_runtime_identity_r2.py`: `b75ecc23a7e122e51b82cdb3fb1f8dfbd3846ddc4196b068d148fce4d6d435e7`

The other seven hashes remain unchanged from the prior frozen manifest.
