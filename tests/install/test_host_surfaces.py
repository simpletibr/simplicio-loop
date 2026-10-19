"""The eight wave-B hosts install their surface through `simplicio-loop install --host <id>`.

For each host the project install writes the skill copy and the host's documented surface, a second run changes
nothing, and `--uninstall` removes exactly what the install wrote. `--global` writes the skills under a temporary
HOME (and `.agents/skills` for OpenClaw, the directory OpenClaw scans), with the same idempotence and clean uninstall.
`deepseek` is a model provider: it is not an install host and the planner refuses it.

The surfaces are the ones the catalog names and the official docs confirm (see `simplicio_loop/install/planner.py`).
"""
from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from simplicio_loop.install import planner

REPO = Path(__file__).resolve().parents[2]
CATALOG = REPO / "simplicio_loop" / "_catalog" / "harnesses.json"
LOOP_SKILL = ".claude/skills/simplicio-loop/SKILL.md"

# catalog id -> the files a project install writes beyond the universal skill copy
PROJECT_SURFACE = {
    "github-copilot": [".github/copilot-instructions.md"],
    "opencode": [".opencode/skills/simplicio-loop/SKILL.md", "AGENTS.md"],
    "hermes": [],
    "continue": [".continue/rules/simplicio-loop.md"],
    "qwen-code": ["QWEN.md"],
    "gemini": ["GEMINI.md"],
    "aider": ["CONVENTIONS.md", ".aider.conf.yml"],
    "openclaw": [".agents/skills/simplicio-loop/SKILL.md"],
}
# catalog id -> the files a --global install writes under the temporary HOME
GLOBAL_SURFACE = {host: [LOOP_SKILL] for host in PROJECT_SURFACE}
GLOBAL_SURFACE["openclaw"] = [LOOP_SKILL, ".agents/skills/simplicio-loop/SKILL.md"]


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _run(args: list[str], *, home: Path, cwd: Path) -> SimpleNamespace:
    """`simplicio-loop install <args>` in this process, under a temporary HOME. In process, because the two steps that end
    `install` (the evidence tools, #1843, and the setup, #1841) are replaced by the suite's stubs (conftest.py and here);
    a subprocess would download the tools and reach the real setup. The environment and the working directory are
    restored afterwards. The setup itself is tested in tests/setup_wizard."""
    from simplicio_loop import cli, setup_cli

    saved_env, saved_cwd = dict(os.environ), os.getcwd()
    os.environ.update(HOME=str(home), USERPROFILE=str(home), SIMPLICIO_HOME=str(home),
                      SIMPLICIO_LOOP_DAEMON="0", SIMPLICIO_NO_BROWSER="1")
    out, err = io.StringIO(), io.StringIO()
    try:
        os.chdir(cwd)
        with redirect_stdout(out), redirect_stderr(err), mock.patch.object(setup_cli, "after_install", return_value=0):
            code = cli.main(["install", *args])
    finally:
        os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_env)
    return SimpleNamespace(returncode=code, stdout=out.getvalue(), stderr=err.getvalue())


@pytest.mark.parametrize("host", sorted(PROJECT_SURFACE))
def test_project_install_writes_the_surface_reruns_as_a_noop_and_uninstalls_clean(host: str,
                                                                                  tmp_path: Path) -> None:
    target, home = tmp_path / "project", tmp_path / "home"
    target.mkdir()
    home.mkdir()

    first = _run(["--host", host, "--target", str(target)], home=home, cwd=target)
    assert first.returncode == 0, first.stdout + first.stderr
    for rel in [LOOP_SKILL, *PROJECT_SURFACE[host]]:
        assert (target / rel).is_file(), rel
    before = _tree(target)

    second = _run(["--host", host, "--target", str(target), "--json"], home=home, cwd=target)
    assert second.returncode == 0, second.stdout + second.stderr
    payload = json.loads(second.stdout)
    assert payload["up_to_date"] is True
    assert payload["changes"]["created"] == [] and payload["changes"]["updated"] == []
    assert _tree(target) == before

    removed = _run(["--host", host, "--target", str(target), "--uninstall"], home=home, cwd=target)
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("host", sorted(PROJECT_SURFACE))
def test_global_install_writes_the_skills_surface_into_a_temporary_home(host: str, tmp_path: Path) -> None:
    home, cwd = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    cwd.mkdir()

    first = _run(["--global", "--host", host], home=home, cwd=cwd)
    assert first.returncode == 0, first.stdout + first.stderr
    for rel in GLOBAL_SURFACE[host]:
        assert (home / rel).is_file(), rel
    before = _tree(home)

    second = _run(["--global", "--host", host], home=home, cwd=cwd)
    assert second.returncode == 0, second.stdout + second.stderr
    assert _tree(home) == before

    removed = _run(["--global", "--host", host, "--uninstall"], home=home, cwd=cwd)
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert list(home.iterdir()) == []


def test_deepseek_is_a_model_provider_and_the_planner_refuses_it_as_a_host(tmp_path: Path) -> None:
    entries = {entry["id"]: entry for entry in json.loads(CATALOG.read_text(encoding="utf-8"))["harnesses"]}
    assert entries["deepseek"]["install"]["status"] == "provider"
    assert entries["deepseek"]["install"]["runtime"] is None
    assert "deepseek" not in planner.HOSTS
    with pytest.raises(planner.InstallError, match="model provider"):
        planner.plan_install(tmp_path, host="deepseek")


def test_catalog_id_and_alias_resolve_to_the_installer_runtime(tmp_path: Path) -> None:
    assert planner.runtime_for("hermes") == "simplicio_agent"
    assert planner.runtime_for("simplicio_agent") == "simplicio_agent"
    assert planner.runtime_for("qwen-code") == "qwen"
    assert planner.runtime_for("claude-code") == "claude"
    assert planner.runtime_for("orca-dev") == "orca"  # an opt-in host: installed by name, never by `--host all`
    with pytest.raises(planner.InstallError, match="unknown host"):
        planner.plan_install(tmp_path, host="not-a-host")
