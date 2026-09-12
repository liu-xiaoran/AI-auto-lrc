"""Controlled shell harness for the S18 B3f-R2 runner contracts.

The harness copies the runner's repository inputs into a temporary repository and
places a recording fake ``uv`` on ``PATH``.  Importing this module has no side
effects.  Only :meth:`RunnerHarness.run` starts the copied runner.

The fake uv delegates embedded ``python -I -S -B -`` helpers to a caller-selected
absolute Python executable.  It never executes the security bootstrap.  A real
verifier can be delegated explicitly; a stub verifier result is marked as
harness-only and must not be treated as verification evidence.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

DEFAULT_COPY_PATHS = (
    "packaging/security-coverage-policy.toml",
    "packaging/security-coverage-manifest.json",
    "pyproject.toml",
    "scripts/capture_test_gate.py",
    "scripts/manage_evidence_retention.py",
    "scripts/pytest_security_events.py",
    "scripts/run_security_coverage.sh",
    "scripts/security_pytest_bootstrap.py",
    "scripts/verify_security_coverage.py",
    "tests/contract/test_evidence_capture.py",
    "tests/contract/test_evidence_retention.py",
    "uv.lock",
)

SANITIZED_ENVIRONMENT_NAMES = (
    "COVERAGE_FILE",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONUSERBASE",
    "PYTEST_ADDOPTS",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "PYTEST_PLUGINS",
    "UV_PROJECT_ENVIRONMENT",
    "UV_PYTHON",
)

EXACT_UV_RUN_PREFIX = (
    "run",
    "--offline",
    "--frozen",
    "--no-sync",
    "python",
    "-I",
    "-S",
    "-B",
)


class HarnessError(RuntimeError):
    """Raised when the harness itself cannot preserve its evidence boundary."""


@dataclass(frozen=True)
class BootstrapArtifacts:
    """Raw files that one intercepted bootstrap invocation should publish.

    ``None`` means that the named raw artifact is deliberately absent.  Bytes are
    written verbatim.  The identity payload alone supports ASCII placeholders for
    invocation-bound values: ``{{RUN_ID}}``, ``{{TARGET}}``, ``{{RUNNER}}``,
    ``{{ATTEMPT}}``, ``{{RUNTIME_TIMESTAMP}}``, ``{{UV_PATH}}``,
    ``{{UV_VERSION}}``, and ``{{UV_SHA256}}``.
    """

    plugin_identity: bytes | None
    pytest_events: bytes | None
    coverage_data: bytes | None
    coverage_json: bytes | None
    junit_xml: bytes | None
    exit_code: int = 0
    stdout: bytes = b""
    stderr: bytes = b""
    rebind_identity_semantic: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
            raise TypeError("bootstrap exit_code must be an integer")
        for name in (
            "plugin_identity",
            "pytest_events",
            "coverage_data",
            "coverage_json",
            "junit_xml",
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bytes):
                raise TypeError(f"{name} must be bytes or None")
        if not isinstance(self.stdout, bytes) or not isinstance(self.stderr, bytes):
            raise TypeError("bootstrap stdout and stderr must be bytes")
        if not isinstance(self.rebind_identity_semantic, bool):
            raise TypeError("rebind_identity_semantic must be a boolean")


ArtifactSupplier = Callable[[str, str, int], BootstrapArtifacts]


@dataclass(frozen=True)
class AliasSpec:
    """One uv alias hop; relative targets model the Homebrew-style entry."""

    relative: bool = True


VerifierMode = Literal["real", "stub-success", "stub-failure"]
GateKind = Literal["real", "stub", "absent"]


@dataclass(frozen=True)
class RunnerScenario:
    """Configuration for one copied-runner invocation."""

    version_stdout: bytes = b"uv 0.12.9 (Harness build)\n"
    version_exit_code: int = 0
    input_helper_exit_code: int | None = None
    input_helper_stderr: bytes = b""
    input_helper_validation_errno: int | None = None
    input_helper_mkdir_errno: int | None = None
    environment_identity_errno: int | None = None
    aliases: tuple[AliasSpec, ...] = (AliasSpec(relative=True),)
    alias_cycle: bool = False
    poison_path_after_first_call: bool = False
    verifier_mode: VerifierMode = "stub-failure"
    verifier_exit_code: int | None = None
    extra_environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.version_stdout, bytes):
            raise TypeError("version_stdout must be bytes")
        if isinstance(self.version_exit_code, bool) or not isinstance(
            self.version_exit_code, int
        ):
            raise TypeError("version_exit_code must be an integer")
        if self.input_helper_exit_code is not None and (
            isinstance(self.input_helper_exit_code, bool)
            or not isinstance(self.input_helper_exit_code, int)
            or not 1 <= self.input_helper_exit_code <= 255
        ):
            raise TypeError("input_helper_exit_code must be a nonzero byte exit code")
        if not isinstance(self.input_helper_stderr, bytes):
            raise TypeError("input_helper_stderr must be bytes")
        if self.input_helper_exit_code is None and self.input_helper_stderr:
            raise ValueError("input_helper_stderr requires input_helper_exit_code")
        for name in ("input_helper_validation_errno", "input_helper_mkdir_errno"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise TypeError(f"{name} must be a positive integer")
        if sum(
            value is not None
            for value in (
                self.input_helper_exit_code,
                self.input_helper_validation_errno,
                self.input_helper_mkdir_errno,
            )
        ) > 1:
            raise ValueError("input helper failure modes are mutually exclusive")
        if self.environment_identity_errno is not None and (
            isinstance(self.environment_identity_errno, bool)
            or not isinstance(self.environment_identity_errno, int)
            or self.environment_identity_errno <= 0
        ):
            raise TypeError("environment_identity_errno must be a positive integer")
        if self.verifier_mode not in {"real", "stub-success", "stub-failure"}:
            raise ValueError("unsupported verifier_mode")
        if self.verifier_exit_code is not None and (
            isinstance(self.verifier_exit_code, bool)
            or not isinstance(self.verifier_exit_code, int)
        ):
            raise TypeError("verifier_exit_code must be an integer or None")
        if self.poison_path_after_first_call and not self.aliases:
            raise ValueError("PATH poisoning requires at least one alias hop")
        if self.alias_cycle and len(self.aliases) < 2:
            raise ValueError("an alias cycle requires at least two alias hops")
        if any(not isinstance(item, AliasSpec) for item in self.aliases):
            raise TypeError("aliases must contain AliasSpec values")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.extra_environment.items()
        ):
            raise TypeError("extra_environment must map strings to strings")


@dataclass(frozen=True)
class FakeUvCall:
    """One JSONL observation emitted by the fake uv."""

    sequence: int
    kind: str
    argv: tuple[str, ...]
    cwd: str
    environment: Mapping[str, str | None]
    prefix_valid: bool | None


@dataclass(frozen=True)
class RunnerResult:
    """Completed runner result plus paths to the harness-owned evidence."""

    returncode: int
    stdout: str
    stderr: str
    repository_root: Path
    artifact_root: Path
    call_log_path: Path

    def calls(self) -> tuple[FakeUvCall, ...]:
        if not self.call_log_path.exists():
            return ()
        result: list[FakeUvCall] = []
        for line_number, line in enumerate(
            self.call_log_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                value = json.loads(line)
                result.append(
                    FakeUvCall(
                        sequence=int(value["sequence"]),
                        kind=str(value["kind"]),
                        argv=tuple(value["argv"]),
                        cwd=str(value["cwd"]),
                        environment=dict(value["environment"]),
                        prefix_valid=value["prefix_valid"],
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise HarnessError(
                    f"invalid fake uv call record at line {line_number}"
                ) from exc
        return tuple(result)

    @property
    def verifier_executed(self) -> bool:
        return any(call.kind == "verifier-real" for call in self.calls())

    def artifacts(self, target: str) -> dict[str, Path]:
        if target not in {"capture", "retention"}:
            raise ValueError("target must be capture or retention")
        directory = self.artifact_root / target
        coverage_name = ".coverage-capture" if target == "capture" else ".coverage-retention"
        return {
            "directory": directory,
            "coverage_data": directory / coverage_name,
            "coverage_json": directory / "coverage.json",
            "junit_xml": directory / "junit.xml",
            "pytest_events": directory / "pytest-events.json",
            "plugin_identity": directory / "plugin-identity.json",
            "environment": directory / "environment.json",
            "command": directory / "command.json",
            "run_manifest": directory / "run-manifest.json",
            "gate": directory / "gate.json",
            "runner_error": directory / "runner-error.json",
            "stdout": directory / "stdout.log",
            "stderr": directory / "stderr.log",
            "verifier_stderr": directory / "verifier.stderr.log",
        }

    def gate_kind(self, target: str) -> GateKind:
        gate = self.artifacts(target)["gate"]
        if not gate.exists():
            return "absent"
        try:
            value = json.loads(gate.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HarnessError("gate output is neither a real nor a marked stub") from exc
        if isinstance(value, dict) and value.get("harness_stub") is True:
            return "stub"
        if any(
            call.kind == "verifier-real"
            and any(
                call.argv[index : index + 2] == ("--target", target)
                for index in range(len(call.argv) - 1)
            )
            for call in self.calls()
        ):
            return "real"
        raise HarnessError("unmarked gate output was not produced by a real verifier call")


_FAKE_UV_SOURCE = r'''#!{python}
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

PREFIX = ["run", "--offline", "--frozen", "--no-sync", "python", "-I", "-S", "-B"]
ENV_NAMES = {env_names}
config = json.loads(Path(os.environ["R2_HARNESS_CONFIG"]).read_text(encoding="utf-8"))
log_path = Path(os.environ["R2_HARNESS_CALL_LOG"])
arguments = sys.argv[1:]

def classify():
    if arguments == ["--version"]:
        return "version", None
    prefix_valid = arguments[:len(PREFIX)] == PREFIX
    if not prefix_valid or len(arguments) <= len(PREFIX):
        return "invalid-prefix", prefix_valid
    program = arguments[len(PREFIX)]
    if program == "-":
        if arguments[len(PREFIX):] == [
            "-",
            config["artifact_root"],
            config["run_id"],
            str(config["attempt"]),
        ]:
            return "input-helper", True
        payload = arguments[len(PREFIX):]
        if (
            len(payload) > 2
            and Path(payload[1]).name == "environment.json"
            and Path(payload[2]).name == "plugin-identity.json"
            and Path(config["artifact_root"]) in Path(payload[1]).parents
            and Path(config["artifact_root"]) in Path(payload[2]).parents
        ):
            return "environment-helper", True
        return "embedded-python", True
    if program == config["bootstrap_path"]:
        return "bootstrap-stub", True
    if program == config["verifier_path"]:
        mode = config["verifier_mode"]
        return ("verifier-real" if mode == "real" else "verifier-stub"), True
    return "blocked-program", True

kind, prefix_valid = classify()
sequence = 1
if log_path.exists():
    with log_path.open("rb") as stream:
        sequence += sum(1 for _line in stream)
record = {{
    "sequence": sequence,
    "kind": kind,
    "argv": sys.argv,
    "cwd": os.getcwd(),
    "environment": {{name: os.environ.get(name) for name in ENV_NAMES}},
    "prefix_valid": prefix_valid,
}}
with log_path.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, sort_keys=True) + "\n")

if config.get("poison_path_after_first_call"):
    marker = Path(config["poison_marker"])
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(descriptor)
        entry = Path(config["path_entry_uv"])
        temporary = entry.with_name(entry.name + ".poison-next")
        temporary.symlink_to(config["poison_uv_path"])
        os.replace(temporary, entry)

def option(prefix):
    matches = [item[len(prefix):] for item in arguments if item.startswith(prefix)]
    if len(matches) != 1:
        raise SystemExit(98)
    return matches[0]

def separate_option(name):
    indexes = [index for index, item in enumerate(arguments) if item == name]
    if len(indexes) != 1 or indexes[0] + 1 >= len(arguments):
        raise SystemExit(98)
    return arguments[indexes[0] + 1]

def write_once(path_text, content):
    if content is None:
        return
    path = Path(path_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
    finally:
        os.close(descriptor)

def decoded(name, plan):
    value = plan[name]
    return None if value is None else base64.b64decode(value, validate=True)

def rebind_identity_semantic(content):
    def pairs(values):
        result = {{}}
        for key, value in values:
            if key in result:
                raise ValueError
            result[key] = value
        return result
    def constant(_value):
        raise ValueError
    value = json.loads(
        content.decode("utf-8"),
        object_pairs_hook=pairs,
        parse_constant=constant,
    )
    required_top = {{
        "schema_version", "provenance", "scope", "runtime", "uv",
        "uv_lock_sha256", "distributions", "plugins", "semantic_runtime_sha256",
    }}
    scope = value.get("scope") if isinstance(value, dict) else None
    claimed = value.get("semantic_runtime_sha256") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 2
        or set(value) != required_top
        or not isinstance(scope, dict)
        or set(scope) != {{"run_id", "target", "runner", "attempt", "timestamp"}}
        or not isinstance(scope["runner"], str)
        or not isinstance(claimed, str)
        or len(claimed) != 64
        or any(character not in "0123456789abcdef" for character in claimed)
    ):
        raise ValueError
    semantic = dict(value)
    semantic.pop("semantic_runtime_sha256")
    semantic["scope"] = {{"runner": scope["runner"]}}
    canonical = json.dumps(
        semantic,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    value["semantic_runtime_sha256"] = hashlib.sha256(canonical).hexdigest()
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")

if kind == "version":
    sys.stdout.buffer.write(base64.b64decode(config["version_stdout"], validate=True))
    raise SystemExit(config["version_exit_code"])
if prefix_valid is not True:
    raise SystemExit(97)

payload = arguments[len(PREFIX):]
program = payload[0]
if kind == "input-helper":
    exit_code = config["input_helper_exit_code"]
    if exit_code is not None:
        sys.stderr.buffer.write(
            base64.b64decode(config["input_helper_stderr"], validate=True)
        )
        raise SystemExit(exit_code)
    validation_errno = config["input_helper_validation_errno"]
    if validation_errno is not None:
        source = sys.stdin.buffer.read()
        needle = b"    parent = root.parent"
        if source.count(needle) != 1:
            raise SystemExit(98)
        replacement = (
            b"    raise OSError("
            + str(validation_errno).encode("ascii")
            + b", 'controlled input-helper validation failure')\n"
            + needle
        )
        completed = subprocess.run(
            [config["python_executable"], "-I", "-S", "-B", *payload],
            input=source.replace(needle, replacement),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        sys.stdout.buffer.write(completed.stdout)
        sys.stderr.buffer.write(completed.stderr)
        raise SystemExit(completed.returncode)
    mkdir_errno = config["input_helper_mkdir_errno"]
    if mkdir_errno is not None:
        source = sys.stdin.buffer.read()
        needle = b"        root.mkdir(mode=0o700)"
        if source.count(needle) != 1:
            raise SystemExit(98)
        replacement = (
            b"        raise OSError("
            + str(mkdir_errno).encode("ascii")
            + b", 'controlled input-helper mkdir failure')"
        )
        completed = subprocess.run(
            [config["python_executable"], "-I", "-S", "-B", *payload],
            input=source.replace(needle, replacement),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        sys.stdout.buffer.write(completed.stdout)
        sys.stderr.buffer.write(completed.stderr)
        raise SystemExit(completed.returncode)
    os.execv(config["python_executable"], [config["python_executable"], "-I", "-S", "-B", *payload])
if kind == "environment-helper" and config["environment_identity_errno"] is not None:
    source = sys.stdin.buffer.read()
    needle = b"    try:\n        before = path.lstat()"
    if source.count(needle) != 1:
        raise SystemExit(98)
    replacement = (
        b"    try:\n        raise OSError("
        + str(config["environment_identity_errno"]).encode("ascii")
        + b", 'controlled identity candidate read failure')\n        before = path.lstat()"
    )
    completed = subprocess.run(
        [config["python_executable"], "-I", "-S", "-B", *payload],
        input=source.replace(needle, replacement),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    sys.stdout.buffer.write(completed.stdout)
    sys.stderr.buffer.write(completed.stderr)
    raise SystemExit(completed.returncode)
if kind == "environment-helper":
    os.execv(config["python_executable"], [config["python_executable"], "-I", "-S", "-B", *payload])
if kind == "embedded-python":
    os.execv(config["python_executable"], [config["python_executable"], "-I", "-S", "-B", *payload])

if kind == "bootstrap-stub":
    target = option("--security-target=")
    plan = config["bootstrap_artifacts"].get(target)
    if plan is None:
        raise SystemExit(98)
    identity = decoded("plugin_identity", plan)
    if identity is not None:
        replacements = {{
            b"{{{{RUN_ID}}}}": option("--security-run-id=").encode(),
            b"{{{{TARGET}}}}": target.encode(),
            b"{{{{RUNNER}}}}": option("--security-runner=").encode(),
            b"{{{{ATTEMPT}}}}": option("--security-attempt=").encode(),
            b"{{{{RUNTIME_TIMESTAMP}}}}": option("--runtime-timestamp=").encode(),
            b"{{{{UV_PATH}}}}": option("--runtime-uv-path=").encode(),
            b"{{{{UV_VERSION}}}}": option("--runtime-uv-version=").encode(),
            b"{{{{UV_SHA256}}}}": option("--runtime-uv-sha256=").encode(),
        }}
        for marker, replacement in replacements.items():
            identity = identity.replace(marker, replacement)
        if plan["rebind_identity_semantic"]:
            try:
                identity = rebind_identity_semantic(identity)
            except (KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
                raise SystemExit(98)
    write_once(option("--plugin-identity="), identity)
    write_once(option("--security-events="), decoded("pytest_events", plan))
    write_once(option("--cov-report=json:"), decoded("coverage_json", plan))
    write_once(option("--junitxml="), decoded("junit_xml", plan))
    coverage_path = os.environ.get("COVERAGE_FILE")
    coverage_data = decoded("coverage_data", plan)
    if coverage_path is None and coverage_data is not None:
        raise SystemExit(98)
    if coverage_path is not None:
        write_once(coverage_path, coverage_data)
    sys.stdout.buffer.write(base64.b64decode(plan["stdout"], validate=True))
    sys.stderr.buffer.write(base64.b64decode(plan["stderr"], validate=True))
    raise SystemExit(plan["exit_code"])

if kind == "verifier-real":
    os.execv(config["python_executable"], [config["python_executable"], "-I", "-S", "-B", *payload])
if kind == "verifier-stub":
    if config["verifier_mode"] == "stub-success":
        output = separate_option("--output")
        marker = {{
            "harness_stub": True,
            "not_verification_evidence": True,
            "target": separate_option("--target"),
        }}
        write_once(output, (json.dumps(marker, sort_keys=True) + "\n").encode())
    raise SystemExit(config["verifier_exit_code"])
raise SystemExit(97)
'''


_FAKE_GIT_SOURCE = r'''#!{python}
import sys

arguments = sys.argv[1:]
if arguments == ["rev-parse", "HEAD"]:
    print("1111111111111111111111111111111111111111")
elif arguments and arguments[0] == "status":
    pass
else:
    raise SystemExit(97)
'''


_POISON_UV_SOURCE = r'''#!{python}
import json
import os
import sys
from pathlib import Path

log = Path(os.environ["R2_HARNESS_CALL_LOG"])
record = {{"sequence": -1, "kind": "poison", "argv": sys.argv,
          "cwd": os.getcwd(), "environment": {{}}, "prefix_valid": None}}
with log.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, sort_keys=True) + "\n")
raise SystemExit(99)
'''


@dataclass
class RunnerHarness:
    """Prepared temporary repository and deferred copied-runner executor."""

    workspace: Path
    repository_root: Path
    source_root: Path
    python_executable: Path
    _run_number: int = 0

    @classmethod
    def create(
        cls,
        tmp_path: Path,
        *,
        source_root: Path | None = None,
        python_executable: Path | None = None,
        copy_paths: tuple[str, ...] = DEFAULT_COPY_PATHS,
    ) -> RunnerHarness:
        workspace = Path(tmp_path) / "security-runtime-r2-runner-harness"
        workspace.mkdir(mode=0o700, parents=True)
        source = (
            Path(source_root)
            if source_root is not None
            else Path(__file__).resolve().parents[2]
        ).resolve(strict=True)
        python = Path(python_executable or sys.executable)
        if not python.is_absolute() or not python.exists():
            raise HarnessError("python_executable must be an existing absolute path")
        repository = workspace / "repository"
        repository.mkdir(mode=0o700)
        for relative in copy_paths:
            source_path = source / relative
            if not source_path.is_file():
                raise HarnessError(f"required repository input is missing: {relative}")
            destination = repository / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
        runner = repository / "scripts/run_security_coverage.sh"
        runner.chmod(runner.stat().st_mode | stat.S_IXUSR)
        return cls(
            workspace=workspace,
            repository_root=repository,
            source_root=source,
            python_executable=python.resolve(strict=True),
        )

    def run(
        self,
        artifact_supplier: ArtifactSupplier,
        *,
        scenario: RunnerScenario | None = None,
        run_id: str = "r2-harness",
        attempt: int = 1,
        timeout: float = 30.0,
    ) -> RunnerResult:
        """Run the copied runner; callers own test locking and assertions."""

        if not callable(artifact_supplier):
            raise TypeError("artifact_supplier must be callable")
        if isinstance(attempt, bool) or not isinstance(attempt, int):
            raise TypeError("attempt must be an integer")
        if scenario is None:
            scenario = RunnerScenario()
        self._run_number += 1
        run_directory = self.workspace / f"run-{self._run_number}"
        run_directory.mkdir(mode=0o700)
        tooling = run_directory / "tooling"
        tooling.mkdir(mode=0o700)
        call_log = run_directory / "fake-uv-calls.jsonl"
        configuration = run_directory / "fake-uv-config.json"
        artifact_root = run_directory / "artifacts"

        fake_uv_source = _FAKE_UV_SOURCE.format(
            python=os.fspath(self.python_executable),
            env_names=repr(SANITIZED_ENVIRONMENT_NAMES),
        ).encode("utf-8")
        path_entry, _final_uv = self._install_uv(
            tooling,
            scenario.aliases,
            fake_uv_source,
            cycle=scenario.alias_cycle,
        )
        poison_uv = tooling / "poison-uv"
        self._write_executable(
            poison_uv,
            _POISON_UV_SOURCE.format(python=os.fspath(self.python_executable)).encode(
                "utf-8"
            ),
        )
        git_directory = tooling / "git-bin"
        git_directory.mkdir(mode=0o700)
        self._write_executable(
            git_directory / "git",
            _FAKE_GIT_SOURCE.format(python=os.fspath(self.python_executable)).encode(
                "utf-8"
            ),
        )

        plans = {
            target: self._encode_artifacts(artifact_supplier(target, run_id, attempt))
            for target in ("capture", "retention")
        }
        verifier_exit = scenario.verifier_exit_code
        if verifier_exit is None:
            verifier_exit = 0 if scenario.verifier_mode == "stub-success" else 1
        config_value = {
            "artifact_root": os.fspath(artifact_root),
            "attempt": attempt,
            "bootstrap_artifacts": plans,
            "environment_identity_errno": scenario.environment_identity_errno,
            "bootstrap_path": os.fspath(
                (self.repository_root / "scripts/security_pytest_bootstrap.py").resolve()
            ),
            "input_helper_exit_code": scenario.input_helper_exit_code,
            "input_helper_mkdir_errno": scenario.input_helper_mkdir_errno,
            "input_helper_stderr": base64.b64encode(
                scenario.input_helper_stderr
            ).decode("ascii"),
            "input_helper_validation_errno": scenario.input_helper_validation_errno,
            "path_entry_uv": os.fspath(path_entry / "uv"),
            "poison_marker": os.fspath(run_directory / "path-poisoned"),
            "poison_path_after_first_call": scenario.poison_path_after_first_call,
            "poison_uv_path": os.fspath(poison_uv),
            "python_executable": os.fspath(self.python_executable),
            "run_id": run_id,
            "verifier_exit_code": verifier_exit,
            "verifier_mode": scenario.verifier_mode,
            "verifier_path": os.fspath(
                (self.repository_root / "scripts/verify_security_coverage.py").resolve()
            ),
            "version_exit_code": scenario.version_exit_code,
            "version_stdout": base64.b64encode(scenario.version_stdout).decode("ascii"),
        }
        configuration.write_text(
            json.dumps(config_value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        configuration.chmod(0o600)

        environment = os.environ.copy()
        environment.update(scenario.extra_environment)
        environment.update(
            {
                "PATH": os.pathsep.join(
                    (
                        os.fspath(path_entry),
                        os.fspath(git_directory),
                        "/usr/bin",
                        "/bin",
                    )
                ),
                "R2_HARNESS_CALL_LOG": os.fspath(call_log),
                "R2_HARNESS_CONFIG": os.fspath(configuration),
            }
        )
        completed = subprocess.run(
            [
                os.fspath(self.repository_root / "scripts/run_security_coverage.sh"),
                os.fspath(artifact_root),
                run_id,
                str(attempt),
            ],
            cwd=self.repository_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return RunnerResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            repository_root=self.repository_root,
            artifact_root=artifact_root,
            call_log_path=call_log,
        )

    def _install_uv(
        self,
        tooling: Path,
        aliases: tuple[AliasSpec, ...],
        source: bytes,
        *,
        cycle: bool,
    ) -> tuple[Path, Path]:
        path_entry = tooling / "path-bin"
        path_entry.mkdir(mode=0o700)
        if not aliases:
            final_uv = path_entry / "uv"
            self._write_executable(final_uv, source)
            return path_entry, final_uv

        final_directory = tooling / "final-bin"
        final_directory.mkdir(mode=0o700)
        final_uv = final_directory / "uv-final"
        self._write_executable(final_uv, source)
        alias_paths = [path_entry / "uv"]
        for index in range(1, len(aliases)):
            alias_path = tooling / "aliases" / f"hop-{index}" / "uv"
            alias_path.parent.mkdir(parents=True, exist_ok=True)
            alias_paths.append(alias_path)
        for index, (alias_path, specification) in enumerate(
            zip(alias_paths, aliases, strict=True)
        ):
            target = (
                alias_paths[index + 1]
                if index + 1 < len(alias_paths)
                else alias_paths[0]
                if cycle
                else final_uv
            )
            target_text = (
                os.path.relpath(target, alias_path.parent)
                if specification.relative
                else os.fspath(target)
            )
            alias_path.symlink_to(target_text)
        return path_entry, final_uv

    @staticmethod
    def _write_executable(path: Path, content: bytes) -> None:
        path.write_bytes(content)
        path.chmod(0o700)

    @staticmethod
    def _encode_artifacts(value: BootstrapArtifacts) -> dict[str, object]:
        if not isinstance(value, BootstrapArtifacts):
            raise TypeError("artifact_supplier must return BootstrapArtifacts")

        def encoded(content: bytes | None) -> str | None:
            return None if content is None else base64.b64encode(content).decode("ascii")

        return {
            "plugin_identity": encoded(value.plugin_identity),
            "pytest_events": encoded(value.pytest_events),
            "coverage_data": encoded(value.coverage_data),
            "coverage_json": encoded(value.coverage_json),
            "junit_xml": encoded(value.junit_xml),
            "exit_code": value.exit_code,
            "stdout": encoded(value.stdout),
            "stderr": encoded(value.stderr),
            "rebind_identity_semantic": value.rebind_identity_semantic,
        }

    @property
    def copied_runner_sha256(self) -> str:
        return hashlib.sha256(
            (self.repository_root / "scripts/run_security_coverage.sh").read_bytes()
        ).hexdigest()
