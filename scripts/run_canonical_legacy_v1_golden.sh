#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image_name="ai-auto-lrc-legacy-v1-golden:cpython310-linux-x86_64"
mode="${1:-verify}"
evidence_dir="${AI_AUTO_LRC_CANONICAL_EVIDENCE_DIR:-}"

if [[ "$mode" == "verify" && "${AI_AUTO_LRC_EVIDENCE_RUN_ID+x}" == x ]]; then
  if [[ -z "$evidence_dir" ]]; then
    echo "AI_AUTO_LRC_CANONICAL_EVIDENCE_DIR is required for capture-bound canonical evidence" >&2
    exit 70
  fi
  if [[ -z "${AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256:-}" ]]; then
    echo "AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256 is required for capture-bound canonical evidence" >&2
    exit 70
  fi
  mkdir -p "$evidence_dir"
  evidence_dir="$(cd "$evidence_dir" && pwd)"
  cd "$repo_root"
  exec uv run --frozen --no-sync python scripts/run_canonical_gate.py \
    --artifact-root "$evidence_dir" \
    --run-id "$AI_AUTO_LRC_EVIDENCE_RUN_ID" \
    --source-sha256 "$AI_AUTO_LRC_EVIDENCE_SOURCE_SHA256" \
    --repo-root "$repo_root"
fi

docker_args=(
  --rm
  --platform linux/amd64
  --network none
  --read-only
  --tmpfs /tmp:rw,noexec,nosuid,size=64m
  --mount "type=bind,source=$repo_root/checkpoints,target=/workspace/checkpoints,readonly"
)

case "$mode" in
  verify)
    container_args=(
      -m pytest
      tests/golden/test_legacy_v1_feature_golden.py
      tests/golden/test_legacy_v1_numeric_golden.py
      tests/golden/test_legacy_v1_public_e2e_golden.py
      -q -p no:cacheprovider
    )
    if [[ -n "$evidence_dir" ]]; then
      mkdir -p "$evidence_dir"
      evidence_dir="$(cd "$evidence_dir" && pwd)"
      container_args+=(--junitxml=/evidence/canonical.xml)
      docker_args+=(
        --mount "type=bind,source=$evidence_dir,target=/evidence"
      )
    fi
    ;;
  candidate)
    container_args=(tests/golden/generate_legacy_v1_feature_golden.py)
    ;;
  numeric-candidate)
    container_args=(tests/golden/generate_legacy_v1_numeric_golden.py)
    ;;
  public-e2e-candidate)
    container_args=(tests/golden/generate_legacy_v1_public_e2e_golden.py)
    ;;
  *)
    echo "usage: $0 [verify|candidate|numeric-candidate|public-e2e-candidate]" >&2
    exit 2
    ;;
esac

docker build \
  --platform linux/amd64 \
  --file "$repo_root/tests/golden/Dockerfile.canonical" \
  --tag "$image_name" \
  "$repo_root"

docker run "${docker_args[@]}" "$image_name" "${container_args[@]}"
