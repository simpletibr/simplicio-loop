"""Real agent driver shared by BOTH A/B arms: the actual OpenCode CLI
(``opencode-ai``, npm), replacing the minimal Python tool-calling loop that
used to live in ``agent.py`` (deleted, issue #1325 -- AGENTS.md rule 1: no
backward-compat shims).

There is no per-arm branching in the OpenCode invocation itself. Both arms
run ``opencode run --model <model> --format json --auto --dir <repo>
<prompt>`` against their own fresh repo; the only differences between them
(``skill=True`` for the simplicio arm) are:

- the ``.claude/skills/simplicio-loop`` directory being present in the
  repo OpenCode is pointed at (OpenCode natively scans a repo's
  ``.claude/skills`` alongside its own ``.opencode/skills``, confirmed by
  inspecting the installed ``opencode`` binary -- see
  ``bench/llm_ab/STANDARD.md`` § OpenCode for how that was verified); and
- the user prompt being prefixed with ``/simplicio-loop ``.

OpenCode drives its own multi-turn tool-calling loop internally (this
module never talks to an LLM directly) and reports, per internal LLM step,
exact token/cost usage in its ``--format json`` event stream -- this module
only runs the process and parses that stream into the same per-task totals
shape the rest of the harness (``run.py``/``aggregate.py``/``report.py``/
``cost.py``) already consumes.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request  # noqa: F401 -- re-exposed as oc.urllib.request for tests to monkeypatch urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import llm_client as lc  # noqa: E402
import measure  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
SKILL_SRC = os.path.join(REPO_ROOT, ".claude", "skills", "simplicio-loop")

TAIL_CHARS = 8000
SIMPLICIO_PREFIX = "simplicio-"

OPENCODE_PROVIDER = "openrouter"
OPENCODE_MODEL = f"{OPENCODE_PROVIDER}/{lc.MODEL}"
OPENCODE_BIN_ENV = "SIMPLICIO_BENCH_OPENCODE_BIN"
DEFAULT_RUN_TIMEOUT = 900  # generous: OpenCode's first invocation against a
# fresh HOME/data dir can take minutes to cold-start its local index/db;
# later invocations against the same config_dir are fast (seconds).

KEY_URL = "https://openrouter.ai/api/v1/key"
DEFAULT_POLL_TIMEOUT_S = 20
DEFAULT_POLL_INTERVAL_S = 2.0


def opencode_bin() -> str:
    """Resolve the ``opencode`` binary: ``SIMPLICIO_BENCH_OPENCODE_BIN`` env
    var first (OpenCode is installed OUTSIDE this repo, see STANDARD.md), a
    ``PATH`` lookup second. Fails loudly (never silently falls back to some
    other binary) when neither resolves."""
    path = os.environ.get(OPENCODE_BIN_ENV, "").strip()
    if path:
        return path
    found = shutil.which("opencode")
    if found:
        return found
    raise RuntimeError(
        f"{OPENCODE_BIN_ENV} is not set and 'opencode' is not on PATH -- install it "
        "outside this repo (e.g. npm install --prefix <dir> opencode-ai) and set "
        f"{OPENCODE_BIN_ENV}=<dir>/node_modules/.bin/opencode."
    )


def truncate_tail(text: str | None, limit: int = TAIL_CHARS) -> str:
    """Keep only the LAST ``limit`` characters of ``text`` (ported from the
    retired ``agent.py``; ``None`` becomes the empty string)."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[-limit:]


def classify_command(command: str | None) -> bool:
    """True iff any token in ``command`` (including after ``cd x &&``, ``;``
    or ``|``) runs a simplicio-loop/mapper/dev-cli/fast binary (ported from
    the retired ``agent.py``)."""
    if not command:
        return False
    stripped = command.strip()
    if not stripped:
        return False
    for token in re.split(r"[\s;&|()]+", stripped):
        if token.rsplit("/", 1)[-1].startswith(SIMPLICIO_PREFIX):
            return True
    return False


def build_prompt(arm: str, task_text: str) -> str:
    """``normal``: the task text unchanged. ``simplicio``: prefixed with
    ``/simplicio-loop `` -- OpenCode's own slash-command convention for
    invoking a skill by name, exactly like a human driving it interactively."""
    if arm == "simplicio":
        return "/simplicio-loop " + task_text
    return task_text


def install_skill(repo_dir: str, skill_src: str = SKILL_SRC) -> str:
    """Copy ``.claude/skills/simplicio-loop`` into ``repo_dir`` -- OpenCode's
    default-scanned Claude Code skill location (confirmed by inspecting the
    installed ``opencode`` binary: it scans a repo's ``.claude/skills`` by
    default unless ``OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1`` is set, in
    addition to its own native ``.opencode/skills``). Idempotent: a second
    call is a no-op (returns the same path) rather than raising on an
    existing destination."""
    dst = os.path.join(repo_dir, ".claude", "skills", "simplicio-loop")
    if os.path.isdir(dst):
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copytree(skill_src, dst)
    return dst


def build_env(arm: str, key: str, config_dir: str, base_env: dict | None = None,
              extra_path: str | None = None) -> dict:
    """The child process environment for one ``opencode run`` invocation.

    The OpenRouter key reaches OpenCode ONLY via ``OPENROUTER_API_KEY`` in
    this environment -- never as a CLI argument (so it never appears in a
    process listing or in ``opencode run``'s own printed command).
    ``config_dir`` becomes ``HOME``/``XDG_CONFIG_HOME``/``XDG_DATA_HOME``, so
    OpenCode's own state (sessions, skill scan, snapshot db) lives in a
    per-arm scratch directory instead of the real ``~`` -- confirmed
    necessary by probing ``scripts/install_lib.py``'s ``copy_skills_opencode``/
    ``merge_opencode_mcp``, which read ``HOME`` directly (not
    ``XDG_CONFIG_HOME``) and otherwise write into the real home directory.

    ``extra_path`` (default: the venv ``bin/`` holding
    ``simplicio-loop``/``simplicio-mapper``/``simplicio-dev-cli``/
    ``simplicio-fast``, i.e. ``dirname(sys.executable)``) is prepended to
    ``PATH`` so the simplicio arm's bash tool calls can actually invoke
    those binaries -- same convention as the retired ``agent.py``.
    """
    env = dict(base_env if base_env is not None else os.environ)
    env["OPENROUTER_API_KEY"] = key
    env["HOME"] = config_dir
    env["XDG_CONFIG_HOME"] = os.path.join(config_dir, ".config")
    env["XDG_DATA_HOME"] = os.path.join(config_dir, ".local", "share")
    path_prefix = extra_path if extra_path is not None else os.path.dirname(os.path.abspath(sys.executable))
    env["PATH"] = path_prefix + os.pathsep + env.get("PATH", "")
    return env


def build_command(bin_path: str, repo_dir: str, prompt: str, model: str = OPENCODE_MODEL) -> list[str]:
    """The argv for one ``opencode run`` invocation. ``--auto`` auto-approves
    bash/edit permissions non-interactively (there is no human to click
    "allow"); ``--format json`` is the raw JSON event stream this module
    parses; the key is never part of this argv (see ``build_env``)."""
    return [bin_path, "run", "--model", model, "--format", "json", "--auto", "--dir", repo_dir, prompt]


def parse_run_events(events: list[dict]) -> dict:
    """Parse ``opencode run --format json``'s event stream into
    ``{"turns", "llm_calls", "commands", "final_text"}``.

    One OpenCode ``step-finish`` event is one LLM call (``turns`` == the
    number of them). Token accounting per OpenCode's own schema:
    ``tokens.input``/``tokens.output``/``tokens.reasoning`` and
    ``tokens.cache.{read,write}`` are DISJOINT (they sum to
    ``tokens.total``), so this harness's ``prompt_tokens`` (total prompt,
    matching the OpenRouter-native meaning the rest of the pipeline already
    uses) is ``input + cache.read + cache.write``, and ``completion_tokens``
    (total completion, reasoning included) is ``output + reasoning``.
    ``part.cost`` is OpenCode's own reported cost for that one step --
    already the real per-call cost including any cache discount.

    A ``tool`` part with ``tool == "bash"`` is one bash-tool command; its
    ``turn`` is the LLM call that is still open when the tool ran (i.e. the
    step whose ``step-finish`` has not yet been seen), so ``len(llm_calls) +
    1`` at the time the event is processed. Unknown event types are ignored
    (forward-compatible with new OpenCode event kinds).
    """
    llm_calls: list[dict] = []
    commands: list[dict] = []
    final_text: str | None = None
    step_start_ts: dict[str, float] = {}

    for ev in events:
        etype = ev.get("type")
        part = ev.get("part") or {}

        if etype == "step_start":
            mid = part.get("messageID")
            if mid is not None:
                step_start_ts[mid] = ev.get("timestamp")

        elif etype == "text":
            text = part.get("text")
            if text:
                final_text = text

        elif etype == "tool_use" and part.get("tool") == "bash":
            state = part.get("state") or {}
            input_ = state.get("input") or {}
            command = input_.get("command") or ""
            meta = state.get("metadata") or {}
            time_info = state.get("time") or {}
            start_ms, end_ms = time_info.get("start"), time_info.get("end")
            wall_s = (
                round((end_ms - start_ms) / 1000.0, 4)
                if isinstance(start_ms, (int, float)) and isinstance(end_ms, (int, float))
                else None
            )
            output = state.get("output")
            if not output:
                output = meta.get("output") or ""
            commands.append({
                "turn": len(llm_calls) + 1,
                "command": command,
                "returncode": meta.get("exit"),
                "wall_s": wall_s,
                "cpu_s": None,
                "peak_rss_mb": None,
                "is_simplicio": classify_command(command),
                "output_bytes": len(output or ""),
                "output_tail": truncate_tail(output),
            })

        elif etype == "step_finish":
            mid = part.get("messageID")
            tokens = part.get("tokens") or {}
            cache = tokens.get("cache") or {}
            input_tok = tokens.get("input") or 0
            output_tok = tokens.get("output") or 0
            reasoning_tok = tokens.get("reasoning") or 0
            cache_read = cache.get("read") or 0
            cache_write = cache.get("write") or 0
            start_ts = step_start_ts.get(mid)
            end_ts = ev.get("timestamp")
            latency_s = (
                round((end_ts - start_ts) / 1000.0, 4)
                if isinstance(start_ts, (int, float)) and isinstance(end_ts, (int, float))
                else None
            )
            llm_calls.append({
                "turn": len(llm_calls) + 1,
                "ok": True,
                "id": mid,
                "latency_s": latency_s,
                "prompt_tokens": input_tok + cache_read + cache_write,
                "completion_tokens": output_tok + reasoning_tok,
                "reasoning_tokens": reasoning_tok,
                "cached_tokens": cache_read,
                "cost_usd": part.get("cost"),
                "finish_reason": part.get("reason"),
                "error": None,
                "reasoning_effort": None,  # OpenCode does not expose per-call effort control
            })

    return {
        "turns": len(llm_calls),
        "llm_calls": llm_calls,
        "commands": commands,
        "final_text": final_text,
    }


def summarize(llm_calls: list[dict], commands: list[dict]) -> dict:
    """Same shape as the retired ``agent.summarize``, plus ``cost_source``/
    ``cost_usd_opencode_reported`` (issue #1325's real-billed-cost
    breakdown). ``cost_usd`` starts as the sum of OpenCode's own per-call
    reported cost; ``run_opencode`` overwrites it with the real OpenRouter
    key-usage delta when that delta was observed (see ``poll_billed_delta``)."""
    prompt = completion = reasoning = cached = 0
    cost = 0.0
    llm_latency = 0.0
    for call in llm_calls:
        if not call.get("ok"):
            continue
        prompt += call.get("prompt_tokens") or 0
        completion += call.get("completion_tokens") or 0
        reasoning += call.get("reasoning_tokens") or 0
        cached += call.get("cached_tokens") or 0
        cost += call.get("cost_usd") or 0
        llm_latency += call.get("latency_s") or 0

    cmd_wall = 0.0
    n_simplicio = 0
    for cmd in commands:
        cmd_wall += cmd.get("wall_s") or 0
        if cmd.get("is_simplicio"):
            n_simplicio += 1

    reported_cost = round(cost, 6)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "cached_tokens": cached,
        "cost_usd": reported_cost,
        "cost_usd_opencode_reported": reported_cost,
        "cost_source": "opencode-reported",
        "llm_latency_s": round(llm_latency, 4),
        "cmd_wall_s": round(cmd_wall, 4),
        "cmd_cpu_s": 0.0,  # not measurable per-command through the opencode CLI (see README)
        "n_commands": len(commands),
        "n_simplicio_commands": n_simplicio,
    }


def fetch_key_usage_usd(key: str, timeout: int = 15) -> float | None:
    """``GET /api/v1/key``'s cumulative ``data.usage`` (USD) for ``key``, or
    ``None`` on any failure (bad status, malformed body, network error) --
    never a fabricated number."""
    status, parsed, _raw = lc.fetch_json(KEY_URL, key=key, timeout=timeout)
    if status != 200 or not isinstance(parsed, dict):
        return None
    data = parsed.get("data") or {}
    usage = data.get("usage")
    return float(usage) if isinstance(usage, (int, float)) else None


def poll_billed_delta(fetch_fn, usage_before: float | None, *, timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
                       interval_s: float = DEFAULT_POLL_INTERVAL_S, sleep=time.sleep,
                       clock_values: list[float] | None = None) -> float | None:
    """Poll ``fetch_fn()`` (no-arg -> ``float | None`` usage) until it rises
    above ``usage_before`` by more than float noise, up to ``timeout_s``
    seconds, sleeping ``interval_s`` between attempts. Returns the observed
    delta, or ``None`` when there was no baseline to compare against or the
    usage never moved within the window (OpenRouter's ledger can lag; the
    caller falls back to OpenCode's own reported cost in that case, marking
    ``cost_source`` accordingly -- never a fabricated number).

    ``clock_values`` (test-only): an explicit sequence consumed instead of
    real ``time.time()`` calls, one per loop condition check, so the timeout
    loop is deterministic under test without any real waiting.
    """
    if usage_before is None:
        return None
    if clock_values is not None:
        ticks = iter(clock_values)

        def now():
            try:
                return next(ticks)
            except StopIteration:
                return usage_before + timeout_s + 1  # force loop exit
    else:
        now = time.time

    start = now()
    deadline = start + timeout_s
    while now() < deadline:
        sleep(interval_s)
        usage_after = fetch_fn()
        if usage_after is not None and usage_after > usage_before + 1e-9:
            return round(usage_after - usage_before, 8)
    return None


def run_opencode(arm: str, prompt: str, repo_dir: str, *, key: str | None = None,
                  config_dir: str, timeout: int = DEFAULT_RUN_TIMEOUT, skill: bool = False,
                  bin_path: str | None = None, extra_path: str | None = None) -> dict:
    """Drive one task to completion via the real OpenCode CLI in ``repo_dir``.

    ``skill=True`` (the simplicio arm): installs ``.claude/skills/
    simplicio-loop`` into ``repo_dir`` (idempotent) and prefixes the prompt
    with ``/simplicio-loop ``. ``skill=False`` (the normal arm): the prompt
    is sent unchanged and no skill directory is added.

    Real billed cost: ``GET /api/v1/key``'s usage is read before and after
    the run with this arm's own key, and the resulting delta becomes
    ``totals["cost_usd"]`` (``cost_source="billed-delta"``) when observed;
    otherwise ``totals["cost_usd"]`` stays OpenCode's own reported cost sum
    (``cost_source="opencode-reported"``) -- see ``poll_billed_delta``.

    Returns the same shape ``run.py`` already consumes from the retired
    ``agent.run_agent``: ``{"turns", "llm_calls", "commands", "final_text",
    "totals"}``.
    """
    key = key if key is not None else lc.get_key(arm)
    bin_path = bin_path or opencode_bin()
    os.makedirs(config_dir, exist_ok=True)

    full_prompt = prompt
    if skill:
        install_skill(repo_dir)
        full_prompt = build_prompt(arm, prompt)

    env = build_env(arm, key, config_dir, extra_path=extra_path)
    cmd = build_command(bin_path, repo_dir, full_prompt)

    usage_before = fetch_key_usage_usd(key)
    out, metrics = measure.run_subprocess(cmd, cwd=repo_dir, timeout=timeout, env=env)

    if metrics.get("returncode") != 0:
        return {
            "turns": 0,
            "llm_calls": [{
                "ok": False, "id": None, "error": f"opencode exited {metrics.get('returncode')}",
                "prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0,
                "cached_tokens": 0, "cost_usd": 0.0, "finish_reason": None, "reasoning_effort": None,
            }],
            "commands": [],
            "final_text": None,
            "totals": summarize([], []),
            "raw_output_tail": truncate_tail(out),
        }

    events: list[dict] = []
    for line in (out or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except (ValueError, TypeError):
            continue

    parsed = parse_run_events(events)
    totals = summarize(parsed["llm_calls"], parsed["commands"])

    billed_delta = poll_billed_delta(lambda: fetch_key_usage_usd(key), usage_before)
    if billed_delta is not None:
        totals["cost_usd"] = billed_delta
        totals["cost_source"] = "billed-delta"

    return {
        "turns": parsed["turns"],
        "llm_calls": parsed["llm_calls"],
        "commands": parsed["commands"],
        "final_text": parsed["final_text"],
        "totals": totals,
    }
