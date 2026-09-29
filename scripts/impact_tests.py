#!/usr/bin/env python3
"""Select the tests a change can affect: symbol-level impact against a base ref.

For every changed Python module it compares the base and the working-tree AST and keeps only the
top-level functions, classes and assignments whose source changed (a new module counts whole). A
test file is selected when it reaches one of those symbols through its module (a bare import or
name, `module.symbol`, an import alias, or a dotted string), when it runs a changed file by path
(a black box, so any change to that file counts), or when it names a changed non-Python file (for
example SKILL.md). Changed test files are always selected, and a changed conftest.py reaches the
tests below it (by fixture name; an autouse fixture or a pytest_ hook reaches all of them).
Generated mirrors (plugin/, simplicio_loop/_bundle/) are left to the parity checks.

    python3 scripts/impact_tests.py [--base origin/main] [--json]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # scripts/ lives at the repo root
MIRRORS = ("plugin/", "simplicio_loop/_bundle/")
RUN_OUTPUT = ("bench/llm_ab/results/",)  # benchmark output, not code
TEST_DIRS = ("tests", "packages/mapper/tests", "packages/dev-cli/tests")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout


def changed_files(base: str) -> list[str]:
    tracked = _git("diff", "--name-only", base).split()
    untracked = [p for p in _git("ls-files", "--others", "--exclude-standard").split()
                 if not any(part.startswith(".") for part in Path(p).parts[:-1]) and not p.startswith(RUN_OUTPUT)]
    return sorted({p for p in tracked + untracked if not p.startswith(MIRRORS)})


def _top_level(source: str) -> dict[str, str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out = {}
    for node in tree.body:
        names = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
        for name in names:
            out[name] = ast.get_source_segment(source, node) or ""
    return out


def changed_symbols(path: str, base: str) -> set[str]:
    new = (ROOT / path).read_text(encoding="utf-8", errors="replace") if (ROOT / path).is_file() else ""
    old = _git("show", f"{base}:{path}")
    if not old:  # new module: every symbol is new, and its module name is the key
        return set(_top_level(new)) | {Path(path).stem}
    before, after = _top_level(old), _top_level(new)
    return {name for name in set(before) | set(after) if before.get(name) != after.get(name)}


def _module_pattern(path: str) -> re.Pattern:
    """How a test reaches a module: `import stem`, `from x import stem`, `stem.attr`, or a path `dir/stem`.

    A bare word is not enough (tests say "check" or "run" in prose all the time).
    """
    p = Path(path)
    stem = re.escape(p.stem)
    parent = re.escape(p.parent.name)
    return re.compile(
        rf"(?:\bimport\s+(?:[\w.]+\.)?{stem}\b|\bimport\s+[^\n]*\b{stem}\b|\b{stem}\."
        rf"|{parent}/{stem}\b|{parent}\.{stem}\b)"
    )


_BARE = re.compile(r"(?<![\w.])[A-Za-z_]\w*")  # names used on their own (imports, calls, fixtures)
_ATTR = re.compile(r"(?<=\.)[A-Za-z_]\w*")  # names used after a dot (`module.symbol`, dotted strings)


class _Module:
    """A changed Python module: which of its symbols changed and how a test file reaches it."""

    def __init__(self, path: str, symbols: set[str]) -> None:
        stem, parent = re.escape(Path(path).stem), re.escape(Path(path).parent.name)
        self.stem = Path(path).stem
        self.symbols = frozenset(symbols)
        self.reach = _module_pattern(path)
        # A test that runs the file by path (`scripts/x.py`) is a black box: any change to it matters.
        self.by_path = re.compile(rf"{parent}/{stem}\.py|[\"']{stem}\.py[\"']")
        self.alias = re.compile(rf"\bimport\s+(?:[\w.]+\.)?{stem}\s+as\s+(\w+)|\bimport\s+[^\n]*?\b{stem}\s+as\s+(\w+)")

    def reached_by(self, text: str, bare: set[str], attr: set[str]) -> bool:
        if self.by_path.search(text):
            return True
        named = self.symbols & (bare | attr)
        if not named or not self.reach.search(text):
            return False
        if named & bare:
            return True
        holders = {self.stem}
        for match in self.alias.finditer(text):
            holders.update(group for group in match.groups() if group)
        holder = "|".join(re.escape(name) for name in sorted(holders))
        return any(re.search(rf"\b(?:{holder})\.{re.escape(symbol)}\b", text) for symbol in named & attr)


def _conftest_rule(path: str, symbols: set[str]) -> tuple[Path, frozenset[str], bool]:
    """A changed conftest.py: its fixtures reach tests by name; an autouse fixture or hook reaches every test below it."""
    try:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        tree = ast.Module(body=[], type_ignores=[])
    everywhere = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in symbols
        and (node.name.startswith("pytest_") or "autouse=True" in "".join(ast.unparse(d) for d in node.decorator_list))
        for node in tree.body
    )
    return (ROOT / path).parent, frozenset(symbols), everywhere


def impacted_tests(base: str) -> tuple[list[str], dict[str, list[str]]]:
    """A test is impacted when it reaches a changed symbol through its module, runs a changed file by path,
    names a changed non-Python file, or is itself changed. A changed conftest.py reaches the tests below it."""
    keys: dict[str, list[str]] = {}
    selected: set[str] = set()
    modules: list[_Module] = []
    conftests: list[tuple[Path, frozenset[str], bool]] = []
    file_names: list[str] = []
    for path in changed_files(base):
        name = Path(path).name
        if path.startswith(TEST_DIRS) and name.startswith("test_") and path.endswith(".py"):
            if (ROOT / path).is_file():
                selected.add(path)
        elif path.endswith(".py"):
            symbols = changed_symbols(path, base)
            for symbol in symbols:
                keys.setdefault(symbol, []).append(path)
            if path.startswith(TEST_DIRS) and name == "conftest.py":
                conftests.append(_conftest_rule(path, symbols))
            else:
                modules.append(_Module(path, symbols))
        else:
            keys.setdefault(name, []).append(path)
            file_names.append(name)
    named_file = re.compile(
        r"(?<![\w.-])(?:" + "|".join(re.escape(n) for n in sorted(set(file_names), key=len, reverse=True)) + r")(?![\w-])"
    ) if file_names else None
    for directory in TEST_DIRS:
        for test in sorted((ROOT / directory).rglob("test_*.py")):
            text = test.read_text(encoding="utf-8", errors="replace")
            bare, attr = set(_BARE.findall(text)), set(_ATTR.findall(text))
            if (
                any(module.reached_by(text, bare, attr) for module in modules)
                or (named_file is not None and named_file.search(text))
                or any(test.is_relative_to(root) and (everywhere or symbols & bare) for root, symbols, everywhere in conftests)
            ):
                selected.add(str(test.relative_to(ROOT)))
    return sorted(selected), keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main", help="git ref to diff against (default: origin/main)")
    parser.add_argument("--json", action="store_true", help="print the tests and the changed symbols as JSON")
    parser.add_argument("--root", help="repository root (default: the parent of scripts/)")
    args = parser.parse_args(argv)
    if args.root:
        global ROOT
        ROOT = Path(args.root).resolve()
    tests, keys = impacted_tests(args.base)
    if args.json:
        print(json.dumps({"tests": tests, "symbols": keys}, indent=1))
    else:
        print("\n".join(tests))
    return 0


if __name__ == "__main__":
    sys.exit(main())
