#!/usr/bin/env bash
# Produce two independent S18 coverage attempts without combining data or overwriting evidence.

set -u
set -o pipefail
umask 077

input_invalid() { echo "SECURITY_COVERAGE_RUNNER_INPUT_INVALID" >&2; exit 2; }
configuration_invalid() { echo "SECURITY_COVERAGE_RUNNER_CONFIGURATION_INVALID" >&2; exit 2; }

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: run_security_coverage.sh ABSOLUTE_ARTIFACT_ROOT RUN_ID [ATTEMPT]" >&2
  exit 2
fi
artifact_root=$1
run_id=$2
attempt=${3:-1}
case "$artifact_root" in /*) ;; *) input_invalid ;; esac
if [ -e "$artifact_root" ] || [ -L "$artifact_root" ]; then
  input_invalid
fi

case "$0" in */*) script_directory=${0%/*} ;; *) script_directory=. ;; esac
repository_root=$(CDPATH= cd -- "$script_directory/.." 2>/dev/null && pwd -P) || configuration_invalid
policy_path="$repository_root/packaging/security-coverage-policy.toml"
manifest_path="$repository_root/packaging/security-coverage-manifest.json"
verifier_path="$repository_root/scripts/verify_security_coverage.py"
runner_path="$repository_root/scripts/run_security_coverage.sh"
bootstrap_path="$repository_root/scripts/security_pytest_bootstrap.py"
pytest_config_path="$repository_root/pyproject.toml"
pytest_events_plugin_path="$repository_root/scripts/pytest_security_events.py"
uv_lock_path="$repository_root/uv.lock"

unset PYTHONPATH PYTHONHOME PYTHONUSERBASE UV_PROJECT_ENVIRONMENT UV_PYTHON
unset PYTEST_ADDOPTS PYTEST_PLUGINS
if ! uv_candidate=$(command -v uv); then configuration_invalid; fi
case "$uv_candidate" in /*) ;; *) configuration_invalid ;; esac
if [[ "$uv_candidate" =~ [[:cntrl:]] ]]; then configuration_invalid; fi

absolute_uv=$uv_candidate
uv_alias_hops=0
uv_seen_paths=("")
while :; do
  uv_parent=${absolute_uv%/*}
  uv_leaf=${absolute_uv##*/}
  [ -n "$uv_leaf" ] || configuration_invalid
  [ -n "$uv_parent" ] || uv_parent=/
  canonical_uv_parent=$(CDPATH= cd -- "$uv_parent" 2>/dev/null && pwd -P) || configuration_invalid
  absolute_uv="$canonical_uv_parent/$uv_leaf"
  if [[ "$absolute_uv" =~ [[:cntrl:]] ]]; then configuration_invalid; fi
  for uv_seen in "${uv_seen_paths[@]}"; do
    [ -z "$uv_seen" ] || [ "$uv_seen" != "$absolute_uv" ] || configuration_invalid
  done
  uv_seen_paths+=("$absolute_uv")
  if [ ! -L "$absolute_uv" ]; then break; fi
  uv_alias_hops=$((uv_alias_hops + 1))
  [ "$uv_alias_hops" -le 16 ] || configuration_invalid
  uv_target_with_marker=$(
    /usr/bin/readlink "$absolute_uv"
    uv_readlink_status=$?
    printf '.%03d' "$uv_readlink_status"
  ) || configuration_invalid
  uv_readlink_status=${uv_target_with_marker: -3}
  [ "$uv_readlink_status" = 000 ] || configuration_invalid
  uv_target_output=${uv_target_with_marker:0:${#uv_target_with_marker}-4}
  case "$uv_target_output" in *$'\n') ;; *) configuration_invalid ;; esac
  uv_target=${uv_target_output%$'\n'}
  if [ -z "$uv_target" ] || [[ "$uv_target" =~ [[:cntrl:]] ]]; then configuration_invalid; fi
  case "$uv_target" in /*) absolute_uv=$uv_target ;; *) absolute_uv="$canonical_uv_parent/$uv_target" ;; esac
done
if [ ! -f "$absolute_uv" ] || [ ! -x "$absolute_uv" ] || [ -L "$absolute_uv" ]; then configuration_invalid; fi
cd "$repository_root" || configuration_invalid

uv_hash() {
  "$absolute_uv" run --offline --frozen --no-sync python -I -S -B - "$absolute_uv" <<'PY'
import hashlib
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
limit = 64 * 1024 * 1024
try:
    if path.resolve(strict=True) != path:
        raise ValueError
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_mode & 0o111 == 0:
        raise ValueError
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        def identity(value):
            return (value.st_dev, value.st_ino, value.st_uid, stat.S_IFMT(value.st_mode), value.st_nlink, value.st_size, value.st_mtime_ns)
        if identity(before) != identity(opened):
            raise ValueError
        digest = hashlib.sha256()
        remaining = limit
        while True:
            chunk = os.read(descriptor, min(65536, remaining + 1))
            if not chunk:
                break
            if len(chunk) > remaining:
                raise ValueError
            digest.update(chunk)
            remaining -= len(chunk)
        if identity(opened) != identity(os.fstat(descriptor)):
            raise ValueError
    finally:
        os.close(descriptor)
    if identity(before) != identity(path.lstat()):
        raise ValueError
except (OSError, RuntimeError, ValueError):
    raise SystemExit(1)
sys.stdout.write(digest.hexdigest())
PY
}

if ! uv_executable_sha256_a=$(uv_hash 2>/dev/null); then configuration_invalid; fi
if [[ ! "$uv_executable_sha256_a" =~ ^[0-9a-f]{64}$ ]]; then configuration_invalid; fi
if ! uv_version=$(
  "$absolute_uv" run --offline --frozen --no-sync python -I -S -B - "$absolute_uv" 2>/dev/null <<'PY'
import re
import subprocess
import sys
import threading
process = subprocess.Popen(
    [sys.argv[1], "--version"],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
)
assert process.stdout is not None
timed_out = [False]
def expire():
    timed_out[0] = True
    process.kill()
timer = threading.Timer(5.0, expire)
timer.start()
raw = process.stdout.read(513)
if len(raw) > 512:
    process.kill()
status = process.wait()
timer.cancel()
if timed_out[0] or status != 0 or len(raw) > 512 or not raw:
    raise SystemExit(1)
if raw.endswith(b"\n"):
    raw = raw[:-1]
if not raw or b"\r" in raw or b"\n" in raw or any(byte < 32 or byte > 126 for byte in raw):
    raise SystemExit(1)
try:
    banner = raw.decode("ascii")
except UnicodeDecodeError:
    raise SystemExit(1)
match = re.fullmatch(r"uv ([0-9]+(?:\.[0-9]+){1,3}(?:[A-Za-z0-9._+-]*)?)(?: \(([^()]+)\))?", banner)
if match is None or len(match.group(1)) > 128:
    raise SystemExit(1)
sys.stdout.write(match.group(1))
PY
); then configuration_invalid; fi
if [ -z "$uv_version" ] || [ "${#uv_version}" -gt 128 ] || [[ ! "$uv_version" =~ ^[0-9]+(\.[0-9]+){1,3}([A-Za-z0-9._+-]*)?$ ]]; then configuration_invalid; fi
if ! uv_executable_sha256_b=$(uv_hash 2>/dev/null); then configuration_invalid; fi
if [[ ! "$uv_executable_sha256_b" =~ ^[0-9a-f]{64}$ ]]; then configuration_invalid; fi
if [ "$uv_executable_sha256_a" != "$uv_executable_sha256_b" ]; then configuration_invalid; fi
uv_executable_sha256_before=$uv_executable_sha256_b

platform_value=$(/usr/bin/uname -s 2>/dev/null)/$(/usr/bin/uname -m 2>/dev/null) || configuration_invalid
case "$platform_value" in
  Darwin/arm64|Darwin/x86_64) runner=macos ;;
  Linux/x86_64) runner=linux ;;
  *) echo "SECURITY_COVERAGE_RUNNER_PLATFORM_INVALID" >&2; exit 2 ;;
esac

if ! input_result=$("$absolute_uv" run --offline --frozen --no-sync python -I -S -B - "$artifact_root" "$run_id" "$attempt" 2>/dev/null <<'PY'
import re
import stat
import sys
from pathlib import Path
root = Path(sys.argv[1])
try:
    if not root.is_absolute() or root.exists() or root.is_symlink(): raise ValueError
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", sys.argv[2]) is None: raise ValueError
    if re.fullmatch(r"[1-9][0-9]*", sys.argv[3]) is None: raise ValueError
    parent = root.parent
    if parent.resolve(strict=True) != parent or not parent.is_dir(): raise ValueError
    current = Path(parent.anchor)
    for component in parent.parts[1:]:
        current = current / component
        value = current.lstat()
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode): raise ValueError
except (FileNotFoundError, NotADirectoryError, RuntimeError, ValueError):
    sys.stdout.write("INPUT_INVALID")
except OSError:
    raise SystemExit(1)
else:
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        sys.stdout.write("INPUT_INVALID")
    except OSError:
        raise SystemExit(1)
    else:
        sys.stdout.write("INPUT_OK")
PY
); then configuration_invalid; fi
case "$input_result" in INPUT_OK) ;; INPUT_INVALID) input_invalid ;; *) configuration_invalid ;; esac

sha256_file() {
  "$absolute_uv" run --offline --frozen --no-sync python -I -S -B - "$1" <<'PY'
import hashlib
import os
import stat
import sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        if identity(before) != identity(opened):
            raise ValueError
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if identity(opened) != identity(os.fstat(descriptor)):
            raise ValueError
    finally:
        os.close(descriptor)
    if identity(before) != identity(path.lstat()):
        raise ValueError
except (OSError, ValueError):
    raise SystemExit(1)
sys.stdout.write(digest)
PY
}

policy_before=$(sha256_file "$policy_path") || configuration_invalid
manifest_before=$(sha256_file "$manifest_path") || configuration_invalid
runner_before=$(sha256_file "$runner_path") || configuration_invalid
verifier_before=$(sha256_file "$verifier_path") || configuration_invalid
bootstrap_before=$(sha256_file "$bootstrap_path") || configuration_invalid
pytest_config_before=$(sha256_file "$pytest_config_path") || configuration_invalid
pytest_events_plugin_before=$(sha256_file "$pytest_events_plugin_path") || configuration_invalid
uv_lock_before=$(sha256_file "$uv_lock_path") || configuration_invalid
policy_limits=$(
  "$absolute_uv" run --offline --frozen --no-sync python -I -S -B - "$policy_path" <<'PY'
import sys
import tomllib
from pathlib import Path
try:
    policy = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    limits = policy["limits"]
    values = (policy["schema_version"], limits["testcases"], limits["pytest_events_nodeid_bytes"], limits["pytest_events_bytes"], limits["plugin_identity_bytes"])
    if type(values[0]) is not int or values[0] != 3 or any(type(value) is not int for value in values[1:]) or values[1:] != (4096, 4096, 8388608, 4194304):
        raise ValueError
except (KeyError, OSError, TypeError, UnicodeError, ValueError, tomllib.TOMLDecodeError):
    raise SystemExit(1)
sys.stdout.write(":".join(str(value) for value in values[1:]))
PY
) || configuration_invalid
IFS=: read -r max_cases max_nodeid_bytes max_events_bytes max_identity_bytes <<EOF
$policy_limits
EOF

overall_status=0
run_one() {
  target=$1; module=$2; source_path=$3; test_file=$4; coverage_name=$5
  target_dir="$artifact_root/$target"
  mkdir -m 700 "$target_dir" || return 2
  coverage_data="$target_dir/$coverage_name"
  coverage_json="$target_dir/coverage.json"
  junit_xml="$target_dir/junit.xml"
  pytest_events_json="$target_dir/pytest-events.json"
  plugin_identity_json="$target_dir/plugin-identity.json"
  stdout_log="$target_dir/stdout.log"
  stderr_log="$target_dir/stderr.log"
  environment_json="$target_dir/environment.json"
  command_json="$target_dir/command.json"
  run_manifest_json="$target_dir/run-manifest.json"
  gate_json="$target_dir/gate.json"
  verifier_stderr="$target_dir/verifier.stderr.log"
  source_before=$(sha256_file "$repository_root/$source_path") || return 2
  test_before=$(sha256_file "$repository_root/$test_file") || return 2
  started_at=$("$absolute_uv" run --offline --frozen --no-sync python -I -S -B - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
PY
  ) || return 2

  command=(
    "$absolute_uv" run --offline --frozen --no-sync python -I -S -B "$bootstrap_path"
    "--plugin-identity=$plugin_identity_json"
    "--runtime-uv-path=$absolute_uv"
    "--runtime-uv-version=$uv_version"
    "--runtime-uv-sha256=$uv_executable_sha256_before"
    "--runtime-timestamp=$started_at"
    -- "$test_file" -q -c pyproject.toml --noconftest
    -p no:cacheprovider -p pytest_cov.plugin -p scripts.pytest_security_events
    -o xfail_strict=true
    "--security-events=$pytest_events_json" "--security-run-id=$run_id"
    "--security-target=$target" "--security-runner=$runner" "--security-attempt=$attempt"
    "--security-test-file=$test_file" "--security-max-cases=$max_cases"
    "--security-max-nodeid-bytes=$max_nodeid_bytes" "--security-max-events-bytes=$max_events_bytes"
    "--junitxml=$junit_xml" "--cov=$module" --cov-branch
    "--cov-report=json:$coverage_json" --cov-report=term-missing --cov-fail-under=80
  )
  (
    unset PYTHONPATH PYTHONHOME PYTHONUSERBASE UV_PROJECT_ENVIRONMENT UV_PYTHON
    unset PYTEST_ADDOPTS PYTEST_PLUGINS
    export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 COVERAGE_FILE="$coverage_data"
    "${command[@]}"
  ) >"$stdout_log" 2>"$stderr_log"
  pytest_status=$?
  finished_at=$("$absolute_uv" run --offline --frozen --no-sync python -I -S -B - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
PY
  ) || return 2
  source_after=$(sha256_file "$repository_root/$source_path") || return 2
  test_after=$(sha256_file "$repository_root/$test_file") || return 2
  policy_after=$(sha256_file "$policy_path") || return 2
  manifest_after=$(sha256_file "$manifest_path") || return 2
  runner_after=$(sha256_file "$runner_path") || return 2
  verifier_after=$(sha256_file "$verifier_path") || return 2
  bootstrap_after=$(sha256_file "$bootstrap_path") || return 2
  pytest_config_after=$(sha256_file "$pytest_config_path") || return 2
  pytest_events_plugin_after=$(sha256_file "$pytest_events_plugin_path") || return 2
  uv_lock_after=$(sha256_file "$uv_lock_path") || return 2
  uv_executable_sha256_after=$(uv_hash) || return 2

  "$absolute_uv" run --offline --frozen --no-sync python -I -S -B - \
    "$environment_json" "$plugin_identity_json" "$max_identity_bytes" "$run_id" "$target" "$runner" "$attempt" \
    "$source_before" "$source_after" "$test_before" "$test_after" "$policy_before" "$policy_after" \
    "$manifest_before" "$manifest_after" "$runner_before" "$runner_after" "$verifier_before" "$verifier_after" \
    "$bootstrap_before" "$bootstrap_after" "$pytest_config_before" "$pytest_config_after" \
    "$pytest_events_plugin_before" "$pytest_events_plugin_after" "$uv_lock_before" "$uv_lock_after" \
    "$uv_executable_sha256_before" "$uv_executable_sha256_after" <<'PY'
import hashlib, json, os, platform, re, stat, subprocess, sys
from pathlib import Path
(
    output, identity_path, identity_limit, run_id, target, runner, attempt,
    source_before, source_after, test_before, test_after, policy_before, policy_after,
    manifest_before, manifest_after, runner_before, runner_after, verifier_before, verifier_after,
    bootstrap_before, bootstrap_after, pytest_config_before, pytest_config_after,
    events_before, events_after, lock_before, lock_after, uv_before, uv_after,
) = sys.argv[1:]
def identity_candidate(path_text, limit):
    path = Path(path_text)
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1:
            return None, None
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            ident = lambda value: (value.st_dev, value.st_ino, value.st_uid, stat.S_IFMT(value.st_mode), value.st_nlink, value.st_size, value.st_mtime_ns)
            if ident(before) != ident(opened):
                return None, None
            chunks = []
            remaining = limit
            while True:
                chunk = os.read(descriptor, min(65536, remaining + 1))
                if not chunk: break
                if len(chunk) > remaining: return None, None
                chunks.append(chunk); remaining -= len(chunk)
            if ident(opened) != ident(os.fstat(descriptor)): return None, None
        finally: os.close(descriptor)
        if ident(before) != ident(path.lstat()): return None, None
    except OSError:
        return None, None
    raw = b"".join(chunks)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        def pairs(values):
            result = {}
            for key, item in values:
                if key in result: raise ValueError
                result[key] = item
            return result
        def constant(_value):
            raise ValueError
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        semantic = value["semantic_runtime_sha256"]
        if type(value) is not dict or type(value.get("schema_version")) is not int or value["schema_version"] != 2 or not isinstance(semantic, str) or re.fullmatch(r"[0-9a-f]{64}", semantic) is None:
            return digest, None
        versions = {"coverage": value["distributions"]["coverage"]["installed"]["version"], "pytest": value["distributions"]["pytest"]["installed"]["version"], "uv": value["uv"]["version"]}
        if any(not isinstance(item, str) or len(item) > 128 or re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}(?:[A-Za-z0-9._+-]*)?", item) is None for item in versions.values()):
            return digest, None
        return digest, (semantic, versions)
    except (KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        return digest, None
artifact_sha, extracted = identity_candidate(identity_path, int(identity_limit))
semantic = extracted[0] if extracted else None
versions = extracted[1] if extracted else {"coverage": None, "pytest": None, "uv": None}
def git(*arguments):
    return subprocess.run(["git", *arguments], check=True, capture_output=True, text=True).stdout.strip()
value = {
    "schema_version": 5, "run_id": run_id, "target": target, "runner": runner, "attempt": int(attempt),
    "platform": {"system": platform.system(), "machine": platform.machine(), "python_implementation": platform.python_implementation(), "python_version": platform.python_version()},
    "tools": versions,
    "runtime_identity": {"artifact_sha256": artifact_sha, "semantic_runtime_sha256": semantic},
    "repository": {
        "git_head": git("rev-parse", "HEAD"), "base_ref": "HEAD", "dirty": bool(git("status", "--porcelain=v1", "--untracked-files=all")),
        "source_sha256_before": source_before, "source_sha256_after": source_after, "test_sha256_before": test_before, "test_sha256_after": test_after,
        "policy_sha256_before": policy_before, "policy_sha256_after": policy_after, "manifest_sha256_before": manifest_before, "manifest_sha256_after": manifest_after,
        "runner_sha256_before": runner_before, "runner_sha256_after": runner_after, "verifier_sha256_before": verifier_before, "verifier_sha256_after": verifier_after,
        "bootstrap_sha256_before": bootstrap_before, "bootstrap_sha256_after": bootstrap_after, "pytest_config_sha256_before": pytest_config_before, "pytest_config_sha256_after": pytest_config_after,
        "pytest_events_plugin_sha256_before": events_before, "pytest_events_plugin_sha256_after": events_after, "uv_lock_sha256_before": lock_before, "uv_lock_sha256_after": lock_after,
        "uv_executable_sha256_before": uv_before, "uv_executable_sha256_after": uv_after,
    },
}
Path(output).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  environment_status=$?

  "$absolute_uv" run --offline --frozen --no-sync python -I -S -B - "$command_json" "$run_id" "$target" "$runner" "$attempt" "$pytest_status" "$started_at" "$finished_at" "$coverage_data" "${command[@]}" <<'PY'
import json, sys
from pathlib import Path
output, run_id, target, runner, attempt, exit_code, started_at, finished_at, coverage_file, *argv = sys.argv[1:]
value = {
    "schema_version": 4, "run_id": run_id, "target": target, "runner": runner, "attempt": int(attempt), "argv": argv,
    "sanitized_environment": {"COVERAGE_FILE": coverage_file, "PYTHONHOME": None, "PYTHONPATH": None, "PYTHONUSERBASE": None, "PYTEST_ADDOPTS": None, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_PLUGINS": None, "UV_PROJECT_ENVIRONMENT": None, "UV_PYTHON": None},
    "exit_code": int(exit_code), "started_at": started_at, "finished_at": finished_at,
}
Path(output).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  command_status=$?

  if [ "$environment_status" -ne 0 ] || [ "$command_status" -ne 0 ] || [ ! -f "$coverage_data" ] || [ ! -f "$coverage_json" ] || [ ! -f "$junit_xml" ] || [ ! -f "$plugin_identity_json" ]; then
    "$absolute_uv" run --offline --frozen --no-sync python -I -S -B - "$target_dir/runner-error.json" "$run_id" "$target" "$runner" "$attempt" "$pytest_status" "$environment_status" "$command_status" "$target_dir" "$coverage_name" <<'PY'
import hashlib, json, stat, sys
from pathlib import Path
output, run_id, target, runner, attempt, pytest_status, environment_status, command_status, target_dir, coverage_name = sys.argv[1:]
root = Path(target_dir)
known = (coverage_name, "coverage.json", "junit.xml", "pytest-events.json", "plugin-identity.json", "environment.json", "command.json", "stdout.log", "stderr.log")
required = {coverage_name, "coverage.json", "junit.xml", "plugin-identity.json", "environment.json", "command.json"}
present = []
for name in known:
    try: value = (root / name).lstat()
    except OSError: continue
    if stat.S_ISREG(value.st_mode): present.append(name)
present.sort(); missing = sorted(set(known) - set(present))
hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in present}
if int(environment_status) != 0: reason = "ENVIRONMENT_ARTIFACT_WRITE_FAILED"
elif int(command_status) != 0: reason = "COMMAND_ARTIFACT_WRITE_FAILED"
elif required & set(missing): reason = "REQUIRED_RAW_ARTIFACT_MISSING"
else: raise SystemExit(1)
value = {"schema_version": 2, "run_id": run_id, "target": target, "runner": runner, "attempt": int(attempt), "stage": "raw-completeness", "reason_code": reason, "pytest_exit_code": int(pytest_status), "environment_exit_code": int(environment_status), "command_exit_code": int(command_status), "qualification": "INCOMPLETE_RAW_EVIDENCE", "present_artifacts": present, "missing_artifacts": missing, "present_hashes": hashes}
Path(output).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
    return 1
  fi

  "$absolute_uv" run --offline --frozen --no-sync python -I -S -B - "$run_manifest_json" "$run_id" "$target" "$runner" "$attempt" "$max_identity_bytes" "$repository_root/$source_path" "$repository_root/$test_file" "$policy_path" "$manifest_path" "$runner_path" "$verifier_path" "$bootstrap_path" "$pytest_config_path" "$pytest_events_plugin_path" "$uv_lock_path" "$coverage_json" "$junit_xml" "$pytest_events_json" "$plugin_identity_json" "$environment_json" "$command_json" <<'PY'
import hashlib, json, os, re, stat, sys
from pathlib import Path
output, run_id, target, runner, attempt, identity_limit, *artifacts = sys.argv[1:]
names = ("source_sha256", "test_sha256", "policy_sha256", "manifest_sha256", "runner_sha256", "verifier_sha256", "bootstrap_sha256", "pytest_config_sha256", "pytest_events_plugin_sha256", "uv_lock_sha256", "coverage_sha256", "junit_sha256", "pytest_events_sha256", "plugin_identity_sha256", "environment_sha256", "command_sha256")
def file_hash(name, path_text):
    path = Path(path_text)
    if name == "pytest_events_sha256" and not path.exists(): return hashlib.sha256(b"").hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536): digest.update(chunk)
    return digest.hexdigest()
hashes = {name: file_hash(name, path) for name, path in zip(names, artifacts, strict=True)}
semantic = None
try:
    path = Path(artifacts[13]); before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1: raise ValueError
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        ident = lambda item: (item.st_dev, item.st_ino, item.st_uid, stat.S_IFMT(item.st_mode), item.st_nlink, item.st_size, item.st_mtime_ns)
        if ident(before) != ident(opened): raise ValueError
        raw = os.read(descriptor, int(identity_limit) + 1)
        if len(raw) > int(identity_limit) or os.read(descriptor, 1): raise ValueError
        if ident(opened) != ident(os.fstat(descriptor)): raise ValueError
    finally: os.close(descriptor)
    if ident(before) != ident(path.lstat()): raise ValueError
    def pairs(values):
        result = {}
        for key, item in values:
            if key in result: raise ValueError
            result[key] = item
        return result
    def constant(_value): raise ValueError
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    candidate = value["semantic_runtime_sha256"]
    if type(value) is dict and type(value.get("schema_version")) is int and value["schema_version"] == 2 and isinstance(candidate, str) and re.fullmatch(r"[0-9a-f]{64}", candidate): semantic = candidate
except (OSError, KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError, RecursionError): pass
value = {"schema_version": 5, "run_id": run_id, "target": target, "runner": runner, "attempt": int(attempt), "artifact_hashes": hashes, "semantic_runtime_sha256": semantic}
Path(output).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  manifest_status=$?
  [ "$manifest_status" -eq 0 ] || return 1

  "$absolute_uv" run --offline --frozen --no-sync python -I -S -B "$verifier_path" --target "$target" --coverage "$coverage_json" --junit "$junit_xml" --pytest-events "$pytest_events_json" --plugin-identity "$plugin_identity_json" --environment "$environment_json" --command "$command_json" --run-manifest "$run_manifest_json" --policy "$policy_path" --manifest "$manifest_path" --output "$gate_json" 2>"$verifier_stderr"
  verifier_status=$?
  if [ "$pytest_status" -ne 0 ] || [ "$verifier_status" -ne 0 ]; then return 1; fi
  return 0
}

run_one capture scripts.capture_test_gate scripts/capture_test_gate.py tests/contract/test_evidence_capture.py .coverage-capture || overall_status=1
run_one retention scripts.manage_evidence_retention scripts/manage_evidence_retention.py tests/contract/test_evidence_retention.py .coverage-retention || overall_status=1
exit "$overall_status"
