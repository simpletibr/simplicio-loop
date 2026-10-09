"""Unit tests for exec_planner: plan-only argv, fake CLIs on PATH, tree-kill, fallback. No real model is called."""

import asyncio
import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

from simplicio_loop import exec_planner, model_roles

PLAN = {"operations": [{"op": "create", "file": "a.txt", "content": "x"}]}
FORBIDDEN_FLAGS = (
    "--dangerously-bypass-approvals-and-sandbox",
    "--always-approve",
    "bypassPermissions",
    "acceptEdits",
    "workspace-write",
    "danger-full-access",
    "yolo",
)


@pytest.fixture
def bindir(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    monkeypatch.delenv("SIMPLICIO_EXEC_FAMILIES", raising=False)
    return d


def fake_cli(bindir, name, body="", stdout=None):
    """Install a fake `name` CLI. It records argv/stdin/order under bindir, then runs `body` (python code)."""
    if stdout is None:
        stdout = json.dumps(PLAN)
    script = (
        "#!%s\n"
        "import json, os, signal, subprocess, sys, time\n"
        "d = %r\n"
        "name = %r\n"
        "stdin = '' if sys.stdin.isatty() else sys.stdin.read()\n"
        "json.dump({'argv': sys.argv[1:], 'stdin': stdin}, open(os.path.join(d, name + '.call'), 'w'))\n"
        "open(os.path.join(d, 'order.log'), 'a').write(name + '\\n')\n"
        "%s\n"
        "sys.stdout.write(%r)\n"
    ) % (sys.executable, str(bindir), name, body, stdout)
    path = bindir / name
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def call_of(bindir, name):
    return json.loads((bindir / (name + ".call")).read_text())


def run(coro):
    return asyncio.run(coro)


def pid_gone(pid, wait=3.0):
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


class TestBuildArgvPlanOnly:
    @pytest.mark.parametrize("family", ["claude", "codex", "grok", "gemini"])
    def test_no_write_or_auto_approve_flags(self, family):
        argv = exec_planner.build_argv(family, "planning", "p", "m", "/w", "high")
        for flag in FORBIDDEN_FLAGS:
            assert flag not in argv

    def test_claude_flags(self):
        argv = exec_planner.build_argv("claude", "planning", "P", "claude-opus-5-5", "/w", "high")
        assert argv[:3] == ["claude", "-p", "P"]
        assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
        assert argv[argv.index("--effort") + 1] == "high"
        assert argv[argv.index("--permission-mode") + 1] == "plan"
        assert argv[argv.index("--tools") + 1] == "Read"

    def test_codex_flags(self):
        argv = exec_planner.build_argv("codex", "planning", "P", "gpt-6-astra", "/w", "high")
        assert argv[:2] == ["codex", "exec"]
        assert argv[argv.index("-s") + 1] == "read-only"
        assert argv[argv.index("--cd") + 1] == "/w"
        assert argv[argv.index("-m") + 1] == "gpt-6-astra"
        assert 'model_reasoning_effort="high"' in argv
        assert argv[-1] == "-"

    def test_grok_flags(self):
        argv = exec_planner.build_argv("grok", "planning", "P", "grok-4.7", "/w", "xhigh")
        assert argv[argv.index("-m") + 1] == "grok-4.7"
        assert argv[argv.index("--reasoning-effort") + 1] == "xhigh"
        assert argv[argv.index("--permission-mode") + 1] == "plan"
        assert argv[argv.index("--cwd") + 1] == "/w"

    def test_gemini_flags_are_doc_based_plan_mode(self):
        argv = exec_planner.build_argv("gemini", "planning", "P", "gemini-3.8-flash", "/w", "high")
        assert argv[argv.index("--approval-mode") + 1] == "plan"

    def test_default_model_is_omitted(self):
        assert "--model" not in exec_planner.build_argv("claude", "planning", "P", "auto", "/w")

    def test_unsupported_family(self):
        with pytest.raises(exec_planner.ExecPlannerError):
            exec_planner.build_argv("invalid", "planning", "t", "m", ".")


class TestExtractPlanJson:
    def test_plain_and_embedded(self):
        assert exec_planner._extract_plan_json(json.dumps(PLAN)) == PLAN
        assert exec_planner._extract_plan_json("pre %s post" % json.dumps(PLAN)) == PLAN

    def test_cli_envelope_result(self):
        env = {"type": "result", "result": "here:\n" + json.dumps(PLAN)}
        assert exec_planner._extract_plan_json(json.dumps(env)) == PLAN

    @pytest.mark.parametrize("text", ['{"data": 1}', "not json", ""])
    def test_invalid(self, text):
        with pytest.raises(ValueError, match="not found or invalid"):
            exec_planner._extract_plan_json(text)


class TestRunPlanner:
    @pytest.mark.parametrize("family", ["claude", "codex", "grok", "gemini"])
    def test_ok_argv_uses_model_roles_resolve(self, bindir, family):
        fake_cli(bindir, family)
        res = run(exec_planner.run_planner(family, "planning", "do it", cwd=str(bindir)))
        assert res.reason_code == "ok" and res.plan == PLAN
        want = model_roles.resolve(family, "planning")
        assert (res.model, res.effort) == (want["model"], want["effort"])
        call = call_of(bindir, family)
        assert want["model"] in call["argv"]
        if family != "gemini":
            assert any(want["effort"] in a for a in call["argv"])
        prompt_text = call["stdin"] if family == "codex" else " ".join(call["argv"])
        assert "do it" in prompt_text
        assert "turbo --apply -" in prompt_text

    def test_role_changes_model(self, bindir):
        fake_cli(bindir, "claude")
        run(exec_planner.run_planner("claude", "execution", "x", cwd=str(bindir)))
        assert model_roles.resolve("claude", "execution")["model"] in call_of(bindir, "claude")["argv"]

    def test_bad_role(self, bindir):
        res = run(exec_planner.run_planner("claude", "nope", "x"))
        assert res.reason_code == "bad_role"

    def test_cli_missing(self, bindir, monkeypatch):
        monkeypatch.setenv("PATH", str(bindir))
        res = run(exec_planner.run_planner("claude", "planning", "x"))
        assert res.reason_code == "cli_missing"

    def test_bad_plan(self, bindir):
        fake_cli(bindir, "claude", stdout="no json here")
        assert run(exec_planner.run_planner("claude", "planning", "x")).reason_code == "bad_plan"

    def test_auth_error(self, bindir):
        fake_cli(bindir, "claude", body="sys.stderr.write('Authentication failed: please login'); sys.exit(1)")
        assert run(exec_planner.run_planner("claude", "planning", "x")).reason_code == "auth_error"

    def test_process_error(self, bindir):
        fake_cli(bindir, "claude", body="sys.exit(3)")
        res = run(exec_planner.run_planner("claude", "planning", "x"))
        assert res.reason_code == "process_error" and res.error == "exit 3"

    def test_timeout(self, bindir):
        fake_cli(bindir, "claude", body="time.sleep(60)")
        res = run(exec_planner.run_planner("claude", "planning", "x", timeout_sec=0.5, grace_sec=1.0))
        assert res.reason_code == "timeout"


class TestTreeKill:
    def test_timeout_kills_hung_child(self, bindir):
        pidfile = bindir / "child.pid"
        body = (
            "c = subprocess.Popen(['sleep', '60'])\n"
            "open(%r, 'w').write(str(c.pid))\n"
            "time.sleep(60)"
        ) % str(pidfile)
        fake_cli(bindir, "claude", body=body)
        res = run(exec_planner.run_planner("claude", "planning", "x", timeout_sec=1.0, grace_sec=1.0))
        assert res.reason_code == "timeout"
        child = int(pidfile.read_text())
        assert pid_gone(child), "child sleep survived the timeout"
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)

    def test_sigkill_after_grace_when_sigterm_ignored(self, bindir):
        pidfile = bindir / "child.pid"
        body = (
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "c = subprocess.Popen(['sh', '-c', 'trap \"\" TERM; sleep 60'])\n"
            "open(%r, 'w').write(str(c.pid))\n"
            "time.sleep(60)"
        ) % str(pidfile)
        fake_cli(bindir, "claude", body=body)
        started = time.monotonic()
        res = run(exec_planner.run_planner("claude", "planning", "x", timeout_sec=1.0, grace_sec=1.0))
        elapsed = time.monotonic() - started
        assert res.reason_code == "timeout"
        assert elapsed >= 1.9, "SIGKILL must wait for the SIGTERM grace period"
        assert pid_gone(int(pidfile.read_text())), "TERM-ignoring child survived"


class TestFallback:
    def test_falls_through_families_in_env_order(self, bindir, monkeypatch):
        monkeypatch.setenv("SIMPLICIO_EXEC_FAMILIES", "grok,claude,codex")
        fake_cli(bindir, "grok", body="sys.exit(2)")
        fake_cli(bindir, "claude", stdout="garbage")
        fake_cli(bindir, "codex")
        res = run(exec_planner.run_planner_with_fallback("coordination", "x", cwd=str(bindir)))
        assert res.is_ok() and res.family == "codex"
        assert (bindir / "order.log").read_text().split() == ["grok", "claude", "codex"]
        assert model_roles.resolve("codex", "coordination")["model"] in call_of(bindir, "codex")["argv"]

    def test_skips_missing_cli_and_stops_at_first_ok(self, bindir):
        fake_cli(bindir, "codex")
        fake_cli(bindir, "grok")
        res = run(
            exec_planner.run_planner_with_fallback("planning", "x", families=["gemini", "codex", "grok"])
        )
        assert res.family == "codex"
        assert (bindir / "order.log").read_text().split() == ["codex"]

    def test_all_fail_returns_last_result(self, bindir):
        fake_cli(bindir, "claude", stdout="garbage")
        res = run(exec_planner.run_planner_with_fallback("planning", "x", families=["claude", "gemini"]))
        assert res.reason_code == "cli_missing" and res.family == "gemini"

    def test_timeout_falls_through(self, bindir):
        fake_cli(bindir, "claude", body="time.sleep(60)")
        fake_cli(bindir, "codex")
        res = run(
            exec_planner.run_planner_with_fallback(
                "planning", "x", timeout_sec=0.5, families=["claude", "codex"], grace_sec=1.0
            )
        )
        assert res.family == "codex" and res.is_ok()

    def test_bad_role_stops_immediately(self, bindir):
        fake_cli(bindir, "claude")
        res = run(exec_planner.run_planner_with_fallback("nope", "x", families=["claude", "codex"]))
        assert res.reason_code == "bad_role"
        assert not (bindir / "order.log").exists()
