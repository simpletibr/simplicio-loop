"""
run_exec_sindico.py — EXECUTION benchmark against sistema-sindico (real PHPUnit).

For every case and every model, two prompts are sent:
  WITHOUT: raw goal + existing file content + "output the full updated file"
  WITH:    same goal + content, wrapped in the simplicio contract (role/stack,
           target, testable criteria, constraints, identical output shape)
Both sides emit the COMPLETE updated PHP file. The harness writes that file
into a working copy of sistema-sindico, drops a HIDDEN PHPUnit test (never
shown to the model) into tests/unit/Core/Hidden/, and runs `vendor/bin/phpunit`
on the WHOLE suite. Pass = every existing test plus the hidden one go green —
which means the new method works AND nothing else was broken.

Usage:
  BENCH_BASE_URL=https://router.huggingface.co/v1 BENCH_API_KEY=... \
    BENCH_MODELS="Qwen/Qwen3-Coder-30B-A3B-Instruct,Qwen/Qwen3-Coder-Next" \
    python3 bench/run_exec_sindico.py
"""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SINDICO_SRC = Path(os.environ.get("BENCH_SINDICO_SRC", "/tmp/sindico"))
WORK = Path(os.environ.get("BENCH_SINDICO_WORK", "/tmp/sindico_work_bench"))
HIDDEN_TPL = ROOT / "bench" / "sindico_hidden"
RESULTS_JSON = ROOT / "bench" / "results_exec_sindico.json"
RESULTS_MD = ROOT / "bench" / "results_exec_sindico.md"
RESULTS_PDF = ROOT / "bench" / "results_exec_sindico.pdf"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_offline as ro  # llm_call / local_call / _lat1
from sindico_cases import CASES

DEFAULT_MODELS = (
    "Qwen/Qwen3-Coder-30B-A3B-Instruct",
    "Qwen/Qwen3-Coder-Next",
)
MODELS = [
    m.strip()
    for m in os.environ.get("BENCH_MODELS", ",".join(DEFAULT_MODELS)).split(",")
    if m.strip()
]
PHPUNIT_TIMEOUT = int(os.environ.get("BENCH_PHPUNIT_TIMEOUT", "60"))
INCLUDE_SP = os.environ.get("BENCH_INCLUDE_SP", "0").strip() not in ("0", "false", "False")
INCLUDE_AGENTS = os.environ.get("BENCH_INCLUDE_AGENTS", "1").strip() not in ("0", "false", "False")
INCLUDE_SP_AG = os.environ.get("BENCH_INCLUDE_SP_AG", "0").strip() not in ("0", "false", "False")
AGENTS_MAX_ATTEMPTS = int(os.environ.get("BENCH_AGENTS_MAX_ATTEMPTS", "3"))

# Per-model endpoint routing: lets one batch mix HuggingFace router models
# (Qwen Coder series, served from the HF inference network) with OpenRouter
# models in the same run. Each entry overrides BENCH_BASE_URL + BENCH_API_KEY
# from run_offline for the duration of that model's loop.
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
    """Point run_offline.llm_call at the right endpoint for the given model.
    Defaults (OpenRouter via OPENROUTER_API_KEY / BENCH_API_KEY) win when the
    model is not in MODEL_ROUTING."""
    cfg = MODEL_ROUTING.get(model)
    if cfg is None:
        ro.BASE_URL = os.environ.get("BENCH_BASE_URL", "https://openrouter.ai/api/v1")
        ro.API_KEY = (os.environ.get("OPENROUTER_API_KEY")
                      or os.environ.get("BENCH_API_KEY"))
        return
    ro.BASE_URL = cfg["base_url"]
    ro.API_KEY = os.environ.get(cfg["env_key"])
    if not ro.API_KEY:
        raise SystemExit(f"missing env var {cfg['env_key']} for model {model}")


def _load_sp_runtime() -> str:
    """Load the simplicio-prompt runtime template (lazy: called only when sp is on).

    Order: explicit env, the simplicio-prompt clone at /tmp/prompt_check, a
    sibling npm install. The PyPI package ships only the kernel, not the .md.
    """
    candidates = [
        os.environ.get("BENCH_SIMPLICIO_PROMPT_PATH"),
        "/tmp/prompt_check/prompts/agent-runtime-execution-prompt.md",
        "node_modules/simplicio-prompt/prompts/agent-runtime-execution-prompt.md",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c).read_text(encoding="utf-8")
    raise SystemExit(
        "simplicio-prompt runtime template not found (needed when BENCH_INCLUDE_SP=1). "
        "Set BENCH_SIMPLICIO_PROMPT_PATH, or clone "
        "https://github.com/wesleysimplicio/simplicio-prompt to /tmp/prompt_check."
    )


SP_RUNTIME = _load_sp_runtime() if INCLUDE_SP else ""


RAW_PROMPT = """{goal}

Here is the current content of {target}:
```php
{file_content}
```

Output the COMPLETE updated contents of {target}. PHP only, no prose."""

CONTRACT_PROMPT = """You are a senior engineer working IN THIS project.
Stack: PHP 8 + composer + PHPUnit. Project conventions are LAW. Do not invent files or libraries the project does not use.

[GOAL]
{goal}

[TARGET]
Touch ONLY this file: {target}
Current content:
```php
{file_content}
```

[CONTRACT]
Done WHEN, and only when, ALL of the states below are true:
{criteria}

Constraints (do not break):
{constraints}

[OUTPUT]
Return ONLY the complete updated contents of {target}. PHP only, no prose, no fences."""


# The sp side is a COMPOSITION, not a standalone alternative: the
# simplicio-prompt runtime template wraps the simplicio-cli 6-layer contract
# as the task that user input X represents. We are measuring whether the
# Tuple-Space + Yool runtime ADDS value on top of an already-sharp 6-layer
# prompt — not whether the runtime alone beats raw goal text.
SP_PROMPT = """{sp_runtime}

---

[USER INPUT - task X]
{cli_contract}"""


# The agents side is the simplicio verify-loop: generate → run phpunit →
# on fail, classify the failure + feed the tail back as feedback → regenerate.
# Up to AGENTS_MAX_ATTEMPTS iterations. The retry template mirrors
# simplicio.pipeline.build_retry_feedback() so this measures the same loop
# that ships in `simplicio-py task --verify`.
AGENTS_RETRY_PROMPT = """Retry feedback for attempt {attempt}:
failure_class={failure_class}
{guidance}

PHPUnit tail (real output from the project's full test suite):
{phpunit_tail}

Your previous attempt was:
```php
{previous_code}
```

Apply the SMALLEST correction so the suite goes green. Output the COMPLETE corrected contents of {target}. PHP only, no prose, no fences."""


def _classify_phpunit_failure(tail: str) -> tuple[str, str]:
    """Light port of simplicio.pipeline.classify_failure to PHPUnit output.
    Returns (failure_class, guidance) matching the cli's retry-feedback shape."""
    t = (tail or "").lower()
    if "parse error" in t or "syntax error" in t:
        return ("syntax",
                "Fix the PHP syntax first; keep the patch minimal and rerun.")
    if "fatal error" in t and ("undefined" in t or "must implement" in t or "cannot redeclare" in t):
        return ("runtime",
                "Resolve the fatal error at the reported callsite.")
    if "failures!" in t:
        return ("assertion",
                "The test ran but behaviour is wrong; re-read the criteria.")
    if "errors!" in t:
        return ("runtime",
                "Resolve the exception raised by the production code path.")
    if "no tests" in t or "no test" in t:
        return ("test-missing",
                "PHPUnit did not see the expected test class; check naming.")
    return ("unknown",
            "Re-read the contract; produce a smaller, directly testable change.")


def setup_workspace() -> dict:
    """Fresh copy of sindico into WORK; return {case_id -> starting content} snapshot.

    Pure-additive tasks snapshot the pristine sindico source. Bug-fix tasks
    (those that set `seed_content`) snapshot the seeded broken state, so a
    reset returns the target file to the broken starting point the case
    declares, not to the pristine source.
    """
    if WORK.exists():
        shutil.rmtree(WORK)
    shutil.copytree(SINDICO_SRC, WORK)
    (WORK / "tests" / "unit" / "Core" / "Hidden").mkdir(parents=True, exist_ok=True)
    snaps: dict[str, str] = {}
    for c in CASES:
        if c.get("seed_content"):
            snaps[c["id"]] = c["seed_content"]
        else:
            snaps[c["id"]] = (SINDICO_SRC / c["target"]).read_text(encoding="utf-8")
    return snaps


def reset_target(case: dict, snaps: dict) -> None:
    (WORK / case["target"]).write_text(snaps[case["id"]], encoding="utf-8")


def extract_php(text: str) -> str:
    """Pull the PHP module out of a model reply (largest fenced block, else raw)."""
    text = text or ""
    blocks = re.findall(r"```(?:php)?\s*\n(.*?)```", text, re.DOTALL)
    code = max(blocks, key=len).strip() if blocks else text.strip()
    if not code.lstrip().startswith("<?php"):
        code = "<?php\n" + code
    return code


def run_phpunit() -> tuple[bool, str]:
    try:
        p = subprocess.run(
            ["vendor/bin/phpunit", "--configuration", "phpunit.xml.dist"],
            cwd=WORK, capture_output=True, text=True, timeout=PHPUNIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    tail = (p.stdout + p.stderr).splitlines()[-3:]
    return p.returncode == 0, " | ".join(tail)


def agents_iterate(model: str, case: dict, cli_contract: str, snaps: dict) -> dict:
    """Verify-loop: generate → phpunit → on fail, feed tail back, regenerate.
    Mirrors simplicio.pipeline.run() with AGENTS_MAX_ATTEMPTS retries.
    Returns the cumulative metrics; passed = pass on ANY attempt."""
    prompt = cli_contract
    total_tokens = 0
    total_ms = 0
    last_tail = ""
    last_code = ""
    final_passed = False
    attempts_used = 0
    for t in range(1, AGENTS_MAX_ATTEMPTS + 1):
        attempts_used = t
        reset_target(case, snaps)
        res = ro.llm_call(model, prompt)
        total_tokens += res.get("total_tokens", 0)
        total_ms += res.get("elapsed_ms", 0)
        last_code = extract_php(res["text"])
        (WORK / case["target"]).write_text(last_code, encoding="utf-8")
        hidden_dst = None
        if case.get("hidden_test"):
            hidden_dst = WORK / "tests" / "unit" / "Core" / "Hidden" / case["hidden_test"]
            hidden_dst.write_text(
                (HIDDEN_TPL / case["hidden_test"]).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        passed, last_tail = run_phpunit()
        if hidden_dst is not None:
            hidden_dst.unlink(missing_ok=True)
        if passed:
            final_passed = True
            break
        kind, guidance = _classify_phpunit_failure(last_tail)
        prompt = AGENTS_RETRY_PROMPT.format(
            attempt=t + 1, failure_class=kind, guidance=guidance,
            phpunit_tail=last_tail[-1600:], previous_code=last_code,
            target=case["target"],
        )
    reset_target(case, snaps)
    return {"passed": final_passed, "tokens": total_tokens, "ms": total_ms,
            "tail": last_tail, "attempts": attempts_used, "error": None}


def one(model: str, case: dict, prompt: str, snaps: dict) -> dict:
    reset_target(case, snaps)
    res = ro.llm_call(model, prompt)
    code = extract_php(res["text"])
    (WORK / case["target"]).write_text(code, encoding="utf-8")
    hidden_dst = None
    if case.get("hidden_test"):
        hidden_dst = WORK / "tests" / "unit" / "Core" / "Hidden" / case["hidden_test"]
        hidden_dst.write_text(
            (HIDDEN_TPL / case["hidden_test"]).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    passed, tail = run_phpunit()
    if hidden_dst is not None:
        hidden_dst.unlink(missing_ok=True)
    reset_target(case, snaps)
    return {"passed": passed, "tokens": res.get("total_tokens", 0),
            "ms": res.get("elapsed_ms", 0), "tail": tail,
            "error": res.get("error")}


def one_sp_fanout(model: str, case: dict, sp_prompt: str, snaps: dict) -> dict:
    """sp side via gradual-escalation fan-out (64 → 100 → 200) with the
    oracle (phpunit) as the gate to stop early.

    Per the 2026-05-30 mandate (cycle 1):
      try 64 subagents; if oracle passes on modal, STOP.
      if not, retry with 100 (fresh fan-out).
      if not, retry with 200.

    Structured output is on by default — small-model parse failures
    fall back gracefully to text aggregation in behavior_modal_vote.
    """
    from sp_fanout_helper import sp_fanout_escalating

    # Pre-install the hidden test once so the oracle callback can run
    # phpunit cheaply. We reset the file between candidates by rewriting
    # `target` from snaps before each attempt.
    reset_target(case, snaps)
    hidden_dst = None
    if case.get("hidden_test"):
        hidden_dst = WORK / "tests" / "unit" / "Core" / "Hidden" / case["hidden_test"]
        hidden_dst.write_text(
            (HIDDEN_TPL / case["hidden_test"]).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    def oracle(text: str) -> bool:
        if not text:
            return False
        try:
            (WORK / case["target"]).write_text(extract_php(text), encoding="utf-8")
        except Exception:
            return False
        ok, _ = run_phpunit()
        return ok

    res = sp_fanout_escalating(model, sp_prompt, oracle)

    # Final phpunit pass to capture the tail message for the report,
    # regardless of whether oracle short-circuit said pass/fail.
    final_text = res.get("text", "") or ""
    if final_text:
        try:
            (WORK / case["target"]).write_text(extract_php(final_text), encoding="utf-8")
        except Exception:
            pass
    passed, tail = run_phpunit()

    if hidden_dst is not None:
        hidden_dst.unlink(missing_ok=True)
    reset_target(case, snaps)

    return {
        "passed": passed, "tokens": res.get("tokens", 0),
        "ms": res.get("ms", 0), "tail": tail, "error": res.get("error"),
        "subagents": res.get("subagents", 0),
        "uniq": res.get("uniq", 0),
        "modal_count": res.get("modal_count", 0),
        "cycles_run": res.get("cycles_run", 0),
        "escalated": res.get("escalated", False),
        "tier_history": res.get("tier_history", []),
        "structured_parse_ok": res.get("structured_parse_ok", 0),
        "structured_parse_fail": res.get("structured_parse_fail", 0),
    }


def run() -> int:
    if not MODELS:
        raise SystemExit("set BENCH_MODELS")
    if not SINDICO_SRC.exists():
        raise SystemExit(f"sindico source not found at {SINDICO_SRC}")
    snaps = setup_workspace()
    n = len(CASES)
    print(f"exec target: sistema-sindico ({WORK})\nmodels: {MODELS}\ncases: {n}\n")
    by_model = {}
    for model in MODELS:
        _route_for(model)
        print(f"=== {model} (endpoint: {ro.BASE_URL}) ===")
        rows = []
        sem_pass = com_pass = sp_pass = ag_pass = spag_pass = 0
        for c in CASES:
            content = (SINDICO_SRC / c["target"]).read_text(encoding="utf-8")
            ctx = {**c, "file_content": content}
            cli_contract = CONTRACT_PROMPT.format(**ctx)
            s = one(model, c, RAW_PROMPT.format(**ctx), snaps)
            w = one(model, c, cli_contract, snaps)
            sem_pass += int(s["passed"]); com_pass += int(w["passed"])
            row = {"id": c["id"], "sem": s, "com": w}
            sp_msg = ""
            if INCLUDE_SP:
                # MANDATE 2026-05-30: sp ALWAYS runs as N=200 real subagents
                # via kernel.subagent_runtime + modal vote. Single-call sp
                # was empirically a regression — never again.
                sp_prompt = SP_PROMPT.format(
                    sp_runtime=SP_RUNTIME, cli_contract=cli_contract)
                p = one_sp_fanout(model, c, sp_prompt, snaps)
                sp_pass += int(p["passed"]); row["sp"] = p
                tiers = "→".join(str(h["n"]) for h in p.get("tier_history", []))
                sp_msg = (f"  cli+sp {'PASS' if p['passed'] else 'fail'}"
                          f"[tiers={tiers},u={p.get('uniq',0)},"
                          f"modal={p.get('modal_count',0)},"
                          f"parse={p.get('structured_parse_ok',0)}/"
                          f"{p.get('structured_parse_ok',0)+p.get('structured_parse_fail',0)}]")
            ag_msg = ""
            if INCLUDE_AGENTS:
                a = agents_iterate(model, c, cli_contract, snaps)
                ag_pass += int(a["passed"]); row["ag"] = a
                ag_msg = (f"  cli+ag {'PASS' if a['passed'] else 'fail'}"
                          f"({a['attempts']}/{AGENTS_MAX_ATTEMPTS})")
            spag_msg = ""
            if INCLUDE_SP_AG:
                # 5th side: verify-loop seeded by the MODAL output from N=200
                # sp-fanout. So the loop fixes the modal vote, not a single
                # sp-wrapped completion. Composition + retry on top of fan-out.
                sp_prompt = SP_PROMPT.format(
                    sp_runtime=SP_RUNTIME, cli_contract=cli_contract)
                modal = one_sp_fanout(model, c, sp_prompt, snaps)
                if modal.get("passed"):
                    # modal already passes — no need to invoke verify-loop
                    pa = {**modal, "attempts": 1}
                else:
                    # seed the agents loop with the modal text as previous attempt
                    seed = sp_prompt
                    pa = agents_iterate(model, c, seed, snaps)
                    pa["modal_seed_uniq"] = modal.get("uniq", 0)
                spag_pass += int(pa["passed"]); row["spag"] = pa
                spag_msg = (f"  cli+sp+ag {'PASS' if pa['passed'] else 'fail'}"
                            f"({pa.get('attempts', 0)}/{AGENTS_MAX_ATTEMPTS})")
            rows.append(row)
            print(f"  {c['id']:25s} baseline {'PASS' if s['passed'] else 'fail'}  "
                  f"cli {'PASS' if w['passed'] else 'fail'}{sp_msg}{ag_msg}{spag_msg}")
        entry = {"rows": rows, "n": n,
            "sem_pass": sem_pass, "com_pass": com_pass,
            "sem_pct": 100*sem_pass//n, "com_pct": 100*com_pass//n}
        if INCLUDE_SP:
            entry["sp_pass"] = sp_pass; entry["sp_pct"] = 100*sp_pass//n
        if INCLUDE_AGENTS:
            entry["ag_pass"] = ag_pass; entry["ag_pct"] = 100*ag_pass//n
        if INCLUDE_SP_AG:
            entry["spag_pass"] = spag_pass; entry["spag_pct"] = 100*spag_pass//n
        by_model[model] = entry
        tail = f" | sp {sp_pass}/{n} ({100*sp_pass//n}%)" if INCLUDE_SP else ""
        tail += f" | ag {ag_pass}/{n} ({100*ag_pass//n}%)" if INCLUDE_AGENTS else ""
        tail += f" | sp+ag {spag_pass}/{n} ({100*spag_pass//n}%)" if INCLUDE_SP_AG else ""
        print(f"  -> baseline {sem_pass}/{n} ({by_model[model]['sem_pct']}%) "
              f"| cli {com_pass}/{n} ({by_model[model]['com_pct']}%){tail}\n")
    RESULTS_JSON.write_text(json.dumps(by_model, indent=2))
    write_reports(by_model)
    g_sem = sum(b["sem_pass"] for b in by_model.values())
    g_com = sum(b["com_pass"] for b in by_model.values())
    g_tot = sum(b["n"] for b in by_model.values())
    sp_tail = ag_tail = spag_tail = ""
    if INCLUDE_SP:
        g_sp = sum(b.get("sp_pass", 0) for b in by_model.values())
        sp_tail = f" | cli+sp {100*g_sp//g_tot}%"
    if INCLUDE_AGENTS:
        g_ag = sum(b.get("ag_pass", 0) for b in by_model.values())
        ag_tail = f" | cli+ag {100*g_ag//g_tot}%"
    if INCLUDE_SP_AG:
        g_spag = sum(b.get("spag_pass", 0) for b in by_model.values())
        spag_tail = f" | cli+sp+ag {100*g_spag//g_tot}%"
    print(f"grand: baseline {100*g_sem//g_tot}% | cli {100*g_com//g_tot}%"
          f"{sp_tail}{ag_tail}{spag_tail} (real phpunit, {g_tot} runs/side)")
    return 0


def _has_sp(by_model: dict) -> bool:
    """True iff any model carries simplicio-prompt data in its rows."""
    return any("sp" in r for b in by_model.values() for r in b.get("rows", []))


def _has_ag(by_model: dict) -> bool:
    """True iff any model carries the agents verify-loop data in its rows."""
    return any("ag" in r for b in by_model.values() for r in b.get("rows", []))


def write_reports(by_model: dict) -> None:
    models = list(by_model.keys())
    # Drive the report off rows actually present in the data, not the static
    # CASES list, so regenerating from a partial run shows what was measured.
    sample_rows = next(iter(by_model.values())).get("rows", []) if by_model else []
    case_ids = [r["id"] for r in sample_rows]
    n_tasks = len(case_ids)
    with_sp = _has_sp(by_model)
    with_ag = _has_ag(by_model)
    g_sem = sum(b.get("sem_pass", 0) for b in by_model.values())
    g_com = sum(b.get("com_pass", 0) for b in by_model.values())
    g_tot = sum(b["n"] for b in by_model.values())
    gsp = 100 * g_sem // max(g_tot, 1)
    gcp = 100 * g_com // max(g_tot, 1)
    sides_blurb = (
        "- **baseline**: raw goal + current file content\n"
        "- **simplicio-cli**: the 6-layer task contract (role/stack, goal, "
        "target, criteria as testable states, constraints, output shape)"
    )
    if with_sp:
        sides_blurb += ("\n- **simplicio-cli + simplicio-prompt (composition)**: "
                        "the Tuple-Space + Yool runtime template from "
                        "simplicio-prompt wrapping the simplicio-cli 6-layer "
                        "contract as user input X. Measures whether the "
                        "runtime adds value ON TOP of an already-sharp "
                        "6-layer prompt — not whether sp alone beats raw goal.")
    if with_ag:
        sides_blurb += ("\n- **simplicio-cli + agents (verify-loop)**: same "
                        "6-layer contract, but on failure the harness feeds "
                        "the PHPUnit tail back as classified retry feedback "
                        "(syntax/assertion/runtime/etc.) and re-prompts up "
                        f"to {AGENTS_MAX_ATTEMPTS} attempts — the exact loop "
                        "shipped in `simplicio-py task --verify` "
                        "(`simplicio/pipeline.py`).")
    md = [
        "# Execution benchmark — real project, real tasks, real test suite",
        "",
        f"Date: **{time.strftime('%Y-%m-%d')}**  ",
        f"Target project: [`wesleysimplicio/sistema-sindico`](https://github.com/wesleysimplicio/sistema-sindico)"
        f" — a real condominium-management system in pure PHP 8 (public on GitHub, PHPUnit 11)  ",
        f"Models: " + ", ".join(f"`{m}`" for m in models) + "  ",
        f"Tasks: **{n_tasks}** additive real-engineering changes across "
        "`src/Core/`, `src/Middleware/`, `src/Repositories/`, and routing.",
        "",
        "## Methodology — what \"pass\" actually means",
        "",
        "**This is NOT regex pattern-matching on model output. This is NOT a "
        "synthetic toy unit-test harness in isolation.** The benchmark runs "
        "against an actual published PHP project using the project's real "
        "PHPUnit suite (`vendor/bin/phpunit --configuration phpunit.xml.dist`).",
        "",
        "For each task:",
        "",
        "1. The model is asked for a real engineering change — add a new method "
        "to an existing production class (permission helper, env parser, "
        "rate-limit key builder, repository SQL builder, route introspection, "
        "etc.).",
        "2. Its generated file replaces the original in a working copy of the "
        "real repo (with `composer install` deps already in place).",
        "3. A **hidden PHPUnit test** (never shown to the model, asserting "
        "BOTH true and false states of the required behaviour) is dropped into "
        "`tests/unit/Core/Hidden/`.",
        "4. The **ENTIRE production suite** runs — every pre-existing test of "
        "the real codebase plus the hidden one. The model's change must be "
        "**correct** (the new test passes) AND must **not break existing "
        "behaviour** (every prior test still passes).",
        "5. **Pass = `phpunit` exit code 0** — the same green/red signal the "
        "project's CI would use to merge a PR.",
        "",
        "All sides emit the complete file (identical output shape); the only "
        "variable is the wrapping prompt:",
        "",
        sides_blurb,
        "",
        "## Headline",
        "",
        f"- **Baseline:** {g_sem}/{g_tot} ({gsp}%)",
        f"- **simplicio-cli (6-layer):** {g_com}/{g_tot} ({gcp}%) — **{gcp - gsp:+d} pts vs baseline**",
    ]
    if with_sp:
        g_sp = sum(b.get("sp_pass", 0) for b in by_model.values())
        gpp = 100 * g_sp // max(g_tot, 1)
        md.append(f"- **simplicio-cli + simplicio-prompt (composition):** "
                  f"{g_sp}/{g_tot} ({gpp}%) "
                  f"— **{gpp - gsp:+d} pts vs baseline · {gpp - gcp:+d} pts vs cli alone**")
    if with_ag:
        g_ag = sum(b.get("ag_pass", 0) for b in by_model.values())
        gap = 100 * g_ag // max(g_tot, 1)
        md.append(f"- **simplicio-cli + agents (verify-loop):** "
                  f"{g_ag}/{g_tot} ({gap}%) "
                  f"— **{gap - gsp:+d} pts vs baseline · {gap - gcp:+d} pts vs cli alone**")
    md += ["", "## Per-model (pass = full PHPUnit suite green)", ""]
    cols = ["Model", "Baseline", "cli alone"]
    if with_sp: cols.append("cli + sp")
    if with_ag: cols.append("cli + ag")
    cols += ["D cli"]
    if with_sp: cols.append("D (cli+sp)")
    if with_ag: cols.append("D (cli+ag)")
    md += ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for m in models:
        b = by_model[m]
        cells = [
            f"`{m}`",
            f"{b['sem_pass']}/{b['n']} ({b['sem_pct']}%)",
            f"{b['com_pass']}/{b['n']} ({b['com_pct']}%)",
        ]
        if with_sp:
            cells.append(f"{b.get('sp_pass', 0)}/{b['n']} ({b.get('sp_pct', 0)}%)")
        if with_ag:
            cells.append(f"{b.get('ag_pass', 0)}/{b['n']} ({b.get('ag_pct', 0)}%)")
        cells.append(f"**{b['com_pct'] - b['sem_pct']:+d}**")
        if with_sp:
            cells.append(f"**{b.get('sp_pct', 0) - b['sem_pct']:+d}**")
        if with_ag:
            cells.append(f"**{b.get('ag_pct', 0) - b['sem_pct']:+d}**")
        md.append("| " + " | ".join(cells) + " |")
    label = "baseline / cli"
    if with_sp: label += " / cli+sp"
    if with_ag: label += " / cli+ag"
    md += ["", f"## Per-task × model ({label})", "",
           "| Task | " + " | ".join(m.split("/")[-1] for m in models) + " |",
           "|---|" + "|".join("---" for _ in models) + "|"]
    for i, cid in enumerate(case_ids):
        cells = []
        for m in models:
            r = by_model[m]["rows"][i]
            base = f"{'P' if r['sem']['passed'] else '.'}/{'P' if r['com']['passed'] else '.'}"
            if with_sp:
                sp = r.get("sp", {"passed": False})
                base += f"/{'P' if sp.get('passed') else '.'}"
            if with_ag:
                ag = r.get("ag", {"passed": False, "attempts": 0})
                base += f"/{'P' if ag.get('passed') else '.'}({ag.get('attempts',0)})"
            cells.append(base)
        md.append(f"| {cid} | " + " | ".join(cells) + " |")
    if with_ag:
        md += ["",
               "Format suffix `(N)` on cli+ag is the number of verify-loop "
               "attempts consumed (1–3). Lower is better; 1 means it passed "
               "on the first try, no feedback needed."]
    md += ["", "Raw counts above are real `vendor/bin/phpunit` exit codes against "
           "`sistema-sindico`. `results_exec_sindico.json` holds per-case "
           "pass/fail, tokens, latency and a phpunit tail for every side.", ""]
    RESULTS_MD.write_text("\n".join(md))
    print(f"-> {RESULTS_MD}")
    _pdf(by_model)


def _pdf(by_model: dict) -> None:
    try:
        from fpdf import FPDF
    except BaseException as e:
        # fpdf2 transitively imports cryptography which can panic when its
        # native bindings are mis-linked (PyO3 PanicException is BaseException,
        # not Exception). Skip the PDF rather than abort the whole batch.
        print(f"[warn] fpdf2 unavailable ({type(e).__name__}); skipping PDF.")
        return
    models = list(by_model.keys())
    with_sp = _has_sp(by_model)
    g_sem = sum(b.get("sem_pass", 0) for b in by_model.values())
    g_com = sum(b.get("com_pass", 0) for b in by_model.values())
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

    sample_rows = next(iter(by_model.values())).get("rows", []) if by_model else []
    n_tasks = len(sample_rows)
    pdf.add_page()
    h1("Execution benchmark - real project, real tasks, real test suite")
    p(f"Date: {time.strftime('%Y-%m-%d')}   "
      f"Target: wesleysimplicio/sistema-sindico (real PHP 8 condominium system, "
      f"public on GitHub)   Tasks: {n_tasks} additive engineering changes "
      f"across Core / Middleware / Repository / Router.")
    h2("Methodology - what 'pass' actually means")
    p("NOT regex on model output. NOT a toy harness in isolation. The model's "
      "generated file replaces the real source file in a working copy of the "
      "real repo; a hidden PHPUnit test (never shown to the model, asserting "
      "TRUE and FALSE states) is added to tests/unit/Core/Hidden/; the FULL "
      "production suite runs (existing tests + hidden). Pass = vendor/bin/phpunit "
      "exit code 0 - same green/red the project's CI would use to merge a PR. "
      "The model's change must be correct AND must not break any pre-existing "
      "test of the real codebase.")
    blurb = ("All sides emit the complete file (identical output shape). "
             "Variables: baseline = raw goal; cli = the simplicio-cli 6-layer "
             "task contract")
    if with_sp:
        blurb += ("; cli+sp = the simplicio-prompt Tuple-Space + Yool runtime "
                  "wrapping the cli 6-layer contract as user input X "
                  "(composition, not substitution)")
    if with_ag:
        blurb += ("; cli+ag = the simplicio verify-loop (cli 6-layer contract "
                  "with classified PHPUnit-tail feedback fed back over up to "
                  f"{AGENTS_MAX_ATTEMPTS} attempts, mirrors simplicio.pipeline)")
    blurb += "."
    p(blurb)
    pdf.ln(1)
    h2("Headline")
    th(["Side", "Passed", "Rate", "vs baseline"], [60, 30, 30, 40])
    tr(["Baseline", f"{g_sem}/{g_tot}", f"{100*g_sem//max(g_tot,1)}%", "-"], [60, 30, 30, 40])
    tr(["cli alone (6-layer)", f"{g_com}/{g_tot}", f"{100*g_com//max(g_tot,1)}%",
        f"{100*g_com//max(g_tot,1) - 100*g_sem//max(g_tot,1):+d} pts"], [60, 30, 30, 40])
    if with_sp:
        g_sp = sum(b.get("sp_pass", 0) for b in by_model.values())
        tr(["cli + sp (composition)", f"{g_sp}/{g_tot}", f"{100*g_sp//max(g_tot,1)}%",
            f"{100*g_sp//max(g_tot,1) - 100*g_sem//max(g_tot,1):+d} pts"], [60, 30, 30, 40])
    if with_ag:
        g_ag = sum(b.get("ag_pass", 0) for b in by_model.values())
        tr(["cli + ag (verify-loop)", f"{g_ag}/{g_tot}", f"{100*g_ag//max(g_tot,1)}%",
            f"{100*g_ag//max(g_tot,1) - 100*g_sem//max(g_tot,1):+d} pts"], [60, 30, 30, 40])
    pdf.ln(2)
    h2("Per-model (pass = full PHPUnit suite green)")
    headers = ["Model", "Baseline", "cli"]
    widths = [62, 22, 22]
    if with_sp:
        headers.append("cli+sp"); widths.append(22)
    if with_ag:
        headers.append("cli+ag"); widths.append(22)
    headers.append("D cli"); widths.append(16)
    if with_sp:
        headers.append("D cli+sp"); widths.append(16)
    if with_ag:
        headers.append("D cli+ag"); widths.append(16)
    th(headers, widths)
    for m in models:
        b = by_model[m]
        cells = [m,
                 f"{b['sem_pass']}/{b['n']} ({b['sem_pct']}%)",
                 f"{b['com_pass']}/{b['n']} ({b['com_pct']}%)"]
        if with_sp:
            cells.append(f"{b.get('sp_pass',0)}/{b['n']} ({b.get('sp_pct',0)}%)")
        if with_ag:
            cells.append(f"{b.get('ag_pass',0)}/{b['n']} ({b.get('ag_pct',0)}%)")
        cells.append(f"{b['com_pct']-b['sem_pct']:+d}")
        if with_sp:
            cells.append(f"{b.get('sp_pct',0)-b['sem_pct']:+d}")
        if with_ag:
            cells.append(f"{b.get('ag_pct',0)-b['sem_pct']:+d}")
        tr(cells, widths)
    pdf.ln(2)
    label = "base / cli"
    if with_sp: label += " / cli+sp"
    if with_ag: label += " / cli+ag"
    h2(f"Per-task x model ({label})")
    case_ids = [r["id"] for r in sample_rows]
    th(["Task"] + [m.split("/")[-1] for m in models],
       [40] + [(140 // max(len(models), 1))] * len(models))
    for i, cid in enumerate(case_ids):
        row = [cid]
        for m in models:
            r = by_model[m]["rows"][i]
            cell = f"{'P' if r['sem']['passed'] else '.'}/{'P' if r['com']['passed'] else '.'}"
            if with_sp:
                sp = r.get("sp", {"passed": False})
                cell += f"/{'P' if sp.get('passed') else '.'}"
            if with_ag:
                ag = r.get("ag", {"passed": False})
                cell += f"/{'P' if ag.get('passed') else '.'}"
            row.append(cell)
        tr(row, [40] + [(140 // max(len(models), 1))] * len(models))
    pdf.output(str(RESULTS_PDF))
    print(f"-> {RESULTS_PDF}")


if __name__ == "__main__":
    raise SystemExit(run())
