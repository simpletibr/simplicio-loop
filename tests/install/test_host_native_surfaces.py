"""Each host's skills and instruction file land where that host's own docs say it reads them (wave C, items 1-3 and 8).

The planner is the one host table. `.claude/skills` stays the universal copy because every entry block points at it;
the native skill root and the user-level instruction file come from the host docs (adapters/MATRIX.md and the catalog
`source` of each host). A host whose docs name no user-level instruction file is skipped for --global and reported.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from simplicio_loop import host_detect, host_rules, skill_sync
from simplicio_loop.install import entry, planner
from simplicio_loop.install.planner import apply_plan, plan_install, uninstall

REPO = Path(__file__).resolve().parents[2]


def make_bundle(root: Path) -> Path:
    skill = root / "skills" / "simplicio-loop"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("loop\n", encoding="utf-8")
    (root / "hooks").mkdir()
    (root / "hooks" / "loop_stop.py").write_text("# stop\n", encoding="utf-8")
    return root


@pytest.fixture
def bundle(tmp_path):
    return make_bundle(tmp_path / "bundle")


@pytest.mark.parametrize("host,skill_file", [
    ("pi", ".pi/skills/simplicio-loop/SKILL.md"),
    ("mistral-vibe", ".vibe/skills/simplicio-loop/SKILL.md"),
    ("gemini", ".gemini/skills/simplicio-loop/SKILL.md"),
    ("kiro", ".kiro/skills/simplicio-loop/SKILL.md"),
    ("simplicio_agent", ".hermes/skills/simplicio-loop/SKILL.md"),
])
def test_a_project_install_writes_the_skill_root_the_host_reads(tmp_path, bundle, host, skill_file):
    repo = tmp_path / "repo"
    repo.mkdir()
    apply_plan(plan_install(repo, host=host), bundle=bundle)
    assert (repo / skill_file).is_file()
    assert (repo / ".claude/skills/simplicio-loop/SKILL.md").is_file(), "the universal copy the entry block names"


def test_native_skill_copies_are_recorded_in_the_receipt_and_removed_by_uninstall(tmp_path, bundle):
    repo = tmp_path / "repo"
    repo.mkdir()
    apply_plan(plan_install(repo, host="pi"), bundle=bundle)
    receipt = json.loads((repo / ".simplicio-loop/install-ownership.json").read_text(encoding="utf-8"))
    assert ".pi/skills/simplicio-loop/SKILL.md" in receipt["paths"]

    uninstall(repo)

    assert not (repo / ".pi/skills/simplicio-loop/SKILL.md").exists()
    assert not (repo / ".pi").exists()


def test_skill_sync_roots_are_the_installer_user_roots(tmp_path):
    """One table: skill_sync resyncs the root the installer writes, so the two cannot disagree (item 3)."""
    expected = {host: root for host, root in planner.GLOBAL_SKILL_ROOTS.items()}
    expected["claude"] = ".claude/skills"
    assert skill_sync.HOST_SKILL_ROOTS == expected
    assert skill_sync.HOST_SKILL_ROOTS["simplicio_agent"] == ".hermes/skills"


def test_skill_sync_does_not_count_a_shared_root_twice(tmp_path):
    home = tmp_path / "home"
    shared = home / ".agents" / "skills" / "simplicio-loop"
    shared.mkdir(parents=True)
    (shared / "SKILL.md").write_text("old\n", encoding="utf-8")

    hosts = skill_sync.installed_skill_hosts(home)

    assert list(hosts.values()).count(home / ".agents" / "skills") == 1


def test_global_gemini_block_goes_into_the_user_file_and_uninstall_restores_its_bytes(tmp_path, bundle, monkeypatch):
    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True)
    user_file = home / ".gemini" / "GEMINI.md"
    user_file.write_text("my own rules\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SIMPLICIO_HOME", str(home))

    apply_plan(plan_install(home, host="gemini", globally=True), bundle=bundle)

    text = user_file.read_text(encoding="utf-8")
    assert text.startswith("my own rules\n") and text.count(entry.BEGIN) == 1
    assert "~/.claude/skills/simplicio-loop/SKILL.md" in text, "a global block names the user-level skill, not a project path"
    uninstall(home)
    assert user_file.read_bytes() == b"my own rules\n"


def test_global_install_reports_the_hosts_without_a_documented_user_instruction_file(tmp_path):
    plan = plan_install(tmp_path, host="all", globally=True)

    assert sorted(plan["global_skipped"]) == ["aider", "continue", "droid", "grok", "openclaude"]
    written = {action["destination"] for action in plan["actions"] if action["kind"] == "entry"}
    assert ".gemini/GEMINI.md" in written and ".codex/AGENTS.md" in written
    assert not {"AGENTS.md", "GEMINI.md", "CONVENTIONS.md"} & written, "project paths must not land in $HOME"


def test_global_entry_paths_are_the_documented_user_files():
    assert planner.GLOBAL_ENTRIES["gemini"] == ".gemini/GEMINI.md"
    assert planner.GLOBAL_ENTRIES["qwen"] == ".qwen/QWEN.md"
    assert planner.GLOBAL_ENTRIES["opencode"] == ".config/opencode/AGENTS.md"
    assert planner.GLOBAL_ENTRIES["kiro"] == ".kiro/steering/simplicio-loop.md"


def test_host_detect_knows_every_wired_host_that_has_an_executable():
    ids = {spec.id for spec in host_detect.HOSTS}
    assert {"aider", "openclaw"} <= ids


def test_host_rules_have_user_rule_rows_for_the_hosts_that_document_a_rules_folder(tmp_path):
    names = {name for name, _ in host_rules.global_destinations(tmp_path)}
    assert {"cline_rules", "auggie_rules", "devin_rules"} <= names


def test_dashboard_lists_every_wired_host_once_per_host_id(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO / "hooks"))
    import simplicio_dashboard as dashboard

    catalog = json.loads((REPO / "simplicio_loop" / "_catalog" / "harnesses.json").read_text(encoding="utf-8"))
    wired = {item["id"] for item in catalog["harnesses"] if item["install"]["status"] == "wired"}
    assert {row["host"] for row in dashboard.RUNTIMES} == wired


def test_cli_global_install_then_uninstall_keeps_the_users_gemini_file_byte_for_byte(tmp_path, monkeypatch, capsys):
    """The round trip the wave asks for, through the command: `install --global --host gemini` adds the block to the
    user's ~/.gemini/GEMINI.md and keeps its text; `install --global --uninstall` leaves the original bytes."""
    from simplicio_loop import cli, cli_impl, setup_cli

    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True)
    user_file = home / ".gemini" / "GEMINI.md"
    user_file.write_text("my own rules\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SIMPLICIO_HOME", str(home))
    monkeypatch.setattr(cli_impl, "BUNDLE", make_bundle(tmp_path / "bundle"))
    monkeypatch.setattr(setup_cli, "after_install", lambda **kw: 0)

    assert cli.main(["install", "--global", "--host", "gemini"]) == 0
    text = user_file.read_text(encoding="utf-8")
    assert text.startswith("my own rules\n") and text.count(entry.BEGIN) == 1
    assert not (home / "GEMINI.md").exists() and not (home / "AGENTS.md").exists()

    assert cli.main(["install", "--global", "--host", "gemini", "--uninstall"]) == 0
    assert user_file.read_bytes() == b"my own rules\n"
