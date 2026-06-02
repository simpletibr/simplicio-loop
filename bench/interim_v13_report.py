#!/usr/bin/env python3
"""interim_v13_report.py — parse the running batch logs and emit a snapshot
report so we can show progress while exec_v13 / regex_v13 are still running.

Reads:
  /tmp/exec_v13.log
  /tmp/regex_v13.log

Writes:
  bench/results_v13_interim.md
  bench/results_v13_interim.pdf
"""
from __future__ import annotations
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXEC_LOG = Path("/tmp/exec_v13.log")
REGEX_LOG = Path("/tmp/regex_v13.log")
OUT_MD = ROOT / "bench" / "results_v13_interim.md"
OUT_PDF = ROOT / "bench" / "results_v13_interim.pdf"


_EXEC_MODEL = re.compile(r"^=== (\S+) \(endpoint:")
_EXEC_CASE = re.compile(
    r"^\s+(\S+)\s+baseline\s+(PASS|fail)\s+"
    r"cli\s+(PASS|fail)\s+"
    r"cli\+sp\s+(PASS|fail)\s+"
    r"cli\+ag\s+(PASS|fail)\((\d+)/\d+\)\s+"
    r"cli\+sp\+ag\s+(PASS|fail)\((\d+)/\d+\)"
)
_EXEC_FINAL = re.compile(
    r"^\s+-> baseline (\d+)/(\d+) \(\d+%\) \| cli (\d+)/\d+ \(\d+%\) "
    r"\| sp (\d+)/\d+ \(\d+%\) \| ag (\d+)/\d+ \(\d+%\) "
    r"\| sp\+ag (\d+)/\d+ \(\d+%\)"
)

_REGEX_MODEL = re.compile(r"^=== model: (\S+)")
_REGEX_CASE = re.compile(
    r"^\s+\[(\d+)/\d+\]\s+(\S+)\s+"
    r"sem (\d+)/(\d+) com (\d+)/\d+\s+"
    r"sp (\d+)/\d+\s+"
    r"ag (\d+)/\d+\(\d+\)\s+"
    r"sp\+ag (\d+)/\d+\(\d+\)"
)
_REGEX_FINAL = re.compile(
    r"^\s+-> baseline (\d+)/(\d+) \(\d+%\) \| cli (\d+)/\d+ \(\d+%\) "
    r"\| sp (\d+)/\d+ \(\d+%\) \| ag (\d+)/\d+ \(\d+%\) "
    r"\| sp\+ag (\d+)/\d+ \(\d+%\)"
)


def parse_exec(log: str) -> dict:
    out = {}
    current = None
    for line in log.splitlines():
        m = _EXEC_MODEL.match(line)
        if m:
            current = m.group(1)
            out[current] = {"cases": [], "final": None}
            continue
        if current is None:
            continue
        m = _EXEC_CASE.match(line)
        if m:
            out[current]["cases"].append({
                "id": m.group(1),
                "sem": m.group(2) == "PASS",
                "com": m.group(3) == "PASS",
                "sp":  m.group(4) == "PASS",
                "ag":  m.group(5) == "PASS",
                "ag_attempts": int(m.group(6)),
                "spag": m.group(7) == "PASS",
                "spag_attempts": int(m.group(8)),
            })
            continue
        m = _EXEC_FINAL.match(line)
        if m:
            n = int(m.group(2))
            out[current]["final"] = {
                "n": n,
                "sem": int(m.group(1)), "com": int(m.group(3)),
                "sp": int(m.group(4)), "ag": int(m.group(5)),
                "spag": int(m.group(6)),
            }
    return out


def parse_regex(log: str) -> dict:
    out = {}
    current = None
    for line in log.splitlines():
        m = _REGEX_MODEL.match(line)
        if m:
            current = m.group(1)
            out[current] = {"cases": [], "final": None}
            continue
        if current is None:
            continue
        m = _REGEX_CASE.match(line)
        if m:
            t = int(m.group(4))
            out[current]["cases"].append({
                "i": int(m.group(1)), "stack": m.group(2),
                "sem": int(m.group(3)), "com": int(m.group(5)),
                "sp":  int(m.group(6)), "ag":  int(m.group(7)),
                "spag": int(m.group(8)), "total": t,
            })
            continue
        m = _REGEX_FINAL.match(line)
        if m:
            total = int(m.group(2))
            out[current]["final"] = {
                "total": total,
                "sem": int(m.group(1)), "com": int(m.group(3)),
                "sp": int(m.group(4)), "ag": int(m.group(5)),
                "spag": int(m.group(6)),
            }
    return out


def _pct(n, d):
    return f"{100*n//max(d,1)}%"


def _delta(a, b):
    return f"**{a-b:+d}**"


def build_md(exec_state: dict, regex_state: dict) -> str:
    md = [
        "# v13 INTERIM — bench em andamento (snapshot dos logs ao vivo)",
        "",
        f"Captura: **{time.strftime('%Y-%m-%d %H:%M:%S')}**",
        "",
        "Parser dos logs `/tmp/exec_v13.log` e `/tmp/regex_v13.log`. Modelos com "
        "linha `-> baseline …` ESTÃO completos; modelos sem ela ainda rodam (mostro o que veio até agora).",
        "",
        "## Sides",
        "",
        "- `sem`  = baseline (raw goal)",
        "- `com`  = cli alone (6-layer contract)",
        "- `sp`   = cli + sp (composition)",
        "- `ag`   = cli + ag (verify-loop max 3 attempts)",
        "- `spag` = cli + sp + ag (composition + verify-loop)",
        "",
    ]
    all_models = list(dict.fromkeys(list(exec_state.keys()) + list(regex_state.keys())))

    md += ["## Headline — fechados (`-> baseline ...`)", ""]
    closed_any = False
    for m in all_models:
        ex = exec_state.get(m, {}).get("final")
        rx = regex_state.get(m, {}).get("final")
        if not ex and not rx:
            continue
        closed_any = True
        short = m.split("/")[-1]
        md.append(f"### `{short}`")
        md.append("")
        md.append("| metric | base | cli | cli+sp | cli+ag | cli+sp+ag | Δcli | Δsp | Δag | Δsp+ag |")
        md.append("|---|---|---|---|---|---|---|---|---|---|")
        if ex:
            n = ex["n"]
            md.append(
                f"| exec  (n={n})  | "
                f"{_pct(ex['sem'], n)} | {_pct(ex['com'], n)} | "
                f"{_pct(ex['sp'], n)} | {_pct(ex['ag'], n)} | {_pct(ex['spag'], n)} | "
                f"{_delta(100*ex['com']//n, 100*ex['sem']//n)} | "
                f"{_delta(100*ex['sp']//n, 100*ex['sem']//n)} | "
                f"{_delta(100*ex['ag']//n, 100*ex['sem']//n)} | "
                f"{_delta(100*ex['spag']//n, 100*ex['sem']//n)} |"
            )
        if rx:
            t = rx["total"]
            md.append(
                f"| regex (t={t}) | "
                f"{_pct(rx['sem'], t)} | {_pct(rx['com'], t)} | "
                f"{_pct(rx['sp'], t)} | {_pct(rx['ag'], t)} | {_pct(rx['spag'], t)} | "
                f"{_delta(100*rx['com']//t, 100*rx['sem']//t)} | "
                f"{_delta(100*rx['sp']//t, 100*rx['sem']//t)} | "
                f"{_delta(100*rx['ag']//t, 100*rx['sem']//t)} | "
                f"{_delta(100*rx['spag']//t, 100*rx['sem']//t)} |"
            )
        md.append("")
    if not closed_any:
        md.append("_(nenhum modelo fechou ainda)_")

    # In-progress section
    md += ["", "## Em andamento (parcial)", ""]
    any_progress = False
    for m in all_models:
        ex_cases = exec_state.get(m, {}).get("cases", [])
        ex_final = exec_state.get(m, {}).get("final")
        rx_cases = regex_state.get(m, {}).get("cases", [])
        rx_final = regex_state.get(m, {}).get("final")
        if (ex_cases and not ex_final) or (rx_cases and not rx_final):
            any_progress = True
            short = m.split("/")[-1]
            md.append(f"### `{short}`")
            md.append("")
            if ex_cases and not ex_final:
                ex_p = lambda k: sum(1 for c in ex_cases if c[k])
                n_so_far = len(ex_cases)
                md.append(
                    f"**exec** progresso: {n_so_far}/12  base={ex_p('sem')}  "
                    f"cli={ex_p('com')}  cli+sp={ex_p('sp')}  cli+ag={ex_p('ag')}  "
                    f"cli+sp+ag={ex_p('spag')}"
                )
            if rx_cases and not rx_final:
                rx_p = lambda k: sum(c[k] for c in rx_cases)
                t_so_far = sum(c["total"] for c in rx_cases)
                md.append(
                    f"**regex** progresso: {len(rx_cases)}/10  base={rx_p('sem')}/{t_so_far}  "
                    f"cli={rx_p('com')}/{t_so_far}  cli+sp={rx_p('sp')}/{t_so_far}  "
                    f"cli+ag={rx_p('ag')}/{t_so_far}  cli+sp+ag={rx_p('spag')}/{t_so_far}"
                )
            md.append("")
    if not any_progress:
        md.append("_(nenhum modelo em andamento — todos fecharam ou nem começaram)_")

    # Per-task exec matrix (closed models only)
    closed_models = [m for m in all_models if exec_state.get(m, {}).get("final")]
    if closed_models:
        md += ["", "## Per-task exec (modelos fechados)", "",
               "Format: `b/c/s/a/sa` (P=pass, .=fail)", ""]
        # Use first closed model's case order
        first_cases = exec_state[closed_models[0]]["cases"]
        case_ids = [c["id"] for c in first_cases]
        header = "| Task | " + " | ".join(m.split("/")[-1] for m in closed_models) + " |"
        sep    = "|---|" + "|".join("---" for _ in closed_models) + "|"
        md += [header, sep]
        for i, cid in enumerate(case_ids):
            cells = []
            for m in closed_models:
                c = exec_state[m]["cases"][i] if i < len(exec_state[m]["cases"]) else None
                if c is None:
                    cells.append("—")
                    continue
                cells.append(
                    ("P" if c["sem"] else ".") + "/" +
                    ("P" if c["com"] else ".") + "/" +
                    ("P" if c["sp"] else ".") + "/" +
                    ("P" if c["ag"] else ".") + "/" +
                    ("P" if c["spag"] else ".")
                )
            md.append(f"| `{cid}` | " + " | ".join(cells) + " |")

    return "\n".join(md) + "\n"


def build_pdf(exec_state, regex_state):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak)
    except ImportError:
        print("[warn] reportlab missing; PDF skipped.")
        return
    doc = SimpleDocTemplate(str(OUT_PDF), pagesize=landscape(A4),
                            leftMargin=10*mm, rightMargin=10*mm,
                            topMargin=10*mm, bottomMargin=10*mm)
    s = getSampleStyleSheet()
    h1, h2 = s["Heading1"], s["Heading2"]
    body = s["BodyText"]; body.fontSize = 9; body.leading = 12
    small = ParagraphStyle("small", parent=body, fontSize=8)
    story = []

    def grid(rows, widths, font="Helvetica", fontsize=8):
        t = Table(rows, colWidths=widths)
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

    story.append(Paragraph("simplicio-py bench v13 — INTERIM (5 sides, batch em andamento)", h1))
    story.append(Paragraph(f"Captura: <b>{time.strftime('%Y-%m-%d %H:%M:%S')}</b>", body))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        "Snapshot parseado dos logs ao vivo. Modelos com headline (Llama-3B) já fecharam; "
        "Gemma-4B em andamento; Qwen-Coder-32B ainda nem começou. Vou regenerar o "
        "PDF final quando os 3 modelos × 2 benches × 5 lados fecharem.", body))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph("Sides", h2))
    story.append(Paragraph(
        "<b>sem</b> = baseline (raw goal) &middot; <b>com</b> = cli alone (6-layer) &middot; "
        "<b>sp</b> = cli + sp (composition) &middot; <b>ag</b> = cli + ag (verify-loop max 3) &middot; "
        "<b>spag</b> = cli + sp + ag (composition + retry)", body))
    story.append(Spacer(1, 4*mm))

    all_models = list(dict.fromkeys(list(exec_state.keys()) + list(regex_state.keys())))

    # Headline closed
    story.append(Paragraph("Headline &mdash; modelos fechados", h2))
    closed_rows = [["Model", "Metric", "base", "cli", "cli+sp", "cli+ag", "cli+sp+ag",
                    "Δcli", "Δsp", "Δag", "Δsp+ag"]]
    any_closed = False
    for m in all_models:
        ex = exec_state.get(m, {}).get("final")
        rx = regex_state.get(m, {}).get("final")
        short = m.split("/")[-1]
        if ex:
            any_closed = True
            n = ex["n"]
            closed_rows.append([
                short, "exec",
                f"{100*ex['sem']//n}%", f"{100*ex['com']//n}%",
                f"{100*ex['sp']//n}%", f"{100*ex['ag']//n}%",
                f"{100*ex['spag']//n}%",
                f"{100*ex['com']//n - 100*ex['sem']//n:+d}",
                f"{100*ex['sp']//n - 100*ex['sem']//n:+d}",
                f"{100*ex['ag']//n - 100*ex['sem']//n:+d}",
                f"{100*ex['spag']//n - 100*ex['sem']//n:+d}",
            ])
        if rx:
            any_closed = True
            t = rx["total"]
            closed_rows.append([
                short, "regex",
                f"{100*rx['sem']//t}%", f"{100*rx['com']//t}%",
                f"{100*rx['sp']//t}%", f"{100*rx['ag']//t}%",
                f"{100*rx['spag']//t}%",
                f"{100*rx['com']//t - 100*rx['sem']//t:+d}",
                f"{100*rx['sp']//t - 100*rx['sem']//t:+d}",
                f"{100*rx['ag']//t - 100*rx['sem']//t:+d}",
                f"{100*rx['spag']//t - 100*rx['sem']//t:+d}",
            ])
    if any_closed:
        story.append(grid(closed_rows, [60*mm, 14*mm, 14*mm, 14*mm, 18*mm, 18*mm, 20*mm,
                                        14*mm, 14*mm, 14*mm, 16*mm]))
    else:
        story.append(Paragraph("<i>nenhum modelo fechou ainda</i>", body))
    story.append(Spacer(1, 5*mm))

    # In-progress
    story.append(Paragraph("Em andamento (parcial)", h2))
    prog_rows = [["Model", "Bench", "Cases done / total", "Tally so far"]]
    any_prog = False
    for m in all_models:
        ex_cases = exec_state.get(m, {}).get("cases", [])
        ex_final = exec_state.get(m, {}).get("final")
        rx_cases = regex_state.get(m, {}).get("cases", [])
        rx_final = regex_state.get(m, {}).get("final")
        short = m.split("/")[-1]
        if ex_cases and not ex_final:
            any_prog = True
            ex_p = lambda k: sum(1 for c in ex_cases if c[k])
            prog_rows.append([
                short, "exec", f"{len(ex_cases)}/12",
                f"base={ex_p('sem')} cli={ex_p('com')} sp={ex_p('sp')} "
                f"ag={ex_p('ag')} spag={ex_p('spag')}"])
        if rx_cases and not rx_final:
            any_prog = True
            rx_p = lambda k: sum(c[k] for c in rx_cases)
            t_so_far = sum(c["total"] for c in rx_cases)
            prog_rows.append([
                short, "regex", f"{len(rx_cases)}/10",
                f"base={rx_p('sem')}/{t_so_far} cli={rx_p('com')}/{t_so_far} "
                f"sp={rx_p('sp')}/{t_so_far} ag={rx_p('ag')}/{t_so_far} "
                f"spag={rx_p('spag')}/{t_so_far}"])
    if any_prog:
        story.append(grid(prog_rows, [55*mm, 18*mm, 25*mm, 130*mm]))
    else:
        story.append(Paragraph("<i>nenhum modelo em andamento</i>", body))

    doc.build(story)
    print(f"-> {OUT_PDF}")


def main() -> int:
    exec_state = parse_exec(EXEC_LOG.read_text()) if EXEC_LOG.exists() else {}
    regex_state = parse_regex(REGEX_LOG.read_text()) if REGEX_LOG.exists() else {}
    OUT_MD.write_text(build_md(exec_state, regex_state))
    print(f"-> {OUT_MD}")
    build_pdf(exec_state, regex_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
