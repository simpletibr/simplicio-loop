"""The Claude Code hook wiring that `simplicio-loop install` writes into `.claude/settings.json`.

The merge keeps every key and hook the user already has, is idempotent, and is recorded in the ownership receipt so
`install --uninstall` removes exactly the entries it added. The git-clone installer uses the same code
(simplicio_loop/install/claude_hooks.py), so the two cannot drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_loop.install import claude_hooks as ch
from simplicio_loop.install.planner import (
    InstallError,
    apply_plan,
    plan_install,
    prune_project_copies,
    uninstall,
)

HOOK_FILES = ("loop_stop.py", "action_gate.py", "orient_rewrite.py")

STOP_GROUP = {"hooks": [{"type": "command", "command": "python3 ./hooks/loop_stop.py"}]}
GATE_GROUP = {"hooks": [{"type": "command", "command": "python3 ./hooks/action_gate.py"}]}
REWRITE_GROUP = {
    "matcher": "Bash",
    "hooks": [{"type": "command", "command": "python3 ./hooks/orient_rewrite.py"}],
}
USER_STOP = {"hooks": [{"type": "command", "command": "echo user-stop"}]}
USER_PRE = {"matcher": "Write", "hooks": [{"type": "command", "command": "echo user-pre"}]}


def make_bundle(root: Path, hooks: tuple = HOOK_FILES) -> Path:
    skill = root / "skills" / "simplicio-loop"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("loop\n", encoding="utf-8")
    (root / "hooks").mkdir()
    for name in hooks:
        (root / "hooks" / name).write_text("# hook\n", encoding="utf-8")
    return root


def install(root: Path, bundle: Path, *, globally: bool = False) -> dict:
    return apply_plan(plan_install(root, host="claude", globally=globally), bundle=bundle)


def settings_path(root: Path) -> Path:
    return root / ".claude" / "settings.json"


def settings_of(root: Path) -> dict:
    return json.loads(settings_path(root).read_text(encoding="utf-8"))


def write_settings(root: Path, data) -> None:
    settings_path(root).parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data)
    settings_path(root).write_text(text, encoding="utf-8")


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    return make_bundle(tmp_path / "bundle")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    folder = tmp_path / "repo"
    folder.mkdir()
    return folder


# --- the file, through the package install ----------------------------------------------------------------------


def test_fresh_project_gets_the_stop_and_pretooluse_hooks(repo, bundle):
    install(repo, bundle)
    assert settings_of(repo) == {"hooks": {
        "Stop": [STOP_GROUP],
        "PreToolUse": [GATE_GROUP, REWRITE_GROUP],
    }}
    for name in HOOK_FILES:
        assert (repo / "hooks" / name).is_file()


def test_user_settings_and_hooks_are_kept_and_ours_come_after_them(repo, bundle):
    write_settings(repo, {
        "model": "sonnet",
        "hooks": {
            "SessionStart": [USER_STOP],
            "Stop": [USER_STOP],
            "PreToolUse": [USER_PRE],
        },
    })
    install(repo, bundle)
    settings = settings_of(repo)
    assert settings["model"] == "sonnet"
    assert settings["hooks"]["SessionStart"] == [USER_STOP]
    assert settings["hooks"]["Stop"] == [USER_STOP, STOP_GROUP]
    assert settings["hooks"]["PreToolUse"] == [USER_PRE, GATE_GROUP, REWRITE_GROUP]


def test_a_second_install_changes_nothing(repo, bundle):
    install(repo, bundle)
    before = settings_path(repo).read_bytes()
    second = install(repo, bundle)
    assert second["up_to_date"] is True
    assert settings_path(repo).read_bytes() == before
    assert ".claude/settings.json" not in second["changes"]["created"] + second["changes"]["updated"]


def test_uninstall_after_two_installs_still_removes_exactly_what_was_added(repo, bundle):
    user = {"model": "sonnet", "hooks": {"Stop": [USER_STOP]}}
    write_settings(repo, user)
    install(repo, bundle)
    install(repo, bundle)
    uninstall(repo)
    assert settings_of(repo) == user


def test_uninstall_removes_only_the_entries_it_added(repo, bundle):
    user = {"model": "sonnet", "hooks": {"Stop": [USER_STOP], "PreToolUse": [USER_PRE]}}
    write_settings(repo, user)
    install(repo, bundle)
    result = uninstall(repo)
    assert settings_of(repo) == user
    assert ".claude/settings.json" in result["unwired"]


def test_uninstall_deletes_the_settings_file_it_created_and_returns_to_baseline(repo, bundle):
    install(repo, bundle)
    result = uninstall(repo)
    assert not settings_path(repo).exists()
    assert ".claude/settings.json" in result["removed"]
    assert sorted(repo.rglob("*")) == []


def test_uninstall_keeps_an_empty_event_list_the_user_already_had(repo, bundle):
    write_settings(repo, {"hooks": {"Stop": []}})
    install(repo, bundle)
    uninstall(repo)
    assert settings_of(repo) == {"hooks": {"Stop": []}}


def test_a_loop_entry_the_user_wired_by_hand_is_not_claimed_by_uninstall(repo, bundle):
    user = {"hooks": {"Stop": [STOP_GROUP]}}
    write_settings(repo, user)
    install(repo, bundle)
    assert settings_of(repo)["hooks"]["Stop"] == [STOP_GROUP], "no duplicate of the user's own loop_stop entry"
    uninstall(repo)
    assert settings_of(repo) == user


def test_dry_run_writes_nothing_and_reports_the_settings_file(repo, bundle):
    result = apply_plan(plan_install(repo, host="claude"), dry_run=True, bundle=bundle)
    assert ".claude/settings.json" in result["changes"]["created"]
    assert not (repo / ".claude").exists()


def test_dry_run_on_an_existing_settings_file_leaves_its_bytes_alone(repo, bundle):
    write_settings(repo, {"model": "sonnet"})
    before = settings_path(repo).read_bytes()
    result = apply_plan(plan_install(repo, host="claude"), dry_run=True, bundle=bundle)
    assert ".claude/settings.json" in result["changes"]["updated"]
    assert settings_path(repo).read_bytes() == before


@pytest.mark.parametrize(
    "body",
    ["{not json", '["an", "array"]', '{"hooks": []}', '{"hooks": {"Stop": {}}}', '{"hooks": {"Stop": [7]}}'],
)
def test_unreadable_or_mis_shaped_settings_fail_closed_before_anything_is_written(repo, bundle, body):
    settings_path(repo).parent.mkdir(parents=True)
    settings_path(repo).write_text(body, encoding="utf-8")
    with pytest.raises(InstallError, match="settings.json"):
        install(repo, bundle)
    assert settings_path(repo).read_text(encoding="utf-8") == body
    assert not (repo / "hooks").exists()
    assert not (repo / ".claude" / "skills").exists()
    assert not (repo / ".simplicio-loop").exists()


def test_uninstall_refuses_settings_it_cannot_read_and_removes_nothing(repo, bundle):
    install(repo, bundle)
    settings_path(repo).write_text("{oops", encoding="utf-8")
    with pytest.raises(InstallError, match="settings.json"):
        uninstall(repo)
    assert (repo / "hooks" / "loop_stop.py").is_file()
    assert (repo / ".claude" / "skills" / "simplicio-loop" / "SKILL.md").is_file()
    assert (repo / ".simplicio-loop" / "install-ownership.json").is_file()


def test_a_hook_the_bundle_does_not_ship_is_not_wired(repo, tmp_path):
    thin = make_bundle(tmp_path / "thin", hooks=("loop_stop.py",))
    install(repo, thin)
    assert settings_of(repo) == {"hooks": {"Stop": [STOP_GROUP]}}


def test_global_install_wires_absolute_paths_and_no_orient_rewrite(tmp_path, bundle):
    home = tmp_path / "home"
    home.mkdir()
    install(home, bundle, globally=True)
    hooks = home.resolve() / ".claude" / "hooks"
    assert settings_of(home) == {"hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": f'python3 "{(hooks / "loop_stop.py").as_posix()}"'}]}],
        "PreToolUse": [{"hooks": [{"type": "command", "command": f'python3 "{(hooks / "action_gate.py").as_posix()}"'}]}],
    }}
    for name in ("loop_stop.py", "action_gate.py", "orient_rewrite.py"):
        assert (hooks / name).is_file()


def test_prune_unwires_the_project_hooks_it_registered_and_keeps_the_users(repo, bundle):
    user = {"model": "sonnet"}
    write_settings(repo, user)
    install(repo, bundle)
    result = prune_project_copies(repo)
    assert settings_of(repo) == user
    assert ".claude/settings.json" in result["unwired"]
    assert not (repo / "hooks" / "loop_stop.py").exists()


@pytest.mark.parametrize(
    "record",
    [
        "not-a-record",
        {"entries": "x", "created_events": [], "created_hooks": False, "file_created": False},
        {"entries": [{"event": 1, "matcher": None, "command": "x"}], "created_events": [],
         "created_hooks": False, "file_created": False},
        {"entries": [], "created_events": [], "created_hooks": False, "file_created": "yes"},
    ],
)
def test_a_malformed_settings_record_in_the_receipt_removes_nothing(repo, bundle, record):
    install(repo, bundle)
    receipt = repo / ".simplicio-loop" / "install-ownership.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["claude_settings"] = record
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    before = settings_path(repo).read_bytes()
    with pytest.raises(InstallError, match="malformed"):
        uninstall(repo)
    assert settings_path(repo).read_bytes() == before
    assert (repo / "hooks" / "loop_stop.py").is_file()


def test_prune_refuses_an_unreadable_settings_file_before_deleting_anything(repo, bundle):
    install(repo, bundle)
    settings_path(repo).write_text("{oops", encoding="utf-8")
    with pytest.raises(InstallError, match="settings.json"):
        prune_project_copies(repo)
    assert (repo / "hooks" / "loop_stop.py").is_file()
    assert (repo / ".claude" / "skills" / "simplicio-loop" / "SKILL.md").is_file()


# --- the pure merge ---------------------------------------------------------------------------------------------

STOP = ch.Entry("Stop", "loop_stop.py", "python3 ./hooks/loop_stop.py")
REWRITE = ch.Entry("PreToolUse", "orient_rewrite.py", "python3 ./hooks/orient_rewrite.py", matcher="Bash")


def test_wire_on_a_missing_file_adds_every_entry_and_says_what_it_created():
    wiring = ch.wire(None, [STOP, REWRITE])
    assert wiring.data == {"hooks": {"Stop": [STOP_GROUP], "PreToolUse": [REWRITE_GROUP]}}
    assert wiring.added == [STOP, REWRITE]
    assert wiring.created_events == ["Stop", "PreToolUse"]
    assert wiring.created_hooks is True


def test_wire_when_every_entry_is_present_adds_nothing():
    first = ch.wire(None, [STOP, REWRITE])
    again = ch.wire(first.data, [STOP, REWRITE])
    assert again.added == [] and again.data == first.data
    assert again.created_events == [] and again.created_hooks is False


def test_unwire_removes_the_recorded_entries_and_only_the_containers_it_created():
    wiring = ch.wire({"model": "sonnet"}, [STOP, REWRITE])
    record = ch.record_of(None, wiring)
    data = wiring.data
    data["hooks"]["Stop"].append(USER_STOP)  # the user added a hook after the install
    data["hooks"]["Keep"] = []  # an event the user made and we never touched
    restored, removed = ch.unwire(data, record)
    assert removed == 2
    assert restored == {"model": "sonnet", "hooks": {"Stop": [USER_STOP], "Keep": []}}


def test_a_record_with_the_wrong_shape_is_not_valid():
    assert ch.valid_record({"file_created": True, "created_hooks": True, "created_events": ["Stop"],
                            "entries": [{"event": "Stop", "matcher": None, "command": "x"}]})
    assert not ch.valid_record({"entries": "x", "file_created": False, "created_hooks": False, "created_events": []})
    assert not ch.valid_record({"entries": [{"event": 1, "matcher": None, "command": "x"}],
                                "file_created": False, "created_hooks": False, "created_events": []})
    assert not ch.valid_record({"entries": [], "file_created": "yes", "created_hooks": False, "created_events": []})
    assert not ch.valid_record(None)
