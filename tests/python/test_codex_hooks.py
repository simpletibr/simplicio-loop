from __future__ import annotations

import io
import json

from simplicio import codex_hooks


def test_user_prompt_submit_emits_hint(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "ajuste o hook em settings.json",
                }
            )
        ),
    )

    assert codex_hooks.main() == 0
    assert "[SIMPLICIO_PROMPT_HINT]" in capsys.readouterr().err


def test_post_tool_use_is_observational_and_malformed_input_is_safe(monkeypatch):
    for raw in (
        json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Edit"}),
        "not-json",
    ):
        monkeypatch.setattr("sys.stdin", io.StringIO(raw))
        assert codex_hooks.main() == 0
