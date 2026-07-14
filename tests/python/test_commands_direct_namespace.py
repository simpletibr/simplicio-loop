"""Direct unit tests for `simplicio/commands/<name>.py` handlers, bypassing
argparse entirely (issue #103 AC: "each extracted handler has a direct unit
test"). Every test here builds an `argparse.Namespace` by hand and calls the
command module's `run(a)` (or, for edit/score-skill, its named entrypoint)
directly — no `cli.main([...])` involved. End-to-end argparse coverage for
these same subcommands already exists in test_run_cli.py, test_doctor_freshness.py,
test_cli_autoinstall.py, etc.; this file is the orthogonal, argparse-free layer.
"""

from __future__ import annotations

import argparse
import json

from simplicio.commands import (
    bench as bench_cmd,
)
from simplicio.commands import (
    cache as cache_cmd,
)
from simplicio.commands import (
    detect as detect_cmd,
)
from simplicio.commands import (
    doctor as doctor_cmd,
)
from simplicio.commands import (
    edit as edit_cmd,
)
from simplicio.commands import (
    env_export as env_export_cmd,
)
from simplicio.commands import (
    index as index_cmd,
)
from simplicio.commands import (
    init as init_cmd,
)
from simplicio.commands import (
    inspect as inspect_cmd,
)
from simplicio.commands import (
    memory as memory_cmd,
)
from simplicio.commands import (
    runtime as runtime_cmd,
)
from simplicio.commands import (
    status as status_cmd,
)
from simplicio.commands import (
    task as task_cmd,
)
from simplicio.commands import (
    token as token_cmd,
)


def ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_index_run_calls_index_repo(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "simplicio.precedent.index_repo", lambda root, stack: seen.update(root=root, stack=stack)
    )
    code = index_cmd.run(ns(root_arg=None, root="/repo", stack="python"))
    assert code == 0
    assert seen == {"root": "/repo", "stack": "python"}


def test_index_run_prefers_positional_root(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "simplicio.precedent.index_repo", lambda root, stack: seen.update(root=root, stack=stack)
    )
    code = index_cmd.run(ns(root_arg="/positional", root=".", stack=None))
    assert code == 0
    assert seen["root"] == "/positional"


def test_status_run_no_state_file(tmp_path, capsys):
    code = status_cmd.run(ns(root=str(tmp_path), json=True))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "none"
    assert payload["claims_gate"]["allow_fresh_verification_claim"] is False


def test_status_claims_gate_requires_complete_and_no_failures():
    assert status_cmd.status_claims_gate({"complete": False})["allow_fresh_verification_claim"] is False
    ok_payload = {"complete": True, "state": "complete", "failed_features": [], "failed_dod_gates": []}
    gate = status_cmd.status_claims_gate(ok_payload)
    assert gate["allow_fresh_verification_claim"] is True
    assert gate["allow_repo_green_claim"] is False


def test_inspect_run_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "simplicio.mapper.inspect_target",
        lambda root, target, goal="": {"context": "hello", "target": target},
    )
    code = inspect_cmd.run(ns(root=str(tmp_path), target="app.py", goal="", json=True))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.dev-cli.inspect/v1"
    assert payload["context"] == "hello"


def test_env_export_run_json(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\n", encoding="utf-8")
    code = env_export_cmd.run(ns(env_file=str(env_file), json=True))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"FOO": "bar"}


def test_env_export_run_missing_file(tmp_path, capsys):
    code = env_export_cmd.run(ns(env_file=str(tmp_path / "nope.env"), json=False))
    assert code == 2


def test_memory_run_init_store_recall(tmp_path, capsys):
    mem_dir = str(tmp_path / "mem")
    code = memory_cmd.run(ns(memory_cmd="init", dir=mem_dir, json=True))
    assert code == 0
    init_payload = json.loads(capsys.readouterr().out)
    assert init_payload["created"] is True

    code = memory_cmd.run(
        ns(
            memory_cmd="store",
            dir=mem_dir,
            topic="handoff test",
            content="cross-vendor note",
            tags="",
            json=True,
        )
    )
    assert code == 0
    store_payload = json.loads(capsys.readouterr().out)
    assert store_payload["committed"] in (True, False)

    code = memory_cmd.run(
        ns(memory_cmd="recall", dir=mem_dir, query="cross-vendor", limit=5, json=True, mode="hybrid")
    )
    assert code == 0
    recall_payload = json.loads(capsys.readouterr().out)
    assert len(recall_payload["results"]) == 1

    code = memory_cmd.run(ns(memory_cmd="validate", dir=mem_dir, strict=False, json=True))
    assert code == 0
    validate_payload = json.loads(capsys.readouterr().out)
    assert validate_payload["ok"] is True

    code = memory_cmd.run(
        ns(
            memory_cmd="handoff",
            dir=mem_dir,
            query="cross-vendor",
            limit=5,
            from_agent="codex",
            to_agent="claude",
            json=True,
        )
    )
    assert code == 0
    handoff_payload = json.loads(capsys.readouterr().out)
    assert handoff_payload["from_agent"] == "codex"
    assert handoff_payload["to_agent"] == "claude"


def test_cache_run_stats(monkeypatch, capsys):
    class FakeCache:
        def stats(self):
            return {
                "root": "/x",
                "enabled": True,
                "bust": False,
                "entries": 0,
                "mb": 0.0,
                "ttl_days": 7,
                "max_mb": 100,
            }

    monkeypatch.setattr("simplicio._cache.cache", lambda: FakeCache())
    code = cache_cmd.run(ns(cache_cmd="stats", json=True))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["entries"] == 0


def test_cache_run_clear_requires_force(monkeypatch, capsys):
    monkeypatch.setattr("simplicio._cache.cache", lambda: object())
    code = cache_cmd.run(ns(cache_cmd="clear", force=False))
    assert code == 2


def test_runtime_run_doctor(monkeypatch, capsys):
    monkeypatch.setattr(
        "simplicio.runtime_contracts.doctor_contract",
        lambda root: {"package": {"version": "9.9.9"}, "tools": {"foo": {"available": True}}},
    )
    code = runtime_cmd.run(ns(runtime_cmd="doctor", root=".", json=True))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["package"]["version"] == "9.9.9"


def test_bench_run_calls_run_bench(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "simplicio.bench.run_bench",
        lambda root, stack, cases: seen.update(root=root, stack=stack, cases=cases),
    )
    code = bench_cmd.run(ns(root=".", stack="python", cases="bench/cases.json"))
    assert code == 0
    assert seen == {"root": ".", "stack": "python", "cases": "bench/cases.json"}


def test_init_run_translates_namespace_to_argv(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr("simplicio.init.main", lambda argv: (seen.__setitem__("argv", argv), 0)[1])
    code = init_cmd.run(ns(claude_home=str(tmp_path), dry_run=True))
    assert code == 0
    assert seen["argv"] == ["--claude-home", str(tmp_path), "--dry-run"]


def test_detect_run_translates_namespace_to_argv(monkeypatch):
    seen = {}
    monkeypatch.setattr("simplicio.detect.main", lambda argv: (seen.__setitem__("argv", argv), 0)[1])
    code = detect_cmd.run(ns(prompt="fix the bug", prompt_words=[], quiet=True, json=True))
    assert code == 0
    assert seen["argv"] == ["--prompt", "fix the bug", "--quiet", "--json"]


def test_detect_run_joins_prompt_words_when_no_prompt(monkeypatch):
    seen = {}
    monkeypatch.setattr("simplicio.detect.main", lambda argv: (seen.__setitem__("argv", argv), 0)[1])
    detect_cmd.run(ns(prompt=None, prompt_words=["fix", "the", "bug"], quiet=False, json=False))
    assert seen["argv"] == ["--prompt", "fix the bug"]


def test_doctor_run_translates_namespace_to_argv(monkeypatch):
    seen = {}
    monkeypatch.setattr("simplicio.doctor.main", lambda argv: (seen.__setitem__("argv", argv), 0)[1])
    code = doctor_cmd.run(
        ns(install=True, json=True, list_tiers=False, no_check_updates=True, refresh=False, upgrade=False)
    )
    assert code == 0
    assert seen["argv"] == ["--install", "--json", "--no-check-updates"]


def test_edit_run_mechanical_edit_dry_run(tmp_path, capsys):
    plan = {
        "schema": "simplicio.mechanical-edit/v1",
        "operations": [{"op": "create_file", "path": "x.txt", "text": "hi\n"}],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    code = edit_cmd.run_mechanical_edit(ns(root=str(tmp_path), plan=str(plan_path), apply=False, json=True))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert not (tmp_path / "x.txt").exists()


def test_edit_run_edit_falls_back_to_mechanical_edit_without_runtime(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    plan = {
        "schema": "simplicio.mechanical-edit/v1",
        "operations": [{"op": "create_file", "path": "x.txt", "text": "hi\n"}],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    code = edit_cmd.run_edit(
        ns(root=str(tmp_path), plan=str(plan_path), apply=True, json=True, no_runtime=False)
    )
    assert code == 0
    assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "hi\n"


def test_token_run_log_summary(tmp_path, capsys):
    log_file = tmp_path / "log.txt"
    log_file.write_text("line one\nline two\n", encoding="utf-8")
    code = token_cmd.run(ns(token_cmd="log-summary", file=str(log_file), max_chars=1200))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "line one" in payload["summary"] or "line" in json.dumps(payload)


def test_task_run_dry_run_task(tmp_path, monkeypatch, capsys):
    (tmp_path / "app.py").write_text("old\n", encoding="utf-8")
    # _dry_run_preconditions (in pipeline_task_result, split out of pipeline.py
    # since this test was written) imports artifact_status/map_handoff
    # directly from .mapper, so that's where the dry-run check must be
    # patched — patching simplicio.pipeline's re-exported names has no effect
    # on it.
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.artifact_status",
        lambda _root: {
            "project_map": {"present": True},
            "precedent_index": {"present": True},
        },
    )
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.map_handoff",
        lambda _root: {"context_pack": {"needs_broader_context": False, "files": [{"path": "app.py"}]}},
    )
    monkeypatch.setattr(
        "simplicio.pipeline.generate",
        lambda *a, **k: "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
    )
    code = task_cmd.run(
        ns(
            root=str(tmp_path),
            stack=None,
            goal="update app.py",
            target="app.py",
            criteria="- true",
            constraints="- build passes",
            dry_run_task=True,
            json=True,
            bound_paths=[],
            local=False,
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "diff_summary" in payload
