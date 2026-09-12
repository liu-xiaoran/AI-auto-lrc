"""Executable documentation integrity checks."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPOSITORY_ROOT / "docs"
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
EXPLICIT_ANCHOR = re.compile(r'<a\s+(?:id|name)="([^"]+)"\s*></a>', re.IGNORECASE)


def _github_slug(heading: str) -> str:
    without_markup = re.sub(r"[`*_~]", "", heading.strip().lower())
    without_punctuation = re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff -]", "", without_markup)
    return re.sub(r"\s+", "-", without_punctuation)


def _anchors(markdown: str) -> set[str]:
    occurrences: Counter[str] = Counter()
    anchors: set[str] = set()
    for heading in HEADING.findall(markdown):
        base = _github_slug(heading)
        suffix = occurrences[base]
        occurrences[base] += 1
        anchors.add(base if suffix == 0 else f"{base}-{suffix}")
    anchors.update(EXPLICIT_ANCHOR.findall(markdown))
    return anchors


def test_doc_001_internal_markdown_links_and_anchors_resolve():
    """DOC-001: local documentation links and anchors resolve inside the repo."""

    failures: list[str] = []
    for source in sorted(DOCS_ROOT.rglob("*.md")):
        markdown = source.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(markdown):
            target = unquote(raw_target.strip().split(maxsplit=1)[0].strip("<>"))
            if target.startswith(("http://", "https://", "mailto:")):
                continue

            relative_path, separator, fragment = target.partition("#")
            destination = source if not relative_path else source.parent / relative_path
            resolved = destination.resolve()
            if not resolved.is_relative_to(REPOSITORY_ROOT):
                failures.append(f"{source}: link escapes repository: {raw_target}")
                continue
            if not resolved.is_file():
                failures.append(f"{source}: missing link target: {raw_target}")
                continue
            if separator and fragment:
                destination_anchors = _anchors(resolved.read_text(encoding="utf-8"))
                if fragment not in destination_anchors:
                    failures.append(
                        f"{source}: missing anchor {fragment!r} in {resolved}"
                    )

    assert not failures, "\n".join(failures)
