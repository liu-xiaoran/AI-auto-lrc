# B3F R2 independent final QA — early RED

Repository: `/Users/liu-haixiao/ai_code/AI-auto-lrc`

Evidence root: `/private/tmp/ai-auto-lrc-b3f-r2-independent-final-qa.Wasltj`

## Decision

QA stopped before the planned fresh 47-node pytest run because the bounded deep-JSON continuity probe confirmed a P1 product defect. The repository was not edited and no real bootstrap, security dual lane, final67, platform matrix, R3, CI, upload, commit, or push was run.

## Probe

- Source: `recursion_continuity_probe.py`
- Structured result: `recursion-probe.stdout.json`
- Wrapper stderr: `recursion-probe.stderr.txt` (empty)
- Wrapper exit: `recursion-probe.exit` (`0`; the probe completed and recorded the copied runner result)
- Evidence hashes: `recursion-probe-evidence.sha256`
- Payload size: 4,256 bytes
- Payload SHA-256: `5bdc6e2a852b21401512062716297d5ef75e65fc837fe17e4220937f9b5eb02a`
- Copied runner exit: `1`
- Bootstrap classification: exactly two `bootstrap-stub` calls; no real bootstrap
- Failure: both environment helpers emit a `RecursionError` traceback while decoding the readable identity candidate
- Capture and retention: `environment.json`, `run-manifest.json`, and `gate.json` are absent
- Capture and retention runner errors: mode `0600`, `reason_code=ENVIRONMENT_ARTIFACT_WRITE_FAILED`, `environment_exit_code=1`

Expected contract behavior is continuity for a readable but semantically unextractable identity: retain the actual raw SHA-256, publish nullable semantic/tool fields, continue through manifest and Gate, and emit no traceback. The observed behavior violates that contract.

## Integrity and lock release

- `pre-recursion-process-gate.txt`: empty; no concurrent pytest/runner/bootstrap process was found.
- `nine-files-after.check.txt`: all nine frozen files are `OK` against the repository evidence manifest.
- `nine-files-after.sha256`: exact post-probe hashes; all match the frozen pre-probe values.
- `final-process-gate.txt`: empty; no pytest/runner/bootstrap process remained.

Testing is explicitly stopped and the sole pytest/runner execution lock is released after the final process gate.

## Static review follow-up (not the dynamic blocker)

The copied-runner/fake-uv safety review found the current implementation safe, but two permanent-oracle gaps remain for a later test-first follow-up:

1. Add a direct unknown-program invocation assertion proving `blocked-program` and exit `97`.
2. Parse a stub Gate and assert both `harness_stub is true` and `not_verification_evidence is true`.
