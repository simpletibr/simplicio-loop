"""Canonical JSON hashing shared by the plan-compiler contracts.

Mirrors the ``_stable_hash`` pattern already used by
:mod:`simplicio.orchestrator.multi_task` (sha256 over sorted-key,
separator-compact JSON) so the same canonical entry always produces a
byte-identical hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_hash(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
