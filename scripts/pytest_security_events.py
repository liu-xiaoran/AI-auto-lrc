"""Pytest plugin that emits canonical per-phase outcome evidence."""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STATE_ATTRIBUTE = "_s18_security_events_state"
_PHASES = ("setup", "call", "teardown")
_OUTCOMES = {"passed", "failed", "skipped"}
_POSITIVE_ASCII_INTEGER = re.compile(r"^[1-9][0-9]*$")
_HARD_MAX_CASES = 4096
_HARD_MAX_NODEID_BYTES = 4096
_HARD_MAX_EVENTS_BYTES = 8388608
_LIMIT_OPTIONS = {
    "testcases": ("--security-max-cases", "security_max_cases", _HARD_MAX_CASES),
    "pytest_events_nodeid_bytes": (
        "--security-max-nodeid-bytes",
        "security_max_nodeid_bytes",
        _HARD_MAX_NODEID_BYTES,
    ),
    "pytest_events_bytes": (
        "--security-max-events-bytes",
        "security_max_events_bytes",
        _HARD_MAX_EVENTS_BYTES,
    ),
}


class EventsPublicationError(RuntimeError):
    """Raised when the events sidecar definitely was not published."""


class EventsCommitUncertain(RuntimeError):
    """Raised after the events sidecar became visible but durability is uncertain."""


def _canonical_name(name: str) -> bool:
    if any(ord(char) < 32 or ord(char) == 127 for char in name) or "::" in name:
        return False
    parameter_start = name.find("[")
    function_name = name if parameter_start == -1 else name[:parameter_start]
    if re.fullmatch(r"test_[A-Za-z0-9_]+", function_name) is None:
        return False
    if parameter_start == -1:
        return "]" not in name
    parameter = name[parameter_start:]
    depth = 0
    for index, char in enumerate(parameter):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if depth < 0 or (depth == 0 and index != len(parameter) - 1):
            return False
    return depth == 0 and parameter.endswith("]")


def _canonical_test_file(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not path.is_absolute()
        and value == path.as_posix()
        and ".." not in path.parts
        and value.endswith(".py")
    )


def _canonical_nodeid(nodeid: str, test_file: str) -> bool:
    prefix = test_file + "::"
    return nodeid.startswith(prefix) and _canonical_name(nodeid.removeprefix(prefix))


def _required_option(config: pytest.Config, name: str) -> str:
    value = config.getoption(name)
    if not isinstance(value, str) or not value:
        raise pytest.UsageError("PYTEST_EVENTS_CONFIGURATION_INVALID")
    return value


def _producer_error(state: dict[str, Any], marker: str) -> None:
    state["fatal"] = True
    raise pytest.UsageError(marker)


def _limit_values(config: pytest.Config) -> dict[str, int]:
    arguments = tuple(config.invocation_params.args)
    limits: dict[str, int] = {}
    for field, (option, destination, hard_ceiling) in _LIMIT_OPTIONS.items():
        matches = [value for value in arguments if value.startswith(option + "=")]
        value = config.getoption(destination)
        if (
            len(matches) != 1
            or not isinstance(value, str)
            or matches[0] != option + "=" + value
            or _POSITIVE_ASCII_INTEGER.fullmatch(value) is None
        ):
            raise pytest.UsageError("PYTEST_EVENTS_CONFIGURATION_INVALID")
        ceiling_text = str(hard_ceiling)
        if len(value) > len(ceiling_text) or (
            len(value) == len(ceiling_text) and value > ceiling_text
        ):
            raise pytest.UsageError("PYTEST_EVENTS_CONFIGURATION_INVALID")
        limits[field] = int(value)
    return limits


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8", "strict")


def _canonical_events_bytes(document: dict[str, object], *, max_bytes: int) -> bytes:
    content = _canonical_json_bytes(document) + b"\n"
    if len(content) > max_bytes:
        raise pytest.UsageError("PYTEST_EVENTS_LIMIT_EXCEEDED")
    return content


def _worst_case_bytes(nodeid: str, *, xfail_marked: bool) -> bytes:
    phase = {"outcome": "skipped", "wasxfail": False}
    return _canonical_json_bytes(
        {
            "nodeid": nodeid,
            "xfail_marked": xfail_marked,
            "phases": {name: phase for name in _PHASES},
        }
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("security-events")
    group.addoption("--security-events", dest="security_events", metavar="PATH")
    group.addoption("--security-run-id", dest="security_run_id", metavar="ID")
    group.addoption("--security-target", dest="security_target", metavar="TARGET")
    group.addoption("--security-runner", dest="security_runner", metavar="RUNNER")
    group.addoption("--security-attempt", dest="security_attempt", metavar="N")
    group.addoption("--security-test-file", dest="security_test_file", metavar="PATH")
    group.addoption("--security-max-cases", dest="security_max_cases", metavar="N")
    group.addoption(
        "--security-max-nodeid-bytes", dest="security_max_nodeid_bytes", metavar="N"
    )
    group.addoption(
        "--security-max-events-bytes", dest="security_max_events_bytes", metavar="N"
    )


def pytest_configure(config: pytest.Config) -> None:
    output_text = _required_option(config, "security_events")
    run_id = _required_option(config, "security_run_id")
    target = _required_option(config, "security_target")
    runner = _required_option(config, "security_runner")
    attempt_text = _required_option(config, "security_attempt")
    test_file = _required_option(config, "security_test_file")
    limits = _limit_values(config)
    output = Path(output_text)
    if (
        not output.is_absolute()
        or output.exists()
        or not _RUN_ID.fullmatch(run_id)
        or target not in {"capture", "retention"}
        or runner not in {"macos", "linux"}
        or not attempt_text.isdecimal()
        or int(attempt_text) < 1
        or not _canonical_test_file(test_file)
    ):
        raise pytest.UsageError("PYTEST_EVENTS_CONFIGURATION_INVALID")
    empty_document = {
        "schema_version": 3,
        "run_id": run_id,
        "target": target,
        "runner": runner,
        "attempt": int(attempt_text),
        "test_file": test_file,
        "limits": limits,
        "cases": [],
    }
    setattr(
        config,
        _STATE_ATTRIBUTE,
        {
            "output": output,
            "run_id": run_id,
            "target": target,
            "runner": runner,
            "attempt": int(attempt_text),
            "test_file": test_file,
            "limits": limits,
            "cases": {},
            "serialized_upper_bound": len(_canonical_json_bytes(empty_document)) + 1,
            "fatal": False,
        },
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    state: dict[str, Any] = getattr(config, _STATE_ATTRIBUTE)
    cases: dict[str, dict[str, Any]] = state["cases"]
    test_file: str = state["test_file"]
    for item in items:
        nodeid = item.nodeid
        if not _canonical_nodeid(nodeid, test_file) or nodeid in cases:
            _producer_error(state, "PYTEST_EVENTS_CONFIGURATION_INVALID")
        if len(nodeid) > state["limits"]["pytest_events_nodeid_bytes"]:
            _producer_error(state, "PYTEST_EVENTS_LIMIT_EXCEEDED")
        try:
            nodeid_bytes = nodeid.encode("utf-8", "strict")
        except UnicodeEncodeError:
            _producer_error(state, "PYTEST_EVENTS_CONFIGURATION_INVALID")
        if len(nodeid_bytes) > state["limits"]["pytest_events_nodeid_bytes"]:
            _producer_error(state, "PYTEST_EVENTS_LIMIT_EXCEEDED")
        if len(cases) >= state["limits"]["testcases"]:
            _producer_error(state, "PYTEST_EVENTS_LIMIT_EXCEEDED")
        xfail_marked = any(item.iter_markers(name="xfail"))
        addition = len(_worst_case_bytes(nodeid, xfail_marked=xfail_marked))
        if cases:
            addition += 1
        if (
            state["serialized_upper_bound"] + addition
            > state["limits"]["pytest_events_bytes"]
        ):
            _producer_error(state, "PYTEST_EVENTS_LIMIT_EXCEEDED")
        cases[nodeid] = {
            "nodeid": nodeid,
            "xfail_marked": xfail_marked,
            "phases": {phase: None for phase in _PHASES},
        }
        state["serialized_upper_bound"] += addition


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Any:
    del call
    outcome = yield
    report = outcome.get_result()
    state: dict[str, Any] = getattr(item.config, _STATE_ATTRIBUTE)
    case = state["cases"].get(report.nodeid)
    if case is None:
        _producer_error(state, "PYTEST_EVENTS_CONFIGURATION_INVALID")
    if (
        report.when not in _PHASES
        or not isinstance(report.outcome, str)
        or report.outcome not in _OUTCOMES
        or case["phases"][report.when] is not None
    ):
        _producer_error(state, "PYTEST_EVENTS_CONFIGURATION_INVALID")
    case["phases"][report.when] = {
        "outcome": report.outcome,
        "wasxfail": bool(getattr(report, "wasxfail", False)),
    }


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor: int | None = None
    directory: int | None = None
    temp_owned = False
    try:
        prepublication_error: OSError | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            temp_owned = True
            os.fchmod(descriptor, 0o600)
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written == 0:
                    raise OSError("events writer made no progress")
                view = view[written:]
            os.fsync(descriptor)
        except OSError as exc:
            prepublication_error = exc
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError as exc:
                    if prepublication_error is None:
                        prepublication_error = exc
                descriptor = None
        if prepublication_error is not None:
            raise EventsPublicationError("PYTEST_EVENTS_PUBLICATION_FAILED") from prepublication_error

        try:
            os.link(temporary, path, follow_symlinks=False)
        except OSError as exc:
            raise EventsPublicationError("PYTEST_EVENTS_PUBLICATION_FAILED") from exc

        postpublication_error: OSError | None = None
        try:
            os.unlink(temporary)
            temp_owned = False
            directory = os.open(
                path.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0),
            )
            try:
                os.fsync(directory)
            except OSError as exc:
                postpublication_error = exc
            try:
                os.close(directory)
            except OSError as exc:
                if postpublication_error is None:
                    postpublication_error = exc
            directory = None
        except OSError as exc:
            postpublication_error = exc
        if postpublication_error is not None:
            raise EventsCommitUncertain("PYTEST_EVENTS_COMMIT_UNCERTAIN") from postpublication_error
    finally:
        if directory is not None:
            with contextlib.suppress(OSError):
                os.close(directory)
        if temp_owned:
            with contextlib.suppress(OSError):
                os.unlink(temporary)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del exitstatus
    state: dict[str, Any] = getattr(session.config, _STATE_ATTRIBUTE)
    if state.get("fatal", False):
        return
    document = {
        "schema_version": 3,
        "run_id": state["run_id"],
        "target": state["target"],
        "runner": state["runner"],
        "attempt": state["attempt"],
        "test_file": state["test_file"],
        "limits": state["limits"],
        "cases": [state["cases"][nodeid] for nodeid in sorted(state["cases"])],
    }
    content = _canonical_events_bytes(
        document,
        max_bytes=state["limits"]["pytest_events_bytes"],
    )
    _atomic_write(state["output"], content)
