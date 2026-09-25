"""
run_fanout.py — REAL fan-out benchmark using simplicio-prompt's SubagentRuntime.

For each N in BENCH_FANOUT_NS (default: 200), launches N parallel LLM calls
through `kernel.subagent_runtime.SubagentRuntime` (the simplicio-prompt kernel)
on the SAME sistema-sindico PHP-modification task, with `temperature=0.7` to
induce real per-call variance. Every subagent output is scored by REAL PHPUnit
on a working copy of the real repo. The "majority-vote" outcome is computed by
hashing each generated solution.php and running phpunit on the most frequent
one. Reports per-attempt noise floor vs majority-vote stability across N
values, plus tokens, cost, and elapsed wall-clock.

This is the only honest test of simplicio-prompt's fan-out value prop on this
codebase: the kernel actually executes N real subagent calls (not just embeds
the runtime as prompt text), and the question we're answering is "does
the N=200 sp default beat single-call and stay inside the release cost cap?".

Usage:
  BENCH_SINDICO_SRC=/path/to/sistema-sindico \
    OPENROUTER_API_KEY=sk-or-... python3 bench/run_fanout.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

# simplicio-prompt kernel (PyPI: simplicio-prompt>=1.7.0)
from kernel.providers import LLMProvider, resolve_provider_config
from kernel.subagent_runtime import SubagentRuntime

ROOT = Path(__file__).resolve().parent.parent
SINDICO_SRC = Path(os.environ.get("BENCH_SINDICO_SRC", "/tmp/sindico"))
WORK = Path(os.environ.get("BENCH_SINDICO_WORK", "/tmp/sindico_work_fanout"))
RESULTS_JSON = ROOT / "bench" / "results_fanout.json"
RESULTS_MD = ROOT / "bench" / "results_fanout.md"
RESULTS_PDF = ROOT / "bench" / "results_fanout.pdf"
SP_DEFAULT_N = 200

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_offline as ro  # noqa: E402  # _lat1
from sindico_cases import CASES, REGEX_CHECKS_BY_TASK  # noqa: E402

# ---- model -> endpoint table (HF for the served Qwen Coders, OR for the rest) ---- #
# Each entry: provider preset, env var holding the API key, optional base_url
# override (for the generic OpenAI-compatible HF route).
HF_ROUTER_BASE_URL = "https://router.huggingface.co/v1"
QWEN3_CODER_DEFAULTS = (
    "Qwen/Qwen3-Coder-30B-A3B-Instruct",
    "Qwen/Qwen3-Coder-Next",
)

MODEL_ENDPOINTS: dict[str, dict] = {
    "Qwen/Qwen3-Coder-30B-A3B-Instruct": {
        "preset": None,
        "base_url": HF_ROUTER_BASE_URL,
        "env_key": "HF_TOKEN",
        "prompt_cost": 0.0,
        "completion_cost": 0.0,
    },
    "Qwen/Qwen3-Coder-Next": {
        "preset": None,
        "base_url": HF_ROUTER_BASE_URL,
        "env_key": "HF_TOKEN",
        "prompt_cost": 0.0,
        "completion_cost": 0.0,
    },
    # Legacy Qwen2.5 Coder entries stay available for fallback and historical
    # comparison runs, but they are no longer part of the default fan-out set.
    "Qwen/Qwen2.5-Coder-3B-Instruct": {
        "preset": None,
        "base_url": HF_ROUTER_BASE_URL,
        "env_key": "HF_TOKEN",
        "prompt_cost": 0.0,
        "completion_cost": 0.0,
    },
    "Qwen/Qwen2.5-Coder-7B-Instruct": {
        "preset": None,
        "base_url": HF_ROUTER_BASE_URL,
        "env_key": "HF_TOKEN",
        "prompt_cost": 0.0,
        "completion_cost": 0.0,
    },
    "meta-llama/llama-3.1-8b-instruct": {
        "preset": "openrouter",
        "base_url": None,
        "env_key": "OPENROUTER_API_KEY",
        "prompt_cost": 0.06,
        "completion_cost": 0.06,
    },
    "google/gemini-3.5-flash": {
        "preset": "openrouter",
        "base_url": None,
        "env_key": "OPENROUTER_API_KEY",
        "prompt_cost": 0.075,
        "completion_cost": 0.30,
    },
}


def make_runtime(model_id: str) -> SubagentRuntime:
    """Build a SubagentRuntime for the given model id, picking the right endpoint."""
    cfg = MODEL_ENDPOINTS.get(model_id)
    if cfg is None:
        raise SystemExit(f"unknown model: {model_id}; add it to MODEL_ENDPOINTS")
    api_key = os.environ.get(cfg["env_key"])
    if not api_key:
        raise SystemExit(f"missing env var {cfg['env_key']} for model {model_id}")
    overrides = {
        "api_key": api_key,
        "model": model_id,
        "prompt_cost_per_mtok": cfg["prompt_cost"],
        "completion_cost_per_mtok": cfg["completion_cost"],
    }
    if cfg["base_url"]:
        overrides["base_url"] = cfg["base_url"]
    config = resolve_provider_config(cfg["preset"], **overrides)
    return SubagentRuntime(LLMProvider(config), temperature=0.7, max_tokens=4096)


# ---- prompt builder uses the same simplicio-cli 6-layer wrap as our other benches ---- #

CLI_SYSTEM = (
    "You are a senior engineer working IN THIS project. Stack: PHP 8 + "
    "composer + PHPUnit. Project conventions are LAW. Do not invent files "
    "or libraries the project does not use."
)


def regex_score(code: str, patterns: list[str]) -> tuple[int, int]:
    """Return (matched, total) for the list of regex checks against `code`."""
    if not patterns:
        return 0, 0
    matched = sum(
        1 for p in patterns if re.search(p, code, re.IGNORECASE | re.MULTILINE)
    )
    return matched, len(patterns)


def build_prompt(case: dict, file_content: str) -> str:
    return (
        f"[GOAL]\n{case['goal']}\n\n[TARGET]\nTouch ONLY this file: {case['target']}\n"
        f"Current content:\n```php\n{file_content}\n```\n\n"
        f"[CONTRACT]\nDone WHEN, and only when, ALL of the states below are true:\n"
        f"{case['criteria']}\n\nConstraints (do not break):\n{case['constraints']}\n\n"
        f"[OUTPUT]\nReturn ONLY the complete updated contents of {case['target']}. "
        f"PHP only, no prose, no fences."
    )


def extract_php(text: str) -> str:
    text = text or ""
    blocks = re.findall(r"```(?:php)?\s*\n(.*?)```", text, re.DOTALL)
    code = max(blocks, key=len).strip() if blocks else text.strip()
    if not code.lstrip().startswith("<?php"):
        code = "<?php\n" + code
    return code


def normalize(code: str) -> str:
    """Hash-friendly normalization: strip trailing ws, collapse blank lines."""
    lines = [line.rstrip() for line in code.split("\n")]
    out, blank = [], False
    for ln in lines:
        if ln == "":
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(ln)
    return "\n".join(out).strip()


def code_hash(code: str) -> str:
    return hashlib.sha256(normalize(code).encode()).hexdigest()[:12]


def setup_workspace_base() -> None:
    """Fresh copy of sindico into WORK; create the Hidden test dir."""
    if WORK.exists():
        _rmtree(WORK)
    shutil.copytree(SINDICO_SRC, WORK)
    (WORK / "tests" / "unit" / "Core" / "Hidden").mkdir(parents=True, exist_ok=True)


def _rmtree(path: Path) -> None:
    def remove_readonly(func, item, _exc_info):
        os.chmod(item, stat.S_IWRITE)
        func(item)

    shutil.rmtree(path, onerror=remove_readonly)


def install_case(case: dict) -> str:
    """Reset target file + install ONLY this case's hidden test (if any).

    Bug-fix tasks set `seed_content` to a deliberately broken version of the
    target; the model is asked to fix it so the EXISTING test suite passes.
    Pure-additive tasks leave seed_content unset and use the pristine sindico
    source as the starting state.
    """
    target_path = WORK / case["target"]
    if case.get("seed_content"):
        # buggy seed — write the case's starting state directly
        content = case["seed_content"]
    else:
        content = (SINDICO_SRC / case["target"]).read_text(encoding="utf-8")
    target_path.write_text(content, encoding="utf-8")
    hidden_dir = WORK / "tests" / "unit" / "Core" / "Hidden"
    for old in hidden_dir.glob("*Test.php"):
        old.unlink()
    if case.get("hidden_test"):
        src_test = ROOT / "bench" / "sindico_hidden" / case["hidden_test"]
        (hidden_dir / case["hidden_test"]).write_text(
            src_test.read_text(encoding="utf-8"), encoding="utf-8"
        )
    return content


def run_phpunit(target_rel: str, code: str) -> bool:
    """Write code to target, run the full phpunit suite. Pass = exit 0."""
    (WORK / target_rel).write_text(code, encoding="utf-8")
    try:
        p = subprocess.run(
            ["vendor/bin/phpunit", "--configuration", "phpunit.xml.dist"],
            cwd=WORK,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False
    return p.returncode == 0


def majority(codes: list[str]) -> tuple[str | None, int]:
    """Return (most-common normalized code, its count) over the list."""
    if not codes:
        return None, 0
    norm = [normalize(c) for c in codes]
    counter = Counter(norm)
    code, count = counter.most_common(1)[0]
    return code, count


# ---- main runner ---- #


def fanout_at(
    n: int, case: dict, runtime: SubagentRuntime, file_content: str, model_id: str
) -> dict:
    user_prompt = build_prompt(case, file_content)
    prompts = [{"system": CLI_SYSTEM, "prompt": user_prompt} for _ in range(n)]
    # use_cache=False so every subagent is an independent provider call (the
    # kernel's ReceiptCache otherwise replays identical-prompt responses and
    # collapses the modal distribution we're measuring).
    report = runtime.run(
        task=f"impl {case['id']}", subagents=n, prompts=prompts, use_cache=False
    )
    codes = [extract_php(r.text) for r in report.results if r.ok]
    # functional scoring: real phpunit on every subagent's solution
    fn_passes = sum(run_phpunit(case["target"], c) for c in codes)
    # regex scoring: structural pattern match on each output (cheap proxy)
    rx_patterns = REGEX_CHECKS_BY_TASK.get(case["id"], [])
    rx_full_pass = 0  # subagents where EVERY regex pattern matched
    rx_match_total = 0  # sum of matched-pattern count across subagents
    for c in codes:
        m, t = regex_score(c, rx_patterns)
        if t > 0 and m == t:
            rx_full_pass += 1
        rx_match_total += m
    rx_denom = max(len(codes) * max(len(rx_patterns), 1), 1)
    # modal vote
    maj_code, maj_count = majority(codes)
    maj_fn_pass = run_phpunit(case["target"], maj_code) if maj_code else False
    if maj_code:
        m, t = regex_score(maj_code, rx_patterns)
        maj_rx_full_pass = t > 0 and m == t
        maj_rx_pct = 100 * m // max(t, 1)
    else:
        maj_rx_full_pass, maj_rx_pct = False, 0
    uniques = len({code_hash(c) for c in codes})
    out = {
        "model": model_id,
        "task": case["id"],
        "n": n,
        "completed": report.completed,
        "failed": report.failed,
        # functional metric (real phpunit)
        "fn_per_attempt_pass": fn_passes,
        "fn_per_attempt_rate": 100 * fn_passes // max(report.completed, 1),
        "fn_majority_pass": maj_fn_pass,
        # regex metric (structural shape check)
        "rx_full_pass": rx_full_pass,
        "rx_full_pass_rate": 100 * rx_full_pass // max(report.completed, 1),
        "rx_match_pct": 100 * rx_match_total // rx_denom,
        "rx_majority_full_pass": maj_rx_full_pass,
        "rx_majority_pct": maj_rx_pct,
        # diagnostics
        "unique_outputs": uniques,
        "majority_count": maj_count,
        "tokens": report.usage.total_tokens,
        "cost_usd": float(report.usage.cost_usd),
        "elapsed_s": report.elapsed_s,
    }
    print(
        f"  N={n:<4d} {case['id']:<33s} "
        f"fn {fn_passes:>3d}/{report.completed} ({out['fn_per_attempt_rate']:>3d}%) "
        f"modal {'P' if maj_fn_pass else '.'} | "
        f"rx {rx_full_pass:>3d}/{report.completed} ({out['rx_full_pass_rate']:>3d}%) "
        f"modal {'P' if maj_rx_full_pass else '.'} | "
        f"uniq {uniques:>3d} | {report.usage.total_tokens:>7,} tok | "
        f"${report.usage.cost_usd:.4f} | {report.elapsed_s:>5.1f}s",
        flush=True,
    )
    return out


def run() -> int:
    if not SINDICO_SRC.exists():
        raise SystemExit(f"sindico source not found at {SINDICO_SRC}")

    setup_workspace_base()
    models_str = os.environ.get(
        "BENCH_FANOUT_MODELS",
        ",".join(
            (
                *QWEN3_CODER_DEFAULTS,
                "meta-llama/llama-3.1-8b-instruct",
                "google/gemini-3.5-flash",
            )
        ),
    )
    models = [m.strip() for m in models_str.split(",") if m.strip()]
    ns_str = os.environ.get("BENCH_FANOUT_NS", "200")
    ns = [int(x) for x in ns_str.split(",") if x.strip()]
    task_filter = os.environ.get("BENCH_FANOUT_TASKS", "").strip()
    tasks = (
        CASES
        if not task_filter
        else [c for c in CASES if c["id"] in task_filter.split(",")]
    )
    print(
        f"fanout benchmark: temp=0.7 N={ns} models={len(models)} tasks={len(tasks)}",
        flush=True,
    )

    # Resume from a checkpoint: skip (model, task, N) tuples already in
    # results_fanout.json so a killed/restarted matrix doesn't redo paid work.
    rows: list[dict] = []
    if RESULTS_JSON.exists():
        try:
            saved = json.loads(RESULTS_JSON.read_text()).get("rows", [])
            rows = [
                r
                for r in saved
                if r.get("model") in models
                and r.get("task") in {c["id"] for c in tasks}
                and r.get("n") in ns
            ]
            if rows:
                print(
                    f"resuming: {len(rows)} fanouts already in checkpoint, "
                    f"skipping those",
                    flush=True,
                )
        except Exception as e:
            print(f"checkpoint unreadable ({e}), starting fresh", flush=True)

    done = {(r["model"], r["task"], r["n"]) for r in rows}

    for model_id in models:
        if all((model_id, c["id"], n) in done for c in tasks for n in ns):
            print(f"\n##### MODEL: {model_id} (all done, skipping) #####", flush=True)
            continue
        print(f"\n##### MODEL: {model_id} #####", flush=True)
        runtime = make_runtime(model_id)
        for case in tasks:
            if all((model_id, case["id"], n) in done for n in ns):
                continue
            print(f"\n=== task: {case['id']} ===", flush=True)
            file_content = install_case(case)
            for n in ns:
                if (model_id, case["id"], n) in done:
                    print(
                        f"  N={n:<4d} {case['id']:<33s} [skip - already in checkpoint]",
                        flush=True,
                    )
                    continue
                rows.append(fanout_at(n, case, runtime, file_content, model_id))
                RESULTS_JSON.write_text(json.dumps({"rows": rows}, indent=2))

    write_reports(models, tasks, ns, rows)
    return 0


def _group_by_task(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(r["task"], []).append(r)
    return out


def _filter(rows: list[dict], *, model=None, n=None, task=None) -> list[dict]:
    out = rows
    if model is not None:
        out = [r for r in out if r["model"] == model]
    if n is not None:
        out = [r for r in out if r["n"] == n]
    if task is not None:
        out = [r for r in out if r["task"] == task]
    return out


def _agg(rows: list[dict]) -> dict:
    """Aggregate fn + rx metrics over a subset of rows."""
    completed = sum(r["completed"] for r in rows)
    fn_pass = sum(r["fn_per_attempt_pass"] for r in rows)
    rx_full = sum(r["rx_full_pass"] for r in rows)
    fn_modal = sum(1 for r in rows if r["fn_majority_pass"])
    rx_modal = sum(1 for r in rows if r["rx_majority_full_pass"])
    tokens = sum(r["tokens"] for r in rows)
    cost = sum(r["cost_usd"] for r in rows)
    elapsed = sum(r["elapsed_s"] for r in rows)
    return {
        "rows": len(rows),
        "completed": completed,
        "fn_pass": fn_pass,
        "fn_pct": 100 * fn_pass // max(completed, 1),
        "rx_full": rx_full,
        "rx_pct": 100 * rx_full // max(completed, 1),
        "fn_modal": fn_modal,
        "rx_modal": rx_modal,
        "tokens": tokens,
        "cost": cost,
        "elapsed": elapsed,
    }


def write_reports(
    models: list[str], tasks: list[dict], ns: list[int], rows: list[dict]
) -> None:
    by_task = _group_by_task(rows)
    n_tasks = len(by_task)
    task_ids = [c["id"] for c in tasks]

    ns_label = ", ".join(str(n) for n in ns)
    md = [
        f"# Fan-out benchmark — regex vs functional, 4 models × N ∈ {{{ns_label}}}",
        "",
        f"Date: **{time.strftime('%Y-%m-%d')}**  ",
        "Engine: `kernel.subagent_runtime.SubagentRuntime` from "
        "simplicio-prompt v1.7.0 (PyPI) · `use_cache=False` (every subagent "
        "is an independent provider call) · `temperature=0.7` (induces real "
        "per-call variance).  ",
        "Target project: [`wesleysimplicio/sistema-sindico`](https://github.com/wesleysimplicio/sistema-sindico) "
        "— real PHP 8 condominium system on GitHub.  ",
        "Models: " + ", ".join(f"`{m}`" for m in models) + "  ",
        "N values: "
        + ", ".join(
            f"**{n}**" + (" *(sp default)*" if n == SP_DEFAULT_N else "") for n in ns
        )
        + "  ",
        f"Tasks: **{n_tasks}** real engineering changes across "
        "`src/Core/`, `src/Middleware/`, `src/Repositories/`, and routing "
        "(includes one bug-fix task that scores against the existing "
        "`PasswordPolicyTest`, not a new hidden test).",
        "",
        "## Methodology",
        "",
        "For each (model, task, N), the simplicio-prompt **kernel** launches "
        "N real parallel LLM calls on the same prompt (simplicio-cli 6-layer "
        "wrap of the task). Every returned solution is scored TWO ways:",
        "",
        "1. **Functional (real PHPUnit)** — write the solution to the target "
        "file in a working copy of sistema-sindico, install the hidden test "
        "for the case (or just keep the existing suite for the bug-fix task), "
        "run `vendor/bin/phpunit --configuration phpunit.xml.dist`. Pass = "
        "exit code 0.",
        "2. **Regex (cheap structural proxy)** — match a small set of patterns "
        "against the solution text (method declared? right keywords? uses the "
        "expected APIs?). Per-task patterns in "
        "`sindico_cases.REGEX_CHECKS_BY_TASK`.",
        "",
        "**The point of carrying both metrics**: where they AGREE, regex is a "
        "reasonable cheap proxy; where they DISAGREE (especially regex-PASS "
        "while phpunit-FAIL), regex is misleading and the criticism that "
        "'regex doesn't mean the code works' is correct.",
        "",
        "## Headline — per (model, N) aggregate across tasks",
        "",
        "| Model | N | fn per-attempt | rx per-attempt | fn modal | rx modal | Tokens | Cost | Avg s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in models:
        for n in ns:
            sub = _filter(rows, model=m, n=n)
            if not sub:
                continue
            a = _agg(sub)
            label = f"**{n}**" + (" *(default)*" if n == SP_DEFAULT_N else "")
            md.append(
                f"| `{m}` | {label} | "
                f"{a['fn_pass']}/{a['completed']} ({a['fn_pct']}%) | "
                f"{a['rx_full']}/{a['completed']} ({a['rx_pct']}%) | "
                f"{a['fn_modal']}/{a['rows']} | "
                f"{a['rx_modal']}/{a['rows']} | "
                f"{a['tokens']:,} | ${a['cost']:.4f} | "
                f"{a['elapsed'] / max(a['rows'], 1):.1f}s |"
            )

    md += [
        "",
        "## Per N (aggregate across all models)",
        "",
        "| N | fn per-attempt | rx per-attempt | fn-vs-rx gap | fn modal | rx modal |",
        "|---|---|---|---|---|---|",
    ]
    for n in ns:
        a = _agg(_filter(rows, n=n))
        gap = a["rx_pct"] - a["fn_pct"]
        md.append(
            f"| **{n}**{' *(default)*' if n == SP_DEFAULT_N else ''} | "
            f"{a['fn_pass']}/{a['completed']} ({a['fn_pct']}%) | "
            f"{a['rx_full']}/{a['completed']} ({a['rx_pct']}%) | "
            f"**{gap:+d}** | "
            f"{a['fn_modal']}/{a['rows']} | "
            f"{a['rx_modal']}/{a['rows']} |"
        )

    md += [
        "",
        "## Regex-vs-functional disagreement (per task, averaged across models × N)",
        "",
        "When the regex score is much higher than phpunit (positive gap), "
        "regex is a **false positive** — the code looks right but doesn't "
        "actually pass. When phpunit is higher, regex misses real wins.",
        "",
        "| Task | fn per-attempt | rx per-attempt | gap (rx − fn) |",
        "|---|---|---|---|",
    ]
    for tid in task_ids:
        a = _agg(_filter(rows, task=tid))
        gap = a["rx_pct"] - a["fn_pct"]
        flag = ""
        if gap >= 20:
            flag = " ⚠️ regex inflates"
        elif gap <= -20:
            flag = " ⚠️ regex misses"
        md.append(f"| `{tid}` | {a['fn_pct']}% | {a['rx_pct']}% | **{gap:+d}**{flag} |")

    md += [
        "",
        "## Per-task × model × N detail",
        "",
        "Format: `fn% / rx% / fn-modal-pass`. P = phpunit modal PASS, . = fail.",
        "",
    ]
    for tid in task_ids:
        md += [
            f"### `{tid}`",
            "",
            "| Model \\\\ N | " + " | ".join(str(n) for n in ns) + " |",
            "|---|" + "|".join("---" for _ in ns) + "|",
        ]
        for m in models:
            cells = []
            for n in ns:
                sub = _filter(rows, model=m, n=n, task=tid)
                if not sub:
                    cells.append("—")
                    continue
                r = sub[0]
                fnp = "P" if r["fn_majority_pass"] else "."
                cells.append(
                    f"{r['fn_per_attempt_rate']:>3d}% / "
                    f"{r['rx_full_pass_rate']:>3d}% / {fnp}"
                )
            md.append(f"| `{m.split('/')[-1]}` | " + " | ".join(cells) + " |")
        md.append("")

    RESULTS_MD.write_text("\n".join(md))
    print(f"\n-> {RESULTS_MD}")
    _pdf(models, tasks, ns, rows)


def _pdf(models: list[str], tasks: list[dict], ns: list[int], rows: list[dict]) -> None:
    try:
        from fpdf import FPDF
    except BaseException as e:
        # fpdf2 transitively imports cryptography which can panic on
        # mis-linked native bindings (PyO3 PanicException is BaseException).
        print(f"[warn] fpdf2 unavailable ({type(e).__name__}); skipping PDF.")
        return
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    L = ro._lat1

    def h1(t):
        pdf.set_font("Helvetica", "B", 15)
        pdf.multi_cell(0, 8, L(t))
        pdf.ln(1)

    def h2(t):
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 7, L(t))
        pdf.ln(1)

    def p(t):
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, L(t))
        pdf.ln(1)

    def th(cols, w):
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(230, 230, 230)
        for c, x in zip(cols, w):
            pdf.cell(x, 6, L(c), border=1, fill=True)
        pdf.ln()

    def tr(cells, w):
        pdf.set_font("Helvetica", "", 9)
        for c, x in zip(cells, w):
            pdf.cell(x, 6, L(c), border=1)
        pdf.ln()

    task_ids = [c["id"] for c in tasks]

    pdf.add_page()
    h1("Fan-out - regex vs functional on sistema-sindico")
    p(
        f"Date: {time.strftime('%Y-%m-%d')}   Models: {len(models)}   "
        f"Tasks: {len(tasks)}   N values: {', '.join(str(n) for n in ns)}   "
        f"temperature: 0.7   use_cache: False"
    )
    p(
        "Engine: kernel.subagent_runtime.SubagentRuntime (PyPI simplicio-prompt "
        "1.7.0). For each (model, task, N), N real parallel LLM calls through "
        "LaneWorkerPool; each output scored TWO ways: real PHPUnit (functional) "
        "and a regex pattern match (structural cheap proxy). The comparison "
        "shows where regex agrees with phpunit (cheap proxy works) and where "
        "regex inflates a pass that phpunit fails (regex is misleading)."
    )
    pdf.ln(1)

    h2("Per (model, N) headline")
    th(
        ["Model", "N", "fn per-att", "rx per-att", "fn modal", "rx modal", "Cost"],
        [56, 14, 30, 30, 22, 22, 22],
    )
    for m in models:
        for n in ns:
            sub = _filter(rows, model=m, n=n)
            if not sub:
                continue
            a = _agg(sub)
            tr(
                [
                    m,
                    str(n),
                    f"{a['fn_pct']}%",
                    f"{a['rx_pct']}%",
                    f"{a['fn_modal']}/{a['rows']}",
                    f"{a['rx_modal']}/{a['rows']}",
                    f"${a['cost']:.4f}",
                ],
                [56, 14, 30, 30, 22, 22, 22],
            )
    pdf.ln(2)

    h2("Per N (all models)")
    th(
        ["N", "fn per-att", "rx per-att", "gap", "fn modal", "rx modal"],
        [22, 32, 32, 22, 32, 32],
    )
    for n in ns:
        a = _agg(_filter(rows, n=n))
        gap = a["rx_pct"] - a["fn_pct"]
        tr(
            [
                str(n),
                f"{a['fn_pct']}%",
                f"{a['rx_pct']}%",
                f"{gap:+d}",
                f"{a['fn_modal']}/{a['rows']}",
                f"{a['rx_modal']}/{a['rows']}",
            ],
            [22, 32, 32, 22, 32, 32],
        )
    pdf.ln(2)

    h2("Regex vs phpunit gap per task")
    th(["Task", "fn", "rx", "gap (rx-fn)", "verdict"], [60, 22, 22, 28, 50])
    for tid in task_ids:
        a = _agg(_filter(rows, task=tid))
        gap = a["rx_pct"] - a["fn_pct"]
        if gap >= 20:
            verdict = "regex INFLATES (false positive)"
        elif gap <= -20:
            verdict = "regex misses real wins"
        else:
            verdict = "regex agrees with phpunit"
        tr(
            [tid, f"{a['fn_pct']}%", f"{a['rx_pct']}%", f"{gap:+d}", verdict],
            [60, 22, 22, 28, 50],
        )

    pdf.ln(2)
    h2("Interpretation")
    p(
        "Functional (fn) = real phpunit exit code 0 on the FULL sindico suite "
        "including the per-case hidden test (or, for the bug-fix task, the "
        "existing PasswordPolicyTest). Regex (rx) = 'every structural pattern "
        "matched' on the generated file (per-task patterns in "
        "REGEX_CHECKS_BY_TASK). Where rx >> fn the regex metric inflates "
        "results -- code looks right but doesn't run; where they agree, regex "
        "is a usable cheap proxy."
    )
    pdf.output(str(RESULTS_PDF))
    print(f"-> {RESULTS_PDF}")


if __name__ == "__main__":
    raise SystemExit(run())
