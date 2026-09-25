"""``simplicio-py smoke`` — deterministic adapter health check.

The Python adapter deliberately does not call a model or provider. This
command reports that policy without making a network, subprocess, or model
load attempt.
"""

from __future__ import annotations

import argparse
import json


def run(a: argparse.Namespace) -> int:
    from ..runtime_contracts import smoke_contract

    provider = "provider=disabled mode=deterministic-only llm_calls=disabled"
    out = "LLM execution disabled; deterministic-only adapter"
    if a.json:
        print(json.dumps(smoke_contract(provider=provider, reply=out, root=a.root), sort_keys=True))
    else:
        print("provider:", provider)
        print("model reply:", out.strip()[:200])
    return 0
