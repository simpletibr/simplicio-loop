"""
providers.py — provider-agnostic. Does NOT list specific models.

Four modes, picked by SIMPLICIO_MODEL prefix (or by absence of config):

1. Native Anthropic SDK
     SIMPLICIO_MODEL=claude-opus-4-7
     SIMPLICIO_API_KEY=<anthropic key>
     SIMPLICIO_BASE_URL=(unset)

2. Any OpenAI-compatible endpoint (OpenRouter, GLM, DeepSeek, Ollama, ...)
     SIMPLICIO_MODEL=anthropic/claude-opus-4
     SIMPLICIO_API_KEY=<provider key>
     SIMPLICIO_BASE_URL=https://openrouter.ai/api/v1

3. Shell-out to a logged-in CLI (zero API key — uses OAuth subscription)
     SIMPLICIO_MODEL=claude-cli/<model>      -> spawns `claude -p`
     SIMPLICIO_MODEL=codex-cli/<model>       -> spawns `codex exec`
     No SIMPLICIO_API_KEY needed. Requires the CLI to be on PATH and the user
     to be logged in (Claude Code session or `codex login`). Subprocess is
     given SIMPLICIO_HOOK_GUARD=1 so the inner CLI does not re-trigger the
     simplicio UserPromptSubmit hook (recursion guard).

4. Local llama.cpp default (offline-first, zero key)
     SIMPLICIO_MODEL=(unset)
     SIMPLICIO_BASE_URL=(unset)
     -> openbmb/minicpm5:latest, loaded in-process with llama-cpp-python

5. Explicit in-process local inference via llama-cpp-python (zero key)
     SIMPLICIO_MODEL=local-llama/<repo>::<file.gguf>   -> explicit HF GGUF
     SIMPLICIO_MODEL=openbmb/minicpm5:latest           -> default MiniCPM5 GGUF
     SIMPLICIO_MODEL=local-llama//abs/path/model.gguf  -> direct local path
     The
     GGUF is reused from ~/.simplicio/models/executor when present, otherwise
     fetched once from the Hugging Face Hub. Requires the `local` extra:
     pip install 'simplicio-cli[local]'.
"""

import os
import shutil
import subprocess
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from ._cache import CacheEntry, cache, make_key

_LAST_CACHE_RECEIPT: dict[str, Any] | None = None


class ProviderExecutionError(SystemExit):
    """Terminal provider failure carrying a machine-readable receipt."""

    def __init__(self, receipt: dict[str, Any]):
        self.receipt = dict(receipt)
        super().__init__(self.receipt.get("message", self.receipt.get("reason_code", "provider failure")))


def _cache_bypass_reason() -> str | None:
    current_cache = cache()
    if not current_cache.enabled:
        return "cache_disabled"
    if current_cache.bust:
        return "cache_busted"
    return None


def _remember_cache_receipt(receipt: dict[str, Any] | None) -> None:
    global _LAST_CACHE_RECEIPT
    _LAST_CACHE_RECEIPT = None if receipt is None else deepcopy(receipt)


def last_cache_receipt() -> dict[str, Any] | None:
    if _LAST_CACHE_RECEIPT is None:
        return None
    return deepcopy(_LAST_CACHE_RECEIPT)


def _new_cache_receipt(*, surface: str, requested_provider_id: str, requested_model: str) -> dict[str, Any]:
    receipt = {
        "schema": "simplicio.providers.cache-receipt/v1",
        "surface": surface,
        "requested_provider_id": requested_provider_id,
        "requested_model": requested_model,
        "outcome": "pending",
        "local_exact_lookup": {
            "status": "not_tried",
            "reason": None,
            "provider_id": None,
            "model": None,
            "key": None,
        },
        "provider_lookup": {
            "status": "not_tried",
            "reason": None,
            "provider_id": None,
            "model": None,
            "key": None,
        },
        "provider_write": {
            "status": "not_tried",
            "reason": None,
            "provider_id": None,
            "model": None,
            "key": None,
        },
    }
    _remember_cache_receipt(receipt)
    return receipt


def _set_cache_step(
    receipt: dict[str, Any],
    step: str,
    *,
    status: str,
    provider_id: str,
    model: str,
    key: str,
    reason: str | None = None,
) -> None:
    receipt[step] = {
        "status": status,
        "reason": reason,
        "provider_id": provider_id,
        "model": model,
        "key": key,
    }
    _remember_cache_receipt(receipt)


def _finalize_cache_receipt(receipt: dict[str, Any]) -> None:
    if receipt["local_exact_lookup"]["status"] == "hit":
        outcome = "local_exact_reuse"
    elif receipt["provider_lookup"]["status"] == "hit":
        outcome = "provider_cache_read"
    elif receipt["provider_write"]["status"] == "written":
        outcome = "provider_cache_write"
    elif any(
        receipt[name]["status"] == "bypass"
        for name in ("local_exact_lookup", "provider_lookup", "provider_write")
    ):
        outcome = "bypass"
    else:
        outcome = "cache_miss"
    receipt["outcome"] = outcome
    _remember_cache_receipt(receipt)
    _log_cache_receipt(receipt)


def _log_cache_receipt(receipt: dict[str, Any]) -> None:
    """Persist the structured cache decision without ever logging the prompt.

    Provider receipts contain cache keys and routing metadata, but not prompt or
    completion content.  Keep persistence opt-in and fail-open like usage
    logging so observability cannot break a provider call.
    """
    root = os.environ.get("SIMPLICIO_LOG_ROOT")
    if not root:
        return
    from .observability import log_run

    try:
        log_run(root, {"mode": "provider_cache_receipt", "receipt": deepcopy(receipt)})
    except OSError:
        pass


def _import_openai():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit(
            "simplicio: this provider needs the openai SDK. "
            "Install extras: pip install 'simplicio-cli[providers]'"
        ) from exc
    return OpenAI


def _import_anthropic():
    try:
        import anthropic
    except ImportError as exc:
        raise SystemExit(
            "simplicio: this provider needs the anthropic SDK. "
            "Install extras: pip install 'simplicio-cli[providers]'"
        ) from exc
    return anthropic


def _cfg():
    return {
        "model": os.environ.get("SIMPLICIO_MODEL"),
        "base": os.environ.get("SIMPLICIO_BASE_URL"),
        "key": os.environ.get("SIMPLICIO_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY"),
    }


def _msgs(prompt, feedback):
    m = [{"role": "user", "content": prompt}]
    if feedback:
        m.append(
            {
                "role": "user",
                "content": f"The test FAILED:\n{feedback}\nFix it. Same output format.",
            }
        )
    return m


def _inline_feedback(prompt, feedback):
    if not feedback:
        return prompt
    return f"{prompt}\n\nThe test FAILED:\n{feedback}\nFix it. Same output format."


# --------------------------------------------------------------------------- #
# Operating constraints injected into EVERY LLM contact (doer + planner, all
# provider paths: Anthropic native, OpenAI-compatible, claude-cli/codex-cli
# shell-out, in-process llama.cpp). The doer is a mechanical task-to-diff
# worker: it must not reason out loud, must not reach the network, and must
# only touch the tools/skills the task strictly needs. Prepended (not
# appended) so the template's strict [OUTPUT] block stays the last thing the
# model reads. Opt out with SIMPLICIO_NO_LLM_DIRECTIVES=1.
# --------------------------------------------------------------------------- #
LLM_DIRECTIVES = (
    "[OPERATING CONSTRAINTS — non-negotiable]\n"
    "- No thinking: do not reason out loud, plan, or emit chain-of-thought. "
    "Produce only the requested output.\n"
    "- No internet: do not browse, fetch URLs, or use any external network "
    "resource. Use only the context provided below.\n"
    "- Tools: use only the tools strictly necessary for this task; invoke no "
    "others.\n"
    "- Skills: load only the skills strictly necessary for this task; activate "
    "no others.\n"
)


def _directives_enabled() -> bool:
    return os.environ.get("SIMPLICIO_NO_LLM_DIRECTIVES", "").strip() not in (
        "1",
        "true",
        "True",
        "yes",
    )


def _apply_directives(prompt):
    """Prepend the operating-constraints header to any prompt bound for an LLM.

    Idempotent and opt-out-able (SIMPLICIO_NO_LLM_DIRECTIVES=1)."""
    if not _directives_enabled():
        return prompt
    if prompt and prompt.startswith(LLM_DIRECTIVES):
        return prompt
    return f"{LLM_DIRECTIVES}\n{prompt}"


# --------------------------------------------------------------------------- #
# Path 4: local llama.cpp default + Path 5: explicit in-process GGUF.
# --------------------------------------------------------------------------- #

# MiniCPM5 is the ecosystem default local doer. The public model id mirrors the
# runtime policy, while the GGUF repo/file are the llama.cpp backing weights.
LOCAL_DEFAULT_MODEL = "openbmb/minicpm5:latest"
LOCAL_DEFAULT_REPO = "openbmb/MiniCPM5-1B-GGUF"
LOCAL_DEFAULT_FILE = "MiniCPM5-1B-Q4_K_M.gguf"
LOCAL_EXECUTOR_DIR = "~/.simplicio/models/executor"
LOCAL_MODEL_PREFIX = "local-llama/"
LOCAL_DEFAULT_CTX = 2048
LOCAL_MAX_CTX = 4096
LOCAL_DEFAULT_THREADS = min(os.cpu_count() or 1, 4)
LOCAL_MAX_THREADS = 4
LOCAL_DEFAULT_MAX_TOKENS = 512
LOCAL_MAX_OUTPUT_TOKENS = 2048
LOCAL_DEFAULT_BATCH = 128
LOCAL_MAX_BATCH = 128
LOCAL_DEFAULT_UBATCH = 32
LOCAL_MAX_UBATCH = 32
LOCAL_MAX_GPU_LAYERS = 0

# Loaded Llama instances, keyed by memory-relevant llama.cpp settings.
# A model load is expensive (weights -> RAM), so we keep it for the process.
_LOCAL_LLAMA_CACHE: dict[tuple[Any, ...], Any] = {}


def _is_local(model, base):
    """True when generate() should route to the in-process llama backend.

    Only explicit `local-llama/` models return true here. The empty config
    default is handled separately so info/errors can describe the auto route.
    """
    if model and (model.startswith(LOCAL_MODEL_PREFIX) or model == LOCAL_DEFAULT_MODEL):
        return True
    return False


def _is_default_local(model, base):
    """True when empty config should use the in-process llama.cpp default."""
    if (not model and not base) or (model == LOCAL_DEFAULT_MODEL and not base):
        return True
    return False


def _local_spec(model):
    """Resolve (repo, file, path) for a local-llama model id.

    Forms after the `local-llama/` prefix:
      "" / "default" / "auto"   -> MiniCPM5 Q4_K_M GGUF fallback
      "<repo>::<file.gguf>"     -> explicit HF repo + filename
      "/abs/path/model.gguf"    -> direct local path (no download)
      "<repo>"                  -> HF repo + default/SIMPLICIO_LOCAL_MODEL_FILE
    The ecosystem id `openbmb/minicpm5:latest` resolves to the same default.
    SIMPLICIO_LOCAL_MODEL_PATH always wins when set.
    """
    path = os.environ.get("SIMPLICIO_LOCAL_MODEL_PATH")
    if path:
        return None, None, path
    file_env = os.environ.get("SIMPLICIO_LOCAL_MODEL_FILE", LOCAL_DEFAULT_FILE)
    spec = ""
    if model == LOCAL_DEFAULT_MODEL:
        spec = "default"
    elif model and model.startswith(LOCAL_MODEL_PREFIX):
        spec = model[len(LOCAL_MODEL_PREFIX) :].strip()
    if spec and spec not in ("default", "auto"):
        if "::" in spec:
            repo, fname = spec.split("::", 1)
            return repo.strip(), fname.strip(), None
        if spec.endswith(".gguf") and (os.sep in spec or spec.startswith((".", "/"))):
            return None, None, spec
        return spec, file_env, None
    repo = os.environ.get("SIMPLICIO_LOCAL_MODEL_REPO", LOCAL_DEFAULT_REPO)
    return repo, file_env, None


def _local_executor_dir() -> Path:
    return Path(os.environ.get("SIMPLICIO_LOCAL_MODEL_DIR", LOCAL_EXECUTOR_DIR)).expanduser()


def _is_gguf_file(path) -> bool:
    """Return true when path exists and starts with the GGUF magic header."""
    try:
        with Path(path).open("rb") as handle:
            return handle.read(4) == b"GGUF"
    except OSError:
        return False


def _local_candidates(repo, fname):
    """Return candidate (repo, GGUF filename) pairs in preference order."""
    return [(repo, fname)]


def _resolve_local_path(repo, fname, path):
    """Return a filesystem path to the GGUF, downloading from HF if needed."""
    if path:
        if not os.path.exists(path):
            raise SystemExit(
                f"simplicio: local model not found at {path}. Point "
                "SIMPLICIO_LOCAL_MODEL_PATH at an existing .gguf file."
            )
        if not _is_gguf_file(path):
            raise SystemExit(
                f"simplicio: local model at {path} is not a valid GGUF file. "
                "Download a GGUF model or update SIMPLICIO_LOCAL_MODEL_PATH."
            )
        return path
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise SystemExit(
            "simplicio: local backend needs huggingface-hub. "
            "Install extras: pip install 'simplicio-cli[local]'"
        ) from exc
    errors = []
    for candidate_repo, candidate_file in _local_candidates(repo, fname):
        local_file = _local_executor_dir() / candidate_file
        if local_file.is_file():
            if _is_gguf_file(local_file):
                return str(local_file)
            errors.append(f"{local_file}: invalid GGUF header")
        try:
            downloaded = hf_hub_download(repo_id=candidate_repo, filename=candidate_file)
            if _is_gguf_file(downloaded):
                return downloaded
            errors.append(f"{candidate_repo}/{candidate_file}: invalid GGUF header")
        except Exception as exc:  # noqa: BLE001 - fallback to the next local GGUF
            errors.append(f"{candidate_repo}/{candidate_file}: {exc}")
    detail = "; ".join(errors) if errors else f"{fname}: unavailable"
    raise SystemExit(f"simplicio: local model download failed ({detail})")


def _bounded_int(name, default, *, minimum=1, maximum=None):
    """Read a positive int env knob and clamp it to the safe local policy."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise SystemExit(f"simplicio: {name} must be a positive integer") from exc
    value = max(minimum, value)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _safe_local_ctx():
    maximum = min(_bounded_int("SIMPLICIO_LOCAL_CTX_MAX", LOCAL_MAX_CTX), LOCAL_MAX_CTX)
    return _bounded_int("SIMPLICIO_LOCAL_CTX", LOCAL_DEFAULT_CTX, maximum=maximum)


def _safe_local_threads():
    maximum = min(
        _bounded_int("SIMPLICIO_LOCAL_THREADS_MAX", LOCAL_MAX_THREADS),
        LOCAL_MAX_THREADS,
    )
    return _bounded_int("SIMPLICIO_LOCAL_THREADS", LOCAL_DEFAULT_THREADS, maximum=maximum)


def _safe_local_batch():
    maximum = min(
        _bounded_int("SIMPLICIO_LOCAL_BATCH_MAX", LOCAL_MAX_BATCH),
        LOCAL_MAX_BATCH,
    )
    return _bounded_int("SIMPLICIO_LOCAL_BATCH", LOCAL_DEFAULT_BATCH, minimum=32, maximum=maximum)


def _safe_local_ubatch():
    maximum = min(
        _bounded_int("SIMPLICIO_LOCAL_UBATCH_MAX", LOCAL_MAX_UBATCH),
        LOCAL_MAX_UBATCH,
    )
    return _bounded_int("SIMPLICIO_LOCAL_UBATCH", LOCAL_DEFAULT_UBATCH, minimum=16, maximum=maximum)


def _safe_local_gpu_layers():
    return min(
        _bounded_int(
            "SIMPLICIO_LOCAL_GPU_LAYERS",
            LOCAL_MAX_GPU_LAYERS,
            minimum=0,
            maximum=LOCAL_MAX_GPU_LAYERS,
        ),
        LOCAL_MAX_GPU_LAYERS,
    )


def _safe_local_max_tokens(requested):
    maximum = min(
        _bounded_int("SIMPLICIO_LOCAL_MAX_TOKENS_CAP", LOCAL_MAX_OUTPUT_TOKENS),
        LOCAL_MAX_OUTPUT_TOKENS,
    )
    configured = os.environ.get("SIMPLICIO_LOCAL_MAX_TOKENS")
    default = min(requested, LOCAL_DEFAULT_MAX_TOKENS)
    if configured is None or configured == "":
        return min(default, maximum)
    return _bounded_int("SIMPLICIO_LOCAL_MAX_TOKENS", default, maximum=maximum)


def _local_llama(model):
    """Load (or reuse) the Llama instance for the given local model id."""
    try:
        from llama_cpp import Llama
    except ImportError as exc:
        raise SystemExit(
            "simplicio: local backend needs llama-cpp-python. "
            "Install extras: pip install 'simplicio-cli[local]'"
        ) from exc
    repo, fname, path = _local_spec(model)
    gguf = _resolve_local_path(repo, fname, path)
    n_ctx = _safe_local_ctx()
    n_threads = _safe_local_threads()
    n_batch = _safe_local_batch()
    n_ubatch = _safe_local_ubatch()
    n_gpu_layers = _safe_local_gpu_layers()
    cache_key = (gguf, n_ctx, n_threads, n_batch, n_ubatch, n_gpu_layers)
    llm = _LOCAL_LLAMA_CACHE.get(cache_key)
    if llm is None:
        llm = Llama(
            model_path=gguf,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_batch=n_batch,
            n_ubatch=n_ubatch,
            n_gpu_layers=n_gpu_layers,
            use_mmap=True,
            use_mlock=False,
            verbose=False,
        )
        _LOCAL_LLAMA_CACHE[cache_key] = llm
    return llm


def _local_generate(prompt, feedback, model, max_tokens):
    """Generate a completion in-process via llama-cpp-python."""
    llm = _local_llama(model)
    out_tokens = _safe_local_max_tokens(max_tokens)
    temperature = float(os.environ.get("SIMPLICIO_LOCAL_TEMP", "0.1"))
    r = llm.create_chat_completion(
        messages=_msgs(prompt, feedback),
        max_tokens=out_tokens,
        temperature=temperature,
    )
    return r["choices"][0]["message"]["content"] or ""


def _provider_id(model, base):
    if model and (model.startswith(LOCAL_MODEL_PREFIX) or model == LOCAL_DEFAULT_MODEL):
        return "local-llama"
    if model.startswith("claude-cli/"):
        return "claude-cli"
    if model.startswith("codex-cli/"):
        return "codex-cli"
    if base:
        return f"openai-compatible:{base.rstrip('/')}"
    return "anthropic-native"


def _shell_out(cmd, label, stdin_text=None, cancel_event=None, *, provider="unknown", model="", effort=""):
    """Run a subprocess that uses an OAuth session instead of an API key.

    SIMPLICIO_HOOK_GUARD=1 + SIMPLICIO_SKIP_AUTO_INIT=1 are injected so the
    inner CLI does not recursively fire simplicio's UserPromptSubmit hook nor
    re-run the first-run bootstrap.

    Issue #210: delegates the actual spawn/wait to
    :func:`simplicio.task_operator.run_bounded_subprocess`, which adds
    heartbeats, a startup-vs-total timeout split, process-tree kill on
    timeout/cancellation, and cooperative cancellation via *cancel_event*.
    The public contract here is unchanged: on any non-success phase this
    still raises ``SystemExit`` with a human-readable message — the message
    now names which phase the stall was classified as, instead of a bare
    "timed out".
    """
    from .task_operator import (
        PHASE_CANCELLED,
        PHASE_COMPLETED,
        PHASE_STARTUP_TIMEOUT,
        PHASE_TOTAL_TIMEOUT,
        run_bounded_subprocess,
    )

    env = {**os.environ, "SIMPLICIO_HOOK_GUARD": "1", "SIMPLICIO_SKIP_AUTO_INIT": "1"}
    root = os.environ.get("SIMPLICIO_LOG_ROOT")
    started = time.monotonic()
    result = run_bounded_subprocess(
        cmd,
        label=label,
        env=env,
        stdin_text=stdin_text,
        cancel_event=cancel_event,
        root=root,
    )

    def terminal(status, reason_code, *, exit_code=None, detail=""):
        return {
            "schema": "simplicio.provider-terminal/v1",
            "status": status,
            "reason_code": reason_code,
            "attempt": 1,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "exit_code": exit_code,
            "provider": provider,
            "model": model or "redacted",
            "effort": effort or "redacted",
            "detail": str(detail)[:500],
            "message": f"{label}: {reason_code}",
        }

    if result.phase != PHASE_COMPLETED or result.returncode != 0:
        stderr = (result.stderr or "").strip()
        combined = f"{stderr}\n{result.stdout or ''}".lower()
        capacity_terms = ("credit", "quota", "rate limit", "rate_limit", "billing", "insufficient", "usage limit")
        if result.phase == PHASE_STARTUP_TIMEOUT:
            reason = "provider_startup_timeout"
        elif result.phase == PHASE_TOTAL_TIMEOUT:
            reason = "provider_timeout"
        elif result.phase == PHASE_CANCELLED:
            reason = "provider_cancelled"
        elif result.returncode is None:
            reason = "provider_not_installed"
        else:
            reason = "provider_capacity_unavailable" if any(term in combined for term in capacity_terms) else (
                "provider_child_exit_silent" if not combined.strip() else "provider_process_failed"
            )
        raise ProviderExecutionError(terminal(
            "blocked" if reason in {"provider_capacity_unavailable", "provider_startup_timeout", "provider_timeout", "provider_cancelled", "provider_not_installed"} else "failed",
            reason,
            exit_code=result.returncode,
            detail=stderr or result.recovery or (result.stdout or "").strip(),
        ))
    return result.stdout


def _cli_command(name):
    if os.name != "nt":
        return name
    for candidate in (f"{name}.cmd", f"{name}.exe", name):
        if shutil.which(candidate):
            return candidate
    return name


def _codex_supports_effort_flag() -> bool:
    cmd = [_cli_command("codex"), "exec", "--help"]
    try:
        result = subprocess.run(
            cmd,
            env={**os.environ, "SIMPLICIO_HOOK_GUARD": "1", "SIMPLICIO_SKIP_AUTO_INIT": "1"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    help_text = f"{result.stdout}\n{result.stderr}"
    return "--effort" in help_text


def _shell_out_claude(prompt, model, cancel_event=None):
    cmd = [_cli_command("claude"), "-p", prompt]
    if model and model not in ("default", "auto"):
        cmd += ["--model", model]
    return _shell_out(cmd, "Claude Code CLI (`claude -p`)", cancel_event=cancel_event, provider="claude-cli", model=model)


def _shell_out_codex(prompt, model, cancel_event=None):
    with tempfile.TemporaryDirectory(prefix="simplicio-codex-") as temp_dir:
        output_path = str(Path(temp_dir) / "last-message.txt")
        cmd = [_cli_command("codex"), "exec"]
        cmd.append("--skip-git-repo-check")
        cmd += ["--cd", temp_dir, "--ignore-rules", "--color", "never", "--output-last-message", output_path]
        if model and model not in ("default", "auto"):
            cmd += ["--model", model]
        effort = os.environ.get("SIMPLICIO_CODEX_EFFORT", "").strip().lower()
        if effort and _codex_supports_effort_flag():
            cmd += ["--effort", effort]
        cmd.append("-")
        _shell_out(
            cmd,
            "Codex CLI (`codex exec`)",
            stdin_text=prompt,
            provider="codex-cli",
            model=model,
            effort=effort,
        )
        try:
            return Path(output_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(
                "simplicio: Codex CLI completed but did not produce an output-last-message file."
            ) from exc


def _charge_if_budgeted(model, prompt, out):
    from .orchestrator.cost_governor import charge_provider_call

    charge_provider_call(model, prompt, out or "")


def _openai_usage(response):
    """Pull `{prompt_tokens, completion_tokens}` off an OpenAI-compatible
    response when the SDK/endpoint reported it, else None."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    if prompt_tokens is None and completion_tokens is None:
        return None
    return {"prompt_tokens": prompt_tokens or 0, "completion_tokens": completion_tokens or 0}


def _anthropic_usage(response):
    """Pull `{prompt_tokens, completion_tokens}` off a native Anthropic
    Messages response (`usage.input_tokens`/`usage.output_tokens`), else
    None."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if input_tokens is None and output_tokens is None:
        return None
    return {"prompt_tokens": input_tokens or 0, "completion_tokens": output_tokens or 0}


def _log_usage_event(*, provider_id, model, prompt, completion, cache_hit, usage=None, surface="generate"):
    """Append one runs.jsonl usage event per provider call (issue #88 AC3).

    Opt-in via `SIMPLICIO_LOG_ROOT`: `providers.py` has no notion of "the
    project root" the way `pipeline.py`/`bench.py` do (both receive `root`
    explicitly from their caller), so — unlike those — it never guesses one
    from the current working directory. Callers that know the project root
    (the `task`/`run`/`bench` CLI commands) set `SIMPLICIO_LOG_ROOT` for the
    duration of the call; with it unset this is a no-op, matching
    `observability.log_run`'s existing "lightweight opt-in" contract.

    `usage_source` is "provider" when the SDK/endpoint reported real token
    counts (`usage` arg present), else "estimated" via the single canonical
    estimator (`observability.estimate_tokens` — see issue #88 AC4). Fails
    open: a logging error never breaks generation.
    """
    root = os.environ.get("SIMPLICIO_LOG_ROOT")
    if not root:
        return
    from .observability import estimate_token_details, log_run

    if usage:
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        usage_source = "provider"
        token_estimate = {"source": "provider", "encoding": None}
    else:
        prompt_estimate = estimate_token_details(prompt)
        completion_estimate = estimate_token_details(completion)
        prompt_tokens = int(prompt_estimate["tokens"])
        completion_tokens = int(completion_estimate["tokens"])
        usage_source = str(prompt_estimate["source"])
        token_estimate = {
            "source": usage_source,
            "encoding": prompt_estimate["encoding"],
            "model": prompt_estimate["model"],
            "completion_source": completion_estimate["source"],
            "completion_encoding": completion_estimate["encoding"],
        }
    try:
        log_run(
            root,
            {
                "mode": "provider_call",
                "surface": surface,
                "provider_id": provider_id,
                "model": model or "",
                "cache_hit": bool(cache_hit),
                "usage_source": usage_source,
                "token_estimate": token_estimate,
                "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
                "tokens_estimated": prompt_tokens + completion_tokens,
            },
        )
    except OSError:
        pass


def _return_cached(
    *,
    provider_id,
    model,
    prompt,
    cached,
    surface="generate",
    receipt: dict[str, Any] | None = None,
    cache_step: str | None = None,
    key: str | None = None,
):
    if receipt is not None and cache_step is not None and key is not None:
        _set_cache_step(
            receipt,
            cache_step,
            status="hit",
            provider_id=provider_id,
            model=model,
            key=key,
        )
        _finalize_cache_receipt(receipt)
    _log_usage_event(
        provider_id=provider_id,
        model=model,
        prompt=prompt,
        completion=cached.completion,
        cache_hit=True,
        surface=surface,
    )
    return cached.completion


def _finalize_completion(
    *,
    key,
    out,
    provider_id,
    model,
    prompt,
    usage=None,
    surface="generate",
    receipt: dict[str, Any] | None = None,
):
    _charge_if_budgeted(model, prompt, out)
    _log_usage_event(
        provider_id=provider_id,
        model=model,
        prompt=prompt,
        completion=out,
        cache_hit=False,
        usage=usage,
        surface=surface,
    )
    bypass_reason = _cache_bypass_reason()
    if receipt is not None:
        if bypass_reason is not None:
            _set_cache_step(
                receipt,
                "provider_write",
                status="bypass",
                reason=bypass_reason,
                provider_id=provider_id,
                model=model,
                key=key,
            )
        else:
            _set_cache_step(
                receipt,
                "provider_write",
                status="written",
                provider_id=provider_id,
                model=model,
                key=key,
            )
    cache().put(key, CacheEntry(out, provider_id=provider_id, model=model))
    if receipt is not None:
        _finalize_cache_receipt(receipt)
    return out


def _generate_local_cached(prompt, feedback, model, max_tokens, cache_full_prompt, receipt=None):
    eff_model = model or (LOCAL_MODEL_PREFIX + "default")
    # Fold the resolved weights into the cache key: two different GGUFs can
    # both route as the default model (via SIMPLICIO_LOCAL_MODEL_PATH /
    # _REPO / _FILE), and must NOT share cached completions.
    repo, fname, path = _local_spec(eff_model)
    weights = path or f"{repo}/{fname}"
    key = make_key(
        "local-llama",
        eff_model,
        prompt,
        feedback=feedback,
        max_tokens=max_tokens,
        weights=weights,
    )
    bypass_reason = _cache_bypass_reason()
    if receipt is not None:
        _set_cache_step(
            receipt,
            "provider_lookup",
            status="bypass" if bypass_reason is not None else "miss",
            reason=bypass_reason,
            provider_id="local-llama",
            model=eff_model,
            key=key,
        )
    cached = cache().get(key)
    if cached is not None:
        return _return_cached(
            provider_id="local-llama",
            model=eff_model,
            prompt=cache_full_prompt,
            cached=cached,
            receipt=receipt,
            cache_step="provider_lookup",
            key=key,
        )
    out = _local_generate(prompt, feedback, eff_model, max_tokens)
    _charge_if_budgeted(eff_model, cache_full_prompt, out)
    _log_usage_event(
        provider_id="local-llama",
        model=eff_model,
        prompt=cache_full_prompt,
        completion=out,
        cache_hit=False,
    )
    if receipt is not None:
        if bypass_reason is not None:
            _set_cache_step(
                receipt,
                "provider_write",
                status="bypass",
                reason=bypass_reason,
                provider_id="local-llama",
                model=eff_model,
                key=key,
            )
        else:
            _set_cache_step(
                receipt,
                "provider_write",
                status="written",
                provider_id="local-llama",
                model=eff_model,
                key=key,
            )
    cache().put(key, CacheEntry(out, provider_id="local-llama", model=eff_model))
    if receipt is not None:
        _finalize_cache_receipt(receipt)
    return out


def _openai_compatible_generate(model, base, key, prompt, feedback, max_tokens):
    """Returns `(completion, usage)`; `usage` is the dict `_openai_usage`
    extracted from the response, or None when the endpoint didn't report
    it."""
    OpenAI = _import_openai()

    cli = OpenAI(base_url=base, api_key=key)
    r = cli.chat.completions.create(model=model, max_tokens=max_tokens, messages=_msgs(prompt, feedback))
    return r.choices[0].message.content, _openai_usage(r)


def generate(prompt, feedback=None, max_tokens=4000, template_version=None):
    # Cache lookup BEFORE provider config. Key uses just SIMPLICIO_MODEL
    # (no credential check) so a hit returns without requiring an API key
    # to be set in the environment.
    from ._cache import cache, make_key

    model_name = os.environ.get("SIMPLICIO_MODEL", "").strip()
    prompt = _apply_directives(prompt)
    cache_full_prompt = _inline_feedback(prompt, feedback)
    cache_key = make_key(
        provider_id="doer",
        model=model_name,
        prompt=cache_full_prompt,
        max_tokens=max_tokens,
        template_version=template_version,
    )
    receipt = _new_cache_receipt(
        surface="generate",
        requested_provider_id="doer",
        requested_model=model_name,
    )
    exact_bypass_reason = _cache_bypass_reason()
    _set_cache_step(
        receipt,
        "local_exact_lookup",
        status="bypass" if exact_bypass_reason is not None else "miss",
        reason=exact_bypass_reason,
        provider_id="doer",
        model=model_name,
        key=cache_key,
    )
    cached = cache().get(cache_key)
    if cached is not None:
        return _return_cached(
            provider_id="doer",
            model=model_name,
            prompt=cache_full_prompt,
            cached=cached,
            receipt=receipt,
            cache_step="local_exact_lookup",
            key=cache_key,
        )

    c = _cfg()
    model = c["model"]

    # Path 4: no config means local llama.cpp GGUF, no Ollama/HTTP service.
    if _is_default_local(model, c["base"]):
        return _generate_local_cached(
            prompt,
            feedback,
            LOCAL_DEFAULT_MODEL,
            max_tokens,
            cache_full_prompt,
            receipt,
        )

    # Path 5: in-process local inference via explicit `local-llama/` model.
    if _is_local(model, c["base"]):
        return _generate_local_cached(prompt, feedback, model, max_tokens, cache_full_prompt, receipt)

    if not model:
        raise SystemExit(
            "set SIMPLICIO_MODEL (e.g. anthropic/claude-opus-4, claude-cli/sonnet, "
            f"codex-cli/gpt-5, {LOCAL_DEFAULT_MODEL}, "
            "glm-4.6, llama3, claude-opus-4-7)"
        )
    provider_id = _provider_id(model, c["base"])
    key = make_key(
        provider_id,
        model,
        prompt,
        feedback=feedback,
        max_tokens=max_tokens,
    )
    provider_bypass_reason = _cache_bypass_reason()
    _set_cache_step(
        receipt,
        "provider_lookup",
        status="bypass" if provider_bypass_reason is not None else "miss",
        reason=provider_bypass_reason,
        provider_id=provider_id,
        model=model,
        key=key,
    )
    cached = cache().get(key)
    if cached is not None:
        return _return_cached(
            provider_id=provider_id,
            model=model,
            prompt=cache_full_prompt,
            cached=cached,
            receipt=receipt,
            cache_step="provider_lookup",
            key=key,
        )

    # Path 3: shell out to a logged-in CLI. No API key needed.
    if model.startswith("claude-cli/"):
        out = _shell_out_claude(_inline_feedback(prompt, feedback), model.split("/", 1)[1])
        return _finalize_completion(
            key=key,
            out=out,
            provider_id=provider_id,
            model=model,
            prompt=cache_full_prompt,
            receipt=receipt,
        )
    if model.startswith("codex-cli/"):
        out = _shell_out_codex(_inline_feedback(prompt, feedback), model.split("/", 1)[1])
        return _finalize_completion(
            key=key,
            out=out,
            provider_id=provider_id,
            model=model,
            prompt=cache_full_prompt,
            receipt=receipt,
        )

    if not c["key"]:
        raise SystemExit(
            "set SIMPLICIO_API_KEY (or OPENROUTER_/ANTHROPIC_API_KEY). "
            "No key? Use SIMPLICIO_MODEL=claude-cli/<model> or codex-cli/<model> "
            "to shell out to your logged-in CLI instead (zero key)."
        )

    # Native Anthropic path: no base_url
    if not c["base"]:
        anthropic = _import_anthropic()

        cli = anthropic.Anthropic(api_key=c["key"])
        r = cli.messages.create(model=model, max_tokens=max_tokens, messages=_msgs(prompt, feedback))
        out = next((b.text for b in r.content if b.type == "text"), "")
        return _finalize_completion(
            key=key,
            out=out,
            provider_id=provider_id,
            model=model,
            prompt=cache_full_prompt,
            usage=_anthropic_usage(r),
            receipt=receipt,
        )

    # Any OpenAI-compatible endpoint (OpenRouter, GLM, DeepSeek, local...)
    out, usage = _openai_compatible_generate(model, c["base"], c["key"], prompt, feedback, max_tokens)
    return _finalize_completion(
        key=key,
        out=out,
        provider_id=provider_id,
        model=model,
        prompt=cache_full_prompt,
        usage=usage,
        receipt=receipt,
    )


def info():
    c = _cfg()
    if _is_default_local(c["model"], c["base"]):
        repo, fname, path = _local_spec(LOCAL_DEFAULT_MODEL)
        target = path or f"{repo}/{fname}"
        return (
            f"model={LOCAL_DEFAULT_MODEL} provider=local-llama "
            f"(in-process, llama-cpp-python) target={target} "
            "key=not-needed"
        )
    if _is_local(c["model"], c["base"]):
        eff_model = c["model"] or (LOCAL_MODEL_PREFIX + "default (auto)")
        repo, fname, path = _local_spec(c["model"] or "")
        target = path or f"{repo}/{fname}"
        return (
            f"model={eff_model} provider=local-llama "
            f"(in-process, llama-cpp-python) target={target} key=not-needed"
        )
    model = c["model"] or "(unset)"
    if model.startswith("claude-cli/"):
        return f"model={model} provider=claude-cli (shell-out, uses Claude Code OAuth) key=not-needed"
    if model.startswith("codex-cli/"):
        return f"model={model} provider=codex-cli (shell-out, uses Codex/ChatGPT login) key=not-needed"
    return f"model={model} base={c['base'] or 'anthropic-native'} key={'set' if c['key'] else 'MISSING'}"


# --------------------------------------------------------------------------- #
# Planner-grade provider (used by `simplicio-py scratch`).
#
# Kept SEPARATE from generate() so:
#   - users keep their cheap doer (SIMPLICIO_MODEL = Coder-Next, etc.)
#   - the planner runs on a frontier model (DeepSeek-V4-Pro default)
#   - swap of one does not touch the other
#
# Selected via SIMPLICIO_PLANNER:
#   deepseek/<model>      -> https://api.deepseek.com/v1, DEEPSEEK_API_KEY
#   anthropic/<model>     -> ANTHROPIC_API_KEY, native SDK
#   openai/<model>        -> https://api.openai.com/v1, OPENAI_API_KEY
#   openrouter/<model>    -> https://openrouter.ai/api/v1, OPENROUTER_API_KEY
#   claude-cli/<model>    -> shell-out, no key needed
#   codex-cli/<model>     -> shell-out, no key needed
#   <bare>                -> falls through to SIMPLICIO_MODEL/_API_KEY path
# --------------------------------------------------------------------------- #

_PLANNER_ROUTES = {
    # Default planner route: DeepSeek family served via HuggingFace Inference
    # Router. Uses HF_TOKEN; the model id after the prefix is whatever HF
    # exposes (e.g. `deepseek-ai/DeepSeek-V3.1`). Cheapest path to a frontier
    # planner when the user already has an HF account.
    "deepseek-hf": ("https://router.huggingface.co/v1", "HF_TOKEN"),
    # DeepSeek's own API (paid, no HF middleman). Pin via `deepseek/<model>`.
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    # Generic HF route for any non-DeepSeek model on the HF router (Qwen, Llama, ...).
    "hf": ("https://router.huggingface.co/v1", "HF_TOKEN"),
}

# Default planner. DeepSeek-V3.1 on HF is the current "frontier model with a
# token most users already have"; users on the DeepSeek Pro plan can swap to
# `deepseek/deepseek-v4-pro` (direct API) when they prefer. Override via
# SIMPLICIO_PLANNER.
_DEFAULT_PLANNER = "deepseek-hf/deepseek-ai/DeepSeek-V3.1"


def planner_cfg(require_key=True):
    """Resolve the planner provider config without touching the doer config.

    Returns a dict with keys: model, base, key, native_anthropic, shell_out.
    Raises SystemExit if planner is selected but its credentials are missing.
    """
    raw = os.environ.get("SIMPLICIO_PLANNER", _DEFAULT_PLANNER).strip()
    if not raw:
        raw = _DEFAULT_PLANNER

    if raw.startswith("claude-cli/") or raw.startswith("codex-cli/"):
        return {
            "model": raw,
            "base": None,
            "key": None,
            "native_anthropic": False,
            "shell_out": True,
        }

    if "/" in raw:
        prefix, name = raw.split("/", 1)
    else:
        prefix, name = "", raw

    if prefix == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key and require_key:
            raise SystemExit("SIMPLICIO_PLANNER=anthropic/* requires ANTHROPIC_API_KEY")
        return {
            "model": name,
            "base": None,
            "key": key,
            "native_anthropic": True,
            "shell_out": False,
        }

    if prefix in _PLANNER_ROUTES:
        base, env_key = _PLANNER_ROUTES[prefix]
        key = os.environ.get(env_key)
        if not key and require_key:
            raise SystemExit(f"SIMPLICIO_PLANNER={raw} requires {env_key}")
        return {
            "model": name,
            "base": base,
            "key": key,
            "native_anthropic": False,
            "shell_out": False,
        }

    # Bare model name — fall back to the same provider config the doer uses.
    # Lets the user run planner against whatever they already configured.
    c = _cfg()
    return {
        "model": raw,
        "base": c["base"],
        "key": c["key"],
        "native_anthropic": not c["base"],
        "shell_out": False,
    }


def _planner_provider_id(cfg):
    model = cfg["model"]
    if model.startswith(LOCAL_MODEL_PREFIX):
        return "planner:local-llama"
    if model.startswith("claude-cli/"):
        return "planner:claude-cli"
    if model.startswith("codex-cli/"):
        return "planner:codex-cli"
    if cfg["native_anthropic"]:
        return "planner:anthropic-native"
    if cfg["base"]:
        return f"planner:openai-compatible:{cfg['base'].rstrip('/')}"
    return "planner:unknown"


def _planner_cache_key(cfg, prompt, max_tokens, temperature, template_version):
    return make_key(
        _planner_provider_id(cfg),
        cfg["model"],
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        template_version=template_version,
    )


def planner_complete(prompt, max_tokens=8192, temperature=0.1, template_version=None):
    """Call the planner provider. Used by simplicio.scratch.planner.

    temperature defaults to 0.1 because plans must be reproducible and
    schema-stable, not creative.
    """
    p = planner_cfg(require_key=False)
    prompt = _apply_directives(prompt)
    key = _planner_cache_key(p, prompt, max_tokens, temperature, template_version)
    receipt = _new_cache_receipt(
        surface="planner_complete",
        requested_provider_id=_planner_provider_id(p),
        requested_model=p["model"],
    )
    exact_bypass_reason = _cache_bypass_reason()
    _set_cache_step(
        receipt,
        "local_exact_lookup",
        status="bypass" if exact_bypass_reason is not None else "miss",
        reason=exact_bypass_reason,
        provider_id=_planner_provider_id(p),
        model=p["model"],
        key=key,
    )
    cached = cache().get(key)
    if cached is not None:
        return _return_cached(
            provider_id=_planner_provider_id(p),
            model=p["model"],
            prompt=prompt,
            cached=cached,
            surface="planner_complete",
            receipt=receipt,
            cache_step="local_exact_lookup",
            key=key,
        )

    if p["shell_out"]:
        provider_id = _planner_provider_id(p)
        if p["model"].startswith("claude-cli/"):
            out = _shell_out_claude(prompt, p["model"].split("/", 1)[1])
            return _finalize_completion(
                key=key,
                out=out,
                provider_id=provider_id,
                model=p["model"],
                prompt=prompt,
                surface="planner_complete",
                receipt=receipt,
            )
        if p["model"].startswith("codex-cli/"):
            out = _shell_out_codex(prompt, p["model"].split("/", 1)[1])
            return _finalize_completion(
                key=key,
                out=out,
                provider_id=provider_id,
                model=p["model"],
                prompt=prompt,
                surface="planner_complete",
                receipt=receipt,
            )

    if p["model"].startswith(LOCAL_MODEL_PREFIX):
        out = _local_generate(prompt, None, p["model"], max_tokens)
        return _finalize_completion(
            key=key,
            out=out,
            provider_id="planner:local-llama",
            model=p["model"],
            prompt=prompt,
            surface="planner_complete",
            receipt=receipt,
        )

    if not p["key"]:
        raise SystemExit(
            "no planner credentials: set SIMPLICIO_PLANNER + matching API key "
            "(default planner is deepseek-hf/deepseek-ai/DeepSeek-V3.1 -> HF_TOKEN)"
        )

    if p["native_anthropic"]:
        anthropic = _import_anthropic()

        cli = anthropic.Anthropic(api_key=p["key"])
        r = cli.messages.create(
            model=p["model"],
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        out = next((b.text for b in r.content if b.type == "text"), "")
        return _finalize_completion(
            key=key,
            out=out,
            provider_id=_planner_provider_id(p),
            model=p["model"],
            prompt=prompt,
            usage=_anthropic_usage(r),
            surface="planner_complete",
            receipt=receipt,
        )

    OpenAI = _import_openai()

    cli = OpenAI(base_url=p["base"], api_key=p["key"])
    r = cli.chat.completions.create(
        model=p["model"],
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    out = r.choices[0].message.content
    return _finalize_completion(
        key=key,
        out=out,
        provider_id=_planner_provider_id(p),
        model=p["model"],
        prompt=prompt,
        usage=_openai_usage(r),
        surface="planner_complete",
        receipt=receipt,
    )


def planner_info():
    p = planner_cfg()
    if p["shell_out"]:
        return f"planner={p['model']} (shell-out)"
    if p["native_anthropic"]:
        return f"planner={p['model']} provider=anthropic-native key={'set' if p['key'] else 'MISSING'}"
    return f"planner={p['model']} base={p['base']} key={'set' if p['key'] else 'MISSING'}"
