"""
4-Quadrant bench - agent × simplicio matrix.

Isolates two independent variables on the same model, same cases, same
checks:

  axis A: prompt structure ........ raw goal  |  simplicio 6-layer
  axis B: execution model ......... one-shot  |  loop until DoD or max-iters

The 2x2:
  Q1 = no agent + raw goal           (baseline)
  Q2 = no agent + simplicio          (current bench)
  Q3 = with agent + raw goal         (loop only)
  Q4 = with agent + simplicio        (composition / .agents/simplicio-ralph)

Feedback between loop iterations is deterministic - derived from which
regex checks failed in the previous output. No LLM judges the LLM.

Outputs:
  bench/results_4quadrant.{md,json,pdf}
  bench/charts/4q_*.svg
  .simplicio/bench_4q/<model>/case_NN/q*_iter*.txt

Usage:
  OPENROUTER_API_KEY=... \
    BENCH_MODELS="google/gemma-3-4b-it" \
    BENCH_MAX_ITERS=3 \
    BENCH_MAX_CASES=5 \
    python3 bench/run_4quadrant.py

See docs/benchmark-4quadrant.md for methodology.
"""
from __future__ import annotations
import json, os, re, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = Path(os.environ.get("BENCH_CASES_PATH", ROOT / "bench" / "cases_offline.json"))
OUT_MD = ROOT / "bench" / "results_4quadrant.md"
OUT_JSON = ROOT / "bench" / "results_4quadrant.json"
OUT_PDF = ROOT / "bench" / "results_4quadrant.pdf"
CHART_DIR = ROOT / "bench" / "charts"
RAW_DIR = ROOT / ".simplicio" / "bench_4q"

MODELS = [m.strip() for m in os.environ.get(
    "BENCH_MODELS",
    "google/gemma-3-4b-it"
).split(",") if m.strip()]
BASE_URL = os.environ.get("BENCH_BASE_URL", "https://openrouter.ai/api/v1")
API_KEY = os.environ.get("BENCH_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
MAX_ITERS = int(os.environ.get("BENCH_MAX_ITERS", "3"))
MAX_CASES = int(os.environ.get("BENCH_MAX_CASES", "5"))
MAX_TOKENS = int(os.environ.get("BENCH_MAX_TOKENS", "8192"))

QUADRANTS = ("Q1", "Q2", "Q3", "Q4")
QUADRANT_LABELS = {
    "Q1": "no agent, no simplicio",
    "Q2": "no agent, with simplicio",
    "Q3": "with agent, no simplicio",
    "Q4": "with agent, with simplicio",
}
QUADRANT_COLORS = {"Q1": "#9ca3af", "Q2": "#60a5fa", "Q3": "#fbbf24", "Q4": "#10b981"}

SIX_LAYER_TEMPLATE = """You are a senior engineer working IN THIS project.
Stack: {stack}. Project conventions are LAW. Do not bring generic patterns.
Do not invent files or libraries the project does not use.

[GOAL]
{goal}

[TARGET]
Touch ONLY this file:
{target}

[CONTRACT]
Done WHEN, and only when, ALL of the states below are true:
{criteria}

Constraints (do not break):
{constraints}

[OUTPUT]
Return EXACTLY in this shape, nothing else:
1. DIFF: unified diff, target file only.
2. TEST: test code asserting each contract state (true AND false case).
3. EVIDENCE: Playwright snippet capturing the UI states, or "N/A".
No prose, no preamble."""

CHECK_HINTS = {
    r"\.component\.html": "name the exact target file (e.g. `*.component.html`) inside the DIFF header.",
    r"\\W\)diff": "include a DIFF block in unified diff format (e.g. ```diff or `--- a/...`).",
    r"\\W\)test": "include a TEST block (e.g. `describe(`, `it(`, `[Test]`, `[Fact]`, `pytest`).",
    r"admin": "mention the admin role/permission check explicitly.",
    r"editor": "reference the editor role explicitly.",
    r"auditor": "reference the auditor role explicitly.",
    r"absent|hidden|removed|ngIf|not.*admin": "use a structural guard (e.g. `*ngIf`, `[hidden]`, role check) and assert both true/false states.",
    r"disabled|\[disabled\]|isEditor": "use `[disabled]` (or `isEditor`) and assert enabled vs disabled state.",
}


def _hint_for_check(pattern: str) -> str:
    for key, msg in CHECK_HINTS.items():
        if re.search(key, pattern, flags=re.IGNORECASE):
            return msg
    return f"satisfy regex check: `{pattern}`"


def llm_call(model: str, prompt: str, timeout: int = 120) -> dict:
    if not API_KEY:
        raise SystemExit("set OPENROUTER_API_KEY (or BENCH_API_KEY)")
    body = json.dumps({
        "model": model,
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/wesleysimplicio/simplicio-cli",
            "X-Title": "simplicio-cli bench 4q",
        },
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        usage = data.get("usage") or {}
        msg = data["choices"][0].get("message") or {}
        text = msg.get("content") or msg.get("reasoning") or ""
        return {
            "text": text,
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
            "elapsed_ms": elapsed_ms,
            "error": None,
        }
    except urllib.error.HTTPError as e:
        # preserve response body so 429/4xx/5xx debugging does not need re-running with curl
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        detail = f"HTTP {e.code}: {body[:500]}" if body else f"HTTP {e.code}"
        return {
            "text": f"[BENCH_ERROR] {detail}",
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "error": detail,
        }
    except Exception as e:
        return {
            "text": f"[BENCH_ERROR] {e}",
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(e),
        }


def score(output: str, checks: list[str]) -> list[bool]:
    out = output or ""
    return [
        re.search(p, out, flags=re.IGNORECASE | re.MULTILINE) is not None
        for p in checks
    ]


def quality_metrics(output: str, case: dict) -> dict:
    out = output or ""
    return {
        "len": len(out),
        "has_diff_block": bool(re.search(r"```diff|^---\s|^\+\+\+\s|@@", out, re.M)),
        "has_test_block": bool(re.search(r"```(ts|js|tsx|jsx|csharp|cs|python|typescript|javascript)\b|describe\(|it\(|test\(|\[Test\]|\[Fact\]", out, re.I | re.M)),
        "target_mentioned": case["target"].split("/")[-1].lower() in out.lower(),
        "criteria_keywords_hit": sum(
            1 for kw in re.findall(r"[A-Za-z]{4,}", case["criteria"].lower())
            if kw in out.lower()
        ),
    }


def format_feedback(iteration: int, flags: list[bool], case: dict) -> str:
    failed = [case["checks"][i] for i, ok in enumerate(flags) if not ok]
    hints = list({_hint_for_check(p) for p in failed})
    lines = [
        "",
        f"[FEEDBACK - iteration {iteration}]",
        "Previous output failed these checks:",
    ]
    for p in failed:
        lines.append(f"- {p}")
    lines += ["", "Required corrections:"]
    for h in hints:
        lines.append(f"- {h}")
    lines += ["", "Return a corrected version following the OUTPUT shape rules."]
    return "\n".join(lines)


def _save_iter(model: str, case_idx: int, quadrant: str, iteration: int, text: str) -> None:
    slug = model.replace("/", "_").replace(":", "_")
    outdir = RAW_DIR / slug / f"case_{case_idx:02d}"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{quadrant.lower()}_iter{iteration}.txt").write_text(text)


def run_one_shot(model: str, case_idx: int, case: dict, prompt: str, quadrant: str) -> dict:
    res = llm_call(model, prompt)
    flags = score(res["text"], case["checks"])
    _save_iter(model, case_idx, quadrant, 1, res["text"])
    return {
        "iterations": 1,
        "passed": all(flags),
        "flags": flags,
        "final_output": res["text"],
        "usage": {
            "prompt_tokens": res["prompt_tokens"],
            "completion_tokens": res["completion_tokens"],
            "total_tokens": res["total_tokens"],
            "elapsed_ms": res["elapsed_ms"],
        },
        "quality": quality_metrics(res["text"], case),
    }


def run_loop(model: str, case_idx: int, case: dict, seed_prompt: str, quadrant: str) -> dict:
    prompt = seed_prompt
    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "elapsed_ms": 0}
    flags: list[bool] = []
    out = ""
    final_iter = MAX_ITERS
    for i in range(1, MAX_ITERS + 1):
        res = llm_call(model, prompt)
        out = res["text"]
        flags = score(out, case["checks"])
        _save_iter(model, case_idx, quadrant, i, out)
        for k in total:
            total[k] += res[k]
        if all(flags):
            final_iter = i
            break
        prompt = seed_prompt + format_feedback(i, flags, case)
    return {
        "iterations": final_iter,
        "passed": all(flags),
        "flags": flags,
        "final_output": out,
        "usage": total,
        "quality": quality_metrics(out, case),
    }


def build_prompt_raw(case: dict) -> str:
    return case["goal"]


def build_prompt_simplicio(case: dict) -> str:
    return SIX_LAYER_TEMPLATE.format(
        stack=case.get("stack", "angular"),
        goal=case["goal"],
        target=case["target"],
        criteria=case["criteria"],
        constraints=case["constraints"],
    )


def run_quadrant(q: str, model: str, case_idx: int, case: dict) -> dict:
    if q == "Q1":
        return run_one_shot(model, case_idx, case, build_prompt_raw(case), q)
    if q == "Q2":
        return run_one_shot(model, case_idx, case, build_prompt_simplicio(case), q)
    if q == "Q3":
        return run_loop(model, case_idx, case, build_prompt_raw(case), q)
    if q == "Q4":
        return run_loop(model, case_idx, case, build_prompt_simplicio(case), q)
    raise ValueError(q)


# ---------- SVG charts ---------- #

def _svg_quadrant_bars(title: str, labels: list[str], series: dict[str, list[float]],
                       ymax: float = 100.0, unit: str = "%") -> str:
    n = len(labels)
    bar_w = 16
    group_w = bar_w * 4 + 18
    chart_w = max(640, 100 + group_w * n + 30)
    chart_h = 380
    pad_l, pad_b, pad_t = 70, 90, 60
    plot_h = chart_h - pad_t - pad_b
    ax_y = pad_t + plot_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {chart_w} {chart_h}" font-family="-apple-system,Segoe UI,Roboto,sans-serif" font-size="12">',
        f'<text x="{chart_w/2}" y="22" text-anchor="middle" font-weight="600" font-size="14">{title}</text>',
        '<style>.grid{stroke:#eee;stroke-width:1}.ax{stroke:#888;stroke-width:1}.lbl{fill:#222}</style>',
    ]
    for i in range(5):
        y = pad_t + plot_h * i / 4
        v = ymax * (1 - i / 4)
        parts.append(f'<line x1="{pad_l}" y1="{y}" x2="{chart_w-10}" y2="{y}" class="grid"/>')
        parts.append(f'<text x="{pad_l-6}" y="{y+4}" text-anchor="end" fill="#666">{v:.0f}{unit}</text>')
    parts.append(f'<line x1="{pad_l}" y1="{ax_y}" x2="{chart_w-10}" y2="{ax_y}" class="ax"/>')
    parts.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{ax_y}" class="ax"/>')
    for i, lbl in enumerate(labels):
        gx = pad_l + 20 + i * group_w
        for j, q in enumerate(QUADRANTS):
            v = series[q][i]
            h = plot_h * (v / ymax) if ymax else 0
            x = gx + j * (bar_w + 2)
            parts.append(f'<rect x="{x}" y="{ax_y - h}" width="{bar_w}" height="{h}" fill="{QUADRANT_COLORS[q]}"/>')
            parts.append(f'<text x="{x + bar_w/2}" y="{ax_y - h - 3}" text-anchor="middle" fill="#444" font-size="9">{v:.0f}</text>')
        cx = gx + (bar_w * 4 + 6) / 2
        parts.append(f'<text x="{cx}" y="{ax_y + 14}" transform="rotate(-25 {cx} {ax_y + 14})" text-anchor="end" class="lbl">{lbl}</text>')
    lx = pad_l
    ly = pad_t - 28
    for j, q in enumerate(QUADRANTS):
        x = lx + j * 150
        parts.append(f'<rect x="{x}" y="{ly}" width="14" height="10" fill="{QUADRANT_COLORS[q]}"/>')
        parts.append(f'<text x="{x+18}" y="{ly+9}">{q} - {QUADRANT_LABELS[q]}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------- markdown ---------- #

def _pct(num: int, den: int) -> int:
    return 100 * num // max(den, 1)


def _aggregate(by_model: dict) -> dict:
    agg = {q: {"passed": 0, "total": 0, "iters_sum": 0, "tokens": 0, "ms": 0,
               "diff": 0, "test": 0, "target": 0} for q in QUADRANTS}
    for m, mdata in by_model.items():
        for q in QUADRANTS:
            for r in mdata[q]:
                agg[q]["total"] += 1
                if r["passed"]:
                    agg[q]["passed"] += 1
                agg[q]["iters_sum"] += r["iterations"]
                agg[q]["tokens"] += r["usage"]["total_tokens"]
                agg[q]["ms"] += r["usage"]["elapsed_ms"]
                agg[q]["diff"] += int(r["quality"]["has_diff_block"])
                agg[q]["test"] += int(r["quality"]["has_test_block"])
                agg[q]["target"] += int(r["quality"]["target_mentioned"])
    for q in QUADRANTS:
        a = agg[q]
        a["pass_pct"] = _pct(a["passed"], a["total"])
        a["avg_iters"] = a["iters_sum"] / max(a["total"], 1)
        a["tokens_per_pass"] = a["tokens"] // max(a["passed"], 1)
        a["ms_per_pass"] = a["ms"] // max(a["passed"], 1)
        a["diff_pct"] = _pct(a["diff"], a["total"])
        a["test_pct"] = _pct(a["test"], a["total"])
        a["target_pct"] = _pct(a["target"], a["total"])
    return agg


def _verdict(value: float, threshold: float = 5.0) -> str:
    if abs(value) < threshold:
        return "NOT REJECTED"
    return "REJECTED"


def build_markdown(by_model: dict, cases: list, agg: dict) -> str:
    n_cases = len(cases)
    n_models = len(by_model)
    md = [
        "# Benchmark 4-quadrant - agent x simplicio matrix",
        "",
        f"Date: **{time.strftime('%Y-%m-%d')}**  ",
        f"Models: " + ", ".join(f"`{m}`" for m in by_model) + "  ",
        f"Cases: **{n_cases}**, max_iters: **{MAX_ITERS}**  ",
        f"Base: `{BASE_URL}`",
        "",
        "Methodology: [docs/benchmark-4quadrant.md](../docs/benchmark-4quadrant.md).",
        "",
        "## Quadrants",
        "",
        "| Cell | Prompt | Execution |",
        "|---|---|---|",
        "| **Q1** | raw goal | 1-shot (baseline) |",
        "| **Q2** | simplicio 6-layer | 1-shot (current bench) |",
        "| **Q3** | raw goal | loop with feedback (`MAX_ITERS`) |",
        "| **Q4** | simplicio 6-layer | loop with feedback (composition) |",
        "",
        "## Headline (aggregate over all models x cases)",
        "",
        "| Quadrant | Pass rate | Avg iters | Tokens / pass | Wall-clock / pass |",
        "|---|---|---|---|---|",
    ]
    for q in QUADRANTS:
        a = agg[q]
        md.append(
            f"| **{q}** ({QUADRANT_LABELS[q]}) | "
            f"{a['passed']}/{a['total']} ({a['pass_pct']}%) | "
            f"{a['avg_iters']:.2f} | "
            f"{a['tokens_per_pass']:,} | "
            f"{a['ms_per_pass']:,} ms |"
        )
    md += [
        "",
        "![4q overall](charts/4q_overall.svg)",
        "",
        "## Contribution decomposition (points)",
        "",
    ]
    d_prompt_alone = agg["Q2"]["pass_pct"] - agg["Q1"]["pass_pct"]
    d_loop_alone = agg["Q3"]["pass_pct"] - agg["Q1"]["pass_pct"]
    d_prompt_in_loop = agg["Q4"]["pass_pct"] - agg["Q3"]["pass_pct"]
    d_loop_with_simpl = agg["Q4"]["pass_pct"] - agg["Q2"]["pass_pct"]
    best_single = max(agg["Q2"]["pass_pct"], agg["Q3"]["pass_pct"])
    composition_gain = agg["Q4"]["pass_pct"] - best_single
    linear_pred = agg["Q1"]["pass_pct"] + d_prompt_alone + d_loop_alone
    synergy = agg["Q4"]["pass_pct"] - linear_pred
    md += [
        "| Delta | Formula | Value |",
        "|---|---|---|",
        f"| Prompt effect, no loop | Q2 - Q1 | **{d_prompt_alone:+d} pts** |",
        f"| Loop effect, no simplicio | Q3 - Q1 | **{d_loop_alone:+d} pts** |",
        f"| Prompt effect inside loop | Q4 - Q3 | **{d_prompt_in_loop:+d} pts** |",
        f"| Loop effect with simplicio | Q4 - Q2 | **{d_loop_with_simpl:+d} pts** |",
        f"| Composition gain over best single axis | Q4 - max(Q2, Q3) | **{composition_gain:+d} pts** |",
        f"| Synergy vs linear stacking | Q4 - (Q1 + (Q2-Q1) + (Q3-Q1)) | **{synergy:+d} pts** |",
        "",
        "## Hypothesis verdicts",
        "",
        "Threshold for rejection: |delta| >= 5 points.",
        "",
        f"1. *Loop alone closes the gap (simplicio unnecessary once you loop).* "
        f"Q4 - Q3 = **{d_prompt_in_loop:+d} pts**. **{_verdict(d_prompt_in_loop)}**.",
        f"2. *Simplicio alone is enough (loop is overkill).* "
        f"Q4 - Q2 = **{d_loop_with_simpl:+d} pts**. **{_verdict(d_loop_with_simpl)}**.",
        f"3. *Gains stack linearly (no synergy).* "
        f"Q4 - linear = **{synergy:+d} pts**. **{_verdict(synergy)}**.",
        "",
        "## Cost - token & wall-clock budget",
        "",
        "| Quadrant | Total tokens | Total wall-clock | Tokens / passing case | ms / passing case |",
        "|---|---|---|---|---|",
    ]
    for q in QUADRANTS:
        a = agg[q]
        md.append(
            f"| {q} | {a['tokens']:,} | {a['ms']/1000:.1f}s | "
            f"{a['tokens_per_pass']:,} | {a['ms_per_pass']:,} |"
        )
    md += [
        "",
        "## Structural quality (rate across all runs)",
        "",
        "| Quadrant | DIFF block | TEST block | target file mentioned |",
        "|---|---|---|---|",
    ]
    for q in QUADRANTS:
        a = agg[q]
        md.append(f"| {q} | {a['diff_pct']}% | {a['test_pct']}% | {a['target_pct']}% |")
    md += [
        "",
        "## Per-model x quadrant",
        "",
        "| Model | Q1 | Q2 | Q3 | Q4 |",
        "|---|---|---|---|---|",
    ]
    for m, mdata in by_model.items():
        cells = []
        for q in QUADRANTS:
            passed = sum(1 for r in mdata[q] if r["passed"])
            total = len(mdata[q])
            cells.append(f"{passed}/{total} ({_pct(passed, total)}%)")
        md.append(f"| `{m}` | " + " | ".join(cells) + " |")
    md += [
        "",
        "## Per-case x quadrant (avg across models)",
        "",
        "| # | Stack | Goal | Q1 | Q2 | Q3 | Q4 |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, c in enumerate(cases):
        row = [f"{i+1}", f"`{c['stack']}`", c["goal"][:50]]
        for q in QUADRANTS:
            # tolerate partial runs: a model may have fewer observations than len(cases)
            observed = [m for m in by_model if i < len(by_model[m][q])]
            passed = sum(1 for m in observed if by_model[m][q][i]["passed"])
            row.append(f"{passed}/{len(observed) or n_models}")
        md.append("| " + " | ".join(row) + " |")
    md += [
        "",
        "![4q per case](charts/4q_per_case.svg)",
        "",
        "![4q cost](charts/4q_cost.svg)",
        "",
        "## How to reproduce",
        "",
        "```bash",
        "pip install -e \".[bench]\"",
        "OPENROUTER_API_KEY=...",
        f"BENCH_MODELS=\"{','.join(by_model.keys())}\" \\",
        f"  BENCH_MAX_ITERS={MAX_ITERS} \\",
        "  python3 bench/run_4quadrant.py",
        "```",
        "",
        "Raw model outputs (one file per iteration per quadrant) live under "
        "`.simplicio/bench_4q/<model>/case_NN/q*_iter*.txt`.",
        "",
    ]
    return "\n".join(md)


# ---------- PDF (fpdf2) ---------- #

def build_pdf(by_model: dict, cases: list, agg: dict) -> None:
    try:
        from fpdf import FPDF
    except ImportError:
        print("[warn] fpdf2 not installed; skipping PDF. install via `pip install fpdf2`.")
        return

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)

    def h1(t):
        pdf.set_font("Helvetica", "B", 18); pdf.multi_cell(0, 9, t); pdf.ln(2)

    def h2(t):
        pdf.set_font("Helvetica", "B", 13); pdf.multi_cell(0, 7, t); pdf.ln(1)

    def p(t):
        pdf.set_font("Helvetica", "", 10); pdf.multi_cell(0, 5, t); pdf.ln(1)

    def kv_row(k, v, w_k=70):
        pdf.set_font("Helvetica", "B", 10); pdf.cell(w_k, 6, k, border=1)
        pdf.set_font("Helvetica", "", 10); pdf.cell(0, 6, v, border=1); pdf.ln()

    def table_header(cols, widths):
        pdf.set_font("Helvetica", "B", 9); pdf.set_fill_color(230, 230, 230)
        for c, w in zip(cols, widths):
            pdf.cell(w, 6, c, border=1, fill=True)
        pdf.ln()

    def table_row(cells, widths):
        pdf.set_font("Helvetica", "", 9)
        for c, w in zip(cells, widths):
            pdf.cell(w, 6, c, border=1)
        pdf.ln()

    # cover
    pdf.add_page()
    h1("simplicio-cli - 4-Quadrant Benchmark")
    p(f"Date: {time.strftime('%Y-%m-%d')}")
    p(f"Models: {', '.join(by_model.keys())}")
    p(f"Cases: {len(cases)}   |   max_iters: {MAX_ITERS}   |   base: {BASE_URL}")
    pdf.ln(3)
    h2("Why this matters")
    p("The original bench answered one question: does wrapping a goal in "
      "simplicio's 6-layer contract help a single LLM call? Answer: yes. "
      "But real-world coding agents add a retry loop on top. So the open "
      "question is: when you add a loop, does the prompt still matter, or "
      "does the loop alone close the gap? This bench answers it with a 2x2 "
      "matrix isolating prompt structure x execution model.")
    h2("The matrix")
    table_header(["Cell", "Prompt", "Execution"], [25, 80, 80])
    table_row(["Q1", "raw goal", "1-shot (baseline)"], [25, 80, 80])
    table_row(["Q2", "simplicio 6-layer", "1-shot (current bench)"], [25, 80, 80])
    table_row(["Q3", "raw goal", f"loop with feedback (<= {MAX_ITERS} iters)"], [25, 80, 80])
    table_row(["Q4", "simplicio 6-layer", f"loop with feedback (composition)"], [25, 80, 80])

    # headline
    pdf.add_page()
    h1("Headline")
    table_header(["Quadrant", "Pass", "Avg iters", "Tokens / pass", "ms / pass"], [55, 30, 30, 35, 30])
    for q in QUADRANTS:
        a = agg[q]
        table_row([f"{q} {QUADRANT_LABELS[q]}",
                   f"{a['pass_pct']}%",
                   f"{a['avg_iters']:.2f}",
                   f"{a['tokens_per_pass']:,}",
                   f"{a['ms_per_pass']:,}"], [55, 30, 30, 35, 30])

    pdf.ln(3)
    h2("Contribution decomposition")
    d_prompt_alone = agg["Q2"]["pass_pct"] - agg["Q1"]["pass_pct"]
    d_loop_alone = agg["Q3"]["pass_pct"] - agg["Q1"]["pass_pct"]
    d_prompt_in_loop = agg["Q4"]["pass_pct"] - agg["Q3"]["pass_pct"]
    d_loop_with_simpl = agg["Q4"]["pass_pct"] - agg["Q2"]["pass_pct"]
    best_single = max(agg["Q2"]["pass_pct"], agg["Q3"]["pass_pct"])
    composition_gain = agg["Q4"]["pass_pct"] - best_single
    linear_pred = agg["Q1"]["pass_pct"] + d_prompt_alone + d_loop_alone
    synergy = agg["Q4"]["pass_pct"] - linear_pred
    table_header(["Delta", "Formula", "Value (pts)"], [80, 60, 35])
    table_row(["Prompt effect, no loop", "Q2 - Q1", f"{d_prompt_alone:+d}"], [80, 60, 35])
    table_row(["Loop effect, no simplicio", "Q3 - Q1", f"{d_loop_alone:+d}"], [80, 60, 35])
    table_row(["Prompt effect inside loop", "Q4 - Q3", f"{d_prompt_in_loop:+d}"], [80, 60, 35])
    table_row(["Loop effect with simplicio", "Q4 - Q2", f"{d_loop_with_simpl:+d}"], [80, 60, 35])
    table_row(["Composition over best single axis", "Q4 - max(Q2, Q3)", f"{composition_gain:+d}"], [80, 60, 35])
    table_row(["Synergy vs linear stacking", "Q4 - linear", f"{synergy:+d}"], [80, 60, 35])

    pdf.ln(3)
    h2("Hypothesis verdicts (threshold |delta| >= 5 pts)")
    p(f"1) Loop alone closes the gap: Q4-Q3 = {d_prompt_in_loop:+d} pts -> {_verdict(d_prompt_in_loop)}.")
    p(f"2) Simplicio alone is enough: Q4-Q2 = {d_loop_with_simpl:+d} pts -> {_verdict(d_loop_with_simpl)}.")
    p(f"3) Linear stacking (no synergy): Q4-linear = {synergy:+d} pts -> {_verdict(synergy)}.")

    # cost
    pdf.add_page()
    h1("Cost")
    table_header(["Quadrant", "Total tokens", "Wall-clock (s)", "Tokens / pass", "ms / pass"], [55, 35, 35, 35, 30])
    for q in QUADRANTS:
        a = agg[q]
        table_row([q, f"{a['tokens']:,}", f"{a['ms']/1000:.1f}",
                   f"{a['tokens_per_pass']:,}", f"{a['ms_per_pass']:,}"], [55, 35, 35, 35, 30])

    pdf.ln(3)
    h2("Structural quality (rate across all runs)")
    table_header(["Quadrant", "DIFF block", "TEST block", "target mentioned"], [55, 45, 45, 45])
    for q in QUADRANTS:
        a = agg[q]
        table_row([q, f"{a['diff_pct']}%", f"{a['test_pct']}%", f"{a['target_pct']}%"], [55, 45, 45, 45])

    # per-model
    pdf.add_page()
    h1("Per-model x quadrant")
    table_header(["Model", "Q1", "Q2", "Q3", "Q4"], [80, 25, 25, 25, 25])
    for m, mdata in by_model.items():
        cells = [m]
        for q in QUADRANTS:
            passed = sum(1 for r in mdata[q] if r["passed"])
            total = len(mdata[q])
            cells.append(f"{passed}/{total}")
        table_row(cells, [80, 25, 25, 25, 25])

    # per-case
    pdf.add_page()
    h1("Per-case x quadrant")
    table_header(["#", "Stack", "Goal", "Q1", "Q2", "Q3", "Q4"], [10, 20, 80, 18, 18, 18, 18])
    n_models = len(by_model)
    for i, c in enumerate(cases):
        row = [str(i+1), c["stack"], c["goal"][:55]]
        for q in QUADRANTS:
            observed = [m for m in by_model if i < len(by_model[m][q])]
            passed = sum(1 for m in observed if by_model[m][q][i]["passed"])
            row.append(f"{passed}/{len(observed) or n_models}")
        table_row(row, [10, 20, 80, 18, 18, 18, 18])

    pdf.ln(3)
    h2("Reproduce")
    p('pip install -e ".[bench]"')
    p("export OPENROUTER_API_KEY=...")
    p(f'BENCH_MODELS="{",".join(by_model.keys())}" BENCH_MAX_ITERS={MAX_ITERS} python3 bench/run_4quadrant.py')
    p("Methodology: docs/benchmark-4quadrant.md")
    p("Raw outputs: .simplicio/bench_4q/<model>/case_NN/q*_iter*.txt")

    pdf.output(str(OUT_PDF))


# ---------- main ---------- #

def run() -> int:
    if not API_KEY:
        print("set OPENROUTER_API_KEY (or BENCH_API_KEY)", file=sys.stderr)
        return 2
    cases = json.loads(CASES_PATH.read_text())[:MAX_CASES]
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    print(f"models: {MODELS}")
    print(f"cases:  {len(cases)} · max_iters: {MAX_ITERS} · base: {BASE_URL}")

    by_model: dict = {}
    for model in MODELS:
        print(f"\n=== model: {model} ===")
        per_q: dict = {q: [] for q in QUADRANTS}
        for i, case in enumerate(cases):
            for q in QUADRANTS:
                t0 = time.perf_counter()
                res = run_quadrant(q, model, i + 1, case)
                per_q[q].append(res)
                dt = (time.perf_counter() - t0) * 1000
                status = "✓" if res["passed"] else "✗"
                print(f"  [{i+1:02d}/{len(cases)}] {q} {status} "
                      f"iter={res['iterations']} tok={res['usage']['total_tokens']} "
                      f"ms={int(dt)}")
        by_model[model] = per_q

    agg = _aggregate(by_model)

    # charts
    case_labels = [f"#{i+1}" for i in range(len(cases))]
    per_case_series = {q: [] for q in QUADRANTS}
    for i in range(len(cases)):
        for q in QUADRANTS:
            observed = [m for m in by_model if i < len(by_model[m][q])]
            passed = sum(1 for m in observed if by_model[m][q][i]["passed"])
            total = len(observed) or len(by_model)
            per_case_series[q].append(100 * passed / max(total, 1))

    overall_labels = ["overall"]
    overall_series = {q: [agg[q]["pass_pct"]] for q in QUADRANTS}
    (CHART_DIR / "4q_overall.svg").write_text(_svg_quadrant_bars(
        "Pass rate per quadrant (aggregate)", overall_labels, overall_series))
    (CHART_DIR / "4q_per_case.svg").write_text(_svg_quadrant_bars(
        "Pass rate per case per quadrant", case_labels, per_case_series))

    cost_series = {q: [agg[q]["tokens_per_pass"]] for q in QUADRANTS}
    cost_max = max(max(v) for v in cost_series.values()) or 1
    (CHART_DIR / "4q_cost.svg").write_text(_svg_quadrant_bars(
        "Tokens per passing case", overall_labels, cost_series,
        ymax=cost_max * 1.1, unit=" tok"))

    # artifacts
    OUT_JSON.write_text(json.dumps({
        "meta": {
            "date": time.strftime("%Y-%m-%d"),
            "models": MODELS,
            "cases_path": str(CASES_PATH),
            "max_iters": MAX_ITERS,
            "base_url": BASE_URL,
        },
        "summary": agg,
        "by_model": by_model,
        "cases": cases,
    }, indent=2, default=str))

    OUT_MD.write_text(build_markdown(by_model, cases, agg))
    build_pdf(by_model, cases, agg)

    print(f"\n-> {OUT_MD}")
    print(f"-> {OUT_JSON}")
    print(f"-> {OUT_PDF} (if fpdf2 present)")
    print("\nheadline:")
    for q in QUADRANTS:
        print(f"  {q} {QUADRANT_LABELS[q]:32s}: {agg[q]['pass_pct']}%  "
              f"(avg iter {agg[q]['avg_iters']:.2f}, {agg[q]['tokens_per_pass']:,} tok/pass)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
