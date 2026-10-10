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
    # Only the fakes are on PATH, so a real claude/codex/grok/gemini on the host can never be run.
    monkeypatch.setenv("PATH", str(d))
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


def _alive(pid):
    """True while the pid runs. A zombie is dead: its parent (here PID 1, which does not reap) just has not waited."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


def pid_gone(pid, wait=3.0):
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


class TestHermeticPath:
    def test_only_the_fakes_are_on_path(self, bindir):
        assert os.environ["PATH"].split(os.pathsep) == [str(bindir)]


class TestBuildArgvPlanOnly:
    @pytest.mark.parametrize("family", ["claude", "codex", "grok", "gemini"])
    def test_no_write_or_auto_approve_flags(self, family):
        argv = exec_planner.build_argv(family, "planning", "p", "m", "/w", "high", schema_file="/s/p.json")
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
        argv = exec_planner.build_argv("codex", "planning", "P", "gpt-6-astra", "/w", "high", schema_file="/s/p.json")
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


class TestBuildArgvAgyOpencode:
    def test_agy_flags_are_verified_plan_only(self):
        argv = exec_planner.build_argv("agy", "planning", "P", "gemini-3.8-pro", "/w", "high")
        assert argv[:3] == ["agy", "-p", "P"]
        assert argv[argv.index("--model") + 1] == "gemini-3.8-pro"
        assert argv[argv.index("--effort") + 1] == "high"
        assert argv[argv.index("--mode") + 1] == "plan"
        assert "--sandbox" in argv
        assert argv[argv.index("--output-format") + 1] == "json"
        assert "--dangerously-skip-permissions" not in argv

    def test_agy_default_model_omitted_effort_kept(self):
        argv = exec_planner.build_argv("agy", "planning", "P", "auto", "/w", "low")
        assert "--model" not in argv
        assert argv[argv.index("--effort") + 1] == "low"

    def test_opencode_flags(self):
        argv = exec_planner.build_argv("opencode", "planning", "P", "anthropic/claude-opus-5-5", "/w", "max")
        assert argv[:3] == ["opencode", "run", "P"]
        assert argv[argv.index("--agent") + 1] == "plan"
        assert argv[argv.index("--format") + 1] == "json"
        assert argv[argv.index("-m") + 1] == "anthropic/claude-opus-5-5"
        assert argv[argv.index("--variant") + 1] == "max"
        assert "--auto" not in argv

    def test_opencode_deny_config_denies_bash_webfetch_edit(self):
        cfg = exec_planner.OPENCODE_DENY_CONFIG
        assert cfg["permission"] == {"bash": "deny", "webfetch": "deny", "edit": "deny"}


class TestOpencodeDenyConfigEnv:
    CAPTURE = (
        "cfg = os.environ.get('OPENCODE_CONFIG')\n"
        "json.dump({'path': cfg, 'text': open(cfg).read() if cfg else None}, open(os.path.join(d, 'cfg.json'), 'w'))"
    )

    def test_opencode_gets_temp_config_with_denies_then_cleaned_up(self, bindir, monkeypatch):
        monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
        fake_cli(bindir, "opencode", body=self.CAPTURE)
        res = run(exec_planner.run_planner("opencode", "planning", "x", cwd=str(bindir)))
        assert res.reason_code == "ok" and res.plan == PLAN
        seen = json.loads((bindir / "cfg.json").read_text())
        assert seen["path"]
        assert json.loads(seen["text"])["permission"] == {"bash": "deny", "webfetch": "deny", "edit": "deny"}
        assert not os.path.exists(seen["path"])

    def test_temp_config_removed_even_on_failure(self, bindir, monkeypatch):
        monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
        fake_cli(bindir, "opencode", body=self.CAPTURE + "\nsys.exit(3)")
        res = run(exec_planner.run_planner("opencode", "planning", "x", cwd=str(bindir)))
        assert res.reason_code == "process_error"
        assert not os.path.exists(json.loads((bindir / "cfg.json").read_text())["path"])

    def test_other_families_get_no_opencode_config(self, bindir, monkeypatch):
        monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
        fake_cli(bindir, "claude", body=self.CAPTURE.replace("open(cfg).read() if cfg else None", "None"))
        run(exec_planner.run_planner("claude", "planning", "x", cwd=str(bindir)))
        assert json.loads((bindir / "cfg.json").read_text())["path"] is None


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


class TestRaw:
    """The planner's own text rides on the result (#1644): the plan is cut out of it, the text is not lost."""

    def test_ok_keeps_the_whole_cli_text(self, bindir):
        text = "thinking...\n" + json.dumps(PLAN) + "\ndone\n"
        fake_cli(bindir, "claude", stdout=text)
        res = run(exec_planner.run_planner("claude", "planning", "x"))
        assert res.is_ok() and res.raw == text and res.to_dict()["raw"] == text

    def test_bad_plan_keeps_the_text(self, bindir):
        fake_cli(bindir, "claude", stdout="no json here")
        res = run(exec_planner.run_planner("claude", "planning", "x"))
        assert res.reason_code == "bad_plan" and res.raw == "no json here"

    def test_a_failed_cli_keeps_stdout_and_stderr(self, bindir):
        fake_cli(bindir, "claude", body="sys.stdout.write('half'); sys.stdout.flush(); sys.stderr.write('boom'); sys.exit(3)")
        res = run(exec_planner.run_planner("claude", "planning", "x"))
        assert res.reason_code == "process_error" and "half" in res.raw and "boom" in res.raw

    def test_auth_failure_keeps_the_text(self, bindir):
        fake_cli(bindir, "claude", body="sys.stderr.write('Authentication failed: please login'); sys.exit(1)")
        assert "Authentication failed" in run(exec_planner.run_planner("claude", "planning", "x")).raw

    def test_no_answer_means_no_raw(self, bindir):
        assert run(exec_planner.run_planner("claude", "planning", "x")).raw is None  # cli_missing
        fake_cli(bindir, "claude", body="time.sleep(60)")
        assert run(exec_planner.run_planner("claude", "planning", "x", timeout_sec=0.5, grace_sec=1.0)).raw is None


class TestTreeKill:
    def test_timeout_kills_hung_child(self, bindir):
        pidfile = bindir / "child.pid"
        body = (
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "open(%r, 'w').write(str(c.pid))\n"
            "time.sleep(60)"
        ) % str(pidfile)
        fake_cli(bindir, "claude", body=body)
        res = run(exec_planner.run_planner("claude", "planning", "x", timeout_sec=1.0, grace_sec=1.0))
        assert res.reason_code == "timeout"
        child = int(pidfile.read_text())
        assert pid_gone(child), "child sleep survived the timeout"
        assert not _alive(child)

    def test_sigkill_after_grace_when_sigterm_ignored(self, bindir):
        # The fake CLI and its child ignore SIGTERM, so only the SIGKILL step ends them. Without it the run waits for
        # the 60 s sleep, and the elapsed bound below fails.
        pidfile = bindir / "child.pid"
        body = (
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "c = subprocess.Popen(['/bin/sh', '-c', 'trap \"\" TERM; sleep 60'])\n"
            "open(%r, 'w').write(str(c.pid))\n"
            "time.sleep(60)"
        ) % str(pidfile)
        fake_cli(bindir, "claude", body=body)
        started = time.monotonic()
        res = run(exec_planner.run_planner("claude", "planning", "x", timeout_sec=1.0, grace_sec=0.5))
        elapsed = time.monotonic() - started
        assert res.reason_code == "timeout"
        assert 1.0 + 0.5 <= elapsed < 1.0 + 0.5 + 1.0, "SIGTERM grace, then SIGKILL, within grace+1s after the timeout"
        assert pid_gone(int(pidfile.read_text()), wait=0.5), "TERM-ignoring child survived SIGKILL"


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
