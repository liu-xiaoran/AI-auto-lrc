"""Print a reviewed candidate for the canonical LegacyV1 feature oracle.

This command deliberately never writes the checked-in manifest. A maintainer
must review its provenance and copy it with the repository's normal patch flow.
"""

from __future__ import annotations

import json

from legacy_v1_feature_case import build_candidate


def main() -> None:
    candidates = [build_candidate() for _ in range(3)]
    if candidates[1:] != candidates[:-1]:
        raise RuntimeError("three consecutive canonical feature runs were not identical")
    print(json.dumps(candidates[0], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
