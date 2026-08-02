from __future__ import annotations

import io
import json
import subprocess

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


def test_runtime_route_blocks_codex_after_success(monkeypatch, capsys, tmp_path):
    observed = {}

    def fake_route(prompt, argv, *, cwd):
        observed.update(prompt=prompt, argv=argv, cwd=cwd)
        return subprocess.CompletedProcess(
            ["simplicio", "run"],
            0,
            stdout='{"schema":"simplicio.io/v1","status":"passed","receipt_id":"receipt-1"}',
            stderr="",
        )

    monkeypatch.setattr(codex_hooks, "route_through_runtime", fake_route)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "fix settings.json",
                    "cwd": str(tmp_path),
                    "codex_argv": ["exec", "fix settings.json"],
                    "permission_mode": "acceptEdits",
                }
            )
        ),
    )

    assert codex_hooks.main(["--route", "runtime", "--marker", codex_hooks.HOOK_MARKER]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["decision"] == "block"
    assert "Runtime completed" in response["reason"]
    assert response["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "additionalContext" in response["hookSpecificOutput"]
    assert observed == {
        "prompt": "fix settings.json",
        "argv": ["exec", "fix settings.json", "--permission-mode", "acceptEdits"],
        "cwd": str(tmp_path),
    }


def test_runtime_route_catches_low_confidence_code_edit(monkeypatch, capsys):
    monkeypatch.setattr(
        codex_hooks,
        "route_through_runtime",
        lambda prompt, argv, *, cwd: subprocess.CompletedProcess(
            ["simplicio", "run"],
            0,
            stdout='{"schema":"simplicio.io/v1","status":"passed","receipt_id":"receipt-3"}',
            stderr="",
        ),
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "refactor authentication flow"})
        ),
    )
    assert codex_hooks.main(["--route", "runtime"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "block"


def test_runtime_route_blocks_on_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        codex_hooks,
        "route_through_runtime",
        lambda prompt, argv, *, cwd: subprocess.CompletedProcess(
            ["simplicio", "run"], 3, stdout="", stderr="timeout"
        ),
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "fix app.py"})),
    )

    assert codex_hooks.main(["--route", "runtime"]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["decision"] == "block"
    assert "timeout" in response["reason"]


def test_runtime_route_blocks_when_runtime_is_unavailable(monkeypatch, capsys):
    def fail_route(*args, **kwargs):
        raise OSError("missing")

    monkeypatch.setattr(codex_hooks, "route_through_runtime", fail_route)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "fix app.py"})),
    )

    assert codex_hooks.main(["--route", "runtime"]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["decision"] == "block"
    assert "unavailable" in response["reason"]


def test_runtime_route_ignores_non_code_prompt_and_guard(monkeypatch, capsys):
    monkeypatch.setattr(
        codex_hooks,
        "route_through_runtime",
        lambda prompt, argv, *, cwd: subprocess.CompletedProcess(
            ["simplicio", "run"],
            0,
            stdout='{"schema":"simplicio.io/v1","status":"passed","receipt_id":"receipt-2"}',
            stderr="",
        ),
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "what is Python?"})),
    )
    assert codex_hooks.main(["--route", "runtime"]) == 0
    assert capsys.readouterr().out == ""

    monkeypatch.setenv("SIMPLICIO_HOOK_GUARD", "1")
    monkeypatch.setattr("sys.stdin", io.StringIO("not-json"))
    assert codex_hooks.main(["--route", "runtime"]) == 0


def test_runtime_route_blocks_when_detection_fails(monkeypatch, capsys):
    monkeypatch.setattr(codex_hooks, "detect", lambda prompt: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "fix app.py"})),
    )
    assert codex_hooks.main(["--route", "runtime"]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["decision"] == "block"
    assert "classification failed" in response["reason"]
