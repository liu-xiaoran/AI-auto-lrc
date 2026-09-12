"""Print, but never install, a canonical real-decoder public e2e candidate."""

from __future__ import annotations

import json

from legacy_v1_public_e2e_case import build_public_e2e_candidate


def main() -> None:
    candidates = [build_public_e2e_candidate() for _ in range(3)]
    if candidates[1:] != candidates[:-1]:
        raise RuntimeError("three consecutive public e2e runs were not identical")
    print(json.dumps(candidates[0], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
