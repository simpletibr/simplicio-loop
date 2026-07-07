"""stack_registry.py — load stack templates from simplicio/templates/stacks/.

A stack template is a directory with:
  stack.json       — metadata, versioning, deps, runners
  README.md        — human + planner context: what this stack is, when to use
  practices.md     — best-practices reference fed to the planner
  verify.json      — how the cli verify-loop runs tests + lint
  tree/            — files literally copied at scaffold time (placeholders
                     {project_name} and {goal} are rendered by executor)
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

_TREE_CACHE_DIRS = {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def _stacks_root() -> Path:
    """Resolve the stacks directory. Honors SIMPLICIO_STACKS_DIR for testing."""
    override = os.environ.get("SIMPLICIO_STACKS_DIR")
    if override:
        return Path(override)
    # package-relative path
    return Path(__file__).resolve().parent.parent / "templates" / "stacks"


@dataclass
class Stack:
    """A single stack template loaded from disk."""

    slug: str
    path: Path
    meta: dict = field(default_factory=dict)
    readme: str = ""
    practices: str = ""
    verify: dict = field(default_factory=dict)

    @property
    def language(self) -> str:
        return self.meta.get("language", "?")

    @property
    def framework(self) -> str:
        return self.meta.get("framework", "?")

    @property
    def version(self) -> str:
        return self.meta.get("template_version", "0.0.0")

    @property
    def test_command(self) -> str:
        return self.verify.get("test", "")

    @property
    def lint_command(self) -> str:
        return self.verify.get("lint", "")

    @property
    def install_command(self) -> str:
        return self.verify.get("install", "")

    def tree_files(self) -> Iterator[Path]:
        """Yield every file under tree/ recursively."""
        tree = self.path / "tree"
        if not tree.is_dir():
            return
        for p in tree.rglob("*"):
            if _is_ignored_tree_cache(p, tree):
                continue
            if p.is_file():
                yield p

    def render_tree(self, dest: Path, vars: dict) -> list[Path]:
        """Copy tree/ into dest, substituting {project_name} / {goal} / etc.
        Returns the list of files written."""
        written: list[Path] = []
        tree = self.path / "tree"
        if not tree.is_dir():
            return written
        for src in tree.rglob("*"):
            if _is_ignored_tree_cache(src, tree):
                continue
            rel = src.relative_to(tree)
            out = dest / rel
            if src.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            content = src.read_text(encoding="utf-8")
            # Substitute simple {name} placeholders. We do NOT use str.format
            # because tree files contain JSON / TS / curly braces that would
            # break naive formatting. Only known variables are substituted.
            for key, value in vars.items():
                content = content.replace("{" + key + "}", str(value))
            with out.open("w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
            written.append(out)
        return written


def _is_ignored_tree_cache(path: Path, tree: Path) -> bool:
    rel = path.relative_to(tree)
    return any(part in _TREE_CACHE_DIRS for part in rel.parts)


class StackRegistry:
    """Lazy registry: scans the stacks dir on first access."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _stacks_root()
        self._cache: dict[str, Stack] | None = None

    def _load(self) -> dict[str, Stack]:
        if self._cache is not None:
            return self._cache
        out: dict[str, Stack] = {}
        if not self.root.is_dir():
            self._cache = out
            return out
        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            meta_file = entry / "stack.json"
            if not meta_file.is_file():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                # Stack file with bad JSON should not crash the whole registry —
                # skip it but make the failure visible.
                print(f"[stack_registry] skipping {entry.name}: bad stack.json ({e})")
                continue
            slug = meta.get("slug") or entry.name
            stack = Stack(slug=slug, path=entry, meta=meta)
            readme = entry / "README.md"
            if readme.is_file():
                stack.readme = readme.read_text(encoding="utf-8")
            practices = entry / "practices.md"
            if practices.is_file():
                stack.practices = practices.read_text(encoding="utf-8")
            verify = entry / "verify.json"
            if verify.is_file():
                try:
                    stack.verify = json.loads(verify.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    stack.verify = {}
            out[slug] = stack
        self._cache = out
        return out

    def list(self) -> list[Stack]:
        return sorted(self._load().values(), key=lambda s: s.slug)

    def get(self, slug: str) -> Stack | None:
        return self._load().get(slug)

    def by_tags(self, tags: list[str]) -> list[Stack]:
        """Filter stacks whose tag set intersects with the given tags."""
        want = {t.lower() for t in tags}
        out = []
        for s in self.list():
            stack_tags = {t.lower() for t in s.meta.get("tags", [])}
            if stack_tags & want:
                out.append(s)
        return out


_SLUG_OK = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


def slugify_project(name: str) -> str:
    """Normalize a human project name to a safe directory name."""
    n = name.strip().lower()
    n = re.sub(r"[^a-z0-9]+", "-", n).strip("-")
    if not n:
        n = "scratch-project"
    if not _SLUG_OK.match(n):
        # truncate + ensure starts with letter
        n = ("p-" + n)[:41].rstrip("-")
    return n
