"""Static dependency-direction contracts for the v2 core."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PREFIXES = (
    "demucs",
    "fasttext",
    "librosa",
    "numpy",
    "t2l.adapters",
    "torch",
    "torchaudio",
)


def _absolute_import(module: str, node: ast.ImportFrom) -> str:
    imported = node.module or ""
    if node.level == 0:
        return imported
    package = module.rsplit(".", 1)[0]
    return importlib.util.resolve_name(f"{'.' * node.level}{imported}", package)


def test_pkg_006_domain_and_application_keep_dependency_direction():
    """PKG-006: domain/application do not import adapters or inference libraries."""

    violations: list[str] = []
    for layer in ("domain", "application"):
        for path in sorted((REPOSITORY_ROOT / "t2l" / layer).glob("*.py")):
            module = ".".join(path.relative_to(REPOSITORY_ROOT).with_suffix("").parts)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported_modules = [_absolute_import(module, node)]
                else:
                    continue
                for imported in imported_modules:
                    if imported.startswith(FORBIDDEN_PREFIXES):
                        relative = path.relative_to(REPOSITORY_ROOT)
                        violations.append(f"{relative}:{node.lineno}: {imported}")

    assert not violations, "forbidden dependency direction:\n" + "\n".join(violations)
