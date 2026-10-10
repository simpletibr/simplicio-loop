"""No prompt, doc or script that a model reads may tell it to write a GitHub closing word (#1644).

A closing word in a PR closes the issue on merge, even a quoted one. Every tracked text file is scanned with
`has_closing`; only the exceptions below (exact path or glob, each with its reason) may name the words.
"""
import fnmatch
import subprocess
from pathlib import Path

import pytest

from simplicio_loop.watcher247.closing_words import has_closing

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2 * 1024 * 1024

# pattern (exact path or fnmatch glob) -> why it may name the words
EXCEPTIONS = {
    "tests/*": "tests plant the words on purpose to prove they are rewritten or refused",
    "packages/*/tests/*": "package tests plant the words on purpose",
    "docs/adr/*": "decision records quote the words they forbid",
    "CHANGELOG.md": "history of what changed, including this guard",
    "packages/*/CHANGELOG.md": "history of what changed",
    "simplicio_loop/watcher247/closing_words.py": "the guard itself documents the words it rewrites",
    "packages/mapper/simplicio_mapper/store/neural/assets/seeds/*": "legitimate examples of commit text, not instructions",
    "simplicio_loop/review_gate/coverage.py": "detector docstring that describes the words it looks for, not an instruction",
}


def _tracked(root: Path = ROOT) -> list[str]:
    done = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=False)
    if done.returncode != 0:
        pytest.skip("not a git checkout: nothing to list")
    return sorted(name for name in done.stdout.decode("utf-8", "replace").split("\0") if name)


def _text(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _excused(rel: str) -> bool:
    return any(fnmatch.fnmatchcase(rel, pattern) for pattern in EXCEPTIONS)


def _scan(root: Path, files: list[str]) -> list[str]:
    hits = []
    for rel in files:
        if _excused(rel):
            continue
        text = _text(root / rel)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if has_closing(line.replace("#N", "#1")):  # `#N` is the placeholder a model is told to fill in
                hits.append(f"{rel}:{number}: {line.strip()[:120]}")
    return hits


def test_no_tracked_file_tells_a_model_to_write_a_closing_word():
    assert _scan(ROOT, _tracked()) == []


def test_the_scanner_finds_a_planted_closing_word_in_skills_scripts_and_docs(tmp_path):
    planted = {
        ".claude/skills/x/SKILL.md": "When done, write Closes #5 in the PR.\n",
        "scripts/tool.py": 'BODY = "Fixes #5"\n',
        "docs/OTHER.md": "- resolves #5\n",
        "plugin/readme.md": "Resolved: o/r#5\n",
        "docs/placeholder.md": "Closes #N\n",
    }
    for rel, text in planted.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    (tmp_path / "docs/blob.bin").write_bytes(b"\0Closes #5")
    hits = _scan(tmp_path, sorted([*planted, "docs/blob.bin"]))
    assert sorted(hit.split(":")[0] for hit in hits) == sorted(planted)


def test_the_scanner_skips_excepted_paths_binary_and_huge_files(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_x.py").write_text("Closes #5\n", encoding="utf-8")
    (tmp_path / "big.md").write_text("Closes #5\n" + "x" * MAX_BYTES, encoding="utf-8")
    assert _scan(tmp_path, ["tests/test_x.py", "big.md"]) == []


def test_every_exception_matches_at_least_one_tracked_file():
    tracked = _tracked()
    dead = [pattern for pattern in EXCEPTIONS if not any(fnmatch.fnmatchcase(rel, pattern) for rel in tracked)]
    assert dead == []
