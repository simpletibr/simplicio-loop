"""run_toon_ab.py — A/B token measurement for TOON on the mapper context path.

Closes the AC3 gap left by #85/PR #87 and asked for explicitly by #88: run
`SIMPLICIO_PROMPT_TOON=1` vs `=0` over the tasks in `bench/cases.json` and
commit the numbers, labeling the tokenizer used.

Method (honest about what this measures — see #88's own finding that the
merged TOON branch was DEAD on the real handoff path until this PR):
  - Drives the real, unmodified `simplicio.mapper.build_mapper_context()`
    for each case in `bench/cases.json`, toggling `SIMPLICIO_PROMPT_TOON`
    around each call — the exact function `simplicio/prompt.py::build_prompt`
    calls for every real task, both on the mapper 0.13+ `handoff` path (the
    one that was dead) and the project-map fallback path.
  - `bench/cases.json` does not ship a `simplicio-mapper` artifact (no
    `.simplicio/project-map.json`, no live `handoff` binary in this sandbox),
    so `map_handoff` is monkeypatched to return a synthetic context-pack
    shaped exactly like the `simplicio.map-handoff/v1` schema
    (`_render_handoff_context`'s tests use the same shape) with the case's
    `target` as the file entry — representative of what `simplicio-mapper`
    emits, not a live capture. This isolates "does the TOON gate actually
    fire and save tokens on the handoff path" (#88's core bug) from "is the
    mapper binary installed" (an orthogonal, environment-dependent fact).
  - Token counts use the single canonical estimator
    (`simplicio.observability.estimate_tokens`, issue #88 AC4) on both
    sides — never two different formulas being compared against each other.

Usage: python3 bench/run_toon_ab.py
Writes bench/results_toon_ab.json and bench/results_toon_ab.md.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simplicio import mapper  # noqa: E402
from simplicio.observability import ESTIMATOR_LABEL, estimate_tokens  # noqa: E402

CASES_PATH = ROOT / "bench" / "cases.json"
RESULTS_JSON = ROOT / "bench" / "results_toon_ab.json"
RESULTS_MD = ROOT / "bench" / "results_toon_ab.md"


def _synthetic_handoff_pack(target: str) -> dict:
    """A representative (not live-captured) `simplicio.map-handoff/v1`
    context_pack for `target`, shaped like the schema `_render_handoff_
    context` consumes and the mapper-integration tests already fixture."""
    stem = Path(target).stem
    return {
        "schema": "simplicio.map-handoff/v1",
        "context_pack": {
            "pack_hash": f"synthetic-{stem}",
            "needs_broader_context": False,
            "dependencies": {"runtime": ["@angular/core", "@angular/common", "rxjs"]},
            "files": [
                {
                    "path": target,
                    "language": "typescript" if target.endswith((".ts", ".tsx")) else "html",
                    "symbols": [
                        {"name": f"{stem}Component", "kind": "class"},
                        {"name": "ngOnInit", "kind": "method"},
                        {"name": "canView", "kind": "method"},
                    ],
                    "imports": ["@angular/core", "@angular/common", "../auth/permission.service"],
                },
                {
                    "path": target.replace(".component.html", ".component.ts"),
                    "language": "typescript",
                    "symbols": [{"name": f"{stem}Component", "kind": "class"}],
                    "imports": ["@angular/core", "../auth/permission.service"],
                },
            ],
            "recent_changes": [{"path": target, "status": "modified"}],
        },
    }


def _run_case(case: dict, tmp_root: str) -> dict:
    target = case["target"]
    pack = _synthetic_handoff_pack(target)

    original_map_handoff = mapper.map_handoff
    mapper.map_handoff = lambda _root: pack
    try:
        os.environ["SIMPLICIO_PROMPT_TOON"] = "0"
        legacy_context = mapper.build_mapper_context(tmp_root, target, goal=case["goal"])
        os.environ["SIMPLICIO_PROMPT_TOON"] = "1"
        toon_context = mapper.build_mapper_context(tmp_root, target, goal=case["goal"])
    finally:
        mapper.map_handoff = original_map_handoff
        os.environ.pop("SIMPLICIO_PROMPT_TOON", None)

    legacy_tokens = estimate_tokens(legacy_context)
    toon_tokens = estimate_tokens(toon_context)
    saved = legacy_tokens - toon_tokens
    return {
        "goal": case["goal"],
        "target": target,
        "legacy_tokens": legacy_tokens,
        "toon_tokens": toon_tokens,
        "saved_tokens": saved,
        "pct_saved": round(100 * saved / legacy_tokens, 2) if legacy_tokens else 0.0,
    }


def main() -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="simplicio-toon-ab-") as tmp_root:
        rows = [_run_case(c, tmp_root) for c in cases]
    total_legacy = sum(r["legacy_tokens"] for r in rows)
    total_toon = sum(r["toon_tokens"] for r in rows)
    total_saved = total_legacy - total_toon
    pct = round(100 * total_saved / total_legacy, 2) if total_legacy else 0.0

    payload = {
        "schema": "simplicio.toon-ab-bench/v1",
        "cases_source": "bench/cases.json",
        "estimator": ESTIMATOR_LABEL,
        "method": (
            "build_mapper_context() driven end-to-end with SIMPLICIO_PROMPT_TOON=0/1, "
            "map_handoff() monkeypatched to a representative (non-live-captured) "
            "simplicio.map-handoff/v1 pack per case target — isolates the handoff-path "
            "TOON gate fixed in #88 from mapper-binary availability."
        ),
        "rows": rows,
        "totals": {
            "legacy_tokens": total_legacy,
            "toon_tokens": total_toon,
            "saved_tokens": total_saved,
            "pct_saved": pct,
        },
    }
    RESULTS_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# TOON A/B — mapper context path (issue #85 AC3 / #88 AC2)",
        "",
        f"Estimator: `{ESTIMATOR_LABEL}` (issue #88 AC4 — single canonical estimator).",
        "",
        payload["method"],
        "",
        "| Case | Target | Legacy tokens | TOON tokens | Saved | % saved |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['goal'][:48]} | {r['target']} | {r['legacy_tokens']} | "
            f"{r['toon_tokens']} | {r['saved_tokens']} | {r['pct_saved']}% |"
        )
    lines.append(
        f"| **Total** |  | **{total_legacy}** | **{total_toon}** | "
        f"**{total_saved}** | **{pct}%** |"
    )
    RESULTS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n-> {RESULTS_JSON}")
    print(f"-> {RESULTS_MD}")


if __name__ == "__main__":
    main()
