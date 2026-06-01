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

4. In-process local inference via llama-cpp-python (offline-first, zero key)
     SIMPLICIO_MODEL=local-llama/<repo>::<file.gguf>   -> explicit HF GGUF
     SIMPLICIO_MODEL=local-llama/default               -> bundled default
     SIMPLICIO_MODEL=local-llama//abs/path/model.gguf  -> direct local path
     This is also the DEFAULT when neither SIMPLICIO_MODEL nor
     SIMPLICIO_BASE_URL is set: simplicio runs Qwen3.5-2B Q6_K GGUF on CPU with
     no HTTP overhead. Legacy Qwen2.5-Coder GGUFs remain fallback executors. The
     GGUF is reused from ~/.simplicio/models/executor when present, otherwise
     fetched once from the Hugging Face Hub. Requires the `local` extra:
     pip install 'simplicio-cli[local]'.
"""

import os
import shutil
from pathlib import Path

from ._cache import CacheEntry, cache, make_key


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
# Path 4: in-process local inference (llama-cpp-python). Offline-first default.
# --------------------------------------------------------------------------- #

# Qwen3.5-2B Q6_K is the preferred local executor. The previous Qwen2.5-Coder
# files stay in the automatic fallback chain so existing offline setups keep
# working if the new GGUF is not present yet.
LOCAL_DEFAULT_REPO = "bartowski/Qwen_Qwen3.5-2B-GGUF"
LOCAL_DEFAULT_FILE = "Qwen3.5-2B-Q6_K.gguf"
LOCAL_FALLBACK_REPO = "bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF"
LOCAL_FALLBACK_FILE = "Qwen2.5-Coder-1.5B-Instruct-Q8_0.gguf"
LOCAL_SECONDARY_FALLBACK_FILE = "Qwen2.5-Coder-1.5B-Instruct-Q6_K_L.gguf"
LOCAL_FALLBACK_SPECS = (
    (LOCAL_FALLBACK_REPO, LOCAL_FALLBACK_FILE),
    (LOCAL_FALLBACK_REPO, LOCAL_SECONDARY_FALLBACK_FILE),
)
LOCAL_EXECUTOR_DIR = "~/.simplicio/models/executor"
LOCAL_MODEL_PREFIX = "local-llama/"

# Loaded Llama instances, keyed by (gguf_path, n_ctx, n_threads, n_gpu_layers).
# A model load is expensive (weights -> RAM), so we keep it for the process.
_LOCAL_LLAMA_CACHE = {}


def _is_local(model, base):
    """True when generate() should route to the in-process llama backend.

    Either an explicit `local-llama/` model, or the offline-first default:
    nothing configured at all (no model, no OpenAI-compatible base_url).
    """
    if model and model.startswith(LOCAL_MODEL_PREFIX):
        return True
    return not model and not base


def _local_spec(model):
    """Resolve (repo, file, path) for a local-llama model id.

    Forms after the `local-llama/` prefix:
      "" / "default" / "auto"   -> bundled Qwen3.5-2B Q6_K default
      "<repo>::<file.gguf>"     -> explicit HF repo + filename
      "/abs/path/model.gguf"    -> direct local path (no download)
      "<repo>"                  -> HF repo + default/SIMPLICIO_LOCAL_MODEL_FILE
    SIMPLICIO_LOCAL_MODEL_PATH always wins when set.
    """
    path = os.environ.get("SIMPLICIO_LOCAL_MODEL_PATH")
    if path:
        return None, None, path
    file_env = os.environ.get("SIMPLICIO_LOCAL_MODEL_FILE", LOCAL_DEFAULT_FILE)
    spec = ""
    if model and model.startswith(LOCAL_MODEL_PREFIX):
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


def _local_candidates(repo, fname):
    """Return candidate (repo, GGUF filename) pairs in preference order."""
    if os.environ.get("SIMPLICIO_LOCAL_MODEL_FILE"):
        return [(repo, fname)]
    if repo == LOCAL_DEFAULT_REPO and fname == LOCAL_DEFAULT_FILE:
        return [(repo, fname), *LOCAL_FALLBACK_SPECS]
    return [(repo, fname)]


def _resolve_local_path(repo, fname, path):
    """Return a filesystem path to the GGUF, downloading from HF if needed."""
    if path:
        if not os.path.exists(path):
            raise SystemExit(
                f"simplicio: local model not found at {path}. Point "
                "SIMPLICIO_LOCAL_MODEL_PATH at an existing .gguf file."
            )
        return path
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise SystemExit(
            "simplicio: local backend needs huggingface-hub. "
            "Install extras: pip install 'simplicio-cli[local]'"
        )
    errors = []
    for candidate_repo, candidate_file in _local_candidates(repo, fname):
        local_file = _local_executor_dir() / candidate_file
        if local_file.is_file():
            return str(local_file)
        try:
            return hf_hub_download(repo_id=candidate_repo, filename=candidate_file)
        except Exception as exc:  # noqa: BLE001 - fallback to the next local GGUF
            errors.append(f"{candidate_repo}/{candidate_file}: {exc}")
    detail = "; ".join(errors) if errors else f"{fname}: unavailable"
    raise SystemExit(f"simplicio: local model download failed ({detail})")


def _local_llama(model):
    """Load (or reuse) the Llama instance for the given local model id."""
    try:
        from llama_cpp import Llama
    except ImportError:
        raise SystemExit(
            "simplicio: local backend needs llama-cpp-python. "
            "Install extras: pip install 'simplicio-cli[local]'"
        )
    repo, fname, path = _local_spec(model)
    gguf = _resolve_local_path(repo, fname, path)
    n_ctx = int(os.environ.get("SIMPLICIO_LOCAL_CTX", "8192"))
    threads = os.environ.get("SIMPLICIO_LOCAL_THREADS")
    n_threads = int(threads) if threads else None
    n_gpu_layers = int(os.environ.get("SIMPLICIO_LOCAL_GPU_LAYERS", "0"))
    cache_key = (gguf, n_ctx, n_threads, n_gpu_layers)
    llm = _LOCAL_LLAMA_CACHE.get(cache_key)
    if llm is None:
        llm = Llama(
            model_path=gguf,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )
        _LOCAL_LLAMA_CACHE[cache_key] = llm
    return llm


def _local_generate(prompt, feedback, model, max_tokens):
    """Generate a completion in-process via llama-cpp-python."""
    llm = _local_llama(model)
    cap = os.environ.get("SIMPLICIO_LOCAL_MAX_TOKENS")
    out_tokens = int(cap) if cap else max_tokens
    temperature = float(os.environ.get("SIMPLICIO_LOCAL_TEMP", "0.1"))
    r = llm.create_chat_completion(
        messages=_msgs(prompt, feedback),
        max_tokens=out_tokens,
        temperature=temperature,
    )
    return r["choices"][0]["message"]["content"] or ""


def _provider_id(model, base):
    if model and model.startswith(LOCAL_MODEL_PREFIX):
        return "local-llama"
    if model.startswith("claude-cli/"):
        return "claude-cli"
    if model.startswith("codex-cli/"):
        return "codex-cli"
    if base:
        return f"openai-compatible:{base.rstrip('/')}"
    return "anthropic-native"


def _shell_out(cmd, label, stdin_text=None):
    """Run a subprocess that uses an OAuth session instead of an API key.

    SIMPLICIO_HOOK_GUARD=1 + SIMPLICIO_SKIP_AUTO_INIT=1 are injected so the
    inner CLI does not recursively fire simplicio's UserPromptSubmit hook nor
    re-run the first-run bootstrap.
    """
    import subprocess

    env = {**os.environ, "SIMPLICIO_HOOK_GUARD": "1", "SIMPLICIO_SKIP_AUTO_INIT": "1"}
    try:
        result = subprocess.run(
            cmd,
            env=env,
            input=stdin_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
    except FileNotFoundError:
        raise SystemExit(
            f"simplicio: `{cmd[0]}` CLI not on PATH. "
            f"Install {label} first, then re-run."
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(f"simplicio: {label} timed out (>600s)")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise SystemExit(
            f"simplicio: {label} failed (exit {result.returncode}): {stderr[:500]}"
        )
    return result.stdout


def _cli_command(name):
    if os.name != "nt":
        return name
    for candidate in (f"{name}.cmd", f"{name}.exe", name):
        if shutil.which(candidate):
            return candidate
    return name


def _shell_out_claude(prompt, model):
    cmd = [_cli_command("claude"), "-p", prompt]
    if model and model not in ("default", "auto"):
        cmd += ["--model", model]
    return _shell_out(cmd, "Claude Code CLI (`claude -p`)")


def _shell_out_codex(prompt, model):
    cmd = [_cli_command("codex"), "exec"]
    cmd.append("--skip-git-repo-check")
    if model and model not in ("default", "auto"):
        cmd += ["--model", model]
    cmd.append("-")
    return _shell_out(cmd, "Codex CLI (`codex exec`)", stdin_text=prompt)


def _charge_if_budgeted(model, prompt, out):
    from .orchestrator.cost_governor import charge_provider_call

    charge_provider_call(model, prompt, out or "")


def generate(prompt, feedback=None, max_tokens=4000, template_version=None):
    # Cache lookup BEFORE provider config. Key uses just SIMPLICIO_MODEL
    # (no credential check) so a hit returns without requiring an API key
    # to be set in the environment.
    from ._cache import cache, make_key, CacheEntry
    model_name = os.environ.get("SIMPLICIO_MODEL", "").strip()
    cache_full_prompt = _inline_feedback(prompt, feedback)
    cache_key = make_key(
        provider_id="doer", model=model_name, prompt=cache_full_prompt,
        max_tokens=max_tokens,
        template_version=template_version,
    )
    cached = cache().get(cache_key)
    if cached is not None:
        return cached.completion

    c = _cfg()
    model = c["model"]

    # Path 4: in-process local inference. Explicit `local-llama/` model, or the
    # offline-first default when nothing is configured. No API key, no HTTP.
    if _is_local(model, c["base"]):
        eff_model = model or (LOCAL_MODEL_PREFIX + "default")
        # Fold the resolved weights into the cache key: two different GGUFs can
        # both route as `local-llama/default` (via SIMPLICIO_LOCAL_MODEL_PATH /
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
        cached = cache().get(key)
        if cached is not None:
            return cached.completion
        out = _local_generate(prompt, feedback, eff_model, max_tokens)
        _charge_if_budgeted(eff_model, cache_full_prompt, out)
        cache().put(key, CacheEntry(out, provider_id="local-llama", model=eff_model))
        return out

    if not model:
        raise SystemExit(
            "set SIMPLICIO_MODEL (e.g. anthropic/claude-opus-4, claude-cli/sonnet, "
            "codex-cli/gpt-5, local-llama/default, glm-4.6, llama3, claude-opus-4-7)"
        )
    provider_id = _provider_id(model, c["base"])
    key = make_key(
        provider_id,
        model,
        prompt,
        feedback=feedback,
        max_tokens=max_tokens,
    )
    cached = cache().get(key)
    if cached is not None:
        return cached.completion

    # Path 3: shell out to a logged-in CLI. No API key needed.
    if model.startswith("claude-cli/"):
        out = _shell_out_claude(
            _inline_feedback(prompt, feedback), model.split("/", 1)[1]
        )
        _charge_if_budgeted(model, cache_full_prompt, out)
        cache().put(key, CacheEntry(out, provider_id=provider_id, model=model))
        return out
    if model.startswith("codex-cli/"):
        out = _shell_out_codex(
            _inline_feedback(prompt, feedback), model.split("/", 1)[1]
        )
        _charge_if_budgeted(model, cache_full_prompt, out)
        cache().put(key, CacheEntry(out, provider_id=provider_id, model=model))
        return out

    if not c["key"]:
        raise SystemExit(
            "set SIMPLICIO_API_KEY (or OPENROUTER_/ANTHROPIC_API_KEY). "
            "No key? Use SIMPLICIO_MODEL=claude-cli/<model> or codex-cli/<model> "
            "to shell out to your logged-in CLI instead (zero key)."
        )

    # Native Anthropic path: no base_url
    if not c["base"]:
        import anthropic

        cli = anthropic.Anthropic(api_key=c["key"])
        r = cli.messages.create(
            model=model, max_tokens=max_tokens, messages=_msgs(prompt, feedback)
        )
        out = next((b.text for b in r.content if b.type == "text"), "")
        _charge_if_budgeted(model, cache_full_prompt, out)
        cache().put(key, CacheEntry(out, provider_id=provider_id, model=model))
        return out

    # Any OpenAI-compatible endpoint (OpenRouter, GLM, DeepSeek, local...)
    from openai import OpenAI

    cli = OpenAI(base_url=c["base"], api_key=c["key"])
    r = cli.chat.completions.create(
        model=model, max_tokens=max_tokens, messages=_msgs(prompt, feedback)
    )
    out = r.choices[0].message.content
    _charge_if_budgeted(model, cache_full_prompt, out)
    cache().put(key, CacheEntry(out, provider_id=provider_id, model=model))
    return out


def info():
    c = _cfg()
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
    return (
        f"model={model} base={c['base'] or 'anthropic-native'} "
        f"key={'set' if c['key'] else 'MISSING'}"
    )


# --------------------------------------------------------------------------- #
# Planner-grade provider (used by `simplicio scratch`).
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
    key = _planner_cache_key(p, prompt, max_tokens, temperature, template_version)
    cached = cache().get(key)
    if cached is not None:
        return cached.completion

    if p["shell_out"]:
        provider_id = _planner_provider_id(p)
        if p["model"].startswith("claude-cli/"):
            out = _shell_out_claude(prompt, p["model"].split("/", 1)[1])
            _charge_if_budgeted(p["model"], prompt, out)
            cache().put(
                key,
                CacheEntry(out, provider_id=provider_id, model=p["model"]),
            )
            return out
        if p["model"].startswith("codex-cli/"):
            out = _shell_out_codex(prompt, p["model"].split("/", 1)[1])
            _charge_if_budgeted(p["model"], prompt, out)
            cache().put(
                key,
                CacheEntry(out, provider_id=provider_id, model=p["model"]),
            )
            return out

    if p["model"].startswith(LOCAL_MODEL_PREFIX):
        out = _local_generate(prompt, None, p["model"], max_tokens)
        _charge_if_budgeted(p["model"], prompt, out)
        cache().put(
            key,
            CacheEntry(out, provider_id="planner:local-llama", model=p["model"]),
        )
        return out

    if not p["key"]:
        raise SystemExit(
            "no planner credentials: set SIMPLICIO_PLANNER + matching API key "
            "(default planner is deepseek-hf/deepseek-ai/DeepSeek-V3.1 -> HF_TOKEN)"
        )

    if p["native_anthropic"]:
        import anthropic

        cli = anthropic.Anthropic(api_key=p["key"])
        r = cli.messages.create(
            model=p["model"],
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        out = next((b.text for b in r.content if b.type == "text"), "")
        _charge_if_budgeted(p["model"], prompt, out)
        cache().put(
            key,
            CacheEntry(out, provider_id=_planner_provider_id(p), model=p["model"]),
        )
        return out

    from openai import OpenAI

    cli = OpenAI(base_url=p["base"], api_key=p["key"])
    r = cli.chat.completions.create(
        model=p["model"],
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    out = r.choices[0].message.content
    _charge_if_budgeted(p["model"], prompt, out)
    cache().put(
        key,
        CacheEntry(out, provider_id=_planner_provider_id(p), model=p["model"]),
    )
    return out


def planner_info():
    p = planner_cfg()
    if p["shell_out"]:
        return f"planner={p['model']} (shell-out)"
    if p["native_anthropic"]:
        return f"planner={p['model']} provider=anthropic-native key={'set' if p['key'] else 'MISSING'}"
    return (
        f"planner={p['model']} base={p['base']} key={'set' if p['key'] else 'MISSING'}"
    )
