"""Minimal Loop execution port used by the QLT-001 operational fixture."""

from __future__ import annotations

from dataclasses import dataclass


class LoopUnavailable(RuntimeError):
    """Raised when simplicio-loop cannot be started."""


@dataclass(frozen=True)
class LoopCommand:
    argv: tuple[str, ...]
    repository: str
    result_path: str
    task_path: str


class LoopInvoker:
    """Thin port: quality never owns scheduler, queue, worker pool or worktree."""

    def build_command(self, *, repository: str, task_path: str) -> LoopCommand:
        if not repository or not task_path:
            raise LoopUnavailable("repository and task_path are required")
        return LoopCommand(
            ("simplicio-loop", "run", "--task", task_path, "--repo", repository),
            repository,
            "run-outcome.json",
            task_path,
        )

    def run(self, command: LoopCommand) -> int:
        if command.argv[0] != "simplicio-loop":
            raise LoopUnavailable("only simplicio-loop may execute")
        return 0
