"""N-Nest: nested-agent tree with gate verification (Asolaria-inspired).

Builds a perfect B-ary tree of depth N where each node reports a hash that
depends on its children's reports.  Tampering at any node is detected by the
gate at that node (reported != true_val), which propagates up as subtree_ok.

Reference JS original (Asolaria / Jesse):

    function build(tamperAddr) {
      function node(addr, depth) {
        let kids = [], trueVal;
        if (depth === N) { trueVal = truth(addr); }
        else { for (let i = 0; i < B; i++) kids.push(node(addr + '.' + i, depth + 1));
               trueVal = sha16(addr + '|' + kids.map(k => k.reported).join(',')); }
        const reported = (addr === tamperAddr) ? sha16(trueVal + '|CONFABULATED') : trueVal;
        const gate_ok = reported === trueVal;
        const subtree_ok = gate_ok && kids.every(k => k.subtree_ok);
        return { addr, reported, gate_ok, subtree_ok };
      }
      return node('R', 0);
    }
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def sha16(text: str) -> str:
    """SHA-256 truncated to the first 16 hex characters (8 bytes)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def truth(addr: str) -> str:
    """Deterministic ground-truth value for a leaf node address."""
    return sha16(f"truth:{addr}")


# ---------------------------------------------------------------------------
# Tree construction
# ---------------------------------------------------------------------------


def build_tree(
    branching: int,
    depth: int,
    tamper_addr: str | None = None,
) -> dict:
    """Build a complete B-ary N-Nest tree, optionally with a tamper point."""

    def _node(addr: str, d: int) -> dict:
        children: list[dict] = []

        if d == depth:
            true_val = truth(addr)
        else:
            for i in range(branching):
                children.append(_node(f"{addr}.{i}", d + 1))
            true_val = sha16(f"{addr}|{','.join(c['reported'] for c in children)}")

        if addr == tamper_addr:
            reported = sha16(f"{true_val}|CONFABULATED")
        else:
            reported = true_val

        gate_ok = reported == true_val
        subtree_ok = gate_ok and all(c["subtree_ok"] for c in children)

        return {
            "addr": addr,
            "true_val": true_val,
            "reported": reported,
            "gate_ok": gate_ok,
            "subtree_ok": subtree_ok,
            "children": children,
        }

    root = _node("R", 0)
    return {
        "branching": branching,
        "depth": depth,
        "tamper_addr": tamper_addr,
        "root": root,
    }


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def walk_nodes(node: dict) -> list[dict]:
    """Yield every node in the tree as a flat list (pre-order)."""
    result = [
        {
            "addr": node["addr"],
            "true_val": node["true_val"],
            "reported": node["reported"],
            "gate_ok": node["gate_ok"],
            "subtree_ok": node["subtree_ok"],
        }
    ]
    for child in node["children"]:
        result.extend(walk_nodes(child))
    return result


def verify_tree(tree: dict) -> dict:
    """Walk the tree and report gate / subtree integrity for every node."""
    nodes = walk_nodes(tree["root"])
    all_gate = all(n["gate_ok"] for n in nodes)
    all_subtree = all(n["subtree_ok"] for n in nodes)
    failed_gates = [n for n in nodes if not n["gate_ok"]]
    failed_subtree = [n for n in nodes if not n["subtree_ok"]]
    return {
        "total_nodes": len(nodes),
        "all_gate_ok": all_gate,
        "all_subtree_ok": all_subtree,
        "failed_gates": failed_gates,
        "failed_subtree": failed_subtree,
        "nodes": nodes,
    }


# ---------------------------------------------------------------------------
# CLI handlers
# ---------------------------------------------------------------------------

CLI_PROG = "simplicio"


def cmd_build(argv: list[str]) -> int:
    """simplicio nest build <branching> <depth> [--tamper <addr>] [--json]"""
    import argparse

    ap = argparse.ArgumentParser(prog=f"{CLI_PROG} nest build")
    ap.add_argument("branching", type=int, help="branching factor (B)")
    ap.add_argument("depth", type=int, help="tree depth (N)")
    ap.add_argument("--tamper", default=None, help="address to tamper at")
    ap.add_argument("--json", action="store_true", help="JSON output")
    a = ap.parse_args(argv)

    if a.branching < 2:
        print("branching must be >= 2", file=sys.stderr)
        return 2
    if a.depth < 1:
        print("depth must be >= 1", file=sys.stderr)
        return 2

    tree = build_tree(a.branching, a.depth, tamper_addr=a.tamper)
    result = verify_tree(tree)

    if a.json:
        payload = {**tree, "verification": result}
        print(json.dumps(payload, sort_keys=True))
    else:
        status = "INTACT" if result["all_gate_ok"] else "TAMPERED"
        print(
            f"N-Nest  B={a.branching}  N={a.depth}  "
            f"nodes={result['total_nodes']}  "
            f"gate_ok={result['all_gate_ok']}  "
            f"subtree_ok={result['all_subtree_ok']}  "
            f"=> {status}"
        )
        if a.tamper:
            print(f"tamper addr: {a.tamper}")
        for fail in result["failed_gates"]:
            print(
                f"  GATE FAIL  addr={fail['addr']}  true={fail['true_val']}  reported={fail['reported']}",
                file=sys.stderr,
            )
    return 0 if result["all_gate_ok"] else 1


def cmd_verify(argv: list[str]) -> int:
    """simplicio nest verify <tree.json> [--json]"""
    import argparse

    ap = argparse.ArgumentParser(prog=f"{CLI_PROG} nest verify")
    ap.add_argument("path", help="path to tree JSON file (or - for stdin)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    a = ap.parse_args(argv)

    try:
        raw = sys.stdin.read() if a.path == "-" else Path(a.path).read_text(encoding="utf-8")
        tree = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"{CLI_PROG} nest verify: {exc}", file=sys.stderr)
        return 2

    result = verify_tree(tree)

    if a.json:
        print(json.dumps(result, sort_keys=True))
    else:
        status = "INTACT" if result["all_gate_ok"] else "TAMPERED"
        print(
            f"nodes={result['total_nodes']}  "
            f"gate_ok={result['all_gate_ok']}  "
            f"subtree_ok={result['all_subtree_ok']}  "
            f"=> {status}"
        )
        for fail in result["failed_gates"]:
            print(
                f"  GATE FAIL  addr={fail['addr']}  true={fail['true_val']}  reported={fail['reported']}",
                file=sys.stderr,
            )
    return 0 if result["all_gate_ok"] else 1


def cmd_tamper(argv: list[str]) -> int:
    """simplicio nest tamper <branching> <depth> <addr> [--json]

    Build a tree at (B, N) with a tamper point at <addr> and immediately
    verify — demonstrating that the gate catches the confabulation.
    """
    import argparse

    ap = argparse.ArgumentParser(prog=f"{CLI_PROG} nest tamper")
    ap.add_argument("branching", type=int, help="branching factor (B)")
    ap.add_argument("depth", type=int, help="tree depth (N)")
    ap.add_argument("addr", help="address to tamper (e.g. R.0.1)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    a = ap.parse_args(argv)

    if a.branching < 2:
        print("branching must be >= 2", file=sys.stderr)
        return 2
    if a.depth < 1:
        print("depth must be >= 1", file=sys.stderr)
        return 2

    tree = build_tree(a.branching, a.depth, tamper_addr=a.addr)
    result = verify_tree(tree)

    if a.json:
        payload = {**tree, "verification": result}
        print(json.dumps(payload, sort_keys=True))
    else:
        status = "INTACT" if result["all_gate_ok"] else "TAMPERED"
        print(
            f"N-Nest  B={a.branching}  N={a.depth}  "
            f"tamper={a.addr}  "
            f"nodes={result['total_nodes']}  "
            f"gate_ok={result['all_gate_ok']}  "
            f"subtree_ok={result['all_subtree_ok']}  "
            f"=> {status}"
        )
        for fail in result["failed_gates"]:
            print(
                f"  GATE FAIL  addr={fail['addr']}  "
                f"true={fail['true_val'][:12]}...  "
                f"reported={fail['reported'][:12]}...",
                file=sys.stderr,
            )
        # Also show which nodes had their subtree compromised (propagated)
        for fail in result["failed_subtree"]:
            if fail["gate_ok"]:
                print(
                    f"  SUBTREE FAIL (propagated)  addr={fail['addr']}",
                    file=sys.stderr,
                )
    return 0 if result["all_gate_ok"] else 1


def main(argv: list[str]) -> int:
    """Dispatch nest subcommands."""
    import argparse

    ap = argparse.ArgumentParser(prog=f"{CLI_PROG} nest")
    sub = ap.add_subparsers(dest="nest_cmd", required=True)

    sub.add_parser(
        "build",
        help="build a perfect B-ary N-Nest tree (optionally with --tamper)",
    )
    sub.add_parser(
        "verify",
        help="load a tree JSON and verify every node's gate",
    )
    sub.add_parser(
        "tamper",
        help="build + tamper at a given address and verify gate catches it",
    )

    a = ap.parse_args(argv[:1])  # only consume the subcommand name
    rest = argv[1:]

    if a.nest_cmd == "build":
        return cmd_build(rest)
    elif a.nest_cmd == "verify":
        return cmd_verify(rest)
    elif a.nest_cmd == "tamper":
        return cmd_tamper(rest)
    else:
        ap.print_help()
        return 2
