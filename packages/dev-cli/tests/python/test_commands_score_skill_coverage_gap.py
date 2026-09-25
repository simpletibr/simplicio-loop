"""Unit coverage for simplicio/commands/score_skill.py (previously 17%)."""

from __future__ import annotations

import argparse
import json

import pytest

from simplicio.commands import score_skill as ss


def test_norm_collapses_whitespace_and_lowercases():
    assert ss.norm("  Hello   World  ") == "hello world"


def test_phrase_present_true_and_false():
    text = ss.norm("the quick brown fox")
    assert ss.phrase_present(text, "Quick Brown") is True
    assert ss.phrase_present(text, "slow turtle") is False


def test_score_all_pass():
    scenarios = [
        {
            "id": "s1",
            "must_include_any": [["quick", "fast"]],
            "must_not_include": ["slow"],
        }
    ]
    result = ss.score("the quick fox", scenarios)
    assert result["ok"] is True
    assert result["passed"] == 1
    assert result["score"] == 1.0


def test_score_missing_group_fails():
    scenarios = [{"id": "s1", "must_include_any": [["nonexistent"]]}]
    result = ss.score("plain text", scenarios)
    assert result["ok"] is False
    assert result["results"][0]["missing_groups"] == [["nonexistent"]]


def test_score_forbidden_hit_fails():
    scenarios = [{"id": "s1", "must_not_include": ["forbidden"]}]
    result = ss.score("text with forbidden word", scenarios)
    assert result["ok"] is False
    assert "forbidden" in result["results"][0]["forbidden_hits"]


def test_score_empty_scenarios_gives_zero_score():
    result = ss.score("text", [])
    assert result["total"] == 0
    assert result["score"] == 0.0
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# _load_text / _resolve_scenarios
# ---------------------------------------------------------------------------


def test_load_text_from_file(tmp_path):
    f = tmp_path / "skill.md"
    f.write_text("hello", encoding="utf-8")
    assert ss._load_text(str(f)) == "hello"


def test_load_text_from_stdin(monkeypatch):
    import io

    monkeypatch.setattr(ss.sys, "stdin", io.StringIO("from stdin"))
    assert ss._load_text("-") == "from stdin"


def test_resolve_scenarios_from_explicit_file_list(tmp_path):
    f = tmp_path / "scenarios.json"
    f.write_text(json.dumps([{"id": "a"}, {"id": "b"}]), encoding="utf-8")
    result = ss._resolve_scenarios([str(f)], [], tmp_path / "builtin")
    assert [s["id"] for s in result] == ["a", "b"]


def test_resolve_scenarios_from_explicit_single_dict_file(tmp_path):
    f = tmp_path / "scenario.json"
    f.write_text(json.dumps({"id": "solo"}), encoding="utf-8")
    result = ss._resolve_scenarios([str(f)], [], tmp_path / "builtin")
    assert result == [{"id": "solo"}]


def test_resolve_scenarios_raises_on_unexpected_shape(tmp_path):
    f = tmp_path / "scenario.json"
    f.write_text(json.dumps("just a string"), encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected JSON structure"):
        ss._resolve_scenarios([str(f)], [], tmp_path / "builtin")


def test_resolve_scenarios_falls_back_to_builtin_dir(tmp_path):
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "a.json").write_text(json.dumps([{"id": "builtin-a"}]), encoding="utf-8")
    (builtin_dir / "b.json").write_text(json.dumps({"id": "builtin-b"}), encoding="utf-8")
    result = ss._resolve_scenarios([], [], builtin_dir)
    ids = sorted(s["id"] for s in result)
    assert ids == ["builtin-a", "builtin-b"]


def test_resolve_scenarios_missing_builtin_dir_returns_empty(tmp_path):
    result = ss._resolve_scenarios([], [], tmp_path / "nonexistent")
    assert result == []


def test_resolve_scenarios_appends_extra_scenarios(tmp_path):
    extra = [json.dumps({"id": "extra1"}), json.dumps([{"id": "extra2"}])]
    result = ss._resolve_scenarios([], extra, tmp_path / "builtin")
    ids = [s["id"] for s in result]
    assert ids == ["extra1", "extra2"]


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def test_main_all_pass_text(tmp_path, capsys):
    skill_file = tmp_path / "skill.md"
    skill_file.write_text("must have quick action here", encoding="utf-8")
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(json.dumps([{"id": "s1", "must_include_any": [["quick"]]}]), encoding="utf-8")

    rc = ss.main([str(skill_file), "--scenario", str(scenario_file)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Score: 100%" in out
    assert "All ok: True" in out


def test_main_json_output(tmp_path, capsys):
    skill_file = tmp_path / "skill.md"
    skill_file.write_text("quick", encoding="utf-8")
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(json.dumps([{"id": "s1", "must_include_any": [["quick"]]}]), encoding="utf-8")

    rc = ss.main([str(skill_file), "--scenario", str(scenario_file), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["ok"] is True


def test_main_failure_prints_details(tmp_path, capsys):
    skill_file = tmp_path / "skill.md"
    skill_file.write_text("nothing relevant", encoding="utf-8")
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(
        json.dumps(
            [
                {
                    "id": "s1",
                    "must_include_any": [["quick"]],
                    "must_not_include": ["relevant"],
                    "failure": "missing keyword and has forbidden word",
                }
            ]
        ),
        encoding="utf-8",
    )

    rc = ss.main([str(skill_file), "--scenario", str(scenario_file)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "missing any of" in out
    assert "forbidden hit" in out
    assert "failure:" in out


def test_main_verbose_prints_even_on_success(tmp_path, capsys):
    skill_file = tmp_path / "skill.md"
    skill_file.write_text("quick", encoding="utf-8")
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(json.dumps([{"id": "s1", "must_include_any": [["quick"]]}]), encoding="utf-8")

    rc = ss.main([str(skill_file), "--scenario", str(scenario_file), "--verbose"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "s1" in out


def test_main_invalid_skill_path_returns_2(tmp_path, capsys):
    rc = ss.main([str(tmp_path / "does-not-exist.md")])
    err = capsys.readouterr().err
    assert rc == 2
    assert "simplicio score-skill:" in err


def test_main_no_scenarios_found_returns_2(tmp_path, monkeypatch, capsys):
    skill_file = tmp_path / "skill.md"
    skill_file.write_text("text", encoding="utf-8")
    monkeypatch.setattr(ss, "_resolve_scenarios", lambda *a, **k: [])
    rc = ss.main([str(skill_file)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "no scenarios found" in err


def test_main_invalid_scenario_json_returns_2(tmp_path, capsys):
    skill_file = tmp_path / "skill.md"
    skill_file.write_text("text", encoding="utf-8")
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text("not json", encoding="utf-8")

    rc = ss.main([str(skill_file), "--scenario", str(scenario_file)])
    capsys.readouterr()
    assert rc == 2


def test_main_extra_scenario_inline(tmp_path, capsys):
    skill_file = tmp_path / "skill.md"
    skill_file.write_text("quick", encoding="utf-8")
    empty_scenarios = tmp_path / "empty.json"
    empty_scenarios.write_text(json.dumps([]), encoding="utf-8")

    rc = ss.main(
        [
            str(skill_file),
            "--scenario",
            str(empty_scenarios),
            "--extra-scenario",
            json.dumps({"id": "inline", "must_include_any": [["quick"]]}),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Score: 100%" in out


# ---------------------------------------------------------------------------
# run() adapter
# ---------------------------------------------------------------------------


def test_run_adapter_falls_back_to_python_main(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("simplicio.commands._shared.try_route_via_simplicio", lambda *a, **k: None)
    skill_file = tmp_path / "skill.md"
    skill_file.write_text("quick", encoding="utf-8")
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(json.dumps([{"id": "s1", "must_include_any": [["quick"]]}]), encoding="utf-8")

    ns = argparse.Namespace(
        skill=str(skill_file),
        scenario_sources=[str(scenario_file)],
        extra_scenario=[],
        json=False,
        verbose=False,
        native=False,
        python=True,
    )
    rc = ss.run(ns)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Score: 100%" in out


def test_run_adapter_uses_native_result_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr("simplicio.commands._shared.try_route_via_simplicio", lambda *a, **k: 0)
    ns = argparse.Namespace(
        skill="-",
        scenario_sources=[],
        extra_scenario=[],
        json=True,
        verbose=False,
        native=True,
        python=False,
    )
    rc = ss.run(ns)
    assert rc == 0
