#!/usr/bin/env python3
"""Generate the Mermaid, SVG and Langflow artifacts from docs/flow/simplicio-loop.flow.json.

Usage: python3 scripts/flow_gen.py [generate|check]   (check = fail when artifacts are stale)
       python3 scripts/flow_gen.py run --progress <progress.json> --out <run.mmd>   (per-run diagram from real state)
Renders SVG with the mermaid CLI (mmdc) when present; otherwise prints `blocked` and exits 3.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOW_DIR = ROOT / "docs" / "flow"
FLOW = FLOW_DIR / "simplicio-loop.flow.json"
SHAPES = {"input": ("([", "])"), "output": ("[[", "]]"), "gate": ("{", "}"), "step": ("[", "]")}


def load() -> dict:
    return json.loads(FLOW.read_text(encoding="utf-8"))


def to_mermaid(flow: dict) -> str:
    lines = ["flowchart TD"]
    for n in flow["nodes"]:
        o, c = SHAPES[n["kind"]]
        lines.append(f'    {n["id"]}{o}"{n["label"]}"{c}')
    for e in flow["edges"]:
        arrow = f' -->|{e[2]}| ' if len(e) > 2 else " --> "
        lines.append(f"    {e[0]}{arrow}{e[1]}")
    return "\n".join(lines) + "\n"


def to_langflow(flow: dict) -> str:
    nodes = []
    for i, n in enumerate(flow["nodes"]):
        nxt = ", ".join(e[1] for e in flow["edges"] if e[0] == n["id"])
        nodes.append({
            "id": n["id"], "type": "noteNode", "width": 240, "height": 110,
            "position": {"x": 260 * (i % 6), "y": 160 * (i // 6)},
            "data": {"id": n["id"], "type": "note",
                     "node": {"display_name": n["label"], "description": f'{n["kind"]} · {n["source"]}' + (f" · next: {nxt}" if nxt else ""),
                              "documentation": "", "template": {}}},
        })
    # note nodes have no handles: handle-less edges make the Langflow canvas render nothing,
    # so the edge order is carried in each note's description ("next: ...") instead.
    edges: list = []
    doc = {"name": flow["title"], "description": f'Generated from {FLOW.name} ({flow["schema"]})',
           "data": {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.6}}}
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


# progress step (loop_progress.STEPS order) -> flow nodes it covers
STEP_NODES = {
    "preflight": ["preflight"], "survey": ["survey"], "triage": ["backlog", "anchor"],
    "decide": ["turbo"], "operate": ["apply", "strict", "human"], "watcher": ["claim"],
    "journal": ["journal"], "evidence": ["pr", "merge"], "refeed_exit": ["promise", "stop"],
}
STEP_ORDER = list(STEP_NODES)
RUN_CLASSES = ("classDef done fill:#c8e6c9,stroke:#2e7d32", "classDef running fill:#fff59d,stroke:#f9a825",
               "classDef pending fill:#eeeeee,stroke:#9e9e9e")


def to_run_mermaid(flow: dict, snap: dict) -> str:
    """Flow diagram colored by the real run state (loop_progress snapshot); no state -> uncolored."""
    lines = to_mermaid(flow).rstrip("\n").split("\n")
    step = snap.get("step")
    if step in STEP_ORDER:
        cur = STEP_ORDER.index(step)
        groups: dict[str, list[str]] = {"done": [], "running": [], "pending": []}
        for i, name in enumerate(STEP_ORDER):
            groups["done" if i < cur else "running" if i == cur else "pending"].extend(STEP_NODES[name])
        known = {n["id"] for n in flow["nodes"]}
        lines.extend(RUN_CLASSES)
        for state, ids in groups.items():
            ids = [i for i in ids if i in known]
            if ids:
                lines.append(f"    class {','.join(ids)} {state}")
    return "\n".join(lines) + "\n"


def run_cli(argv: list[str]) -> int:
    opts = dict(zip(argv[::2], argv[1::2]))
    prog, out = opts.get("--progress"), opts.get("--out")
    if not prog or not out:
        print(__doc__)
        return 2
    try:
        snap = json.loads(Path(prog).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reason": f"no run state: {exc}"}))
        return 4
    Path(out).write_text(to_run_mermaid(load(), snap), encoding="utf-8")
    print(json.dumps({"status": "ok", "out": out, "step": snap.get("step")}))
    return 0


def render_svg(mmd: Path, out: Path) -> bool:
    mmdc = shutil.which("mmdc")
    if not mmdc:
        return False
    subprocess.run([mmdc, "-p", str(ROOT / "docs" / "flow" / ".puppeteer.json"), "-i", str(mmd), "-o", str(out), "-q"], check=True)
    return True


def main(argv: list[str]) -> int:
    if any(a in ("-h", "--help") for a in argv[1:]):
        print(__doc__)
        return 0
    if argv[1:2] == ["--describe-cli"]:
        print(json.dumps({"verbs": ["generate", "check", "run"], "flags": ["--progress", "--out"]}))
        return 0
    if argv[1:2] == ["run"]:
        return run_cli(argv[2:])
    mode = argv[1] if len(argv) > 1 else "generate"
    if mode not in ("generate", "check"):
        print(__doc__)
        return 2
    flow = load()
    outputs = {FLOW_DIR / "simplicio-loop.mmd": to_mermaid(flow),
               FLOW_DIR / "langflow" / "simplicio-loop.langflow.json": to_langflow(flow)}
    if mode == "check":
        stale = [str(p.relative_to(ROOT)) for p, t in outputs.items()
                 if not p.exists() or p.read_text(encoding="utf-8") != t]
        print(json.dumps({"status": "stale" if stale else "fresh", "stale": stale}))
        return 1 if stale else 0
    for p, t in outputs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    if render_svg(FLOW_DIR / "simplicio-loop.mmd", FLOW_DIR / "simplicio-loop.svg") and render_svg(
        FLOW_DIR / "simplicio-loop.mmd", FLOW_DIR / "simplicio-loop.png"
    ):
        print(json.dumps({"status": "ok"}))
        return 0
    print(json.dumps({"status": "blocked", "reason": "mmdc (mermaid CLI) not found; SVG/PNG not rendered"}))
    return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
