"""Print, but never install, a canonical LegacyV1 numeric candidate."""

from __future__ import annotations

import json

from legacy_v1_numeric_case import build_numeric_candidate


def main() -> None:
    candidates = [build_numeric_candidate() for _ in range(3)]
    if candidates[1:] != candidates[:-1]:
        raise RuntimeError("three consecutive canonical numeric runs were not identical")
    print(json.dumps(candidates[0], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
