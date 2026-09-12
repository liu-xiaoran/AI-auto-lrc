"""Cross-layer contract checks for the stable error registry."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import MappingProxyType

from t2l.errors import (
    DIAGNOSTIC_CODES,
    ERROR_REGISTRY,
    T2LError,
    create_registered_error,
    registration_for,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPOSITORY_ROOT / "t2l"
ERROR_TOKEN = re.compile(r"\bT2L_[A-Z0-9_]+\b")
NON_ERROR_PROTOCOL_TOKENS = frozenset({"T2L_ASSET_ROOT", "T2L_PROGRESS"})


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _keyword_string(node: ast.Call, name: str) -> str | None:
    for keyword in node.keywords:
        if (
            keyword.arg == name
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ):
            return keyword.value.value
    return None


def _literal_detail_keys(node: ast.Call) -> set[str] | None:
    for keyword in node.keywords:
        if keyword.arg != "details" or not isinstance(keyword.value, ast.Dict):
            continue
        keys = {
            key.value
            for key in keyword.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        return keys
    return None


def _has_details_keyword(node: ast.Call) -> bool:
    return any(keyword.arg == "details" for keyword in node.keywords)


def _assert_required_details(
    registration,
    node: ast.Call,
    path: Path,
) -> None:
    if not registration.required_details:
        return
    assert _has_details_keyword(node), (
        f"{path} must construct {registration.code} with required details"
    )
    keys = _literal_detail_keys(node)
    if keys is None:
        return
    missing = set(registration.required_details) - keys
    assert not missing, (
        f"{path} omits required details for {registration.code}: {sorted(missing)}"
    )


def test_error_registry_is_complete_unique_and_machine_readable():
    assert isinstance(ERROR_REGISTRY, MappingProxyType)
    assert tuple(ERROR_REGISTRY) == tuple(
        registration.code for registration in ERROR_REGISTRY.values()
    )
    assert len(ERROR_REGISTRY) == len(set(ERROR_REGISTRY))

    for code, registration in ERROR_REGISTRY.items():
        assert code == registration.code
        assert issubclass(registration.exception_type, BaseException)
        assert registration.stage
        assert len(registration.required_details) == len(
            set(registration.required_details)
        )
        assert registration.cause_policy in {
            "optional-preserved",
            "propagate-unchanged",
        }
        assert registration.safe_message_policy in {"redact", "generic"}
        assert 1 <= registration.cli_exit_code <= 255


def test_registered_error_factory_owns_dynamic_type_and_stage_routing():
    checkpoint = create_registered_error(
        "CHECKPOINT_NOT_ALLOWLISTED", "fixture"
    )
    alignment = create_registered_error(
        "ALIGNMENT_MEMORY_LIMIT",
        "fixture",
        details={"estimated": 2, "limit": 1},
    )

    assert type(checkpoint) is ERROR_REGISTRY[checkpoint.code].exception_type
    assert checkpoint.stage == ERROR_REGISTRY[checkpoint.code].stage
    assert type(alignment) is ERROR_REGISTRY[alignment.code].exception_type
    assert alignment.stage == ERROR_REGISTRY[alignment.code].stage


def test_unregistered_or_mismatched_domain_errors_fail_closed_to_code_one():
    unregistered = T2LError("fixture", code="T2L_TEST_ONLY")
    mismatched = T2LError(
        "fixture",
        code="T2L_CONFIG_INVALID",
        stage="configuration",
    )

    for error in (unregistered, mismatched):
        registration = registration_for(error)
        assert registration.code == "T2L_ERROR"
        assert registration.cli_exit_code == 1
        assert registration.safe_message_policy == "redact"


def test_production_error_codes_are_registered_and_callsite_types_do_not_drift():
    error_types = {
        registration.exception_type.__name__: registration.exception_type
        for registration in ERROR_REGISTRY.values()
        if issubclass(registration.exception_type, T2LError)
    }
    observed_tokens: set[str] = set()

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        observed_tokens.update(ERROR_TOKEN.findall(source))
        tree = ast.parse(source, filename=str(path))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_name = _call_name(node)
            if call_name == "_failure" and node.args:
                raw_code = node.args[0]
                if isinstance(raw_code, ast.Constant) and isinstance(
                    raw_code.value, str
                ):
                    code = raw_code.value
                    if not code.startswith("T2L_"):
                        code = f"T2L_{code}"
                    assert code in ERROR_REGISTRY, (
                        f"unregistered _failure code {code} in {path}"
                    )
                    _assert_required_details(ERROR_REGISTRY[code], node, path)
                continue
            if call_name not in error_types:
                continue

            error_type = error_types[call_name]
            code = _keyword_string(node, "code") or error_type.default_code
            stage = _keyword_string(node, "stage") or error_type.default_stage
            registration = ERROR_REGISTRY[code]
            assert registration.exception_type is error_type, (
                f"{path} constructs {code} with {call_name}, expected "
                f"{registration.exception_type.__name__}"
            )
            assert registration.stage == stage, (
                f"{path} constructs {code} at {stage}, expected "
                f"{registration.stage}"
            )
            _assert_required_details(registration, node, path)

    allowed_tokens = (
        set(ERROR_REGISTRY) | set(DIAGNOSTIC_CODES) | set(NON_ERROR_PROTOCOL_TOKENS)
    )
    assert observed_tokens <= allowed_tokens, (
        f"unregistered production T2L tokens: "
        f"{sorted(observed_tokens - allowed_tokens)}"
    )
