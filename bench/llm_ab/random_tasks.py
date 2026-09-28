"""Two tasks drawn at run time.

The harness owns the spec. Both arms receive the same task text. Turbo does
not add a solution.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

_FIELDS = (
    ("phone", "tel"),
    ("city", "text"),
    ("company", "text"),
    ("nickname", "text"),
    ("age", "number"),
)


def generate(n: int = 2, rng: random.Random | None = None) -> tuple[list[dict], list[dict]]:
    """Return ``n`` disjoint HTML tasks and the checker spec for those pages."""
    if n < 1:
        raise ValueError("n must be at least 1")
    draw = rng or random.SystemRandom()
    used: set[str] = set()
    tasks: list[dict] = []
    spec: list[dict] = []
    fields = list(_FIELDS)
    draw.shuffle(fields)
    for index in range(1, n + 1):
        while True:
            page = f"r{draw.randrange(1000, 10000)}"
            if page not in used:
                used.add(page)
                break
        name, kind = fields[(index - 1) % len(fields)]
        spec.append({"stage": index, "id": page, "name": name, "type": kind})
        sentence = (
            f"Create {page}.html: a pure HTML page with no JS framework and "
            f"no external CSS or JS. It needs a form whose id is {page}, a "
            f"labeled input whose name is {name} and whose type is {kind}, "
            "marked required, and a submit button."
        )
        tasks.append({
            "index": index,
            "kind": "create",
            "depends_on": [index - 1] if index > 1 else [],
            "target": f"{page}.html",
            "checker": "check_random.py",
            "text": sentence,
            "verify_stage": index,
        })
    return tasks, spec


def write_spec(spec: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
