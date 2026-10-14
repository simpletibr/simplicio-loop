#!/usr/bin/env python3
"""Immutable contract headers + "What the model sees" sections (issue #1342).

Every contract document loaded into an LLM prefix starts with one canonical,
immutable header (after the YAML frontmatter, when the file has one):

    <!-- simplicio-contract:begin -->
    contract: <name>
    schema: <stable schema id>
    purpose: <invariant one-paragraph purpose>
    rules: <invariant rules>
    <!-- simplicio-contract:end -->

No versions, dates, counts, run ids or release trains in the header or the
frontmatter: they change on every release and break the prompt cache for
everything after them. Header bytes are pinned in
``contracts/headers.lock.json``; a change needs a ``header-change: <path>``
line in CHANGELOG.md.

Usage: contract_headers.py [--check] [--lock]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(ROOT, "contracts", "headers.lock.json")
BEGIN = "<!-- simplicio-contract:begin -->"
END = "<!-- simplicio-contract:end -->"
HEADER_KEYS = ("contract", "schema", "purpose", "rules")

CONTRACT_GLOBS = (
    ".claude/skills/*/SKILL.md",
    ".claude/skills/*/references/*.md",
    "AGENTS.md",
    "bench/llm_ab/STANDARD.md",
    "contracts/**/*.md",
)
MODEL_SEES_FILES = ("docs/GUIDE.md", "packages/mapper/README.md", "packages/dev-cli/README.md")
MODEL_SEES_GLOBS = (".claude/skills/*/SKILL.md",)
MODEL_SEES_HEADINGS = ("What the model sees", "Token effect", "KV cache effect")

VOLATILE_PATTERNS = (
    ("semver", re.compile(r"\bv?\d+\.\d+\.\d+\b")),
    ("iso_date", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    ("release_train", re.compile(r"\b(?:Mapper|Loop|dev-cli|Fast|Runtime)\s+v?0\.\d+", re.I)),
    ("count", re.compile(r"\b\d+\s+(?:tests?|skills?|runtimes?|issues?|files?|arms?|releases?)\b", re.I)),
    ("run_id", re.compile(r"\brun-\d{8}-\d{6}")),
)


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def contract_files(root: str = ROOT) -> list[str]:
    found: set[str] = set()
    for pattern in CONTRACT_GLOBS:
        found.update(glob.glob(os.path.join(root, pattern), recursive=True))
    return sorted(path for path in found if "/fixtures/" not in path.replace(os.sep, "/"))


def model_sees_files(root: str = ROOT) -> list[str]:
    found = {os.path.join(root, rel) for rel in MODEL_SEES_FILES}
    for pattern in MODEL_SEES_GLOBS:
        found.update(glob.glob(os.path.join(root, pattern)))
    return sorted(found)


def split_frontmatter(text: str) -> tuple[str, str]:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[: end + 5], text[end + 5:]
    return "", text


def extract_header(text: str) -> str | None:
    """The header block, which must be the first thing after the frontmatter."""
    _, body = split_frontmatter(text)
    body = body.lstrip("\n")
    if not body.startswith(BEGIN):
        return None
    end = body.find(END)
    if end == -1:
        return None
    return body[: end + len(END)]


def header_problems(text: str) -> list[str]:
    header = extract_header(text)
    if header is None:
        return ["missing_header"]
    problems = []
    lines = header.splitlines()[1:-1]
    keys = [line.split(":", 1)[0].strip() for line in lines if ":" in line]
    for key in HEADER_KEYS:
        if key not in keys:
            problems.append(f"missing_key:{key}")
    frontmatter, _ = split_frontmatter(text)
    for name, pattern in VOLATILE_PATTERNS:
        if pattern.search(header) or pattern.search(frontmatter):
            problems.append(f"volatile:{name}")
    return problems


def model_sees_problems(text: str) -> list[str]:
    return [
        f"missing_section:{heading}" for heading in MODEL_SEES_HEADINGS
        if not re.search(r"^#{2,4}\s+" + re.escape(heading) + r"\b", text, re.M)
    ]


def header_digest(text: str) -> str:
    header = extract_header(text) or ""
    frontmatter, _ = split_frontmatter(text)
    return hashlib.sha256((frontmatter + header).encode("utf-8")).hexdigest()


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def check(root: str = ROOT, lock_path: str | None = None, changelog: str | None = None) -> list[str]:
    lock_path = lock_path or os.path.join(root, "contracts", "headers.lock.json")
    changelog = changelog or os.path.join(root, "CHANGELOG.md")
    errors: list[str] = []
    lock = json.loads(_read(lock_path)) if os.path.isfile(lock_path) else {}
    notes = _read(changelog) if os.path.isfile(changelog) else ""
    for path in contract_files(root):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        text = _read(path)
        errors.extend(f"{rel}: {problem}" for problem in header_problems(text))
        pinned = lock.get(rel)
        if pinned and pinned != header_digest(text) and f"header-change: {rel}" not in notes:
            errors.append(f"{rel}: header_changed_without_note")
    for path in model_sees_files(root):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        if not os.path.isfile(path):
            errors.append(f"{rel}: missing_file")
            continue
        errors.extend(f"{rel}: {problem}" for problem in model_sees_problems(_read(path)))
    return errors


def write_lock(root: str = ROOT) -> dict[str, str]:
    lock = {
        os.path.relpath(path, root).replace(os.sep, "/"): header_digest(_read(path))
        for path in contract_files(root)
    }
    with open(os.path.join(root, "contracts", "headers.lock.json"), "w", encoding="utf-8") as handle:
        json.dump(lock, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return lock


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lock", action="store_true", help="re-pin every header digest")
    args = ap.parse_args(argv)
    if args.lock:
        write_lock()
    errors = check()
    for error in errors:
        print(error)
    print("contract-headers: %s (%d problem(s))" % ("PASS" if not errors else "FAIL", len(errors)))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
