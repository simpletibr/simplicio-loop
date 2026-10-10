"""Who wrote, who approved, and at which level: the roles are recorded, and the author never approves their own PR.

Every agent of the loop comments with the same GitHub account, so the account proves nothing. The proof is the
agent id and role, recorded in the approval comment, and for T2 a marker of an independent reviewer bound to the head.
"""
from __future__ import annotations

import ast
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Iterator, Mapping, Sequence

from .. import plan_paths
from .diffs import FileChange, is_pytest_infra
from .model import ERROR, FAIL, PASS, CheckResult, Level

NAME = "identity"
T0_MAX_ADDED_LINES = 200
# Words of a path (split on anything that is not a letter or digit) that make a change security-sensitive.
SECURITY_WORDS = frozenset({"sandbox", "daemon", "token", "tokens", "uninstall", "mapper", "login", "secret", "secrets",
                            "credential", "credentials", "auth", "permission", "permissions"})
INDEPENDENT_PHRASE = "REVISAO INDEPENDENTE: APROVADA"
_FIELDS = {"revisor": "agent_id", "papel": "role", "modelo": "model", "host": "host"}


@dataclass(frozen=True)
class Agent:
    agent_id: str
    role: str
    model: str
    host: str

    def to_dict(self) -> dict[str, str]:
        return {"agent_id": self.agent_id, "role": self.role, "model": self.model, "host": self.host}


AUTO_REVIEWER = Agent("review-gate/auto", "automatic-reviewer", "deterministic", "loop")


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


# Paths that decide what the loop trusts (#1649, M1): the gate itself, the squad flow and the host rules. Beside what
# `plan_paths.protected_refusal` already names (the one source of the protected list). Also what steers the pytest that
# judges the PR: a `conftest.py` at any depth, the pytest configuration and the plugin modules (`diffs.is_pytest_infra`).
# The gate is a quality filter against vacuous and dead-code PRs, not a boundary against an author who writes code to fool it:
# what Python loads by itself (`sitecustomize.py`, `*.pth`, installed metadata) and a test module that sets `pytest_plugins` are
# T2 too, so a human reads them.
GATE_DIRS = frozenset({"review_gate"})
GATE_FILES = frozenset({"squads.py", "squad_review.py", "squad_flow.py", "SKILL.md"})
GATE_WORDS = frozenset({"host-rules", "host_rules"})


START_UP_NAMES = frozenset({"sitecustomize.py", "usercustomize.py"})  # Python imports them before pytest starts
METADATA_SUFFIXES = (".egg-info", ".dist-info")  # an installed distribution can declare a pytest plugin (`[pytest11]`)


def _runs_before_the_tests(path: str) -> bool:
    """True for what Python or pytest loads by itself: `sitecustomize.py`, `usercustomize.py`, any `*.pth`, and anything inside
    a `*.egg-info/` or `*.dist-info/` folder (`entry_points.txt`). The names are read as a forgiving file system reads them."""
    parts = [unicodedata.normalize("NFKC", p).lower().rstrip(" .") for p in PurePosixPath(path.replace("\\", "/")).parts]
    if not parts:
        return False
    return (parts[-1] in START_UP_NAMES or parts[-1].endswith(".pth")
            or any(p.endswith(METADATA_SUFFIXES) for p in parts[:-1]))


def sensitive_path(path: str) -> bool:
    """True when a change to `path` is T2 whatever it contains: protected by the plan paths, or part of the gate/host rules."""
    posix = PurePosixPath(path)
    return (plan_paths.protected_refusal(path) is not None or posix.name in GATE_FILES or is_pytest_infra(path)
            or _runs_before_the_tests(path)
            or bool(GATE_DIRS.intersection(posix.parts[:-1])) or bool(GATE_WORDS.intersection(p.lower() for p in posix.parts)))


def _names(target: ast.expr) -> Iterator[str]:
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, ast.Starred):
        yield from _names(target.value)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for item in target.elts:
            yield from _names(item)


def _module_level(body: Sequence[ast.stmt]) -> Iterator[ast.stmt]:
    """The statements that run when the module is imported: not the bodies of functions and classes."""
    for node in body:
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for field in ("body", "orelse", "finalbody"):
                yield from _module_level(getattr(node, field, None) or [])
            for handler in getattr(node, "handlers", None) or []:
                yield from _module_level(handler.body)
            for case in getattr(node, "cases", None) or []:
                yield from _module_level(case.body)


def sets_pytest_plugins(text: str) -> bool:
    """True when the module assigns to the name `pytest_plugins` at module level: pytest then loads those plugins."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    for node in _module_level(tree.body):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
        if any("pytest_plugins" in _names(t) for t in targets):
            return True
    return False


def paths_level(paths: Sequence[str]) -> int:
    """2 when any path is sensitive or names a security topic, else 0: the floor of the level the diff imposes."""
    for path in paths:
        if sensitive_path(path) or SECURITY_WORDS.intersection(re.split(r"[^a-z0-9]+", path.lower())):
            return 2
    return 0


def classify_level(changes: Sequence[FileChange], read: Callable[[str], str | None] | None = None) -> Level:
    """`read(path)` gives the text of a file of the head (None: unknown); with it a changed test module that sets
    `pytest_plugins` is T2 as well. Without it only the paths count."""
    if any(sensitive_path(c.path) for c in changes):  # deleting or touching the gate is as sensitive as editing it
        return Level.T2
    if read is not None:
        for c in changes:
            if c.kind == "test" and c.status != "D" and (text := read(c.path)) and sets_pytest_plugins(text):
                return Level.T2
    production = [c for c in changes if c.kind in ("code", "other") and c.status != "D"]
    scanned = [*production, *(c for c in changes if c.kind == "test" and c.status != "D")] if production else []  # a security test beside production code names the topic
    if any(SECURITY_WORDS.intersection(re.split(r"[^a-z0-9]+", str(PurePosixPath(c.path)).lower())) for c in scanned):
        return Level.T2
    # Non-Python production files (M2, #1649) cannot be checked by the automatic gate (redgreen, mutation, usage):
    # the gate runs Python tests, so non-Python behavior changes need human review. But test files are not production code.
    non_python_production = [c for c in production if c.kind == "other" and PurePosixPath(c.path).parts[0] != "tests"]
    if any(non_python_production):
        return Level.T2
    if not production and sum(len(c.added) for c in changes) <= T0_MAX_ADDED_LINES:
        return Level.T0
    return Level.T1


def check_identity(author: Agent, reviewer: Agent, level: Level, independent: Agent | None) -> CheckResult:
    if not author.agent_id or not author.role:
        return CheckResult(NAME, ERROR, ("autor do PR desconhecido: sem identidade nao ha como provar independencia",))
    measured = {"level": level.value, "author": author.to_dict(), "reviewer": reviewer.to_dict(),
                "independent": independent.agent_id if independent else None}
    reasons: list[str] = []
    if reviewer.agent_id == author.agent_id:
        reasons.append(f"auto-aprovacao: o autor ({author.agent_id}) nao pode aprovar o proprio PR")
    elif reviewer.role == author.role:
        reasons.append(f"o revisor ({reviewer.agent_id}) tem o mesmo papel do autor ({author.role}): a aprovacao exige papel diferente")
    if level is Level.T2:
        if independent is None:
            reasons.append("nivel T2 (seguranca) exige revisor independente: nenhum marcador "
                           f"'{INDEPENDENT_PHRASE}' com o head atual; o portao automatico sozinho nao aprova")
        elif independent.agent_id in (author.agent_id, reviewer.agent_id) or independent.role in (author.role, reviewer.role):
            reasons.append(f"revisor independente ({independent.agent_id}, {independent.role}) nao e independente "
                           "do autor nem do portao automatico")
    return CheckResult(NAME, FAIL if reasons else PASS, tuple(reasons), measured)


def parse_independent_marker(comments: Sequence[Mapping], head: str) -> Agent | None:
    """The independent reviewer who approved exactly `head`: a comment line `REVISÃO INDEPENDENTE: APROVADA`
    (not quoted) with `revisor:`, `papel:`, `modelo:`, `host:` and `head:` lines."""
    for comment in comments:
        lines = [_fold(raw.strip()) for raw in str(comment.get("body") or "").splitlines()]
        if INDEPENDENT_PHRASE not in [ln.upper() for ln in lines]:
            continue
        found: dict[str, str] = {}
        for line in lines:
            key, sep, value = line.partition(":")
            if sep and key.strip().lower() in (*_FIELDS, "head"):
                found[key.strip().lower()] = value.strip()
        marked = found.get("head", "")
        if marked == head and len(head) == 40 and all(found.get(k) for k in _FIELDS):
            return Agent(**{attr: found[key] for key, attr in _FIELDS.items()})
    return None
