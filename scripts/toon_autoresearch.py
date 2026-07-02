#!/usr/bin/env python3
"""Autoresearch pilot 1 — evolutionary loop over the TOON encoder (issue #151).

First pilot of the `simplicio-autoresearch` skill pattern (Karpathy-style
mutate -> evaluate -> keep/revert via git -> repeat), targeting
`simplicio_mapper/toon.py`. See `docs/toon-autoresearch-log.md` for the
actual run this script produced (iteration log, evidence, retrospective).

Eval (composite, in this order — a "shorter but lossy" mutation is rejected
by the GATE before it ever reaches the SCORE):

1. GATE — `python -m unittest tests.python.test_toon tests.python.test_toon_contract -q`
   (round-trip + the full TOON-CONTRACT golden corpus) plus
   `ruff check simplicio_mapper/toon.py`. Any failure -> reject, revert.
2. SCORE — sum of the same approximate-token count used by
   `scripts/toon_benchmark.py` (regex word-boundary split; see that
   script's docstring for why it is not `chars/4` and not a real BPE
   tokenizer) over `encode_toon()` of the 3 real survey artifacts. Lower is
   better.

Baseline: the state after #148's manual fix (list-of-scalars cells now
tabular). The loop starts *after* that deterministic fix, to optimize what
remains, not to replace it.

Usage:
  python3 scripts/toon_autoresearch.py gate      # run just the gate, print pass/fail
  python3 scripts/toon_autoresearch.py score      # print the current score
  python3 scripts/toon_autoresearch.py baseline   # print gate+score as JSON (one line)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from simplicio_mapper.toon import encode_toon  # noqa: E402

ARTIFACTS = ["project-map", "precedent-index", "flow-inventory"]
_APPROX_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]")


def _approx_tokens(text: str) -> int:
    return len(_APPROX_TOKEN_RE.findall(text))


def score() -> int:
    total = 0
    for name in ARTIFACTS:
        path = os.path.join(ROOT, ".simplicio", f"{name}.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        total += _approx_tokens(encode_toon(data))
    return total


def gate() -> tuple[bool, str]:
    unit = subprocess.run(  # noqa: S603 - fixed argv, no shell, dev-tooling script
        [sys.executable, "-m", "unittest", "tests.python.test_toon", "tests.python.test_toon_contract", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if unit.returncode != 0:
        return False, f"unit/contract gate failed:\n{unit.stdout}\n{unit.stderr}"
    lint = subprocess.run(  # noqa: S603
        ["ruff", "check", "simplicio_mapper/toon.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if lint.returncode != 0:
        return False, f"ruff gate failed:\n{lint.stdout}\n{lint.stderr}"
    return True, "gate passed (unit + contract + ruff)"


def emit_savings_event(baseline_score: int, final_score: int, kept: bool, note: str) -> str:
    """Write a ``simplicio.savings-event/v1`` receipt under ``.receipts/``
    (repo-local, gitignored execution evidence — see AGENTS.md's receipt
    schema reference). Returns the written path.
    """
    saved = max(0, baseline_score - final_score)
    pct = round(saved / baseline_score * 100, 2) if baseline_score else 0.0
    payload = {
        "schema": "simplicio.savings-event/v1",
        "source": "autoresearch",
        "target": "simplicio_mapper/toon.py",
        "baseline_score_tokens_approx": baseline_score,
        "final_score_tokens_approx": final_score,
        "saved_tokens_approx": saved,
        "saved_pct": pct,
        "mutation_kept": kept,
        "note": note,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    content = json.dumps(payload, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    payload["id"] = f"sha256:{digest}"
    out_dir = os.path.join(ROOT, ".receipts")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"toon-autoresearch-{digest[:16]}.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return out_path


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "baseline"
    if command == "gate":
        ok, detail = gate()
        print(detail)
        return 0 if ok else 1
    if command == "score":
        print(score())
        return 0
    if command == "baseline":
        ok, detail = gate()
        print(json.dumps({"gate_pass": ok, "gate_detail": detail, "score": score() if ok else None}))
        return 0 if ok else 1
    if command == "emit-savings-event":
        # argv: emit-savings-event <baseline> <final> <kept:true|false> <note>
        baseline_score = int(argv[1])
        final_score = int(argv[2])
        kept = argv[3].lower() == "true"
        note = argv[4] if len(argv) > 4 else ""
        path = emit_savings_event(baseline_score, final_score, kept, note)
        print(path)
        return 0
    print(f"Unknown command: {command!r} (expected gate|score|baseline|emit-savings-event)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
