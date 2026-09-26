"""Mapper survey provenance shared by every mutating flow (issue #1318;
issue #1343 removed simplicio-fast from the stack entirely -- Mapper is now
the sole survey operator).

`orient` (plain and `--brief`) records which Mapper generation it produced
in `.simplicio-loop/survey.json`; `apply` (hot path) and `prepare` (wave)
refuse to run without it, so no flow can mutate a repo that Mapper has not
surveyed.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .state_dir import ensure_state_dir

SURVEY_FILE = "survey.json"
PROJECT_MAP = "project-map.json"
SURVEY_OPERATORS = frozenset({"simplicio-mapper"})
MISSING_REASON = "mapper_provenance_missing"
MISSING_HINT = ("run `simplicio-loop orient --brief --repo . --task ...` first "
                "(Mapper survey); nothing was written")


def write_survey(root: Path, generations: Sequence[Mapping[str, Any]]) -> Path:
    path = ensure_state_dir(root) / SURVEY_FILE
    path.write_text(json.dumps({"generations": [dict(g) for g in generations]},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def provenance(root: Path, generations: Any = None) -> dict[str, Any] | None:
    """The Mapper survey bound to this run, or ``None`` when missing.

    Requires the Mapper project map under `.simplicio-loop/` and, per task
    generation (``generations`` if given, else `survey.json`), the Mapper
    operator."""
    state = Path(root) / ".simplicio-loop"
    if not (state / PROJECT_MAP).is_file():
        return None
    if not generations:
        try:
            generations = json.loads((state / SURVEY_FILE).read_text(encoding="utf-8")).get("generations")
        except (OSError, ValueError, AttributeError):
            return None
    if not isinstance(generations, list) or not generations:
        return None
    for entry in generations:
        if not isinstance(entry, Mapping) or entry.get("operator") not in SURVEY_OPERATORS:
            return None
    return {"project_map": f".simplicio-loop/{PROJECT_MAP}", "generations": [dict(e) for e in generations]}
