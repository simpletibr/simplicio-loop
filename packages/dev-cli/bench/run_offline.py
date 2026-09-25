"""
Standalone bench runner — no heavy deps, only stdlib + an HTTP key.

Compares two prompts head-to-head on the *same* model(s):
  WITHOUT: raw one-line goal (baseline)
  WITH:    same goal wrapped in simplicio's 6-layer contract (target,
           criteria, constraints, output shape).

Scoring is deterministic: each case lists hard regex checks the model
output must satisfy. No LLM judging the LLM. Same model on both sides —
only the prompt structure changes. Runs across multiple models so the
result is a property of the *method*, not of one model.

Usage:
  HF_TOKEN=... \\
    BENCH_BASE_URL=https://router.huggingface.co/v1 \\
    BENCH_MODELS="Qwen/Qwen3-Coder-30B-A3B-Instruct,Qwen/Qwen3-Coder-Next" \\
    python3 bench/run_offline.py
"""
from __future__ import annotations
import json, os, re, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "bench" / "cases_offline.json"
RESULTS_MD = ROOT / "bench" / "results.md"
RESULTS_JSON = ROOT / "bench" / "results.json"
RESULTS_PDF = ROOT / "bench" / "results.pdf"
CHART_DIR = ROOT / "bench" / "charts"

MODELS = [m.strip() for m in os.environ.get(
    "BENCH_MODELS",
    "Qwen/Qwen3-Coder-30B-A3B-Instruct,Qwen/Qwen3-Coder-Next"
).split(",") if m.strip()]
BASE_URL = os.environ.get("BENCH_BASE_URL", "https://router.huggingface.co/v1")
API_KEY = (
    os.environ.get("BENCH_API_KEY")
    or os.environ.get("HF_TOKEN")
    or os.environ.get("OPENROUTER_API_KEY")
)
INCLUDE_SP = os.environ.get("BENCH_INCLUDE_SP", "0").strip() not in ("0", "false", "False")
INCLUDE_AGENTS = os.environ.get("BENCH_INCLUDE_AGENTS", "0").strip() not in ("0", "false", "False")
INCLUDE_SP_AG = os.environ.get("BENCH_INCLUDE_SP_AG", "0").strip() not in ("0", "false", "False")
AGENTS_MAX_ATTEMPTS = int(os.environ.get("BENCH_AGENTS_MAX_ATTEMPTS", "3"))

# Per-model endpoint routing (mirrors bench/run_exec_sindico.py). Lets one
# batch mix HuggingFace router models with OpenRouter models — `_route_for()`
# swaps BASE_URL + API_KEY before each model loop. The module-level BASE_URL
# above stays as the fallback for models not listed here.
MODEL_ROUTING: dict[str, dict] = {
    "Qwen/Qwen2.5-Coder-3B-Instruct": {
        "base_url": "https://router.huggingface.co/v1", "env_key": "HF_TOKEN",
    },
    "Qwen/Qwen2.5-Coder-7B-Instruct": {
        "base_url": "https://router.huggingface.co/v1", "env_key": "HF_TOKEN",
    },
    "Qwen/Qwen3-Coder-30B-A3B-Instruct": {
        "base_url": "https://router.huggingface.co/v1", "env_key": "HF_TOKEN",
    },
    "Qwen/Qwen3-Coder-Next": {
        "base_url": "https://router.huggingface.co/v1", "env_key": "HF_TOKEN",
    },
}


def _route_for(model: str) -> None:
    """Update module globals BASE_URL + API_KEY for this model's endpoint."""
    global BASE_URL, API_KEY
    cfg = MODEL_ROUTING.get(model)
    if cfg is None:
        BASE_URL = os.environ.get("BENCH_BASE_URL", "https://router.huggingface.co/v1")
        API_KEY = (os.environ.get("BENCH_API_KEY")
                   or os.environ.get("HF_TOKEN")
                   or os.environ.get("OPENROUTER_API_KEY"))
        return
    BASE_URL = cfg["base_url"]
    API_KEY = os.environ.get(cfg["env_key"])
    if not API_KEY:
        raise SystemExit(f"missing env var {cfg['env_key']} for model {model}")


def _load_sp_runtime() -> str:
    """Mirror of bench/run_exec_sindico._load_sp_runtime."""
    candidates = [
        os.environ.get("BENCH_SIMPLICIO_PROMPT_PATH"),
        "/tmp/prompt_check/prompts/agent-runtime-execution-prompt.md",
        "node_modules/simplicio-prompt/prompts/agent-runtime-execution-prompt.md",
    ]
    for cand in candidates:
        if cand and Path(cand).is_file():
            return Path(cand).read_text(encoding="utf-8")
    raise SystemExit(
        "simplicio-prompt runtime template not found (needed when "
        "BENCH_INCLUDE_SP=1). Set BENCH_SIMPLICIO_PROMPT_PATH."
    )


SP_RUNTIME = _load_sp_runtime() if INCLUDE_SP else ""

SP_PROMPT_REGEX = """{sp_runtime}

---

[USER INPUT - task X]
{cli_contract}"""

AGENTS_RETRY_PROMPT_REGEX = """Retry feedback for attempt {attempt}:

Your previous attempt missed these required structural patterns (regex):
{missing}

Apply the SMALLEST correction so all patterns match. Output ONLY the corrected DIFF + TEST block (same shape as the contract specifies). No prose."""

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


# ---------- local transformers backend (model id prefixed "local:") ---------- #
# Use Qwen3 Coder GGUF/OpenAI-compatible servers when the hardware can host the
# MoE defaults. The local transformers path remains for small legacy weights
# that hosted providers do not serve (for example Qwen2.5-Coder-1.5B).

_LOCAL_MODELS: dict = {}
_GGUF_MODELS: dict = {}


def _load_local(model_id: str):
    if model_id not in _LOCAL_MODELS:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(
            model_id, torch_dtype=torch.float32, low_cpu_mem_usage=True
        )
        model.eval()
        _LOCAL_MODELS[model_id] = (tok, model)
    return _LOCAL_MODELS[model_id]


def _load_gguf(gguf_path: str):
    """Load a GGUF model via llama-cpp-python. Path can be absolute or
    relative to ~/models. CPU-only inference; supports Q4_K_M / Q5_K_M /
    Q8_0 quants standardly published by bartowski."""
    if gguf_path in _GGUF_MODELS:
        return _GGUF_MODELS[gguf_path]
    from llama_cpp import Llama
    import os as _os
    full = gguf_path if _os.path.isabs(gguf_path) else _os.path.expanduser(
        f"~/models/{gguf_path}"
    )
    if not _os.path.isfile(full):
        raise FileNotFoundError(f"GGUF model not found: {full}")
    llm = Llama(
        model_path=full,
        n_ctx=int(_os.environ.get("BENCH_GGUF_CTX", "4096")),
        n_threads=int(_os.environ.get("BENCH_GGUF_THREADS", "4")),
        verbose=False,
        seed=int(_os.environ.get("BENCH_GGUF_SEED", "-1")),
    )
    _GGUF_MODELS[gguf_path] = llm
    return llm


def gguf_call(gguf_path: str, prompt: str) -> dict:
    """Run prompt through a llama.cpp GGUF model. Returns the same shape
    as local_call/llm_call so the rest of the bench harness can call it
    transparently when model_id starts with 'gguf:'."""
    max_new = int(os.environ.get("BENCH_LOCAL_MAX_TOKENS", "1024"))
    t0 = time.perf_counter()
    try:
        llm = _load_gguf(gguf_path)
        msgs = [{"role": "user", "content": prompt}]
        out = llm.create_chat_completion(
            messages=msgs,
            max_tokens=max_new,
            temperature=float(os.environ.get("BENCH_LOCAL_TEMP", "0.7")),
            top_p=0.9,
        )
        text = out["choices"][0]["message"]["content"]
        usage = out.get("usage") or {}
        return {
            "text": text,
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "error": None,
        }
    except Exception as e:
        return {
            "text": "", "prompt_tokens": 0, "completion_tokens": 0,
            "total_tokens": 0,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(e),
        }


def local_call(model_id: str, prompt: str) -> dict:
    # Route to GGUF backend when the model_id contains a path to a .gguf file.
    if model_id.startswith("gguf:") or model_id.endswith(".gguf"):
        return gguf_call(
            model_id[5:] if model_id.startswith("gguf:") else model_id,
            prompt,
        )
    import torch
    max_new = int(os.environ.get("BENCH_LOCAL_MAX_TOKENS", "1024"))
    t0 = time.perf_counter()
    try:
        tok, model = _load_local(model_id)
        text = tok.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False, add_generation_prompt=True,
        )
        inputs = tok(text, return_tensors="pt")
        prompt_tokens = int(inputs["input_ids"].shape[1])
        with torch.no_grad():
            out = model.generate(
                **inputs, max_new_tokens=max_new,
                do_sample=False, pad_token_id=tok.eos_token_id,
            )
        gen = out[0][prompt_tokens:]
        completion = tok.decode(gen, skip_special_tokens=True)
        completion_tokens = int(gen.shape[0])
        return {
            "text": completion,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "error": None,
        }
    except Exception as e:
        return {
            "text": f"[BENCH_ERROR] {e}",
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(e),
        }


def llm_call(model: str, prompt: str, timeout: int = 120) -> dict:
    if model.startswith("local:") or model.startswith("gguf:") or model.endswith(".gguf"):
        return local_call(model.split(":", 1)[1] if ":" in model else model, prompt)
    if not API_KEY:
        raise SystemExit("set BENCH_API_KEY, HF_TOKEN, or OPENROUTER_API_KEY")
    body = json.dumps({
        "model": model,
        "max_tokens": 8192,
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
            "X-Title": "simplicio-cli bench",
        },
    )
    retries = int(os.environ.get("BENCH_HTTP_RETRIES", "4"))
    t0 = time.perf_counter()
    last_err = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            usage = data.get("usage") or {}
            msg = data["choices"][0].get("message") or {}
            text = msg.get("content") or msg.get("reasoning") or ""
            return {
                "text": text,
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
                "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                "error": None,
            }
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(2 ** attempt)  # transient router/SSL hiccup: back off and retry
    return {
        "text": f"[BENCH_ERROR] {last_err}",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "error": str(last_err),
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


# ---------- SVG charts (no matplotlib) ---------- #

def _svg_bar_compare(title: str, labels: list[str], sem: list[float], com: list[float],
                     ymax: float = 100.0, unit: str = "%") -> str:
    """Grouped bar chart: sem (gray) vs com (blue) per label."""
    n = len(labels)
    bar_w = 28
    group_w = bar_w * 2 + 14
    chart_w = max(560, 90 + group_w * n + 20)
    chart_h = 360
    pad_l, pad_b, pad_t = 60, 90, 50
    plot_h = chart_h - pad_t - pad_b
    ax_y = pad_t + plot_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {chart_w} {chart_h}" font-family="-apple-system,Segoe UI,Roboto,sans-serif" font-size="12">',
        '<style>.bar-sem{fill:#aaa}.bar-com{fill:#2962ff}.lbl{fill:#222}.ax{stroke:#888;stroke-width:1}.grid{stroke:#eee;stroke-width:1}</style>',
        f'<text x="{chart_w/2}" y="22" text-anchor="middle" font-weight="600" font-size="14">{title}</text>',
    ]
    # gridlines
    for i in range(5):
        y = pad_t + plot_h * i / 4
        v = ymax * (1 - i / 4)
        parts.append(f'<line x1="{pad_l}" y1="{y}" x2="{chart_w-10}" y2="{y}" class="grid"/>')
        parts.append(f'<text x="{pad_l-6}" y="{y+4}" text-anchor="end" fill="#666">{v:.0f}{unit}</text>')
    # axes
    parts.append(f'<line x1="{pad_l}" y1="{ax_y}" x2="{chart_w-10}" y2="{ax_y}" class="ax"/>')
    parts.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{ax_y}" class="ax"/>')
    # bars
    for i, lbl in enumerate(labels):
        gx = pad_l + 30 + i * group_w
        hs = plot_h * (sem[i] / ymax)
        hc = plot_h * (com[i] / ymax)
        parts.append(f'<rect x="{gx}" y="{ax_y - hs}" width="{bar_w}" height="{hs}" class="bar-sem"/>')
        parts.append(f'<rect x="{gx + bar_w + 6}" y="{ax_y - hc}" width="{bar_w}" height="{hc}" class="bar-com"/>')
        parts.append(f'<text x="{gx + bar_w/2}" y="{ax_y - hs - 4}" text-anchor="middle" fill="#444" font-size="10">{sem[i]:.0f}</text>')
        parts.append(f'<text x="{gx + bar_w + 6 + bar_w/2}" y="{ax_y - hc - 4}" text-anchor="middle" fill="#2962ff" font-size="10">{com[i]:.0f}</text>')
        # rotated label
        cx = gx + bar_w + 3
        parts.append(f'<text x="{cx}" y="{ax_y + 14}" transform="rotate(-25 {cx} {ax_y + 14})" text-anchor="end" class="lbl">{lbl}</text>')
    # legend
    lx = chart_w - 220
    parts.append(f'<rect x="{lx}" y="32" width="14" height="10" class="bar-sem"/>')
    parts.append(f'<text x="{lx+20}" y="42">without simplicio</text>')
    parts.append(f'<rect x="{lx+120}" y="32" width="14" height="10" class="bar-com"/>')
    parts.append(f'<text x="{lx+140}" y="42">with simplicio</text>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_delta(title: str, labels: list[str], deltas: list[float]) -> str:
    n = len(labels)
    bar_w = 36
    chart_w = max(560, 90 + (bar_w + 18) * n + 20)
    chart_h = 320
    pad_l, pad_b, pad_t = 60, 80, 50
    plot_h = chart_h - pad_t - pad_b
    ax_y = pad_t + plot_h / 2  # zero line in the middle
    ymax = max(50, max(abs(d) for d in deltas) + 10) if deltas else 50
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {chart_w} {chart_h}" font-family="-apple-system,Segoe UI,Roboto,sans-serif" font-size="12">',
        '<style>.bar-pos{fill:#2e7d32}.bar-neg{fill:#c62828}.ax{stroke:#444;stroke-width:1.2}.grid{stroke:#eee;stroke-width:1}</style>',
        f'<text x="{chart_w/2}" y="22" text-anchor="middle" font-weight="600" font-size="14">{title}</text>',
    ]
    for i in range(5):
        y = pad_t + plot_h * i / 4
        v = ymax - 2 * ymax * i / 4
        parts.append(f'<line x1="{pad_l}" y1="{y}" x2="{chart_w-10}" y2="{y}" class="grid"/>')
        parts.append(f'<text x="{pad_l-6}" y="{y+4}" text-anchor="end" fill="#666">{v:+.0f} pts</text>')
    parts.append(f'<line x1="{pad_l}" y1="{ax_y}" x2="{chart_w-10}" y2="{ax_y}" class="ax"/>')
    for i, (lbl, d) in enumerate(zip(labels, deltas)):
        bx = pad_l + 30 + i * (bar_w + 18)
        h = abs(d) / ymax * (plot_h / 2)
        cls = "bar-pos" if d >= 0 else "bar-neg"
        y = ax_y - h if d >= 0 else ax_y
        parts.append(f'<rect x="{bx}" y="{y}" width="{bar_w}" height="{h}" class="{cls}"/>')
        ty = (ax_y - h - 6) if d >= 0 else (ax_y + h + 14)
        parts.append(f'<text x="{bx + bar_w/2}" y="{ty}" text-anchor="middle" fill="#222">{d:+.0f}</text>')
        cx = bx + bar_w / 2
        parts.append(f'<text x="{cx}" y="{pad_t + plot_h + 16}" transform="rotate(-25 {cx} {pad_t + plot_h + 16})" text-anchor="end" fill="#222">{lbl}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------- PDF report (fpdf2) ---------- #

def _lat1(s) -> str:
    """Core PDF fonts are latin-1 only; drop anything outside it."""
    return str(s).encode("latin-1", "replace").decode("latin-1")


def build_pdf(by_model: dict, cases: list) -> None:
    try:
        from fpdf import FPDF
    except BaseException as e:
        # fpdf2 transitively imports cryptography which can panic on
        # mis-linked native bindings (PyO3 PanicException is BaseException).
        print(f"[warn] fpdf2 unavailable ({type(e).__name__}); skipping PDF.")
        return

    models = list(by_model.keys())
    n_cases = len(cases)
    stacks = sorted({c["stack"] for c in cases})
    grand_sem = sum(by_model[m]["sem_hits"] for m in models)
    grand_com = sum(by_model[m]["com_hits"] for m in models)
    grand_total = sum(by_model[m]["total"] for m in models)
    gsp = 100 * grand_sem // max(grand_total, 1)
    gcp = 100 * grand_com // max(grand_total, 1)

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)

    def h1(t):
        pdf.set_font("Helvetica", "B", 18); pdf.multi_cell(0, 9, _lat1(t)); pdf.ln(2)

    def h2(t):
        pdf.set_font("Helvetica", "B", 13); pdf.multi_cell(0, 7, _lat1(t)); pdf.ln(1)

    def p(t):
        pdf.set_font("Helvetica", "", 10); pdf.multi_cell(0, 5, _lat1(t)); pdf.ln(1)

    def th(cols, widths):
        pdf.set_font("Helvetica", "B", 9); pdf.set_fill_color(230, 230, 230)
        for c, w in zip(cols, widths):
            pdf.cell(w, 6, _lat1(c), border=1, fill=True)
        pdf.ln()

    def tr(cells, widths):
        pdf.set_font("Helvetica", "", 9)
        for c, w in zip(cells, widths):
            pdf.cell(w, 6, _lat1(c), border=1)
        pdf.ln()

    rel_grand = 100 * (grand_com - grand_sem) / max(grand_sem, 1)
    total_runs = n_cases * max(len(models), 1)

    # ---- page 1: cover + methodology + headline ---- #
    pdf.add_page()
    h1("simplicio-cli - Benchmark")
    p(f"Date: {time.strftime('%Y-%m-%d')}")
    p(f"Models ({len(models)}): {', '.join(models)}")
    p(f"Cases: {n_cases} across stacks: {', '.join(stacks)}")
    p(f"Base: {BASE_URL}")
    p(f"Checks: {grand_total} total ({n_cases} cases x {len(models)} models)")
    pdf.ln(2)
    h2("Method")
    p("Same model on both sides; only the prompt structure changes. The WITHOUT "
      "run sends the raw one-line goal; the WITH run wraps the same goal in "
      "simplicio's 6-layer contract (role/stack, goal, target, precedent, "
      "contract states, output shape). Each check is a deterministic regex "
      "against the model output (target-file mention, DIFF block, TEST block, "
      "contract-state words). No LLM judges the LLM. Models prefixed 'local:' "
      "run on CPU via transformers; the rest go through the OpenAI-compatible "
      "endpoint at the base URL above.")
    pdf.ln(1)
    h2("Headline")
    th(["Side", "Checks passed", "Rate"], [70, 55, 35])
    tr(["Without simplicio", f"{grand_sem}/{grand_total}", f"{gsp}%"], [70, 55, 35])
    tr(["With simplicio", f"{grand_com}/{grand_total}", f"{gcp}%"], [70, 55, 35])
    tr(["Delta", f"{grand_com - grand_sem:+d} checks",
        f"{gcp - gsp:+d} pts ({rel_grand:+.0f}%)"], [70, 55, 35])

    # ---- page 2: per-model + per-case ---- #
    pdf.add_page()
    h1("Per-model breakdown")
    th(["Model", "Without", "With", "Delta(pts)", "Rel.gain"], [78, 28, 28, 24, 24])
    for m in models:
        b = by_model[m]
        rel = 100 * (b["com_hits"] - b["sem_hits"]) / max(b["sem_hits"], 1)
        tr([m, f"{b['sem_hits']}/{b['total']} ({b['sem_pct']}%)",
            f"{b['com_hits']}/{b['total']} ({b['com_pct']}%)",
            f"{b['com_pct'] - b['sem_pct']:+d}", f"{rel:+.0f}%"], [78, 28, 28, 24, 24])

    pdf.ln(3)
    h2("Per-case (avg across models)")
    th(["#", "Stack", "Goal", "Without", "With", "Delta"], [10, 22, 84, 20, 20, 20])
    for i, c in enumerate(cases):
        s_pcts = [100 * by_model[m]["rows"][i]["sem_hits"] / max(by_model[m]["rows"][i]["total"], 1) for m in models]
        c_pcts = [100 * by_model[m]["rows"][i]["com_hits"] / max(by_model[m]["rows"][i]["total"], 1) for m in models]
        s_avg = sum(s_pcts) / len(s_pcts)
        c_avg = sum(c_pcts) / len(c_pcts)
        tr([str(i + 1), c["stack"], c["goal"][:50],
            f"{s_avg:.0f}%", f"{c_avg:.0f}%", f"{c_avg - s_avg:+.0f}"], [10, 22, 84, 20, 20, 20])

    # ---- page 3: per-stack + output-quality signals ---- #
    pdf.add_page()
    h1("Per-stack")
    th(["Stack", "Without", "With", "Delta(pts)"], [60, 40, 40, 40])
    for stk in stacks:
        idxs = [i for i, c in enumerate(cases) if c["stack"] == stk]
        s = sum(by_model[m]["rows"][i]["sem_hits"] for m in models for i in idxs)
        cc = sum(by_model[m]["rows"][i]["com_hits"] for m in models for i in idxs)
        t = sum(by_model[m]["rows"][i]["total"] for m in models for i in idxs)
        sp = 100 * s / max(t, 1); cp = 100 * cc / max(t, 1)
        tr([stk, f"{sp:.0f}%", f"{cp:.0f}%", f"{cp - sp:+.0f}"], [60, 40, 40, 40])

    pdf.ln(3)
    h2("Output-quality signals (rate across all runs)")
    th(["Signal", "Without simplicio", "With simplicio"], [80, 50, 50])
    for key, label in (("has_diff_block", "DIFF block present"),
                       ("has_test_block", "TEST block present"),
                       ("target_mentioned", "Target file mentioned")):
        s_count = sum(by_model[m]["quality_sem"][key] for m in models)
        c_count = sum(by_model[m]["quality_com"][key] for m in models)
        tr([label, f"{100*s_count//total_runs}% ({s_count}/{total_runs})",
            f"{100*c_count//total_runs}% ({c_count}/{total_runs})"], [80, 50, 50])
    s_kw = sum(by_model[m]["quality_sem"]["criteria_keywords_hit"] for m in models)
    c_kw = sum(by_model[m]["quality_com"]["criteria_keywords_hit"] for m in models)
    tr(["Avg criteria-keywords / run", f"{s_kw/total_runs:.1f}", f"{c_kw/total_runs:.1f}"], [80, 50, 50])
    s_len = sum(by_model[m]["quality_sem"]["len"] for m in models)
    c_len = sum(by_model[m]["quality_com"]["len"] for m in models)
    tr(["Avg output length (chars)", f"{s_len//total_runs}", f"{c_len//total_runs}"], [80, 50, 50])

    # ---- page 4: cost ---- #
    pdf.add_page()
    h1("Cost - tokens & latency")
    h2("Per-model, average per run")
    th(["Model", "Side", "Prompt", "Compl", "Total", "Latency"], [56, 22, 24, 24, 26, 28])
    for m in models:
        us = by_model[m]["usage_sem"]; uc = by_model[m]["usage_com"]
        tr([m, "without", f"{us['prompt_tokens']//n_cases}", f"{us['completion_tokens']//n_cases}",
            f"{us['total_tokens']//n_cases}", f"{us['elapsed_ms']//n_cases} ms"], [56, 22, 24, 24, 26, 28])
        tr([m, "with", f"{uc['prompt_tokens']//n_cases}", f"{uc['completion_tokens']//n_cases}",
            f"{uc['total_tokens']//n_cases}", f"{uc['elapsed_ms']//n_cases} ms"], [56, 22, 24, 24, 26, 28])

    agg_sem_t = sum(by_model[m]["usage_sem"]["total_tokens"] for m in models)
    agg_com_t = sum(by_model[m]["usage_com"]["total_tokens"] for m in models)
    agg_sem_ms = sum(by_model[m]["usage_sem"]["elapsed_ms"] for m in models)
    agg_com_ms = sum(by_model[m]["usage_com"]["elapsed_ms"] for m in models)
    tok_d = agg_com_t - agg_sem_t
    ms_d = agg_com_ms - agg_sem_ms
    pdf.ln(3)
    h2(f"Aggregate over the full bench ({total_runs} runs / side)")
    th(["Side", "Total tokens", "Wall-clock", "Tok / run", "ms / run"], [40, 38, 36, 32, 30])
    tr(["without", f"{agg_sem_t:,}", f"{agg_sem_ms/1000:.1f}s",
        f"{agg_sem_t//total_runs}", f"{agg_sem_ms//total_runs}"], [40, 38, 36, 32, 30])
    tr(["with", f"{agg_com_t:,}", f"{agg_com_ms/1000:.1f}s",
        f"{agg_com_t//total_runs}", f"{agg_com_ms//total_runs}"], [40, 38, 36, 32, 30])
    tr(["delta", f"{tok_d:+,} ({tok_d*100//max(agg_sem_t,1):+d}%)",
        f"{ms_d/1000:+.1f}s ({ms_d*100//max(agg_sem_ms,1):+d}%)", "", ""], [40, 38, 36, 32, 30])

    # ---- page 5: appendix - per-model x per-case detail ---- #
    pdf.add_page()
    h1("Appendix - per-model x per-case checks")
    for m in models:
        h2(m)
        th(["#", "Stack", "Without", "With", "Delta"], [12, 26, 36, 36, 30])
        for i, c in enumerate(cases):
            r = by_model[m]["rows"][i]
            tr([str(i + 1), c["stack"], f"{r['sem_hits']}/{r['total']}",
                f"{r['com_hits']}/{r['total']}", f"{r['com_hits'] - r['sem_hits']:+d}"], [12, 26, 36, 36, 30])
        pdf.ln(2)

    # ---- reproduce ---- #
    pdf.ln(1)
    h2("How to reproduce")
    p(f"BENCH_BASE_URL={BASE_URL} BENCH_API_KEY=... "
      f"BENCH_MODELS=\"{','.join(models)}\" python3 bench/run_offline.py")
    p("Raw model outputs per case/side are saved under "
      ".simplicio/bench_runs/<model>/case_NN/{sem,com}.txt for audit. "
      "Charts are SVG under bench/charts/; aggregated data under bench/results.json.")

    pdf.output(str(RESULTS_PDF))
    print(f"-> {RESULTS_PDF}")


# ---------- main runner ---------- #

def _agents_iterate_regex(model: str, c: dict, cli_prompt: str) -> dict:
    """Verify-loop with regex checks as the oracle. Up to AGENTS_MAX_ATTEMPTS.
    Returns the BEST score across attempts + cumulative usage."""
    prompt = cli_prompt
    best_text = ""; best_flags = [False] * len(c["checks"])
    best_hits = -1
    total_tokens = 0; total_prompt = 0; total_completion = 0; total_ms = 0
    attempts_used = 0
    for t in range(1, AGENTS_MAX_ATTEMPTS + 1):
        attempts_used = t
        res = llm_call(model, prompt)
        total_tokens += res.get("total_tokens", 0)
        total_prompt += res.get("prompt_tokens", 0)
        total_completion += res.get("completion_tokens", 0)
        total_ms += res.get("elapsed_ms", 0)
        flags = score(res["text"], c["checks"])
        hits = sum(flags)
        if hits > best_hits:
            best_hits = hits; best_flags = flags; best_text = res["text"]
        if hits == len(c["checks"]):
            break  # all patterns matched, done
        # build retry feedback listing the missing patterns
        missing = [p for p, ok in zip(c["checks"], flags) if not ok]
        missing_lines = "\n".join(f"  - {m}" for m in missing)
        prompt = AGENTS_RETRY_PROMPT_REGEX.format(
            attempt=t + 1, missing=missing_lines,
        )
    return {
        "text": best_text, "flags": best_flags, "hits": best_hits,
        "attempts": attempts_used,
        "prompt_tokens": total_prompt, "completion_tokens": total_completion,
        "total_tokens": total_tokens, "elapsed_ms": total_ms,
        "error": None,
    }


def run() -> int:
    cases = json.loads(CASES_PATH.read_text())
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    print(f"models: {MODELS}")
    print(f"cases:  {len(cases)}")
    print(f"sides:  baseline / cli"
          + (" / cli+sp" if INCLUDE_SP else "")
          + (f" / cli+ag (max {AGENTS_MAX_ATTEMPTS} attempts)" if INCLUDE_AGENTS else "")
          + (f" / cli+sp+ag (max {AGENTS_MAX_ATTEMPTS} attempts)" if INCLUDE_SP_AG else ""))
    by_model = {}
    for model in MODELS:
        _route_for(model)
        print(f"\n=== model: {model} (base: {BASE_URL}) ===")
        rows = []
        sem_hits = com_hits = sp_hits = ag_hits = spag_hits = total = 0
        qsum_sem = {"len": 0, "has_diff_block": 0, "has_test_block": 0, "target_mentioned": 0, "criteria_keywords_hit": 0}
        qsum_com = dict(qsum_sem)
        usage_sem = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "elapsed_ms": 0}
        usage_com = dict(usage_sem)
        usage_sp = dict(usage_sem)
        usage_ag = dict(usage_sem)
        usage_spag = dict(usage_sem)
        for i, c in enumerate(cases, 1):
            sem_res = llm_call(model, c["goal"])
            com_prompt = SIX_LAYER_TEMPLATE.format(
                stack=c.get("stack", "angular"),
                goal=c["goal"],
                target=c["target"],
                criteria=c["criteria"],
                constraints=c["constraints"],
            )
            com_res = llm_call(model, com_prompt)
            sem_out = sem_res["text"]
            com_out = com_res["text"]

            s_flags = score(sem_out, c["checks"])
            c_flags = score(com_out, c["checks"])
            s_h, c_h, t = sum(s_flags), sum(c_flags), len(c["checks"])
            sem_hits += s_h; com_hits += c_h; total += t

            qs = quality_metrics(sem_out, c)
            qc = quality_metrics(com_out, c)
            for k in qsum_sem:
                qsum_sem[k] += int(qs[k]) if isinstance(qs[k], bool) else qs[k]
                qsum_com[k] += int(qc[k]) if isinstance(qc[k], bool) else qc[k]
            for k in usage_sem:
                usage_sem[k] += sem_res[k]
                usage_com[k] += com_res[k]

            row = {
                "goal": c["goal"], "stack": c["stack"],
                "sem_hits": s_h, "com_hits": c_h, "total": t,
                "sem_flags": s_flags, "com_flags": c_flags,
                "sem_quality": qs, "com_quality": qc,
                "sem_usage": {k: sem_res[k] for k in usage_sem},
                "com_usage": {k: com_res[k] for k in usage_com},
            }
            sp_msg = ""
            if INCLUDE_SP:
                # MANDATE 2026-05-30 (cycle 1+): gradual escalation
                # 64 → 100 → 200 with regex-all-match as the oracle,
                # structured output schema for better modal-vote on behavior.
                from sp_fanout_helper import sp_fanout_escalating
                sp_prompt = SP_PROMPT_REGEX.format(
                    sp_runtime=SP_RUNTIME, cli_contract=com_prompt)
                checks = c["checks"]
                def regex_oracle(text: str) -> bool:
                    flags = score(text, checks)
                    return sum(flags) == len(checks)
                sp_res_full = sp_fanout_escalating(model, sp_prompt, regex_oracle)
                sp_text = sp_res_full.get("text", "")
                sp_flags = score(sp_text, checks)
                p_h = sum(sp_flags); sp_hits += p_h
                row["sp_hits"] = p_h; row["sp_flags"] = sp_flags
                row["sp_subagents"] = sp_res_full.get("subagents", 0)
                row["sp_uniq"] = sp_res_full.get("uniq", 0)
                row["sp_modal_count"] = sp_res_full.get("modal_count", 0)
                row["sp_cycles_run"] = sp_res_full.get("cycles_run", 0)
                row["sp_escalated"] = sp_res_full.get("escalated", False)
                row["sp_tier_history"] = sp_res_full.get("tier_history", [])
                row["sp_structured_parse_ok"] = sp_res_full.get("structured_parse_ok", 0)
                row["sp_usage"] = {
                    "prompt_tokens": 0, "completion_tokens": 0,
                    "total_tokens": sp_res_full.get("tokens", 0),
                    "elapsed_ms": sp_res_full.get("ms", 0),
                }
                usage_sp["total_tokens"] += sp_res_full.get("tokens", 0)
                usage_sp["elapsed_ms"] += sp_res_full.get("ms", 0)
                tiers = "→".join(str(h["n"]) for h in sp_res_full.get("tier_history", []))
                sp_msg = (f"  sp {p_h}/{t}[tiers={tiers},"
                          f"u={sp_res_full.get('uniq',0)}]")
            ag_msg = ""
            if INCLUDE_AGENTS:
                ag_res = _agents_iterate_regex(model, c, com_prompt)
                a_h = ag_res["hits"]; ag_hits += a_h
                row["ag_hits"] = a_h; row["ag_flags"] = ag_res["flags"]
                row["ag_attempts"] = ag_res["attempts"]
                row["ag_usage"] = {k: ag_res[k] for k in usage_ag}
                for k in usage_ag:
                    usage_ag[k] += ag_res[k]
                ag_msg = f"  ag {a_h}/{t}({ag_res['attempts']})"
            spag_msg = ""
            if INCLUDE_SP_AG:
                # 5th side: N=200 sp-fanout modal first. If modal misses any
                # regex pattern, retry via verify-loop. Composition + retry on
                # top of fan-out.
                from sp_fanout_helper import sp_fanout_complete
                sp_prompt = SP_PROMPT_REGEX.format(
                    sp_runtime=SP_RUNTIME, cli_contract=com_prompt)
                modal_full = sp_fanout_complete(model, sp_prompt)
                modal_flags = score(modal_full.get("text", ""), c["checks"])
                if sum(modal_flags) == len(c["checks"]):
                    spag_res = {
                        "text": modal_full["text"], "flags": modal_flags,
                        "hits": sum(modal_flags), "attempts": 1,
                        "total_tokens": modal_full.get("tokens", 0),
                        "elapsed_ms": modal_full.get("ms", 0),
                        "prompt_tokens": 0, "completion_tokens": 0,
                    }
                else:
                    spag_res = _agents_iterate_regex(model, c, sp_prompt)
                    spag_res["total_tokens"] = spag_res.get("total_tokens", 0) + modal_full.get("tokens", 0)
                    spag_res["elapsed_ms"] = spag_res.get("elapsed_ms", 0) + modal_full.get("ms", 0)
                sa_h = spag_res["hits"]; spag_hits += sa_h
                row["spag_hits"] = sa_h
                row["spag_flags"] = spag_res["flags"]
                row["spag_attempts"] = spag_res["attempts"]
                row["spag_modal_uniq"] = modal_full.get("uniq", 0)
                row["spag_usage"] = {k: spag_res[k] for k in usage_spag}
                for k in usage_spag:
                    usage_spag[k] += spag_res[k]
                spag_msg = f"  sp+ag {sa_h}/{t}({spag_res['attempts']})"
            rows.append(row)
            print(
                f"  [{i:02d}/{len(cases)}] {c['stack']:7s} "
                f"sem {s_h}/{t} com {c_h}/{t}{sp_msg}{ag_msg}{spag_msg}  "
                f"Δcli{c_h-s_h:+d}"
            )

            slug = model.replace("/", "_").replace(":", "_")
            outdir = ROOT / ".simplicio" / "bench_runs" / slug / f"case_{i:02d}"
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "sem.txt").write_text(sem_out)
            (outdir / "com.txt").write_text(com_out)

        entry = {
            "rows": rows,
            "sem_hits": sem_hits, "com_hits": com_hits, "total": total,
            "sem_pct": 100 * sem_hits // max(total, 1),
            "com_pct": 100 * com_hits // max(total, 1),
            "quality_sem": qsum_sem, "quality_com": qsum_com,
            "usage_sem": usage_sem, "usage_com": usage_com,
        }
        if INCLUDE_SP:
            entry["sp_hits"] = sp_hits
            entry["sp_pct"] = 100 * sp_hits // max(total, 1)
            entry["usage_sp"] = usage_sp
        if INCLUDE_AGENTS:
            entry["ag_hits"] = ag_hits
            entry["ag_pct"] = 100 * ag_hits // max(total, 1)
            entry["usage_ag"] = usage_ag
        if INCLUDE_SP_AG:
            entry["spag_hits"] = spag_hits
            entry["spag_pct"] = 100 * spag_hits // max(total, 1)
            entry["usage_spag"] = usage_spag
        by_model[model] = entry
        tail = f" | sp {sp_hits}/{total} ({100*sp_hits//max(total,1)}%)" if INCLUDE_SP else ""
        tail += f" | ag {ag_hits}/{total} ({100*ag_hits//max(total,1)}%)" if INCLUDE_AGENTS else ""
        tail += f" | sp+ag {spag_hits}/{total} ({100*spag_hits//max(total,1)}%)" if INCLUDE_SP_AG else ""
        print(f"  -> baseline {sem_hits}/{total} ({entry['sem_pct']}%) "
              f"| cli {com_hits}/{total} ({entry['com_pct']}%){tail}\n")

    build_reports(by_model, cases)
    return 0


def build_reports(by_model: dict, cases: list) -> int:
    # ---- write artifacts ---- #
    RESULTS_JSON.write_text(json.dumps(by_model, indent=2))

    # per-model overall chart
    overall_labels = [m.split("/")[-1] for m in MODELS]
    overall_sem = [by_model[m]["sem_pct"] for m in MODELS]
    overall_com = [by_model[m]["com_pct"] for m in MODELS]
    overall_delta = [c - s for c, s in zip(overall_com, overall_sem)]
    (CHART_DIR / "overall.svg").write_text(_svg_bar_compare(
        "Pass rate by model — without vs with simplicio", overall_labels,
        overall_sem, overall_com,
    ))
    (CHART_DIR / "delta.svg").write_text(_svg_delta(
        "Gain from simplicio (points) — by model", overall_labels, overall_delta,
    ))

    # per-case chart (average across models)
    case_labels = [f"#{i+1} {cases[i]['stack']}" for i in range(len(cases))]
    case_sem_avg = []
    case_com_avg = []
    for i in range(len(cases)):
        s_pcts = [100 * by_model[m]["rows"][i]["sem_hits"] / by_model[m]["rows"][i]["total"] for m in MODELS]
        c_pcts = [100 * by_model[m]["rows"][i]["com_hits"] / by_model[m]["rows"][i]["total"] for m in MODELS]
        case_sem_avg.append(sum(s_pcts) / len(s_pcts))
        case_com_avg.append(sum(c_pcts) / len(c_pcts))
    (CHART_DIR / "by_case.svg").write_text(_svg_bar_compare(
        "Per-case pass rate (avg across models)", case_labels,
        case_sem_avg, case_com_avg,
    ))

    # per-stack aggregation
    stacks = sorted({c["stack"] for c in cases})
    stack_sem = []
    stack_com = []
    for stk in stacks:
        idxs = [i for i, c in enumerate(cases) if c["stack"] == stk]
        s = sum(by_model[m]["rows"][i]["sem_hits"] for m in MODELS for i in idxs)
        cc = sum(by_model[m]["rows"][i]["com_hits"] for m in MODELS for i in idxs)
        t = sum(by_model[m]["rows"][i]["total"] for m in MODELS for i in idxs)
        stack_sem.append(100 * s / max(t, 1))
        stack_com.append(100 * cc / max(t, 1))
    (CHART_DIR / "by_stack.svg").write_text(_svg_bar_compare(
        "Per-stack pass rate (all models, all cases)", stacks, stack_sem, stack_com,
    ))

    # ---- markdown report ---- #
    n_cases = len(cases)
    grand_sem = sum(by_model[m]["sem_hits"] for m in MODELS)
    grand_com = sum(by_model[m]["com_hits"] for m in MODELS)
    grand_total = sum(by_model[m]["total"] for m in MODELS)
    grand_sem_pct = 100 * grand_sem // max(grand_total, 1)
    grand_com_pct = 100 * grand_com // max(grand_total, 1)

    md = [
        "# Benchmark — simplicio-cli (offline harness)",
        "",
        f"Date: **{time.strftime('%Y-%m-%d')}**  ",
        f"Models: " + ", ".join(f"`{m}`" for m in MODELS) + "  ",
        f"Cases: **{n_cases}** across stacks: " + ", ".join(f"`{s}`" for s in stacks) + "  ",
        f"Base: `{BASE_URL}`",
        "",
        "Each check is a deterministic regex against the model output ",
        "(target-file mention, DIFF block, TEST block, contract-state words). ",
        "Same model on both sides — only the prompt structure changes. The ",
        "*without* run is the raw one-line goal; the *with* run wraps the ",
        "same goal in simplicio's 6-layer contract.",
        "",
        "## Headline",
        "",
        f"- **Without simplicio:** {grand_sem}/{grand_total} ({grand_sem_pct}%)",
        f"- **With simplicio:** {grand_com}/{grand_total} ({grand_com_pct}%)",
        f"- **Delta:** **{grand_com_pct - grand_sem_pct:+d} points** "
        f"({100 * (grand_com - grand_sem) / max(grand_sem, 1):+.0f}% relative)",
        "",
        "![pass rate by model](charts/overall.svg)",
        "",
        "![gain in points](charts/delta.svg)",
        "",
        "## Per-model breakdown",
        "",
        "| Model | Cases | Without | With | Delta (pts) | Relative gain |",
        "|---|---|---|---|---|---|",
    ]
    for m in MODELS:
        b = by_model[m]
        rel = 100 * (b["com_hits"] - b["sem_hits"]) / max(b["sem_hits"], 1)
        md.append(
            f"| `{m}` | {n_cases} | {b['sem_hits']}/{b['total']} ({b['sem_pct']}%) | "
            f"{b['com_hits']}/{b['total']} ({b['com_pct']}%) | "
            f"**{b['com_pct'] - b['sem_pct']:+d}** | {rel:+.0f}% |"
        )

    md += [
        "",
        "## Per-case (averaged across models)",
        "",
        "![per case](charts/by_case.svg)",
        "",
        "| # | Stack | Task | Without | With | Δ |",
        "|---|---|---|---|---|---|",
    ]
    for i, c in enumerate(cases, 1):
        s_avg = case_sem_avg[i-1]
        c_avg = case_com_avg[i-1]
        md.append(
            f"| {i} | `{c['stack']}` | {c['goal'][:60]} | "
            f"{s_avg:.0f}% | {c_avg:.0f}% | **{c_avg - s_avg:+.0f}** |"
        )

    md += [
        "",
        "## Per-stack",
        "",
        "![per stack](charts/by_stack.svg)",
        "",
        "| Stack | Without | With | Δ |",
        "|---|---|---|---|",
    ]
    for stk, sp, cp in zip(stacks, stack_sem, stack_com):
        md.append(f"| `{stk}` | {sp:.0f}% | {cp:.0f}% | **{cp - sp:+.0f}** |")

    md += [
        "",
        "## Output-quality signals (rate across all runs)",
        "",
        "Beyond pass-rate, the same outputs are scored on structural quality. ",
        "Each row = % of runs (cases × models) where the signal is present.",
        "",
        "| Signal | Without simplicio | With simplicio |",
        "|---|---|---|",
    ]
    total_runs = n_cases * len(MODELS)
    signals = [
        ("has_diff_block", "DIFF block present"),
        ("has_test_block", "TEST block present"),
        ("target_mentioned", "target file mentioned"),
    ]
    for key, label in signals:
        s_count = sum(by_model[m]["quality_sem"][key] for m in MODELS)
        c_count = sum(by_model[m]["quality_com"][key] for m in MODELS)
        md.append(
            f"| {label} | {100*s_count//total_runs}% ({s_count}/{total_runs}) | "
            f"{100*c_count//total_runs}% ({c_count}/{total_runs}) |"
        )
    # avg criteria keyword hits
    s_kw = sum(by_model[m]["quality_sem"]["criteria_keywords_hit"] for m in MODELS)
    c_kw = sum(by_model[m]["quality_com"]["criteria_keywords_hit"] for m in MODELS)
    md.append(f"| avg criteria-keywords hit / run | {s_kw/total_runs:.1f} | {c_kw/total_runs:.1f} |")
    # avg output length
    s_len = sum(by_model[m]["quality_sem"]["len"] for m in MODELS)
    c_len = sum(by_model[m]["quality_com"]["len"] for m in MODELS)
    md.append(f"| avg output length (chars) | {s_len//total_runs} | {c_len//total_runs} |")

    # ---- token & latency cost ---- #
    md += [
        "",
        "## Cost — tokens & wall-clock (measured, per run)",
        "",
        "Reported straight from the provider's `usage` field and `time.perf_counter()`. ",
        "*Per-run* = one model call (one case, one side). With simplicio uses more input ",
        "tokens (the 6-layer wrap) and fewer output tokens (model stops guessing earlier).",
        "",
        "| Model | Side | Avg prompt tok | Avg completion tok | Avg total tok | Avg latency |",
        "|---|---|---|---|---|---|",
    ]
    for m in MODELS:
        b = by_model[m]
        us = b["usage_sem"]; uc = b["usage_com"]
        md.append(
            f"| `{m}` | without | {us['prompt_tokens']//n_cases} | {us['completion_tokens']//n_cases} | "
            f"{us['total_tokens']//n_cases} | {us['elapsed_ms']//n_cases} ms |"
        )
        md.append(
            f"| `{m}` | with    | {uc['prompt_tokens']//n_cases} | {uc['completion_tokens']//n_cases} | "
            f"{uc['total_tokens']//n_cases} | {uc['elapsed_ms']//n_cases} ms |"
        )

    # aggregate totals
    agg_sem_p = sum(by_model[m]["usage_sem"]["prompt_tokens"] for m in MODELS)
    agg_sem_c = sum(by_model[m]["usage_sem"]["completion_tokens"] for m in MODELS)
    agg_sem_t = sum(by_model[m]["usage_sem"]["total_tokens"] for m in MODELS)
    agg_sem_ms = sum(by_model[m]["usage_sem"]["elapsed_ms"] for m in MODELS)
    agg_com_p = sum(by_model[m]["usage_com"]["prompt_tokens"] for m in MODELS)
    agg_com_c = sum(by_model[m]["usage_com"]["completion_tokens"] for m in MODELS)
    agg_com_t = sum(by_model[m]["usage_com"]["total_tokens"] for m in MODELS)
    agg_com_ms = sum(by_model[m]["usage_com"]["elapsed_ms"] for m in MODELS)
    md += [
        "",
        f"**Aggregate over the full bench** ({total_runs} runs per side):",
        "",
        f"- without simplicio: {agg_sem_t:,} tokens total · {agg_sem_ms/1000:.1f}s wall-clock · "
        f"{agg_sem_t // total_runs} tok/run · {agg_sem_ms // total_runs} ms/run",
        f"- with simplicio:    {agg_com_t:,} tokens total · {agg_com_ms/1000:.1f}s wall-clock · "
        f"{agg_com_t // total_runs} tok/run · {agg_com_ms // total_runs} ms/run",
        f"- token delta:       {agg_com_t - agg_sem_t:+,} ({(agg_com_t - agg_sem_t)*100//max(agg_sem_t,1):+d}%)",
        f"- time delta:        {(agg_com_ms - agg_sem_ms)/1000:+.1f}s ({(agg_com_ms - agg_sem_ms)*100//max(agg_sem_ms,1):+d}%)",
        "",
        "## How to reproduce",
        "",
        "```bash",
        f'BENCH_BASE_URL="{BASE_URL}" \\',
        "  BENCH_API_KEY=… \\",
        f'  BENCH_MODELS="{",".join(MODELS)}" \\',
        "  python3 bench/run_offline.py",
        "```",
        "",
        "Models prefixed `local:` run on CPU via `transformers` (downloaded from the ",
        "Hugging Face Hub); all others go through the OpenAI-compatible endpoint at ",
        "`BENCH_BASE_URL`. Cap local generation length with `BENCH_LOCAL_MAX_TOKENS`.",
        "",
        "Raw model outputs are saved under `.simplicio/bench_runs/<model>/case_NN/{sem,com}.txt` ",
        "so you can audit what the LLM actually produced on each side. Charts are ",
        "SVG under `bench/charts/`; raw aggregated data under `bench/results.json`.",
        "",
    ]
    RESULTS_MD.write_text("\n".join(md))
    print(f"\n-> {RESULTS_MD}")
    build_pdf(by_model, cases)
    print(f"grand: without {grand_sem_pct}% · with {grand_com_pct}% · delta {grand_com_pct - grand_sem_pct:+d} pts "
          f"(over {grand_total} checks, {n_cases} cases × {len(MODELS)} models)")
    return 0


def pdf_only() -> int:
    """Rebuild only the PDF from an existing results.json (no model calls)."""
    by_model = json.loads(RESULTS_JSON.read_text())
    cases = json.loads(CASES_PATH.read_text())
    build_pdf(by_model, cases)
    return 0


def report_only() -> int:
    """Rebuild all reports (charts + md + pdf) from results.json, no model calls."""
    global MODELS
    by_model = json.loads(RESULTS_JSON.read_text())
    cases = json.loads(CASES_PATH.read_text())
    MODELS = list(by_model.keys())
    return build_reports(by_model, cases)


if __name__ == "__main__":
    if "--report-only" in sys.argv:
        sys.exit(report_only())
    elif "--pdf-only" in sys.argv:
        sys.exit(pdf_only())
    else:
        sys.exit(run())
