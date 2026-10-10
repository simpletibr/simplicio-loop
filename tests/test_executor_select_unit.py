"""Unit tests for executor_select (issue 1432) and the agy/opencode exec families (issue 1431).

Only fake CLIs on PATH are run. No real model CLI and no OpenRouter call is made.
"""

import asyncio
import json
import stat
import sys

import pytest

from simplicio_loop import exec_planner, executor_select, model_roles

PLAN = {"operations": [{"op": "create", "file": "a.txt", "content": "x"}]}
FORBIDDEN_FLAGS = (
    "--dangerously-bypass-approvals-and-sandbox",
    "--always-approve",
    "--yolo",
    "--auto",
    "bypassPermissions",
    "acceptEdits",
    "accept-edits",
    "workspace-write",
    "danger-full-access",
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def bindir(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    # Only the fakes are on PATH, so no real CLI on the host can be spawned.
    monkeypatch.setenv("PATH", str(d))
    for name in ("SIMPLICIO_EXECUTOR", "SIMPLICIO_EXEC_FAMILIES", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return d


def fake_cli(bindir, name, body="", stdout=None):
    """Install a fake CLI that records its argv under bindir, runs `body`, then prints `stdout`."""
    if stdout is None:
        stdout = json.dumps(PLAN)
    script = (
        "#!%s\n"
        "import json, os, sys\n"
        "d = %r\n"
        "name = %r\n"
        "json.dump({'argv': sys.argv[1:]}, open(os.path.join(d, name + '.call'), 'w'))\n"
        "open(os.path.join(d, 'order.log'), 'a').write(name + '\\n')\n"
        "%s\n"
        "sys.stdout.write(%r)\n"
    ) % (sys.executable, str(bindir), name, body, stdout)
    path = bindir / name
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def call_of(bindir, name):
    return json.loads((bindir / (name + ".call")).read_text())["argv"]


def order_of(bindir):
    log = bindir / "order.log"
    return log.read_text().split() if log.exists() else []


# --- 1. Executor selection --------------------------------------------------------------------------------------


class TestSelectMode:
    def test_default_is_exec(self):
        assert executor_select.select_mode({}) == "exec"

    @pytest.mark.parametrize("value", ["host", "exec"])
    def test_host_and_exec_are_selected_by_env(self, value):
        assert executor_select.select_mode({"SIMPLICIO_EXECUTOR": value}) == value

    def test_blank_env_falls_back_to_default(self):
        assert executor_select.select_mode({"SIMPLICIO_EXECUTOR": "  "}) == "exec"

    def test_unknown_mode_fails_closed(self):
        with pytest.raises(executor_select.ExecutorSelectError, match="unknown executor"):
            executor_select.select_mode({"SIMPLICIO_EXECUTOR": "turbo"})

    def test_openrouter_without_key_is_refused(self):
        with pytest.raises(executor_select.ExecutorSelectError, match="OPENROUTER_API_KEY"):
            executor_select.select_mode({"SIMPLICIO_EXECUTOR": "openrouter"})

    def test_openrouter_with_key_is_selected(self):
        env = {"SIMPLICIO_EXECUTOR": "openrouter", "OPENROUTER_API_KEY": "k"}
        assert executor_select.select_mode(env) == "openrouter"


class TestExecFamilies:
    def test_default_order_when_unset(self):
        assert executor_select.exec_families({}) == exec_planner.DEFAULT_FAMILIES

    def test_env_order_is_kept(self):
        env = {"SIMPLICIO_EXEC_FAMILIES": "agy, opencode ,claude"}
        assert executor_select.exec_families(env) == ["agy", "opencode", "claude"]

    def test_unknown_family_is_refused(self):
        with pytest.raises(executor_select.ExecutorSelectError, match="unknown family"):
            executor_select.exec_families({"SIMPLICIO_EXEC_FAMILIES": "claude,mystery"})

    def test_openrouter_is_never_an_exec_family(self):
        env = {"SIMPLICIO_EXEC_FAMILIES": "claude,openrouter", "OPENROUTER_API_KEY": "k"}
        with pytest.raises(executor_select.ExecutorSelectError, match="openrouter"):
            executor_select.exec_families(env)


class TestOpenRouterNeverImplicit:
    def test_exec_mode_with_key_present_does_not_pick_openrouter(self):
        env = {"OPENROUTER_API_KEY": "k"}
        resolved = executor_select.resolve(env)
        assert resolved["mode"] == "exec"
        assert "openrouter" not in resolved["families"]

    def test_host_mode_has_no_families_and_no_openrouter(self):
        resolved = executor_select.resolve({"SIMPLICIO_EXECUTOR": "host", "OPENROUTER_API_KEY": "k"})
        assert resolved == {"mode": "host", "families": []}

    def test_run_refuses_non_exec_modes(self, bindir):
        with pytest.raises(executor_select.ExecutorSelectError, match="exec"):
            run(executor_select.run_with_fallback("planning", "x", env={"SIMPLICIO_EXECUTOR": "host"}, repo_root=bindir))
        assert order_of(bindir) == []


# --- 2. Quota classification and fallback -----------------------------------------------------------------------


class TestClassifyFailure:
    @pytest.mark.parametrize(
        "stderr, expected",
        [
            ("Error: insufficient_quota: you exceeded your current quota", "quota_exhausted"),
            ("Your credit balance is too low to access the API", "quota_exhausted"),
            ("Usage limit reached. Resets at 5pm", "quota_exhausted"),
            ("429 rate limit exceeded, retry later", "rate_limited"),
            ("Too many requests", "rate_limited"),
            ("Authentication failed: please login", "auth_error"),
            ("401 Unauthorized", "auth_error"),
        ],
    )
    def test_stderr_patterns(self, stderr, expected):
        assert exec_planner.classify_failure(1, stderr, "") == expected

    def test_quota_wins_over_rate_limit_wording(self):
        assert exec_planner.classify_failure(1, "quota exceeded (rate limit)", "") == "quota_exhausted"

    def test_stdout_is_scanned_too(self):
        assert exec_planner.classify_failure(1, "", '{"error": "usage limit"}') == "quota_exhausted"

    def test_generic_failure_is_unclassified(self):
        assert exec_planner.classify_failure(3, "segfault", "") is None

    def test_success_is_never_classified(self):
        assert exec_planner.classify_failure(0, "quota", "") is None


class TestQuotaFallback:
    def test_quota_on_first_family_falls_through_and_records_reason(self, bindir):
        fake_cli(bindir, "claude", body="sys.stderr.write('quota exceeded'); sys.exit(1)")
        fake_cli(bindir, "codex")
        env = {"SIMPLICIO_EXEC_FAMILIES": "claude,codex"}
        res = run(executor_select.run_with_fallback("planning", "x", env=env, cwd=str(bindir), repo_root=bindir))
        assert res["status"] == "ok" and res["family"] == "codex"
        assert order_of(bindir) == ["claude", "codex"]
        assert res["attempts"][0] == {
            "family": "claude",
            "reason_code": "quota_exhausted",
            "error": res["attempts"][0]["error"],
        }

    def test_rate_limit_falls_through(self, bindir):
        fake_cli(bindir, "claude", body="sys.stderr.write('rate limit'); sys.exit(1)")
        fake_cli(bindir, "codex")
        env = {"SIMPLICIO_EXEC_FAMILIES": "claude,codex"}
        res = run(executor_select.run_with_fallback("planning", "x", env=env, cwd=str(bindir), repo_root=bindir))
        assert res["family"] == "codex"
        assert res["attempts"][0]["reason_code"] == "rate_limited"

    def test_missing_cli_falls_through(self, bindir):
        fake_cli(bindir, "codex")
        env = {"SIMPLICIO_EXEC_FAMILIES": "agy,codex"}
        res = run(executor_select.run_with_fallback("planning", "x", env=env, cwd=str(bindir), repo_root=bindir))
        assert res["family"] == "codex"
        assert res["attempts"][0] == {"family": "agy", "reason_code": "cli_missing", "error": res["attempts"][0]["error"]}

    def test_all_exhausted_is_blocked(self, bindir):
        fake_cli(bindir, "claude", body="sys.stderr.write('quota'); sys.exit(1)")
        fake_cli(bindir, "codex", body="sys.stderr.write('rate limit'); sys.exit(1)")
        env = {"SIMPLICIO_EXEC_FAMILIES": "claude,codex"}
        res = run(executor_select.run_with_fallback("planning", "x", env=env, cwd=str(bindir), repo_root=bindir))
        assert res["status"] == "blocked"
        assert res["reason_code"] == "all_executors_exhausted"
        assert [a["reason_code"] for a in res["attempts"]] == ["quota_exhausted", "rate_limited"]
        assert res["plan"] is None

    def test_bad_role_stops_without_trying_next_family(self, bindir):
        fake_cli(bindir, "claude")
        fake_cli(bindir, "codex")
        env = {"SIMPLICIO_EXEC_FAMILIES": "claude,codex"}
        res = run(executor_select.run_with_fallback("nope", "x", env=env, cwd=str(bindir), repo_root=bindir))
        assert res["status"] == "blocked" and res["reason_code"] == "bad_role"
        assert order_of(bindir) == []


# --- 3. agy and opencode families -------------------------------------------------------------------------------


class TestAgyAndOpencodeArgv:
    def test_agy_is_plan_mode_sandboxed_json(self):
        argv = exec_planner.build_argv("agy", "planning", "p", "default", "/w", "high")
        assert argv[:3] == ["agy", "-p", "p"]
        assert argv[argv.index("--mode") + 1] == "plan"
        assert "--sandbox" in argv
        assert argv[argv.index("--output-format") + 1] == "json"

    def test_agy_passes_a_real_model_and_the_role_effort(self):
        argv = exec_planner.build_argv("agy", "planning", "p", "agy-model-x", "/w", "high")
        assert argv[argv.index("--model") + 1] == "agy-model-x"
        assert argv[argv.index("--effort") + 1] == "high"

    def test_agy_omits_effort_when_the_role_has_none(self):
        argv = exec_planner.build_argv("agy", "planning", "p", "default", "/w", "")
        assert "--effort" not in argv

    def test_opencode_passes_model_and_effort_as_variant(self):
        argv = exec_planner.build_argv("opencode", "planning", "p", "prov/model", "/w", "high")
        assert argv[argv.index("-m") + 1] == "prov/model"
        assert argv[argv.index("--variant") + 1] == "high"

    def test_opencode_omits_variant_without_effort(self):
        argv = exec_planner.build_argv("opencode", "planning", "p", "default", "/w", "")
        assert "--variant" not in argv

    def test_opencode_is_run_with_json_format_and_plan_agent(self):
        argv = exec_planner.build_argv("opencode", "planning", "p", "default", "/w", "high")
        assert argv[:3] == ["opencode", "run", "p"]
        assert argv[argv.index("--format") + 1] == "json"
        assert argv[argv.index("--agent") + 1] == "plan"

    @pytest.mark.parametrize("family", ["agy", "opencode"])
    def test_default_model_is_flag_free(self, family):
        argv = exec_planner.build_argv(family, "planning", "p", "default", "/w", "high")
        assert "-m" not in argv and "--model" not in argv

    @pytest.mark.parametrize("family", ["agy", "opencode"])
    def test_no_write_or_auto_approve_flags(self, family):
        argv = exec_planner.build_argv(family, "planning", "p", "default", "/w", "high")
        for flag in FORBIDDEN_FLAGS:
            assert flag not in argv

    @pytest.mark.parametrize("family", ["agy", "opencode"])
    def test_model_roles_resolve_with_default_model(self, family):
        for role in model_roles.ROLES:
            assert model_roles.resolve(family, role)["model"] == "default"

    def test_agy_runs_through_fake_cli(self, bindir):
        fake_cli(bindir, "agy")
        res = run(exec_planner.run_planner("agy", "execution", "x", cwd=str(bindir), repo_root=bindir))
        assert res.is_ok() and res.family == "agy"
        argv = call_of(bindir, "agy")
        assert argv[argv.index("--mode") + 1] == "plan"
        assert "-m" not in argv

    def test_opencode_runs_through_fake_cli(self, bindir):
        fake_cli(bindir, "opencode")
        res = run(exec_planner.run_planner("opencode", "execution", "x", cwd=str(bindir), repo_root=bindir))
        assert res.is_ok() and res.family == "opencode"
        assert call_of(bindir, "opencode")[0] == "run"


class TestSelectionPerEnvValueEndToEnd:
    def test_env_order_decides_which_fake_runs(self, bindir):
        fake_cli(bindir, "agy")
        fake_cli(bindir, "opencode")
        env = {"SIMPLICIO_EXEC_FAMILIES": "opencode,agy"}
        res = run(executor_select.run_with_fallback("execution", "x", env=env, cwd=str(bindir), repo_root=bindir))
        assert res["family"] == "opencode"
        assert order_of(bindir) == ["opencode"]
