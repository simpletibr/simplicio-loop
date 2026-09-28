"""Turbo survey: one Mapper pass reused for every task in the run.

The DeepSeek harness cache rule (``request-cache.e2e.ts``) is separate and
lives in ``bench.llm_ab.report.run_prefix_cache_miss``. This module only
owns the Mapper stage: index once, then hand the same generation to each
later task.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

IndexFn = Callable[[Path], str]


def _default_index(root: Path) -> str:
    """Run the shipped Mapper index once and return a stable digest."""
    from .cli_impl import _ensure_project_map

    _ensure_project_map(root)
    project_map = root / ".simplicio-loop" / "project-map.json"
    payload = project_map.read_bytes() if project_map.is_file() else b""
    import hashlib
    return hashlib.sha256(payload).hexdigest()


def survey_tasks(
    root: Path,
    tasks: Sequence[Mapping[str, Any]],
    index: IndexFn | None = None,
) -> dict[str, Any]:
    """Survey ``root`` once and attach that generation to every task.

    A second call on an unchanged survey file does not call ``index`` again.
    """
    indexer = index or _default_index
    state_path = root / ".simplicio-loop" / "turbo-survey.json"
    if state_path.is_file():
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        generation = str(saved["generation"])
        indexed = False
    else:
        generation = str(indexer(root))
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"generation": generation}, ensure_ascii=False),
            encoding="utf-8",
        )
        indexed = True
    traces = [
        {"index": task.get("index"), "generation": generation, "reused": not indexed or i > 0}
        for i, task in enumerate(tasks)
    ]
    # The first task of a fresh survey is the one that paid for the index.
    if indexed and traces:
        traces[0]["reused"] = False
    return {
        "generation": generation,
        "indexed": indexed,
        "tasks": traces,
    }
