"""No plan creates, edits, moves or deletes a protected path (issue #1567).

The watcher applies plans written by a model that reads the text of an issue. A plan that edits ``.simplicio-loop/loop.toml``
(the opt-in, the allowed authors, the ``verify`` command), a workflow, CODEOWNERS, a hook, the systemd unit, the local CI or
one of the gates lets the next step approve its own change. ``plan_paths.PROTECTED_PATHS`` names them and every write
checkpoint (``operations_refusal`` in ``turbo.apply_plan``, ``apply`` and the runner) refuses them with the reason
``protected_path``: through any spelling the file system reads as the same name, through a symlink, and as a parent
directory that would carry the file away. Reading an excerpt of such a file stays allowed. Only fake data lives here.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from simplicio_loop import apply as loop_apply
from simplicio_loop import intake_gate, plan_paths, turbo, turbo_window

ROOT = Path(__file__).resolve().parents[1]

# (path a plan names, the PROTECTED_PATHS entry the reason must name)
PROTECTED = [
    pytest.param(".github/workflows/ci.yml", ".github", id="workflow"),
    pytest.param(".github/CODEOWNERS", ".github", id="github-codeowners"),
    pytest.param(".github", ".github", id="github-dir"),
    pytest.param(".github/", ".github", id="github-dir-slash"),
    pytest.param("CODEOWNERS", "CODEOWNERS", id="codeowners"),
    pytest.param("docs/CODEOWNERS", "docs/CODEOWNERS", id="docs-codeowners"),
    pytest.param(".simplicio-loop/loop.toml", ".simplicio-loop", id="loop-toml"),
    pytest.param(".simplicio-loop/state/scratchpad.md", ".simplicio-loop", id="loop-state"),
    pytest.param(".simplicio-loop", ".simplicio-loop", id="loop-dir"),
    pytest.param("packaging/systemd/simplicio-loop-247.service", "packaging/systemd", id="unit"),
    pytest.param("packaging/systemd/simplicio-loop-247.env.example", "packaging/systemd", id="env-example"),
    pytest.param("scripts/check.py", "scripts/check.py", id="local-ci"),
    pytest.param("hooks/action_gate.py", "hooks", id="hook"),
    pytest.param("hooks/pre-commit.py", "hooks", id="pre-commit-hook"),
    pytest.param("hooks/hooks.json", "hooks", id="hooks-json"),
    pytest.param("plugin/hooks/action_gate.py", "plugin/hooks", id="plugin-hook"),
    pytest.param("simplicio_loop/_bundle/hooks/action_gate.py", "simplicio_loop/_bundle/hooks", id="bundle-hook"),
    pytest.param(".codex/hooks.json", ".codex/hooks.json", id="codex-hooks"),
    pytest.param(".codex/config.toml", ".codex/config.toml", id="codex-config"),
    pytest.param(".claude/settings.json", ".claude/settings.json", id="claude-settings"),
    pytest.param(".claude/settings.local.json", ".claude/settings.local.json", id="claude-settings-local"),
    pytest.param(".claude/hooks/pre.sh", ".claude/hooks", id="claude-hook"),
    pytest.param(".cursor/hooks.json", ".cursor/hooks.json", id="cursor-hooks"),
    pytest.param(".kiro/hooks/x.json", ".kiro/hooks", id="kiro-hook"),
    pytest.param(".githooks/pre-commit", ".githooks", id="githooks"),
    pytest.param(".husky/pre-commit", ".husky", id="husky"),
    pytest.param(".pre-commit-config.yaml", ".pre-commit-config.yaml", id="pre-commit-config"),
    pytest.param(".vscode/tasks.json", ".vscode/tasks.json", id="vscode-tasks"),
    pytest.param("simplicio_loop/watcher247/verify.py", "simplicio_loop/watcher247/verify.py", id="verify"),
    pytest.param("simplicio_loop/plan_paths.py", "simplicio_loop/plan_paths.py", id="this-gate"),
    pytest.param("simplicio_loop/intake_gate.py", "simplicio_loop/intake_gate.py", id="intake-gate"),
    pytest.param("simplicio_loop/watcher247/sandbox.py", "simplicio_loop/watcher247/sandbox.py", id="sandbox"),
    pytest.param("simplicio_loop/watcher247/secret_scan.py", "simplicio_loop/watcher247/secret_scan.py", id="secret-scan"),
    pytest.param("simplicio_loop/watcher247/prompt_guard.py", "simplicio_loop/watcher247/prompt_guard.py", id="prompt-guard"),
    pytest.param("simplicio_loop/watcher247/env_guard.py", "simplicio_loop/watcher247/env_guard.py", id="env-guard"),
    pytest.param("simplicio_loop/watcher247/squad_flow.py", "simplicio_loop/watcher247/squad_flow.py", id="squad-flow"),
    pytest.param("simplicio_loop/watcher247/points/judge.py", "simplicio_loop/watcher247/points/judge.py", id="judge"),
    pytest.param("simplicio_loop/watcher247/points/delivery_gate.py",
                 "simplicio_loop/watcher247/points/delivery_gate.py", id="delivery-gate"),
]
# The same files spelled the way a forgiving file system reads them.
SPELLINGS = [
    pytest.param(".GitHub/workflows/ci.yml", ".github", id="case-dir"),
    pytest.param(".GITHUB/WORKFLOWS/CI.YML", ".github", id="case-all"),
    pytest.param("codeowners", "CODEOWNERS", id="case-codeowners"),
    pytest.param("Docs/CodeOwners", "docs/CODEOWNERS", id="case-docs"),
    pytest.param(".Simplicio-Loop/LOOP.TOML", ".simplicio-loop", id="case-loop"),
    pytest.param("Scripts/Check.PY", "scripts/check.py", id="case-check"),
    pytest.param(".github\\workflows\\ci.yml", ".github", id="backslash"),
    pytest.param(".simplicio-loop\\loop.toml", ".simplicio-loop", id="backslash-loop"),
    pytest.param("./.github/workflows/ci.yml", ".github", id="dot-prefix"),
    pytest.param("./././.simplicio-loop/loop.toml", ".simplicio-loop", id="dot-prefix-loop"),
    pytest.param(".github//workflows///ci.yml", ".github", id="double-slash"),
    pytest.param(".github./workflows/ci.yml", ".github", id="trailing-dot"),
    pytest.param(".github /workflows/ci.yml", ".github", id="trailing-space"),
    pytest.param(".simplicio-loop.../loop.toml", ".simplicio-loop", id="trailing-dots-loop"),
    pytest.param("scripts/check.py.", "scripts/check.py", id="trailing-dot-file"),
    pytest.param("CODEOWNERS ", "CODEOWNERS", id="trailing-space-file"),
    pytest.param(".git​hub/workflows/ci.yml", ".github", id="zero-width-space"),
    pytest.param(".github‌/workflows/ci.yml", ".github", id="zero-width-non-joiner"),
    pytest.param("﻿.simplicio-loop/loop.toml", ".simplicio-loop", id="byte-order-mark"),
    pytest.param("．github/workflows/ci.yml", ".github", id="fullwidth-dot"),
    pytest.param(".ｇｉｔｈｕｂ/workflows/ci.yml", ".github", id="fullwidth-letters"),
    pytest.param("ＣＯＤＥＯＷＮＥＲＳ", "CODEOWNERS", id="fullwidth-codeowners"),
    pytest.param(".ſimplicio-loop/loop.toml", ".simplicio-loop", id="long-s-casefold"),
]
# `refusal` turns these away first as unsafe_path; the predicate alone still sees where they land.
CLIMBING = [
    pytest.param("sub/../.github/workflows/ci.yml", ".github", id="dotdot"),
    pytest.param("sub/../scripts/ｃheck.py", "scripts/check.py", id="dotdot-fullwidth"),
]
# A directory that holds a protected path: a move or a delete of it carries the file away.
PARENTS = [
    pytest.param("packaging", "packaging/systemd", id="packaging"),
    pytest.param("plugin", "plugin/hooks", id="plugin"),
    pytest.param("simplicio_loop", "simplicio_loop/_bundle/hooks", id="package"),
    pytest.param("simplicio_loop/watcher247", "simplicio_loop/watcher247/sandbox.py", id="watcher"),  # the first entry below it
    pytest.param("simplicio_loop/watcher247/points", "simplicio_loop/watcher247/points/judge.py", id="points"),
    pytest.param("scripts", "scripts/check.py", id="scripts"),
    pytest.param("docs", "docs/CODEOWNERS", id="docs"),
    pytest.param("simplicio_loop/_bundle", "simplicio_loop/_bundle/hooks", id="bundle"),
]
ORDINARY = [
    "app.py",
    "src/a.txt",
    "src/new/deeper/file.py",
    "README.md",
    "docs/WATCHER_247.md",
    "docs/CODEOWNERS.md",
    "docs/guide/CODEOWNERS.md",
    "tests/test_plan_paths.py",
    "scripts/check_other.py",
    "scripts/checks.py",
    "scripts/sub/check.py",
    "hooks_extra/x.py",
    "hook/x.py",
    "plugin/skills/x.md",
    "plugin/hookz/x.py",
    "packaging/systemd-extra/x",
    "packaging/other.txt",
    "simplicio_loop/turbo.py",
    "simplicio_loop/plan_paths_extra.py",
    "simplicio_loop/intake_gate_x.py",
    "simplicio_loop/watcher247/tick.py",
    "simplicio_loop/watcher247/host_mode.py",
    ".claude/skills/simplicio-loop/SKILL.md",
    "AGENTS.md",
    ".claude/commands/x.md",
    ".vscode/settings.json",
    ".codex/other.json",
    "simplicio_loop/watcher247/sandbox_x.py",
    "simplicio_loop/watcher247/points/judge_x.py",
    "simplicio_loop/watcher247/points/recall.py",
    "simplicio_loop/_bundle/scripts/operator_check.py",
    ".githubx/y",
    ".githu/y",
    "github/workflows/ci.yml",
    "src/.github/workflows/ci.yml",
    ".simplicio-loop-notes.md",
    ".simplicio_loop/x",
    "CODEOWNER",
    "área/código.py",
    "a..b/c.py",
    "..git/x",
]


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    for directory in (".github/workflows", ".simplicio-loop", "docs", "src", "sub"):
        (root / directory).mkdir(parents=True)
    (root / ".github/workflows/ci.yml").write_text("on: push\n", encoding="utf-8")
    (root / ".simplicio-loop/loop.toml").write_text("enabled = true\n", encoding="utf-8")
    (root / "docs/CODEOWNERS").write_text("* @owner\n", encoding="utf-8")
    (root / "src/a.txt").write_text("a\n", encoding="utf-8")
    (root / "app.py").write_text("old\n", encoding="utf-8")
    links = {
        "ghlink": ".github",
        "cfg": ".simplicio-loop/loop.toml",
        "loopdir": ".simplicio-loop",
        "docslink": "docs",
        "hop2": "ghlink",
        "hop3": "hop2",
        "sub/up": "../.github",
        "dangling": ".github/not-yet",
        "srcln": "src",
        "appln": "app.py",
        "docsorted": "docs/sub",
    }
    for name, target in links.items():
        os.symlink(target, root / name)
    return root


def _edit(path: str) -> list[dict]:
    return [{"path": path, "find": "a", "replace": "b"}]


@pytest.mark.parametrize(("path", "entry"), [*PROTECTED, *SPELLINGS, *PARENTS])
def test_a_plan_that_writes_a_protected_path_is_refused_with_the_reason(repo, path, entry):
    reason = plan_paths.operations_refusal(_edit(path), repo)
    assert reason is not None and reason.startswith("protected_path:")
    assert repr(entry) in reason


@pytest.mark.parametrize(("path", "entry"), [*PROTECTED, *SPELLINGS, *PARENTS, *CLIMBING])
def test_the_protected_predicate_alone_names_the_same_entry(path, entry):
    reason = plan_paths.protected_refusal(path)
    assert reason is not None and reason.startswith("protected_path:") and repr(entry) in reason


@pytest.mark.parametrize("path", ORDINARY)
def test_an_ordinary_path_is_left_alone(repo, path):
    assert plan_paths.protected_refusal(path) is None
    assert plan_paths.operations_refusal(_edit(path), repo) is None


def test_the_reason_is_exact_and_deterministic(repo):
    expected = ("protected_path: '.GitHub/workflows/ci.yml' touches protected '.github': "
                "a plan never creates, edits, moves or deletes it")
    assert plan_paths.operations_refusal(_edit(".GitHub/workflows/ci.yml"), repo) == expected
    assert plan_paths.operations_refusal(_edit(".GitHub/workflows/ci.yml"), repo) == expected
    assert plan_paths.protected_refusal(".GitHub/workflows/ci.yml") == expected


@pytest.mark.parametrize("path", [".github/workflows/ci.yml", ".simplicio-loop/loop.toml", "scripts/check.py"])
def test_every_kind_of_write_is_refused(repo, path):
    create = {"path": path, "find": "", "replace": "x\n"}
    edit = {"path": path, "find": "a", "replace": "b"}
    delete = {"op": "delete_file", "path": path}
    move_away = {"op": "move_file", "path": path, "dest": "elsewhere.txt"}
    move_in = {"op": "move_file", "path": "app.py", "dest": path}
    for operation in (create, edit, delete, move_away, move_in):
        reason = plan_paths.operations_refusal([operation], repo)
        assert reason is not None and reason.startswith("protected_path:"), operation


def test_one_protected_operation_refuses_the_whole_plan(repo):
    operations = [*_edit("app.py"), {"path": ".github/workflows/x.yml", "find": "", "replace": "x"}, *_edit("src/a.txt")]
    assert plan_paths.operations_refusal(operations, repo).startswith("protected_path:")
    assert plan_paths.operations_refusal(operations[:1], repo) is None


@pytest.mark.parametrize("key", plan_paths.PLAN_KEYS)
def test_a_plan_is_read_under_every_key_the_runner_accepts(repo, key):
    assert plan_paths.plan_refusal({key: _edit(".github/workflows/ci.yml")}, repo).startswith("protected_path:")
    assert plan_paths.plan_refusal({key: [{"path": "app.py", "dest": ".simplicio-loop/loop.toml"}]}, repo).startswith("protected_path:")
    assert plan_paths.plan_refusal({key: _edit("app.py")}, repo) is None


@pytest.mark.parametrize(("path", "entry"), [
    pytest.param("ghlink/workflows/new.yml", ".github", id="dir-link"),
    pytest.param("ghlink/workflows/ci.yml", ".github", id="dir-link-existing"),
    pytest.param("ghlink", ".github", id="dir-link-itself"),
    pytest.param("cfg", ".simplicio-loop", id="file-link"),
    pytest.param("loopdir/loop.toml", ".simplicio-loop", id="loop-dir-link"),
    pytest.param("loopdir", ".simplicio-loop", id="loop-dir-link-itself"),
    pytest.param("docslink/CODEOWNERS", "docs/CODEOWNERS", id="docs-link"),
    pytest.param("hop2/workflows/x.yml", ".github", id="two-hops"),
    pytest.param("hop3/workflows/x.yml", ".github", id="three-hops"),
    pytest.param("sub/up/workflows/x.yml", ".github", id="nested-link"),
    pytest.param("dangling", ".github", id="dangling-into-protected"),
    pytest.param("./ghlink//workflows/x.yml", ".github", id="link-with-noise"),
])
def test_a_symlink_into_a_protected_path_is_refused(repo, path, entry):
    reason = plan_paths.operations_refusal(_edit(path), repo)
    assert reason is not None and reason.startswith("protected_path:") and repr(entry) in reason


@pytest.mark.parametrize("path", ["srcln/a.txt", "srcln/new.txt", "appln", "docslink/other.md", "docsorted/x.md", "sub/ok.py"])
def test_a_symlink_to_an_ordinary_place_stays_allowed(repo, path):
    assert plan_paths.operations_refusal(_edit(path), repo) is None


def test_without_a_root_only_the_text_is_followed(repo):
    assert plan_paths.protected_refusal("ghlink/workflows/x.yml") is None
    assert plan_paths.protected_refusal("ghlink/workflows/x.yml", repo).startswith("protected_path:")


def test_an_unresolvable_path_is_left_to_the_other_checks(repo):
    assert plan_paths.protected_refusal("a\0b", repo) is None
    assert plan_paths.operations_refusal(_edit("a\0b"), repo).startswith("unsafe_path")
    assert plan_paths.operations_refusal(_edit("../outside/x"), repo).startswith("unsafe_path")
    assert plan_paths.operations_refusal(_edit("/etc/passwd"), repo).startswith("unsafe_path")


def test_git_and_unsafe_reasons_come_first_and_keep_their_text(repo):
    assert "inside .git" in plan_paths.operations_refusal(_edit(".git/config"), repo)
    assert plan_paths.operations_refusal(_edit("sub/../../x"), repo).startswith("unsafe_path")


def test_a_dotdot_cannot_climb_above_the_first_component():
    assert plan_paths.protected_refusal("../.github/x") is not None
    assert plan_paths.protected_refusal("a/../../.github/x") is not None
    assert plan_paths.protected_refusal("a/b/../../src/x") is None


@pytest.mark.parametrize("path", ["", ".", "./", "/", "a/..", "sub/../.", " ", ".//", ".\\", "./."])
def test_a_path_with_no_component_is_no_protected_path(path):
    """The root holds everything, but `refusal` turns such a path away as unsafe_path; this check does not guess."""
    assert plan_paths.protected_refusal(path) is None


def test_the_config_path_the_gate_reads_is_protected():
    assert plan_paths.protected_refusal(intake_gate.CONFIG_PATH).startswith("protected_path:")


# Protected before anyone creates them: surfaces of the host (or of the repos the watcher serves) that this repo does not have.
NOT_IN_THIS_REPO = {
    "CODEOWNERS", "docs/CODEOWNERS", ".claude/settings.json", ".claude/settings.local.json", ".claude/hooks", ".cursor/hooks.json",
    ".kiro/hooks", ".githooks", ".husky", ".pre-commit-config.yaml", ".vscode/tasks.json",
}


def test_every_protected_entry_names_a_file_the_repository_has():
    """Every other entry must exist, or a rename silently drops its guard."""
    gone = [entry for entry in plan_paths.PROTECTED_PATHS if entry not in NOT_IN_THIS_REPO and not (ROOT / entry).exists()]
    assert gone == [], f"{gone} is gone or renamed: update PROTECTED_PATHS"
    assert NOT_IN_THIS_REPO <= set(plan_paths.PROTECTED_PATHS)


def test_reading_an_excerpt_of_a_protected_file_stays_allowed(repo):
    assert plan_paths.refusal(".github/workflows/ci.yml", repo) is None
    assert plan_paths.refusal(".simplicio-loop/loop.toml") is None
    assert turbo_window.parse_need([{"path": ".github/workflows/ci.yml", "start": 1, "end": 5}])


@pytest.fixture
def fake_dev_cli(tmp_path) -> tuple[str, Path]:
    """A dev-cli that writes wherever it is told would plant the file. This one only records its call."""
    calls = tmp_path / "dev-cli-calls.txt"
    script = tmp_path / "recording-dev-cli"
    script.write_text(f"#!{sys.executable}\nimport sys\nopen({str(calls)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n",
                      encoding="utf-8")
    script.chmod(0o755)
    return str(script), calls


@pytest.mark.parametrize("path", [".github/workflows/x.yml", ".simplicio-loop/loop.toml", "ghlink/workflows/x.yml", "cfg", "CODEOWNERS"])
def test_apply_plan_never_calls_dev_cli_for_a_protected_path(repo, fake_dev_cli, path):
    binary, calls = fake_dev_cli
    result = asyncio.run(turbo.apply_plan(repo, [{"path": path, "find": "", "replace": "planted\n"}], "t", binary))
    assert result["applied"] is False
    assert result["reason"].startswith("protected_path:")
    assert not calls.exists()
    assert not (repo / ".simplicio-loop" / "turbo-ops-t.json").exists()
    assert not (repo / "CODEOWNERS").exists()


def test_apply_plan_still_calls_dev_cli_for_an_ordinary_path(repo, fake_dev_cli):
    binary, calls = fake_dev_cli
    asyncio.run(turbo.apply_plan(repo, _edit("src/a.txt"), "t", binary))
    assert calls.exists() and "--compile" in calls.read_text(encoding="utf-8")


def test_a_protected_operation_after_an_ordinary_one_refuses_the_whole_plan(repo, fake_dev_cli):
    binary, calls = fake_dev_cli
    operations = [*_edit("app.py"), {"path": ".github/workflows/ci.yml", "find": "push", "replace": "pull_request_target"}]
    assert asyncio.run(turbo.apply_plan(repo, operations, "t", binary))["applied"] is False
    assert not calls.exists()
    assert (repo / ".github/workflows/ci.yml").read_text(encoding="utf-8") == "on: push\n"


def test_apply_names_the_protected_path_reason_code_and_calls_nothing(repo, tmp_path, monkeypatch):
    def no_dev_cli():
        raise AssertionError("apply reached dev-cli")

    monkeypatch.setattr(loop_apply, "_resolve_dev_cli", no_dev_cli)
    task = {"id": "T1", "operations": _edit(".simplicio-loop/loop.toml"), "depends_on": [], "check": None}
    result = loop_apply._apply_task_devcli(repo, task, tmp_path)
    assert result["ok"] is False and result["reason_code"] == "protected_path"
    assert result["steps"][0]["error"].startswith("protected_path:")
    task["operations"] = [{"path": "/etc/passwd", "find": "a", "replace": "b"}]
    assert loop_apply._apply_task_devcli(repo, task, tmp_path)["reason_code"] == "unsafe_path"


# --- a sibling with the gate's name shadows the gate (review of #1684, MAJOR-2) -------------------------------------
# python imports the package `intake_gate/` before `intake_gate.py`, and an extension or a byte-code file of the same stem
# beside it as well, so a new file with the gate's name replaces the gate without touching it.
PY_GATES = [
    "scripts/check.py",
    "simplicio_loop/plan_paths.py",
    "simplicio_loop/intake_gate.py",
    "simplicio_loop/watcher247/verify.py",
    "simplicio_loop/watcher247/sandbox.py",
    "simplicio_loop/watcher247/secret_scan.py",
    "simplicio_loop/watcher247/prompt_guard.py",
    "simplicio_loop/watcher247/env_guard.py",
    "simplicio_loop/watcher247/squad_flow.py",
    "simplicio_loop/watcher247/points/judge.py",
    "simplicio_loop/watcher247/points/delivery_gate.py",
]


def _siblings(gate: str) -> list[str]:
    folder, _, name = gate.rpartition("/")
    stem = name.removesuffix(".py")
    return [
        f"{folder}/{stem}",
        f"{folder}/{stem}/__init__.py",
        f"{folder}/{stem}/deeper/x.py",
        f"{folder}/{stem}.so",
        f"{folder}/{stem}.cpython-314-x86_64-linux-gnu.so",
        f"{folder}/{stem}.pyc",
        f"{folder}/{stem}.pyd",
        f"{folder}/__pycache__/{stem}.cpython-314.pyc",
        f"{folder.upper()}/{stem.upper()}/__init__.py",
        f"{folder}/{stem}./__init__.py",
    ]


def _lookalikes(gate: str) -> list[str]:
    folder, _, name = gate.rpartition("/")
    stem = name.removesuffix(".py")
    return [
        f"{folder}/{stem}_x.py",
        f"{folder}/x{stem}.py",
        f"{folder}/{stem}x/__init__.py",
        f"{folder}/x{stem}/__init__.py",
        f"{folder}/__pycache__/{stem}_x.cpython-314.pyc",
        f"{folder}/__pycache__/other.cpython-314.pyc",
        f"{folder}/other/{stem}.py",
        "/".join("zz" for _ in folder.split("/")) + f"/{stem}.so",
        "/".join("zz" for _ in folder.split("/")) + f"/__pycache__/{stem}.cpython-314.pyc",
    ]


def test_the_python_entries_of_the_list_are_the_ones_tested_for_shadows():
    assert sorted(entry for entry in plan_paths.PROTECTED_PATHS if entry.endswith(".py")) == sorted(PY_GATES)


@pytest.mark.parametrize("gate", PY_GATES)
def test_a_file_that_shadows_a_gate_is_refused_like_the_gate(repo, gate):
    for path in _siblings(gate):
        reason = plan_paths.operations_refusal([{"path": path, "find": "", "replace": "x\n"}], repo)
        assert reason is not None and reason.startswith("protected_path:") and repr(gate) in reason, path
        assert plan_paths.protected_refusal(path) == reason, path


@pytest.mark.parametrize("gate", PY_GATES)
def test_a_name_that_only_looks_like_the_gate_is_left_alone(repo, gate):
    for path in _lookalikes(gate):
        assert plan_paths.protected_refusal(path) is None, path


@pytest.mark.parametrize("path", ["simplicio_loop/intake_gate/__init__.py", "simplicio_loop/watcher247/sandbox/__init__.py"])
def test_apply_plan_does_not_write_a_package_that_shadows_a_gate(repo, fake_dev_cli, path):
    binary, calls = fake_dev_cli
    result = asyncio.run(turbo.apply_plan(repo, [{"path": path, "find": "", "replace": "def repo_enabled(cfg):\n    return True\n"}],
                                          "t", binary))
    assert result["applied"] is False and result["reason"].startswith("protected_path:")
    assert not calls.exists()


# --- a path with no component is the root, and the root holds everything (review of #1684, m2) ----------------------
@pytest.mark.parametrize("path", ["./", ".//", ".\\", "./.", "a/..", "sub/../.", ".///"])
def test_the_root_spelled_with_dots_is_refused_as_text(repo, path):
    assert plan_paths.refusal(path).startswith("unsafe_path")
    assert plan_paths.refusal(path, repo).startswith("unsafe_path")
    assert plan_paths.operations_refusal([{"op": "delete_file", "path": path}], repo).startswith("unsafe_path")
    assert plan_paths.operations_refusal([{"op": "move_file", "path": "app.py", "dest": path}], repo).startswith("unsafe_path")


# --- dest is followed through symlinks too (review of #1684, m3) ---------------------------------------------------
@pytest.mark.parametrize("dest", ["ghlink/workflows/x.yml", "cfg", "hop3/workflows/x.yml", "docslink/CODEOWNERS", "loopdir/loop.toml"])
def test_a_move_whose_dest_lands_in_a_protected_path_through_a_symlink_is_refused(repo, dest):
    move = [{"op": "move_file", "path": "app.py", "dest": dest}]
    reason = plan_paths.operations_refusal(move, repo)
    assert reason is not None and reason.startswith("protected_path:")
    assert plan_paths.plan_refusal({"operations": move}, repo) == reason


@pytest.mark.parametrize("source", ["ghlink/workflows/ci.yml", "cfg", "loopdir/loop.toml"])
def test_a_move_whose_source_lands_in_a_protected_path_through_a_symlink_is_refused(repo, source):
    move = [{"op": "move_file", "path": source, "dest": "elsewhere.txt"}]
    assert plan_paths.operations_refusal(move, repo).startswith("protected_path:")


# --- validation commands run after the apply and write anywhere (review of #1684, MAJOR-1) ---------------------------
VALIDATION = [{"cmd": ["sh", "-c", "echo PWNED >> .github/workflows/ci.yml; echo 'enabled = false' > .simplicio-loop/loop.toml"]}]
VALIDATION_REASON = "protected_path: validation commands are not allowed in a plan: dev-cli runs them after the apply, anywhere"


@pytest.mark.parametrize("schema", ["simplicio.mechanical-edit/v1", "simplicio.dev-cli.edit-plan/v1", None])
@pytest.mark.parametrize("validation", [VALIDATION, [{"cmd": ["true"]}], [{}], "rm -rf /", {"cmd": ["true"]}, [None]])
def test_a_plan_that_carries_validation_commands_is_refused(repo, schema, validation):
    plan = {"operations": [{"op": "create_file", "path": "src/n.py", "text": "ok = 1\n"}], "validation": validation}
    if schema:
        plan["schema"] = schema
    assert plan_paths.plan_refusal(plan, repo) == VALIDATION_REASON


@pytest.mark.parametrize("key", plan_paths.PLAN_KEYS)
def test_validation_is_refused_whichever_key_holds_the_operations(repo, key):
    assert plan_paths.plan_refusal({key: _edit("src/a.txt"), "validation": VALIDATION}, repo) == VALIDATION_REASON


@pytest.mark.parametrize("plan", [
    {"operations": [{"op": "create_file", "path": "src/n.py", "text": "x"}], "validation": []},
    {"operations": [{"op": "create_file", "path": "src/n.py", "text": "x"}]},
    {"operations": [{"op": "create_file", "path": "src/n.py", "text": "x"}], "validation": None},
])
def test_an_empty_or_absent_validation_stays_allowed(repo, plan):
    assert plan_paths.plan_refusal(plan, repo) is None


# --- apply refuses the whole ops.json before it writes anything (review of #1684, m1) ------------------------------
def _ops(*paths: str) -> dict:
    return {"tasks": [{"id": f"t{n}", "operations": [{"path": path, "find": "old" if path == "app.py" else "a", "replace": "new"}]}
                      for n, path in enumerate(paths, start=1)]}


def test_normalize_blocks_a_protected_path_naming_the_task(repo):
    with pytest.raises(loop_apply.ApplyValidationError, match=r"t2.*protected_path"):
        loop_apply._normalize_tasks(_ops("app.py", ".github/workflows/ci.yml", "src/a.txt"))


def test_validate_ops_blocks_a_symlink_into_a_protected_path_and_reads_nothing(repo, monkeypatch):
    def no_read(self, *args, **kwargs):
        raise AssertionError(f"validate_ops read {self}")

    monkeypatch.setattr(Path, "read_text", no_read)
    tasks = [{"id": "T1", "operations": _edit("ghlink/workflows/ci.yml"), "depends_on": [], "check": None}]
    assert loop_apply.validate_ops(repo, tasks, [["T1"]]) == [
        {"task": "T1", "path": "ghlink/workflows/ci.yml", "op_index": 0, "reason": "protected_path"}]


@pytest.mark.parametrize("protected", [".github/workflows/ci.yml", "ghlink/workflows/ci.yml", "cfg"])
def test_apply_run_writes_nothing_when_a_later_task_is_protected(repo, monkeypatch, protected):
    monkeypatch.setattr(loop_apply, "survey_provenance", lambda root, generations: {"ok": True})
    before = {name: (repo / name).read_text(encoding="utf-8") for name in ("app.py", "src/a.txt", ".github/workflows/ci.yml")}
    result = loop_apply.run(_ops("app.py", protected, "src/a.txt"), repo=repo)
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] in {"ops_invalid", "validation_failed"}
    assert {name: (repo / name).read_text(encoding="utf-8") for name in before} == before
