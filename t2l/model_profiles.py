"""Validated model profiles for the frozen LegacyV1 inference graph.

This module deliberately has no torch dependency.  Reading a manifest must be
safe before a checkpoint is trusted or deserialized.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from types import MappingProxyType
from typing import Any

from t2l._version import PACKAGE_VERSION

DISTRIBUTION_NAME = "ai-auto-lrc"
LEGACY_V1_PROFILE_ID = "legacy-v1"
LEGACY_V1_PROFILE_CONTRACT_VERSION = 1
_KNOWN_ARCHITECTURES = {
    "Baseline": "legacy-v1-acoustic-baseline",
    "MTL": "legacy-v1-acoustic-mtl",
    "BDR": "legacy-v1-boundary",
}
_KNOWN_RUNTIME_ASSETS = (
    "lid-fasttext-176",
    "nltk-averaged-perceptron-tagger",
    "nltk-cmudict",
)


class ManifestValidationError(ValueError):
    """Raised when a model manifest violates the frozen profile contract."""


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    spec_id: str
    sample_rate: int
    n_mels: int
    n_fft: int
    win_length: int
    hop_length: int
    power: float
    center: bool
    pad_mode: str
    normalized: bool
    mel_scale: str


@dataclass(frozen=True, slots=True)
class ArchitectureSpec:
    architecture_id: str
    kind: str
    n_cnn_layers: int
    rnn_dim: int
    n_feats: int
    stride: int
    dropout: float
    output_classes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CheckpointSpec:
    logical_name: str
    profile_id: str
    relative_path: Path
    sha256: str
    size_bytes: int
    architecture_id: str
    feature_spec_id: str
    phone_inventory_id: str
    state_dict_key_count: int
    state_dict_signature_sha256: str
    source: str
    license: str
    output_classes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RuntimeAssetSpec:
    logical_name: str
    relative_path: Path
    sha256: str
    size_bytes: int
    source: str
    license: str


@dataclass(frozen=True, slots=True)
class ManifestCompatibility:
    distribution: str
    package_version: str
    profile_id: str
    profile_contract_version: int


@dataclass(frozen=True, slots=True)
class LegacyV1Profile:
    schema_version: int
    profile_id: str
    compatibility: ManifestCompatibility
    feature: FeatureSpec
    phone_inventory_id: str
    frame_clock_numerator: int
    frame_clock_denominator: int
    lstm_batch_first: tuple[bool, bool, bool]
    architectures: Mapping[str, ArchitectureSpec]
    checkpoints: Mapping[str, CheckpointSpec]
    runtime_assets: Mapping[str, RuntimeAssetSpec]
    manifest_path: Path


def _required(mapping: Mapping[str, Any], key: str, context: str) -> Any:
    try:
        return mapping[key]
    except KeyError as exc:
        raise ManifestValidationError(f"{context} is missing required field {key!r}") from exc


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestValidationError(f"{context} must be a JSON object")
    return value


def _positive_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ManifestValidationError(f"{context} must be a positive integer")
    return value


def _installed_package_version() -> str:
    """Return distribution metadata, with a narrow source-tree fallback."""

    try:
        return distribution_version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return PACKAGE_VERSION


def _parse_compatibility(
    document: Mapping[str, Any], *, manifest_profile_id: str
) -> ManifestCompatibility:
    raw = _mapping(_required(document, "compatibility", "manifest"), "compatibility")
    distribution = str(_required(raw, "distribution", "compatibility"))
    package_version = str(_required(raw, "package_version", "compatibility"))
    profile_id = str(_required(raw, "profile_id", "compatibility"))
    profile_contract_version = _positive_int(
        _required(raw, "profile_contract_version", "compatibility"),
        "profile_contract_version",
    )

    if distribution != DISTRIBUTION_NAME:
        raise ManifestValidationError(
            f"manifest distribution must be {DISTRIBUTION_NAME!r}, got {distribution!r}"
        )
    installed_version = _installed_package_version()
    if package_version != installed_version:
        raise ManifestValidationError(
            "manifest package_version is incompatible with the installed distribution: "
            f"expected {installed_version!r}, got {package_version!r}"
        )
    if package_version != PACKAGE_VERSION:
        raise ManifestValidationError(
            "installed distribution metadata is incompatible with this package code: "
            f"expected {PACKAGE_VERSION!r}, got {package_version!r}"
        )
    if profile_id != manifest_profile_id or profile_id != LEGACY_V1_PROFILE_ID:
        raise ManifestValidationError(
            "compatibility profile_id does not match the manifest profile contract"
        )
    if profile_contract_version != LEGACY_V1_PROFILE_CONTRACT_VERSION:
        raise ManifestValidationError(
            "unsupported compatibility profile_contract_version "
            f"{profile_contract_version}"
        )
    return ManifestCompatibility(
        distribution=distribution,
        package_version=package_version,
        profile_id=profile_id,
        profile_contract_version=profile_contract_version,
    )


def _parse_feature(document: Mapping[str, Any]) -> FeatureSpec:
    raw = _mapping(_required(document, "feature_spec", "manifest"), "feature_spec")
    return FeatureSpec(
        spec_id=str(_required(raw, "id", "feature_spec")),
        sample_rate=_positive_int(_required(raw, "sample_rate", "feature_spec"), "sample_rate"),
        n_mels=_positive_int(_required(raw, "n_mels", "feature_spec"), "n_mels"),
        n_fft=_positive_int(_required(raw, "n_fft", "feature_spec"), "n_fft"),
        win_length=_positive_int(_required(raw, "win_length", "feature_spec"), "win_length"),
        hop_length=_positive_int(_required(raw, "hop_length", "feature_spec"), "hop_length"),
        power=float(_required(raw, "power", "feature_spec")),
        center=bool(_required(raw, "center", "feature_spec")),
        pad_mode=str(_required(raw, "pad_mode", "feature_spec")),
        normalized=bool(_required(raw, "normalized", "feature_spec")),
        mel_scale=str(_required(raw, "mel_scale", "feature_spec")),
    )


def _parse_architectures(document: Mapping[str, Any]) -> dict[str, ArchitectureSpec]:
    raw_architectures = _mapping(
        _required(document, "architectures", "manifest"), "architectures"
    )
    architectures: dict[str, ArchitectureSpec] = {}
    for architecture_id, value in raw_architectures.items():
        raw = _mapping(value, f"architecture {architecture_id!r}")
        output = _required(raw, "output_classes", f"architecture {architecture_id!r}")
        if not isinstance(output, list) or not output:
            raise ManifestValidationError(
                f"architecture {architecture_id!r} output_classes must be a non-empty list"
            )
        architectures[architecture_id] = ArchitectureSpec(
            architecture_id=architecture_id,
            kind=str(_required(raw, "kind", f"architecture {architecture_id!r}")),
            n_cnn_layers=_positive_int(raw.get("n_cnn_layers"), "n_cnn_layers"),
            rnn_dim=_positive_int(raw.get("rnn_dim"), "rnn_dim"),
            n_feats=_positive_int(raw.get("n_feats"), "n_feats"),
            stride=_positive_int(raw.get("stride"), "stride"),
            dropout=float(_required(raw, "dropout", f"architecture {architecture_id!r}")),
            output_classes=tuple(_positive_int(item, "output_classes") for item in output),
        )
    return architectures


def _safe_relative_path(value: Any, context: str) -> Path:
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts:
        raise ManifestValidationError(f"{context} relative_path must remain below asset root")
    return path


def _parse_runtime_assets(
    document: Mapping[str, Any],
) -> dict[str, RuntimeAssetSpec]:
    raw_assets = _mapping(
        _required(document, "runtime_assets", "manifest"), "runtime_assets"
    )
    if tuple(raw_assets) != _KNOWN_RUNTIME_ASSETS:
        raise ManifestValidationError(
            "runtime_assets must list exactly the pinned LID, NLTK tagger, and CMUdict"
        )
    parsed: dict[str, RuntimeAssetSpec] = {}
    for logical_name in _KNOWN_RUNTIME_ASSETS:
        raw = _mapping(raw_assets[logical_name], f"runtime asset {logical_name!r}")
        sha256 = str(_required(raw, "sha256", logical_name)).lower()
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ManifestValidationError(
                f"runtime asset {logical_name!r} has invalid sha256"
            )
        source = str(_required(raw, "source", logical_name))
        license_name = str(_required(raw, "license", logical_name))
        if not source or not license_name:
            raise ManifestValidationError(
                f"runtime asset {logical_name!r} requires source and license"
            )
        parsed[logical_name] = RuntimeAssetSpec(
            logical_name=logical_name,
            relative_path=_safe_relative_path(
                _required(raw, "relative_path", logical_name), logical_name
            ),
            sha256=sha256,
            size_bytes=_positive_int(
                _required(raw, "size_bytes", logical_name), "size_bytes"
            ),
            source=source,
            license=license_name,
        )
    return parsed


def load_legacy_v1_profile(path: str | Path | None = None) -> LegacyV1Profile:
    """Load and validate the allowlisted LegacyV1 manifest.

    Validation includes cross-checking profile, architecture, feature, and phone
    identifiers.  A loadable state dict can therefore never override manifest
    identity.
    """

    manifest_resource = (
        Path(path)
        if path is not None
        else resources.files("t2l._assets").joinpath("legacy_v1_manifest.json")
    )
    try:
        document = json.loads(manifest_resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestValidationError(
            f"Cannot read model manifest {manifest_resource}: {exc}"
        ) from exc
    document = _mapping(document, "manifest")

    schema_version = _positive_int(
        _required(document, "schema_version", "manifest"), "schema_version"
    )
    if schema_version != 1:
        raise ManifestValidationError(f"Unsupported manifest schema_version {schema_version}")
    profile_id = str(_required(document, "profile_id", "manifest"))
    if profile_id != LEGACY_V1_PROFILE_ID:
        raise ManifestValidationError(
            f"manifest profile_id must be {LEGACY_V1_PROFILE_ID!r}, got {profile_id!r}"
        )
    compatibility = _parse_compatibility(
        document,
        manifest_profile_id=profile_id,
    )

    feature = _parse_feature(document)
    phone_inventory_id = str(_required(document, "phone_inventory_id", "manifest"))
    architectures = _parse_architectures(document)
    raw_checkpoints = _mapping(
        _required(document, "checkpoints", "manifest"), "checkpoints"
    )
    if tuple(raw_checkpoints) != tuple(_KNOWN_ARCHITECTURES):
        raise ManifestValidationError(
            "checkpoints must list exactly Baseline, MTL, and BDR in canonical order"
        )

    checkpoints: dict[str, CheckpointSpec] = {}
    for logical_name, expected_architecture in _KNOWN_ARCHITECTURES.items():
        raw = _mapping(raw_checkpoints[logical_name], f"checkpoint {logical_name!r}")
        checkpoint_profile = str(_required(raw, "profile_id", logical_name))
        if checkpoint_profile != profile_id:
            raise ManifestValidationError(
                f"checkpoint {logical_name!r} profile_id {checkpoint_profile!r} "
                f"does not match {profile_id!r}"
            )
        architecture_id = str(_required(raw, "architecture_id", logical_name))
        if architecture_id != expected_architecture or architecture_id not in architectures:
            raise ManifestValidationError(
                f"checkpoint {logical_name!r} architecture_id must be "
                f"{expected_architecture!r}, got {architecture_id!r}"
            )
        feature_spec_id = str(_required(raw, "feature_spec_id", logical_name))
        if feature_spec_id != feature.spec_id:
            raise ManifestValidationError(
                f"checkpoint {logical_name!r} feature_spec_id does not match profile"
            )
        checkpoint_phone_id = str(_required(raw, "phone_inventory_id", logical_name))
        if checkpoint_phone_id != phone_inventory_id:
            raise ManifestValidationError(
                f"checkpoint {logical_name!r} phone_inventory_id does not match profile"
            )
        sha256 = str(_required(raw, "sha256", logical_name)).lower()
        signature = str(_required(raw, "state_dict_signature_sha256", logical_name)).lower()
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ManifestValidationError(f"checkpoint {logical_name!r} has invalid sha256")
        if len(signature) != 64 or any(c not in "0123456789abcdef" for c in signature):
            raise ManifestValidationError(
                f"checkpoint {logical_name!r} has invalid state_dict signature"
            )
        checkpoints[logical_name] = CheckpointSpec(
            logical_name=logical_name,
            profile_id=checkpoint_profile,
            relative_path=_safe_relative_path(
                _required(raw, "relative_path", logical_name), logical_name
            ),
            sha256=sha256,
            size_bytes=_positive_int(_required(raw, "size_bytes", logical_name), "size_bytes"),
            architecture_id=architecture_id,
            feature_spec_id=feature_spec_id,
            phone_inventory_id=checkpoint_phone_id,
            state_dict_key_count=_positive_int(
                _required(raw, "state_dict_key_count", logical_name),
                "state_dict_key_count",
            ),
            state_dict_signature_sha256=signature,
            source=str(_required(raw, "source", logical_name)),
            license=str(_required(raw, "license", logical_name)),
            output_classes=architectures[architecture_id].output_classes,
        )

    runtime_assets = _parse_runtime_assets(document)

    frame_clock = _mapping(_required(document, "frame_clock", "manifest"), "frame_clock")
    axes = _required(document, "lstm_batch_first", "manifest")
    if axes != [True, False, False]:
        raise ManifestValidationError(
            "LegacyV1 lstm_batch_first must remain [true, false, false]"
        )

    return LegacyV1Profile(
        schema_version=schema_version,
        profile_id=profile_id,
        compatibility=compatibility,
        feature=feature,
        phone_inventory_id=phone_inventory_id,
        frame_clock_numerator=_positive_int(frame_clock.get("numerator"), "frame numerator"),
        frame_clock_denominator=_positive_int(
            frame_clock.get("denominator"), "frame denominator"
        ),
        lstm_batch_first=tuple(axes),
        architectures=MappingProxyType(architectures),
        checkpoints=MappingProxyType(checkpoints),
        runtime_assets=MappingProxyType(runtime_assets),
        manifest_path=Path(str(manifest_resource)).resolve(),
    )
