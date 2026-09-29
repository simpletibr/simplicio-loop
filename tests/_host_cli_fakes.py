"""Fake host CLIs for the hybrid-mode tests: a real executable on PATH that prints recorded output shapes.

`install(tmp_path, "opencode", calls=[...])` writes `<tmp_path>/bin/opencode`, a Python script that

* counts its own invocations atomically (parallel lanes are safe),
* logs argv, stdin, cwd, its start time and the environment variables the engine sets to `<name>.log` (one JSON per line),
* sleeps, writes stderr and stdout, and exits with the status the matching entry of `calls` asks for. The last entry
  repeats, so one entry describes every call.

An entry is `{"mode": "opencode"|"claude"|"pi"|"json"|"text", "reply": "<model text>", "exit": 0, "stderr": "", "sleep": 0,
"stdout": <exact bytes to print instead of a synthesized reply>, "stdout_file": <path of a recorded output>,
"when": "<text>"}`. An entry with `when` answers the call whose stdin contains that text (lanes run at the same time, so
their order is not fixed); the other entries answer by call number.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "host_llm"

_SCRIPT = r'''#!{python}
import json, os, sys, time

here = os.path.dirname(os.path.abspath(__file__))
name = os.path.basename(__file__)
spec = json.load(open(os.path.join(here, name + ".spec.json")))
number = 0
while True:
    try:
        os.close(os.open(os.path.join(here, "%s.call.%d" % (name, number)), os.O_CREAT | os.O_EXCL))
        break
    except FileExistsError:
        number += 1
stdin, picked = None, None
if any("when" in c for c in spec["calls"]):  # parallel lanes: pick the reply by what this call was asked, not by its number
    stdin = sys.stdin.read()
    picked = next((c for c in spec["calls"] if c.get("when") and c["when"] in stdin), None)
plain = [c for c in spec["calls"] if "when" not in c]
call = picked or plain[min(number, len(plain) - 1)]
if stdin is None:
    stdin = "" if call.get("stdin") == "ignore" else sys.stdin.read()
seen = {{k: v for k, v in os.environ.items() if k.startswith(("SIMPLICIO_", "OPENCODE", "CLAUDE", "PI_", "AGENT"))}}
with open(os.path.join(here, name + ".log"), "a") as log:
    log.write(json.dumps({{"n": number, "pid": os.getpid(), "start": time.time(), "sleep": call.get("sleep", 0), "argv": sys.argv[1:], "stdin": stdin, "cwd": os.getcwd(), "env": seen,
                          "agent_file": open(seen["OPENCODE_CONFIG"]).read() if seen.get("OPENCODE_CONFIG") and os.path.isfile(seen["OPENCODE_CONFIG"]) else None}}) + "\n")
time.sleep(call.get("sleep", 0))
sys.stderr.write(call.get("stderr", ""))
mode, reply = call.get("mode", "text"), call.get("reply", "")
if "stdout" in call:
    out = call["stdout"]
elif "stdout_file" in call:
    out = open(call["stdout_file"]).read()
elif mode == "opencode":
    tokens = {{"total": 1225, "input": 970, "output": 255, "reasoning": 0, "cache": {{"write": 0, "read": 0}}}}
    tokens.update(call.get("tokens", {{}}))
    events = [{{"type": "step_start", "timestamp": 1000, "sessionID": "ses_x", "part": {{"messageID": "msg_1", "type": "step-start"}}}},
              {{"type": "text", "timestamp": 1400, "sessionID": "ses_x", "part": {{"messageID": "msg_1", "type": "text", "text": reply}}}},
              {{"type": "step_finish", "timestamp": 1450, "sessionID": "ses_x", "part": {{"messageID": "msg_1", "type": "step-finish", "reason": "stop", "tokens": tokens, "cost": call.get("cost", 0.0006)}}}}]
    out = "".join(json.dumps(e) + "\n" for e in events)
elif mode == "claude":
    out = json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": reply, "num_turns": 1, "duration_ms": 900,
                      "total_cost_usd": call.get("cost", 0.001), "usage": {{"input_tokens": 400, "output_tokens": 30, "cache_read_input_tokens": 80,
                      "cache_creation_input_tokens": 20, "output_tokens_details": {{"thinking_tokens": 0}}}}, "modelUsage": {{"claude-test": {{}}}}}})
elif mode == "pi":
    message = {{"role": "assistant", "content": [{{"type": "text", "text": reply}}], "provider": "openrouter", "model": "test/model", "stopReason": "stop",
               "usage": {{"input": 300, "output": 40, "cacheRead": 100, "cacheWrite": 0, "reasoning": 0, "cost": {{"total": 0.0004}}}}}}
    out = "".join(json.dumps(e) + "\n" for e in ({{"type": "agent_start"}}, {{"type": "message_end", "message": message}}, {{"type": "agent_end", "messages": [message]}}))
elif mode == "json":
    out = json.dumps(call["document"] if "document" in call else {{"response": reply}})
else:
    out = reply
sys.stdout.write(out)
sys.exit(call.get("exit", 0))
'''


def install(tmp_path: Path, name: str, calls: list[dict[str, Any]] | None = None, **single: Any) -> Path:
    """Write the fake `name` into `<tmp_path>/bin` and return that directory (prepend it to PATH)."""
    bin_dir = Path(tmp_path) / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / name
    script.write_text(_SCRIPT.format(python=sys.executable), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (bin_dir / f"{name}.spec.json").write_text(json.dumps({"calls": calls or [single]}), encoding="utf-8")
    return bin_dir


def log(bin_dir: Path, name: str) -> list[dict[str, Any]]:
    path = Path(bin_dir) / f"{name}.log"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def path_with(bin_dir: Path) -> str:
    return os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
