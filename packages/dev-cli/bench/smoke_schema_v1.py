#!/usr/bin/env python3
"""Smoke schema v1 against one local/hosted model.

Issue #46 uses this as the cheap go/no-go gate before running the full v14
Qwen2.5-Coder-1.5B GGUF quant curve. The default protocol is 4 calls on one
small PHP task; parse_ok >= 2/4 means the quant is worth the expensive bench.

Examples:
  BENCH_GGUF_PATH=~/models/Qwen2.5-Coder-1.5B-Instruct-Q8_0.gguf \
    python bench/smoke_schema_v1.py

  BENCH_MODEL=local:Qwen/Qwen2.5-Coder-3B-Instruct \
    python bench/smoke_schema_v1.py --out bench/results_sp_schema_smoke_local.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
_GGUF_MODELS: dict[str, Any] = {}
_LOCAL_MODELS: dict[str, tuple[Any, Any]] = {}

STRUCTURED_OUTPUT_INSTRUCTION = """
[OUTPUT FORMAT - STRUCTURED v1]
Your entire response MUST be a single JSON object. The JSON object MUST have
these exact fields:

  - "artifact": (string) the complete deliverable (file content, diff, code)
  - "files_changed": (array of strings) paths the artifact touches
  - "behaviors_added": (array of strings) function/method names you added,
                       in `ClassName::method` or `module.function` form
  - "expected_oracle_pass": (array of strings) tests/patterns you EXPECT
                            will pass with this artifact
  - "confidence": (float 0.0 to 1.0) your self-rated confidence
  - "concerns": (array of strings) things you are unsure about

The "artifact" field is the only field consumed downstream - the others
are aggregated across N parallel subagents to vote on the best output.
Do NOT include code fences around the JSON. Do NOT include prose before
or after. Start with `{` and end with `}`. Nothing else.
"""


TASK_PROMPT = """You are a senior engineer working IN THIS project.
Stack: PHP 8 + PHPUnit.

[GOAL]
Add a NEW public static method `isStrong(string $password): bool` to
App\\Core\\PasswordPolicy.

[TARGET]
Touch ONLY this file: src/Core/PasswordPolicy.php

Current content:
```php
<?php
declare(strict_types=1);

namespace App\\Core;

final class PasswordPolicy
{
    public static function violations(string $password): array
    {
        $violations = [];
        if (strlen($password) < 8) {
            $violations[] = 'min_length';
        }
        return $violations;
    }
}
```

[CONTRACT]
- `isStrong('short')` returns false
- `isStrong('12345678901')` returns false
- `isStrong('123456789012')` returns true
- keep `violations()` unchanged

[OUTPUT]
Return the complete updated PHP file in the `artifact` field.
"""


def _expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_") or "model"


def _quant_from_path(path: str) -> str:
    name = Path(path).name
    m = re.search(r"-(Q\d(?:_[A-Z0-9]+)+)\.gguf$", name)
    return m.group(1) if m else "unknown_quant"


def _model_from_args(args: argparse.Namespace) -> tuple[str, str, str]:
    gguf_path = args.gguf_path or os.environ.get("BENCH_GGUF_PATH")
    model = args.model or os.environ.get("BENCH_MODEL")
    if gguf_path:
        full = _expand(gguf_path)
        return full, f"gguf:{full}", _quant_from_path(full)
    if model:
        return model, model, _quant_from_path(model) if model.endswith(".gguf") else "unknown_quant"
    raise SystemExit("set BENCH_GGUF_PATH or BENCH_MODEL")


def _default_out(model_label: str, quant: str) -> Path:
    if quant != "unknown_quant":
        suffix = quant.lower()
    else:
        suffix = _slug(Path(model_label).name if model_label.endswith(".gguf") else model_label)
    return BENCH / f"results_v14_qwen15b_{suffix}_smoke_schema_v1.json"


def _call_model(model_spec: str, prompt: str) -> dict[str, Any]:
    if model_spec.startswith("gguf:"):
        return _gguf_call(model_spec[5:], prompt)
    if model_spec.endswith(".gguf"):
        return _gguf_call(model_spec, prompt)
    if model_spec.startswith("local:"):
        return _transformers_call(model_spec.split(":", 1)[1], prompt)
    return _http_call(model_spec, prompt)


def _gguf_call(gguf_path: str, prompt: str) -> dict[str, Any]:
    max_new = int(os.environ.get("BENCH_LOCAL_MAX_TOKENS", "1024"))
    t0 = time.perf_counter()
    try:
        llm = _load_gguf(gguf_path)
        out = llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_new,
            temperature=float(os.environ.get("BENCH_LOCAL_TEMP", "0.7")),
            top_p=0.9,
        )
        usage = out.get("usage") or {}
        return {
            "text": out["choices"][0]["message"]["content"],
            "total_tokens": int(usage.get("total_tokens", 0)),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "error": None,
        }
    except Exception as exc:
        return _error_result(t0, exc)


def _load_gguf(gguf_path: str) -> Any:
    full = _expand(gguf_path)
    if full in _GGUF_MODELS:
        return _GGUF_MODELS[full]
    from llama_cpp import Llama

    llm = Llama(
        model_path=full,
        n_ctx=int(os.environ.get("BENCH_GGUF_CTX", "4096")),
        n_threads=int(os.environ.get("BENCH_GGUF_THREADS", "4")),
        verbose=False,
        seed=int(os.environ.get("BENCH_GGUF_SEED", "-1")),
    )
    _GGUF_MODELS[full] = llm
    return llm


def _transformers_call(model_id: str, prompt: str) -> dict[str, Any]:
    max_new = int(os.environ.get("BENCH_LOCAL_MAX_TOKENS", "1024"))
    t0 = time.perf_counter()
    try:
        import torch

        tok, model = _load_transformers(model_id)
        text = tok.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tok(text, return_tensors="pt")
        prompt_tokens = int(inputs["input_ids"].shape[1])
        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=max_new,
                do_sample=True,
                temperature=float(os.environ.get("BENCH_LOCAL_TEMP", "0.7")),
                top_p=0.9,
            )
        completion = out[0][prompt_tokens:]
        response = tok.decode(completion, skip_special_tokens=True)
        return {
            "text": response,
            "total_tokens": int(out.shape[1]),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "error": None,
        }
    except Exception as exc:
        return _error_result(t0, exc)


def _load_transformers(model_id: str) -> tuple[Any, Any]:
    if model_id in _LOCAL_MODELS:
        return _LOCAL_MODELS[model_id]
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.float32,
        low_cpu_mem_usage=True,
    )
    model.eval()
    _LOCAL_MODELS[model_id] = (tok, model)
    return tok, model


def _http_call(model: str, prompt: str) -> dict[str, Any]:
    import urllib.request

    t0 = time.perf_counter()
    base_url = os.environ.get("BENCH_BASE_URL", "https://router.huggingface.co/v1")
    api_key = (
        os.environ.get("BENCH_API_KEY")
        or os.environ.get("HF_TOKEN")
        or os.environ.get("OPENROUTER_API_KEY")
    )
    if not api_key:
        return _error_result(t0, RuntimeError("missing BENCH_API_KEY/HF_TOKEN/OPENROUTER_API_KEY"))
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": float(os.environ.get("BENCH_LOCAL_TEMP", "0.7")),
            "max_tokens": int(os.environ.get("BENCH_LOCAL_MAX_TOKENS", "1024")),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(os.environ.get("BENCH_TIMEOUT", "120"))) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        usage = data.get("usage") or {}
        return {
            "text": data["choices"][0]["message"]["content"],
            "total_tokens": int(usage.get("total_tokens", 0)),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "error": None,
        }
    except Exception as exc:
        return _error_result(t0, exc)


def _error_result(start: float, exc: Exception) -> dict[str, Any]:
    return {
        "text": "",
        "total_tokens": 0,
        "elapsed_ms": int((time.perf_counter() - start) * 1000),
        "error": str(exc),
    }


def _parse_structured_response(text: str) -> dict[str, Any]:
    if not text:
        return {
            "artifact": "",
            "parse_ok": False,
            "parse_error": "empty response",
            "confidence": 0.0,
            "files_changed": [],
            "behaviors_added": [],
            "expected_oracle_pass": [],
        }
    cleaned = text
    fenced = re.search(r"```(?:json)?\s*\n(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    start = cleaned.find("{")
    if start < 0:
        return _parse_fail(text, "no '{' in response")
    depth = 0
    end = -1
    for idx in range(start, len(cleaned)):
        char = cleaned[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = idx
                break
    if end < 0:
        return _parse_fail(text, "unbalanced braces")
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        return _parse_fail(text, f"json error: {exc}")
    if not isinstance(payload, dict):
        return _parse_fail(text, "root is not an object")
    artifact = payload.get("artifact")
    if not isinstance(artifact, str):
        for alt in ("code", "content", "output", "diff"):
            if isinstance(payload.get(alt), str):
                artifact = payload[alt]
                break
    if not isinstance(artifact, str):
        return _parse_fail(text, "no string 'artifact' field")
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "artifact": artifact,
        "parse_ok": True,
        "parse_error": None,
        "confidence": max(0.0, min(1.0, confidence)),
        "files_changed": _string_list(payload.get("files_changed")),
        "behaviors_added": _string_list(payload.get("behaviors_added")),
        "expected_oracle_pass": _string_list(payload.get("expected_oracle_pass")),
    }


def _parse_fail(text: str, reason: str) -> dict[str, Any]:
    return {
        "artifact": text,
        "parse_ok": False,
        "parse_error": reason,
        "confidence": 0.0,
        "files_changed": [],
        "behaviors_added": [],
        "expected_oracle_pass": [],
    }


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _artifact_matches_contract(artifact: str) -> bool:
    text = artifact or ""
    return (
        "isStrong" in text
        and "function" in text
        and "12" in text
        and "violations" in text
        and "PasswordPolicy" in text
    )


def run_smoke(
    model_label: str,
    model_spec: str,
    quant: str,
    calls: int,
    prompt: str,
) -> dict[str, Any]:
    rows = []
    parse_ok = 0
    artifact_ok = 0
    tokens = 0
    elapsed_ms = 0
    for idx in range(1, calls + 1):
        res = _call_model(model_spec, prompt)
        parsed = _parse_structured_response(res.get("text", ""))
        artifact_matches = _artifact_matches_contract(parsed["artifact"])
        parse_ok += int(parsed["parse_ok"])
        artifact_ok += int(artifact_matches)
        tokens += int(res.get("total_tokens") or 0)
        elapsed_ms += int(res.get("elapsed_ms") or 0)
        rows.append(
            {
                "call": idx,
                "parse_ok": parsed["parse_ok"],
                "parse_error": parsed["parse_error"],
                "artifact_matches_contract": artifact_matches,
                "confidence": parsed["confidence"],
                "files_changed": parsed["files_changed"],
                "behaviors_added": parsed["behaviors_added"],
                "expected_oracle_pass": parsed["expected_oracle_pass"],
                "error": res.get("error"),
                "elapsed_ms": int(res.get("elapsed_ms") or 0),
                "total_tokens": int(res.get("total_tokens") or 0),
                "artifact_preview": parsed["artifact"][:500],
            }
        )
        print(
            f"[{idx}/{calls}] parse_ok={parsed['parse_ok']} "
            f"artifact_contract={artifact_matches} "
            f"elapsed_ms={int(res.get('elapsed_ms') or 0)}"
        )
    go_no_go_threshold = max(1, calls // 2)
    return {
        "benchmark": "schema-v1-smoke",
        "issue": 46,
        "date": time.strftime("%Y-%m-%d"),
        "model": model_label,
        "model_spec": model_spec,
        "quant": quant,
        "calls": calls,
        "task": "PasswordPolicy::isStrong schema v1 smoke",
        "go_no_go": {
            "criterion": f"parse_ok >= {go_no_go_threshold}/{calls}",
            "pass": parse_ok >= go_no_go_threshold,
        },
        "summary": {
            "parse_ok": parse_ok,
            "parse_failed": calls - parse_ok,
            "parse_ok_rate": round(parse_ok / max(calls, 1), 4),
            "artifact_matches_contract": artifact_ok,
            "artifact_matches_contract_rate": round(artifact_ok / max(calls, 1), 4),
            "total_tokens": tokens,
            "elapsed_ms": elapsed_ms,
            "avg_elapsed_ms": elapsed_ms // max(calls, 1),
        },
        "rows": rows,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the 4-call schema v1 smoke used by issue #46."
    )
    parser.add_argument("--gguf-path", help="Path to a GGUF model file. Also BENCH_GGUF_PATH.")
    parser.add_argument("--model", help="Hosted or local model id. Also BENCH_MODEL.")
    parser.add_argument(
        "--calls",
        type=int,
        default=int(os.environ.get("BENCH_SCHEMA_SMOKE_CALLS", "4")),
        help="Number of calls; issue #46 protocol uses 4.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Output JSON path. Defaults to bench/results_v14_qwen15b_<quant>_smoke_schema_v1.json.",
    )
    parser.add_argument("--no-write", action="store_true", help="Print summary without writing JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.calls <= 0:
        raise SystemExit("--calls must be positive")
    model_label, model_spec, quant = _model_from_args(args)
    prompt = TASK_PROMPT + "\n\n" + STRUCTURED_OUTPUT_INSTRUCTION.strip()
    result = run_smoke(model_label, model_spec, quant, args.calls, prompt)
    out = args.out or _default_out(model_label, quant)
    if not args.no_write:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    s = result["summary"]
    print(
        "summary: "
        f"parse_ok={s['parse_ok']}/{result['calls']} "
        f"artifact_contract={s['artifact_matches_contract']}/{result['calls']} "
        f"go_no_go={result['go_no_go']['pass']}"
    )
    if not args.no_write:
        print(f"-> {out}")
    return 0 if result["go_no_go"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
