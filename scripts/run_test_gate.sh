#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
layer="${1:-portable}"
base_ref="${2:-${AI_AUTO_LRC_DIFF_BASE_REF:-HEAD}}"
artifact_root="${AI_AUTO_LRC_GATE_ARTIFACT_DIR:-}"

verify_gate() {
  if [[ "${AI_AUTO_LRC_EVIDENCE_RUN_ID+x}" == x ]]; then
    uv run --frozen --no-sync python scripts/verify_quality_gates.py \
      "$@" --run-id "$AI_AUTO_LRC_EVIDENCE_RUN_ID"
  else
    uv run --frozen --no-sync python scripts/verify_quality_gates.py "$@"
  fi
}

if [[ -z "$artifact_root" ]]; then
  artifact_root="$(mktemp -d "${TMPDIR:-/tmp}/ai-auto-lrc-gate.XXXXXX")"
fi
mkdir -p "$artifact_root"
artifact_root="$(cd "$artifact_root" && pwd)"
cd "$repo_root"

case "$layer" in
  portable)
    uv run --frozen --no-sync python -m pytest \
      tests/unit tests/contract tests/component \
      -q -p no:cacheprovider \
      --junitxml="$artifact_root/portable.xml" \
      --cov=t2l \
      --cov-branch \
      --cov-report="json:$artifact_root/coverage.json" \
      --cov-report=term-missing \
      --cov-fail-under=80
    verify_gate junit \
      --layer portable \
      --junit-xml "$artifact_root/portable.xml" \
      --output "$artifact_root/portable-gate.json"
    verify_gate coverage \
      --base-ref "$base_ref" \
      --coverage-json "$artifact_root/coverage.json" \
      --output "$artifact_root/coverage-gate.json"
    ;;
  package)
    package_scope="${AI_AUTO_LRC_PACKAGE_SCOPE:-}"
    package_keyword=""
    case "$package_scope" in
      "") ;;
      linux-x86_64)
        package_keyword="not test_pkg_013_pkg_014_pkg_015_cold_offline_sdist_build and not test_pkg_012_pkg_017_macos_cold_install_and_tags"
        ;;
      macos-arm64) package_keyword="not test_pkg_019_linux_cold_install" ;;
      *)
        echo "AI_AUTO_LRC_PACKAGE_SCOPE must be linux-x86_64 or macos-arm64" >&2
        exit 2
        ;;
    esac
    if [[ -n "$package_keyword" ]]; then
      uv run --frozen --no-sync python -m pytest \
        tests/package -m package -k "$package_keyword" \
        -q -p no:cacheprovider \
        --junitxml="$artifact_root/package.xml"
    else
      uv run --frozen --no-sync python -m pytest \
        tests/package -m package \
        -q -p no:cacheprovider \
        --junitxml="$artifact_root/package.xml"
    fi
    verify_gate junit \
      --layer package \
      --junit-xml "$artifact_root/package.xml" \
      --output "$artifact_root/package-gate.json"
    if [[ "${AI_AUTO_LRC_EVIDENCE_RUN_ID+x}" == x ]]; then
      if [[ "$package_scope" != "linux-x86_64" ]]; then
        echo "capture-bound package evidence currently requires linux-x86_64 scope" >&2
        exit 70
      fi
      if [[ -z "${AI_AUTO_LRC_WHEELHOUSE:-}" ]]; then
        echo "AI_AUTO_LRC_WHEELHOUSE is required for package evidence" >&2
        exit 70
      fi
      if [[ -z "${AI_AUTO_LRC_PACKAGE_IMAGE:-}" ]]; then
        echo "AI_AUTO_LRC_PACKAGE_IMAGE must be an immutable repo digest" >&2
        exit 70
      fi
      uv run --frozen --no-sync python scripts/run_linux_package_gate.py \
        --wheelhouse "$AI_AUTO_LRC_WHEELHOUSE" \
        --artifact-root "$artifact_root" \
        --run-id "$AI_AUTO_LRC_EVIDENCE_RUN_ID" \
        --image "$AI_AUTO_LRC_PACKAGE_IMAGE"
    fi
    ;;
  canonical)
    if [[ "${AI_AUTO_LRC_EVIDENCE_RUN_ID+x}" == x && \
      -z "${AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256:-}" ]]; then
      echo "AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256 is required for capture-bound canonical evidence" >&2
      exit 70
    fi
    AI_AUTO_LRC_CANONICAL_EVIDENCE_DIR="$artifact_root" \
      scripts/run_canonical_legacy_v1_golden.sh verify
    verify_gate junit \
      --layer canonical \
      --junit-xml "$artifact_root/canonical.xml" \
      --output "$artifact_root/canonical-gate.json"
    ;;
  *)
    echo "usage: $0 [portable [base-ref]|package|canonical]" >&2
    exit 2
    ;;
esac

echo "quality gate evidence: $artifact_root"
