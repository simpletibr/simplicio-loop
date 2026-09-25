"""Run and persist the real Q0/Q1/Q2 benchmark for issue #198."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from simplicio_fast.quant_benchmark import run_benchmark  # noqa: E402


def _number(value: float | None, digits: int = 3) -> str:
    return "null" if value is None else f"{value:.{digits}f}"


def render_report(receipt: dict[str, Any]) -> str:
    lines = [
        "# Quant benchmark Q0/Q1/Q2 — issue #198",
        "",
        f"- Classification: `{receipt['classification']}`",
        f"- Source commit: `{receipt['source_commit']}`",
        f"- Source tree: `{receipt['source_tree']}`",
        f"- Reproducible clean tree: `{receipt['source_state']['reproducible']}`",
        f"- Config hash: `{receipt['config_hash']}`",
        f"- Generation: `{receipt['generation']}`",
        f"- Reproduction: `{receipt['command']}`",
        "- Rust parity: `null` "
        f"(`{receipt['parity']['rust_reason']}`); no Rust compilation was attempted.",
        "",
        "![Measured size, latency and quality trade-off](quant-benchmark-198.svg)",
        "",
        "Measured lanes use identical corpus, queries, judgments, embeddings and configuration.",
        "Q2a is 4-bit without reranking; Q2b reranks its candidates with integral vectors.",
        "",
    ]
    for case in receipt["measured"]:
        lines.extend(
            [
                f"## {case['vectors']:,} vectors",
                "",
                f"Dataset: `{case['dataset']['dataset_hash']}`",
                "",
                f"Corpus: `{case['dataset']['corpus_hash']}`",
                "",
                f"Queries: `{case['dataset']['query_hash']}`",
                "",
                f"Embeddings: `{case['dataset']['embedding']['sha256']}`",
                "",
                "| Lane | Index bytes | Total bytes | Gate memory bytes | "
                "Reduction | Query p50 ms | Query p95 ms | Recall@10 | "
                "nDCG@10 | Rerank p50 ms |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for lane_name, lane in case["lanes"].items():
            lines.append(
                f"| {lane_name} | {lane['index_bytes']:,} | "
                f"{lane['total_storage_bytes']:,} | "
                f"{lane['promotion_memory_bytes']:,} | "
                f"{lane['index_reduction_vs_q0'] * 100:.2f}% | "
                f"{_number(lane['query_ms']['p50'])} | "
                f"{_number(lane['query_ms']['p95'])} | "
                f"{lane['quality']['recall_at_10']:.4f} | "
                f"{lane['quality']['ndcg_at_10']:.4f} | "
                f"{_number(lane['rerank_ms']['p50'])} |"
            )
        gate = case["promotion_gate"]
        lines.extend(
            [
                "",
                f"Promotion gate: **{gate['decision']}** (fail-closed).",
                "",
                "```json",
                json.dumps(gate, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
    if receipt["unavailable_sizes"]:
        lines.extend(
            [
                "## Unavailable sizes",
                "",
                "Unexecuted sizes are classified `BLOCKED`, have `null` values and "
                "stable reasons; no projection is substituted for a measurement.",
                "",
                "| Vectors | Value | Reason |",
                "|---:|---:|---|",
            ]
        )
        for item in receipt["unavailable_sizes"]:
            lines.append(f"| {item['vectors']:,} | null | `{item['reason']}` |")
        lines.append("")
    lines.extend(
        [
            "## Classification boundary",
            "",
            "- `measured`: raw samples from this machine, at least ten repetitions per lane.",
            "- `simulated`: `null`; simulations were not run or mixed into rankings.",
            "- Claims about speed or memory are restricted to measured samples in the JSON.",
            "- Current-RSS values may be `null` with a reason on hosts without `/proc`; "
            "index bytes, page faults, I/O blocks and peak RSS remain independently reported.",
            "",
        ]
    )
    return "\n".join(lines)


def render_svg(receipt: dict[str, Any]) -> str:
    """Render three directly comparable measured dimensions without dependencies."""
    case = receipt["measured"][0]
    lanes = tuple(case["lanes"])
    colors = {
        "Q0": "#334155",
        "Q1": "#0ea5e9",
        "Q2a": "#f59e0b",
        "Q2b": "#10b981",
    }
    panels = (
        (
            "Index size (MiB)",
            [case["lanes"][lane]["index_bytes"] / (1024 * 1024) for lane in lanes],
        ),
        (
            "Query p95 (ms)",
            [case["lanes"][lane]["query_ms"]["p95"] for lane in lanes],
        ),
        (
            "Recall@10",
            [case["lanes"][lane]["quality"]["recall_at_10"] for lane in lanes],
        ),
    )
    width, height = 1080, 430
    panel_width = 320
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Measured quantization trade-off chart">',
        "<style>text{font-family:ui-sans-serif,system-ui;fill:#0f172a}"
        ".title{font-size:20px;font-weight:700}.label{font-size:13px}"
        ".value{font-size:12px;font-weight:600}.axis{stroke:#94a3b8;stroke-width:1}</style>",
        '<rect width="1080" height="430" fill="#f8fafc"/>',
        '<text x="40" y="36" class="title">Simplicio Fast #198 — MEASURED trade-off</text>',
        (
            f'<text x="40" y="59" class="label">10,000 vectors · '
            f"{receipt['configuration']['repetitions']} repetitions · "
            f"gate {case['promotion_gate']['decision']}</text>"
        ),
    ]
    for panel_index, (title, values) in enumerate(panels):
        origin_x = 40 + panel_index * 345
        origin_y = 105
        chart_height = 230
        maximum = max(values) or 1.0
        parts.extend(
            [
                f'<text x="{origin_x}" y="88" class="label">{title}</text>',
                f'<line x1="{origin_x}" y1="{origin_y + chart_height}" '
                f'x2="{origin_x + panel_width}" y2="{origin_y + chart_height}" class="axis"/>',
            ]
        )
        bar_width = 54
        for lane_index, (lane, value) in enumerate(zip(lanes, values)):
            bar_x = origin_x + 15 + lane_index * 74
            bar_height = (value / maximum) * 205
            bar_y = origin_y + chart_height - bar_height
            rendered = f"{value:.3f}"
            parts.extend(
                [
                    f'<rect x="{bar_x}" y="{bar_y:.2f}" width="{bar_width}" '
                    f'height="{bar_height:.2f}" rx="4" fill="{colors[lane]}"/>',
                    f'<text x="{bar_x + bar_width / 2}" y="{bar_y - 7:.2f}" '
                    f'text-anchor="middle" class="value">{rendered}</text>',
                    f'<text x="{bar_x + bar_width / 2}" y="{origin_y + chart_height + 22}" '
                    f'text-anchor="middle" class="label">{lane}</text>',
                ]
            )
    gate = case["promotion_gate"]
    failed = (
        ", ".join(name for name, passed in gate["checks"].items() if not passed)
        or "none"
    )
    parts.extend(
        [
            f'<text x="40" y="405" class="label">Fail-closed gate failures: {failed}</text>',
            "</svg>",
        ]
    )
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--max-vectors", type=int, default=10_000)
    parser.add_argument("--sizes", default="10000,100000,1000000")
    parser.add_argument("--dimension", type=int, default=16)
    parser.add_argument("--candidate-k", type=int, default=80)
    parser.add_argument("--result-k", type=int, default=20)
    parser.add_argument("--seed", type=int, default=198)
    parser.add_argument("--shared-integral-store", action="store_true")
    parser.add_argument(
        "--output",
        default=str(ROOT / "benchmarks/results/quant-benchmark-198.json"),
    )
    parser.add_argument(
        "--report",
        default=str(ROOT / "benchmarks/reports/quant-benchmark-198.md"),
    )
    parser.add_argument(
        "--chart",
        default=str(ROOT / "benchmarks/reports/quant-benchmark-198.svg"),
    )
    args = parser.parse_args()
    sizes = tuple(int(value) for value in args.sizes.split(","))
    receipt = run_benchmark(
        ROOT,
        sizes=sizes,
        repetitions=args.repetitions,
        max_vectors=args.max_vectors,
        dimension=args.dimension,
        candidate_k=args.candidate_k,
        result_k=args.result_k,
        seed=args.seed,
        shared_integral_store=args.shared_integral_store,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(receipt), encoding="utf-8")
    chart = Path(args.chart)
    chart.parent.mkdir(parents=True, exist_ok=True)
    chart.write_text(render_svg(receipt), encoding="utf-8")
    summary = {
        "schema": receipt["schema"],
        "status": receipt["status"],
        "output": str(output),
        "report": str(report),
        "chart": str(chart),
        "measured_sizes": [item["vectors"] for item in receipt["measured"]],
        "unavailable_sizes": receipt["unavailable_sizes"],
        "promotion": [
            {
                "vectors": item["vectors"],
                "decision": item["promotion_gate"]["decision"],
            }
            for item in receipt["measured"]
        ],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
