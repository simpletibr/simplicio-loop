"""Hybrid mode: the turbo engine's model calls go through the invoking host's own headless CLI.

The host agent (OpenCode, Claude Code, Codex, ...) runs ONE command, ``simplicio-loop "<task>"``. Everything behind it (Mapper
survey, fan-out, dev-cli apply, verify, one repair) is the turbo engine; each model call it needs is a one-shot,
tool-less run of the host's own CLI, so it uses the same model, account and configuration with no key of its own.

Which host, and how to call it, is DATA: ``_catalog/harnesses.json`` (schema ``simplicio.harnesses/v1``). An entry has

* ``detect``: ``env`` markers (``"NAME"`` = set, ``"NAME=value"`` = equals) that a tool subprocess of that host sees, and
  ``process`` names looked for among the ancestors of this process (the nearest match wins);
* ``llm``: ``status`` (``verified``: run locally on ``verified_on``; ``documented``: from ``source``; ``host-mode``: no headless
  one-shot, so the two-command plan request applies), ``argv`` (the command; ``{system}``, ``{prompt}`` and ``{model}`` are
  substituted), ``auto`` (``false``: the run may keep its tools, so the host is only used when ``SIMPLICIO_TURBO_LLM`` names it),
  ``model_args``, ``prompt`` (``stdin`` | ``arg``), ``system`` (``flag`` | ``agent`` | ``prompt``: how the planner
  rule reaches the model), ``env``, ``parse`` (the output family) with its ``paths``, ``network``, ``probe`` and the measured
  ``overhead_tokens``.

Nothing here writes to the user's own configuration: the one file it writes, for OpenCode, is the planner agent under the
repo's ``.simplicio-loop/host-llm/``. A host that cannot be used (not detected, CLI missing, no network, auth or HTTP error,
timeout, budget spent) is a typed cause, and the caller falls back to the two-command host mode.
"""
from __future__ import annotations

import atexit
import contextlib
import functools
import json
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

LLM_ENV = "SIMPLICIO_TURBO_LLM"
NESTED_ENV = "SIMPLICIO_TURBO_NESTED"
MODEL_ENV = "SIMPLICIO_TURBO_HOST_MODEL"
BUDGET_ENV = "SIMPLICIO_TURBO_BUDGET_S"
CALL_TIMEOUT_ENV = "SIMPLICIO_TURBO_CALL_TIMEOUT_S"
PARALLEL_ENV = "SIMPLICIO_TURBO_HOST_PARALLEL"
PROBE_ENV = "SIMPLICIO_TURBO_PROBE"
DEFAULT_BUDGET_S = 100.0  # the Claude Code and OpenCode bash tools time out at 120 s
DEFAULT_CALL_TIMEOUT_S = 90.0
DEFAULT_PARALLEL = 4  # 8 opencode runs at once were slower than 4 (20.9 s against 11.3 s for 8 tasks, 8 GB machine): each is heavy
MIN_CALL_S = 1.0
BUSY_BACKOFF_S = 0.5  # a host whose own state store was busy is retried once after this pause
PROBE_BUDGET_S = 2.0
DEFAULT_PROBES = ("api.openai.com:443", "api.anthropic.com:443", "openrouter.ai:443", "generativelanguage.googleapis.com:443")
STATE_SUBDIR = (".simplicio-loop", "host-llm")
PLANNER_AGENT = "simplicio-planner"
# Reasoning is switched off only for a model that is known to take it (it is what the engine was benchmarked with).
REASONING_OFF_MODELS = ("deepseek/deepseek-v4.1-flash",)


# --- the catalog ---------------------------------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def catalog() -> tuple[dict, ...]:
    """Every harness of ``_catalog/harnesses.json``, in file order."""
    path = Path(__file__).resolve().parent / "_catalog" / "harnesses.json"
    return tuple(json.loads(path.read_text(encoding="utf-8"))["harnesses"])


def entry(harness_id: str, entries: Sequence[Mapping[str, Any]] | None = None) -> dict | None:
    """The entry whose id or alias is ``harness_id`` (case-insensitive), else None."""
    wanted = str(harness_id).strip().lower()
    for item in entries if entries is not None else catalog():
        if wanted == item["id"].lower() or wanted in [a.lower() for a in item.get("aliases") or []]:
            return dict(item)
    return None


# --- which host is this, and can it be used ---------------------------------------------------------------------------

def _basename(name: str) -> str:
    base = re.split(r"[\\/]", name.strip())[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


def _env_matches(rule: str, environ: Mapping[str, str]) -> bool:
    """``NAME`` is set and non-empty; ``NAME=value`` equals that value."""
    name, equals, value = rule.partition("=")
    seen = environ.get(name)
    return seen == value if equals else bool(seen)


def ancestor_names(limit: int = 12) -> list[str]:
    """Executable names of this process's parents, nearest first (empty where ``ps`` is unavailable)."""
    if os.name != "posix":
        return []
    try:
        listing = subprocess.run(["ps", "-axo", "pid=,ppid=,comm="], capture_output=True, text=True, timeout=5,
                                 stdin=subprocess.DEVNULL, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    table: dict[int, tuple[int, str]] = {}
    for line in listing.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), parts[2])
    names, pid = [], os.getppid()
    while pid > 1 and pid in table and len(names) < limit:
        pid, command = table[pid]
        names.append(_basename(command))
    return names


def detect(environ: Mapping[str, str] | None = None, ancestors: Sequence[str] | None = None,
           entries: Sequence[Mapping[str, Any]] | None = None) -> dict | None:
    """The catalog entry of the host this process runs under, or None.

    A host whose executable is among the ancestors wins, the nearest first (a host started inside another one is the
    one that matters); a host that only shows an env marker comes after them, in catalog order.
    """
    env = os.environ if environ is None else environ
    items = list(catalog() if entries is None else entries)
    chain = ancestor_names() if ancestors is None else [_basename(n) for n in ancestors]
    best: tuple[tuple[int, int, int], Mapping[str, Any]] | None = None
    for index, item in enumerate(items):
        rules = item.get("detect") or {}
        names = [n.lower() for n in rules.get("process") or []]
        depth = next((d for d, name in enumerate(chain) if name in names), None)
        if depth is None and not any(_env_matches(rule, env) for rule in rules.get("env") or []):
            continue
        key = (0 if depth is not None else 1, depth or 0, index)
        if best is None or key < best[0]:
            best = (key, item)
    return dict(best[1]) if best else None


def probe_network(targets: Sequence[str], budget: float = PROBE_BUDGET_S, environ: Mapping[str, str] | None = None) -> bool:
    """True when any ``host:port`` accepts a connection within ``budget`` seconds (or the proxy the CLI goes through does).

    ``SIMPLICIO_TURBO_PROBE=0`` skips the probe. A host CLI retries a dead network for a minute or more before it fails, so
    this is what keeps a sandboxed host from waiting that long.
    """
    env = os.environ if environ is None else environ
    if (env.get(PROBE_ENV) or "").strip() == "0":
        return True
    proxy = next((env[name] for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy")
                  if env.get(name)), None)
    if proxy:
        parsed = urlparse(proxy if "://" in proxy else "//" + proxy)
        if parsed.hostname:
            targets = [f"{parsed.hostname}:{parsed.port or 8080}"]
    reached = threading.Event()

    def connect(target: str) -> None:
        host, _, port = target.rpartition(":")
        try:
            socket.create_connection((host, int(port)), timeout=budget).close()
            reached.set()
        except (OSError, ValueError):
            pass

    threads = [threading.Thread(target=connect, args=(t,), daemon=True) for t in targets]
    for thread in threads:
        thread.start()
    end = time.monotonic() + budget
    while time.monotonic() < end and not reached.is_set() and any(t.is_alive() for t in threads):
        reached.wait(0.02)
    return reached.is_set()


@dataclass(frozen=True)
class Choice:
    """The outcome of ``resolve``: a backend to use, or the typed cause the hybrid mode cannot be used."""
    backend: Backend | None = None
    cause: str | None = None
    detail: str = ""
    provider: bool = False  # SIMPLICIO_TURBO_LLM=provider: the OpenRouter provider client

    @property
    def reason(self) -> str:
        return f"hybrid_unavailable: {self.cause}"


def resolve(environ: Mapping[str, str] | None = None, ancestors: Sequence[str] | None = None,
            entries: Sequence[Mapping[str, Any]] | None = None, which: Callable[..., str | None] = shutil.which,
            probe: Callable[..., bool] | None = None) -> Choice:
    """Pick the host CLI that answers the engine's model calls, or say why none can."""
    env = os.environ if environ is None else environ
    items = list(catalog() if entries is None else entries)
    wanted, forced = (env.get(LLM_ENV) or "").strip(), None
    if wanted.lower() == "host":
        return Choice(cause="forced_host")
    if wanted.lower() == "provider":
        return Choice(provider=True)
    if wanted and wanted.lower() != "auto":
        forced = entry(wanted, items)
        if forced is None:
            return Choice(cause="unknown_llm", detail=wanted)
    if env.get(NESTED_ENV) == "1":
        return Choice(cause="nested", detail="this command runs inside a hybrid model call")
    host = forced or detect(env, ancestors, items)
    if host is None:
        return Choice(cause="no_host_detected")
    llm = host.get("llm") or {}
    if llm.get("status") not in ("verified", "documented") or not llm.get("argv"):
        return Choice(cause="host_mode_only", detail=f"{host['name']} has no headless one-shot mode")
    if forced is None and llm.get("auto") is False:  # repository text is untrusted: a run that may keep its tools is opt-in
        return Choice(cause="opt_in", detail=f"{host['name']} runs an agent that may keep its tools; set {LLM_ENV}={host['id']} "
                                             "to use it in a trusted repository")
    binary = llm["argv"][0]
    if which(binary, path=env.get("PATH")) is None:
        return Choice(cause="host_cli_missing", detail=f"{binary} is not on PATH")
    if any(env.get(name) for name in llm.get("network_env") or []):
        return Choice(cause="network", detail=f"the {host['name']} sandbox blocks the network")
    if forced is None and not (probe or probe_network)(llm.get("probe") or DEFAULT_PROBES, environ=env):
        return Choice(cause="network", detail="no model API is reachable")
    return Choice(backend=Backend(entry=host, model=(env.get(MODEL_ENV) or "").strip() or None, forced=forced is not None))


# --- what the host printed ------------------------------------------------------------------------------------------

@dataclass
class Parsed:
    text: str | None = None
    error: str | None = None
    cause: str | None = None
    prompt_tokens: int = 0
    cached_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cost: float | None = None
    model: str | None = None
    usage: bool = False  # did the host report token usage at all?


_AUTH = re.compile(
    r"\b(?:401|403)\b|unauthori[sz]ed|forbidden|not logged in|/login\b|log ?in required|invalid[_ ]api[_ ]key|api key is invalid"
    r"|user not found|authenticat|credential|no api key|missing api key|api key is (?:missing|required)|permission denied"
    r"|rejected your api key", re.I)
_NETWORK = re.compile(
    r"cannot connect|unable to connect|econnrefused|econnreset|enotfound|eai_again|getaddrinfo|could not resolve|"
    r"name or service not known|network is unreachable|enetunreach|ehostunreach|connection refused|connection reset|"
    r"fetch failed|failed to fetch|socket hang up|no route to host|tls handshake", re.I)
_HTTP = re.compile(r"\b[45]\d\d\b|rate.?limit|quota|usage limit|overloaded|too many requests|bad gateway|service unavailable|"
                   r"gateway timeout|http error|api error", re.I)
_BUSY = re.compile(r"failed query|sqlite_busy|database is locked|database table is locked|database schema is locked", re.I)


def classify(message: str | None, status: int | None = None) -> str:
    """The typed cause of a failed host call: host_state_busy, host_auth, network, host_http or host_error."""
    text = message or ""
    if _BUSY.search(text):  # first: the SQL text of a failed query can contain any word, "credential" included
        return "host_state_busy"
    if status in (401, 403) or _AUTH.search(text):
        return "host_auth"
    if _NETWORK.search(text):
        return "network"
    if (isinstance(status, int) and status >= 400) or _HTTP.search(text):
        return "host_http"
    return "host_error"


def _json_objects(text: str) -> list[dict]:
    """Every JSON object in ``text``: one document, or one per line (JSONL)."""
    try:
        whole = json.loads(text)
        return [whole] if isinstance(whole, dict) else []
    except ValueError:
        pass
    found = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            found.append(item)
    return found


def _dig(document: Any, path: str) -> Any:
    """``a.b.0.c`` into nested dicts and lists; None when any step is missing."""
    for step in path.split("."):
        if isinstance(document, list) and step.isdigit() and int(step) < len(document):
            document = document[int(step)]
        elif isinstance(document, dict) and step in document:
            document = document[step]
        else:
            return None
    return document


def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _parse_opencode(stdout: str, _stderr: str, _code: int, _llm: Mapping[str, Any]) -> Parsed:
    parsed, tokens = Parsed(), [0, 0, 0, 0]
    for event in _json_objects(stdout):
        part = event.get("part") or {}
        if event.get("type") == "text" and part.get("text"):
            parsed.text = part["text"]
        elif event.get("type") == "step_finish":
            usage = part.get("tokens") or {}
            cache = usage.get("cache") or {}
            tokens[0] += _int(usage.get("input")) + _int(cache.get("read")) + _int(cache.get("write"))
            tokens[1] += _int(cache.get("read"))
            tokens[2] += _int(usage.get("output")) + _int(usage.get("reasoning"))
            tokens[3] += _int(usage.get("reasoning"))
            if isinstance(part.get("cost"), (int, float)):
                parsed.cost = (parsed.cost or 0.0) + part["cost"]
            parsed.usage = True
        elif event.get("type") == "error":
            error = event.get("error") or {}
            data = error.get("data") or {}
            parsed.error = str(data.get("message") or error.get("message") or error.get("name") or "the host reported an error")
            parsed.cause = classify(parsed.error, data.get("statusCode") if isinstance(data.get("statusCode"), int) else None)
    parsed.prompt_tokens, parsed.cached_tokens, parsed.completion_tokens, parsed.reasoning_tokens = tokens
    return parsed


def _parse_claude(stdout: str, _stderr: str, _code: int, _llm: Mapping[str, Any]) -> Parsed:
    results = [d for d in _json_objects(stdout) if d.get("type") == "result" or "result" in d]
    if not results:
        return Parsed()
    doc = results[-1]
    usage = doc.get("usage") or {}
    parsed = Parsed(cost=doc.get("total_cost_usd") if isinstance(doc.get("total_cost_usd"), (int, float)) else None,
                    model=next(iter(doc.get("modelUsage") or {}), None), usage=bool(usage))
    cache_read, cache_write = _int(usage.get("cache_read_input_tokens")), _int(usage.get("cache_creation_input_tokens"))
    parsed.prompt_tokens = _int(usage.get("input_tokens")) + cache_read + cache_write
    parsed.cached_tokens = cache_read
    parsed.completion_tokens = _int(usage.get("output_tokens"))
    parsed.reasoning_tokens = _int((usage.get("output_tokens_details") or {}).get("thinking_tokens"))
    result = doc.get("result")
    if doc.get("is_error"):
        status = doc.get("api_error_status")
        parsed.error = str(result or "the host reported an error")
        parsed.cause = classify(parsed.error, status if isinstance(status, int) else None)
    else:
        parsed.text = result if isinstance(result, str) else None
    return parsed


def _parse_pi(stdout: str, _stderr: str, _code: int, _llm: Mapping[str, Any]) -> Parsed:
    """pi and oh-my-pi: JSONL events; the last assistant ``message_end`` holds the text and the usage. Exit 0 even on error."""
    messages = [e["message"] for e in _json_objects(stdout)
                if e.get("type") == "message_end" and (e.get("message") or {}).get("role") == "assistant"]
    if not messages:
        return Parsed()
    message = messages[-1]
    usage = message.get("usage") or {}
    parsed = Parsed(model=message.get("model"), usage=bool(usage))
    cache_read, cache_write = _int(usage.get("cacheRead")), _int(usage.get("cacheWrite"))
    parsed.prompt_tokens = _int(usage.get("input")) + cache_read + cache_write
    parsed.cached_tokens = cache_read
    parsed.completion_tokens = _int(usage.get("output"))
    parsed.reasoning_tokens = _int(usage.get("reasoning"))
    cost = (usage.get("cost") or {}).get("total")
    parsed.cost = cost if isinstance(cost, (int, float)) else None
    if message.get("stopReason") == "error" or message.get("errorMessage"):
        parsed.error = str(message.get("errorMessage") or "the host reported an error")
        parsed.cause = classify(parsed.error)
    else:
        parsed.text = "".join(c.get("text", "") for c in message.get("content") or [] if c.get("type") == "text") or None
    return parsed


def _parse_json_paths(stdout: str, _stderr: str, _code: int, llm: Mapping[str, Any]) -> Parsed:
    """One JSON document (or an array of messages); ``llm.paths`` says where its parts are.

    ``text``, ``model`` and ``cost`` are paths (``a.b.0.c``); a token field is a path or a list of paths to add up; ``select``
    picks the last element of an array whose fields equal it. A failure is ``ok`` (``{"path", "equals"}``) not holding,
    ``failed`` matching, or, when neither is given, a non-empty ``error`` path; ``error`` also names the message.
    """
    try:
        whole = json.loads(stdout)
    except ValueError:
        whole = None
    documents = whole if isinstance(whole, list) else _json_objects(stdout)
    paths = llm.get("paths") or {}
    select = paths.get("select") or {}
    documents = [d for d in documents if isinstance(d, dict) and all(d.get(k) == v for k, v in select.items())]
    if not documents:
        return Parsed()
    doc = documents[-1]

    def get(key: str) -> Any:
        return _dig(doc, paths[key]) if isinstance(paths.get(key), str) else None

    def count(key: str) -> int:
        spec = paths.get(key)
        if isinstance(spec, list):
            return sum(_int(_dig(doc, path)) for path in spec)
        return _int(get(key)) if spec else 0

    parsed = Parsed(model=get("model") if isinstance(get("model"), str) else None)
    parsed.prompt_tokens, parsed.cached_tokens = count("prompt_tokens"), count("cached_tokens")
    parsed.completion_tokens, parsed.reasoning_tokens = count("completion_tokens"), count("reasoning_tokens")
    parsed.usage = bool(parsed.prompt_tokens or parsed.completion_tokens)
    parsed.cost = get("cost") if isinstance(get("cost"), (int, float)) else None
    ok, failed, message = paths.get("ok"), paths.get("failed"), get("error")
    if isinstance(ok, dict):
        problem = _dig(doc, ok["path"]) != ok.get("equals")
    elif isinstance(failed, dict):
        problem = _dig(doc, failed["path"]) == failed.get("equals")
    else:
        problem = bool(message)
    if problem:
        parsed.error = str(message) if message else "the host reported a failure"
        parsed.cause = classify(parsed.error)
    else:
        text = get("text")
        parsed.text = text if isinstance(text, str) else None
    return parsed


def _parse_codex(stdout: str, _stderr: str, _code: int, _llm: Mapping[str, Any]) -> Parsed:
    """``codex exec --json``: the last ``agent_message`` item is the text, ``turn.completed`` carries the usage."""
    parsed, soft_error, failed = Parsed(), None, None
    for event in _json_objects(stdout):
        kind, item = event.get("type"), event.get("item") or {}
        if kind == "item.completed" and item.get("type") == "agent_message" and item.get("text"):
            parsed.text = item["text"]
        elif kind == "turn.completed":
            usage = event.get("usage") or {}
            parsed.prompt_tokens, parsed.cached_tokens = _int(usage.get("input_tokens")), _int(usage.get("cached_input_tokens"))
            parsed.completion_tokens, parsed.reasoning_tokens = _int(usage.get("output_tokens")), _int(usage.get("reasoning_output_tokens"))
            parsed.usage = True
        elif kind == "turn.failed":
            failed = str((event.get("error") or {}).get("message") or "the turn failed")
        elif kind == "error" and event.get("message"):
            soft_error = str(event["message"])
    if failed or (soft_error and not parsed.text):
        parsed.error = failed or soft_error
        parsed.cause = classify(parsed.error)
    return parsed


def _parse_text(stdout: str, _stderr: str, _code: int, _llm: Mapping[str, Any]) -> Parsed:
    return Parsed(text=stdout)


PARSERS: dict[str, Callable[[str, str, int, Mapping[str, Any]], Parsed]] = {
    "opencode": _parse_opencode, "claude": _parse_claude, "pi": _parse_pi, "json": _parse_json_paths, "text": _parse_text,
    "codex": _parse_codex,
}


def _tail(*texts: str, limit: int = 300) -> str:
    for text in texts:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if lines:
            return lines[-1][:limit]
    return ""


def parse_output(host: Mapping[str, Any], stdout: str, stderr: str, returncode: int) -> Parsed:
    """The host's output as a reply: text and usage, or a typed error. ``host`` is a catalog entry."""
    llm = host["llm"]
    parsed = PARSERS[llm["parse"]](stdout, stderr, returncode, llm)
    if parsed.text is not None:
        parsed.text = parsed.text.strip() or None
    if parsed.error is None and returncode != 0:
        parsed.error = _tail(stdout, stderr) or f"{llm['argv'][0]} exited {returncode}"
        parsed.text = None
    if parsed.error is None and not parsed.text:
        parsed.error = "the host returned no text"
    if parsed.error is not None:
        parsed.text = None
        parsed.cause = parsed.cause or classify(parsed.error)
    return parsed


# --- the call ---------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Backend:
    """One catalog entry chosen to answer the engine's model calls."""
    entry: dict
    model: str | None = None
    forced: bool = False

    @property
    def id(self) -> str:
        return self.entry["id"]

    @property
    def llm(self) -> Mapping[str, Any]:
        return self.entry["llm"]


@dataclass
class Call:
    argv: list[str]
    stdin: str | None
    env: dict[str, str]
    cwd: Path
    notes: dict[str, Any] = field(default_factory=dict)


def split_messages(messages: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    """The system text, and everything else as one prompt (a retry conversation gets role labels)."""
    system = "\n\n".join(str(m["content"]) for m in messages if m.get("role") == "system")
    turns = [m for m in messages if m.get("role") != "system"]
    if len(turns) == 1:
        return system, str(turns[0]["content"])
    return system, "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in turns)


_setup_lock = threading.Lock()


def _write_if_changed(path: Path, text: str) -> None:
    with _setup_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return
        scratch = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        scratch.write_text(text, encoding="utf-8")
        os.replace(scratch, path)


def _setup_opencode(backend: Backend, root: Path, env: dict[str, str], slot: int) -> dict[str, Any]:
    """The planner agent, merged into the user's own OpenCode configuration and written only under ``.simplicio-loop/``.

    No tools (``permission {"*": "deny"}``) and no ``model``, so OpenCode resolves the user's default model with the user's
    provider and credentials. Reasoning is switched off for the benchmarked model, and for an explicit openrouter model, only.

    Every ``opencode run`` opens a SQLite session database. Lanes that share one fail with "database is locked" when they
    start together (measured: 3 of 4 on a fresh database), so each concurrency slot has its own, reused by the calls that
    run in that slot. An ``OPENCODE_DB`` the user already exports is not used: two lanes must never share it.
    """
    off = list(REASONING_OFF_MODELS)
    if backend.model and backend.model.startswith("openrouter/") and backend.model.count("/") >= 2:
        off.append(backend.model.split("/", 1)[1])
    config = {
        "$schema": "https://opencode.ai/config.json",
        "agent": {PLANNER_AGENT: {
            "description": "simplicio turbo planner: answers with one JSON edit plan and uses no tools",
            "mode": "primary", "temperature": 0, "permission": {"*": "deny"},
            "prompt": _planner_rule(),
        }},
        "provider": {"openrouter": {"models": {m: {"options": {"reasoning": {"enabled": False}}} for m in dict.fromkeys(off)}}},
    }
    state = root.joinpath(*STATE_SUBDIR)
    text = json.dumps(config, indent=2) + "\n"
    _write_if_changed(state / "opencode.json", text)
    if env.get("OPENCODE_CONFIG"):  # the user's own file stays loaded: ours is merged on top as inline content
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
    else:
        env["OPENCODE_CONFIG"] = str(state / "opencode.json")
    database = state / "db" / f"slot-{slot}.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    env["OPENCODE_DB"] = str(database)
    return {"reasoning_off_for": [f"openrouter/{m}" for m in dict.fromkeys(off)]}


SETUPS: dict[str, Callable[[Backend, Path, dict[str, str], int], dict[str, Any]]] = {"opencode": _setup_opencode}


def _planner_rule() -> str:
    from .turbo import _PLANNER_SYSTEM
    return _PLANNER_SYSTEM


def build_call(backend: Backend, root: Path, messages: Sequence[Mapping[str, Any]],
               environ: Mapping[str, str] | None = None, slot: int = 0) -> Call:
    """The argv, stdin, environment and directory of one host CLI run for these engine messages, in concurrency ``slot``."""
    llm, root = backend.llm, Path(root).resolve()
    env = dict(os.environ if environ is None else environ)
    system, prompt = split_messages(messages)
    how = llm.get("system", "prompt")
    if how == "agent":  # the planner rule lives in the agent; only what follows it (the map) travels with the task
        rule = _planner_rule()
        rest = system[len(rule):].lstrip("\n") if system.startswith(rule) else system
        prompt = f"{rest}\n\n{prompt}" if rest else prompt
    elif how == "prompt" and system:
        prompt = f"{system}\n\n{prompt}"
    values = {"system": system, "prompt": prompt, "model": backend.model or ""}
    args = list(llm["argv"]) + (list(llm.get("model_args") or []) if backend.model else [])
    argv = [re.sub(r"\{(system|prompt|model)\}", lambda found: values[found.group(1)], a) for a in args]
    env.update(llm.get("env") or {})
    env[NESTED_ENV] = "1"  # a nested simplicio-loop must not start the hybrid backend again
    notes = SETUPS[llm["setup"]](backend, root, env, slot) if llm.get("setup") else {}
    return Call(argv=argv, stdin=prompt if llm.get("prompt") == "stdin" else None, env=env, cwd=root, notes=notes)


# --- the process -------------------------------------------------------------------------------------------------------

_active: set[subprocess.Popen] = set()
_active_lock = threading.Lock()
_slots: queue.LifoQueue | None = None


def parallel(environ: Mapping[str, str] | None = None) -> int:
    """How many host CLI processes run at once: the number of slots, and so the most calls one run makes."""
    try:
        return max(1, int((os.environ if environ is None else environ).get(PARALLEL_ENV, "") or DEFAULT_PARALLEL))
    except ValueError:
        return DEFAULT_PARALLEL


def _slot_pool() -> queue.LifoQueue:
    """The free concurrency slots (0..width-1). Last in, first out: calls that follow each other reuse slot 0."""
    global _slots
    with _active_lock:
        if _slots is None:
            _slots = queue.LifoQueue()
            for index in reversed(range(parallel())):
                _slots.put(index)
        return _slots


@contextlib.contextmanager
def _slot():
    """Wait for a free slot and hold it: at most ``width`` host processes run, and none shares its slot with another."""
    pool = _slot_pool()
    index = pool.get()
    try:
        yield index
    finally:
        pool.put(index)


def _terminate(proc: subprocess.Popen) -> None:
    """Stop the CLI and everything it started (its own process group), then reap it."""
    for sig in (signal.SIGTERM, getattr(signal, "SIGKILL", signal.SIGTERM)):  # Windows has no SIGKILL: proc.kill() below
        try:
            if os.name == "posix":
                os.killpg(proc.pid, sig)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            break
        try:
            proc.wait(timeout=2)
            return
        except subprocess.TimeoutExpired:
            continue
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def kill_active() -> None:
    """Called on exit and on SIGTERM/SIGINT: no host CLI outlives the command that started it."""
    with _active_lock:
        running = list(_active)
    for proc in running:
        if proc.poll() is None:
            _terminate(proc)


_cleanup_installed = False


def install_cleanup() -> None:
    """Once per process: kill the host CLIs on exit and on SIGTERM/SIGINT, then let the previous handler run."""
    global _cleanup_installed
    if _cleanup_installed:
        return
    _cleanup_installed = True
    atexit.register(kill_active)
    if threading.current_thread() is not threading.main_thread():
        return
    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue

        def _handler(signum, frame, _previous=signal.getsignal(sig)):
            kill_active()
            if callable(_previous):
                _previous(signum, frame)
            else:
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)

        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass


def budget_s(environ: Mapping[str, str] | None = None) -> float:
    """The time budget of one run: past it no new lane starts and the rest is handed to the host (default 100 s)."""
    raw = (os.environ if environ is None else environ).get(BUDGET_ENV) or ""
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_BUDGET_S
    return value if value > 0 else DEFAULT_BUDGET_S


def _fatal(code: str, detail: str, started: float, host: str) -> dict[str, Any]:
    return {"ok": False, "fatal": True, "reason_code": code, "error": detail[:500], "host": host,
            "latency_s": round(time.monotonic() - started, 3)}


def _call_timeout(environ: Mapping[str, str]) -> float:
    try:
        return float(environ.get(CALL_TIMEOUT_ENV) or DEFAULT_CALL_TIMEOUT_S)
    except ValueError:
        return DEFAULT_CALL_TIMEOUT_S


def complete(arm: str, messages: Sequence[Mapping[str, Any]], *, backend: Backend, root: Path,
             deadline: float | None = None, timeout: float | None = None, environ: Mapping[str, str] | None = None,
             **_ignored: Any) -> dict[str, Any]:
    """One model call through the host CLI, shaped like ``turbo_provider.complete``'s reply.

    Never raises for a host problem: a failure is ``{"ok": False, "fatal": True, "reason_code": <cause>, "error": ...}`` so the
    engine can stop, keep what it applied and hand the rest to the host. A call that failed because the host's own state
    store was busy (``host_state_busy``) is made once more after a short pause before that failure is reported.
    """
    del arm
    reply = _complete_once(messages, backend, root, deadline, timeout, environ)
    if reply.get("reason_code") == "host_state_busy":
        time.sleep(BUSY_BACKOFF_S)
        reply = _complete_once(messages, backend, root, deadline, timeout, environ)
    return reply


def _complete_once(messages: Sequence[Mapping[str, Any]], backend: Backend, root: Path, deadline: float | None,
                   timeout: float | None, environ: Mapping[str, str] | None) -> dict[str, Any]:
    started, env = time.monotonic(), (os.environ if environ is None else environ)
    limit = timeout or _call_timeout(env)
    if deadline is not None:
        left = deadline - started
        if left < MIN_CALL_S:
            return _fatal("budget", f"the {BUDGET_ENV} time budget is spent", started, backend.id)
        limit = min(limit, left)
    with _slot() as slot:
        started = time.monotonic()  # the latency of the call, not the wait for a slot
        if deadline is not None:  # ...which spent part of the budget
            left = deadline - started
            if left < MIN_CALL_S:
                return _fatal("budget", f"the {BUDGET_ENV} time budget is spent", started, backend.id)
            limit = min(limit, left)
        call = build_call(backend, root, messages, environ=env, slot=slot)
        binary = shutil.which(call.argv[0], path=call.env.get("PATH"))
        if binary is None:
            return _fatal("host_cli_missing", f"{call.argv[0]} is not on PATH", started, backend.id)
        try:
            proc = subprocess.Popen(
                [binary, *call.argv[1:]], stdin=subprocess.PIPE if call.stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(call.cwd), env=call.env,
                start_new_session=os.name == "posix")
        except OSError as exc:
            return _fatal("host_cli_missing" if isinstance(exc, FileNotFoundError) else "host_error", f"{call.argv[0]}: {exc}", started, backend.id)
        with _active_lock:
            _active.add(proc)
        try:
            out, err = proc.communicate(input=call.stdin.encode("utf-8") if call.stdin is not None else None, timeout=limit)
        except subprocess.TimeoutExpired:
            _terminate(proc)
            try:
                proc.communicate(timeout=2)  # closes the pipes
            except (subprocess.TimeoutExpired, ValueError, OSError):
                pass
            return _fatal("host_timeout", f"{call.argv[0]} did not answer within {limit:.0f}s", started, backend.id)
        except BrokenPipeError:
            out, err = b"", b""
            proc.wait()
        finally:
            with _active_lock:
                _active.discard(proc)
    stdout, stderr = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    for pattern in backend.llm.get("fatal_stderr") or []:
        hit = re.search(pattern, stderr)
        if hit:
            return _fatal("host_error", f"the host did not load the planner agent ({_tail(stderr)})", started, backend.id)
    parsed = parse_output(backend.entry, stdout, stderr, proc.returncode)
    if parsed.error:
        return _fatal(parsed.cause or "host_error", parsed.error, started, backend.id)
    return {
        "ok": True, "content": parsed.text, "finish_reason": "stop", "provider": None, "model": parsed.model, "host": backend.id,
        "latency_s": round(time.monotonic() - started, 3), "prompt_tokens": parsed.prompt_tokens,
        "completion_tokens": parsed.completion_tokens, "reasoning_tokens": parsed.reasoning_tokens,
        "cached_tokens": parsed.cached_tokens, "cost": parsed.cost, "cost_usd": parsed.cost, "usage_reported": parsed.usage,
        "notes": call.notes,
    }
