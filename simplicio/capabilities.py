"""Cheap, static capability discovery -- the in-process half of ``capabilities``.

``simplicio-dev-cli capabilities --json`` (see ``simplicio/cli.py``'s fast
path) and this module's :func:`load_capabilities_manifest` read the exact
same packaged JSON (``simplicio/data/capabilities.json``); a caller that
already runs in the same interpreter (an MCP server, a host loop's Python
process) can call the function directly and skip the subprocess entirely.

Deliberately minimal imports (``json``, ``importlib.resources``) so this
module never pulls in ``simplicio.cli`` or anything import-heavy -- the
whole point is that discovering the command/flag surface must not cost more
than reading one small file, in-process or as a subprocess.

The packaged file is regenerated from the real argparse parser by
``scripts/gen_capabilities_manifest.py``; ``tests/python/
test_capabilities_manifest.py`` fails the build if the two drift apart.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

_ANCHOR_PACKAGE = "simplicio"
_MANIFEST_RELATIVE_PATH = ("data", "capabilities.json")


@lru_cache(maxsize=1)
def load_capabilities_manifest() -> dict[str, Any]:
    """Return the packaged ``simplicio.dev-cli.capabilities/v1`` manifest.

    Cached per-process (the file is static for the life of an install), so a
    caller that reads it many times in one run pays the cost once.
    """
    resource = resources.files(_ANCHOR_PACKAGE)
    for part in _MANIFEST_RELATIVE_PATH:
        resource = resource.joinpath(part)
    return json.loads(resource.read_text(encoding="utf-8"))
