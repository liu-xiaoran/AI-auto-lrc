#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

# Package tests intentionally run outside this process: their isolated installed
# copies share the t2l module name and would corrupt source-tree coverage totals.
# Canonical golden evidence has its own pinned Linux/CPython 3.10 harness.
uv run --frozen --no-sync python -m pytest \
  tests/unit tests/contract tests/component \
  -q -p no:cacheprovider \
  --cov=t2l \
  --cov-report=term-missing \
  --cov-fail-under=80
