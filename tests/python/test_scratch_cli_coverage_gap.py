"""Additional unit coverage for simplicio/scratch/cli.py.

Targets the previously-uncovered branches: --list-stacks (text + json),
--show-stack (unknown slug, known slug text + json), stack inference
(_infer_stack keyword matching + file-marker fallback), and the main
`_cmd_scratch` flow (missing goal, unknown stack, invalid slot, planner
failure, plan-only text/json, and a mocked full execute path).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio.scratch import cli as scratch_cli
from simplicio.scratch.planner import PlannerError
from simplicio.scratch.plan_schema import EXAMPLE_PLAN, validate_plan
from simplicio.scratch.stack_registry import StackRegistry


def _real_registry() -> StackRegistry:
    return StackRegistry()


def test_main_list_stacks_text(capsys) -> None:
    rc = scratch_cli.main(["--list-stacks"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "py-fastapi" in out
    assert "slug" in out and "language" in out


def test_main_list_stacks_json(capsys) -> None:
    rc = scratch_cli.main(["--list-stacks", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert any(entry["slug"] == "py-fastapi" for entry in data)


def test_main_show_stack_unknown(capsys) -> None:
    rc = scratch_cli.main(["--show-stack", "does-not-exist"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "unknown stack" in err


def test_main_show_stack_known_text(capsys) -> None:
    rc = scratch_cli.main(["--show-stack", "py-fastapi"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "py-fastapi" in out
    assert "## README" in out


def test_main_show_stack_known_json(capsys) -> None:
    rc = scratch_cli.main(["--show-stack", "py-fastapi", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["slug"] == "py-fastapi"
    assert "readme" in data


@pytest.mark.parametrize(
    "goal,expected",
    [
        ("build a nextjs site", "ts-nextjs"),
        ("a nestjs backend", "ts-nestjs"),
        ("a fastapi service", "py-fastapi"),
        ("a django app", "py-django"),
        ("a flask app", "py-flask"),
        ("a python cli tool", "py-cli"),
        ("an express node api", "js-express"),
        ("a react spa app", "react-vite"),
        ("a bash shell script", "bash-cli"),
        ("an axum rust service", "rust-axum"),
        ("a cli using clap crate", "rust-cli"),
        ("a laravel app", "php-laravel"),
        ("plain php vanilla php site", "php-vanilla"),
        ("a symfony app", "php-symfony"),
        ("a rails app", "ruby-rails"),
        ("an asp.net api", "csharp-aspnet"),
        ("a c# ui blazor app", "csharp-blazor"),
        ("a java spring boot service", "java-spring"),
        ("a kotlin spring boot service", "kotlin-spring"),
        ("a ktor service", "kotlin-ktor"),
        ("a phoenix elixir app", "elixir-phoenix"),
        ("a flutter app", "dart-flutter"),
        ("an android jetpack compose app", "kotlin-android"),
        ("a vapor swift api", "swift-vapor"),
        ("a swiftui ios app", "swift-ios"),
        ("a go echo api", "go-echo"),
        ("a go cli with cobra", "go-cli"),
        ("a go gin api", "go-gin"),
    ],
)
def test_infer_stack_keyword_matches(goal: str, expected: str, tmp_path: Path) -> None:
    reg = _real_registry()
    if reg.get(expected) is None:
        pytest.skip(f"stack template '{expected}' not installed")
    result = scratch_cli._infer_stack(reg, goal, str(tmp_path))
    assert result == expected


def test_infer_stack_falls_back_to_file_detection(tmp_path: Path) -> None:
    reg = _real_registry()
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    result = scratch_cli._infer_stack(reg, "some vague goal with no keyword", str(tmp_path))
    assert result == "py-fastapi"


def test_detect_stack_from_files_package_json(tmp_path: Path) -> None:
    reg = _real_registry()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    result = scratch_cli._detect_stack_from_files(reg, str(tmp_path))
    assert result in {"ts-nextjs", "react-vite", None}


def test_detect_stack_from_files_csproj(tmp_path: Path) -> None:
    reg = _real_registry()
    (tmp_path / "app.csproj").write_text("<Project/>", encoding="utf-8")
    result = scratch_cli._detect_stack_from_files(reg, str(tmp_path))
    assert result in {"csharp-aspnet", "csharp-blazor", None}


def test_detect_stack_from_files_no_markers(tmp_path: Path) -> None:
    reg = _real_registry()
    result = scratch_cli._detect_stack_from_files(reg, str(tmp_path))
    assert result is None


def test_detect_stack_from_files_bad_root_returns_none() -> None:
    reg = _real_registry()
    # A root containing NUL bytes cannot be resolved on any platform.
    result = scratch_cli._detect_stack_from_files(reg, "\0bad")
    assert result is None


def test_cmd_scratch_missing_goal(capsys) -> None:
    rc = scratch_cli.main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "provide a goal" in err


def test_cmd_scratch_unknown_stack(capsys) -> None:
    rc = scratch_cli.main(["some goal", "--stack", "totally-bogus-stack"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "unknown stack" in err


def test_cmd_scratch_cannot_infer_stack(capsys, tmp_path: Path) -> None:
    rc = scratch_cli.main(["blah blah blah", "--root", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "could not infer stack" in err


def test_cmd_scratch_invalid_slot(capsys) -> None:
    rc = scratch_cli.main(
        ["a fastapi service", "--stack", "py-fastapi", "--slot", "bad-slot-no-equals"]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "invalid --slot" in err


def test_cmd_scratch_planner_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        scratch_cli,
        "_generate_plan_with_slots",
        lambda *a, **k: (_ for _ in ()).throw(PlannerError("boom")),
    )
    rc = scratch_cli.main(["a fastapi service", "--stack", "py-fastapi"])
    err = capsys.readouterr().err
    assert rc == 3
    assert "planner failed" in err


def _fake_plan(stack_slug: str = "py-fastapi", project_name: str = "demo"):
    raw = {**EXAMPLE_PLAN, "stack": stack_slug, "project_name": project_name}
    return validate_plan(raw)


def test_cmd_scratch_plan_only_text(monkeypatch, capsys) -> None:
    plan = _fake_plan()
    monkeypatch.setattr(scratch_cli, "_generate_plan_with_slots", lambda *a, **k: plan)
    rc = scratch_cli.main(["a fastapi service", "--stack", "py-fastapi", "--plan-only"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "scratch plan" in out
    assert "tasks:" in out


def test_cmd_scratch_plan_only_json(monkeypatch, capsys) -> None:
    plan = _fake_plan()
    monkeypatch.setattr(scratch_cli, "_generate_plan_with_slots", lambda *a, **k: plan)
    rc = scratch_cli.main(
        ["a fastapi service", "--stack", "py-fastapi", "--plan-only", "--json"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["project_name"] == "demo"
    assert isinstance(data["tasks"], list)


class _FakeReport:
    def __init__(self) -> None:
        self.project_dir = "/tmp/demo"
        self.files_written = ["a.py", "b.py"]
        self.install_ok = True
        self.tasks_passed = 2
        self.tasks_total = 2

    def to_dict(self) -> dict:
        return {
            "project_dir": self.project_dir,
            "files_written": self.files_written,
            "install_ok": self.install_ok,
            "tasks_passed": self.tasks_passed,
            "tasks_total": self.tasks_total,
        }


def test_cmd_scratch_full_execute_json(monkeypatch, capsys, tmp_path: Path) -> None:
    plan = _fake_plan()
    monkeypatch.setattr(scratch_cli, "_generate_plan_with_slots", lambda *a, **k: plan)

    import simplicio.scratch.executor as executor_mod

    monkeypatch.setattr(executor_mod, "execute_plan", lambda *a, **k: _FakeReport())

    rc = scratch_cli.main(
        ["a fastapi service", "--stack", "py-fastapi", "--dest", str(tmp_path), "--json"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["tasks_passed"] == 2


def test_cmd_scratch_full_execute_text_partial_failure(monkeypatch, capsys, tmp_path: Path) -> None:
    plan = _fake_plan()
    monkeypatch.setattr(scratch_cli, "_generate_plan_with_slots", lambda *a, **k: plan)

    class _PartialReport(_FakeReport):
        def __init__(self) -> None:
            super().__init__()
            self.tasks_passed = 1
            self.tasks_total = 2
            self.install_ok = False

    import simplicio.scratch.executor as executor_mod

    monkeypatch.setattr(executor_mod, "execute_plan", lambda *a, **k: _PartialReport())

    rc = scratch_cli.main(
        ["a fastapi service", "--stack", "py-fastapi", "--dest", str(tmp_path)]
    )
    err = capsys.readouterr().err
    assert rc == 1
    assert "fail/skipped" in err
    assert "1/2 passed" in err


def test_cmd_scratch_file_exists_error(monkeypatch, capsys, tmp_path: Path) -> None:
    plan = _fake_plan()
    monkeypatch.setattr(scratch_cli, "_generate_plan_with_slots", lambda *a, **k: plan)

    import simplicio.scratch.executor as executor_mod

    def _boom(*a, **k):
        raise FileExistsError("dir already exists")

    monkeypatch.setattr(executor_mod, "execute_plan", _boom)

    rc = scratch_cli.main(
        ["a fastapi service", "--stack", "py-fastapi", "--dest", str(tmp_path)]
    )
    err = capsys.readouterr().err
    assert rc == 4
    assert "already exists" in err


def test_list_recipes_registry_unavailable(monkeypatch, capsys) -> None:
    monkeypatch.setattr(scratch_cli, "_load_recipe_registry", lambda: None)
    rc = scratch_cli.main(["--list-recipes"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not available" in err
