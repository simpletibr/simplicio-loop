"""`map gc` and the central bases: keep the newest N and every base a live worktree still references (#1574)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from simplicio_loop import map_service_gc as gc
from simplicio_loop.map_service_cli import run
from simplicio_mapper.mapper.central_overlay import apply_overlay


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", raising=False)
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.email", "t@example.invalid")
    _git(main, "config", "user.name", "T")
    for index in range(4):
        (main / f"m{index}.py").write_text(f"def f{index}():\n    return {index}\n", encoding="utf-8")
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "one")
    a = tmp_path / "a"
    _git(main, "worktree", "add", "-q", "-b", "wa", str(a))
    apply_overlay(str(a))  # base #1, referenced by a's overlay.json
    (main / "m0.py").write_text("def moved():\n    return 9\n", encoding="utf-8")
    _git(main, "commit", "-qam", "two")
    b = tmp_path / "b"
    _git(main, "worktree", "add", "-q", "-b", "wb", str(b))
    apply_overlay(str(b))  # base #2 (the new default-branch tree), referenced by b
    canonical = main / ".git" / "simplicio" / "canonical"
    return {"main": main, "a": a, "b": b, "canonical": canonical}


def _bases(world) -> list[str]:
    return sorted(name for name in os.listdir(world["canonical"]) if "." not in name)


def _plan(world, **kwargs):
    import time

    return gc.plan_gc(str(world["main"]), now=time.time() + 7200, **kwargs)


def _actions(plan) -> dict[str, str]:
    return {Path(i.path).name: i.action for i in plan.items if i.kind == "canonical-base"}


def test_two_default_branch_trees_make_two_bases_and_both_are_referenced(world):
    assert len(_bases(world)) == 2
    state = json.loads((world["a"] / ".simplicio-loop" / "overlay.json").read_text(encoding="utf-8"))
    assert state["base_digest"] in _bases(world)
    assert set(gc.referenced_keys(str(world["main"]))["digests"]) == {
        json.loads((world[name] / ".simplicio-loop" / "overlay.json").read_text(encoding="utf-8"))["base_digest"]
        for name in ("a", "b")
    }


def test_a_base_a_live_worktree_references_survives_keep_zero(world):
    plan = _plan(world, keep=0)
    assert set(_actions(plan).values()) == {"keep"}, _actions(plan)
    gc.apply_gc(plan)
    assert len(_bases(world)) == 2


def test_an_unreferenced_old_base_is_removed_and_the_current_one_never_is(world):
    older = json.loads((world["a"] / ".simplicio-loop" / "overlay.json").read_text(encoding="utf-8"))["base_digest"]
    newer = json.loads((world["b"] / ".simplicio-loop" / "overlay.json").read_text(encoding="utf-8"))["base_digest"]
    _git(world["main"], "worktree", "remove", "--force", str(world["a"]))  # nobody references base #1 now
    plan = _plan(world, keep=0)
    actions = _actions(plan)
    assert actions[older] == "remove"
    assert actions[newer] == "keep"
    assert plan.would_free_bytes > 0
    result = gc.apply_gc(plan)
    assert _bases(world) == [newer]
    assert any(older in path for path in result.removed)


def test_keep_n_retains_unreferenced_bases_among_the_newest(world):
    _git(world["main"], "worktree", "remove", "--force", str(world["a"]))
    plan = _plan(world, keep=3)
    assert set(_actions(plan).values()) == {"keep"}


def test_dry_run_lists_bases_and_removes_nothing(world, capsys):
    _git(world["main"], "worktree", "remove", "--force", str(world["a"]))
    before = _bases(world)
    assert run("gc", repo=str(world["main"]), as_json=True, dry_run=True, keep=0, max_age=0.0) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True and payload["removed"] == []
    assert any(i["kind"] == "canonical-base" for i in payload["items"])
    assert _bases(world) == before
