"""Hermetic 10-task turbo comparison: no OpenRouter, one Mapper survey, cache prefix."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.llm_ab import compare10
from bench.llm_ab import tasks as bench_tasks
from bench.llm_ab.report import run_prefix_cache_miss
from simplicio_loop.turbo import survey_tasks


def test_task_set_ten_is_ten_pages():
    tasks = bench_tasks.task_set(10)
    assert len(tasks) == 10
    assert [task["target"] for task in tasks] == [f"p{i:02d}.html" for i in range(1, 11)]
    assert tasks[0]["checker"] == "check_page.py"


def test_hermetic_comparison_is_ten_tasks_and_does_not_call_openrouter(tmp_path, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("OpenRouter was called")

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    def write_map(root):
        state = Path(root) / ".simplicio"
        state.mkdir(parents=True, exist_ok=True)
        (state / "project-map.json").write_text('{"files": 6}', encoding="utf-8")

    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", write_map)
    out = tmp_path / "hermetic.json"
    rc = compare10.main(["--root", str(tmp_path), "--out", str(out)])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["task_count"] == 10
    assert payload["arms"] == ["normal", "simplicio"]
    assert payload["live"] is False
    assert len(payload["tasks"]) == 10
    assert payload["survey"]["generation"] != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_mapper_survey_runs_once_and_is_reused_for_the_other_nine(tmp_path, monkeypatch):
    calls = []

    def fake_index(root):
        calls.append(root)
        state = root / ".simplicio"
        state.mkdir(parents=True, exist_ok=True)
        (state / "project-map.json").write_text('{"files": 6}', encoding="utf-8")

    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", fake_index)
    tasks = bench_tasks.task_set(10)
    first = survey_tasks(tmp_path, tasks)
    second = survey_tasks(tmp_path, tasks)
    assert len(calls) == 1
    generations = {row["generation"] for row in first["tasks"]}
    assert generations == {second["generation"]}
    assert len(generations) == 1
    assert first["tasks"][0]["reused"] is False
    assert all(row["reused"] for row in first["tasks"][1:])
    assert second["indexed"] is False


def test_prefix_cache_rule_matches_the_deepseek_harness():
    """The gate flags a later call with no cache read, and the skill-loaded
    OpenRouter run on 2400cedd satisfies it with the recorded tokens."""
    cold = [
        {"ok": True, "turn": 1, "cached_tokens": 0, "prompt_tokens": 400},
        {"ok": True, "turn": 2, "cached_tokens": 256, "prompt_tokens": 420},
        {"ok": True, "turn": 3, "cached_tokens": 0, "prompt_tokens": 420},
    ]
    miss = run_prefix_cache_miss(cold)
    assert miss is not None
    assert miss["turn"] == 3
    result = json.loads(Path(
        "bench/llm_ab/results/2026-09-28-4a0a7bb6-t10.json"
    ).read_text(encoding="utf-8"))
    assert result["meta"]["main_commit"] == "4a0a7bb6"
    calls = []
    for task in result["arms"]["simplicio"]["tasks"]:
        calls.extend(task.get("llm_calls") or [])
    assert len(calls) >= 2
    assert run_prefix_cache_miss(calls) is None
    assert all((call.get("cached_tokens") or 0) > 0 for call in calls[1:])
    normal = result["arms"]["normal"]
    simplicio = result["arms"]["simplicio"]
    assert sum(1 for task in normal["tasks"] if task["success"]) == 10
    assert sum(1 for task in simplicio["tasks"] if task["success"]) == 10
    assert simplicio["total_wall_s"] < normal["total_wall_s"]
    normal_cost = sum((task.get("totals") or {}).get("cost_usd") or 0 for task in normal["tasks"])
    simplicio_cost = sum((task.get("totals") or {}).get("cost_usd") or 0 for task in simplicio["tasks"])
    assert simplicio_cost > 0
    assert simplicio_cost < normal_cost


def test_short_prefix_cannot_claim_a_cache_hit():
    calls = compare10.recorded_prefix_calls(3, prefix_tokens=16)
    assert calls[1]["cached_tokens"] == 0
    assert run_prefix_cache_miss(calls) is not None


def test_page_checker_accepts_boolean_required(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "check_page",
        Path("bench/llm_ab/fixture/tests/check_page.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    page = tmp_path / "p01.html"
    page.write_text(
        '<form id="p01"><label>Email</label>'
        '<input type="email" name="email" required>'
        '<button type="submit">Submit</button></form>',
        encoding="utf-8",
    )
    assert mod.check(page, 1) == []


def test_turbo_run_opencode_installs_the_skill(tmp_path, monkeypatch):
    """Turbo still loads .claude/skills/simplicio-loop before the agent runs."""
    import bench.llm_ab.opencode_agent as oc

    monkeypatch.setenv("SIMPLICIO_BENCH_TURBO", "1")
    seen = {}

    def fake_run(cmd, cwd=None, timeout=None, env=None):
        seen["cmd"] = cmd
        seen["cwd"] = cwd
        return "", {"returncode": 0, "wall_s": 0.0, "cpu_s": 0.0, "peak_rss_mb": 0.0}

    monkeypatch.setattr(oc.measure, "run_subprocess", fake_run)
    monkeypatch.setattr(oc, "fetch_key_usage_usd", lambda key: 1.0)
    monkeypatch.setattr(oc, "write_opencode_provider_config", lambda *args, **kwargs: None)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    oc.run_opencode(
        "simplicio",
        "Create p01.html",
        str(repo),
        key="k",
        config_dir=str(tmp_path / "oc"),
        bin_path="/bin/echo",
        skill=True,
        usage_baseline=1.0,
        settle_reads=1,
        settle_interval_s=0,
        settle_max_wait_s=0,
    )
    skill = repo / ".claude" / "skills" / "simplicio-loop" / "SKILL.md"
    assert skill.is_file()
    body = skill.read_text(encoding="utf-8")
    assert "contract: simplicio-loop" in body
    assert "Mapper survey" in body
    joined = " ".join(seen["cmd"])
    assert "turbo" in joined
    assert "/simplicio-loop" in joined


def test_turbo_prompt_follows_the_engine_flow(monkeypatch):
    import bench.llm_ab.opencode_agent as oc
    monkeypatch.setenv("SIMPLICIO_BENCH_TURBO", "1")
    prompt = oc.build_prompt("simplicio", "Create the page described below.")
    assert "simplicio-dev-cli" in prompt
    assert "Read the repo once" in prompt
    assert "write every HTML" not in prompt
    assert "hand-edit files" in prompt


def test_turbo_read_ai_devcli_writes_what_the_model_returns(tmp_path, monkeypatch):
    """The shipped turbo reads, asks, and lets dev-cli create the file."""
    import subprocess
    from simplicio_loop.turbo import run_read_ai_devcli

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)

    def complete(arm, messages, **kwargs):
        assert arm == "simplicio"
        assert messages[0]["role"] == "system"
        assert "MAPMARK" in messages[1]["content"]
        assert "Create page" in messages[1]["content"]
        return {
            "ok": True,
            "content": '{"operations":[{"path":"made.html","find":"","replace":"<p>made</p>"}]}',
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
        }

    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", lambda root: None)
    state = tmp_path / ".simplicio"
    state.mkdir()
    (state / "project-map.json").write_text('{"mark":"MAPMARK"}', encoding="utf-8")
    tasks = [{"index": 1, "text": "Create page made.html with a paragraph."}]
    result = run_read_ai_devcli(tmp_path, tasks, complete)
    assert (tmp_path / "made.html").read_text(encoding="utf-8") == "<p>made</p>"
    assert result["turns"] == 1
    assert any("simplicio-dev-cli" in cmd["command"] and "--apply" in cmd["command"] for cmd in result["commands"])


def test_wave_turbo_above_three_fans_out_with_the_mapper_reading(tmp_path, monkeypatch):
    import subprocess
    from simplicio_loop.turbo import run_turbo

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", lambda root: None)
    state = tmp_path / ".simplicio"
    state.mkdir()
    (state / "project-map.json").write_text('{"mark":"MAPMARK"}', encoding="utf-8")
    seen = []

    def complete(arm, messages, **kwargs):
        body = messages[1]["content"]
        seen.append(body)
        assert "MAPMARK" in body
        name = "page" + body.strip().split("Tasks:", 1)[1].strip().split(".", 1)[0].strip()
        return {
            "ok": True,
            "content": '{"operations":[{"path":"%s.html","find":"","replace":"<p>%s</p>"}]}' % (name, name),
            "prompt_tokens": 40,
            "completion_tokens": 10,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
        }

    tasks = [{"index": index, "text": "Create %s" % index} for index in range(1, 5)]
    result = run_turbo(tmp_path, tasks, complete)
    assert result["wave"] is True
    assert len(seen) == 4
    assert (tmp_path / "page1.html").is_file()
    assert (tmp_path / "page4.html").read_text(encoding="utf-8") == "<p>page4</p>"
