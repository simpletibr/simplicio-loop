import json
import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugin"
HOOKS = PLUGIN / "hooks" / "hooks.claude.json"
SCRIPT = PLUGIN / "hooks" / "user_prompt_submit.py"


def test_marketplace_plugin_registers_user_prompt_submit():
    manifest = json.loads(HOOKS.read_text(encoding="utf-8"))
    registrations = manifest["hooks"]["UserPromptSubmit"]
    command = registrations[0]["hooks"][0]["command"]
    assert "user_prompt_submit.py" in command
    assert SCRIPT.is_file()


def test_marketplace_user_prompt_hook_runs_canonical_adapter():
    payload = json.dumps({
        "prompt": "implement the roster fix",
        "session_id": "plugin-hook-session",
        "env": {"SIMPLICIO_RUNTIME_AVAILABLE": "0"},
    })
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN)
    process = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        cwd=str(REPO),
        env=env,
    )
    assert process.returncode == 0, process.stderr
    value = json.loads(process.stdout)
    assert value["decision"] == "continue"
    assert value["reason"] == "prompt_passthrough"
    assert value["route_decision"] == value["route"]
    assert value["prompt_enrichment"]["status"] == "skipped"
    assert value["prompt_enrichment"]["reason_code"] == "prompt_enrichment_removed"
    assert value["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "simplicio.prompt-enrichment-receipt/v1" in value["hookSpecificOutput"]["additionalContext"]
    assert "## Simplicio skill:" not in value["hookSpecificOutput"]["additionalContext"]
