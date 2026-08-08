#!/usr/bin/env python3
"""Fail when product code gains a mutation primitive outside the Effect boundary."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

# Reviewed 2026-08-02 at origin/main fbefdd56: the inventory includes the
# controlled checkpoint, transaction, verification, write-set, causal-path,
# native Fast, Mapper-delta, context-cache writer-lock, and MapperStore route
# primitives already merged before this baseline. The changeset refresh
# producer and canonical Mapper operations adapter are explicit external
# boundaries; their subprocess, route initialization, and string normalization
# are not final source mutation. Transaction recovery also owns cleanup of its
# validated candidate/backup directories after a crash-window replay. Issue
# #650 adds the reviewed atomic deterministic-edit receipt and bounded apply
# lock under the repository-local .simplicio/dev-cli-receipts directory. Issue
# #649 changes recovery metadata to argv and adds MapperStore reconciliation receipts.
BASELINE_SHA256 = "5f1b325a49bec6f42a22dc8d2a8c5a0a845da998b24b033d94963f1577ce2a37"
APPROVED_EFFECT_BOUNDARIES = frozenset(
    {
        "simplicio/hbp.py",
        "simplicio/plan_compiler/runtime_effect_sink.py",
    }
)
MUTATING_METHODS = frozenset(
    {
        "chmod",
        "mkdir",
        "rename",
        "replace",
        "rmdir",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    }
)
MUTATING_FUNCTIONS = frozenset(
    {
        "os.remove",
        "os.rename",
        "os.replace",
        "os.unlink",
        "shutil.copy",
        "shutil.copy2",
        "shutil.copytree",
        "shutil.move",
        "shutil.rmtree",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.run",
        "write_bytes_atomic",
        "write_text_atomic",
    }
)
MUTATING_FUNCTION_LEAVES = frozenset({"write_bytes_atomic", "write_text_atomic"})


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _resolve_alias(name: str, aliases: dict[str, str]) -> str:
    head, separator, tail = name.partition(".")
    resolved = aliases.get(head, head)
    return f"{resolved}.{tail}" if separator else resolved


def _scope(parents: list[ast.AST]) -> str:
    names = [
        node.name
        for node in parents
        if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef))
    ]
    return ".".join(names) or "<module>"


def _open_writes(call: ast.Call) -> bool:
    name = _qualified_name(call.func)
    if name not in {"open", "Path.open"} and not name.endswith(".open"):
        return False
    mode: object = None
    if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for keyword in call.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            mode = keyword.value.value
    return isinstance(mode, str) and any(flag in mode for flag in "wax+")


def _inventory_file(path: Path, root: Path) -> Counter[tuple[str, str, str]]:
    relative = path.relative_to(root).as_posix()
    if relative in APPROVED_EFFECT_BOUNDARIES:
        return Counter()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    rows: Counter[tuple[str, str, str]] = Counter()
    parents: list[ast.AST] = []
    aliases: dict[str, str] = {}

    class Visitor(ast.NodeVisitor):
        def generic_visit(self, node: ast.AST) -> None:
            parents.append(node)
            super().generic_visit(node)
            parents.pop()

        def visit_Call(self, node: ast.Call) -> None:
            name = _resolve_alias(_qualified_name(node.func), aliases)
            primitive = ""
            if isinstance(node.func, ast.Attribute) and node.func.attr in MUTATING_METHODS:
                primitive = node.func.attr
            elif name.rsplit(".", 1)[-1] in MUTATING_METHODS:
                primitive = name.rsplit(".", 1)[-1]
            elif name in MUTATING_FUNCTIONS or name.rsplit(".", 1)[-1] in MUTATING_FUNCTION_LEAVES:
                primitive = name.rsplit(".", 1)[-1]
            elif _open_writes(node):
                primitive = "open:write"
            if primitive:
                rows[(relative, _scope(parents), primitive)] += 1
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import) -> None:
            for item in node.names:
                aliases[item.asname or item.name] = item.name

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module:
                for item in node.names:
                    aliases[item.asname or item.name] = f"{node.module}.{item.name}"

        def visit_Assign(self, node: ast.Assign) -> None:
            value = _resolve_alias(_qualified_name(node.value), aliases)
            if value:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        aliases[target.id] = value
            self.generic_visit(node)

    Visitor().visit(tree)
    return rows


def mutation_inventory(root: Path) -> list[dict[str, object]]:
    rows: Counter[tuple[str, str, str]] = Counter()
    for path in sorted((root / "simplicio").rglob("*.py")):
        rows.update(_inventory_file(path, root))
    return [
        {"path": path, "scope": scope, "primitive": primitive, "count": count}
        for (path, scope, primitive), count in sorted(rows.items())
    ]


def inventory_digest(rows: list[dict[str, object]]) -> str:
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--inventory", action="store_true")
    args = parser.parse_args(argv)
    rows = mutation_inventory(Path(args.root).resolve())
    digest = inventory_digest(rows)
    if args.inventory:
        print(json.dumps({"digest": digest, "entries": rows}, indent=2, sort_keys=True))
    if digest != BASELINE_SHA256:
        print(
            "effect-boundary guard failed: mutation inventory changed "
            f"(expected {BASELINE_SHA256}, got {digest})"
        )
        return 1
    print(f"effect-boundary guard passed: {len(rows)} mutation scopes, digest {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
