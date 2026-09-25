"""Build a pending human-review packet for SkillOpt-generated skills.

Issue #32/#33 need real human approval evidence for SkillOpt skills. This
script does not approve anything. It collects review-gated ``SKILL.md`` files,
records stable hashes, and writes a JSON template that a human reviewer can
fill with ``reviewer``, ``approved``, ``reviewed_at``, and ``notes``. The same
JSON shape is accepted by ``bench/run_scratch_live_gate.py --skillopt-review-json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULTS_JSON = ROOT / "bench" / "results_skillopt_review_packet.json"
RESULTS_MD = ROOT / "bench" / "results_skillopt_review_packet.md"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---", re.DOTALL)
_FIELD_RE = re.compile(r"^(?P<key>[A-Za-z0-9_-]+):\s*(?P<value>.*?)\s*$")


def build_review_packet(
    *,
    skills_root: Path,
    min_reviews: int = 10,
    min_approval_rate: float = 0.80,
    generated_candidates: list[Path] | None = None,
    generation_failures: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    rows = [_review_row(path, skills_root) for path in _review_gated_skills(skills_root)]
    rows = [row for row in rows if row is not None]
    generated_candidates = generated_candidates or []
    generation_failures = generation_failures or []
    return {
        "benchmark": "skillopt-review-packet",
        "scope": (
            "pending human-review packet for SkillOpt-generated skills; this "
            "artifact intentionally does not count as approval evidence until "
            "a human fills reviewer and approved fields"
        ),
        "date": time.strftime("%Y-%m-%d"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "skills_root": str(skills_root),
        "review_policy": {
            "min_reviews": min_reviews,
            "min_approval_rate": min_approval_rate,
            "required_fields": [
                "skill",
                "path",
                "sha256",
                "reviewer",
                "approved",
                "reviewed_at",
            ],
        },
        "summary": {
            "review_gated_skills": len(rows),
            "pending_reviews": len(rows),
            "generated_candidates": len(generated_candidates),
            "candidate_generation_failures": len(generation_failures),
            "human_review_complete": False,
            "release_ready": False,
            "gate_command": (
                "python bench/run_scratch_live_gate.py "
                "--skillopt-review-json bench/results_skillopt_review_packet.json"
            ),
        },
        "generated_candidates": [_relative_path(path, ROOT) for path in generated_candidates],
        "generation_failures": generation_failures,
        "reviews": rows,
    }


def generate_review_candidates(
    goals: list[str],
    *,
    skills_root: Path,
    planner: str | None = None,
) -> tuple[list[Path], list[dict[str, str]]]:
    from simplicio.scratch import skill_opt

    generated = []
    failures = []
    for goal in goals:
        description = goal.strip()
        if not description:
            continue
        try:
            generated.append(
                skill_opt.install_skill_from_description(
                    description,
                    skills_root=skills_root,
                    planner_model=planner,
                )
            )
        except Exception as exc:
            failures.append({"description": description, "error": str(exc)})
    return generated, failures


def load_candidate_goals(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("goals", [])
        if not isinstance(data, list):
            raise ValueError("candidate goals JSON must be a list or {'goals': [...]}")
        return [str(item).strip() for item in data if str(item).strip()]
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def _review_gated_skills(skills_root: Path) -> list[Path]:
    if not skills_root.is_dir():
        return []
    paths = []
    for path in sorted(skills_root.glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        if _is_skillopt_review_candidate(_frontmatter(text)):
            paths.append(path)
    return paths


def _review_row(path: Path, skills_root: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8")
    frontmatter = _frontmatter(text)
    if not _is_skillopt_review_candidate(frontmatter):
        return None
    skill = frontmatter.get("name") or path.parent.name
    if not skill:
        return None
    return {
        "skill": skill,
        "path": _relative_path(path, ROOT),
        "skill_md": _relative_path(path, ROOT),
        "skills_root_path": _relative_path(path, skills_root),
        "sha256": _stable_skill_hash(path),
        "review_required": True,
        "source_goal": frontmatter.get("source_goal", frontmatter.get("auto_generated.source_goal", "")),
        "planner_model": frontmatter.get(
            "planner_model", frontmatter.get("auto_generated.planner_model", "")
        ),
        "reviewer": "",
        "approved": None,
        "reviewed_at": "",
        "notes": "",
    }


def _stable_skill_hash(path: Path) -> str:
    """Hash review artifacts independently of checkout line endings."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _is_skillopt_review_candidate(frontmatter: dict[str, str]) -> bool:
    return (
        frontmatter.get("review_required", frontmatter.get("auto_generated.review_required", "")).lower()
        == "true"
        and frontmatter.get("by", frontmatter.get("auto_generated.by")) == "skill-opt"
        and bool(frontmatter.get("source_goal", frontmatter.get("auto_generated.source_goal")))
        and bool(frontmatter.get("planner_model", frontmatter.get("auto_generated.planner_model")))
    )


def _frontmatter(text: str) -> dict[str, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    current_section = ""
    for line in match.group("body").splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if stripped.endswith(":") and indent == 0:
            current_section = stripped[:-1]
            continue
        parsed = _FIELD_RE.match(stripped)
        if parsed:
            key = parsed.group("key")
            if indent > 0 and current_section:
                key = f"{current_section}.{key}"
            fields[key] = parsed.group("value").strip('"')
    return fields


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def write_reports(packet: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_to_markdown(packet), encoding="utf-8")


def _to_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    policy = packet["review_policy"]
    lines = [
        "# SkillOpt Human Review Packet",
        "",
        packet["scope"],
        "",
        "## Summary",
        "",
        f"- review gated skills: {summary['review_gated_skills']}",
        f"- pending reviews: {summary['pending_reviews']}",
        f"- generated candidates: {summary['generated_candidates']}",
        f"- candidate generation failures: {summary['candidate_generation_failures']}",
        f"- human review complete: {summary['human_review_complete']}",
        f"- release ready: {summary['release_ready']}",
        f"- minimum reviews: {policy['min_reviews']}",
        f"- minimum approval rate: {policy['min_approval_rate']:.0%}",
        "",
        "## How To Complete",
        "",
        "Fill `reviewer`, `approved`, `reviewed_at`, and `notes` in the JSON.",
        "`approved` must be a real boolean, not a string. Then rerun the live gate",
        "with `--skillopt-review-json`.",
        "",
        "## Pending Reviews",
        "",
        "| skill | path | sha256 |",
        "| --- | --- | --- |",
    ]
    for row in packet["reviews"]:
        lines.append(f"| {row['skill']} | `{row['path']}` | `{row['sha256'][:12]}` |")
    if packet.get("generation_failures"):
        lines.extend(["", "## Generation Failures", ""])
        for failure in packet["generation_failures"]:
            lines.append(f"- {failure.get('description', '')}: {failure.get('error', '')}")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path, default=ROOT / ".skills")
    parser.add_argument(
        "--candidate-goal",
        "--description",
        dest="candidate_goal",
        action="append",
        default=[],
        help="Generate one review-gated SkillOpt candidate before building the packet.",
    )
    parser.add_argument(
        "--candidate-goals-file",
        "--descriptions-file",
        dest="candidate_goals_file",
        type=Path,
        help="Text or JSON file of candidate skill descriptions to generate.",
    )
    parser.add_argument("--planner", help="Planner model override for candidate generation.")
    parser.add_argument("--json-output", type=Path, default=RESULTS_JSON)
    parser.add_argument("--md-output", type=Path, default=RESULTS_MD)
    parser.add_argument("--min-reviews", type=int, default=10)
    parser.add_argument("--min-approval-rate", type=float, default=0.80)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    goals = list(args.candidate_goal)
    if args.candidate_goals_file:
        goals.extend(load_candidate_goals(args.candidate_goals_file))
    generated_candidates: list[Path] = []
    generation_failures: list[dict[str, str]] = []
    if goals:
        generated_candidates, generation_failures = generate_review_candidates(
            goals,
            skills_root=args.skills_root,
            planner=args.planner,
        )
        for failure in generation_failures:
            print(
                "skillopt review packet: failed to generate candidate "
                f"{failure['description']!r}: {failure['error']}",
                file=sys.stderr,
            )
    packet = build_review_packet(
        skills_root=args.skills_root,
        min_reviews=args.min_reviews,
        min_approval_rate=args.min_approval_rate,
        generated_candidates=generated_candidates,
        generation_failures=generation_failures,
    )
    write_reports(packet, args.json_output, args.md_output)
    if not args.quiet:
        print(json.dumps(packet["summary"], indent=2, sort_keys=True))
        print(f"wrote {args.json_output}")
        print(f"wrote {args.md_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
