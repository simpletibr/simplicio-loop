"""Structured output at the origin (issue #1612, PR B): provider response_format, CLI schema flags, the receipt."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from simplicio_loop import exec_planner, plan_scope, structured_output as so, turbo_provider
from simplicio_loop.cli_impl import main as cli_main

PINNED = "deepseek/deepseek-v4.1-flash"
PLAN_OK = json.dumps({"operations": [{"path": "a.py", "find": "", "replace": "x = 1\n"}]})
BANNED = {"$schema", "$id", "title", "if", "then", "else"}


def _nodes(schema):
    yield schema
    for sub in (schema.get("properties") or {}).values():
        yield from _nodes(sub)
    if isinstance(schema.get("items"), dict):
        yield from _nodes(schema["items"])


def _errors(kind, answer):
    return list(Draft202012Validator(so.origin_schema(kind)).iter_errors(answer))


# --- the origin schema: the contract, narrowed to what every CLI and provider takes --------------------------------

@pytest.mark.parametrize("kind", ["plan", "verdict"])
def test_origin_schema_is_closed_requires_every_property_and_keeps_to_portable_keywords(kind):
    for node in _nodes(so.origin_schema(kind)):
        assert not BANNED & set(node)
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert sorted(node["required"]) == sorted(node["properties"])


def test_origin_plan_answer_is_valid_for_the_contract_too():
    answer = {"operations": [{"path": "a.py", "find": "", "replace": "x"}], "need": []}
    assert _errors("plan", answer) == []
    assert plan_scope.validate_response(json.dumps(answer), "plan") == []


def test_origin_verdict_answer_is_valid_for_the_contract_too():
    answer = {"verdict": "fail", "findings": [{"severity": "minor", "path": "a.py", "line": 1, "note": ""}]}
    assert _errors("verdict", answer) == []
    assert plan_scope.validate_response(json.dumps(answer), "verdict") == []


def test_origin_schema_keeps_the_contract_limits():
    op = {"path": "a.py", "find": "", "replace": "x"}
    assert _errors("plan", {"operations": [{**op, "extra": 1}], "need": []})
    assert _errors("plan", {"operations": [{**op, "path": "p" * 261}], "need": []})
    assert _errors("plan", {"operations": [op] * 41, "need": []})
    assert _errors("plan", {"operations": [op], "need": [], "prose": "x"})
    assert _errors("verdict", {"verdict": "maybe", "findings": []})


def test_origin_schema_is_a_copy_the_caller_cannot_use_to_edit_the_contract():
    so.origin_schema("plan")["properties"].clear()
    assert so.origin_schema("plan")["properties"]
    so.origin_schema("verdict")["properties"]["verdict"]["enum"].clear()  # a list the contract also holds
    assert plan_scope.RESPONSE_SCHEMAS["verdict"]["properties"]["verdict"]["enum"] == ["pass", "fail", "blocked"]


# --- the plan contract can ask for more lines (the watcher `need` flow) ---------------------------------------------

def test_plan_may_ask_for_more_lines_instead_of_editing():
    ask = {"operations": [], "need": [{"path": "a.py", "start": 10, "end": 40}]}
    assert plan_scope.validate_response(json.dumps(ask), "plan") == []


@pytest.mark.parametrize("text", ['{"operations":[]}', '{"operations":[],"need":[]}'])
def test_empty_plan_without_a_real_need_is_still_rejected(text):
    assert [v.split(":", 1)[0] for v in plan_scope.validate_response(text, "plan")] == ["empty"]


def test_need_is_closed_and_bounded():
    item = {"path": "a.py", "start": 1, "end": 2}
    assert plan_scope.validate_response(json.dumps({"operations": [], "need": [item] * 8}), "plan") == []
    for need in ([item] * 9, [{**item, "x": 1}], [{**item, "start": 0}], [{"path": "a.py", "start": 1}]):
        assert plan_scope.validate_response(json.dumps({"operations": [], "need": need}), "plan")


# --- CLI capabilities -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("family", ["claude", "agy", "grok"])
def test_inline_flag_carries_the_origin_schema(family):
    flags = so.cli_flags(family)
    assert flags[0] == "--json-schema" and len(flags) == 2
    assert json.loads(flags[1]) == so.origin_schema("plan")
    assert not so.cli_needs_file(family)


def test_codex_flag_names_a_schema_file():
    assert so.cli_needs_file("codex")
    assert so.cli_flags("codex", "/s/plan.json") == ["--output-schema", "/s/plan.json"]
    with pytest.raises(ValueError):
        so.cli_flags("codex")


@pytest.mark.parametrize("family", ["opencode", "gemini", "nope"])
def test_no_flag_means_nothing_is_added(family):
    assert so.cli_flags(family) == [] and not so.cli_needs_file(family)


@pytest.mark.parametrize("family, expected", [
    ("claude", ("enforced", "flag:--json-schema")),
    ("agy", ("enforced", "flag:--json-schema")),
    ("grok", ("enforced", "flag:--json-schema")),
    ("codex", ("enforced", "flag:--output-schema")),
    ("opencode", ("validated_only", "no_schema_flag")),
    ("gemini", ("validated_only", "cli_not_measured")),
    ("nope", ("validated_only", "unknown_family")),
])
def test_receipt_of_each_cli(family, expected):
    assert so.cli_receipt(family) == expected


# --- the flags reach the argv of the planner -----------------------------------------------------------------------

@pytest.mark.parametrize("family", ["claude", "agy", "grok"])
def test_argv_of_inline_clis_carries_the_schema(family):
    argv = exec_planner.build_argv(family, "planning", "P", "m", "/w", "high")
    assert json.loads(argv[argv.index("--json-schema") + 1]) == so.origin_schema("plan")


def test_argv_of_codex_names_the_schema_file_before_the_stdin_marker():
    argv = exec_planner.build_argv("codex", "planning", "P", "m", "/w", "high", schema_file="/s/p.json")
    assert argv[argv.index("--output-schema") + 1] == "/s/p.json"
    assert argv.index("--output-schema") < len(argv) - 1 and argv[-1] == "-"


def test_argv_of_codex_without_the_file_is_refused():
    with pytest.raises(exec_planner.ExecPlannerError):
        exec_planner.build_argv("codex", "planning", "P", "m", "/w", "high")


@pytest.mark.parametrize("family", ["opencode", "gemini"])
def test_argv_without_a_flag_has_no_schema_option(family):
    argv = exec_planner.build_argv(family, "planning", "P", "m", "/w", "high")
    assert not [a for a in argv if "schema" in a]


# --- run_planner: the schema file, the receipt ----------------------------------------------------------------------

@pytest.fixture
def bindir(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    monkeypatch.setenv("PATH", str(d))  # only the fakes: a real CLI can never run
    return d


def _fake(bindir, name, body="", exit_code=0):
    """A fake CLI that records its argv (and the schema file it was given) in ``seen.json`` next to the cwd."""
    script = (
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "seen = {'argv': sys.argv[1:]}\n"
        "if '--output-schema' in sys.argv:\n"
        "    path = sys.argv[sys.argv.index('--output-schema') + 1]\n"
        "    seen['schema_path'] = path\n"
        "    seen['schema'] = json.load(open(path))\n"
        "json.dump(seen, open('seen.json', 'w'))\n"
        f"{body}\n"
        f"print({PLAN_OK!r})\n"
        f"sys.exit({exit_code})\n"
    )
    path = bindir / name
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def _run(family, tmp_path, **kwargs):
    return asyncio.run(exec_planner.run_planner(family, "planning", "x", cwd=str(tmp_path), **kwargs))


def test_codex_schema_file_exists_during_the_run_inside_config_dir_and_is_removed_after(bindir, tmp_path):
    _fake(bindir, "codex")
    cfg = tmp_path / "cfg"
    result = _run("codex", tmp_path, config_dir=str(cfg))
    seen = json.loads((tmp_path / "seen.json").read_text())
    assert result.is_ok() and seen["schema"] == so.origin_schema("plan")
    assert Path(seen["schema_path"]).parent == cfg
    assert not Path(seen["schema_path"]).exists()


@pytest.mark.parametrize("family", ["claude", "grok", "agy"])
def test_inline_cli_gets_the_flag_and_the_receipt_says_enforced(bindir, tmp_path, family):
    _fake(bindir, family)
    result = _run(family, tmp_path)
    seen = json.loads((tmp_path / "seen.json").read_text())
    assert json.loads(seen["argv"][seen["argv"].index("--json-schema") + 1]) == so.origin_schema("plan")
    assert (result.structured_output, result.structured_reason) == ("enforced", "flag:--json-schema")
    assert result.to_dict()["structured_output"] == "enforced"
    assert result.to_dict()["structured_reason"] == "flag:--json-schema"


def test_codex_receipt_says_enforced_with_its_flag(bindir, tmp_path):
    _fake(bindir, "codex")
    result = _run("codex", tmp_path)
    assert (result.structured_output, result.structured_reason) == ("enforced", "flag:--output-schema")


def test_opencode_runs_without_a_flag_and_the_receipt_says_validated_only(bindir, tmp_path):
    _fake(bindir, "opencode")
    result = _run("opencode", tmp_path)
    seen = json.loads((tmp_path / "seen.json").read_text())
    assert not [a for a in seen["argv"] if "schema" in a]
    assert (result.structured_output, result.structured_reason) == ("validated_only", "no_schema_flag")


def test_a_failed_run_keeps_the_receipt_of_what_was_asked(bindir, tmp_path):
    _fake(bindir, "claude", exit_code=3)
    result = _run("claude", tmp_path)
    assert result.reason_code == "process_error"
    assert (result.structured_output, result.structured_reason) == ("enforced", "flag:--json-schema")


def test_a_cli_that_never_ran_has_no_receipt(bindir, tmp_path):
    result = _run("claude", tmp_path)  # no fake on PATH
    assert result.reason_code == "cli_missing"
    assert (result.structured_output, result.structured_reason) == ("", "")


# --- the flags are the ones the installed CLI lists (measured with --help) ------------------------------------------

HELP = {
    "claude": (["claude", "--help"], "--json-schema"),
    "codex": (["codex", "exec", "--help"], "--output-schema"),
    "agy": (["agy", "--help"], "--json-schema"),
    "grok": (["grok", "--help"], "--json-schema"),
}


def _help(cmd):
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    return done.stdout + done.stderr


@pytest.mark.parametrize("family", sorted(HELP))
def test_flag_is_listed_by_the_installed_cli(family):
    cmd, flag = HELP[family]
    if not shutil.which(cmd[0]):
        pytest.skip(f"{cmd[0]} is not installed")
    assert flag in _help(cmd)
    assert flag in so.cli_flags(family, "/s/p.json")


def test_opencode_run_help_lists_no_schema_flag():
    if not shutil.which("opencode"):
        pytest.skip("opencode is not installed")
    assert "schema" not in _help(["opencode", "run", "--help"]).lower()


# --- provider: strict json_schema only for a model that declares it, max_tokens from the task ----------------------

def test_model_in_the_table_gets_a_strict_json_schema(tmp_path):
    fields = so.provider_fields(PINNED, [], tmp_path)
    assert fields["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "simplicio_model_plan_v1", "strict": True, "schema": so.origin_schema("plan")},
    }


def test_model_outside_the_table_gets_no_response_format_but_keeps_max_tokens(tmp_path):
    fields = so.provider_fields("openai/gpt-4o-mini", [], tmp_path)
    assert "response_format" not in fields and fields["max_tokens"] == so.MIN_TOKENS


def test_provider_receipt():
    assert so.provider_receipt(PINNED) == ("enforced", "model_declares_structured_outputs")
    assert so.provider_receipt("openai/gpt-4o-mini") == ("validated_only", "model_not_in_table")


def test_the_table_is_small():
    assert 1 <= len(so.PROVIDER_MODELS) <= 6 and PINNED in so.PROVIDER_MODELS
    assert PINNED == turbo_provider.DEFAULT_MODEL


def _task(target=None, context=()):
    return {"index": 1, "text": "t", "target": target, "context": list(context)}


def test_max_tokens_floor_when_the_task_names_nothing_existing(tmp_path):
    assert so.max_tokens_for([], tmp_path) == so.MIN_TOKENS == 2048


def test_max_tokens_for_an_existing_target_is_twice_its_tokens(tmp_path):
    (tmp_path / "a.py").write_bytes(b"x" * 3000)  # find + replace may both be the whole file: 2 x 1000 tokens
    assert so.max_tokens_for([_task("a.py")], tmp_path) == 2048 + 2000


def test_max_tokens_for_a_new_target_or_no_target_is_the_creation_allowance(tmp_path):
    assert so.max_tokens_for([_task("new.py")], tmp_path) == 2048 + 4096
    assert so.max_tokens_for([_task(None)], tmp_path) == 2048 + 4096


def test_max_tokens_one_file_is_bounded_and_a_file_counts_once(tmp_path):
    (tmp_path / "big.py").write_bytes(b"x" * 90000)
    assert so.max_tokens_for([_task("big.py")], tmp_path) == 2048 + 6144
    assert so.max_tokens_for([_task("big.py"), _task("x.py", ["big.py"])], tmp_path) == 2048 + 6144 + 4096


def test_max_tokens_counts_existing_context_but_skips_a_missing_one(tmp_path):
    (tmp_path / "c.py").write_bytes(b"x" * 300)
    assert so.max_tokens_for([_task("new.py", ["c.py", "gone.py"])], tmp_path) == 2048 + 4096 + 200


def test_max_tokens_is_capped(tmp_path):
    tasks = [_task(f"n{i}.py") for i in range(10)]
    assert so.max_tokens_for(tasks, tmp_path) == so.MAX_TOKENS == 16384


# --- turbo_provider.complete sends them ----------------------------------------------------------------------------

def _post_bodies(monkeypatch):
    bodies = []

    async def post(body, key, session_id, timeout):
        bodies.append(dict(body))
        return {"ok": True, "content": "{}", "latency_s": 0.0}

    monkeypatch.setattr(turbo_provider, "_post", post)
    return bodies


def _complete(**kwargs):
    return asyncio.run(turbo_provider.complete("a", [], session_id="s", api_key="k", hedge=0, **kwargs))


def test_complete_sends_response_format_and_max_tokens(monkeypatch):
    bodies = _post_bodies(monkeypatch)
    fmt = {"type": "json_schema", "json_schema": {"name": "n", "strict": True, "schema": {}}}
    _complete(response_format=fmt, max_tokens=500)
    assert bodies[0]["response_format"] == fmt and bodies[0]["max_tokens"] == 500


def test_complete_without_response_format_sends_none(monkeypatch):
    bodies = _post_bodies(monkeypatch)
    _complete(max_tokens=500)
    assert "response_format" not in bodies[0]


def test_the_one_token_warm_up_never_carries_a_response_format(monkeypatch):
    bodies = _post_bodies(monkeypatch)
    _complete(response_format={"type": "json_schema"}, max_tokens=1)
    assert "response_format" not in bodies[0] and bodies[0]["max_tokens"] == 1


# --- turbo provider mode binds them and reports the receipt --------------------------------------------------------

def _provider_run(tmp_path, monkeypatch, capsys, model=None):
    (tmp_path / "a.py").write_bytes(b"x" * 3000)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    if model:
        monkeypatch.setenv("SIMPLICIO_TURBO_MODEL", model)
    else:
        monkeypatch.delenv("SIMPLICIO_TURBO_MODEL", raising=False)
    seen = []

    async def fake_complete(arm, messages, **kwargs):
        seen.append(kwargs)
        return {"ok": True, "content": PLAN_OK}

    async def fake_run_turbo(root, tasks, complete):
        await complete("simplicio", [{"role": "user", "content": "x"}])
        await complete("simplicio", [{"role": "user", "content": "w"}], max_tokens=1)
        return {"commands": [], "llm_calls": [], "outcomes": [], "applied_all": True}

    monkeypatch.setattr(turbo_provider, "complete", fake_complete)
    monkeypatch.setattr("simplicio_loop.turbo.run_turbo", fake_run_turbo)
    cli_main(["turbo", "--provider", "openrouter", "--repo", str(tmp_path), "--task", "fix a.py"])
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1]), seen


def test_provider_run_binds_the_task_budget_and_the_schema_and_reports_enforced(tmp_path, monkeypatch, capsys):
    out, seen = _provider_run(tmp_path, monkeypatch, capsys)
    assert seen[0]["max_tokens"] == 2048 + 2000
    assert seen[0]["response_format"]["json_schema"]["schema"] == so.origin_schema("plan")
    assert seen[1]["max_tokens"] == 1  # the caller's own value wins
    assert (out["structured_output"], out["structured_reason"]) == ("enforced", "model_declares_structured_outputs")


def test_provider_run_with_an_unlisted_model_is_validated_only_and_still_bounded(tmp_path, monkeypatch, capsys):
    out, seen = _provider_run(tmp_path, monkeypatch, capsys, model="openai/gpt-4o-mini")
    assert "response_format" not in seen[0] and seen[0]["max_tokens"] == 2048 + 2000
    assert (out["structured_output"], out["structured_reason"]) == ("validated_only", "model_not_in_table")


# --- the watcher keeps the receipt in the role step it writes -----------------------------------------------------

def test_watcher_step_record_carries_the_receipt(tmp_path):
    from simplicio_loop import execution_report
    from simplicio_loop.watcher247 import host_mode

    planned = exec_planner.PlannerResult("ok", "claude", "planning", "m", "high", structured=("enforced", "flag:--json-schema"))
    report = execution_report.new_report(tmp_path)
    host_mode._note_step(report, repo="o/r", issue={"number": 7}, step=1, planned=planned, outcome="COMPLETE", wall_ms=5)
    task = report["tasks"][-1]
    assert (task["structured_output"], task["structured_reason"]) == ("enforced", "flag:--json-schema")


# --- the envelopes of the CLIs that take a schema flag (key sets measured with one minimal call each) ----------------

PLAN = {"operations": [{"path": "a.txt", "find": "", "replace": "hi"}], "need": []}
ENVELOPES = {
    "claude": {"type": "result", "subtype": "success", "result": json.dumps(PLAN), "structured_output": PLAN},
    "grok": {"text": json.dumps(PLAN), "stopReason": "end_turn", "structuredOutput": PLAN},
    "agy": {"status": "SUCCESS", "response": "Plan written.\n" + json.dumps(PLAN), "structured_output": PLAN},
}


@pytest.mark.parametrize("family", sorted(ENVELOPES))
def test_the_plan_is_read_from_the_envelope_of_each_cli(family):
    assert exec_planner._find_plan(json.dumps(ENVELOPES[family])) == PLAN


@pytest.mark.parametrize("family, text_key", [("claude", "result"), ("grok", "text"), ("agy", "response")])
def test_the_parsed_object_wins_over_the_text(family, text_key):
    envelope = {**ENVELOPES[family], text_key: "prose, no JSON"}
    assert exec_planner._find_plan(json.dumps(envelope)) == PLAN


@pytest.mark.parametrize("family, text_key", [("claude", "result"), ("grok", "text"), ("agy", "response")])
def test_the_text_is_read_when_the_envelope_has_no_object(family, text_key):
    envelope = {k: v for k, v in ENVELOPES[family].items() if k not in ("structured_output", "structuredOutput")}
    assert text_key in envelope and exec_planner._find_plan(json.dumps(envelope)) == PLAN


def test_an_envelope_without_a_plan_is_not_a_plan():
    assert exec_planner._find_plan(json.dumps({"text": "no plan here", "structuredOutput": {"other": 1}})) is None
