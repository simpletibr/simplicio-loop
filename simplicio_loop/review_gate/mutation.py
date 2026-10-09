"""Mutation gate: check that code changes are well-tested via mutation score."""
from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import sys
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simplicio_loop.review_gate.diffs import FileChange
from simplicio_loop.review_gate.model import FAIL, PASS, SKIPPED, CheckResult


@dataclass(frozen=True)
class Mutant:
    """A single mutant: a line mutation in a file."""

    path: str
    line: int
    kind: str
    original: str  # Original line text
    mutated: str  # Original full source (yes, confusing name for backward compat)

    @property
    def id(self) -> str:
        """Stable, deterministic ID of this mutant."""
        parts = f"{self.path}:{self.line}:{self.kind}:{self.original}"
        return hashlib.sha256(parts.encode()).hexdigest()[:12]

    def describe(self) -> str:
        """Short human-readable description of the mutant."""
        orig_snippet = self.original[:20] if len(self.original) <= 20 else self.original[:17] + "..."
        # Find the mutated line in mutated source
        mutated_lines = self.mutated.splitlines(keepends=True)
        if self.line <= len(mutated_lines):
            mut_line = mutated_lines[self.line - 1].strip()
            mut_snippet = mut_line[:20] if len(mut_line) <= 20 else mut_line[:17] + "..."
        else:
            mut_snippet = "?"
        return f"{self.path}:{self.line} {self.kind}: `{orig_snippet}` -> `{mut_snippet}`"


def generate(path: str, source: str, lines: Collection[int]) -> list[Mutant]:
    """Generate mutants for a source file.

    Deterministic, via regex patterns. Only mutants on nodes whose lineno is in `lines`.
    Operators: flip de comparacao, and <-> or, return expr -> return None,
    constante numerica int ±1, True<->False, x += k <-> x -= k.

    Generated mutants are valid Python (compile() succeeds).
    """
    if not lines:
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines_set = set(lines)
    mutants: list[Mutant] = []
    source_lines = source.splitlines(keepends=True)

    # For each target line, collect relevant text patterns and create mutants
    for line_no in lines_set:
        if line_no > len(source_lines) or line_no < 1:
            continue

        line_text = source_lines[line_no - 1]
        line_content = line_text.rstrip('\n\r')
        indent = len(line_content) - len(line_content.lstrip())

        # Try flips: ==, !=, <, >, <=, >=, in, not in, is, is not
        flips = [
            ("==", "!="),
            ("!=", "=="),
            ("<=", ">"),
            (">=", "<"),
            ("<", ">="),
            (">", "<="),
            (" in ", " not in "),
            (" not in ", " in "),
            (" is not ", " is "),
            (" is ", " is not "),
        ]

        for old, new in flips:
            if old in line_content:
                mutated_content = line_content.replace(old, new, 1)
                if mutated_content != line_content:
                    mutated_lines = source_lines[:line_no - 1] + [mutated_content + ('\n' if line_text.endswith('\n') else '')] + source_lines[line_no:]
                    mutated_source = ''.join(mutated_lines)
                    if _is_valid_python(mutated_source):
                        mutants.append(Mutant(
                            path=path,
                            line=line_no,
                            kind="flip_cmp",
                            original=line_content,
                            mutated=mutated_source,
                        ))

        # Flip and <-> or
        if " and " in line_content:
            mutated_content = line_content.replace(" and ", " or ", 1)
            if mutated_content != line_content:
                mutated_lines = source_lines[:line_no - 1] + [mutated_content + ('\n' if line_text.endswith('\n') else '')] + source_lines[line_no:]
                mutated_source = ''.join(mutated_lines)
                if _is_valid_python(mutated_source):
                    mutants.append(Mutant(
                        path=path,
                        line=line_no,
                        kind="and_or",
                        original=line_content,
                        mutated=mutated_source,
                    ))

        if " or " in line_content:
            mutated_content = line_content.replace(" or ", " and ", 1)
            if mutated_content != line_content:
                mutated_lines = source_lines[:line_no - 1] + [mutated_content + ('\n' if line_text.endswith('\n') else '')] + source_lines[line_no:]
                mutated_source = ''.join(mutated_lines)
                if _is_valid_python(mutated_source):
                    mutants.append(Mutant(
                        path=path,
                        line=line_no,
                        kind="and_or",
                        original=line_content,
                        mutated=mutated_source,
                    ))

        # Flip True <-> False
        if "True" in line_content:
            mutated_content = line_content.replace("True", "False", 1)
            if mutated_content != line_content:
                mutated_lines = source_lines[:line_no - 1] + [mutated_content + ('\n' if line_text.endswith('\n') else '')] + source_lines[line_no:]
                mutated_source = ''.join(mutated_lines)
                if _is_valid_python(mutated_source):
                    mutants.append(Mutant(
                        path=path,
                        line=line_no,
                        kind="bool_flip",
                        original=line_content,
                        mutated=mutated_source,
                    ))

        if "False" in line_content:
            mutated_content = line_content.replace("False", "True", 1)
            if mutated_content != line_content:
                mutated_lines = source_lines[:line_no - 1] + [mutated_content + ('\n' if line_text.endswith('\n') else '')] + source_lines[line_no:]
                mutated_source = ''.join(mutated_lines)
                if _is_valid_python(mutated_source):
                    mutants.append(Mutant(
                        path=path,
                        line=line_no,
                        kind="bool_flip",
                        original=line_content,
                        mutated=mutated_source,
                    ))

        # Return expr -> return None
        if "return " in line_content and "return None" not in line_content:
            match = re.search(r"return\s+(.+?)(?:\s*#|$)", line_content)
            if match:
                mutated_content = re.sub(r"(return\s+).+?(\s*#|$)", r"return None\2", line_content)
                if mutated_content != line_content:
                    mutated_lines = source_lines[:line_no - 1] + [mutated_content + ('\n' if line_text.endswith('\n') else '')] + source_lines[line_no:]
                    mutated_source = ''.join(mutated_lines)
                    if _is_valid_python(mutated_source):
                        mutants.append(Mutant(
                            path=path,
                            line=line_no,
                            kind="return_none",
                            original=line_content,
                            mutated=mutated_source,
                        ))

        # Int constant ±1
        int_matches = list(re.finditer(r"\b(\d+)\b", line_content))
        for match in int_matches:
            num = int(match.group(1))
            for delta in (1, -1):
                new_num = num + delta
                mutated_content = line_content[:match.start(1)] + str(new_num) + line_content[match.end(1):]
                if mutated_content != line_content:
                    mutated_lines = source_lines[:line_no - 1] + [mutated_content + ('\n' if line_text.endswith('\n') else '')] + source_lines[line_no:]
                    mutated_source = ''.join(mutated_lines)
                    if _is_valid_python(mutated_source):
                        mutants.append(Mutant(
                            path=path,
                            line=line_no,
                            kind=f"int_{'inc' if delta > 0 else 'dec'}",
                            original=line_content,
                            mutated=mutated_source,
                        ))

        # x += k <-> x -= k
        if "+=" in line_content:
            mutated_content = line_content.replace("+=", "-=", 1)
            if mutated_content != line_content:
                mutated_lines = source_lines[:line_no - 1] + [mutated_content + ('\n' if line_text.endswith('\n') else '')] + source_lines[line_no:]
                mutated_source = ''.join(mutated_lines)
                if _is_valid_python(mutated_source):
                    mutants.append(Mutant(
                        path=path,
                        line=line_no,
                        kind="arith_flip",
                        original=line_content,
                        mutated=mutated_source,
                    ))

        if "-=" in line_content:
            mutated_content = line_content.replace("-=", "+=", 1)
            if mutated_content != line_content:
                mutated_lines = source_lines[:line_no - 1] + [mutated_content + ('\n' if line_text.endswith('\n') else '')] + source_lines[line_no:]
                mutated_source = ''.join(mutated_lines)
                if _is_valid_python(mutated_source):
                    mutants.append(Mutant(
                        path=path,
                        line=line_no,
                        kind="arith_flip",
                        original=line_content,
                        mutated=mutated_source,
                    ))

    # Remove duplicates
    seen = set()
    unique = []
    for m in mutants:
        if m.id not in seen:
            seen.add(m.id)
            unique.append(m)

    return unique


def _is_valid_python(source: str) -> bool:
    """Check if source is valid Python."""
    try:
        compile(source, "<string>", "exec")
        return True
    except SyntaxError:
        return False


def sample(mutants: list[Mutant], n: int, seed: str) -> list[Mutant]:
    """Sample n mutants stably.

    Deterministic: same input => same output.
    Orders by sha256(seed + mutant.id), takes n first, returns ordered by id.
    """
    if not mutants:
        return []

    # Create stable order based on seed + mutant.id
    scored = [
        (hashlib.sha256((seed + m.id).encode()).hexdigest(), m)
        for m in mutants
    ]
    scored.sort(key=lambda x: x[0])

    # Take first n
    selected = [m for _, m in scored[:n]]

    # Return ordered by id
    return sorted(selected, key=lambda m: m.id)


def run_mutants(
    root: Path,
    mutants: Sequence[Mutant],
    test_argv: Sequence[str],
    timeout_each: float,
    wrap: Callable[[list[str]], list[str]] = lambda argv: argv,
    env: dict[str, str] | None = None,
) -> list[tuple[Mutant, str]]:
    """Run tests on each mutant. Apply, test, restore.

    Returns list of (Mutant, status) where status is "killed", "survived", or "timeout".
    - killed: returncode != 0 and returncode != 5
    - survived: returncode == 0 or returncode == 5
    - timeout: subprocess timeout
    """
    results: list[tuple[Mutant, str]] = []

    for mutant in mutants:
        fpath = root / mutant.path
        original_content = fpath.read_text(encoding="utf-8")

        try:
            # Apply mutant - write full mutated source
            fpath.write_text(mutant.mutated, encoding="utf-8")

            # Run tests
            try:
                cmd = wrap(list(test_argv))
                done = subprocess.run(
                    cmd,
                    cwd=root,
                    timeout=timeout_each,
                    capture_output=True,
                    env=env or {},
                )
                returncode = done.returncode
            except subprocess.TimeoutExpired:
                results.append((mutant, "timeout"))
                continue
            except FileNotFoundError as exc:
                raise RuntimeError(f"test command not found: {exc}") from exc

            # Determine kill status
            if returncode == 5:
                # No tests collected = survived
                status = "survived"
            elif returncode == 0:
                # Tests passed = survived
                status = "survived"
            else:
                # Tests failed = killed
                status = "killed"

            results.append((mutant, status))
        finally:
            # Always restore original
            fpath.write_text(original_content, encoding="utf-8")

    return results


def check_mutation(
    root: Path,
    changes: Sequence[FileChange],
    test_argv: Sequence[str],
    n: int = 12,
    min_kill: float = 0.6,
    timeout_each: float = 120.0,
    seed: str = "",
    wrap: Callable[[list[str]], list[str]] = lambda argv: argv,
    env: dict[str, str] | None = None,
) -> CheckResult:
    """Check mutation testing gate.

    For each FileChange with kind=="code" and status A/M:
    - Read source, generate mutants on added lines
    - Sample n mutants
    - Run mutants
    - If killed/total < min_kill => FAIL
    - Else => PASS
    - No code changes => SKIPPED
    """
    # Collect code changes
    code_changes = [
        c for c in changes
        if c.kind == "code" and c.status in ("A", "M")
    ]

    if not code_changes:
        return CheckResult(
            name="mutation",
            status=SKIPPED,
            reasons=("sem linha de producao mutavel",),
        )

    # Generate mutants on added lines
    all_mutants: list[Mutant] = []
    for change in code_changes:
        fpath = root / change.path
        if not fpath.exists():
            continue
        try:
            source = fpath.read_text(encoding="utf-8")
        except Exception:
            continue

        mutants = generate(change.path, source, change.added)
        all_mutants.extend(mutants)

    if not all_mutants:
        return CheckResult(
            name="mutation",
            status=SKIPPED,
            reasons=("sem linha de producao mutavel",),
        )

    # Sample
    sampled = sample(all_mutants, n, seed)

    # Run
    start = time.time()
    results = run_mutants(root, sampled, test_argv, timeout_each, wrap=wrap, env=env)
    elapsed = time.time() - start

    # Analyze
    total = len(results)
    killed = sum(1 for _, status in results if status == "killed")
    survived = [m for m, status in results if status == "survived"]
    timeout = sum(1 for _, status in results if status == "timeout")
    ratio = killed / total if total > 0 else 0.0

    measured = {
        "total": total,
        "killed": killed,
        "survived": [m.describe() for m in survived[:8]],
        "timeout": timeout,
        "ratio": round(ratio, 3),
        "n": n,
        "seed": seed,
    }

    if ratio < min_kill:
        survived_desc = ", ".join(m.describe() for m in survived[:8])
        reason = f"mutantes mortos {killed}/{total} (<{int(min_kill*100)}%): sobreviventes: {survived_desc}"
        return CheckResult(
            name="mutation",
            status=FAIL,
            reasons=(reason,),
            measured=measured,
        )

    return CheckResult(
        name="mutation",
        status=PASS,
        measured=measured,
    )
