"""``simplicio-py smoke`` — one proof call: connect+generate.

Extracted from `cli.py`'s `main()` body (issue #103); behavior unchanged.
"""

from __future__ import annotations

import argparse
import json


def run(a: argparse.Namespace) -> int:
    from ..providers import generate, info
    from ..runtime_contracts import smoke_contract

    provider = info()
    out = generate("Reply exactly: OK simplicio connected.")
    if a.json:
        print(json.dumps(smoke_contract(provider=provider, reply=out, root=a.root), sort_keys=True))
    else:
        print("provider:", provider)
        print("model reply:", out.strip()[:200])
    return 0
