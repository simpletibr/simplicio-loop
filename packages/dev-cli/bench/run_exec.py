"""
run_exec.py — EXECUTION benchmark. Scores by running the model's code.

For every case and every model, two prompts are sent:
  WITHOUT: the raw one-line goal.
  WITH:    the same goal wrapped in the simplicio contract (role/stack, target,
           testable criteria, constraints).
Both sides are asked for the COMPLETE contents of solution.py — output shape is
held constant, so the only variable is the contract. The model's code is
written to a temp dir next to a HIDDEN pytest suite (never shown to the model)
and `pytest` is run. Pass == the code imports and every assertion (true AND
false states) holds. This measures whether the code WORKS, not whether the
output matches a regex.

Usage:
  BENCH_BASE_URL=https://router.huggingface.co/v1 BENCH_API_KEY=... \
    BENCH_MODELS="Qwen/Qwen3-Coder-30B-A3B-Instruct,Qwen/Qwen3-Coder-Next" python3 bench/run_exec.py
Models prefixed `local:` run on CPU via transformers.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_offline as ro  # reuse llm_call / local_call / _lat1
from exec_cases import CASES

ROOT = Path(__file__).resolve().parent.parent
RESULTS_JSON = ROOT / "bench" / "results_exec.json"
RESULTS_MD = ROOT / "bench" / "results_exec.md"
RESULTS_PDF = ROOT / "bench" / "results_exec.pdf"

MODELS = [m.strip() for m in os.environ.get("BENCH_MODELS", "").split(",") if m.strip()]
PYTEST_TIMEOUT = int(os.environ.get("BENCH_PYTEST_TIMEOUT", "60"))

RAW_PROMPT = """{goal}

Output ONLY the complete contents of solution.py."""

CONTRACT_PROMPT = """You are a senior engineer working IN THIS project.
Stack: python. Project conventions are LAW. Do not invent files or libraries the project does not use.

[GOAL]
{goal}

[TARGET]
Touch ONLY this file: solution.py

[CONTRACT]
Done WHEN, and only when, ALL of the states below are true:
{criteria}

Constraints (do not break):
{constraints}

[OUTPUT]
Return ONLY the complete contents of solution.py. No prose, no preamble."""


def extract_code(text: str) -> str:
    """Pull the solution module out of a model reply (largest fenced block, else raw)."""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text or "", re.DOTALL)
    if blocks:
        return max(blocks, key=len).strip()
    return (text or "").strip()


def run_pytest(code: str, test_src: str) -> bool:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "solution.py").write_text(code)
        (Path(d) / "test_solution.py").write_text(test_src)
        try:
            p = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "test_solution.py"],
                cwd=d, capture_output=True, text=True, timeout=PYTEST_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return False
        return p.returncode == 0


def one(model: str, case: dict, prompt: str) -> dict:
    res = ro.llm_call(model, prompt)
    code = extract_code(res["text"])
    passed = run_pytest(code, case["test"])
    return {"passed": passed, "tokens": res.get("total_tokens", 0),
            "ms": res.get("elapsed_ms", 0), "error": res.get("error")}


def run() -> int:
    if not MODELS:
        raise SystemExit("set BENCH_MODELS")
    n = len(CASES)
    print(f"exec models: {MODELS}\ncases: {n} (real pytest)\n")
    by_model = {}
    for model in MODELS:
        print(f"=== {model} ===")
        rows = []
        sem_pass = com_pass = 0
        for c in CASES:
            s = one(model, c, RAW_PROMPT.format(**c))
            w = one(model, c, CONTRACT_PROMPT.format(**c))
            sem_pass += int(s["passed"]); com_pass += int(w["passed"])
            rows.append({"id": c["id"], "sem": s, "com": w})
            print(f"  {c['id']:18s} without {'PASS' if s['passed'] else 'fail'}  "
                  f"with {'PASS' if w['passed'] else 'fail'}")
        by_model[model] = {
            "rows": rows, "n": n, "sem_pass": sem_pass, "com_pass": com_pass,
            "sem_pct": 100 * sem_pass // n, "com_pct": 100 * com_pass // n,
        }
        print(f"  -> without {sem_pass}/{n} ({by_model[model]['sem_pct']}%)  "
              f"with {com_pass}/{n} ({by_model[model]['com_pct']}%)\n")

    RESULTS_JSON.write_text(json.dumps(by_model, indent=2))
    write_reports(by_model)
    g_sem = sum(b["sem_pass"] for b in by_model.values())
    g_com = sum(b["com_pass"] for b in by_model.values())
    g_tot = sum(b["n"] for b in by_model.values())
    print(f"grand: without {100*g_sem//g_tot}% · with {100*g_com//g_tot}% "
          f"(real pytest, {g_tot} runs/side)")
    return 0


def write_reports(by_model: dict) -> None:
    models = list(by_model.keys())
    case_ids = [c["id"] for c in CASES]
    g_sem = sum(b["sem_pass"] for b in by_model.values())
    g_com = sum(b["com_pass"] for b in by_model.values())
    g_tot = sum(b["n"] for b in by_model.values())
    gsp = 100 * g_sem // max(g_tot, 1)
    gcp = 100 * g_com // max(g_tot, 1)

    md = [
        "# Execution benchmark — simplicio-cli (real pytest, not regex)",
        "",
        f"Date: **{time.strftime('%Y-%m-%d')}**  ",
        f"Models: " + ", ".join(f"`{m}`" for m in models) + "  ",
        f"Tasks: **{len(CASES)}** self-contained Python functions.",
        "",
        "Each task's generated `solution.py` is written next to a **hidden "
        "pytest suite** (never shown to the model, asserting true AND false "
        "states) and executed. **Pass = the code runs and every assertion "
        "holds.** Both sides emit the complete file — the only variable is "
        "whether the goal is wrapped in the simplicio contract.",
        "",
        "## Headline",
        "",
        f"- **Without simplicio:** {g_sem}/{g_tot} ({gsp}%)",
        f"- **With simplicio:** {g_com}/{g_tot} ({gcp}%)",
        f"- **Delta:** **{gcp - gsp:+d} points**",
        "",
        "## Per-model (pass = pytest green)",
        "",
        "| Model | Without | With | Delta (pts) |",
        "|---|---|---|---|",
    ]
    for m in models:
        b = by_model[m]
        md.append(f"| `{m}` | {b['sem_pass']}/{b['n']} ({b['sem_pct']}%) | "
                  f"{b['com_pass']}/{b['n']} ({b['com_pct']}%) | "
                  f"**{b['com_pct'] - b['sem_pct']:+d}** |")
    md += ["", "## Per-task x model (P = pass)", "",
           "| Task | " + " | ".join(m.split("/")[-1] for m in models) + " |",
           "|---|" + "|".join("---" for _ in models) + "|"]
    for i, cid in enumerate(case_ids):
        cells = []
        for m in models:
            r = by_model[m]["rows"][i]
            cells.append(f"{'P' if r['sem']['passed'] else '.'}/{'P' if r['com']['passed'] else '.'}")
        md.append(f"| {cid} (w/o,with) | " + " | ".join(cells) + " |")
    md += ["", "Raw counts above are real `pytest` exit codes. `results_exec.json` "
           "holds per-case pass/fail, tokens and latency.", ""]
    RESULTS_MD.write_text("\n".join(md))
    print(f"-> {RESULTS_MD}")
    _pdf(by_model)


def _pdf(by_model: dict) -> None:
    try:
        from fpdf import FPDF
    except ImportError:
        print("[warn] fpdf2 not installed; skipping exec PDF.")
        return
    models = list(by_model.keys())
    g_sem = sum(b["sem_pass"] for b in by_model.values())
    g_com = sum(b["com_pass"] for b in by_model.values())
    g_tot = sum(b["n"] for b in by_model.values())
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15); pdf.set_margins(15, 15, 15)
    L = ro._lat1

    def h1(t): pdf.set_font("Helvetica", "B", 16); pdf.multi_cell(0, 8, L(t)); pdf.ln(1)
    def h2(t): pdf.set_font("Helvetica", "B", 12); pdf.multi_cell(0, 7, L(t)); pdf.ln(1)
    def p(t): pdf.set_font("Helvetica", "", 9); pdf.multi_cell(0, 5, L(t)); pdf.ln(1)

    def th(cols, w):
        pdf.set_font("Helvetica", "B", 9); pdf.set_fill_color(230, 230, 230)
        for c, x in zip(cols, w):
            pdf.cell(x, 6, L(c), border=1, fill=True)
        pdf.ln()

    def tr(cells, w):
        pdf.set_font("Helvetica", "", 9)
        for c, x in zip(cells, w):
            pdf.cell(x, 6, L(c), border=1)
        pdf.ln()

    pdf.add_page()
    h1("Execution benchmark - real pytest (not regex)")
    p(f"Date: {time.strftime('%Y-%m-%d')}   Tasks: {len(CASES)} Python functions")
    p("Each generated solution.py is run against a hidden pytest suite "
      "(true AND false states). Pass = code runs and all assertions hold. "
      "Both sides emit the complete file; the only variable is the simplicio contract.")
    pdf.ln(1)
    h2("Headline")
    th(["Side", "Passed", "Rate"], [70, 50, 40])
    tr(["Without simplicio", f"{g_sem}/{g_tot}", f"{100*g_sem//max(g_tot,1)}%"], [70, 50, 40])
    tr(["With simplicio", f"{g_com}/{g_tot}", f"{100*g_com//max(g_tot,1)}%"], [70, 50, 40])
    pdf.ln(2)
    h2("Per-model (pass = pytest green)")
    th(["Model", "Without", "With", "Delta(pts)"], [86, 30, 30, 30])
    for m in models:
        b = by_model[m]
        tr([m, f"{b['sem_pass']}/{b['n']} ({b['sem_pct']}%)",
            f"{b['com_pass']}/{b['n']} ({b['com_pct']}%)",
            f"{b['com_pct']-b['sem_pct']:+d}"], [86, 30, 30, 30])
    pdf.output(str(RESULTS_PDF))
    print(f"-> {RESULTS_PDF}")


if __name__ == "__main__":
    raise SystemExit(run())
