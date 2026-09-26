"""Agentic driver shared by BOTH A/B arms: an OpenAI-style tool-calling loop
with exactly ONE tool, ``bash``, executed as ``bash -lc <command>`` inside the
target repo.

There is no per-arm branching in this module. The "normal" and "simplicio"
arms run the SAME agent loop; the only difference between them is which
system/user prompt run.py hands to ``run_agent`` (the simplicio arm's system
prompt appends the simplicio-loop SKILL.md text, and its user prompt is
``"/simplicio-loop " + task``). The model decides everything else -- which
commands to run, whether to invoke simplicio-loop, when it is done -- via the
bash tool, exactly like a real coding agent.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import llm_client as lc  # noqa: E402
import measure  # noqa: E402

TAIL_CHARS = 8000

SIMPLICIO_PREFIX = "simplicio-"

BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": (
            "Run a shell command in the repository's working directory and "
            "get back its combined stdout/stderr and exit code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "the shell command to run, e.g. via `bash -lc`",
                },
            },
            "required": ["command"],
        },
    },
}


def truncate_tail(text: str | None, limit: int = TAIL_CHARS) -> str:
    """Keep only the LAST ``limit`` characters of ``text``.

    Command output can be arbitrarily large (a build log, a full test run);
    only the tail is what a coding agent needs to react to. ``None`` becomes
    the empty string rather than raising.
    """
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[-limit:]


def classify_command(command: str | None) -> bool:
    """True iff any command in ``command`` (including after ``cd x &&``,
    ``;`` or ``|``) runs a simplicio-loop/mapper/dev-cli/fast binary."""
    if not command:
        return False
    stripped = command.strip()
    if not stripped:
        return False
    for token in re.split(r"[\s;&|()]+", stripped):
        if token.rsplit("/", 1)[-1].startswith(SIMPLICIO_PREFIX):
            return True
    return False


def parse_tool_calls(message: dict | None) -> list[dict]:
    """Extract ``[{"id", "name", "arguments"}]`` from an OpenAI-shaped
    assistant message. Tolerates a missing ``tool_calls`` list and malformed
    per-call ``arguments`` JSON (degrades to ``{}`` rather than raising)."""
    out: list[dict] = []
    for call in (message or {}).get("tool_calls") or []:
        func = call.get("function") or {}
        raw_args = func.get("arguments")
        args: dict = {}
        if isinstance(raw_args, dict):
            args = raw_args
        elif isinstance(raw_args, str) and raw_args.strip():
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    args = parsed
            except (ValueError, TypeError):
                args = {}
        out.append({"id": call.get("id"), "name": func.get("name"), "arguments": args})
    return out


def summarize(llm_calls: list[dict], commands: list[dict]) -> dict:
    """Pure aggregation over one task's recorded ``llm_calls``/``commands``
    into the totals dict stored on that task's results entry."""
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

    cmd_wall = cmd_cpu = 0.0
    n_simplicio = 0
    for cmd in commands:
        cmd_wall += cmd.get("wall_s") or 0
        cmd_cpu += cmd.get("cpu_s") or 0
        if cmd.get("is_simplicio"):
            n_simplicio += 1

    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "cached_tokens": cached,
        "cost_usd": round(cost, 6),
        "llm_latency_s": round(llm_latency, 4),
        "cmd_wall_s": round(cmd_wall, 4),
        "cmd_cpu_s": round(cmd_cpu, 4),
        "n_commands": len(commands),
        "n_simplicio_commands": n_simplicio,
    }


def run_agent(arm: str, system_prompt: str, user_prompt: str, repo_dir: str,
              max_turns: int = 30, cmd_timeout: int = 180, env: dict | None = None) -> dict:
    """Drive one agentic task to completion (or ``max_turns``) in ``repo_dir``.

    OpenAI-style tool-calling loop with the single ``bash`` tool: each turn,
    ask the model for the next step; if it replies with ``tool_calls``, run
    every requested command via ``bash -lc`` in ``repo_dir`` and feed back
    the truncated combined output as a ``tool`` message; stop when the
    assistant replies with no ``tool_calls`` (it is done) or ``max_turns``
    is reached.

    The subprocess ``PATH`` is the caller's environment with the venv bin
    holding ``simplicio-loop``/``simplicio-mapper``/``simplicio-dev-cli``/
    ``simplicio-fast`` (``dirname(sys.executable)``) prepended, so both arms
    can invoke those binaries from the bash tool -- the simplicio arm
    because its prompt asks it to, the normal arm never because it is never
    told to.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    run_env = dict(env if env is not None else os.environ)
    venv_bin = os.path.dirname(os.path.abspath(sys.executable))
    run_env["PATH"] = venv_bin + os.pathsep + run_env.get("PATH", "")

    llm_calls: list[dict] = []
    commands: list[dict] = []
    final_text = None
    turns = 0

    for turn in range(1, max_turns + 1):
        turns = turn
        llm_result, _call_metrics = measure.measure_call(
            lambda: lc.chat(arm, messages, temperature=0, tools=[BASH_TOOL])
        )
        llm_calls.append({
            "turn": turn,
            "ok": llm_result.get("ok"),
            "id": llm_result.get("id"),
            "latency_s": llm_result.get("latency_s"),
            "prompt_tokens": llm_result.get("prompt_tokens"),
            "completion_tokens": llm_result.get("completion_tokens"),
            "reasoning_tokens": llm_result.get("reasoning_tokens"),
            "cached_tokens": llm_result.get("cached_tokens"),
            "cost_usd": llm_result.get("cost_usd"),
            "finish_reason": llm_result.get("finish_reason"),
            "error": llm_result.get("error"),
        })
        if not llm_result.get("ok"):
            break

        message = llm_result.get("message") or {"role": "assistant", "content": llm_result.get("content")}
        messages.append(message)
        tool_calls = parse_tool_calls(message)
        if not tool_calls:
            final_text = message.get("content")
            break

        for call in tool_calls:
            command = (call.get("arguments") or {}).get("command", "") or ""
            out, metrics = measure.run_subprocess(
                ["bash", "-lc", command], cwd=repo_dir, timeout=cmd_timeout, env=run_env,
            )
            tail = truncate_tail(out)
            commands.append({
                "turn": turn,
                "command": command,
                "returncode": metrics.get("returncode"),
                "wall_s": metrics.get("wall_s"),
                "cpu_s": metrics.get("cpu_s"),
                "peak_rss_mb": metrics.get("peak_rss_mb"),
                "is_simplicio": classify_command(command),
                "output_bytes": len(out or ""),
                "output_tail": tail,
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id"),
                "content": tail if tail else "(no output)",
            })

    return {
        "turns": turns,
        "llm_calls": llm_calls,
        "commands": commands,
        "final_text": final_text,
        "totals": summarize(llm_calls, commands),
    }
