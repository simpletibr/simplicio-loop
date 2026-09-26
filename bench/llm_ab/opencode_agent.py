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
import tempfile
import time
import urllib.error
import urllib.request  # noqa: F401 -- re-exposed as oc.urllib.request for tests to monkeypatch urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import llm_client as lc  # noqa: E402
import measure  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
SKILLS_ROOT = os.path.join(REPO_ROOT, ".claude", "skills")
SKILL_SRC = os.path.join(SKILLS_ROOT, "simplicio-loop")

# Fixed system dirs appended after an arm's shim (issue #1337 ablation
# benchmark): Node (OpenCode itself needs it) plus the base POSIX toolchain
# (python3, git, sh, ...). Deliberately excludes the venv `bin/` AND
# `/usr/local/bin` -- both also hold `simplicio-*` binaries system-wide, so
# either would silently defeat the per-arm isolation this module builds.
SYSTEM_PATH_DIRS = ("/opt/node22/bin", "/usr/bin", "/bin")

TAIL_CHARS = 8000
SIMPLICIO_PREFIX = "simplicio-"

OPENCODE_PROVIDER = "openrouter"
OPENCODE_MODEL = f"{OPENCODE_PROVIDER}/{lc.MODEL}"
OPENCODE_BIN_ENV = "SIMPLICIO_BENCH_OPENCODE_BIN"
DEFAULT_RUN_TIMEOUT = 900  # generous: OpenCode's first invocation against a
# fresh HOME/data dir can take minutes to cold-start its local index/db;
# later invocations against the same config_dir are fast (seconds).

KEY_URL = "https://openrouter.ai/api/v1/key"

# Settled-usage polling (issue #1335): OpenRouter's key-usage ledger settles
# in several increments after a run finishes, not in one jump -- returning
# on the FIRST observed movement (the old `poll_billed_delta`, removed)
# undercounts the task that just ran and leaks the rest of its cost into the
# next task's "before" baseline. Instead, poll until the usage has been
# UNCHANGED for `reads` consecutive reads, bounded by `max_wait_s` total.
DEFAULT_SETTLE_READS = 3
DEFAULT_SETTLE_INTERVAL_S = 5.0
DEFAULT_SETTLE_MAX_WAIT_S = 120.0


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


def install_skills(repo_dir: str, skill_names: list[str], skills_root: str = SKILLS_ROOT) -> list[str]:
    """Generalization of ``install_skill`` for the ablation benchmark's
    single/pair arms (issue #1337): copy each of ``skill_names`` from
    ``skills_root/<name>`` into ``repo_dir/.claude/skills/<name>``.
    Idempotent per skill, same as ``install_skill``. An empty list is a
    no-op (never even creates ``.claude/``), returning ``[]``."""
    installed: list[str] = []
    for name in skill_names:
        src = os.path.join(skills_root, name)
        dst = os.path.join(repo_dir, ".claude", "skills", name)
        if not os.path.isdir(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copytree(src, dst)
        installed.append(dst)
    return installed


def build_shim_dir(bins: list[str], venv_bin: str | None = None) -> str:
    """A fresh temp dir holding a symlink for each of ``bins`` that actually
    exists in ``venv_bin`` (default: ``dirname(sys.executable)``, i.e. the
    venv/interpreter's own ``bin/`` where the editable-installed
    ``simplicio-*`` console scripts live) -- never anywhere else, so a
    binary this arm was not granted can never be resolved through this
    shim. A name not found in ``venv_bin`` is silently skipped (never
    fabricates a broken symlink)."""
    venv_bin = venv_bin or os.path.dirname(os.path.abspath(sys.executable))
    shim_dir = tempfile.mkdtemp(prefix="llm-ab-shim-")
    for name in bins:
        src = os.path.join(venv_bin, name)
        if os.path.isfile(src) or os.path.islink(src):
            os.symlink(src, os.path.join(shim_dir, name))
    return shim_dir


def build_arm_path(bins: list[str], venv_bin: str | None = None) -> str:
    """The full, REPLACEMENT ``PATH`` for one ablation arm (issue #1337):
    a fresh shim (see ``build_shim_dir``) holding only ``bins``, followed
    by ``SYSTEM_PATH_DIRS`` -- deliberately NOT the inherited process
    ``PATH`` (which would still carry the venv ``bin/`` and
    ``/usr/local/bin``, both of which also expose every ``simplicio-*``
    binary system-wide and would defeat the isolation). Pass this as
    ``run_opencode(..., isolated_path=...)``."""
    shim = build_shim_dir(bins, venv_bin=venv_bin)
    return os.pathsep.join([shim, *SYSTEM_PATH_DIRS])


def build_env(arm: str, key: str, config_dir: str, base_env: dict | None = None,
              extra_path: str | None = None, isolated_path: str | None = None) -> dict:
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

    ``isolated_path`` (issue #1337 ablation arms), when given, REPLACES
    ``PATH`` outright instead of prepending to the inherited one -- build it
    with ``build_arm_path`` so an arm's PATH holds only its allowed
    ``simplicio-*`` binaries plus the fixed system dirs, never the venv
    ``bin/`` or ``/usr/local/bin`` (both of which expose every
    ``simplicio-*`` binary system-wide and would defeat the isolation if
    they were still reachable further down an inherited PATH). Takes
    precedence over ``extra_path`` when both are given.
    """
    env = dict(base_env if base_env is not None else os.environ)
    env["OPENROUTER_API_KEY"] = key
    env["HOME"] = config_dir
    env["XDG_CONFIG_HOME"] = os.path.join(config_dir, ".config")
    env["XDG_DATA_HOME"] = os.path.join(config_dir, ".local", "share")
    if isolated_path is not None:
        env["PATH"] = isolated_path
    else:
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
    ``cost_usd_opencode_reported``/``billed_cost_usd`` (issue #1325/#1335's
    real-billed-cost breakdown). ``cost_usd`` starts as the sum of OpenCode's
    own per-call reported cost; ``run_opencode`` overwrites it with the
    settled OpenRouter key-usage delta when one was observed (see
    ``poll_settled_usage``); ``billed_cost_usd`` starts ``None`` and is set
    the same way."""
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
        "billed_cost_usd": None,
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


def poll_settled_usage(fetch_fn, *, reads: int = DEFAULT_SETTLE_READS,
                        interval_s: float = DEFAULT_SETTLE_INTERVAL_S,
                        max_wait_s: float = DEFAULT_SETTLE_MAX_WAIT_S, sleep=time.sleep,
                        clock_values: list[float] | None = None) -> dict:
    """Poll ``fetch_fn()`` (no-arg -> ``float | None`` usage) until it
    returns the SAME value (within float noise) for ``reads`` consecutive
    reads in a row, bounded by ``max_wait_s`` seconds total, sleeping
    ``interval_s`` between reads.

    Returns ``{"value": <last observed reading or None>, "settled": bool}``.
    ``settled`` is True only once ``reads`` consecutive equal reads were
    observed -- the returned ``value`` is then the settled figure (the FULL
    delta from a baseline, not the first step off it). On timeout,
    ``settled`` is False and ``value`` is the LAST reading seen (never
    ``None`` unless every read failed) -- a caller still uses it as the next
    baseline (no leakage across tasks) even though this window's cost falls
    back to the token-computed figure.

    ``clock_values`` (test-only): an explicit sequence consumed instead of
    real ``time.time()`` calls, one per loop condition check, so the
    timeout loop is deterministic under test without any real waiting.
    """
    if clock_values is not None:
        ticks = iter(clock_values)

        def now():
            try:
                return next(ticks)
            except StopIteration:
                return max_wait_s * 10  # force loop exit

    else:
        now = time.time

    start = now()
    deadline = start + max_wait_s
    last_value: float | None = None
    streak = 0

    while now() < deadline:
        value = fetch_fn()
        if value is not None:
            if last_value is not None and abs(value - last_value) <= 1e-9:
                streak += 1
            else:
                streak = 1
            last_value = value
            if streak >= reads:
                return {"value": last_value, "settled": True}
        else:
            streak = 0
        sleep(interval_s)

    return {"value": last_value, "settled": False}


def run_opencode(arm: str, prompt: str, repo_dir: str, *, key: str | None = None,
                  config_dir: str, timeout: int = DEFAULT_RUN_TIMEOUT, skill: bool = False,
                  bin_path: str | None = None, extra_path: str | None = None,
                  isolated_path: str | None = None,
                  usage_baseline: float | None = None, settle_reads: int = DEFAULT_SETTLE_READS,
                  settle_interval_s: float = DEFAULT_SETTLE_INTERVAL_S,
                  settle_max_wait_s: float = DEFAULT_SETTLE_MAX_WAIT_S, sleep=time.sleep,
                  clock_values: list[float] | None = None) -> dict:
    """Drive one task to completion via the real OpenCode CLI in ``repo_dir``.

    ``skill=True`` (the simplicio arm): installs ``.claude/skills/
    simplicio-loop`` into ``repo_dir`` (idempotent) and prefixes the prompt
    with ``/simplicio-loop ``. ``skill=False`` (the normal arm): the prompt
    is sent unchanged and no skill directory is added.

    Real billed cost (issue #1335, settled): OpenCode's JSON events carry no
    OpenRouter generation id, so per-generation stats aren't available and
    the key's cumulative ``GET /api/v1/key`` usage is the only ledger. That
    ledger settles in several increments after the run finishes, so this
    polls with ``poll_settled_usage`` until it has been unchanged for
    ``settle_reads`` consecutive reads (bounded by ``settle_max_wait_s``)
    rather than returning on the first movement. ``usage_baseline`` is the
    ALREADY-SETTLED usage from before this task started (the caller's job --
    see ``run.py``'s per-arm loop -- so no cost leaks across tasks). When the
    usage settles, the full delta becomes ``totals["billed_cost_usd"]`` /
    ``totals["cost_usd"]`` (``cost_source="billed-settled"``); when it never
    settles within the window, ``totals["billed_cost_usd"]`` stays ``None``
    and ``totals["cost_usd"]``/``cost_source`` stay OpenCode's own reported
    sum -- the caller (``run.py``, via ``cost.finalize_task_cost``) then
    falls back to the token-computed cost, never a fabricated number.

    The result also carries ``usage_settled_value`` (the last observed
    reading, settled or not) so the caller can thread it as the NEXT task's
    ``usage_baseline`` with no gap.

    Returns the same shape ``run.py`` already consumes from the retired
    ``agent.run_agent``, plus ``usage_settled_value``: ``{"turns",
    "llm_calls", "commands", "final_text", "totals", "usage_settled_value"}``.
    """
    key = key if key is not None else lc.get_key(arm)
    bin_path = bin_path or opencode_bin()
    os.makedirs(config_dir, exist_ok=True)

    full_prompt = prompt
    if skill:
        install_skill(repo_dir)
        full_prompt = build_prompt(arm, prompt)

    env = build_env(arm, key, config_dir, extra_path=extra_path, isolated_path=isolated_path)
    cmd = build_command(bin_path, repo_dir, full_prompt)

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
            "usage_settled_value": usage_baseline,
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

    settled = poll_settled_usage(
        lambda: fetch_key_usage_usd(key), reads=settle_reads, interval_s=settle_interval_s,
        max_wait_s=settle_max_wait_s, sleep=sleep, clock_values=clock_values,
    )
    if usage_baseline is not None and settled["settled"] and settled["value"] is not None:
        billed = round(settled["value"] - usage_baseline, 8)
        totals["billed_cost_usd"] = billed
        totals["cost_usd"] = billed
        totals["cost_source"] = "billed-settled"
    # else: never settled (or no baseline to compare against) -- leave
    # totals["cost_usd"]/["cost_source"] as OpenCode's own reported sum;
    # billed_cost_usd stays None (summarize()'s default).

    return {
        "turns": parsed["turns"],
        "llm_calls": parsed["llm_calls"],
        "commands": parsed["commands"],
        "final_text": parsed["final_text"],
        "totals": totals,
        "usage_settled_value": settled["value"],
    }
