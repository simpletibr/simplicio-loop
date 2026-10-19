"""The AGENTS.md hosts install like Codex and Grok: the skills plus the AGENTS.md marker block.

Each host below has the catalog surface `.claude/skills/ + AGENTS.md`. A project install writes the skills and the
marker block, a second run changes nothing, and uninstall removes exactly what install wrote. A user's own
AGENTS.md keeps its text. Orca is installed by name only: `--host all` never enables it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from simplicio_loop import cli, cli_impl, setup_cli
from simplicio_loop.install import entry
from simplicio_loop.install.planner import InstallError, apply_plan, plan_install, uninstall

AGENTS_MD_HOSTS = (
    "mimo-code", "amp", "openclaude", "antigravity", "pi", "oh-my-pi", "devin", "goose", "auggie", "autohand",
    "charm", "cline", "codebuff", "command-code", "droid", "kilocode", "kimi", "mistral-vibe", "rovo-dev",
    "orca-dev",
)


def make_bundle(root: Path) -> Path:
    skill = root / "skills" / "simplicio-loop"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("loop\n", encoding="utf-8")
    (root / "hooks").mkdir()
    (root / "hooks" / "loop_stop.py").write_text("# stop\n", encoding="utf-8")
    return root


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def bundle(tmp_path):
    return make_bundle(tmp_path / "bundle")


@pytest.fixture
def repo(tmp_path):
    target = tmp_path / "repo"
    target.mkdir()
    return target


@pytest.mark.parametrize("host", AGENTS_MD_HOSTS)
def test_project_install_writes_the_skills_and_the_marker_block_once(host, repo, bundle):
    result = apply_plan(plan_install(repo, host=host), bundle=bundle)
    assert result["status"] == "applied"
    assert (repo / ".claude" / "skills" / "simplicio-loop" / "SKILL.md").is_file()
    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert text.count(entry.BEGIN) == 1 and text.count(entry.END) == 1
    assert "AGENTS.md" in result["changes"]["created"]


@pytest.mark.parametrize("host", AGENTS_MD_HOSTS)
def test_a_second_run_changes_nothing(host, repo, bundle):
    apply_plan(plan_install(repo, host=host), bundle=bundle)
    before = snapshot(repo)
    again = apply_plan(plan_install(repo, host=host), bundle=bundle)
    assert again["up_to_date"] is True
    assert again["written"] == 0
    assert snapshot(repo) == before


@pytest.mark.parametrize("host", AGENTS_MD_HOSTS)
def test_uninstall_removes_exactly_what_install_wrote(host, repo, bundle):
    apply_plan(plan_install(repo, host=host), bundle=bundle)
    uninstall(repo)
    assert sorted(repo.rglob("*")) == []


@pytest.mark.parametrize("host", AGENTS_MD_HOSTS)
def test_a_users_agents_md_keeps_its_text_and_loses_only_the_block(host, repo, bundle):
    user_text = "# Project rules\n\nUse four spaces.\n"
    (repo / "AGENTS.md").write_text(user_text, encoding="utf-8")
    apply_plan(plan_install(repo, host=host), bundle=bundle)
    assert (repo / "AGENTS.md").read_text(encoding="utf-8").startswith(user_text)
    uninstall(repo)
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == user_text


@pytest.mark.parametrize("host", AGENTS_MD_HOSTS)
def test_global_install_writes_skills_hooks_and_the_block_into_home(host, tmp_path, bundle):
    home = tmp_path / "home"
    home.mkdir()
    apply_plan(plan_install(home, host=host, globally=True), bundle=bundle)
    assert (home / ".claude" / "skills" / "simplicio-loop" / "SKILL.md").is_file()
    assert (home / ".claude" / "hooks" / "loop_stop.py").is_file()
    assert (home / "AGENTS.md").read_text(encoding="utf-8").count(entry.BEGIN) == 1
    again = apply_plan(plan_install(home, host=host, globally=True), bundle=bundle)
    assert again["up_to_date"] is True
    uninstall(home)
    assert sorted(home.rglob("*")) == []


def test_a_receipt_that_listed_the_entry_file_whole_stops_owning_it_as_a_whole(repo, bundle):
    apply_plan(plan_install(repo, host="amp"), bundle=bundle)
    receipt = repo / ".simplicio-loop" / "install-ownership.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["paths"] = sorted([*payload["paths"], "AGENTS.md"])  # what an older install registered
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    apply_plan(plan_install(repo, host="amp"), bundle=bundle)
    corrected = json.loads(receipt.read_text(encoding="utf-8"))
    assert "AGENTS.md" not in corrected["paths"]
    assert corrected["blocks"] == [{"path": "AGENTS.md", "created": True}]


def test_a_catalog_id_or_alias_resolves_to_its_installer_runtime(tmp_path):
    assert plan_install(tmp_path, host="orca-dev")["hosts"] == ["orca"]
    assert plan_install(tmp_path, host="orca")["hosts"] == ["orca"]
    assert plan_install(tmp_path, host="claude-code")["hosts"] == ["claude"]


def test_orca_is_installed_by_name_and_never_by_all(tmp_path):
    assert "orca" not in plan_install(tmp_path, host="all")["hosts"]
    assert "orca" not in plan_install(tmp_path, host="all", globally=True)["hosts"]


def test_an_unknown_host_still_fails_closed(tmp_path):
    with pytest.raises(InstallError, match="unknown host"):
        plan_install(tmp_path, host="not-a-host")


def test_the_cli_installs_orca_dev_by_name(repo, bundle, monkeypatch, capsys):
    monkeypatch.setattr(cli_impl, "BUNDLE", bundle)
    monkeypatch.setattr(setup_cli, "after_install", lambda: None)
    rc = cli.main(["install", "--target", str(repo), "--host", "orca-dev"])
    assert rc == 0
    assert (repo / "AGENTS.md").read_text(encoding="utf-8").count(entry.BEGIN) == 1
    assert "host   -> orca-dev" in capsys.readouterr().out


def test_the_block_names_the_skill_the_host_must_load(tmp_path):
    body = entry.block()
    assert body.startswith(entry.BEGIN) and body.endswith(entry.END)
    assert ".claude/skills/simplicio-loop/SKILL.md" in body
