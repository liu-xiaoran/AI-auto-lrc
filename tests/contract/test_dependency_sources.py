"""Dependency-lock and single-source governance for v2 packaging."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPOSITORY_ROOT / "uv.lock"
PYPROJECT_PATH = REPOSITORY_ROOT / "pyproject.toml"


def test_pkg_016_lock_rejects_mutable_sources_and_unhashed_artifacts():
    """PKG-016: the lock has no VCS/direct sources or unhashed artifacts."""

    lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["version"] == 1
    assert lock["requires-python"] == ">=3.10, <3.12"

    for package in lock["package"]:
        source = package["source"]
        if package["name"] == "ai-auto-lrc":
            assert source == {"editable": "."}
        else:
            assert set(source) == {"registry"}, (package["name"], source)
            assert source["registry"] in {
                "https://pypi.org/simple",
                "https://download.pytorch.org/whl/cpu",
            }

        assert package.get("yanked") not in (True, "true", "True"), package["name"]
        artifacts = []
        if "sdist" in package:
            artifacts.append(package["sdist"])
        artifacts.extend(package.get("wheels", ()))
        for artifact in artifacts:
            assert set(artifact) >= {"url", "hash"}, (
                package["name"],
                artifact,
            )
            assert artifact["url"].startswith("https://")
            assert artifact["hash"].startswith("sha256:")
            assert len(artifact["hash"]) == len("sha256:") + 64
            if "size" in artifact:
                assert artifact["size"] > 0


def test_pkg_020_pyproject_and_uv_lock_are_the_only_dependency_inputs():
    """PKG-020: retired dependency files cannot reappear as installation inputs."""

    assert PYPROJECT_PATH.is_file()
    assert LOCK_PATH.is_file()
    for retired in ("requirements.txt", "Pipfile", "Pipfile.lock", "setup.py"):
        assert not (REPOSITORY_ROOT / retired).exists(), retired

    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["project"]["dependencies"]
    assert pyproject["tool"]["uv"]["sources"]

    builder = (
        REPOSITORY_ROOT / "scripts" / "build_offline_wheelhouse.py"
    ).read_text(encoding="utf-8")
    assert '"export"' in builder
    assert '"--frozen"' in builder
    assert '"--emit-index-url"' in builder
    assert '"runtime-requirements.txt"' in builder
    assert "REPOSITORY_ROOT / \"requirements.txt\"" not in builder

    for readme_name in ("README.md", "README_zh.md"):
        readme = (REPOSITORY_ROOT / readme_name).read_text(encoding="utf-8")
        assert "pyproject.toml" in readme
        assert "uv.lock" in readme
        assert "Pipfile" in readme
