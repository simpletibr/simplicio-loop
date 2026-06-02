"""Load sprint task specs for ``simplicio-py run --scope sprint``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SprintTask:
    path: Path
    title: str
    goal: str


@dataclass
class SprintPlan:
    root: Path
    title: str
    tasks: list[SprintTask]


def load_sprint(root: str | Path, sprint: str) -> SprintPlan:
    repo = Path(root)
    sprint_dir = repo / ".specs" / "sprints" / sprint
    if not sprint_dir.is_dir():
        raise FileNotFoundError(f"sprint directory not found: {sprint_dir}")

    sprint_title = sprint
    sprint_md = sprint_dir / "SPRINT.md"
    if sprint_md.is_file():
        sprint_title = _first_heading(sprint_md.read_text(encoding="utf-8")) or sprint

    tasks = []
    for path in sorted(sprint_dir.glob("*.task.md")):
        text = path.read_text(encoding="utf-8")
        tasks.append(
            SprintTask(
                path=path,
                title=_first_heading(text) or path.stem,
                goal=_goal_from_task(text) or _body_after_first_heading(text) or text.strip(),
            )
        )
    return SprintPlan(root=sprint_dir, title=sprint_title, tasks=tasks)


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return None


def _goal_from_task(text: str) -> str | None:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().lower() in {"## goal", "## objetivo"}:
            body = []
            for next_line in lines[idx + 1 :]:
                if next_line.startswith("## "):
                    break
                if next_line.strip():
                    body.append(next_line.strip())
            return "\n".join(body).strip() or None
    return None


def _body_after_first_heading(text: str) -> str | None:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().startswith("#"):
            body = "\n".join(lines[idx + 1 :]).strip()
            return body or None
    return None
