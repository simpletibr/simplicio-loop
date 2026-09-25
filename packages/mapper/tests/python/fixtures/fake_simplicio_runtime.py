#!/usr/bin/env python3
"""Fake `simplicio` runtime binary used by tests/python/test_native_ask_delegation.py
(issue #174).

The real `simplicio` runtime binary (Rust, `simplicio-runtime`) is not
present in this container/CI environment, so the native-delegation tests for
`ask impact`/`ask tests-for` exercise a REAL subprocess (not a mocked
`subprocess.run`) against this fake, controllable stand-in -- genuine
argv-parsing and stdout/JSON-envelope round-tripping through
`simplicio_mapper.query._runtime_ask_query`, same as production would do
against the real binary.

Behavior is controlled by the `FAKE_SIMPLICIO_MODE` environment variable:

  - "ok" (default)   -- print a valid `simplicio.ask/v1` envelope, exit 0.
  - "bad-schema"      -- print JSON missing the `schema` field, exit 0.
  - "bad-json"        -- print invalid JSON, exit 0.
  - "nonzero"         -- print nothing useful, exit 1.

Only understands the identity/capability probes plus the subset of argv this
project's `ask impact`/`ask tests-for` native delegation actually sends:
    simplicio --version
    simplicio capabilities list --json
    simplicio ask <verb> --repo <path> --arg <arg> --limit <n> --json
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    mode = os.environ.get("FAKE_SIMPLICIO_MODE", "ok")
    argv = sys.argv[1:]

    if argv == ["--version"]:
        if mode == "agent-homonym":
            sys.stdout.write("Simplicio Agent v0.17.0\n")
        else:
            sys.stdout.write("Simplicio Runtime 0.0.0-test\n")
        return 0
    if argv == ["capabilities", "list", "--json"]:
        sys.stdout.write(
            json.dumps(
                {
                    "schema": "simplicio.capability-list/v1",
                    "items": [{"id": "simplicio-mapper", "status": "available"}],
                }
            )
        )
        return 0

    if mode == "nonzero":
        sys.stderr.write("fake_simplicio_runtime: simulated failure\n")
        return 1
    if mode == "bad-json":
        sys.stdout.write("not-json{")
        return 0

    verb = argv[1] if len(argv) > 1 and argv[0] == "ask" else "unknown"
    arg = None
    if "--arg" in argv:
        arg = argv[argv.index("--arg") + 1]

    if mode == "bad-schema":
        payload = {"results": [], "total": 0}
        sys.stdout.write(json.dumps(payload))
        return 0

    if verb == "impact":
        payload = {
            "schema": "simplicio.ask/v1",
            "version": 1,
            "query": {"verb": "impact", "arg": arg},
            "note": None,
            "results": {
                "affected_symbols": [{"symbol": "fake_symbol", "path": arg}],
                "affected_flows": [],
                "needs_review": [],
            },
            "total": 1,
        }
    elif verb == "tests-for":
        payload = {
            "schema": "simplicio.ask/v1",
            "version": 1,
            "query": {"verb": "tests-for", "arg": arg},
            "note": None,
            "results": ["tests/test_fake.py"],
            "total": 1,
        }
    else:
        payload = {"schema": "simplicio.ask/v1", "version": 1, "results": [], "total": 0}

    sys.stdout.write(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
