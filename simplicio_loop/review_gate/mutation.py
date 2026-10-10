"""Mutation sample of the review gate (#1649): small deterministic mutants of the production lines a PR added or changed.

The mutants come from the AST, never from the text of a line: a string, a comment or a docstring is never mutated
(they are not nodes the operators below visit), and a mutant that does not compile is dropped. Each mutant is the whole
mutated file (`ast.unparse`), applied to the head tree, run against the PR's tests and restored. A mutant the tests
do not fail on is a survivor; the gate fails when too few mutants die.

An equivalent mutant changes no observable behaviour, so no test can kill it. The only mutants classed as equivalent
(rule `_unreachable`) are the ones no run reaches: after an unconditional return, raise, continue or break in the same
block, or in the branch a literal test never takes (`if False:`, the else of `if True:`). A surviving equivalent leaves
the sample; the sample fails when no live mutant is left or when the equivalents are more than half of it.
"""
from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import isolation
from .diffs import FileChange
from .model import ERROR, FAIL, PASS, SKIPPED, CheckResult

KILLED, SURVIVED, TIMEOUT, EQUIVALENT = "killed", "survived", "timeout", "equivalent"  # a timeout is not a kill: a slow test must not pass a PR
NO_TESTS_COLLECTED = 5  # pytest exit code
_JUMPS = (ast.Return, ast.Raise, ast.Continue, ast.Break)
_FLIPS: dict[type, type] = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is, ast.In: ast.NotIn, ast.NotIn: ast.In,
}
_ARITH: dict[type, type] = {ast.Add: ast.Sub, ast.Sub: ast.Add}


@dataclass(frozen=True)
class Mutant:
    path: str
    line: int
    kind: str
    original: str  # the node before the mutation, as `ast.unparse` prints it
    replacement: str  # the same node after it
    source: str  # the whole mutated file
    equivalent: bool = False  # no run reaches the node: see `_unreachable`

    @property
    def id(self) -> str:
        return hashlib.sha256(f"{self.path}:{self.line}:{self.kind}:{self.original}:{self.replacement}".encode()).hexdigest()[:12]

    def describe(self) -> str:
        def short(text: str) -> str:
            text = " ".join(text.split())
            return text if len(text) <= 24 else text[:21] + "..."
        return f"{self.path}:{self.line} {self.kind}: `{short(self.original)}` -> `{short(self.replacement)}`"


def _candidates(tree: ast.AST, lines: Collection[int]) -> list[tuple[int, str, int]]:
    """(index in `ast.walk` order, kind, sub-index) of every node on the target lines an operator applies to."""
    found: list[tuple[int, str, int]] = []
    for index, node in enumerate(ast.walk(tree)):
        if getattr(node, "lineno", None) not in lines:
            continue
        if isinstance(node, ast.Compare):
            found += [(index, "flip_cmp", i) for i, op in enumerate(node.ops) if type(op) in _FLIPS]
        elif isinstance(node, ast.BoolOp):
            found.append((index, "and_or", 0))
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            found.append((index, "bool_flip", 0))
        elif isinstance(node, ast.Constant) and type(node.value) is int:
            found.append((index, "int_const", 0))
        elif isinstance(node, (ast.BinOp, ast.AugAssign)) and type(node.op) in _ARITH:
            found.append((index, "arith_flip", 0))
        elif isinstance(node, ast.Return) and node.value is not None and not (isinstance(node.value, ast.Constant) and node.value.value is None):
            found.append((index, "return_none", 0))
        elif isinstance(node, (ast.If, ast.IfExp, ast.While)):
            found.append((index, "negate_cond", 0))
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            found.append((index, "drop_call", 0))
    return found


def _unreachable(tree: ast.AST) -> set[int]:
    """Indexes (in `ast.walk` order) of the nodes no run reaches: after a jump in the same block, or under a literal test that never takes them."""
    dead: set[int] = set()
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list):
                for i, stmt in enumerate(block):
                    if isinstance(stmt, _JUMPS):
                        dead.update(id(n) for after in block[i + 1:] for n in ast.walk(after))
        if isinstance(node, ast.If) and isinstance(node.test, ast.Constant):
            for stmt in node.orelse if node.test.value else node.body:
                dead.update(id(n) for n in ast.walk(stmt))
    return {index for index, node in enumerate(ast.walk(tree)) if id(node) in dead}


def _text(node: ast.AST, kind: str) -> str:
    return ast.unparse(node.test if kind == "negate_cond" else node)  # type: ignore[attr-defined]


def _apply(node: ast.AST, kind: str, sub: int) -> None:
    if kind == "flip_cmp":
        node.ops[sub] = _FLIPS[type(node.ops[sub])]()  # type: ignore[attr-defined]
    elif kind == "and_or":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()  # type: ignore[attr-defined]
    elif kind == "bool_flip":
        node.value = not node.value  # type: ignore[attr-defined]
    elif kind == "int_const":
        node.value = node.value + 1  # type: ignore[attr-defined]
    elif kind == "arith_flip":
        node.op = _ARITH[type(node.op)]()  # type: ignore[attr-defined]
    elif kind == "negate_cond":
        node.test = ast.UnaryOp(ast.Not(), node.test)  # type: ignore[attr-defined]
    else:  # return_none, drop_call: the value becomes None
        node.value = ast.Constant(None)  # type: ignore[attr-defined]


def generate(path: str, source: str, lines: Collection[int]) -> list[Mutant]:
    """Every mutant of `source` on `lines` (1-based), in a stable order. A source that does not parse has none."""
    if not lines:
        return []
    try:
        plain = ast.unparse(ast.parse(source)) + "\n"
        picks = _candidates(ast.parse(source), set(lines))
        unreachable = _unreachable(ast.parse(source))
    except (SyntaxError, ValueError):
        return []
    mutants: list[Mutant] = []
    for index, kind, sub in picks:
        tree = ast.parse(source)
        node = list(ast.walk(tree))[index]
        before = _text(node, kind)
        _apply(node, kind, sub)
        ast.fix_missing_locations(tree)
        mutated = ast.unparse(tree) + "\n"
        try:
            compile(mutated, path, "exec")  # the mutant has to compile, or it dies for the wrong reason
        except (SyntaxError, ValueError):
            continue
        if mutated != plain:
            mutants.append(Mutant(path, node.lineno, kind, before, _text(node, kind), mutated,  # type: ignore[attr-defined]
                                  equivalent=index in unreachable))
    return sorted(mutants, key=lambda m: (m.path, m.line, m.kind, m.id))


def sample(mutants: Sequence[Mutant], n: int, seed: str) -> list[Mutant]:
    """n mutants chosen by hash(seed + id): the same seed picks the same ones, whatever the order of `mutants`."""
    ranked = sorted(mutants, key=lambda m: hashlib.sha256((seed + m.id).encode()).hexdigest())
    return sorted(ranked[:max(n, 0)], key=lambda m: m.id)


class _Stamp:
    """Every write moves the mtime forward by whole seconds: the .pyc of a same-size source is never mistaken for the new one."""

    def __init__(self) -> None:
        self.at = int(time.time()) + 2

    def write(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        self.at += 2
        os.utime(path, (self.at, self.at))


def _run(root: Path, argv: Sequence[str], timeout: float, wrap: Callable[[list[str]], list[str]], env: dict[str, str] | None,
         home: Path | None = None) -> int | None:
    """The exit code of one test run, or None on timeout. The child gets a scrubbed environment, never the watcher's."""
    try:
        return subprocess.run(wrap(list(argv)), cwd=root, timeout=timeout, capture_output=True, env=isolation.child_env(env, home),
                              check=False).returncode
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError as exc:
        raise RuntimeError(f"test command not found: {exc}") from exc


def run_mutants(root: Path, mutants: Sequence[Mutant], test_argv: Sequence[str], timeout_each: float,
                wrap: Callable[[list[str]], list[str]] = lambda argv: argv, env: dict[str, str] | None = None,
                home: Path | None = None) -> list[tuple[Mutant, str]]:
    """Apply each mutant to `root`, run the tests, restore the file. Status: killed (tests failed), survived (passed or collected nothing), equivalent (a survivor no run reaches), timeout."""
    results: list[tuple[Mutant, str]] = []
    stamp = _Stamp()
    for mutant in mutants:
        target = root / mutant.path
        original = target.read_text(encoding="utf-8")
        try:
            stamp.write(target, mutant.source)
            code = _run(root, test_argv, timeout_each, wrap, env, home)
        finally:
            stamp.write(target, original)
        status = TIMEOUT if code is None else KILLED if code not in (0, NO_TESTS_COLLECTED) else EQUIVALENT if mutant.equivalent else SURVIVED
        results.append((mutant, status))
    return results


def check_mutation(root: Path, changes: Sequence[FileChange], test_argv: Sequence[str], n: int = 12, min_kill: float = 0.6,
                   timeout_each: float = 120.0, seed: str = "", wrap: Callable[[list[str]], list[str]] = lambda argv: argv,
                   env: dict[str, str] | None = None, home: Path | None = None) -> CheckResult:
    """Fail when fewer than `min_kill` of the live mutants in a sample of n of the PR's added production lines die under the PR's tests."""
    mutants: list[Mutant] = []
    for change in changes:
        if change.kind != "code" or change.status not in ("A", "M") or not (root / change.path).is_file():
            continue
        try:
            mutants += generate(change.path, (root / change.path).read_text(encoding="utf-8"), change.added)
        except (OSError, UnicodeDecodeError):
            continue
    if not mutants:
        return CheckResult("mutation", SKIPPED, ("sem linha de producao mutavel",))
    if not test_argv:  # pytest without a file would run the whole suite
        return CheckResult("mutation", FAIL, ("sem teste novo nem vizinho para rodar contra os mutantes",))
    code = _run(root, test_argv, timeout_each * 2, wrap, env, home)  # the tests have to pass on the unmutated tree, or every mutant "dies"
    if code != 0:
        return CheckResult("mutation", ERROR, (f"os testes nao passam sem mutante (saida {code}): a amostra nao diz nada",))
    results = run_mutants(root, sample(mutants, n, seed), test_argv, timeout_each, wrap=wrap, env=env, home=home)
    killed = sum(1 for _, status in results if status == KILLED)
    equivalent = sum(1 for _, status in results if status == EQUIVALENT)
    survivors = [m for m, status in results if status == SURVIVED]
    live = len(results) - equivalent
    ratio = killed / live if live else 0.0
    measured = {"total": len(results), "killed": killed, "timeout": sum(1 for _, s in results if s == TIMEOUT),
                "survived": [m.describe() for m in survivors[:8]], "ratio": round(ratio, 3), "n": n, "seed": seed,
                "candidates": len(mutants), "equivalent": equivalent}
    if live == 0:
        return CheckResult("mutation", FAIL, ("nenhum mutante vivo na amostra (todos equivalentes ou inalcancaveis): a amostra nao diz nada",), measured)
    if equivalent * 2 > len(results):
        return CheckResult("mutation", FAIL, (f"mutantes equivalentes {equivalent}/{len(results)} (mais da metade da amostra): a amostra nao diz nada",), measured)
    if ratio < min_kill:
        reason = f"mutantes mortos {killed}/{live} (<{int(min_kill * 100)}%): sobreviventes: " + ", ".join(m.describe() for m in survivors[:8])
        return CheckResult("mutation", FAIL, (reason,), measured)
    return CheckResult("mutation", PASS, (), measured)
