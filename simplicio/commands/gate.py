"""
gate — N-Nest corrective gate.

Absorbed from Asolaria's N-Nest corrective gate (Jesse/crypto-gate).
An agent at an address has a *truth* (the real system state) and a
*reported* value (what it claims — may be confabulated). A watcher
independently reads the agent's address and returns *watcherTruth*.

    gate_ok = reported == watcherTruth   #  is the agent honest?

Usage:

    simplicio-py gate check <reported> <watcher>   →  check a single pair
    simplicio-py gate verify <tree_json>            →  walk a tree of agents
    simplicio-py gate tamper <addr>                 →  inject a confabulation
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Core gate primitives (absorbed from Asolaria/N-Nest)
# ---------------------------------------------------------------------------

def sha16(s: str) -> str:
    """16-char hex digest mimicking the original JS `sha16`."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def agent_pid(addr: str) -> str:
    """Deterministic agent process ID derived from address."""
    return sha16(addr)


def watcher_pid(addr: str) -> str:
    """Deterministic watcher process ID derived from address + watch salt."""
    return sha16(addr + "|watch")


def truth(addr: str) -> str:
    """Return the *truth* for an address — the real system state.

    In production this would query the actual system; for this CLI we
    derive it deterministically from the address so the gate is
    reproducible.
    """
    return sha16("truth:" + addr)


def gate_ok(reported: str, watcher_truth: str) -> bool:
    """Check whether an agent's reported value matches the watcher truth.

    This is the core N-Nest corrective gate invariant:
        gate_ok = reported === watcherTruth
    """
    return reported == watcher_truth


# ---------------------------------------------------------------------------
# Tree verification
# ---------------------------------------------------------------------------

def make_agent(addr: str, *, confabulate: bool = False) -> dict[str, Any]:
    """Construct an N-Nest agent node.

    Parameters
    ----------
    addr : str
        Unique address of this agent (e.g. ``"node-a"``, ``"agent/42"``).
    confabulate : bool
        If True, the *reported* value is deliberately corrupted so that
        ``gate_ok`` fails — useful for testing tamper detection.

    Returns
    -------
    dict
        A serialisable agent node with keys ``addr``, ``agentPid``,
        ``watcherPid``, ``truth``, ``reported``, ``watcherTruth``,
        and ``gate_ok``.
    """
    real = truth(addr)
    if confabulate:
        # Invert the real truth to simulate a confabulation
        reported = sha16("confab:" + addr)
    else:
        reported = real
    w_truth = truth(addr)
    ok = gate_ok(reported, w_truth)
    return {
        "addr": addr,
        "agentPid": agent_pid(addr),
        "watcherPid": watcher_pid(addr),
        "truth": real,
        "reported": reported,
        "watcherTruth": w_truth,
        "gate_ok": ok,
    }


def verify_tree(tree: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    """Walk a tree of agent nodes and verify every gate.

    Accepts either a single agent dict or a list (flat or nested under a
    ``"nodes"`` key).  Returns a summary with total / passed / failed
    counts and per-node details.
    """
    nodes: list[dict[str, Any]] = []

    def _collect(n: Any) -> None:
        if isinstance(n, dict):
            if "addr" in n:
                nodes.append(n)
            for v in n.values():
                _collect(v)
        elif isinstance(n, list):
            for item in n:
                _collect(item)

    _collect(tree)

    results = []
    passed = 0
    failed = 0
    for node in nodes:
        addr = node.get("addr", "<unknown>")
        reported = node.get("reported", "")
        w_truth = node.get("watcherTruth", "")
        ok = gate_ok(reported, w_truth)
        if ok:
            passed += 1
        else:
            failed += 1
        results.append(
            {
                "addr": addr,
                "agentPid": node.get("agentPid", agent_pid(addr)),
                "reported": reported,
                "watcherTruth": w_truth,
                "gate_ok": ok,
            }
        )

    return {
        "total": len(nodes),
        "passed": passed,
        "failed": failed,
        "all_pass": failed == 0,
        "nodes": results,
    }


# ---------------------------------------------------------------------------
# Tamper injection (testing helper)
# ---------------------------------------------------------------------------

def _random_addr() -> str:
    return f"agent/{random.randint(1000, 9999)}"


def tamper(addr: str | None = None) -> dict[str, Any]:
    """Inject a confabulated agent for testing tamper detection.

    Returns the agent node with ``gate_ok=False`` so the caller can see
    how a corrective gate catches the lie.
    """
    addr = addr or _random_addr()
    agent = make_agent(addr, confabulate=True)
    assert not agent["gate_ok"], "tampered agent should fail gate_ok"
    return agent


# ---------------------------------------------------------------------------
# CLI handler
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Entry point for ``simplicio-py gate ...``."""
    import argparse

    ap = argparse.ArgumentParser(
        prog="simplicio-py gate",
        description="N-Nest corrective gate — verify agent honesty in a tree.",
    )
    sub = ap.add_subparsers(dest="gate_cmd", required=True)

    # -- gate check --
    p_check = sub.add_parser(
        "check",
        help="check if gate_ok between a reported value and a watcher truth",
    )
    p_check.add_argument("reported", help="value reported by the agent")
    p_check.add_argument("watcher", help="truth observed by the watcher")
    p_check.add_argument("--json", action="store_true", help="emit JSON output")

    # -- gate verify --
    p_verify = sub.add_parser(
        "verify",
        help="verify all gates in an agent tree (JSON file or stdin)",
    )
    p_verify.add_argument(
        "tree",
        nargs="?",
        default="-",
        help="path to agent tree JSON, or '-' for stdin",
    )
    p_verify.add_argument("--json", action="store_true", help="emit JSON output")

    # -- gate tamper --
    p_tamper = sub.add_parser(
        "tamper",
        help="inject a confabulated agent for testing (gate_ok=False)",
    )
    p_tamper.add_argument(
        "addr",
        nargs="?",
        default=None,
        help="address to confabulate (random if omitted)",
    )
    p_tamper.add_argument("--json", action="store_true", help="emit JSON output")

    args = ap.parse_args(argv)

    if args.gate_cmd == "check":
        ok = gate_ok(args.reported, args.watcher)
        if args.json:
            print(
                json.dumps(
                    {
                        "reported": args.reported,
                        "watcherTruth": args.watcher,
                        "gate_ok": ok,
                    },
                    sort_keys=True,
                )
            )
        else:
            status = "PASS" if ok else "FAIL"
            print(f"GATE {status}: reported={args.reported!r} vs watcher={args.watcher!r}")
        return 0 if ok else 1

    elif args.gate_cmd == "verify":
        if args.tree == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(args.tree).read_text(encoding="utf-8")
        try:
            tree_data = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"gate verify: invalid JSON — {exc}", file=sys.stderr)
            return 2
        result = verify_tree(tree_data)
        if args.json:
            print(json.dumps(result, sort_keys=True, indent=2))
        else:
            status = "ALL PASS" if result["all_pass"] else f"{result['failed']} FAILED"
            print(
                f"GATE VERIFY: {status}  "
                f"({result['passed']}/{result['total']} gates passed)"
            )
            for node in result["nodes"]:
                if not node["gate_ok"]:
                    print(
                        f"  FAIL {node['addr']}: "
                        f"reported={node['reported']!r} "
                        f"watcherTruth={node['watcherTruth']!r}",
                        file=sys.stderr,
                    )
        return 0 if result["all_pass"] else 1

    elif args.gate_cmd == "tamper":
        agent = tamper(args.addr)
        if args.json:
            print(json.dumps(agent, sort_keys=True, indent=2))
        else:
            print(
                f"confabulated agent at {agent['addr']!r}\n"
                f"  agentPid    {agent['agentPid']}\n"
                f"  watcherPid  {agent['watcherPid']}\n"
                f"  truth       {agent['truth']}\n"
                f"  reported    {agent['reported']}\n"
                f"  watcherTruth {agent['watcherTruth']}\n"
                f"  gate_ok     {agent['gate_ok']}  <── tamper detected"
            )
        return 0

    return 0
