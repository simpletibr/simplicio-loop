import os

from simplicio.orchestrator.cost_governor import charge_provider_call
from simplicio.orchestrator.feature import run_feature
from simplicio.scratch.plan_schema import Plan, Task


def _plan(*tasks):
    return Plan(
        version="1.0",
        stack="py-fastapi",
        project_name="demo",
        rationale="test",
        files_to_create=[],
        tasks=list(tasks),
        deps_to_install=[],
        deps_dev=[],
        test_command="pytest -q",
        lint_command="ruff check .",
        estimated_total_tasks=len(tasks),
    )


def _task(tid, target, depends_on=None):
    return Task(
        id=tid,
        goal=f"update {target}",
        target=target,
        criteria="- passes",
        constraints="- minimal",
        verify='python -c "raise SystemExit(0)"',
        depends_on=depends_on or [],
    )


def test_run_feature_executes_planned_tasks_in_order(tmp_path):
    calls = []

    def fake_planner(stack, goal, project_name):
        return _plan(_task("T01-a", "src/a.py"), _task("T02-b", "src/b.py"))

    def fake_runner(task, project_dir, stack):
        calls.append(task.id)
        return True, "ok"

    result = run_feature(
        root=str(tmp_path),
        stack_slug="py-fastapi",
        goal="implement login flow",
        planner=fake_planner,
        task_runner=fake_runner,
    )

    assert result["applied"] is True
    assert calls == ["T01-a", "T02-b"]
    assert result["replans"] == 0


def test_run_feature_replans_after_failed_task(tmp_path):
    plans = iter(
        [
            _plan(_task("T01-a", "src/a.py")),
            _plan(_task("T01-b", "src/b.py")),
        ]
    )
    calls = []

    def fake_planner(stack, goal, project_name):
        return next(plans)

    def fake_runner(task, project_dir, stack):
        calls.append(task.id)
        return (task.id == "T01-b"), "failed" if task.id == "T01-a" else "ok"

    result = run_feature(
        root=str(tmp_path),
        stack_slug="py-fastapi",
        goal="implement login flow",
        max_iter=1,
        planner=fake_planner,
        task_runner=fake_runner,
    )

    assert result["applied"] is True
    assert calls == ["T01-a", "T01-b"]
    assert result["replans"] == 1


def test_run_feature_replan_skips_previously_passed_tasks(tmp_path):
    plans = iter(
        [
            _plan(_task("T01-a", "src/a.py"), _task("T02-b", "src/b.py")),
            _plan(_task("T01-a", "src/a.py"), _task("T02-b", "src/b.py")),
        ]
    )
    calls = []

    def fake_planner(stack, goal, project_name):
        return next(plans)

    def fake_runner(task, project_dir, stack):
        calls.append(task.id)
        return task.id == "T01-a" or calls.count("T02-b") == 2, "ok"

    result = run_feature(
        root=str(tmp_path),
        stack_slug="py-fastapi",
        goal="implement login flow",
        max_iter=1,
        planner=fake_planner,
        task_runner=fake_runner,
    )

    assert result["applied"] is True
    assert calls == ["T01-a", "T02-b", "T02-b"]
    assert result["replans"] == 1


def test_run_feature_returns_failure_after_replan_limit(tmp_path):
    def fake_planner(stack, goal, project_name):
        return _plan(_task("T01-a", "src/a.py"))

    def fake_runner(task, project_dir, stack):
        return False, "still broken"

    result = run_feature(
        root=str(tmp_path),
        stack_slug="py-fastapi",
        goal="implement login flow",
        max_iter=0,
        planner=fake_planner,
        task_runner=fake_runner,
    )

    assert result["applied"] is False
    assert result["warnings"]


def test_run_feature_orders_tasks_by_dependencies(tmp_path):
    calls = []

    def fake_planner(stack, goal, project_name):
        return _plan(
            _task("T02-b", "src/b.py", depends_on=["T01-a"]),
            _task("T01-a", "src/a.py"),
        )

    def fake_runner(task, project_dir, stack):
        calls.append(task.id)
        return True, "ok"

    result = run_feature(
        root=str(tmp_path),
        stack_slug="py-fastapi",
        goal="implement login flow",
        planner=fake_planner,
        task_runner=fake_runner,
    )

    assert result["applied"] is True
    assert calls == ["T01-a", "T02-b"]


def test_run_feature_reports_dependency_cycle(tmp_path):
    def fake_planner(stack, goal, project_name):
        return _plan(
            _task("T01-a", "src/a.py", depends_on=["T02-b"]),
            _task("T02-b", "src/b.py", depends_on=["T01-a"]),
        )

    def fake_runner(task, project_dir, stack):
        raise AssertionError("runner should not execute blocked dependency cycle")

    result = run_feature(
        root=str(tmp_path),
        stack_slug="py-fastapi",
        goal="implement login flow",
        planner=fake_planner,
        task_runner=fake_runner,
    )

    assert result["applied"] is False
    assert "dependency" in result["warnings"][0]


def test_run_feature_reports_duplicate_task_ids(tmp_path):
    def fake_planner(stack, goal, project_name):
        return _plan(
            _task("T01-a", "src/a.py"),
            _task("T01-a", "src/b.py"),
        )

    def fake_runner(task, project_dir, stack):
        raise AssertionError("runner should not execute duplicate task ids")

    result = run_feature(
        root=str(tmp_path),
        stack_slug="py-fastapi",
        goal="implement login flow",
        planner=fake_planner,
        task_runner=fake_runner,
    )

    assert result["applied"] is False
    assert "duplicate task id" in result["warnings"][0]


def test_run_feature_rejects_unknown_stack(tmp_path):
    try:
        run_feature(root=str(tmp_path), stack_slug="missing", goal="x")
    except ValueError as exc:
        assert "unknown stack" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_run_feature_applies_max_cost_to_provider_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_PRICE_PER_MTOK", "100")
    monkeypatch.delenv("SIMPLICIO_MAX_COST", raising=False)
    monkeypatch.delenv("SIMPLICIO_COST_SPENT_USD", raising=False)

    def fake_planner(stack, goal, project_name):
        charge_provider_call("planner", "x" * 4000, "y" * 4000)
        return _plan(_task("T01-a", "src/a.py"))

    def fake_runner(task, project_dir, stack):
        return True, "ok"

    result = run_feature(
        root=str(tmp_path),
        stack_slug="py-fastapi",
        goal="implement login flow",
        max_cost="0.0001",
        planner=fake_planner,
        task_runner=fake_runner,
    )

    assert result["applied"] is False
    assert "cost budget exceeded" in result["warnings"][0]
    assert result["cost"]["budget_usd"] == "0.0001"
    assert "SIMPLICIO_MAX_COST" not in os.environ
    assert "SIMPLICIO_COST_SPENT_USD" not in os.environ


def test_run_feature_requires_context_before_any_codegen(tmp_path):
    marker = "SimplicioCode Desktop DEBUG E2E"

    def fake_planner(stack, goal, project_name):
        return _plan(
            Task(
                id="T01-doc-marker",
                goal=(
                    f"Create or update docs/simplicio-code-desktop-debug-flow.md with marker text `{marker}`."
                ),
                target="docs/simplicio-code-desktop-debug-flow.md",
                criteria=f"- file contains marker text `{marker}`",
                constraints="- keep the change limited to the requested evidence document",
                verify=f'grep -q "{marker}" docs/simplicio-code-desktop-debug-flow.md',
            )
        )

    result = run_feature(
        root=str(tmp_path),
        stack_slug="php-vanilla",
        goal="validate desktop debug evidence",
        planner=fake_planner,
    )

    assert result["applied"] is False
    assert result["tasks"][0]["target"] == "docs/simplicio-code-desktop-debug-flow.md"
    assert "MUTATION_CONTEXT_REQUIRED" in result["tasks"][0]["log"]
    assert not (tmp_path / "docs/simplicio-code-desktop-debug-flow.md").exists()
