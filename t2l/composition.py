"""The sole default composition root for the v2 application."""

from __future__ import annotations

from pathlib import Path

from t2l.adapters.assets import AssetLocator, AssetSpec, MaterializedAssetSet
from t2l.adapters.audio import AudioPreparationAdapter
from t2l.adapters.legacy_v1_inference import LegacyV1Inference
from t2l.adapters.lyrics import (
    LegacyV1LyricsAdapter,
    LegacyV1PhoneEncoder,
    OfflineG2PProvider,
)
from t2l.api import AlignmentRuntime
from t2l.application.align_lyrics import AlignLyricsUseCase
from t2l.application.ports import ProgressObserverPort
from t2l.contracts import RuntimeConfig
from t2l.domain.lrc import LrcRenderer
from t2l.errors import CheckpointError
from t2l.model_profiles import (
    LegacyV1Profile,
    ManifestValidationError,
    load_legacy_v1_profile,
)
from t2l.phonetic import PhoneticConverter

_NLTK_RESOURCE_PATHS = {
    "nltk-averaged-perceptron-tagger": Path(
        "taggers/averaged_perceptron_tagger.zip"
    ),
    "nltk-cmudict": Path("corpora/cmudict.zip"),
}


def _prepare_g2p_resources(
    locator: AssetLocator,
    profile: LegacyV1Profile,
) -> MaterializedAssetSet:
    """Publish both verified NLTK archives as one private immutable set."""

    return locator.materialize_set(
        {
            logical_name: (
                AssetSpec.from_manifest_entry(profile.runtime_assets[logical_name]),
                destination,
            )
            for logical_name, destination in _NLTK_RESOURCE_PATHS.items()
        }
    )


def _prepare_lid_resource(
    locator: AssetLocator,
    profile: LegacyV1Profile,
) -> MaterializedAssetSet:
    """Publish the verified fastText model at a runtime-owned path."""

    logical_name = "lid-fasttext-176"
    return locator.materialize_set(
        {
            logical_name: (
                AssetSpec.from_manifest_entry(profile.runtime_assets[logical_name]),
                Path("lid.176.ftz"),
            )
        }
    )


def create_default_runtime(
    config: RuntimeConfig,
    *,
    progress_observer: ProgressObserverPort | None = None,
) -> AlignmentRuntime:
    locator = AssetLocator(config.asset_root)
    try:
        profile = load_legacy_v1_profile()
    except ManifestValidationError as cause:
        raise CheckpointError(
            "The bundled LegacyV1 asset manifest is invalid or incompatible.",
            code="T2L_ASSET_MANIFEST_INVALID",
            stage="asset_resolution",
            details={"profile": "legacy-v1"},
            cause=cause,
        ) from cause
    lid_assets = _prepare_lid_resource(locator, profile)
    converter = PhoneticConverter(
        lid_assets.path("lid-fasttext-176"), asset_owner=lid_assets
    )
    g2p = OfflineG2PProvider(
        prepare_resources=lambda: _prepare_g2p_resources(locator, profile)
    )
    phone_encoder = LegacyV1PhoneEncoder(g2p=g2p)
    lyrics = LegacyV1LyricsAdapter(
        phonetizer=converter.phonetize,
        phone_encoder=phone_encoder,
    )
    audio = AudioPreparationAdapter()
    inference = LegacyV1Inference(
        asset_locator=locator,
        profile=profile,
        device=config.device,
    )
    use_case = AlignLyricsUseCase(
        lyrics=lyrics,
        audio=audio,
        inference=inference,
        renderer=LrcRenderer(),
        progress_observer=progress_observer,
    )
    return AlignmentRuntime(config=config, use_case=use_case)


__all__ = ["create_default_runtime"]
