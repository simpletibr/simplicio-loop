"""Rewrite simplicio_loop/setup_pins.json from the latest gh and uv releases (#1657). Maintainer step; needs network.

Each archive's SHA256 is kept only when the release's own checksums publish the same digest. Before committing the file,
check the provenance of each archive: `gh attestation verify <archive> --repo cli/cli` (gh 2.50 or newer) and the same
for `--repo astral-sh/uv`. The pin is then a reviewed change of its own.
"""
from __future__ import annotations

import json
import sys

from simplicio_loop import release_fetch, setup_pins


def main() -> int:
    try:
        doc = setup_pins.build(release_fetch.default_get)
    except (setup_pins.PinError, release_fetch.FetchError) as exc:
        print(f"no pins written: {exc}", file=sys.stderr)
        return 1
    setup_pins.PINS_PATH.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {setup_pins.PINS_PATH}: gh {doc['gh']['tag']}, uv {doc['uv']['tag']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
