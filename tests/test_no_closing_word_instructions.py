"""No prompt or doc that a model reads may tell it to write a GitHub closing word (#1644).

A closing word in a PR closes the issue on merge, even a quoted one. Only the files that must name the words
on purpose are allowed, by exact path.
"""
from pathlib import Path

from simplicio_loop.watcher247.closing_words import has_closing

ROOT = Path(__file__).resolve().parents[1]

FILES = (
    "packaging/host-rules/simplicio-loop-operator-flow.md",
    "simplicio_loop/_bundle/host-rules/simplicio-loop-operator-flow.md",
    "docs/GUIDE.md",
    "docs/LLM_MAX_SPEED_ORIENTATION.md",
    "docs/flow/simplicio-loop.mmd",
    "docs/flow/simplicio-loop.flow.json",
    "docs/flow/langflow/simplicio-loop.langflow.json",
    "docs/flow/simplicio-loop.svg",
)
TREES = ("packaging/host-rules", "simplicio_loop/_bundle/skills", "simplicio_loop/_bundle/host-rules", "docs/flow")
ALLOWED = frozenset({"simplicio_loop/watcher247/closing_words.py", "CHANGELOG.md"})
ALLOWED_PREFIXES = ("tests/", "docs/adr/")


def _sources():
    found = {ROOT / name for name in FILES}
    for tree in TREES:
        found.update((ROOT / tree).rglob("*.md"))
    return sorted(found)


def _hits():
    hits = []
    for path in _sources():
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED or rel.startswith(ALLOWED_PREFIXES):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if has_closing(line.replace("#N", "#1")):  # `#N` is the placeholder a model is told to fill in
                hits.append(f"{rel}:{number}: {line.strip()[:120]}")
    return hits


def test_sources_exist():
    assert all(path.is_file() for path in _sources())


def test_no_prompt_or_doc_tells_a_model_to_write_a_closing_word():
    assert _hits() == []
