"""sp_fanout_helper.py — execute the sp side via REAL N=200 subagents.

Before: bench harnesses prepended the sp .md template to the prompt and
sent ONE LLM call. The template was just text; the runtime fan-out kernel
was never touched. Empirical result: sp regressed or tied vs cli alone on
4 models.

After (mandate from user 2026-05-30): every sp invocation must run through
`kernel.subagent_runtime.SubagentRuntime` with N=200 parallel subagents
(diversify=True so prompts actually differ), then modal-vote pick the
winning output.

Public API:
  sp_fanout_complete(model_id, sp_wrapped_prompt) -> dict
    {"text": str, "tokens": int, "ms": int, "uniq": int,
     "modal_count": int, "subagents": int, "error": str|None}
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from collections import Counter
from typing import Optional


DEFAULT_SUBAGENTS = int(os.environ.get("BENCH_SP_SUBAGENTS", "200"))

# Gradual escalation tiers (override via BENCH_SP_TIERS="64,100,200")
ESCALATION_TIERS: tuple[int, ...] = tuple(
    int(x) for x in os.environ.get("BENCH_SP_TIERS", "64,100,200").split(",")
    if x.strip()
) or (64, 100, 200)


# ---- model → endpoint table (mirrors bench/run_fanout.py) ---- #

_ROUTING: dict[str, dict] = {
    # HuggingFace router models
    "Qwen/Qwen2.5-Coder-3B-Instruct":   {"preset": None, "base_url": "https://router.huggingface.co/v1", "env_key": "HF_TOKEN"},
    "Qwen/Qwen2.5-Coder-7B-Instruct":   {"preset": None, "base_url": "https://router.huggingface.co/v1", "env_key": "HF_TOKEN"},
    "Qwen/Qwen3-Coder-30B-A3B-Instruct": {"preset": None, "base_url": "https://router.huggingface.co/v1", "env_key": "HF_TOKEN"},
    "Qwen/Qwen3-Coder-Next":             {"preset": None, "base_url": "https://router.huggingface.co/v1", "env_key": "HF_TOKEN"},
}


def _normalize(text: str) -> str:
    """Hash-friendly normalization: strip trailing whitespace + collapse blanks."""
    if not text:
        return ""
    lines = [line.rstrip() for line in text.split("\n")]
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


def _modal_vote(texts: list[str]) -> tuple[Optional[str], int, int]:
    """Return (winning_text, count_of_modal, unique_outputs)."""
    if not texts:
        return None, 0, 0
    normalized = [_normalize(t) for t in texts]
    by_hash: dict[str, str] = {}
    for raw, norm in zip(texts, normalized):
        h = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]
        by_hash.setdefault(h, raw)
    hashes = [hashlib.sha256(n.encode("utf-8")).hexdigest()[:12] for n in normalized]
    counter = Counter(hashes)
    winning_hash, winning_count = counter.most_common(1)[0]
    return by_hash[winning_hash], winning_count, len(counter)


def _build_runtime(model_id: str):
    """Make a SubagentRuntime configured for model_id. Routes via the same
    table run_fanout.py uses; falls back to OpenRouter for unlisted models."""
    from kernel.providers import LLMProvider, resolve_provider_config
    from kernel.subagent_runtime import SubagentRuntime

    cfg = _ROUTING.get(model_id)
    if cfg is not None:
        api_key = os.environ.get(cfg["env_key"])
        if not api_key:
            raise SystemExit(
                f"sp_fanout_helper: missing {cfg['env_key']} for {model_id}")
        overrides = {
            "api_key": api_key, "model": model_id,
            "prompt_cost_per_mtok": 0.0, "completion_cost_per_mtok": 0.0,
        }
        if cfg.get("base_url"):
            overrides["base_url"] = cfg["base_url"]
        config = resolve_provider_config(cfg.get("preset"), **overrides)
    else:
        # default: OpenRouter
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise SystemExit(
                f"sp_fanout_helper: missing OPENROUTER_API_KEY for {model_id}")
        config = resolve_provider_config(
            "openrouter", api_key=api_key, model=model_id,
            prompt_cost_per_mtok=0.0, completion_cost_per_mtok=0.0,
        )

    return SubagentRuntime(
        LLMProvider(config),
        temperature=float(os.environ.get("BENCH_SP_TEMP", "0.7")),
        max_tokens=int(os.environ.get("BENCH_SP_MAX_TOKENS", "4096")),
    )


# ---- local transformers backend (model_id prefixed with "local:") ---- #
# For Qwen 2.5 Coder 1.5B / 3B running on CPU. SubagentRuntime can't reach
# these (no HTTP endpoint), so we run N sequential generations via the same
# `bench/run_offline.local_call()` machinery used by single-call benches.

def _is_local(model_id: str) -> bool:
    return model_id.startswith("local:")


def _local_fanout(model_id: str, sp_wrapped_prompt: str, n: int,
                  system: str) -> dict:
    """Run N sequential generations via transformers (CPU). Returns the same
    shape as a SubagentRuntime report (text per result + total token usage)."""
    import sys
    from pathlib import Path
    bench_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(bench_dir))
    import run_offline as ro

    local_model = model_id.split(":", 1)[1]
    full_prompt = (system + "\n\n" if system else "") + sp_wrapped_prompt
    t0 = time.perf_counter()
    texts: list[str] = []
    tokens_total = 0
    completed = 0
    failed = 0
    for _ in range(n):
        res = ro.local_call(local_model, full_prompt)
        if res.get("error"):
            failed += 1
            texts.append("")
        else:
            completed += 1
            texts.append(res.get("text", ""))
            tokens_total += res.get("total_tokens", 0)
    return {
        "texts": texts,
        "tokens_total": tokens_total,
        "completed": completed,
        "failed": failed,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


def sp_fanout_complete(model_id: str, sp_wrapped_prompt: str,
                        system: str = "You are a senior engineer.",
                        subagents: int = DEFAULT_SUBAGENTS) -> dict:
    """Fan out N=subagents parallel calls of the sp-wrapped prompt. Take
    modal vote. Returns the winning text + diagnostics."""
    t0 = time.perf_counter()
    try:
        runtime = _build_runtime(model_id)
    except SystemExit as e:
        return {"text": "", "tokens": 0, "ms": 0, "uniq": 0,
                "modal_count": 0, "subagents": 0, "error": str(e)}

    # Build N prompts. We use diversify=True via the kernel so each subagent
    # gets a different persona injected — same goal, varied framing → varied
    # outputs → meaningful modal vote.
    prompts = [{"system": system, "prompt": sp_wrapped_prompt}] * subagents
    try:
        report = runtime.run(
            task="sp-fanout",
            subagents=subagents,
            prompts=prompts,
            use_cache=False,
            diversify=True,
        )
    except TypeError:
        # Older kernel without diversify kwarg — fall back without it
        report = runtime.run(
            task="sp-fanout",
            subagents=subagents,
            prompts=prompts,
            use_cache=False,
        )
    except Exception as e:
        return {"text": "", "tokens": 0, "ms": int((time.perf_counter() - t0) * 1000),
                "uniq": 0, "modal_count": 0, "subagents": 0, "error": str(e)}

    texts = [r.text for r in report.results if getattr(r, "ok", False)]
    winning_text, modal_count, uniq = _modal_vote(texts)
    return {
        "text": winning_text or "",
        "tokens": getattr(report.usage, "total_tokens", 0) if hasattr(report, "usage") else 0,
        "ms": int((time.perf_counter() - t0) * 1000),
        "uniq": uniq,
        "modal_count": modal_count,
        "subagents": subagents,
        "completed": getattr(report, "completed", subagents),
        "failed": getattr(report, "failed", 0),
        "error": None,
    }


def sp_fanout_escalating(
    model_id: str, sp_wrapped_prompt: str,
    oracle, *,
    system: str = "You are a senior engineer.",
    tiers: Optional[tuple[int, ...]] = None,
    structured: bool = True,
) -> dict:
    """Gradual N-escalation: try cheap tier first, escalate only if oracle
    says no. Per user mandate 2026-05-30:

      cycle 1 → 64 subagents; if oracle PASSES on modal, stop.
      cycle 2 → 100 subagents (fresh run); if PASSES, stop.
      cycle 3 → 200 subagents.

    `oracle(text) -> bool` is the caller-provided correctness check.
    For exec bench: phpunit on the artifact. For regex: all patterns
    match. Returns the same shape as sp_fanout_complete plus:
      cycles_run, tier_history, escalated, structured_parse_stats

    structured=True: prompts the LLM with [STRUCTURED_OUTPUT=v1] marker
    and uses behavior-modal-vote instead of raw-string modal. Falls back
    to text aggregation when parsing fails (small models).
    """
    from sp_output_schema import (
        STRUCTURED_OUTPUT_INSTRUCTION,
        StructuredResponse,
        behavior_modal_vote,
    )

    tier_list = tiers if tiers is not None else ESCALATION_TIERS
    if not tier_list:
        tier_list = (200,)

    final_prompt = sp_wrapped_prompt
    if structured:
        final_prompt = (
            sp_wrapped_prompt + "\n\n" + STRUCTURED_OUTPUT_INSTRUCTION.strip()
        )

    t0 = time.perf_counter()
    history = []
    total_tokens = 0
    last_text = ""
    last_uniq = 0
    last_modal = 0
    last_subagents = 0
    last_diagnostics: dict = {}
    last_parse_ok = 0
    last_parse_fail = 0
    last_passed = False

    local_mode = _is_local(model_id)
    runtime = None
    if not local_mode:
        try:
            runtime = _build_runtime(model_id)
        except SystemExit as e:
            return {
                "text": "", "tokens": 0,
                "ms": int((time.perf_counter() - t0) * 1000),
                "uniq": 0, "modal_count": 0, "subagents": 0,
                "passed": False, "cycles_run": 0,
                "tier_history": [], "escalated": False,
                "error": str(e),
            }

    for cycle, n in enumerate(tier_list, start=1):
        cycle_start = time.perf_counter()

        if local_mode:
            try:
                local_res = _local_fanout(model_id, final_prompt, n, system)
            except Exception as e:
                history.append({
                    "cycle": cycle, "n": n, "error": str(e),
                    "elapsed_ms": int((time.perf_counter() - cycle_start) * 1000),
                })
                break
            texts = local_res["texts"]
            cycle_tokens = local_res["tokens_total"]
            total_tokens += cycle_tokens
        else:
            prompts = [{"system": system, "prompt": final_prompt}] * n
            try:
                try:
                    report = runtime.run(
                        task=f"sp-escalate-cycle{cycle}",
                        subagents=n, prompts=prompts,
                        use_cache=False, diversify=True,
                    )
                except TypeError:
                    report = runtime.run(
                        task=f"sp-escalate-cycle{cycle}",
                        subagents=n, prompts=prompts, use_cache=False,
                    )
            except Exception as e:
                history.append({
                    "cycle": cycle, "n": n, "error": str(e),
                    "elapsed_ms": int((time.perf_counter() - cycle_start) * 1000),
                })
                break

            texts = [r.text for r in report.results if getattr(r, "ok", False)]
            cycle_tokens = (
                getattr(report.usage, "total_tokens", 0)
                if hasattr(report, "usage") else 0
            )
            total_tokens += cycle_tokens

        if structured:
            parsed = [StructuredResponse.from_text(t) for t in texts]
            winner, modal_count, uniq, diag = behavior_modal_vote(parsed)
            last_text = winner.artifact if winner else ""
            last_diagnostics = diag
            last_parse_ok = diag.get("parse_ok_count", 0)
            last_parse_fail = diag.get("parse_failed_count", 0)
        else:
            winning_text, modal_count, uniq = _modal_vote(texts)
            last_text = winning_text or ""
            last_diagnostics = {}
            last_parse_ok = 0
            last_parse_fail = 0

        last_uniq = uniq
        last_modal = modal_count
        last_subagents = n

        passed = False
        oracle_error = None
        try:
            passed = bool(oracle(last_text))
        except Exception as e:
            oracle_error = str(e)
        last_passed = passed

        history.append({
            "cycle": cycle, "n": n, "uniq": uniq,
            "modal_count": modal_count, "passed": passed,
            "parse_ok": last_parse_ok, "parse_fail": last_parse_fail,
            "tokens": cycle_tokens,
            "elapsed_ms": int((time.perf_counter() - cycle_start) * 1000),
            "oracle_error": oracle_error,
        })

        if passed:
            break

    return {
        "text": last_text,
        "tokens": total_tokens,
        "ms": int((time.perf_counter() - t0) * 1000),
        "uniq": last_uniq,
        "modal_count": last_modal,
        "subagents": last_subagents,
        "passed": last_passed,
        "cycles_run": len(history),
        "tier_history": history,
        "escalated": len(history) > 1,
        "structured_parse_ok": last_parse_ok,
        "structured_parse_fail": last_parse_fail,
        "modal_diagnostics": last_diagnostics,
        "error": None,
    }
