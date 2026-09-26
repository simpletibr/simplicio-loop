"""#1327: `install_lib.py opencode --target <dir>` must honor --target for
project-local installs instead of hardcoding the real $HOME.

Before this fix, `copy_skills_opencode()` and `merge_opencode_mcp()` read the
module-level `OPCODE_SKILLS`/`OPCODE_CONFIG` constants (built from `HOME` at
import time), so a project-local `--target <repo>` install still wrote
skills and the MCP entry under `$HOME/.config/opencode/` -- never under
`<repo>/.opencode/`. This test drives a REAL `install_lib.py opencode`
subprocess (same safety posture as test_install_lib_integration.py: always
--skip-operators --minimal, always --target <tmp_path>, never the real HOME,
PATH restricted to core utils) and asserts:

1. `--target <repo>` (project-local, no `--global`) writes skills ONLY under
   `<repo>/.opencode/skills/` and `opencode.json` ONLY under `<repo>/`; the
   throwaway `$HOME` stays completely empty (no `.config/opencode/` at all).
2. `--global` writes skills and `opencode.json` ONLY under the throwaway
   `$HOME/.config/opencode/`; the project target is untouched by the
   opencode-specific skills/MCP copy (whatever the generic `.claude/skills`
   copy_skills() does is out of scope for this test).
3. A project-local install (no optional runtime-bind flag) never writes an
   MCP entry at all -- for a project-local OpenCode install, the Runtime/MCP
   bind is optional and off by default, so no `opencode.json` is written
   when there's nothing else that would create it. Requesting the runtime
   bind explicitly (`--with-runtime-mcp`) is required for the MCP entry to
   be written, project-local or global.
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_LIB = os.path.join(REPO, "scripts", "install_lib.py")
SKILLS = ["simplicio-tasks", "simplicio-loop", "simplicio-orient",
          "simplicio-review", "simplicio-compress", "simplicio-learn",
          "simplicio-autoresearch"]


def _safe_env(tmp_home):
    """A PATH with no simplicio*/az binaries + a throwaway HOME -- mirrors
    test_install_lib_integration.py's `_safe_env` so nothing here can ever
    touch the real host."""
    env = dict(os.environ)
    env["PATH"] = "/usr/bin:/bin"
    env["HOME"] = str(tmp_home)
    return env


def _install(args, target, tmp_home):
    argv = [sys.executable, INSTALL_LIB, "opencode", "--target", str(target),
            "--skip-operators", "--minimal"] + list(args)
    return subprocess.run(argv, capture_output=True, text=True, cwd=str(target),
                          env=_safe_env(tmp_home), timeout=120)


def _tree_is_empty(path):
    if not os.path.exists(path):
        return True
    for _root, _dirs, files in os.walk(path):
        if files:
            return False
    return True


def test_opencode_target_writes_only_under_target_home_stays_empty(tmp_path):
    target = tmp_path / "project_repo"
    target.mkdir()
    home = tmp_path / "throwaway_home"
    home.mkdir()

    r = _install([], target, home)
    assert r.returncode == 0, r.stdout + r.stderr

    opencode_skills = target / ".opencode" / "skills"
    for s in SKILLS:
        assert (opencode_skills / s).is_dir(), (
            "opencode skill %s not copied under --target: %s" % (s, r.stdout + r.stderr))

    # the throwaway $HOME must stay completely untouched -- no
    # ~/.config/opencode/{skills,opencode.json} at all.
    home_opencode = home / ".config" / "opencode"
    assert _tree_is_empty(home_opencode), (
        "opencode --target wrote into $HOME instead of --target: %s"
        % list(home_opencode.rglob("*")) if home_opencode.exists() else "n/a")


def test_opencode_global_writes_only_under_home(tmp_path):
    target = tmp_path / "project_repo_unused"
    target.mkdir()
    home = tmp_path / "throwaway_home_global"
    home.mkdir()

    r = _install(["--global"], target, home)
    assert r.returncode == 0, r.stdout + r.stderr

    home_skills = home / ".config" / "opencode" / "skills"
    for s in SKILLS:
        assert (home_skills / s).is_dir(), (
            "opencode --global did not copy skill %s under $HOME: %s"
            % (s, r.stdout + r.stderr))

    # project-local .opencode/skills/ must NOT be created by a --global install.
    assert not (target / ".opencode").exists(), (
        "--global install must not write project-local .opencode/")


def test_opencode_target_without_runtime_bind_writes_no_mcp_entry(tmp_path):
    target = tmp_path / "project_repo_no_mcp"
    target.mkdir()
    home = tmp_path / "throwaway_home_no_mcp"
    home.mkdir()

    r = _install([], target, home)
    assert r.returncode == 0, r.stdout + r.stderr

    opencode_json = target / "opencode.json"
    assert not opencode_json.exists(), (
        "project-local opencode install must not write an MCP entry unless the "
        "optional runtime bind is explicitly requested: %s" % (r.stdout + r.stderr))


def test_opencode_target_with_runtime_bind_flag_writes_mcp_entry_under_target(tmp_path):
    target = tmp_path / "project_repo_with_mcp"
    target.mkdir()
    home = tmp_path / "throwaway_home_with_mcp"
    home.mkdir()

    r = _install(["--with-runtime-mcp"], target, home)
    assert r.returncode == 0, r.stdout + r.stderr

    opencode_json = target / "opencode.json"
    assert opencode_json.is_file(), (
        "--with-runtime-mcp must write the project-local opencode.json MCP entry: %s"
        % (r.stdout + r.stderr))
    data = json.loads(opencode_json.read_text())
    assert "mcp" in data, "opencode.json missing mcp block: %s" % data

    # the throwaway $HOME still must not get an opencode.json out of this run.
    home_opencode_json = home / ".config" / "opencode" / "opencode.json"
    assert not home_opencode_json.exists(), (
        "--with-runtime-mcp on a project-local (non --global) install must not "
        "touch $HOME's opencode.json")
