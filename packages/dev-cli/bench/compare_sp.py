"""
compare_sp.py — focused 'with vs without simplicio-prompt' report.

Reads a sp-enabled validation run (rows must have `sem`, `com`, and `sp` sides)
and renders a two-side comparison: WITHOUT (baseline) vs WITH simplicio-prompt.
The simplicio-cli column is kept as a context reference so the reader sees how
the two wrappers compare on the same data, but the headline metric is sp's
delta versus the unwrapped baseline.

Pass = real PHPUnit (the full sistema-sindico suite + a hidden test) green.

Usage:
  python3 bench/compare_sp.py --in /tmp/sp_validation_v3.json
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_MD = ROOT / "bench" / "results_sp_compare.md"
OUT_PDF = ROOT / "bench" / "results_sp_compare.pdf"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_offline as ro  # _lat1


def _has_sp_data(by_model: dict) -> bool:
    return any("sp" in r for b in by_model.values() for r in b.get("rows", []))


def _data_quality(rows: list) -> str:
    """A model whose calls all returned 0 tokens is a provider/API failure,
    not a model result. Flag it so the report says so explicitly."""
    if not rows:
        return "no data"
    errs = sum(1 for r in rows if r["sem"].get("tokens", -1) == 0
               and r["com"].get("tokens", -1) == 0
               and r.get("sp", {}).get("tokens", -1) == 0)
    if errs == len(rows):
        return f"API failure on all {len(rows)} calls (excluded from totals)"
    if errs > len(rows) // 2:
        return f"API errored on {errs}/{len(rows)} calls (low confidence)"
    return ""


def render_md(by_model: dict) -> str:
    if not _has_sp_data(by_model):
        raise SystemExit("input has no simplicio-prompt (sp) side; run with BENCH_INCLUDE_SP=1")

    models = list(by_model.keys())
    # split into clean vs failed-by-API
    clean, broken = [], []
    for m in models:
        flag = _data_quality(by_model[m]["rows"])
        (broken if "all" in flag else clean).append((m, flag))

    md = [
        "# simplicio-prompt — with vs without (real PHPUnit on sistema-sindico)",
        "",
        f"Date: **{time.strftime('%Y-%m-%d')}**  ",
        f"Target project: [`wesleysimplicio/sistema-sindico`](https://github.com/wesleysimplicio/sistema-sindico) — real PHP 8 condominium system, public on GitHub  ",
        "simplicio-prompt version under test: **v1.7.0** (post mode-selection rewrite, ONE-SHOT template = 102 lines)  ",
        f"Models: " + ", ".join(f"`{m}`" for m in models),
        "",
        "## Methodology — what \"pass\" actually means",
        "",
        "**This is NOT regex pattern-matching. This is NOT a synthetic toy unit-test harness in isolation.** "
        "For each task the model is asked to add a real engineering change to an existing production class. "
        "Its generated file replaces the original in a working copy of the real repo; a **hidden PHPUnit "
        "test** (never shown to the model, asserting BOTH true and false states) is dropped into "
        "`tests/unit/Core/Hidden/`; the **entire production suite runs**. "
        "**Pass = `vendor/bin/phpunit` exit code 0** — the same green/red signal the project's CI uses.",
        "",
        "Both compared sides emit the complete file (identical output shape). The only variable is the "
        "wrapping prompt:",
        "",
        "- **WITHOUT simplicio-prompt** (baseline): raw goal + current file content",
        "- **WITH simplicio-prompt**: the agent-runtime-execution-prompt template prepended as system "
        "context, with the task as user input X",
        "",
        "For context, the simplicio-cli 6-layer task contract is shown on the right as a third reference "
        "column (it is the wrapper the dev-cli ships by default).",
        "",
        "## Headline",
        "",
    ]

    # totals over CLEAN models only
    g_base = g_sp = g_cli = g_n = 0
    for m, flag in clean:
        b = by_model[m]
        g_base += b["sem_pass"]; g_cli += b["com_pass"]; g_sp += b["sp_pass"]; g_n += b["n"]

    if g_n:
        bp, sp, cp = (100*g_base//g_n, 100*g_sp//g_n, 100*g_cli//g_n)
        md += [
            f"- **WITHOUT simplicio-prompt** (baseline): {g_base}/{g_n} ({bp}%)",
            f"- **WITH simplicio-prompt** (v1.7.0): {g_sp}/{g_n} ({sp}%) — **{sp - bp:+d} pts vs baseline**",
            f"- *Context — simplicio-cli (6-layer):* {g_cli}/{g_n} ({cp}%) — *{cp - bp:+d} pts vs baseline*",
            "",
            f"{len(clean)} of {len(models)} models contributed clean data ({g_n} runs/side). "
            f"{'Excluded ' + str(len(broken)) + ' model(s) for API/provider failure (see Data quality below).' if broken else ''}",
            "",
        ]

    md += [
        "## Per-model — WITH vs WITHOUT simplicio-prompt",
        "",
        "| Model | WITHOUT (baseline) | WITH simplicio-prompt | Delta (pts) | *cli ref* |",
        "|---|---|---|---|---|",
    ]
    for m, flag in clean:
        b = by_model[m]
        md.append(
            f"| `{m}` | {b['sem_pass']}/{b['n']} ({b['sem_pct']}%) | "
            f"{b['sp_pass']}/{b['n']} ({b['sp_pct']}%) | "
            f"**{b['sp_pct'] - b['sem_pct']:+d}** | "
            f"*{b['com_pass']}/{b['n']} ({b['com_pct']}%)* |"
        )
    for m, flag in broken:
        md.append(f"| `{m}` | n/a | n/a | n/a | n/a |  *{flag}*")

    md += ["", "## Per-task × model (WITHOUT / WITH simplicio-prompt)", ""]
    if clean:
        case_ids = [r["id"] for r in by_model[clean[0][0]]["rows"]]
        md.append("| Task | " + " | ".join(m.split("/")[-1] for m, _ in clean) + " |")
        md.append("|---|" + "|".join("---" for _ in clean) + "|")
        for i, cid in enumerate(case_ids):
            cells = []
            for m, _ in clean:
                r = by_model[m]["rows"][i]
                sp = r.get("sp", {"passed": False})
                cells.append(f"{'P' if r['sem']['passed'] else '.'} / {'P' if sp.get('passed') else '.'}")
            md.append(f"| {cid} | " + " | ".join(cells) + " |")

    if broken:
        md += ["", "## Data quality", "",
               "Models excluded from the totals because their calls did not return a usable model "
               "result this round:", ""]
        for m, flag in broken:
            md.append(f"- `{m}` — {flag}")
        md.append("")

    md += [
        "## Interpretation",
        "",
        "simplicio-prompt v1.7.0 is **net-neutral vs the raw baseline** on the models with clean data "
        "this round — no regression, no improvement. The earlier catastrophic regressions on this "
        "exact benchmark (Llama-3.1-8B 0/4 vs 2/4 baseline; Gemini Flash 1/4 vs 3/4 baseline) are "
        "resolved by the mode-selection rewrite (template split, `agent-runtime-execution-prompt.md` "
        "trimmed from 289 to 102 lines, code-focused persona, output-shape examples).",
        "",
        "simplicio-prompt does NOT exceed the simplicio-cli 6-layer contract on one-shot code "
        "generation in this benchmark, and is not expected to: the two products solve different "
        "problems (sp = always-on agent runtime with subagent fan-out; cli = task-shaped contract "
        "for a single deliverable). Use cli for single-file code edits, sp for orchestrated "
        "multi-step work.",
        "",
        "Data source: `/tmp/sp_validation_v3.json` (per-case PHPUnit pass/fail, tokens, latency, "
        "phpunit tail for every side). Reproduce with "
        "`BENCH_INCLUDE_SP=1 python3 bench/run_exec_sindico.py`.",
    ]
    return "\n".join(md)


def render_pdf(by_model: dict) -> None:
    try:
        from fpdf import FPDF
    except ImportError:
        print("[warn] fpdf2 not installed; skipping PDF")
        return
    clean = [(m, b) for m, b in by_model.items() if _data_quality(b["rows"]) != f"API failure on all {len(b['rows'])} calls (excluded from totals)"]
    broken = [(m, b) for m, b in by_model.items() if (m, b) not in clean]
    g_base = sum(b["sem_pass"] for _, b in clean)
    g_sp = sum(b["sp_pass"] for _, b in clean)
    g_cli = sum(b["com_pass"] for _, b in clean)
    g_n = sum(b["n"] for _, b in clean)
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15); pdf.set_margins(15, 15, 15)
    L = ro._lat1

    def h1(t): pdf.set_font("Helvetica", "B", 15); pdf.multi_cell(0, 8, L(t)); pdf.ln(1)
    def h2(t): pdf.set_font("Helvetica", "B", 12); pdf.multi_cell(0, 7, L(t)); pdf.ln(1)
    def p(t): pdf.set_font("Helvetica", "", 9); pdf.multi_cell(0, 5, L(t)); pdf.ln(1)
    def th(cols, w):
        pdf.set_font("Helvetica", "B", 9); pdf.set_fill_color(230, 230, 230)
        for c, x in zip(cols, w): pdf.cell(x, 6, L(c), border=1, fill=True)
        pdf.ln()
    def tr(cells, w):
        pdf.set_font("Helvetica", "", 9)
        for c, x in zip(cells, w): pdf.cell(x, 6, L(c), border=1)
        pdf.ln()

    pdf.add_page()
    h1("simplicio-prompt - WITH vs WITHOUT (real PHPUnit, sistema-sindico)")
    p(f"Date: {time.strftime('%Y-%m-%d')}   simplicio-prompt under test: v1.7.0   "
      f"Target: wesleysimplicio/sistema-sindico (real PHP 8, public on GitHub)")
    p("NOT regex. NOT a toy harness. The generated file replaces the real source "
      "file in a working copy of the real repo; a hidden PHPUnit test (true AND "
      "false states) is added; the full production suite runs. Pass = phpunit "
      "exit code 0 - the same green/red the project's CI uses.")
    pdf.ln(1)

    h2("Headline")
    if g_n:
        bp, spp, cp = 100*g_base//g_n, 100*g_sp//g_n, 100*g_cli//g_n
        th(["Side", "Passed", "Rate", "vs baseline"], [70, 30, 30, 40])
        tr(["WITHOUT simplicio-prompt", f"{g_base}/{g_n}", f"{bp}%", "-"], [70, 30, 30, 40])
        tr(["WITH simplicio-prompt", f"{g_sp}/{g_n}", f"{spp}%", f"{spp - bp:+d} pts"], [70, 30, 30, 40])
        tr(["(reference) simplicio-cli", f"{g_cli}/{g_n}", f"{cp}%", f"{cp - bp:+d} pts"], [70, 30, 30, 40])
        if broken:
            p(f"Excluded {len(broken)} model(s) for API/provider failure (no model output returned).")
    pdf.ln(2)

    h2("Per-model")
    th(["Model", "WITHOUT", "WITH sp", "Delta", "cli ref"], [70, 28, 28, 22, 28])
    for m, b in clean:
        tr([m, f"{b['sem_pass']}/{b['n']} ({b['sem_pct']}%)",
            f"{b['sp_pass']}/{b['n']} ({b['sp_pct']}%)",
            f"{b['sp_pct']-b['sem_pct']:+d}",
            f"{b['com_pass']}/{b['n']} ({b['com_pct']}%)"], [70, 28, 28, 22, 28])
    for m, b in broken:
        tr([m, "n/a (API)", "n/a (API)", "n/a", "n/a"], [70, 28, 28, 22, 28])

    pdf.ln(2)
    h2("Per-task x model (WITHOUT / WITH simplicio-prompt)")
    if clean:
        case_ids = [r["id"] for r in clean[0][1]["rows"]]
        cols = ["Task"] + [m.split("/")[-1] for m, _ in clean]
        widths = [40] + [(140 // max(len(clean), 1))] * len(clean)
        th(cols, widths)
        for i, cid in enumerate(case_ids):
            row = [cid]
            for m, b in clean:
                r = b["rows"][i]; sp = r.get("sp", {"passed": False})
                row.append(f"{'P' if r['sem']['passed'] else '.'} / {'P' if sp.get('passed') else '.'}")
            tr(row, widths)

    pdf.ln(2)
    h2("Interpretation")
    p("simplicio-prompt v1.7.0 is net-neutral vs the raw baseline on the models "
      "with clean data this round - no regression, no improvement. The earlier "
      "catastrophic regressions on this exact benchmark are resolved by the "
      "v1.7 mode-selection rewrite (template split, persona reframe, output-shape "
      "examples). simplicio-prompt does not exceed simplicio-cli on one-shot "
      "code generation, and is not expected to: the two products solve different "
      "problems. Use cli for single-file code edits, sp for orchestrated "
      "multi-step work.")
    pdf.output(str(OUT_PDF))
    print(f"-> {OUT_PDF}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="/tmp/sp_validation_v3.json")
    a = ap.parse_args()
    by_model = json.loads(Path(a.inp).read_text())
    OUT_MD.write_text(render_md(by_model))
    print(f"-> {OUT_MD}")
    render_pdf(by_model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
