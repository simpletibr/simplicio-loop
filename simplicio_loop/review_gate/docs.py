"""Docs check: ste-lint of a touched doc must not get worse, and a new measured claim needs a label.

The linter is the one the loop ships (`_bundle/skills/asd-ste100/scripts/ste-lint.py`), loaded as a module.
A claim is a new line with a number and a unit; it needs `MEASURED` or `UNVERIFIED` on the line, or a test path.
"""
from __future__ import annotations

import importlib.util
import re
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from .diffs import FileChange
from .model import ERROR, FAIL, PASS, SKIPPED, CheckResult

NAME = "docs"
_LINT = Path(__file__).resolve().parents[1] / "_bundle" / "skills" / "asd-ste100" / "scripts" / "ste-lint.py"
_CLAIM = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:%|ms|s|x|MB|GB|tokens?|testes?|tests?|linhas?|lines?|mutantes?|mutants?)\b")
_LABEL = re.compile(r"\b(?:MEASURED|UNVERIFIED)\b|\btests/[\w/.-]+")


@lru_cache(maxsize=1)
def _lint_module():
    spec = importlib.util.spec_from_file_location("ste_lint_gate", _LINT)
    if spec is None or spec.loader is None or not _LINT.is_file():
        raise RuntimeError(f"ste-lint not found at {_LINT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hard_count(text: str) -> int:
    findings, _ = _lint_module().lint(text, filename="doc")
    return sum(1 for f in findings if f["level"] == "advisory-free")


def check_docs(base_root: Path, head_root: Path, changes: Sequence[FileChange]) -> CheckResult:
    docs = [c for c in changes if c.kind == "docs" and c.path.endswith(".md") and c.status in ("A", "M")]
    if not docs:
        return CheckResult(NAME, SKIPPED, ("nenhum doc .md novo ou alterado",))
    reasons: list[str] = []
    files: dict[str, dict] = {}
    try:
        for change in docs:
            text = (head_root / change.path).read_text(encoding="utf-8")
            old_file = base_root / change.path
            base = hard_count(old_file.read_text(encoding="utf-8")) if change.status == "M" and old_file.is_file() else 0
            head = hard_count(text)
            files[change.path] = {"base": base, "head": head}
            if head > base:
                reasons.append(f"ste-lint piorou em {change.path}: {base} -> {head} violacoes duras")
            lines = text.splitlines()
            for number in change.added:
                line = lines[number - 1] if 0 < number <= len(lines) else ""
                found = _CLAIM.search(line)
                if found and not _LABEL.search(line):
                    reasons.append(f"afirmacao nova sem teste em {change.path}:{number} ('{found.group(0)}'): "
                                   "marque UNVERIFIED ou aponte o teste")
    except (OSError, RuntimeError) as exc:
        return CheckResult(NAME, ERROR, (f"docs check could not run: {exc}",))
    return CheckResult(NAME, FAIL if reasons else PASS, tuple(reasons), {"files": files})
