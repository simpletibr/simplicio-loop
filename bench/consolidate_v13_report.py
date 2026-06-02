#!/usr/bin/env python3
"""
consolidate_v13_report.py — 5-side consolidated PDF + MD for the v13 batch.

Reads:
  bench/results_exec_sindico.json   (exec, 5 sides: sem/com/sp/ag/spag)
  bench/results.json                 (regex, 5 sides idem)

Writes:
  bench/results_v13_5side.md
  bench/results_v13_5side.pdf

Sides under test (in the bench JSON keys):
  sem   = baseline (raw goal, no simplicio)
  com   = cli alone (6-layer contract)
  sp    = cli + sp (composition, sp runtime wrapping cli)
  ag    = cli + ag (cli + verify-loop with PHPUnit/regex feedback)
  spag  = cli + sp + ag (sp-wrapped cli as the verify-loop seed)
"""
from __future__ import annotations
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXEC_JSON = ROOT / "bench" / "results_exec_sindico.json"
REGEX_JSON = ROOT / "bench" / "results.json"
OUT_MD = ROOT / "bench" / "results_v13_5side.md"
OUT_PDF = ROOT / "bench" / "results_v13_5side.pdf"


SIDE_LABELS = {
    "sem":  "baseline",
    "com":  "cli alone",
    "sp":   "cli + sp",
    "ag":   "cli + ag",
    "spag": "cli + sp + ag",
}


def exec_per_model(by_model: dict) -> list[dict]:
    out = []
    for model, b in by_model.items():
        rows = b.get("rows", [])
        n = b.get("n") or len(rows)
        def avg(side, key):
            vs = [r[side].get(key, 0) for r in rows if side in r and isinstance(r[side], dict)]
            return sum(vs) / max(len(vs), 1) if vs else 0
        out.append({
            "model": model,
            "n": n,
            "sem_pct": b.get("sem_pct", 0),
            "com_pct": b.get("com_pct", 0),
            "sp_pct":  b.get("sp_pct", 0),
            "ag_pct":  b.get("ag_pct", 0),
            "spag_pct": b.get("spag_pct", 0),
            "ag_avg_attempts":   avg("ag", "attempts"),
            "spag_avg_attempts": avg("spag", "attempts"),
            "sem_tok":  avg("sem", "tokens"),
            "com_tok":  avg("com", "tokens"),
            "sp_tok":   avg("sp", "tokens"),
            "ag_tok":   avg("ag", "tokens"),
            "spag_tok": avg("spag", "tokens"),
            "sem_ms":   avg("sem", "ms"),
            "com_ms":   avg("com", "ms"),
            "sp_ms":    avg("sp", "ms"),
            "ag_ms":    avg("ag", "ms"),
            "spag_ms":  avg("spag", "ms"),
        })
    return out


def regex_per_model(by_model: dict) -> list[dict]:
    out = []
    for model, b in by_model.items():
        out.append({
            "model": model,
            "n": b.get("total", 0),
            "sem_pct":  b.get("sem_pct", 0),
            "com_pct":  b.get("com_pct", 0),
            "sp_pct":   b.get("sp_pct", 0),
            "ag_pct":   b.get("ag_pct", 0),
            "spag_pct": b.get("spag_pct", 0),
        })
    return out


def fmt(p: int) -> str: return f"{p}%"
def delta(a: int, b: int) -> str: return f"**{a-b:+d}**"


def build_md(exec_rows: list, regex_rows: list, exec_raw: dict) -> str:
    md = [
        "# 5-side comparison — v13 (baseline / cli / cli+sp / cli+ag / cli+sp+ag)",
        "",
        f"Date: **{time.strftime('%Y-%m-%d')}**",
        "",
        "Five sides on **two metrics** (functional/PHPUnit + regex), three models.",
        "",
        "## Sides",
        "",
        "| key | label | description |",
        "|---|---|---|",
        "| `sem`  | baseline       | raw one-line goal. No simplicio anywhere. |",
        "| `com`  | cli alone      | the simplicio-cli 6-layer task contract (role/stack, goal, target, criteria, constraints, output shape). |",
        "| `sp`   | cli + sp       | simplicio-prompt v1.9 runtime wrapping the cli 6-layer as user-input-X. Composition. |",
        "| `ag`   | cli + ag       | cli 6-layer as the seed of the verify-loop (PHPUnit tail / missing-pattern feedback over up to 3 attempts). |",
        "| `spag` | cli + sp + ag  | **full stack:** sp-wrapped cli as the verify-loop seed. Composition + retry. |",
        "",
        "## Benches",
        "",
        "| bench | n | oracle |",
        "|---|---|---|",
        "| exec   | 12 | real `vendor/bin/phpunit` on `wesleysimplicio/sistema-sindico` |",
        "| regex  | 10 | structural pattern match per `bench/cases_offline.json` |",
        "",
        "## Models",
        "",
    ]
    for r in exec_rows:
        md.append(f"- `{r['model']}` (n={r['n']})")
    md += [
        "",
        "## Headline — pct per side, both metrics",
        "",
        "| Model | metric | base | cli | cli+sp | cli+ag | cli+sp+ag | Δcli | Δsp | Δag | Δsp+ag |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    # Index regex rows by model so we can join
    regex_by = {r["model"]: r for r in regex_rows}
    for e in exec_rows:
        short = e["model"].split("/")[-1]
        md.append(
            f"| `{short}` | exec | "
            f"{fmt(e['sem_pct'])} | {fmt(e['com_pct'])} | "
            f"{fmt(e['sp_pct'])} | {fmt(e['ag_pct'])} | {fmt(e['spag_pct'])} | "
            f"{delta(e['com_pct'], e['sem_pct'])} | "
            f"{delta(e['sp_pct'], e['sem_pct'])} | "
            f"{delta(e['ag_pct'], e['sem_pct'])} | "
            f"{delta(e['spag_pct'], e['sem_pct'])} |"
        )
        rr = regex_by.get(e["model"])
        if rr:
            md.append(
                f"| `{short}` | regex | "
                f"{fmt(rr['sem_pct'])} | {fmt(rr['com_pct'])} | "
                f"{fmt(rr['sp_pct'])} | {fmt(rr['ag_pct'])} | {fmt(rr['spag_pct'])} | "
                f"{delta(rr['com_pct'], rr['sem_pct'])} | "
                f"{delta(rr['sp_pct'], rr['sem_pct'])} | "
                f"{delta(rr['ag_pct'], rr['sem_pct'])} | "
                f"{delta(rr['spag_pct'], rr['sem_pct'])} |"
            )

    md += [
        "",
        "## Verify-loop convergence (exec)",
        "",
        "Average attempts consumed by the ag-based sides (1=passed first try; 3=ran loop to exhaustion).",
        "",
        "| Model | cli+ag avg | cli+sp+ag avg |",
        "|---|---|---|",
    ]
    for e in exec_rows:
        md.append(
            f"| `{e['model'].split('/')[-1]}` | "
            f"{e['ag_avg_attempts']:.2f} | {e['spag_avg_attempts']:.2f} |"
        )

    md += [
        "",
        "## Cost & latency (exec, per call avg)",
        "",
        "Tokens/call and ms/call averaged across the 12 cases. ag-based sides sum across attempts.",
        "",
        "| Model | side | tokens/call | ms/call |",
        "|---|---|---|---|",
    ]
    for e in exec_rows:
        s = e["model"].split("/")[-1]
        for side in ("sem", "com", "sp", "ag", "spag"):
            tok = e[f"{side}_tok"]; ms = e[f"{side}_ms"]
            md.append(f"| `{s}` | {SIDE_LABELS[side]} | {tok:.0f} | {ms:.0f} |")

    md += [
        "",
        "## Per-task × model (exec, base / cli / cli+sp / cli+ag / cli+sp+ag)",
        "",
        "Format per cell: `b/c/s/a/sa` where each char is `P` (pass) or `.` (fail).",
        "",
        "| Task | " + " | ".join(m["model"].split("/")[-1] for m in exec_rows) + " |",
        "|---|" + "|".join("---" for _ in exec_rows) + "|",
    ]
    sample = list(exec_raw.values())[0]["rows"] if exec_raw else []
    for i, r0 in enumerate(sample):
        cid = r0["id"]
        cells = []
        for em in exec_rows:
            row = exec_raw[em["model"]]["rows"][i]
            cell = (
                ("P" if row["sem"]["passed"] else ".") + "/" +
                ("P" if row["com"]["passed"] else ".") + "/" +
                ("P" if row.get("sp", {}).get("passed") else ".") + "/" +
                ("P" if row.get("ag", {}).get("passed") else ".") + "/" +
                ("P" if row.get("spag", {}).get("passed") else ".")
            )
            cells.append(cell)
        md.append(f"| {cid} | " + " | ".join(cells) + " |")

    return "\n".join(md) + "\n"


def build_pdf(exec_rows, regex_rows, exec_raw):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak)
    except ImportError:
        print("[warn] reportlab not installed; PDF skipped.")
        return
    doc = SimpleDocTemplate(
        str(OUT_PDF), pagesize=landscape(A4),
        leftMargin=10*mm, rightMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm,
    )
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]; body.fontSize = 9; body.leading = 12
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=10)
    story = []

    def grid(data, widths, font="Helvetica", fontsize=8):
        t = Table(data, colWidths=widths)
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), fontsize),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7eaf0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]))
        return t

    story.append(Paragraph("simplicio-py bench v13 — 5-side comparison (baseline / cli / cli+sp / cli+ag / cli+sp+ag)", h1))
    story.append(Paragraph(f"Date: <b>{time.strftime('%Y-%m-%d')}</b>", body))
    story.append(Spacer(1, 3*mm))

    story.append(Paragraph("Sides", h2))
    story.append(Paragraph(
        "<b>sem</b> = baseline (raw goal). <b>com</b> = cli alone (6-layer). "
        "<b>sp</b> = sp runtime wrapping cli (composition). "
        "<b>ag</b> = cli + verify-loop (up to 3 attempts with PHPUnit/missing-pattern feedback). "
        "<b>spag</b> = sp-wrapped cli as the verify-loop seed (full stack composition + retry).",
        body))
    story.append(Spacer(1, 3*mm))

    story.append(Paragraph("Models tested", h2))
    for r in exec_rows:
        story.append(Paragraph(f"&bull; <font face='Courier'>{r['model']}</font> "
                              f"(n={r['n']} cases)", body))
    story.append(Spacer(1, 4*mm))

    # Headline table
    story.append(Paragraph("Headline &mdash; pct per side, both metrics", h2))
    data = [["Model", "Metric", "base", "cli", "cli+sp", "cli+ag", "cli+sp+ag",
             "Δcli", "Δsp", "Δag", "Δsp+ag"]]
    regex_by = {r["model"]: r for r in regex_rows}
    for e in exec_rows:
        short = e["model"].split("/")[-1]
        data.append([short, "exec",
                     f"{e['sem_pct']}%", f"{e['com_pct']}%",
                     f"{e['sp_pct']}%", f"{e['ag_pct']}%", f"{e['spag_pct']}%",
                     f"{e['com_pct']-e['sem_pct']:+d}",
                     f"{e['sp_pct']-e['sem_pct']:+d}",
                     f"{e['ag_pct']-e['sem_pct']:+d}",
                     f"{e['spag_pct']-e['sem_pct']:+d}"])
        rr = regex_by.get(e["model"])
        if rr:
            data.append([short, "regex",
                         f"{rr['sem_pct']}%", f"{rr['com_pct']}%",
                         f"{rr['sp_pct']}%", f"{rr['ag_pct']}%", f"{rr['spag_pct']}%",
                         f"{rr['com_pct']-rr['sem_pct']:+d}",
                         f"{rr['sp_pct']-rr['sem_pct']:+d}",
                         f"{rr['ag_pct']-rr['sem_pct']:+d}",
                         f"{rr['spag_pct']-rr['sem_pct']:+d}"])
    story.append(grid(data, [70*mm, 14*mm, 14*mm, 14*mm, 18*mm, 18*mm, 20*mm,
                             14*mm, 14*mm, 14*mm, 16*mm]))
    story.append(Spacer(1, 5*mm))

    # Convergence
    story.append(Paragraph("Verify-loop convergence (avg attempts)", h2))
    data = [["Model", "cli+ag avg", "cli+sp+ag avg"]]
    for e in exec_rows:
        data.append([e["model"].split("/")[-1],
                     f"{e['ag_avg_attempts']:.2f}",
                     f"{e['spag_avg_attempts']:.2f}"])
    story.append(grid(data, [120*mm, 40*mm, 40*mm]))
    story.append(Spacer(1, 5*mm))

    # Cost & latency
    story.append(Paragraph("Cost &amp; latency (exec, per call avg)", h2))
    data = [["Model", "Side", "tokens/call", "ms/call"]]
    for e in exec_rows:
        s = e["model"].split("/")[-1]
        for side in ("sem", "com", "sp", "ag", "spag"):
            data.append([s, SIDE_LABELS[side],
                         f"{e[f'{side}_tok']:.0f}",
                         f"{e[f'{side}_ms']:.0f}"])
    story.append(grid(data, [100*mm, 40*mm, 35*mm, 30*mm]))
    story.append(PageBreak())

    # Per-task matrix
    story.append(Paragraph("Per-task &times; model (exec)", h2))
    story.append(Paragraph(
        "Format: <b>base/cli/cli+sp/cli+ag/cli+sp+ag</b> &mdash; P=pass, .=fail.", small))
    sample = list(exec_raw.values())[0]["rows"] if exec_raw else []
    hdr = ["Task"] + [m["model"].split("/")[-1] for m in exec_rows]
    rows = [hdr]
    for i, r0 in enumerate(sample):
        cid = r0["id"]
        cells = [cid]
        for em in exec_rows:
            row = exec_raw[em["model"]]["rows"][i]
            cell = (
                ("P" if row["sem"]["passed"] else ".") + "/" +
                ("P" if row["com"]["passed"] else ".") + "/" +
                ("P" if row.get("sp", {}).get("passed") else ".") + "/" +
                ("P" if row.get("ag", {}).get("passed") else ".") + "/" +
                ("P" if row.get("spag", {}).get("passed") else ".")
            )
            cells.append(cell)
        rows.append(cells)
    story.append(grid(rows, [55*mm] + [70*mm] * len(exec_rows),
                      font="Courier", fontsize=8))

    doc.build(story)
    print(f"-> {OUT_PDF}")


def main() -> int:
    if not EXEC_JSON.exists():
        raise SystemExit(f"missing {EXEC_JSON}")
    exec_raw = json.loads(EXEC_JSON.read_text())
    regex_raw = json.loads(REGEX_JSON.read_text()) if REGEX_JSON.exists() else {}
    exec_rows = exec_per_model(exec_raw)
    regex_rows = regex_per_model(regex_raw)
    OUT_MD.write_text(build_md(exec_rows, regex_rows, exec_raw))
    print(f"-> {OUT_MD}")
    build_pdf(exec_rows, regex_rows, exec_raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
