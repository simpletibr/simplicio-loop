"""Hard benchmark set: hidden tests outside the arm repo, multi-file context, reasoning toggle."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from bench.llm_ab import run as bench_run
from bench.llm_ab import tasks as bench_tasks
from simplicio_loop.turbo import task_message

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "bench" / "llm_ab" / "fixture_hard"
HIDDEN = ROOT / "bench" / "llm_ab" / "hidden" / "check_hard.py"
SOLUTION = ROOT / "tests" / "fixtures" / "llm_ab_hard_solution"


def _check(repo: Path, stage: int) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HIDDEN), "--stage", str(stage)], cwd=repo,
                          capture_output=True, text=True, timeout=60)


def _seed(tmp_path: Path, solved: bool) -> Path:
    repo = tmp_path / ("solved" if solved else "pristine")
    shutil.copytree(FIXTURE, repo)
    if solved:
        shutil.copytree(SOLUTION, repo, dirs_exist_ok=True)
    return repo


def test_hard_set_is_four_independent_tasks_checked_by_the_hidden_checker():
    tasks = bench_tasks.hard_task_set()
    assert [t["index"] for t in tasks] == [1, 2, 3, 4]
    assert all(t["depends_on"] == [] for t in tasks)
    assert all(Path(t["checker"]) == HIDDEN and Path(t["checker"]).is_absolute() for t in tasks)
    assert [t["verify_stage"] for t in tasks] == [1, 2, 3, 4]
    assert [t["target"] for t in tasks] == ["pricing.py", "inventory.py", "shop/money.py", "duration.py"]
    assert tasks[2]["context"] == ["shop/report.py", "shop/invoice.py"]


def test_hidden_checker_never_ships_inside_the_arm_repo():
    assert HIDDEN.is_file()
    assert not any(p.name.startswith("check_") for p in FIXTURE.rglob("*.py"))


def test_hidden_checker_fails_the_pristine_fixture_and_passes_the_reference(tmp_path):
    pristine, solved = _seed(tmp_path, False), _seed(tmp_path, True)
    for stage in (1, 2, 3, 4):
        assert _check(pristine, stage).returncode == 1, stage
        result = _check(solved, stage)
        assert result.returncode == 0, (stage, result.stdout)


def test_hidden_checker_catches_bankers_rounding(tmp_path):
    repo = _seed(tmp_path, True)
    source = (repo / "pricing.py").read_text(encoding="utf-8")
    (repo / "pricing.py").write_text(
        source.replace("(subtotal * 10 + 50) // 100", "round(subtotal * 0.1)"), encoding="utf-8")
    assert "round(" in (repo / "pricing.py").read_text(encoding="utf-8")
    result = _check(repo, 1)
    assert result.returncode == 1 and "half up" in result.stdout


def test_run_check_accepts_an_absolute_checker_path(tmp_path):
    repo = _seed(tmp_path, True)
    passed, output, _ = bench_run.checker.run_check(str(repo), 2, sys.executable, checker=str(HIDDEN))
    assert passed, output


def test_turbo_task_message_carries_the_context_files(tmp_path):
    repo = _seed(tmp_path, False)
    message = task_message([bench_tasks.hard_task_set()[2]], repo)["content"]
    assert "Current shop/report.py:" in message and "def summary" in message
    assert "Current shop/invoice.py:" in message and "def invoice_total" in message


def test_hard_flag_names_results_and_toggles_turbo_reasoning(monkeypatch):
    assert bench_run.result_filename("d", "s", 4, hard=True) == "d-s-t4-hard.json"
    assert bench_run.result_filename("d", "s", 4, hard=True, reasoning=True) == "d-s-t4-hard-reason.json"
    args = bench_run.build_arg_parser().parse_args(["--tasks", "4", "--hard", "--turbo-reasoning"])
    assert args.hard is True and args.turbo_reasoning is True
    from simplicio_loop import turbo_provider

    import asyncio

    captured = {}

    async def complete(arm, messages, **kw):
        captured.update(kw)
        return {"ok": True}

    monkeypatch.setattr(bench_run.lc, "get_key", lambda arm: "sk-arm")
    monkeypatch.setattr(turbo_provider, "complete", complete)
    monkeypatch.setenv("SIMPLICIO_BENCH_TURBO_REASONING", "on")
    asyncio.run(bench_run.turbo_complete("simplicio", []))
    assert captured["reasoning_off"] is False and captured["session_id"]
    monkeypatch.delenv("SIMPLICIO_BENCH_TURBO_REASONING")
    asyncio.run(bench_run.turbo_complete("simplicio", []))
    assert captured["reasoning_off"] is True


def test_turbo_applies_reference_plans_on_the_hard_fixture_and_the_hidden_tests_pass(tmp_path, monkeypatch):
    """End to end without a model: the real dev-cli applies the plans; only the reply is canned."""
    import json

    from simplicio_loop.turbo import run_turbo

    repo = _seed(tmp_path, False)
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"],
                 ["add", "-A"], ["commit", "-qm", "seed"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", lambda root: None)
    (repo / ".simplicio-loop").mkdir()
    (repo / ".simplicio-loop" / "project-map.json").write_text('{"files":[]}', encoding="utf-8")

    def plan(task):
        ops = []
        for rel in [task["target"], *(task.get("context") or [])]:
            new = (SOLUTION / rel).read_text(encoding="utf-8")
            old_path = repo / rel
            old = old_path.read_text(encoding="utf-8") if old_path.is_file() else ""
            ops.append({"path": rel, "find": old, "replace": new})
        return {"ok": True, "content": json.dumps({"operations": ops})}

    by_text = {task["text"]: task for task in bench_tasks.hard_task_set()}

    async def complete(arm, messages, **kwargs):
        if kwargs.get("max_tokens") == 1:  # warm-up call
            return {"ok": True, "content": "OK"}
        body = messages[-1]["content"]
        task = next(t for text, t in by_text.items() if text in body)
        return plan(task)

    import asyncio

    asyncio.run(run_turbo(repo, bench_tasks.hard_task_set(), complete))
    for stage in (1, 2, 3, 4):
        result = _check(repo, stage)
        assert result.returncode == 0, (stage, result.stdout)
