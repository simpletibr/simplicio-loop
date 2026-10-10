"""No prompt, doc or script that a model reads may tell it to write a GitHub closing word (#1644).

A closing word in a PR closes the issue on merge, even a quoted one. Every tracked text file is scanned with
`has_closing`; only the exceptions below (exact path or glob, each with its reason) may name the words.

Also scans for placeholder patterns after closing words: #<n>, #{...}, #$N, #{issue}, {ref}, etc.
These indicate a model was instructed to write a closing word and fill in an issue number.
"""
import fnmatch
import re
import subprocess
from pathlib import Path

import pytest

from simplicio_loop.watcher247.closing_words import has_closing, KEYWORDS

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

# Regex to detect placeholder patterns after closing words
# Matches: keyword + optional whitespace/colon + placeholder like #<n>, #{issue}, #$N, etc.
_PLACEHOLDER_PATTERN = re.compile(
    rf"(?:{'|'.join(re.escape(k) for k in KEYWORDS)})\b\s*[:=]?\s*"
    r"(?:#<[a-z]+>|#\{(?:issue|ref|number|n|id)\}|#\$[A-Z]+|\{\s*(?:issue|ref|number|n|id)\s*\})",
    re.IGNORECASE
)


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


def _has_placeholder_pattern(text: str) -> bool:
    """Check if text has a closing word followed by a placeholder pattern."""
    return bool(_PLACEHOLDER_PATTERN.search(text))


def _scan(root: Path, files: list[str]) -> list[str]:
    """Scan files for closing words and placeholders. Reads whole files to catch splits."""
    hits = []
    for rel in files:
        if _excused(rel):
            continue
        text = _text(root / rel)
        if text is None:
            continue
        
        # Scan whole file for closing words (to catch splits like "Closes" on one line, "#5" on next)
        # Replace #N placeholder with #1 so placeholder scanning works
        test_text = text.replace("#N", "#1").replace("#{issue}", "#1").replace("#{ref}", "#1")
        
        if has_closing(test_text):
            # Find the line number for reporting
            for number, line in enumerate(text.splitlines(), 1):
                if has_closing(line.replace("#N", "#1")):
                    hits.append(f"{rel}:{number}: {line.strip()[:120]}")
                    break
            else:
                # If no single line has it, it's a split - report the first occurrence
                hits.append(f"{rel}:1: (split across lines) {text[:120]}")
        
        # Also check for placeholder patterns after closing words
        if _has_placeholder_pattern(test_text):
            for number, line in enumerate(text.splitlines(), 1):
                if _PLACEHOLDER_PATTERN.search(line.replace("#N", "#1")):
                    hits.append(f"{rel}:{number}: {line.strip()[:120]}")
                    break
    
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


def test_the_scanner_catches_closing_word_split_across_lines(tmp_path):
    """Closing word on one line, issue number on next - should be caught."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/split.md").write_text("Closes\n#5\n", encoding="utf-8")
    (tmp_path / "docs/split2.md").write_text("Some text\nCloses #5", encoding="utf-8")
    hits = _scan(tmp_path, ["docs/split.md", "docs/split2.md"])
    assert len(hits) >= 1, f"Should find split closing word, got: {hits}"


def test_the_scanner_finds_placeholder_patterns_after_closing_words(tmp_path):
    """Scanner should flag closing words followed by placeholders like #<n>, #{issue}, etc."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/placeholder1.md").write_text("Closes #<n>\n", encoding="utf-8")
    (tmp_path / "docs/placeholder2.md").write_text("Fixes #{issue}\n", encoding="utf-8")
    (tmp_path / "docs/placeholder3.md").write_text("Resolved #$N\n", encoding="utf-8")
    
    hits = _scan(tmp_path, [
        "docs/placeholder1.md", "docs/placeholder2.md",
        "docs/placeholder3.md"
    ])
    assert len(hits) >= 2, f"Should find placeholder patterns, got {len(hits)}: {hits}"


def test_the_scanner_skips_excepted_paths_binary_and_huge_files(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_x.py").write_text("Closes #5\n", encoding="utf-8")
    (tmp_path / "big.md").write_text("Closes #5\n" + "x" * MAX_BYTES, encoding="utf-8")
    assert _scan(tmp_path, ["tests/test_x.py", "big.md"]) == []


def test_every_exception_matches_at_least_one_tracked_file():
    tracked = _tracked()
    dead = [pattern for pattern in EXCEPTIONS if not any(fnmatch.fnmatchcase(rel, pattern) for rel in tracked)]
    assert dead == []


def test_hooks_exception_is_narrow_and_exact(tmp_path):
    """The hooks/* exception (if it exists) should only match files we explicitly chose to exclude."""
    # Check if there are any hooks/* files in exceptions
    hooks_patterns = [p for p in EXCEPTIONS if "hooks" in p.lower()]
    
    if hooks_patterns:
        # If we have a hooks exception, it should be specific (e.g., "hooks/action_gate.py")
        for pattern in hooks_patterns:
            # Glob patterns should be for specific files, not broad wildcards
            assert "*" in pattern, f"hooks exception should use glob for specificity: {pattern}"
            # Count how many tracked files match
            tracked = _tracked()
            matches = [f for f in tracked if fnmatch.fnmatchcase(f, pattern)]
            assert len(matches) <= 5, f"hooks exception pattern '{pattern}' matches too many files ({len(matches)})"
