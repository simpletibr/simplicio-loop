#!/usr/bin/env python3
"""
consolidate_4side_report.py — merge regex + functional benches into one
markdown showing all 4 sides (baseline / cli / cli+sp / cli+ag) for the
Qwen3 Coder MoE batch.

Reads:
  bench/results.json              (regex, from run_offline.py)
  bench/results_exec_sindico.json (functional, from run_exec_sindico.py)

Writes:
  bench/results_4side_qwen3.md
"""
from __future__ import annotations
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGEX_JSON = ROOT / "bench" / "results.json"
EXEC_JSON = ROOT / "bench" / "results_exec_sindico.json"
FANOUT_JSON = ROOT / "bench" / "results_fanout.json"
OUT_MD = ROOT / "bench" / "results_4side_qwen3.md"
OUT_PDF = ROOT / "bench" / "results_4side_qwen3.pdf"


def _row_attempts(rows: list, key: str) -> float:
    vals = [r[key].get("attempts", 1) for r in rows if key in r]
    return sum(vals) / max(len(vals), 1)


def _row_token_avg(rows: list, key: str, field: str = "tokens") -> float:
    vals = [r[key].get(field, 0) for r in rows if key in r]
    return sum(vals) / max(len(vals), 1)


def _row_ms_avg(rows: list, key: str) -> float:
    vals = [r[key].get("ms", 0) for r in rows if key in r]
    return sum(vals) / max(len(vals), 1)


def _exec_row(by_model: dict, model: str) -> dict:
    b = by_model[model]
    rows = b["rows"]
    return {
        "n": b["n"],
        "sem": b.get("sem_pct", 0),
        "com": b.get("com_pct", 0),
        "sp":  b.get("sp_pct", 0),
        "ag":  b.get("ag_pct", 0),
        "ag_attempts_avg": _row_attempts(rows, "ag"),
        "sem_tok": _row_token_avg(rows, "sem"),
        "com_tok": _row_token_avg(rows, "com"),
        "sp_tok":  _row_token_avg(rows, "sp"),
        "ag_tok":  _row_token_avg(rows, "ag"),
        "sem_ms": _row_ms_avg(rows, "sem"),
        "com_ms": _row_ms_avg(rows, "com"),
        "sp_ms":  _row_ms_avg(rows, "sp"),
        "ag_ms":  _row_ms_avg(rows, "ag"),
    }


def _regex_row(by_model: dict, model: str) -> dict:
    b = by_model[model]
    rows = b.get("rows", [])
    n = b["total"]
    ag_attempts = [r.get("ag_attempts", 1) for r in rows if "ag_attempts" in r]
    return {
        "n": n,
        "sem": b.get("sem_pct", 0),
        "com": b.get("com_pct", 0),
        "sp":  b.get("sp_pct", 0),
        "ag":  b.get("ag_pct", 0),
        "ag_attempts_avg": (sum(ag_attempts) / max(len(ag_attempts), 1)) if ag_attempts else 0,
        "sem_tok": b.get("usage_sem", {}).get("total_tokens", 0) / max(len(rows), 1),
        "com_tok": b.get("usage_com", {}).get("total_tokens", 0) / max(len(rows), 1),
        "sp_tok":  b.get("usage_sp",  {}).get("total_tokens", 0) / max(len(rows), 1),
        "ag_tok":  b.get("usage_ag",  {}).get("total_tokens", 0) / max(len(rows), 1),
    }


def fmt_pct(p: int) -> str:
    return f"{p}%"


def fmt_delta(a: int, b: int) -> str:
    d = a - b
    return f"**{d:+d}**"


def _fanout_by_model(rows: list) -> dict:
    """Aggregate fan-out rows by model: per-attempt fn/rx, modal counts."""
    by_model: dict = {}
    for r in rows:
        b = by_model.setdefault(r["model"], {
            "n_cases": 0, "fn_pass": 0, "fn_attempts": 0,
            "rx_pass": 0, "rx_attempts": 0,
            "fn_modal_pass": 0, "rx_modal_pass": 0,
            "tokens": 0, "elapsed_s": 0.0, "uniq_total": 0,
        })
        b["n_cases"] += 1
        b["fn_pass"] += r["fn_per_attempt_pass"]
        b["fn_attempts"] += r["completed"]
        b["rx_pass"] += r["rx_full_pass"]
        b["rx_attempts"] += r["completed"]
        if r["fn_majority_pass"]: b["fn_modal_pass"] += 1
        if r["rx_majority_full_pass"]: b["rx_modal_pass"] += 1
        b["tokens"] += r["tokens"]
        b["elapsed_s"] += r["elapsed_s"]
        b["uniq_total"] += r["unique_outputs"]
    return by_model


def main() -> int:
    if not EXEC_JSON.exists():
        raise SystemExit(f"missing {EXEC_JSON}")
    exec_data = json.loads(EXEC_JSON.read_text())
    regex_data = json.loads(REGEX_JSON.read_text()) if REGEX_JSON.exists() else {}
    fanout_data: dict = {}
    fanout_rows: list = []
    if FANOUT_JSON.exists():
        fanout_payload = json.loads(FANOUT_JSON.read_text())
        fanout_rows = fanout_payload.get("rows", [])
        fanout_data = _fanout_by_model(fanout_rows)

    # collect models present in either bench, in stable order
    exec_models = list(exec_data.keys())
    regex_models = [m for m in regex_data.keys() if m not in exec_models]
    all_models = exec_models + regex_models

    md = [
        "# 4-side comparison — Qwen3 Coder MoE",
        "",
        f"Date: **{time.strftime('%Y-%m-%d')}**  ",
        "",
        "**Sides** (same 6-layer task contract on cli / cli+sp / cli+ag):",
        "",
        "- `baseline` — raw one-line goal + file content. No simplicio at all.",
        "- `cli` — wrapped in the simplicio-cli 6-layer contract "
        "(role/stack, goal, target, criteria, constraints, output shape).",
        "- `cli + sp` — same contract, embedded as user-input-X inside the "
        "simplicio-prompt v1.9 Tuple-Space + Yool runtime template (3,907 "
        "chars of runtime preamble).",
        "- `cli + ag` — same contract, but on failure the harness classifies "
        "the failure (syntax/assertion/runtime/etc.), feeds the PHPUnit tail "
        "(or list of missed regex patterns) back as retry feedback, re-prompts. "
        "Up to 3 attempts. Mirrors `simplicio-py task --verify`.",
        "",
        "**Metrics**:",
        "",
        "- `functional` — real `vendor/bin/phpunit --configuration phpunit.xml.dist` "
        "on `wesleysimplicio/sistema-sindico` (PHP 8). Pass = full suite green.",
        "- `regex` — structural pattern match against the generated output "
        "(cheap proxy used by `bench/run_offline.py`).",
        "",
    ]

    # ---- HEADLINE TABLE ---- #
    md += ["## Headline — pass rate per side, both metrics", "",
           "| Model | metric | baseline | cli | cli+sp | cli+ag | "
           "Δ cli | Δ cli+sp | Δ cli+ag |",
           "|---|---|---|---|---|---|---|---|---|"]

    for model in all_models:
        if model in exec_data:
            e = _exec_row(exec_data, model)
            md.append(
                f"| `{model}` | functional | {fmt_pct(e['sem'])} | {fmt_pct(e['com'])} | "
                f"{fmt_pct(e['sp'])} | {fmt_pct(e['ag'])} | "
                f"{fmt_delta(e['com'], e['sem'])} | {fmt_delta(e['sp'], e['sem'])} | "
                f"{fmt_delta(e['ag'], e['sem'])} |"
            )
        if model in regex_data:
            r = _regex_row(regex_data, model)
            md.append(
                f"| `{model}` | regex | {fmt_pct(r['sem'])} | {fmt_pct(r['com'])} | "
                f"{fmt_pct(r['sp'])} | {fmt_pct(r['ag'])} | "
                f"{fmt_delta(r['com'], r['sem'])} | {fmt_delta(r['sp'], r['sem'])} | "
                f"{fmt_delta(r['ag'], r['sem'])} |"
            )

    # ---- AGENTS LOOP CONVERGENCE ---- #
    md += ["", "## Agents verify-loop convergence", "",
           "Lower attempts = the model resolved the case earlier; 1 means it "
           "passed on the first try with no feedback. Max attempts capped per "
           "harness.",
           "",
           "| Model | metric | avg attempts (cli+ag) |",
           "|---|---|---|"]
    for model in all_models:
        if model in exec_data:
            e = _exec_row(exec_data, model)
            md.append(f"| `{model}` | functional | {e['ag_attempts_avg']:.2f} |")
        if model in regex_data:
            r = _regex_row(regex_data, model)
            md.append(f"| `{model}` | regex | {r['ag_attempts_avg']:.2f} |")

    # ---- COST/LATENCY (functional only — exec captures both) ---- #
    md += ["", "## Cost & latency per call (functional bench)", "",
           "Tokens/call averaged across the 12 cases. cli+ag burns more tokens "
           "AND more wall-clock per case because it may run up to 3 attempts. "
           "If pass-rate gain doesn't justify the multiplier, single-shot cli "
           "wins for batch jobs; cli+ag wins for interactive workflows where "
           "a 1.5x cost is acceptable to avoid manual rerun.",
           "",
           "| Model | side | tokens/call | ms/call |",
           "|---|---|---|---|"]
    for model in exec_models:
        e = _exec_row(exec_data, model)
        md.append(f"| `{model}` | baseline | {e['sem_tok']:.0f} | {e['sem_ms']:.0f} |")
        md.append(f"| `{model}` | cli      | {e['com_tok']:.0f} | {e['com_ms']:.0f} |")
        md.append(f"| `{model}` | cli+sp   | {e['sp_tok']:.0f} | {e['sp_ms']:.0f} |")
        md.append(f"| `{model}` | cli+ag   | {e['ag_tok']:.0f} | {e['ag_ms']:.0f} |")

    # ---- PER-TASK MATRIX (functional) ---- #
    md += ["", "## Per-task × model (functional, base / cli / cli+sp / cli+ag)", ""]
    if exec_models:
        sample = next(iter(exec_data.values()))["rows"]
        md.append("| Task | " + " | ".join(m.split("/")[-1] for m in exec_models) + " |")
        md.append("|---|" + "|".join("---" for _ in exec_models) + "|")
        for i, r0 in enumerate(sample):
            cid = r0["id"]
            cells = []
            for m in exec_models:
                r = exec_data[m]["rows"][i]
                cell = ("P" if r["sem"]["passed"] else ".") + "/" + \
                       ("P" if r["com"]["passed"] else ".") + "/" + \
                       ("P" if r.get("sp", {}).get("passed") else ".") + "/" + \
                       ("P" if r.get("ag", {}).get("passed") else ".") + \
                       f"({r.get('ag', {}).get('attempts', 0)})"
                cells.append(cell)
            md.append(f"| {cid} | " + " | ".join(cells) + " |")
        md += ["",
               "Last digit on cli+ag is the attempt count consumed (1–3). 1 = "
               "no feedback loop needed. 3 with `.` = ran the full loop and "
               "still failed; this is a model-capability ceiling, not a "
               "feedback-loop problem."]

    # ---- FAN-OUT SECTION (if data present) ---- #
    if fanout_data:
        md += ["", "## Fan-out N=200 (cli + sp subagent runtime)", "",
               "Same `cli + sp` configuration as single-call, but the "
               "simplicio-prompt SubagentRuntime fires **N=200 real parallel "
               "LLM calls per (model, case)** at temperature=0.7 with "
               "`use_cache=False`. Each generated PHP file is scored two "
               "ways: real PHPUnit (functional) and structural regex. "
               "Modal vote = pass on the most-common normalized output.",
               "",
               "| Model | Cases | fn per-attempt | rx per-attempt | "
               "fn modal | rx modal | gap (rx − fn) | tokens | avg s/case |",
               "|---|---|---|---|---|---|---|---|---|"]
        for model, b in fanout_data.items():
            fn_pct = 100 * b["fn_pass"] // max(b["fn_attempts"], 1)
            rx_pct = 100 * b["rx_pass"] // max(b["rx_attempts"], 1)
            gap = rx_pct - fn_pct
            md.append(
                f"| `{model}` | {b['n_cases']} | "
                f"{b['fn_pass']}/{b['fn_attempts']} ({fn_pct}%) | "
                f"{b['rx_pass']}/{b['rx_attempts']} ({rx_pct}%) | "
                f"**{b['fn_modal_pass']}/{b['n_cases']}** | "
                f"{b['rx_modal_pass']}/{b['n_cases']} | "
                f"**{gap:+d}** | {b['tokens']:,} | "
                f"{b['elapsed_s']/max(b['n_cases'],1):.1f}s |"
            )

        md += ["",
               "### Per-task fan-out detail (fn% / rx% / modal fn / uniq)",
               "",
               "Format: `fn-per-attempt% / rx-per-attempt% / modal-fn / uniq-outputs`. "
               "**Bold uniq counts** ≥10 show high diversity at temp=0.7.",
               ""]
        fanout_models = list(fanout_data.keys())
        # collect task ids in order from first model
        task_ids = []
        for r in fanout_rows:
            if r["model"] == fanout_models[0]:
                task_ids.append(r["task"])
        md += ["| Task | " + " | ".join(m.replace("Qwen/Qwen3-Coder-", "Qwen3-C-")
                                         for m in fanout_models) + " |",
               "|---|" + "|".join("---" for _ in fanout_models) + "|"]
        # index by (model, task)
        idx = {(r["model"], r["task"]): r for r in fanout_rows}
        for tid in task_ids:
            cells = []
            for m in fanout_models:
                r = idx.get((m, tid))
                if r is None:
                    cells.append("—")
                    continue
                u = r["unique_outputs"]
                ub = f"**{u}**" if u >= 10 else str(u)
                cells.append(f"{r['fn_per_attempt_rate']}% / "
                             f"{r['rx_full_pass_rate']}% / "
                             f"{'P' if r['fn_majority_pass'] else '.'} / {ub}")
            md.append(f"| `{tid}` | " + " | ".join(cells) + " |")

        md += ["",
               "### Regex-vs-functional disagreement (the core finding)",
               "",
               "Cases where regex says PASS while PHPUnit says FAIL — the "
               "'regex doesn't mean the code runs' criticism in numbers.",
               "",
               "| Task | Model | rx | fn | gap |",
               "|---|---|---|---|---|"]
        for tid in task_ids:
            for m in fanout_models:
                r = idx.get((m, tid))
                if r is None: continue
                rx = r["rx_full_pass_rate"]; fn = r["fn_per_attempt_rate"]
                gap = rx - fn
                if gap >= 30:
                    flag = " ⚠️ inflates"
                    md.append(f"| `{tid}` | `{m.replace('Qwen/', '')}` | "
                              f"{rx}% | {fn}% | **{gap:+d}**{flag} |")

    OUT_MD.write_text("\n".join(md) + "\n")
    print(f"-> {OUT_MD}")
    _write_pdf(exec_data, regex_data, exec_models, all_models,
               fanout_data=fanout_data, fanout_rows=fanout_rows)
    return 0


def _write_pdf(exec_data: dict, regex_data: dict,
               exec_models: list, all_models: list,
               fanout_data: dict | None = None,
               fanout_rows: list | None = None) -> None:
    """Use reportlab (pure Python, no native crypto deps) to render a PDF
    mirroring the markdown headline + tables. Falls back silently if
    reportlab is missing."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak)
    except ImportError:
        print("[warn] reportlab not installed; skipping PDF.")
        return

    doc = SimpleDocTemplate(
        str(OUT_PDF), pagesize=A4,
        leftMargin=14*mm, rightMargin=14*mm,
        topMargin=14*mm, bottomMargin=14*mm,
    )
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]; body.fontSize = 9; body.leading = 12
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)
    story = []

    story.append(Paragraph(
        "4-side comparison &mdash; Qwen3 Coder MoE", h1))
    story.append(Paragraph(
        f"Date: <b>{time.strftime('%Y-%m-%d')}</b>", body))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph("Sides", h2))
    story.append(Paragraph(
        "<b>baseline</b> &mdash; raw one-line goal + file content. No "
        "simplicio.<br/>"
        "<b>cli</b> &mdash; the simplicio-cli 6-layer task contract "
        "(role/stack, goal, target, criteria, constraints, output shape).<br/>"
        "<b>cli + sp</b> &mdash; same contract wrapped as user-input-X inside "
        "the simplicio-prompt v1.9 Tuple-Space + Yool runtime template.<br/>"
        "<b>cli + ag</b> &mdash; same contract, with classified failure feedback "
        "(PHPUnit tail or missed regex patterns) fed back over up to 3 attempts. "
        "Mirrors <font face='Courier'>simplicio-py task --verify</font>.",
        body))
    story.append(Spacer(1, 3*mm))

    story.append(Paragraph("Metrics", h2))
    story.append(Paragraph(
        "<b>functional</b> &mdash; real <font face='Courier'>vendor/bin/phpunit "
        "--configuration phpunit.xml.dist</font> on "
        "<font face='Courier'>wesleysimplicio/sistema-sindico</font> (PHP 8). "
        "Pass = full suite green.<br/>"
        "<b>regex</b> &mdash; structural pattern match against the generated "
        "output (cheap proxy used by <font face='Courier'>bench/run_offline.py</font>).",
        body))
    story.append(Spacer(1, 5*mm))

    # Headline table
    story.append(Paragraph("Headline &mdash; pass rate per side, both metrics", h2))
    headline = [["Model", "Metric", "baseline", "cli", "cli+sp", "cli+ag",
                 "Δcli", "Δcli+sp", "Δcli+ag"]]
    for model in all_models:
        short = model.replace("Qwen/", "")
        if model in exec_data:
            e = _exec_row(exec_data, model)
            headline.append([short, "functional",
                             f"{e['sem']}%", f"{e['com']}%",
                             f"{e['sp']}%", f"{e['ag']}%",
                             f"{e['com']-e['sem']:+d}",
                             f"{e['sp']-e['sem']:+d}",
                             f"{e['ag']-e['sem']:+d}"])
        if model in regex_data:
            r = _regex_row(regex_data, model)
            headline.append([short, "regex",
                             f"{r['sem']}%", f"{r['com']}%",
                             f"{r['sp']}%", f"{r['ag']}%",
                             f"{r['com']-r['sem']:+d}",
                             f"{r['sp']-r['sem']:+d}",
                             f"{r['ag']-r['sem']:+d}"])
    t = Table(headline, colWidths=[55*mm, 18*mm, 17*mm, 13*mm, 17*mm, 17*mm,
                                   13*mm, 17*mm, 17*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7eaf0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888")),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(t)
    story.append(Spacer(1, 5*mm))

    # Agents convergence
    story.append(Paragraph("Agents verify-loop convergence", h2))
    story.append(Paragraph(
        "Lower attempts = the model resolved the case earlier; 1 means it "
        "passed on the first try. Max attempts capped per harness.", body))
    conv = [["Model", "Metric", "avg attempts (cli+ag)"]]
    for model in all_models:
        short = model.replace("Qwen/", "")
        if model in exec_data:
            e = _exec_row(exec_data, model)
            conv.append([short, "functional", f"{e['ag_attempts_avg']:.2f}"])
        if model in regex_data:
            r = _regex_row(regex_data, model)
            conv.append([short, "regex", f"{r['ag_attempts_avg']:.2f}"])
    t = Table(conv, colWidths=[80*mm, 25*mm, 40*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7eaf0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888")),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(t)
    story.append(Spacer(1, 5*mm))

    # Cost & latency (functional only)
    story.append(Paragraph("Cost & latency per call (functional bench)", h2))
    story.append(Paragraph(
        "Tokens/call averaged across the 12 cases. cli+ag burns more "
        "tokens AND wall-clock per case because it may run up to 3 attempts.", body))
    cost = [["Model", "Side", "tokens/call", "ms/call"]]
    for model in exec_models:
        short = model.replace("Qwen/", "")
        e = _exec_row(exec_data, model)
        cost.append([short, "baseline", f"{e['sem_tok']:.0f}", f"{e['sem_ms']:.0f}"])
        cost.append([short, "cli", f"{e['com_tok']:.0f}", f"{e['com_ms']:.0f}"])
        cost.append([short, "cli+sp", f"{e['sp_tok']:.0f}", f"{e['sp_ms']:.0f}"])
        cost.append([short, "cli+ag", f"{e['ag_tok']:.0f}", f"{e['ag_ms']:.0f}"])
    t = Table(cost, colWidths=[80*mm, 25*mm, 30*mm, 30*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7eaf0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888")),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(t)
    story.append(Spacer(1, 5*mm))

    # Per-task matrix (functional)
    if exec_models:
        story.append(PageBreak())
        story.append(Paragraph(
            "Per-task &times; model (functional, base / cli / cli+sp / cli+ag)", h2))
        story.append(Paragraph(
            "P = pass, . = fail. cli+ag suffix is the attempt count (1-3). "
            "1 means no feedback loop needed; 3 with . means the loop ran to "
            "exhaustion and still failed (model-capability ceiling).", small))
        sample = next(iter(exec_data.values()))["rows"]
        header = ["Task"] + [m.replace("Qwen/Qwen3-Coder-", "Qwen3-C-")
                             for m in exec_models]
        rows = [header]
        for i, r0 in enumerate(sample):
            cid = r0["id"]
            cells = [cid]
            for m in exec_models:
                r = exec_data[m]["rows"][i]
                cell = ("P" if r["sem"]["passed"] else ".") + "/" + \
                       ("P" if r["com"]["passed"] else ".") + "/" + \
                       ("P" if r.get("sp", {}).get("passed") else ".") + "/" + \
                       ("P" if r.get("ag", {}).get("passed") else ".") + \
                       f"({r.get('ag', {}).get('attempts', 0)})"
                cells.append(cell)
            rows.append(cells)
        t = Table(rows, colWidths=[55*mm] + [55*mm] * len(exec_models))
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7eaf0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (1, 1), (-1, -1), "Courier"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888")),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ]))
        story.append(t)

    # ---- Fan-out N=200 section ---- #
    if fanout_data:
        story.append(PageBreak())
        story.append(Paragraph(
            "Fan-out N=200 (cli + sp subagent runtime)", h2))
        story.append(Paragraph(
            "The simplicio-prompt SubagentRuntime fires <b>200 parallel LLM "
            "calls per case</b> at temperature=0.7. Each output is scored by "
            "real PHPUnit AND structural regex. Modal vote = pass on the "
            "most-common output. The <b>regex - fn gap</b> column quantifies "
            "where the cheap regex proxy lies.", body))
        story.append(Spacer(1, 3*mm))
        head = [["Model", "Cases", "fn per-att", "rx per-att",
                 "fn modal", "rx modal", "gap", "avg s/case"]]
        for model, b in fanout_data.items():
            fn_pct = 100 * b["fn_pass"] // max(b["fn_attempts"], 1)
            rx_pct = 100 * b["rx_pass"] // max(b["rx_attempts"], 1)
            gap = rx_pct - fn_pct
            head.append([
                model.replace("Qwen/", ""), str(b["n_cases"]),
                f"{fn_pct}%", f"{rx_pct}%",
                f"{b['fn_modal_pass']}/{b['n_cases']}",
                f"{b['rx_modal_pass']}/{b['n_cases']}",
                f"{gap:+d}",
                f"{b['elapsed_s']/max(b['n_cases'],1):.1f}s",
            ])
        t = Table(head, colWidths=[50*mm, 12*mm, 22*mm, 22*mm, 18*mm,
                                   18*mm, 14*mm, 22*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7eaf0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888")),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ]))
        story.append(t)
        story.append(Spacer(1, 4*mm))

        story.append(Paragraph(
            "Regex-vs-functional disagreement (gap &gt;= 30 pts)", h2))
        story.append(Paragraph(
            "Each row below is a (task, model) where regex says PASS while "
            "PHPUnit says FAIL. This is the case-by-case evidence that the "
            "regex proxy is misleading for these particular failure modes.", body))
        if fanout_rows:
            idx = {(r["model"], r["task"]): r for r in fanout_rows}
            rows = [["Task", "Model", "rx", "fn", "gap"]]
            # task order from first row's model
            first_model = next(iter(fanout_data.keys()))
            task_ids = [r["task"] for r in fanout_rows if r["model"] == first_model]
            for tid in task_ids:
                for m in fanout_data.keys():
                    r = idx.get((m, tid))
                    if r is None: continue
                    rx = r["rx_full_pass_rate"]; fn = r["fn_per_attempt_rate"]
                    gap = rx - fn
                    if gap >= 30:
                        rows.append([tid, m.replace("Qwen/Qwen3-Coder-", ""),
                                     f"{rx}%", f"{fn}%", f"{gap:+d}"])
            if len(rows) > 1:
                t = Table(rows, colWidths=[60*mm, 50*mm, 18*mm, 18*mm, 18*mm])
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7eaf0")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888")),
                    ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                    ("TEXTCOLOR", (4, 1), (4, -1), colors.HexColor("#c62828")),
                ]))
                story.append(t)

    doc.build(story)
    print(f"-> {OUT_PDF}")


if __name__ == "__main__":
    raise SystemExit(main())
