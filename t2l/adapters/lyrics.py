from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from t2l.adapters.assets import MaterializedAssetSet
from t2l.contracts import Diagnostic, LyricsPlan, LyricsToken
from t2l.errors import LyricsInputError

Phonetizer = Callable[[str], Iterable[tuple[str, str]]]
PhoneEncoder = Callable[[Sequence[Sequence[str]]], tuple[object, object, object, object]]
G2P = Callable[[str], Sequence[str]]
ResourceFinder = Callable[[str], bool]
ResourcePreparer = Callable[[], str | Path | MaterializedAssetSet]

_REQUIRED_NLTK_RESOURCES = (
    "taggers/averaged_perceptron_tagger.zip",
    "corpora/cmudict.zip",
)
_NLTK_DATA_PATH_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class LegacyLyricsPayload:
    lines: tuple[tuple[str, ...], ...]
    phonetics: tuple[tuple[str, ...], ...]
    phones: tuple[str, ...]
    word_spans: tuple[tuple[int, int], ...]
    line_spans: tuple[tuple[int, int], ...]
    pre_lines_unprocessed: str = ""


def _default_phonetizer(line: str):
    from t2l.phonetic import phonetize

    return phonetize(line)


def _nltk_resource_exists(name: str, root: Path | None = None) -> bool:
    import nltk

    try:
        paths = None if root is None else [str(root)]
        nltk.data.find(name, paths=paths)
    except LookupError:
        return False
    return True


def _register_nltk_data_root(root: Path) -> None:
    """Prepend one verified root without duplicating global NLTK search entries."""

    import nltk

    value = str(root)
    with _NLTK_DATA_PATH_LOCK:
        nltk.data.path[:] = [entry for entry in nltk.data.path if entry != value]
        nltk.data.path.insert(0, value)


def _create_g2p():
    # g2p-en 2.1.0 downloads NLTK data at import time when these resources
    # are absent. OfflineG2PProvider verifies them before reaching this import.
    from g2p_en import G2p

    return G2p()


class OfflineG2PProvider:
    """Runtime-local, lazy G2P that fails closed instead of downloading data."""

    def __init__(
        self,
        *,
        prepare_resources: ResourcePreparer | None = None,
        resource_finder: ResourceFinder | None = None,
        g2p_factory: Callable[[], G2P] | None = None,
    ) -> None:
        self._prepare_resources = prepare_resources
        self._resource_finder = resource_finder
        self._g2p_factory = g2p_factory or _create_g2p
        self._g2p: G2P | None = None
        self._failure: Exception | None = None
        self._resource_root: Path | None = None
        self._resource_assets: MaterializedAssetSet | None = None
        self._lock = threading.RLock()

    def _get(self) -> G2P:
        with self._lock:
            if self._g2p is not None:
                return self._g2p
            if self._failure is not None:
                raise self._failure
            try:
                resource_root = None
                if self._prepare_resources is not None:
                    prepared = self._prepare_resources()
                    if isinstance(prepared, MaterializedAssetSet):
                        self._resource_assets = prepared
                        resource_root = prepared.root
                    else:
                        resource_root = Path(prepared).resolve()
                with _NLTK_DATA_PATH_LOCK:
                    if resource_root is not None:
                        _register_nltk_data_root(resource_root)
                    missing = tuple(
                        name
                        for name in _REQUIRED_NLTK_RESOURCES
                        if not (
                            self._resource_finder(name)
                            if self._resource_finder is not None
                            else _nltk_resource_exists(name, resource_root)
                        )
                    )
                    if missing:
                        raise LyricsInputError(
                            "Required offline G2P resources are not installed.",
                            code="T2L_G2P_ASSET_MISSING",
                            details={"resources": missing},
                        )
                    self._g2p = self._g2p_factory()
                self._resource_root = resource_root
            except BaseException as error:
                # Interruptions are control flow, not sticky provider failures.
                # Still release a private materialized asset set so an aborted
                # initialization cannot strand a runtime-owned temporary tree.
                if self._resource_assets is not None:
                    self._resource_assets.close()
                    self._resource_assets = None
                if isinstance(error, Exception):
                    self._failure = error
                raise
            return self._g2p

    def __call__(self, text: str) -> Sequence[str]:
        # g2p-en does not guarantee that one G2p instance is safe for concurrent
        # calls.  Serialize initialization and invocation per runtime while
        # retaining isolation (and parallelism) between distinct runtimes.
        with self._lock:
            return self._get()(text)


class LegacyV1PhoneEncoder:
    """Preserve LegacyV1 ARPABET and half-open span construction."""

    def __init__(self, *, g2p: G2P | None = None) -> None:
        self._g2p = g2p or OfflineG2PProvider()

    def __call__(
        self,
        phonetics: Sequence[Sequence[str]],
    ) -> tuple[
        tuple[str, ...],
        tuple[tuple[str, ...], ...],
        tuple[tuple[int, int], ...],
        tuple[tuple[int, int], ...],
    ]:
        lines = tuple(
            tuple(
                tuple(
                    phone[:-1] if phone and phone[-1].isdigit() else phone
                    for phone in self._g2p(word)
                )
                for word in line
            )
            for line in phonetics
        )
        words = tuple(word for line in lines for word in line)

        phones: list[str] = []
        word_spans: list[tuple[int, int]] = []
        for word in words:
            start = len(phones)
            phones.extend(word)
            word_spans.append((start, len(phones)))
            phones.append(" ")
        if phones:
            phones.pop()

        line_spans: list[tuple[int, int]] = []
        token_offset = 0
        for line in lines:
            line_phone_count = sum(len(word) for word in line) + max(0, len(line) - 1)
            line_spans.append((token_offset, token_offset + line_phone_count))
            token_offset += line_phone_count + 1

        return tuple(phones), words, tuple(word_spans), tuple(line_spans)


class LegacyV1LyricsAdapter:
    """Preserve v1 text segmentation while exposing immutable v2 values."""

    def __init__(
        self,
        *,
        phonetizer: Phonetizer | None = None,
        phone_encoder: PhoneEncoder | None = None,
    ) -> None:
        self._phonetizer = phonetizer or _default_phonetizer
        self._phone_encoder = phone_encoder or LegacyV1PhoneEncoder()

    def prepare(self, lyrics: tuple[str, ...]) -> LyricsPlan:
        phonetics: list[list[str]] = []
        lines: list[list[str]] = []
        pre_lines_unprocessed = ""

        for raw_line in lyrics:
            line = raw_line.strip()
            line = re.sub(r"^\[[\d.:]+\]\s*", "", line)
            line = re.sub(r"^\[[a-zA-Z]{2}:.+\]\s*", "", line)

            line_phonetics: list[str] = []
            words: list[str] = []
            pending_display = ""

            for display, phonetic in self._phonetizer(line):
                if pending_display:
                    display = pending_display + display
                    pending_display = ""
                if re.search(r"[^a-z'~]", phonetic):
                    display_offset = 0
                    pieces = re.split(
                        r'[\s\?\.!@#$%\^&\*\(\)\-\+=`_,\{\[\]\\;:|"/<>0-9]',
                        phonetic,
                    )
                    for piece in pieces:
                        if not piece:
                            continue
                        end = display.find(piece, display_offset) + len(piece)
                        words.append(display[display_offset:end])
                        line_phonetics.append(piece)
                        display_offset = end
                    if display_offset < len(display):
                        if words:
                            words[-1] += display[display_offset:]
                        else:
                            pending_display += display[display_offset:]
                else:
                    words.append(display)
                    line_phonetics.append(phonetic)

            if words:
                phonetics.append(line_phonetics)
                lines.append(words)
            elif lines:
                lines[-1][-1] += "\n" + line
            else:
                pre_lines_unprocessed += (
                    ("\n" if pre_lines_unprocessed else "") + line
                )

        if not lines:
            raise LyricsInputError(
                "Lyrics contain no alignable content.",
                details={"line_count": len(lyrics)},
            )

        phones, _words_p, word_spans, line_spans = self._phone_encoder(phonetics)
        phone_values = tuple(str(phone) for phone in phones)
        word_span_values = tuple(
            (int(start), int(end)) for start, end in word_spans
        )
        line_span_values = tuple(
            (int(start), int(end)) for start, end in line_spans
        )

        tokens: list[LyricsToken] = []
        token_index = 0
        for line_index, words in enumerate(lines):
            for text in words:
                tokens.append(LyricsToken(token_index, line_index, text))
                token_index += 1

        from t2l.mtl.utils import phone2int

        unknown_count = sum(phone not in phone2int for phone in phone_values)
        diagnostics = ()
        if unknown_count:
            diagnostics = (
                Diagnostic(
                    code="T2L_UNKNOWN_PHONE",
                    stage="lyrics",
                    message="Unknown phones map to the LegacyV1 blank class.",
                    details={"count": unknown_count},
                ),
            )

        payload = LegacyLyricsPayload(
            lines=tuple(tuple(line) for line in lines),
            phonetics=tuple(tuple(line) for line in phonetics),
            phones=phone_values,
            word_spans=word_span_values,
            line_spans=line_span_values,
            pre_lines_unprocessed=pre_lines_unprocessed,
        )
        return LyricsPlan(
            tokens=tuple(tokens), payload=payload, diagnostics=diagnostics
        )
