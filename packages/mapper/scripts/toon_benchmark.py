#!/usr/bin/env python3
"""Measure JSON vs TOON size on the mapper's real survey artifacts.

Honest re-run of the #144/#148 benchmark. Prints a Markdown table (also
written to ``docs/toon-benchmark.md``) with:

- compact-JSON char count vs TOON char count (the primary, exact metric)
- an approximate token count for both encodings, so the reduction is
  comparable to the upstream ~40% claim without pretending we have a model
  tokenizer wired in (see "Tokenizer used" below)
- round-trip lossless check (``decode_toon(encode_toon(x)) == x``)
- the ``toon_fallbacks`` report (issue #148) — which arrays, if any,
  could not take the tabular/inline path and why

Tokenizer used: this repo has no tokenizer dependency (``tiktoken`` is not
installed, and this project's rule is "no new dependency without human
confirmation" — see AGENTS.md). The "approx tokens" column below uses a
regex word-boundary split (``\\S+`` runs plus punctuation as their own
token, roughly matching how BPE tokenizers split on whitespace/punctuation
boundaries) — NOT ``chars/4`` and NOT a real BPE tokenizer. It is a
documented, reproducible proxy, not a substitute for a labeled model
tokenizer. Getting an exact GPT/Claude token count needs ``tiktoken`` (or
equivalent) added as a dependency, which is flagged as a follow-up rather
than added silently.

Usage: python3 scripts/toon_benchmark.py [--write]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from simplicio_mapper.toon import decode_toon, encode_toon_with_report  # noqa: E402

ARTIFACTS = ["project-map", "precedent-index", "flow-inventory"]

_APPROX_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]")


def _approx_tokens(text: str) -> int:
    """Regex word-boundary token approximation (see module docstring)."""
    return len(_APPROX_TOKEN_RE.findall(text))


def _measure(name: str) -> dict:
    path = os.path.join(ROOT, ".simplicio-loop", f"{name}.json")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    json_compact = json.dumps(data, separators=(",", ":"))
    toon_text, fallbacks = encode_toon_with_report(data)
    lossless = decode_toon(toon_text) == data
    json_chars = len(json_compact)
    toon_chars = len(toon_text)
    json_tokens = _approx_tokens(json_compact)
    toon_tokens = _approx_tokens(toon_text)
    return {
        "name": name,
        "json_chars": json_chars,
        "toon_chars": toon_chars,
        "char_reduction_pct": round((1 - toon_chars / json_chars) * 100, 1) if json_chars else 0.0,
        "json_tokens_approx": json_tokens,
        "toon_tokens_approx": toon_tokens,
        "token_reduction_pct": round((1 - toon_tokens / json_tokens) * 100, 1) if json_tokens else 0.0,
        "lossless": lossless,
        "fallbacks": fallbacks,
    }


def _render_markdown(results: list[dict]) -> str:
    lines = [
        "# TOON benchmark — mapper survey artifacts",
        "",
        f"Re-measured: {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (issue #148, follow-up to #144).",
        "",
        "Tokenizer used: regex word-boundary approximation (`\\S+`-ish split on "
        "`[A-Za-z0-9_]+` runs and individual punctuation characters), **not** "
        "`chars/4` and **not** a real BPE tokenizer — `tiktoken` is not installed "
        "in this repo (no new dependency added without human confirmation, per "
        "AGENTS.md). Char-count reduction is the exact, primary number; the "
        "token column is a documented, reproducible proxy for it.",
        "",
        "| Artifact | JSON chars | TOON chars | Char reduction | JSON tokens (approx) |"
        " TOON tokens (approx) | Token reduction (approx) | Lossless | Fallbacks |",
        "|---|---:|---:|---:|---:|---:|---:|:---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| `{r['name']}.json` | {r['json_chars']:,} | {r['toon_chars']:,} | "
            f"{r['char_reduction_pct']}% | {r['json_tokens_approx']:,} | "
            f"{r['toon_tokens_approx']:,} | {r['token_reduction_pct']}% | "
            f"{'yes' if r['lossless'] else '**NO**'} | {len(r['fallbacks'])} |"
        )
    lines.append("")
    any_fallbacks = [r for r in results if r["fallbacks"]]
    if any_fallbacks:
        lines.append("## Fallbacks (non-tabular arrays)")
        lines.append("")
        for r in any_fallbacks:
            for fb in r["fallbacks"]:
                lines.append(f"- `{r['name']}.json` `{fb['path']}` — {fb['reason']}")
        lines.append("")
    lines.append(
        "## History\n\n"
        "- **Pre-fix (#144, PR #145)**: 7.1% / 4.5% / 8.4% char reduction on "
        "`project-map` / `precedent-index` / `flow-inventory` — the tabular "
        "path rejected any array whose elements contained a list cell "
        "(`files[].exports/imports/roles`, `items[].tags`), which is most of "
        "the mapper's real data shape, so almost everything fell back to "
        "embedded compact JSON.\n"
        "- **Post-fix (#148)**: the tabular path now accepts cells whose value "
        "is a list of scalars (`[a,b,c]` inline within the row), which is "
        "exactly that shape. Remaining fallbacks are genuine nested "
        "dict-valued cells (`agent_tree.children`, `flows[].steps`), not a bug "
        "— honestly reported below via `toon_fallbacks`, not silently dropped.\n"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="Write docs/toon-benchmark.md instead of only printing"
    )
    args = parser.parse_args()

    results = [_measure(name) for name in ARTIFACTS]
    markdown = _render_markdown(results)
    print(markdown)

    if args.write:
        out_path = os.path.join(ROOT, "docs", "toon-benchmark.md")
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
        print(f"\nWrote {out_path}", file=sys.stderr)

    return 0 if all(r["lossless"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
