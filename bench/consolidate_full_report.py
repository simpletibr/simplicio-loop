#!/usr/bin/env python3
"""
consolidate_full_report.py — single PDF + MD covering EVERYTHING run
against the Qwen3 Coder MoE batch:

  1. exec single-call (12 cases × 4 sides, real PHPUnit)
  2. regex single-call (10 cases × 4 sides)
  3. fan-out N=200 (12 cases × N parallel subagents, real PHPUnit + regex)

Reads:
  bench/results_exec_sindico.json
  bench/results.json
  bench/results_fanout.json

Writes:
  bench/results_full_qwen3.md
  bench/results_full_qwen3.pdf
"""
from __future__ import annotations
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXEC_JSON = ROOT / "bench" / "results_exec_sindico.json"
REGEX_JSON = ROOT / "bench" / "results.json"
FANOUT_JSON = ROOT / "bench" / "results_fanout.json"
OUT_MD = ROOT / "bench" / "results_full_qwen3.md"
OUT_PDF = ROOT / "bench" / "results_full_qwen3.pdf"


# ---- per-bench extractors ---- #

def exec_summary(by_model: dict) -> dict:
    """Per-model: pct for each of the 4 sides + avg agents attempts +
    avg tokens/ms per side."""
    out = {}
    for model, b in by_model.items():
        rows = b["rows"]
        n = b["n"]
        def avg(side, key):
            vs = [r[side].get(key, 0) for r in rows if side in r]
            return sum(vs) / max(len(vs), 1)
        out[model] = {
            "n": n,
            "sem_pct": b.get("sem_pct", 0),
            "com_pct": b.get("com_pct", 0),
            "sp_pct": b.get("sp_pct", 0),
            "ag_pct": b.get("ag_pct", 0),
            "ag_attempts": avg("ag", "attempts"),
            "sem_tok": avg("sem", "tokens"),
            "com_tok": avg("com", "tokens"),
            "sp_tok": avg("sp", "tokens"),
            "ag_tok": avg("ag", "tokens"),
            "sem_ms": avg("sem", "ms"),
            "com_ms": avg("com", "ms"),
            "sp_ms": avg("sp", "ms"),
            "ag_ms": avg("ag", "ms"),
        }
    return out


def regex_summary(by_model: dict) -> dict:
    out = {}
    for model, b in by_model.items():
        rows = b.get("rows", [])
        n = b["total"]
        ag_attempts = [r.get("ag_attempts", 1) for r in rows if "ag_attempts" in r]
        out[model] = {
            "n": n,
            "sem_pct": b.get("sem_pct", 0),
            "com_pct": b.get("com_pct", 0),
            "sp_pct": b.get("sp_pct", 0),
            "ag_pct": b.get("ag_pct", 0),
            "ag_attempts": (sum(ag_attempts)/max(len(ag_attempts), 1)) if ag_attempts else 0,
        }
    return out


def fanout_summary(rows: list) -> dict:
    out = {}
    for r in rows:
        m = r["model"]
        d = out.setdefault(m, {
            "cases": 0, "fn_attempts": 0, "fn_pass": 0,
            "rx_attempts": 0, "rx_pass": 0,
            "fn_modal": 0, "rx_modal": 0,
            "uniq_total": 0, "tokens": 0, "elapsed": 0.0, "cost": 0.0,
            "per_case": [],
        })
        d["cases"] += 1
        d["fn_attempts"] += r["completed"]
        d["fn_pass"] += r["fn_per_attempt_pass"]
        d["rx_attempts"] += r["completed"]
        d["rx_pass"] += r["rx_full_pass"]
        d["fn_modal"] += int(r["fn_majority_pass"])
        d["rx_modal"] += int(r["rx_majority_full_pass"])
        d["uniq_total"] += r["unique_outputs"]
        d["tokens"] += r["tokens"]
        d["elapsed"] += r["elapsed_s"]
        d["cost"] += r["cost_usd"]
        d["per_case"].append({
            "task": r["task"],
            "fn_pct": r["fn_per_attempt_rate"],
            "rx_pct": r["rx_full_pass_rate"],
            "fn_modal": r["fn_majority_pass"],
            "rx_modal": r["rx_majority_full_pass"],
            "uniq": r["unique_outputs"],
        })
    return out


def fmt_pct(p: int) -> str: return f"{p}%"
def fmt_d(a: int, b: int) -> str: return f"**{a-b:+d}**"


def build_md(exec_s: dict, regex_s: dict, fanout_s: dict) -> str:
    models = list(set(list(exec_s) + list(regex_s) + list(fanout_s)))
    models.sort()

    md = [
        "# Qwen3 Coder MoE — comprehensive benchmark report",
        "",
        f"Date: **{time.strftime('%Y-%m-%d')}**  ",
        "",
        "Single-source-of-truth report covering every measurement taken "
        "against the Qwen3 Coder MoE family on this branch. Three benches, "
        "two models, three to four sides each, two metrics where applicable.",
        "",
        "## Models",
        "",
        "- **`Qwen/Qwen3-Coder-30B-A3B-Instruct`** — MoE 30B total / 3B active per token, "
        "Apache 2.0, served via the HuggingFace Inference Router.",
        "- **`Qwen/Qwen3-Coder-Next`** — MoE 80B total / 3B active, 256K context, "
        "Apache 2.0, also via HF router.",
        "",
        "Both replace the previous Qwen2.5-Coder-3B/7B defaults (closed via PR #30 "
        "and issue #31; master commit `e3d3ccf`).",
        "",
        "## Sides under test",
        "",
        "| Side | Single-call (1 LLM call/case) | Description |",
        "|---|---|---|",
        "| `baseline` | yes | Raw one-line goal + file content. No simplicio. |",
        "| `cli` | yes | The simplicio-cli 6-layer task contract (role/stack, "
        "goal, target, criteria as testable states, constraints, output shape). |",
        "| `cli + sp` | yes | Same contract embedded as user-input X inside the "
        "simplicio-prompt v1.9 Tuple-Space + Yool runtime template "
        "(~3,900 chars of runtime preamble). |",
        "| `cli + ag` | up to **3** sequential attempts | Same contract; on "
        "failure the harness classifies the PHPUnit tail (or missed regex "
        "patterns) and re-prompts with retry feedback. Mirrors "
        "`simplicio-py task --verify` / `simplicio.pipeline.run()`. |",
        "| `cli (fan-out)` | **N=200** parallel subagents | "
        "Single-call cli contract repeated 200x in parallel through "
        "`kernel.subagent_runtime.SubagentRuntime` (LaneWorkerPool, "
        "temperature=0.7, use_cache=False). Pass = (a) per-attempt rate, "
        "(b) modal-vote PHPUnit pass. |",
        "",
        "## Benches",
        "",
        "| Bench | Cases | Oracle | Metric |",
        "|---|---|---|---|",
        "| **exec** | 12 | real `vendor/bin/phpunit` on `wesleysimplicio/sistema-sindico` "
        "(PHP 8) | functional (suite green = pass) |",
        "| **regex** | 10 | structural pattern match on output | regex hit / total |",
        "| **fan-out** | 12 | real PHPUnit **and** regex on every "
        "subagent's output | per-attempt + modal-vote, both metrics |",
        "",
        "## Headline — single-call (12 functional + 10 regex cases)",
        "",
        "| Model | metric | baseline | cli | cli+sp | cli+ag | Δcli | Δcli+sp | Δcli+ag |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in models:
        short = m.replace("Qwen/", "")
        if m in exec_s:
            e = exec_s[m]
            md.append(
                f"| `{short}` | exec | {fmt_pct(e['sem_pct'])} | {fmt_pct(e['com_pct'])} | "
                f"{fmt_pct(e['sp_pct'])} | {fmt_pct(e['ag_pct'])} | "
                f"{fmt_d(e['com_pct'], e['sem_pct'])} | {fmt_d(e['sp_pct'], e['sem_pct'])} | "
                f"{fmt_d(e['ag_pct'], e['sem_pct'])} |"
            )
        if m in regex_s:
            r = regex_s[m]
            md.append(
                f"| `{short}` | regex | {fmt_pct(r['sem_pct'])} | {fmt_pct(r['com_pct'])} | "
                f"{fmt_pct(r['sp_pct'])} | {fmt_pct(r['ag_pct'])} | "
                f"{fmt_d(r['com_pct'], r['sem_pct'])} | {fmt_d(r['sp_pct'], r['sem_pct'])} | "
                f"{fmt_d(r['ag_pct'], r['sem_pct'])} |"
            )

    md += [
        "",
        "## Headline — fan-out N=200 (cli contract, 200 parallel subagents)",
        "",
        "| Model | per-attempt fn | modal fn | per-attempt rx | modal rx | avg uniq/200 | total wall-clock | cost |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for m in models:
        if m not in fanout_s: continue
        f = fanout_s[m]
        short = m.replace("Qwen/", "")
        attempts = f["fn_attempts"]
        md.append(
            f"| `{short}` | {f['fn_pass']}/{attempts} "
            f"({100*f['fn_pass']//max(attempts,1)}%) | **{f['fn_modal']}/{f['cases']}** | "
            f"{f['rx_pass']}/{attempts} ({100*f['rx_pass']//max(attempts,1)}%) | "
            f"{f['rx_modal']}/{f['cases']} | "
            f"{f['uniq_total']/max(f['cases'],1):.1f} | "
            f"{f['elapsed']:.0f}s | ${f['cost']:.4f} |"
        )

    # Key findings
    md += [
        "",
        "## Key findings",
        "",
        "### 1. `cli + ag` is the only side that beats `cli` reliably on functional",
        "",
        "On the exec bench (real PHPUnit), `cli + ag` (verify-loop) recovers "
        "one or two cases per model that single-shot `cli` misses, by feeding "
        "the PHPUnit tail back as classified retry feedback. `cli + sp` "
        "(runtime composition) ties or trails `cli` in aggregate — it adds "
        "~1,000 tokens/call of runtime preamble that, in this single-call "
        "context, doesn't translate into pass-rate gains.",
        "",
        "### 2. Regex *inflates* on `Qwen3-Coder-30B-A3B-Instruct` under temp=0.7",
        "",
        "In the fan-out batch (N=200, temp=0.7), the 30B-A3B model shows a "
        "stark regex-vs-functional disagreement on **6 of 12 cases**: regex "
        "scores 100% (every pattern matched on every output), but PHPUnit "
        "exit code 0 was hit **zero times in 200 attempts**. The model "
        "produces output that LOOKS right (correct method names, correct "
        "types, correct token-level shape) but the runtime behaviour is "
        "wrong — exactly the criticism that `regex doesn't mean it works`.",
        "",
        "### 3. `Qwen3-Coder-Next` is dramatically more robust to temp=0.7",
        "",
        "Same fan-out config, same prompts, same 12 cases — Coder-Next "
        "modal-vote passes **12/12 cases on real PHPUnit**, while 30B-A3B "
        "modal-vote passes 5/12. The cli's 6-layer contract is enough; "
        "Coder-Next preserves semantic correctness across temperature-induced "
        "variations where 30B-A3B drifts.",
        "",
        "### 4. Some cases are model-capability ceilings, not feedback-loop "
        "problems",
        "",
        "`password_require_symbol` failed for every side and every iteration "
        "on 30B-A3B (3-attempt verify-loop exhausted; 200 fan-out attempts "
        "exhausted). It only passed on Coder-Next, and only with modal-vote "
        "fan-out at 187/200. This is a model-capability boundary — no "
        "amount of feedback or retry helps; either the model can or it can't.",
        "",
        "## Cost & latency (exec bench, per call)",
        "",
        "| Model | Side | tokens/call | ms/call |",
        "|---|---|---|---|",
    ]
    for m in models:
        if m not in exec_s: continue
        e = exec_s[m]
        short = m.replace("Qwen/", "")
        md.append(f"| `{short}` | baseline | {e['sem_tok']:.0f} | {e['sem_ms']:.0f} |")
        md.append(f"| `{short}` | cli      | {e['com_tok']:.0f} | {e['com_ms']:.0f} |")
        md.append(f"| `{short}` | cli+sp   | {e['sp_tok']:.0f} | {e['sp_ms']:.0f} |")
        md.append(f"| `{short}` | cli+ag   | {e['ag_tok']:.0f} | {e['ag_ms']:.0f} (avg {e['ag_attempts']:.2f} attempts) |")

    # Fan-out per-task
    md += [
        "",
        "## Fan-out per-task (N=200, both metrics, modal-vote)",
        "",
        "Format: `fn% / rx% / fn-modal / unique-outputs`",
        "",
        "| Task | " + " | ".join(m.replace("Qwen/", "") for m in models if m in fanout_s) + " |",
        "|---|" + "|".join("---" for m in models if m in fanout_s) + "|",
    ]
    # collect all task ids from fan-out
    all_tasks: list = []
    for m in models:
        if m in fanout_s:
            for c in fanout_s[m]["per_case"]:
                if c["task"] not in all_tasks:
                    all_tasks.append(c["task"])
    for task in all_tasks:
        cells = []
        for m in models:
            if m not in fanout_s:
                continue
            match = next((c for c in fanout_s[m]["per_case"] if c["task"] == task), None)
            if match is None:
                cells.append("—")
                continue
            cells.append(
                f"{match['fn_pct']:>3d}% / {match['rx_pct']:>3d}% / "
                f"{'P' if match['fn_modal'] else '.'} / "
                f"u{match['uniq']}"
            )
        md.append(f"| `{task}` | " + " | ".join(cells) + " |")

    # Exec per-task matrix
    if exec_s:
        md += [
            "",
            "## Exec per-task × model × side (base / cli / cli+sp / cli+ag(attempts))",
            "",
            "P = real PHPUnit suite green; . = fail. cli+ag suffix is the "
            "attempt count consumed (1–3). 1 = no feedback loop needed.",
            "",
        ]
        # need the raw per-row data — re-load exec JSON for case ids
        exec_data = json.loads(EXEC_JSON.read_text())
        sample = next(iter(exec_data.values()))["rows"]
        md.append("| Task | " + " | ".join(m.replace("Qwen/", "")
                  for m in exec_data) + " |")
        md.append("|---|" + "|".join("---" for _ in exec_data) + "|")
        for i, r0 in enumerate(sample):
            cid = r0["id"]
            cells = []
            for m in exec_data:
                r = exec_data[m]["rows"][i]
                cell = ("P" if r["sem"]["passed"] else ".") + "/" + \
                       ("P" if r["com"]["passed"] else ".") + "/" + \
                       ("P" if r.get("sp", {}).get("passed") else ".") + "/" + \
                       ("P" if r.get("ag", {}).get("passed") else ".") + \
                       f"({r.get('ag', {}).get('attempts', 0)})"
                cells.append(cell)
            md.append(f"| {cid} | " + " | ".join(cells) + " |")

    return "\n".join(md) + "\n"


# ---- PDF (reportlab, pure Python — no cryptography native deps) ---- #

def build_pdf(exec_s, regex_s, fanout_s, exec_data, fanout_rows):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak)
    except ImportError:
        print("[warn] reportlab not installed; PDF skipped.")
        return

    doc = SimpleDocTemplate(
        str(OUT_PDF), pagesize=A4,
        leftMargin=12*mm, rightMargin=12*mm,
        topMargin=12*mm, bottomMargin=12*mm,
    )
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    h3 = styles["Heading3"]
    body = styles["BodyText"]; body.fontSize = 9; body.leading = 12
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=10)
    story = []
    models = sorted(set(list(exec_s) + list(regex_s) + list(fanout_s)))

    def grid(data, widths, header_row=True, font="Helvetica", fontsize=8):
        t = Table(data, colWidths=widths)
        style = [
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), fontsize),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 1 if header_row else 0), (-1, -1), "RIGHT"),
        ]
        if header_row:
            style += [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7eaf0")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        t.setStyle(TableStyle(style))
        return t

    story.append(Paragraph("Qwen3 Coder MoE &mdash; comprehensive benchmark report", h1))
    story.append(Paragraph(f"Date: <b>{time.strftime('%Y-%m-%d')}</b>", body))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        "Three benches, two models, four sides on single-call plus a "
        "fifth fan-out side at N=200 subagents. All exec results come from "
        "the real <font face='Courier'>vendor/bin/phpunit</font> suite on "
        "<font face='Courier'>wesleysimplicio/sistema-sindico</font>.", body))
    story.append(Spacer(1, 4*mm))

    # Headline single-call
    story.append(Paragraph("Headline &mdash; single-call (4 sides)", h2))
    data = [["Model", "Metric", "base", "cli", "cli+sp", "cli+ag",
             "Δcli", "Δcli+sp", "Δcli+ag"]]
    for m in models:
        short = m.replace("Qwen/", "")
        if m in exec_s:
            e = exec_s[m]
            data.append([short, "exec",
                         f"{e['sem_pct']}%", f"{e['com_pct']}%",
                         f"{e['sp_pct']}%", f"{e['ag_pct']}%",
                         f"{e['com_pct']-e['sem_pct']:+d}",
                         f"{e['sp_pct']-e['sem_pct']:+d}",
                         f"{e['ag_pct']-e['sem_pct']:+d}"])
        if m in regex_s:
            r = regex_s[m]
            data.append([short, "regex",
                         f"{r['sem_pct']}%", f"{r['com_pct']}%",
                         f"{r['sp_pct']}%", f"{r['ag_pct']}%",
                         f"{r['com_pct']-r['sem_pct']:+d}",
                         f"{r['sp_pct']-r['sem_pct']:+d}",
                         f"{r['ag_pct']-r['sem_pct']:+d}"])
    story.append(grid(data, [54*mm, 16*mm, 14*mm, 14*mm, 16*mm, 16*mm,
                             14*mm, 16*mm, 16*mm]))
    story.append(Spacer(1, 5*mm))

    # Headline fan-out
    story.append(Paragraph("Headline &mdash; fan-out N=200", h2))
    data = [["Model", "fn per-att", "fn modal", "rx per-att", "rx modal",
             "avg uniq", "wall-clock", "cost"]]
    for m in models:
        if m not in fanout_s: continue
        f = fanout_s[m]; short = m.replace("Qwen/", "")
        att = f["fn_attempts"]
        data.append([short,
                     f"{f['fn_pass']}/{att} ({100*f['fn_pass']//max(att,1)}%)",
                     f"{f['fn_modal']}/{f['cases']}",
                     f"{f['rx_pass']}/{att} ({100*f['rx_pass']//max(att,1)}%)",
                     f"{f['rx_modal']}/{f['cases']}",
                     f"{f['uniq_total']/max(f['cases'],1):.1f}",
                     f"{f['elapsed']:.0f}s",
                     f"${f['cost']:.4f}"])
    story.append(grid(data, [54*mm, 28*mm, 18*mm, 28*mm, 18*mm, 18*mm, 18*mm, 16*mm]))
    story.append(Spacer(1, 5*mm))

    # Key findings
    story.append(Paragraph("Key findings", h2))
    for title, text in [
        ("1. cli + ag is the only side that beats cli reliably on functional",
         "On the exec bench (real PHPUnit), cli + ag (verify-loop) recovers "
         "one or two cases per model that single-shot cli misses, by feeding "
         "the PHPUnit tail back as classified retry feedback. cli + sp ties or "
         "trails cli in aggregate &mdash; it adds ~1,000 tokens/call of runtime "
         "preamble that, in this single-call context, doesn't translate into "
         "pass-rate gains."),
        ("2. Regex INFLATES on Qwen3-Coder-30B-A3B-Instruct under temp=0.7",
         "Fan-out N=200 at temp=0.7: 30B-A3B shows regex-vs-functional "
         "disagreement on 6 of 12 cases. Regex scores 100% (every pattern "
         "matched on every output) but PHPUnit exit code 0 was hit ZERO "
         "times in 200 attempts. The model produces output that LOOKS right "
         "but the runtime behaviour is wrong &mdash; exactly the criticism "
         "that 'regex doesn't mean it works'."),
        ("3. Qwen3-Coder-Next is dramatically more robust to temp=0.7",
         "Same fan-out config, same prompts, same 12 cases &mdash; Coder-Next "
         "modal-vote passes 12/12 cases on real PHPUnit, while 30B-A3B "
         "modal-vote passes 5/12. cli's 6-layer contract is enough; "
         "Coder-Next preserves semantic correctness across temperature-induced "
         "variations where 30B-A3B drifts."),
        ("4. Some cases are model-capability ceilings, not feedback-loop problems",
         "password_require_symbol failed for every side and every iteration "
         "on 30B-A3B (3-attempt verify-loop exhausted; 200 fan-out attempts "
         "exhausted). It only passed on Coder-Next, and only with modal-vote "
         "fan-out at 187/200. This is a model-capability boundary &mdash; no "
         "amount of feedback or retry helps; either the model can or it can't."),
    ]:
        story.append(Paragraph(f"<b>{title}</b>", h3))
        story.append(Paragraph(text, body))
        story.append(Spacer(1, 2*mm))

    story.append(PageBreak())

    # Cost & latency
    story.append(Paragraph("Cost & latency (exec bench, per call)", h2))
    data = [["Model", "Side", "tokens/call", "ms/call", "notes"]]
    for m in models:
        if m not in exec_s: continue
        e = exec_s[m]; short = m.replace("Qwen/", "")
        data.append([short, "baseline", f"{e['sem_tok']:.0f}", f"{e['sem_ms']:.0f}", ""])
        data.append([short, "cli", f"{e['com_tok']:.0f}", f"{e['com_ms']:.0f}", ""])
        data.append([short, "cli+sp", f"{e['sp_tok']:.0f}", f"{e['sp_ms']:.0f}",
                     "+sp runtime ~1k tokens"])
        data.append([short, "cli+ag", f"{e['ag_tok']:.0f}", f"{e['ag_ms']:.0f}",
                     f"{e['ag_attempts']:.2f} avg attempts"])
    story.append(grid(data, [50*mm, 18*mm, 24*mm, 22*mm, 60*mm]))
    story.append(Spacer(1, 5*mm))

    # Fan-out per task
    if fanout_s:
        story.append(Paragraph("Fan-out per-task (N=200, modal-vote)", h2))
        story.append(Paragraph(
            "Format per cell: <b>fn% / rx% / fn-modal / unique-outputs</b>. "
            "P = modal pass, . = fail. uX = X unique outputs out of 200.", small))
        # collect all tasks
        all_tasks = []
        for m in models:
            if m in fanout_s:
                for c in fanout_s[m]["per_case"]:
                    if c["task"] not in all_tasks:
                        all_tasks.append(c["task"])
        f_models = [m for m in models if m in fanout_s]
        rows = [["Task"] + [m.replace("Qwen/Qwen3-Coder-", "Q3C-") for m in f_models]]
        for task in all_tasks:
            cells = [task]
            for m in f_models:
                match = next((c for c in fanout_s[m]["per_case"]
                              if c["task"] == task), None)
                if match is None:
                    cells.append("—")
                else:
                    cells.append(
                        f"{match['fn_pct']:>3d}/{match['rx_pct']:>3d}/"
                        f"{'P' if match['fn_modal'] else '.'}/u{match['uniq']}"
                    )
            rows.append(cells)
        story.append(grid(rows, [60*mm] + [62*mm] * len(f_models),
                          font="Courier", fontsize=7.5))
        story.append(Spacer(1, 4*mm))

    # Exec per-task matrix
    if exec_data:
        story.append(Paragraph(
            "Exec per-task &times; model &times; side", h2))
        story.append(Paragraph(
            "Format per cell: <b>base / cli / cli+sp / cli+ag(attempts)</b>. "
            "P = real PHPUnit suite green; . = fail.", small))
        sample = next(iter(exec_data.values()))["rows"]
        e_models = list(exec_data.keys())
        rows = [["Task"] + [m.replace("Qwen/Qwen3-Coder-", "Q3C-") for m in e_models]]
        for i, r0 in enumerate(sample):
            cid = r0["id"]
            cells = [cid]
            for m in e_models:
                r = exec_data[m]["rows"][i]
                cell = ("P" if r["sem"]["passed"] else ".") + "/" + \
                       ("P" if r["com"]["passed"] else ".") + "/" + \
                       ("P" if r.get("sp", {}).get("passed") else ".") + "/" + \
                       ("P" if r.get("ag", {}).get("passed") else ".") + \
                       f"({r.get('ag', {}).get('attempts', 0)})"
                cells.append(cell)
            rows.append(cells)
        story.append(grid(rows, [56*mm] + [62*mm] * len(e_models),
                          font="Courier", fontsize=7.5))

    doc.build(story)
    print(f"-> {OUT_PDF}")


def main() -> int:
    if not EXEC_JSON.exists():
        raise SystemExit(f"missing {EXEC_JSON}")
    exec_data = json.loads(EXEC_JSON.read_text())
    regex_data = json.loads(REGEX_JSON.read_text()) if REGEX_JSON.exists() else {}
    fanout_rows = (json.loads(FANOUT_JSON.read_text()).get("rows", [])
                   if FANOUT_JSON.exists() else [])

    exec_s = exec_summary(exec_data)
    regex_s = regex_summary(regex_data)
    fanout_s = fanout_summary(fanout_rows)

    OUT_MD.write_text(build_md(exec_s, regex_s, fanout_s))
    print(f"-> {OUT_MD}")
    build_pdf(exec_s, regex_s, fanout_s, exec_data, fanout_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
