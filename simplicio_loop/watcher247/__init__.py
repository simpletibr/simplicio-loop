"""24/7 watcher for simplicio-* repos: intake, plan, apply, verify, open PR, optionally merge.

Stages: intake gate (issues) → plan (exec CLI, default) → apply (dev-cli turbo)
→ verify (tests) → PR (draft/open) → done (merge iff SIMPLICIO_247_AUTO_MERGE=1).
Extension-point registry runs at each stage. Subscription gate guards operation.
Squads supported; workers escalate on failure. The motor único (#1469) is turbo +
watcher's points registry; runner.py is not grafted.
"""
from __future__ import annotations
