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
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import identity, isolation, redgreen
from .diffs import FileChange
from .model import ERROR, FAIL, PASS, SKIPPED, CheckResult

KILLED, SURVIVED, TIMEOUT, EQUIVALENT = "killed", "survived", "timeout", "equivalent"  # a timeout is not a kill: a slow test must not pass a PR
NO_TESTS_COLLECTED = 5  # pytest exit code
EXTRA_CAP = 3  # probes per sampled mutant, spent only on new red tests the sample did not attribute
MIN_LIVE_TO_JUDGE = 5  # live mutants below this: a kill ratio is noise, so the check warns instead of failing (#1649)
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


@dataclass(frozen=True)
class Outcome:
    mutant: Mutant
    status: str
    killers: tuple[str, ...] = ()  # the test node ids that failed under this mutant (a bare file path: a collection error took it down)


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
         home: Path | None = None) -> tuple[int | None, str]:
    """The exit code and the stdout of one test run; (None, "") on timeout. The child gets a scrubbed environment, never the watcher's."""
    try:
        done = subprocess.run(wrap(list(argv)), cwd=root, timeout=timeout, capture_output=True, env=isolation.child_env(env, home),
                              check=False, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return None, ""
    except FileNotFoundError as exc:
        raise RuntimeError(f"test command not found: {exc}") from exc
    return done.returncode, done.stdout


def _killers(output: str) -> tuple[str, ...]:
    """The tests a run reports as failed (`-rfE` short summary), by node id. A collection ERROR is not one: it kills the mutant, but it
    is a broken import, not a test that caught the change, so it credits no test."""
    return tuple(sorted(name for name, verdict in redgreen.parse_outcomes(output).items() if verdict == "failed"))


def run_mutants(root: Path, mutants: Sequence[Mutant], test_argv: Sequence[str], timeout_each: float,
                wrap: Callable[[list[str]], list[str]] = lambda argv: argv, env: dict[str, str] | None = None,
                home: Path | None = None) -> list[Outcome]:
    """Apply each mutant to `root`, run the tests, restore the file. Status: killed (tests failed), survived (passed or collected nothing), equivalent (a survivor no run reaches), timeout.
    `-rfE` names every failing test of a killed mutant: no `-x`, so a second test that kills the same mutant is credited too."""
    results: list[Outcome] = []
    stamp = _Stamp()
    for mutant in mutants:
        target = root / mutant.path
        original = target.read_text(encoding="utf-8")
        try:
            stamp.write(target, mutant.source)
            code, out = _run(root, [*test_argv, "-rfE"], timeout_each, wrap, env, home)
        finally:
            stamp.write(target, original)
        status = TIMEOUT if code is None else KILLED if code not in (0, NO_TESTS_COLLECTED) else EQUIVALENT if mutant.equivalent else SURVIVED
        results.append(Outcome(mutant, status, _killers(out) if status == KILLED else ()))
    return results


def _killer_map(outcomes: Sequence[Outcome]) -> dict[str, list[str]]:
    """Test node id -> the ids of the mutants it killed."""
    killers: dict[str, list[str]] = {}
    for outcome in outcomes:
        for test in outcome.killers:
            killers.setdefault(test, []).append(outcome.mutant.id)
    return killers


def _unattributed(red: Sequence[str], killers: Mapping[str, object]) -> list[str]:
    """The new tests that fail on main and killed no mutant of the sample."""
    return [test for test in red if test not in killers]


def _attribution_reason(unattributed: Sequence[str]) -> str:
    return ("test_kills_no_mutant: teste novo que falha na main e nao mata nenhum mutante da amostra (vacuo, ou testa so a propria "
            "saida; marque characterization se ja e verdade na main): " + ", ".join(unattributed[:8]))


def check_mutation(root: Path, changes: Sequence[FileChange], test_argv: Sequence[str], n: int = 12, min_kill: float = 0.6,
                   timeout_each: float = 120.0, seed: str = "", wrap: Callable[[list[str]], list[str]] = lambda argv: argv,
                   env: dict[str, str] | None = None, home: Path | None = None, red: Sequence[str] | None = None) -> CheckResult:
    """Fail when fewer than `min_kill` of the live mutants in a sample of n of the PR's added production lines die under the PR's tests.
    `red` (the new tests that fail on main, from the red/green check) must each kill a mutant of the sample, or the check fails with
    `test_kills_no_mutant`; None skips that rule."""
    red = list(red or ())
    mutants: list[Mutant] = []
    for change in changes:
        if change.kind != "code" or change.status not in ("A", "M") or not (root / change.path).is_file():
            continue
        try:
            mutants += generate(change.path, (root / change.path).read_text(encoding="utf-8"), change.added)
        except (OSError, UnicodeDecodeError):
            continue
    if not mutants:
        if red:  # no mutable line: the whole candidate pool (empty) was tested, so the attribution rule has no mutant to apply to; it says so
            return CheckResult("mutation", SKIPPED, (f"test_kills_no_mutant pulado: nenhum mutante nas linhas alteradas, {len(red)} teste(s) vermelho(s) novo(s) nao checados",),
                               {"unattributed": [], "killers": {}, "skipped": list(red)})
        python_changed = any(c.kind == "code" and c.status in ("A", "M") for c in changes)  # Python with no mutable line: the old reason
        reason = None if python_changed else identity.non_python_skip_reason(changes)
        return CheckResult("mutation", SKIPPED, (reason or "sem linha de producao mutavel",))
    if not test_argv:  # pytest without a file would run the whole suite
        return CheckResult("mutation", FAIL, ("sem teste novo nem vizinho para rodar contra os mutantes",))
    code, _ = _run(root, test_argv, timeout_each * 2, wrap, env, home)  # the tests have to pass on the unmutated tree, or every mutant "dies"
    if code != 0:
        return CheckResult("mutation", ERROR, (f"os testes nao passam sem mutante (saida {code}): a amostra nao diz nada",))
    picked = sample(mutants, n, seed)
    results = run_mutants(root, picked, test_argv, timeout_each, wrap=wrap, env=env, home=home)
    probes: list[Outcome] = []  # the sample is bounded by seed: a new red test it missed is probed with the other mutants, capped
    for mutant in [m for m in mutants if m not in picked][:EXTRA_CAP * max(n, 1)] if red else []:
        if not _unattributed(red, _killer_map(results + probes)):
            break
        probes += run_mutants(root, [mutant], test_argv, timeout_each, wrap=wrap, env=env, home=home)
    killed = sum(1 for o in results if o.status == KILLED)
    equivalent = sum(1 for o in results if o.status == EQUIVALENT)
    survivors = [o.mutant for o in results if o.status == SURVIVED]
    live = len(results) - equivalent
    ratio = killed / live if live else 0.0
    judged = live >= MIN_LIVE_TO_JUDGE
    killers = _killer_map(results + probes)
    unattributed = _unattributed(red, killers) if red else []
    measured = {"total": len(results), "killed": killed, "timeout": sum(1 for o in results if o.status == TIMEOUT),
                "survived": [m.describe() for m in survivors[:8]], "ratio": round(ratio, 3), "n": n, "seed": seed,
                "candidates": len(mutants), "equivalent": equivalent, "judged": judged, "killers": killers,
                "unattributed": unattributed, "probes": len(probes)}
    extra = (_attribution_reason(unattributed),) if unattributed else ()  # the attribution rule holds at any sample size, small ones included
    if live == 0:
        return CheckResult("mutation", FAIL, ("nenhum mutante vivo na amostra (todos equivalentes ou inalcancaveis): a amostra nao diz nada", *extra), measured)
    if equivalent * 2 > len(results):
        return CheckResult("mutation", FAIL, (f"mutantes equivalentes {equivalent}/{len(results)} (mais da metade da amostra): a amostra nao diz nada", *extra), measured)
    if killed == 0 or (judged and ratio < min_kill) or (not judged and killed < live - 1):  # zero kills is vacuous at any size; a ratio judges from MIN_LIVE_TO_JUDGE up; below it at most one survivor (the equivalent mutant the ratio would punish)
        reason = f"mutantes mortos {killed}/{live} (<{int(min_kill * 100)}%): sobreviventes: " + ", ".join(m.describe() for m in survivors[:8])
        return CheckResult("mutation", FAIL, (reason, *extra), measured)
    if extra:
        return CheckResult("mutation", FAIL, extra, measured)
    if not judged:  # some kill, too few live mutants for a ratio: the survivors go to a human, the check does not block
        warning = (f"amostra pequena demais para julgar ({killed}/{live} vivos mortos, minimo {MIN_LIVE_TO_JUDGE}); "
                   "sobreviventes para revisao humana: " + ", ".join(m.describe() for m in survivors))
        return CheckResult("mutation", PASS, (warning,) if survivors else (), measured)
    return CheckResult("mutation", PASS, (), measured)
