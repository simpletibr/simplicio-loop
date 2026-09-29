"""3.45.0: invoking the skill runs the benchmarked turbo engine through `simplicio-loop turbo`."""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import turbo_provider
from simplicio_loop.cli_impl import main as cli_main
from simplicio_loop.turbo import run_turbo

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "bench" / "llm_ab" / "fixture_hard"
SOLUTION = ROOT / "tests" / "fixtures" / "llm_ab_hard_solution"
HIDDEN = ROOT / "bench" / "llm_ab" / "hidden" / "check_hard.py"
SKILL = ROOT / ".claude" / "skills" / "simplicio-loop" / "SKILL.md"


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(seen):
    def urlopen(request, timeout=None):
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["body"] = json.loads(request.data)
        seen["url"] = request.full_url
        return _Response(json.dumps({
            "provider": "Together",
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0001,
                      "prompt_tokens_details": {"cached_tokens": 8},
                      "completion_tokens_details": {"reasoning_tokens": 0}},
        }).encode())
    return urlopen


def test_session_id_is_stable_per_repository(tmp_path):
    assert turbo_provider.session_id_for(tmp_path) == turbo_provider.session_id_for(tmp_path)
    assert turbo_provider.session_id_for(tmp_path) != turbo_provider.session_id_for(tmp_path / "other")


def _seed(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"],
                 ["add", "-A"], ["commit", "-qm", "seed"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    return repo


def _solution_ops(repo: Path, rels):
    ops = []
    for rel in rels:
        old = (repo / rel).read_text(encoding="utf-8") if (repo / rel).is_file() else ""
        ops.append({"path": rel, "find": old, "replace": (SOLUTION / rel).read_text(encoding="utf-8")})
    return ops


def test_run_turbo_reports_whether_each_task_plan_applied(tmp_path, monkeypatch):
    repo = _seed(tmp_path)
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", lambda root: None)
    (repo / ".simplicio-loop").mkdir()
    (repo / ".simplicio-loop" / "project-map.json").write_text('{"files":[]}', encoding="utf-8")

    def complete(arm, messages, **kwargs):  # one call covers both tasks; the inventory find never matches
        ops = _solution_ops(repo, ["pricing.py"]) + [{"path": "inventory.py", "find": "NOT THERE", "replace": "x"}]
        return {"ok": True, "content": json.dumps({"operations": ops})}

    tasks = [{"index": 1, "text": "pricing.py task", "target": "pricing.py", "depends_on": []},
             {"index": 2, "text": "inventory.py task", "target": "inventory.py", "depends_on": [1]}]
    result = run_turbo(repo, tasks, complete)
    assert result["applied_all"] is False
    assert [o["applied"] for o in result["outcomes"]] == [False]
    assert result["outcomes"][0]["tasks"] == [1, 2] and result["outcomes"][0]["reason"]


def test_cli_turbo_without_a_key_blocks_with_a_typed_reason(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    rc = cli_main(["turbo", "--provider", "openrouter", "--repo", str(_seed(tmp_path)), "--task", "fix inventory.py"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2 and out["status"] == "blocked" and out["mode"] == "provider"
    assert out["reason_code"] == "turbo_provider_key_missing" and "OPENROUTER_API_KEY" in out["fix"]


def test_cli_turbo_runs_the_engine_end_to_end_and_verifies(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    seen = []

    def fake_complete(arm, messages, **kwargs):
        seen.append(([dict(m) for m in messages], dict(kwargs)))  # a copy: the engine appends later
        rels = ["inventory.py"] if "Fix the two bugs in inventory.py." in messages[-1]["content"] else ["pricing.py"]
        return {"ok": True, "latency_s": 0.1, "provider": "Together", "prompt_tokens": 100,
                "cached_tokens": 0, "completion_tokens": 50, "reasoning_tokens": 0, "cost": 0.0002,
                "content": json.dumps({"operations": _solution_ops(repo, rels)})}

    monkeypatch.setattr(turbo_provider, "complete", fake_complete)
    verify = f'"{sys.executable}" "{HIDDEN}" --stage 1 && "{sys.executable}" "{HIDDEN}" --stage 2'
    rc = cli_main(["turbo", "--provider", "openrouter", "--repo", str(repo),
                   "--task", "Create pricing.py with order_total as specified.",
                   "--task", "Fix the two bugs in inventory.py.",
                   "--verify", verify])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0, out
    assert out["status"] == "ok" and out["verify"]["passed"] is True
    assert out["tasks"] == 2 and out["model_calls"] == 2 and out["reasoning"] == "off"  # independent tasks: one call each
    assert all(kwargs["session_id"] == turbo_provider.session_id_for(repo) for _, kwargs in seen)
    messages = next(m for m, _ in seen if "Fix the two bugs" in m[-1]["content"])
    assert "Current inventory.py:" in messages[-1]["content"]  # named file reached the model


def test_cli_turbo_provider_mode_packs_independent_tasks_into_at_most_four_calls(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.delenv("SIMPLICIO_TURBO_HOST_PARALLEL", raising=False)
    (repo / "tasks.json").write_text(json.dumps([{"text": f"Create page{i}.html.", "target": f"page{i}.html"} for i in range(1, 11)]),
                                     encoding="utf-8")
    seen = []

    def fake_complete(arm, messages, **kwargs):
        seen.append(messages[-1]["content"])
        pages = re.findall(r"^\d+\. Create (page\d+\.html)\.", messages[-1]["content"], flags=re.M)
        return {"ok": True, "latency_s": 0.1, "prompt_tokens": 100, "cached_tokens": 0, "completion_tokens": 50, "reasoning_tokens": 0,
                "cost": 0.0002, "content": json.dumps({"operations": [{"path": p, "find": "", "replace": p} for p in pages]})}

    monkeypatch.setattr(turbo_provider, "complete", fake_complete)
    rc = cli_main(["turbo", "--provider", "openrouter", "--repo", str(repo), "--tasks-file", str(repo / "tasks.json")])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["status"] == "ok" and out["tasks"] == 10
    assert out["model_calls"] == 4 == len(seen) and out["retries"] == 0  # one round of four calls, not ten
    assert all((repo / f"page{i}.html").is_file() for i in range(1, 11))


def test_cli_turbo_surveys_again_on_every_invocation(tmp_path, monkeypatch, capsys):
    """The saved survey marker belongs to one run. A later invocation asks Mapper again (its own
    tree-state cache makes an unchanged tree free), so a repo that changed does not keep the first map."""
    repo = _seed(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("SIMPLICIO_TURBO_SLICE", "0")  # this test reads the whole map in the header
    surveys, headers = [], []

    def fake_ensure(root, **kwargs):
        surveys.append(str(root))
        state = root / ".simplicio-loop"
        state.mkdir(exist_ok=True)
        files = sorted(p.name for p in root.glob("*.py"))
        (state / "project-map.json").write_text(json.dumps({"files": files}), encoding="utf-8")

    def fake_complete(arm, messages, **kwargs):
        headers.append(messages[0]["content"])
        ops = [{"path": f"note{len(headers)}.txt", "find": "", "replace": "x\n"}]
        return {"ok": True, "content": json.dumps({"operations": ops}), "prompt_tokens": 1, "completion_tokens": 1}

    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", fake_ensure)
    monkeypatch.setattr(turbo_provider, "complete", fake_complete)
    assert cli_main(["turbo", "--provider", "openrouter", "--repo", str(repo), "--task", "Create note1.txt"]) == 0
    (repo / "extra.py").write_text("X = 1\n", encoding="utf-8")
    assert cli_main(["turbo", "--provider", "openrouter", "--repo", str(repo), "--task", "Create note2.txt"]) == 0
    capsys.readouterr()
    assert len(surveys) == 2
    assert "extra.py" not in headers[0] and "extra.py" in headers[1]


def test_cli_turbo_help_names_the_key_and_the_model(capsys):
    with pytest.raises(SystemExit):
        cli_main(["turbo", "--help"])
    text = "".join(capsys.readouterr().out.split())  # the help wraps lines, also inside hyphenated names
    assert "OPENROUTER_API_KEY" in text and "deepseek/deepseek-v4.1-flash" in text
    assert "--provideropenrouter" in text and "nokey" in text


def test_skill_orients_every_host_to_the_turbo_command():
    """Host mode: the model plans and dev-cli applies, in two commands. No key requirement."""
    text = SKILL.read_text(encoding="utf-8")
    flat = " ".join(text.split())
    assert 'simplicio-loop turbo --repo <path> --task "<task>"' in text and 'simplicio-loop "<task>"' in text
    assert "--apply -" in text and "<<'PLAN'" in text and "`apply` command" in text.split("SIMPLICIO-LLM-ORIENTATION:BEGIN", 1)[1]
    block = text.split("<!-- SIMPLICIO-LLM-ORIENTATION:BEGIN -->", 1)[1].split("<!-- SIMPLICIO-LLM-ORIENTATION:END -->", 1)[0]
    assert "simplicio-loop turbo" in block and "OPENROUTER_API_KEY" not in block
    assert "needs no API key" not in text and "There is no provider call and no API key." in flat
    assert "The host LLM writes find/replace text" not in text
    assert "edit-plan-<N>.json" not in text


ORIENTATION_SURFACES = (
    ".claude/skills/simplicio-loop/SKILL.md",
    ".claude/skills/simplicio-loop/references/full-flow.md",
    "docs/LLM_MAX_SPEED_ORIENTATION.md",
    "docs/ECOSYSTEM_LLM_GUIDE.md",
    "docs/CLI_COMMANDS.md",
    "llms.txt",
    "AGENTS.md",
    "README.md",
    "adapters/opencode/README.md",
    "packaging/host-rules/simplicio-loop-operator-flow.md",
    "bench/llm_ab/STANDARD.md",
    "bench/llm_ab/README.md",
)
HOST_PLAN_PHRASES = (
    "edit-plan-<N>.json",
    "The host LLM writes find/replace text",
    "Host writes the edit plan.",
    "write every `edit-plan",
)


def test_the_skill_ends_the_run_at_the_result_and_never_asks_for_a_verification_script():
    text = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert "After an ok result do not read files or write or run tests or verification scripts" in text
    assert "with no known test command pass no `--verify` and create none" in text


@pytest.mark.parametrize("rel", ORIENTATION_SURFACES)
def test_every_orientation_surface_names_turbo_and_drops_the_host_plan_flow(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert "simplicio-loop turbo" in text, rel
    assert not [phrase for phrase in HOST_PLAN_PHRASES if phrase in text], rel


def test_host_rule_mirrors_stay_identical():
    canonical = (ROOT / "packaging/host-rules/simplicio-loop-operator-flow.md").read_bytes()
    for mirror in (".cursor/rules/simplicio-loop-operator-flow.md", ".github/simplicio-loop-operator-flow.md",
                   ".kiro/steering/simplicio-loop-operator-flow.md"):
        assert (ROOT / mirror).read_bytes() == canonical, mirror


def test_benchmark_turbo_arm_calls_the_product_provider(monkeypatch):
    from bench.llm_ab import run as bench_run

    captured = {}
    monkeypatch.setattr(bench_run.lc, "get_key", lambda arm: "sk-arm")
    monkeypatch.setattr(turbo_provider, "complete", lambda arm, messages, **kw: captured.update(kw) or {"ok": True})
    monkeypatch.delenv("SIMPLICIO_BENCH_TURBO_REASONING", raising=False)
    bench_run.turbo_complete("simplicio", [])
    assert captured == {"api_key": "sk-arm", "session_id": bench_run.oc.session_id_for_arm("simplicio"),
                        "reasoning_off": True}
