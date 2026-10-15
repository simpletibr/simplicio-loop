"""An impact selection whose base ref does not resolve fails closed, never a silent pass (#1825).

A shallow clone without origin/main has no base to diff against. Selecting zero tests there and exiting 0 is a
fake green, so the selection raises a typed reason that names the fix: fetch the base, pass --full, or --base REF.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pkg").mkdir()
    (path / "pkg" / "shop.py").write_text("def total():\n    return 1\n", encoding="utf-8")
    (path / "tests").mkdir()
    (path / "tests" / "test_total.py").write_text("from pkg.shop import total\n", encoding="utf-8")
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"],
                 ["add", "-A"], ["commit", "-qm", "seed"]):
        subprocess.run(["git", *args], cwd=path, check=True)
    return path


def _point_origin_main_at_head(repo: Path) -> None:
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=repo, check=True)


def test_an_unresolvable_base_raises_the_typed_reason_with_the_fix_in_the_message(tmp_path, monkeypatch):
    impact = _load("impact_tests")
    repo = _git_repo(tmp_path / "shallow-like")  # no refs/remotes/origin/main, as after a `--depth 1` clone
    monkeypatch.setattr(impact, "ROOT", repo)
    (repo / "pkg" / "shop.py").write_text("def total():\n    return 2\n", encoding="utf-8")

    try:
        impact.impacted_tests("origin/main")
    except impact.BaseRefUnresolved as error:
        assert error.reason == "impact_base_unresolved" and error.base == "origin/main"
        message = str(error)
        assert "git fetch origin main" in message and "--full" in message and "--base" in message
    else:
        raise AssertionError("an unresolvable base must fail closed, not select nothing")


def test_a_resolvable_base_still_selects_the_impacted_tests(tmp_path, monkeypatch):
    impact = _load("impact_tests")
    repo = _git_repo(tmp_path / "full")
    _point_origin_main_at_head(repo)
    monkeypatch.setattr(impact, "ROOT", repo)
    (repo / "pkg" / "shop.py").write_text("def total():\n    return 2\n", encoding="utf-8")
    assert impact.impacted_tests("origin/main")[0] == ["tests/test_total.py"]


def test_the_impact_cli_exits_2_and_prints_the_reason_when_the_base_is_missing(tmp_path, monkeypatch, capsys):
    impact = _load("impact_tests")
    repo = _git_repo(tmp_path / "cli")
    monkeypatch.setattr(impact, "ROOT", repo)
    assert impact.main(["--base", "origin/main"]) == 2
    err = capsys.readouterr().err
    assert "impact_base_unresolved" in err and "git fetch origin main" in err
    assert capsys.readouterr().out == ""


def test_check_turns_an_unresolvable_base_into_a_failed_tests_gate_that_runs_no_pytest(tmp_path, monkeypatch, capsys):
    impact = _load("impact_tests")
    check = _load("check")
    repo = _git_repo(tmp_path / "gate")
    monkeypatch.setattr(impact, "ROOT", repo)
    monkeypatch.setattr(check, "_IMPACT_CACHE", {})
    ran = []
    monkeypatch.setattr(check, "_have_pytest", lambda: ran.append("probe") or True)

    result = check.run_tests(impact=True, base_ref="origin/main")

    assert not result.ok and result.reason_code == "impact_base_unresolved"
    assert ran == []  # the gate stops before any test file is selected or run
    assert "git fetch origin main" in capsys.readouterr().out


def test_a_package_gate_with_an_unresolvable_base_fails_closed_before_any_tool_runs(monkeypatch):
    check = _load("check")

    def unresolved(base):
        impact = sys.modules["impact_tests"]
        raise impact.BaseRefUnresolved(base)

    ran = []
    monkeypatch.setattr(check, "_impacted_test_files", unresolved)
    monkeypatch.setattr(check, "_run_step", lambda *a, **kw: ran.append(a) or None)
    result = check.run_package_gate("mapper", impact=True, base="origin/main")
    assert not result.ok and result.reason_code == "impact_base_unresolved"
    assert ran == []
