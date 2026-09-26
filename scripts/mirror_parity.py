#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import claims_audit  # noqa: E402


def cmd_check(_args):
    checks = [
        ("bundle_parity", claims_audit.check_bundle_parity),
        ("plugin_parity", claims_audit.check_plugin_sync),
        ("skill_pair_parity", claims_audit.check_skill_pair_parity),
        ("host_rule_sync_parity", claims_audit.check_host_rule_sync),
    ]
    rows = []
    ok = True
    for name, fn in checks:
        passed, detail = fn()
        rows.append({"name": name, "ok": bool(passed), "detail": detail})
        ok = ok and bool(passed)
    print(json.dumps({"ok": ok, "checks": rows}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def cmd_selftest(_args):
    print("selftest: PASS mirror-parity cli loaded")
    return 0


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    if not argv or argv[0] not in {"check", "selftest"}:
        print("unknown command '%s'. choices: check selftest" % (argv[0] if argv else ""))
        return 2
    if argv[0] == "check":
        return cmd_check(argv[1:])
    return cmd_selftest(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
