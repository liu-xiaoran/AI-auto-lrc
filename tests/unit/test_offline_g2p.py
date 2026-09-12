"""Offline, runtime-scoped English phone encoding gates."""

from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest

from t2l.adapters.lyrics import LegacyV1PhoneEncoder, OfflineG2PProvider
from t2l.errors import LyricsInputError


def test_off_001_missing_nltk_assets_fail_before_g2p_import():
    """OFF-001: missing lexical assets fail closed before g2p-en can download."""

    calls = Counter()

    def forbidden_factory():
        calls["factory"] += 1
        raise AssertionError("g2p-en must not import when offline assets are missing")

    provider = OfflineG2PProvider(
        resource_finder=lambda _name: False,
        g2p_factory=forbidden_factory,
    )

    with pytest.raises(LyricsInputError) as first:
        provider("hello")
    with pytest.raises(LyricsInputError) as second:
        provider("hello")

    assert first.value is second.value
    assert first.value.code == "T2L_G2P_ASSET_MISSING"
    assert first.value.stage == "lyrics"
    assert first.value.details == {
        "resources": (
            "taggers/averaged_perceptron_tagger.zip",
            "corpora/cmudict.zip",
        )
    }
    assert calls == Counter()


def test_legacy_phone_encoder_preserves_phone_and_half_open_span_layout():
    """TXT-019: runtime G2P keeps LegacyV1 phones, spaces, and span semantics."""

    pronunciations = {
        "hello": ["HH", "AH0"],
        "world": ["W", "ER1", "L", "D"],
        "again": ["AH0", "G", "EH1", "N"],
    }
    encoder = LegacyV1PhoneEncoder(
        g2p=lambda word: pronunciations[word]
    )

    phones, words, word_spans, line_spans = encoder(
        (("hello", "world"), ("again",))
    )

    assert phones == ("HH", "AH", " ", "W", "ER", "L", "D", " ", "AH", "G", "EH", "N")
    assert words == (("HH", "AH"), ("W", "ER", "L", "D"), ("AH", "G", "EH", "N"))
    assert word_spans == ((0, 2), (3, 7), (8, 12))
    assert line_spans == ((0, 7), (8, 12))


def test_txt_020_concurrent_first_use_initializes_one_runtime_g2p(monkeypatch):
    """TXT-020: concurrent first use constructs exactly one runtime G2P."""

    calls = Counter()
    calls_lock = threading.Lock()
    workers = 16
    start = threading.Barrier(workers + 1)

    def prepare_resources():
        with calls_lock:
            calls["prepare"] += 1
        return "/verified-nltk-data"

    def create_g2p():
        with calls_lock:
            calls["factory"] += 1
        return lambda text: (text.upper(),)

    monkeypatch.setattr("t2l.adapters.lyrics._register_nltk_data_root", lambda _root: None)

    provider = OfflineG2PProvider(
        prepare_resources=prepare_resources,
        resource_finder=lambda _name: True,
        g2p_factory=create_g2p,
    )

    def encode():
        start.wait()
        return provider("hello")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(encode) for _ in range(workers)]
        start.wait()
        results = [future.result(timeout=2) for future in futures]

    assert results == [("HELLO",)] * workers
    assert calls == Counter({"prepare": 1, "factory": 1})


def test_g2p_prepare_failure_is_cached_only_by_owning_provider(monkeypatch):
    """One provider caches preparation failure; a fresh one retries."""

    calls = Counter()
    failure = LyricsInputError(
        "fixture asset verification failed",
        code="T2L_G2P_ASSET_FIXTURE",
    )

    def prepare_resources():
        calls["prepare"] += 1
        if calls["prepare"] == 1:
            raise failure
        return "/verified-nltk-data"

    monkeypatch.setattr("t2l.adapters.lyrics._register_nltk_data_root", lambda _root: None)

    first = OfflineG2PProvider(
        prepare_resources=prepare_resources,
        resource_finder=lambda _name: True,
        g2p_factory=lambda: lambda text: (text,),
    )
    for _ in range(2):
        with pytest.raises(LyricsInputError) as error:
            first("hello")
        assert error.value is failure
    assert calls == Counter({"prepare": 1})

    fresh = OfflineG2PProvider(
        prepare_resources=prepare_resources,
        resource_finder=lambda _name: True,
        g2p_factory=lambda: lambda text: (text,),
    )
    assert fresh("hello") == ("hello",)
    assert calls == Counter({"prepare": 2})
