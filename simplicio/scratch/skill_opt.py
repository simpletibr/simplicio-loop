"""skill_opt.py — generate a new .skills/<slug>/SKILL.md from a description.

Used both standalone (`simplicio-py skill new "<desc>"`) and inline from
executor.py when a plan task needs a capability not yet represented in
`.skills/`. Always writes the generated skill with `review_required: true`
in the frontmatter, so a human gate-keeps before it becomes a default.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

from ..providers import planner_complete


def _skills_root() -> Path:
    override = os.environ.get("SIMPLICIO_SKILLS_DIR")
    if override:
        return Path(override)
    cwd_skills = Path.cwd() / ".skills"
    if cwd_skills.is_dir():
        return cwd_skills
    # walk up looking for an existing .skills
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / ".skills"
        if candidate.is_dir():
            return candidate
    return cwd_skills  # will be created


SKILL_GEN_SYSTEM = """You generate skill manifests for the simplicio agent system.

Output ONLY a single Markdown document. No prose framing. No code fences
around the WHOLE document. Internal fenced code blocks are fine.

The document MUST start with a YAML frontmatter block and contain these
sections in order:

  ---
  name: <kebab-case-slug>
  description: <one sentence, <120 chars>
  trigger: <when this skill applies, plain prose>
  auto_generated:
    by: skill-opt
    date: <YYYY-MM-DD>
    source_goal: <verbatim user request>
    planner_model: <model id used to generate this skill>
    review_required: true
  ---

  # <Title — match the name>

  ## When to use
  …

  ## Steps
  1. …
  2. …

  ## DoD
  - [ ] …

  ## Anti-patterns
  - …

Do not invent extra top-level sections. Do not add tools/permissions blocks."""


SKILL_GEN_TEMPLATE = """{system}

[USER REQUEST]
{description}

[EXISTING SKILLS — do not duplicate]
{existing}

[REQUIRED FRONTMATTER FIELDS]
date={date}
planner_model={planner_model}
source_goal={description}

Now produce the SKILL.md document."""


_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


class SkillOptError(RuntimeError):
    pass


def _list_existing_skills(skills_root: Path) -> list[str]:
    if not skills_root.is_dir():
        return []
    out = []
    for entry in sorted(skills_root.iterdir()):
        if entry.is_dir() and not entry.name.startswith("_"):
            out.append(entry.name)
    return out


def _extract_slug(text: str) -> Optional[str]:
    """Pull the `name:` field out of the YAML frontmatter."""
    m = re.search(r"^name:\s*([a-z][a-z0-9-]{1,40})\s*$", text, re.MULTILINE)
    if not m:
        return None
    return m.group(1)


def _has_review_gate(text: str) -> bool:
    return bool(re.search(r"review_required:\s*true", text))


def generate_skill_doc(
    description: str,
    skills_root: Optional[Path] = None,
    planner_model: Optional[str] = None,
) -> tuple[str, str]:
    """Generate the SKILL.md content. Returns (slug, full markdown)."""
    root = skills_root or _skills_root()
    existing = _list_existing_skills(root)
    pm = planner_model or os.environ.get(
        "SIMPLICIO_PLANNER", "deepseek/deepseek-v4-pro"
    )

    prompt = SKILL_GEN_TEMPLATE.format(
        system=SKILL_GEN_SYSTEM,
        description=description.strip(),
        existing="\n".join(f"- {e}" for e in existing) or "(none)",
        date=time.strftime("%Y-%m-%d"),
        planner_model=pm,
    )

    text = planner_complete(prompt)
    if not text:
        raise SkillOptError("planner returned empty response")

    slug = _extract_slug(text)
    if not slug:
        raise SkillOptError(
            "generated SKILL.md is missing a valid `name:` frontmatter field"
        )
    if not _has_review_gate(text):
        raise SkillOptError(
            "generated SKILL.md is missing `review_required: true` gate — "
            "rejected to protect .skills/ from un-reviewed defaults"
        )
    if slug in existing:
        raise SkillOptError(
            f"skill '{slug}' already exists; pick a different angle or "
            f"reference the existing one"
        )

    return slug, text


def install_skill(slug: str, markdown: str, skills_root: Optional[Path] = None) -> Path:
    """Write the generated SKILL.md to disk and return its path."""
    root = skills_root or _skills_root()
    root.mkdir(parents=True, exist_ok=True)
    target_dir = root / slug
    if target_dir.exists():
        raise SkillOptError(f"target directory already exists: {target_dir}")
    target_dir.mkdir()
    skill_md = target_dir / "SKILL.md"
    skill_md.write_text(markdown, encoding="utf-8")
    return skill_md


def install_skill_from_description(
    description: str,
    skills_root: Optional[Path] = None,
    planner_model: Optional[str] = None,
) -> Path:
    """Generate and install one review-gated skill from a plain description."""

    slug, markdown = generate_skill_doc(
        description,
        skills_root=skills_root,
        planner_model=planner_model,
    )
    return install_skill(slug, markdown, skills_root=skills_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simplicio-py skill new")
    parser.add_argument(
        "description", help="what the skill should do (one or two sentences)"
    )
    parser.add_argument(
        "--planner", default=None, help="override SIMPLICIO_PLANNER for this run"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the generated SKILL.md but do not write it",
    )
    args = parser.parse_args(argv)

    if args.planner:
        os.environ["SIMPLICIO_PLANNER"] = args.planner

    try:
        slug, doc = generate_skill_doc(args.description)
    except SkillOptError as e:
        print(f"[skill-opt] {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(doc)
        return 0

    try:
        path = install_skill(slug, doc)
    except SkillOptError as e:
        print(f"[skill-opt] {e}", file=sys.stderr)
        return 3
    print(f"[skill-opt] installed at {path}", file=sys.stderr)
    print(
        "[skill-opt] frontmatter has review_required: true — review it "
        "before relying on it.",
        file=sys.stderr,
    )
    return 0
