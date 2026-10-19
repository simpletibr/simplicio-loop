"""#415: global VS Code/Copilot install must wire the REAL user-level surfaces.

Covers the resolver (per-OS), the user-level skills copy, the user-level MCP write/merge,
and a full `install_lib.py vscode --global` run in a throwaway HOME (no real host writes,
no real pip — mirrors the safety posture of test_install_lib_integration.py).
"""
import json
import os
import subprocess
import sys
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_LIB = os.path.join(REPO, "scripts", "install_lib.py")
SKILLS = ["simplicio-tasks", "simplicio-loop", "simplicio-orient",
          "simplicio-review", "simplicio-compress", "simplicio-learn",
          "simplicio-autoresearch"]


def _safe_env(tmp_home):
    env = dict(os.environ)
    env["PATH"] = "/usr/bin:/bin"  # no pip/uv/simplicio/az shims
    env["HOME"] = str(tmp_home)
    env.pop("SIMPLICIO_HOME", None)  # install_lib prefers SIMPLICIO_HOME to HOME: the throwaway HOME must win
    return env


def _import_install_lib():
    import importlib.util
    spec = importlib.util.spec_from_file_location("install_lib_415_test", INSTALL_LIB)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load install_lib.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vscode_user_level_dirs_per_os(monkeypatch):
    mod = _import_install_lib()
    home = "/home/tester"
    cases = (
        ("win32", os.path.join(home, "AppData", "Roaming", "Code", "User")),
        ("darwin", os.path.join(home, "Library", "Application Support", "Code", "User")),
        ("linux", os.path.join(home, ".config", "Code", "User")),
    )
    for plat, expected_user in cases:
        # Replace only install_lib's platform view; mutating the process-global
        # sys.platform breaks subprocess on Windows for later tests.
        monkeypatch.setattr(mod, "sys", types.SimpleNamespace(platform=plat))
        if plat == "win32":
            monkeypatch.setenv("APPDATA", os.path.join(home, "AppData", "Roaming"))
        else:
            monkeypatch.delenv("APPDATA", raising=False)
        assert mod.vscode_user_level_dirs(home)["user_dir"] == expected_user


def test_copy_skills_override_dst(tmp_path):
    mod = _import_install_lib()
    # source skills exist in the real repo
    src_skills = os.path.join(REPO, ".claude", "skills")
    assert os.path.isdir(src_skills), "repo skills source missing"
    dst = tmp_path / "user_level_skills"
    mod.copy_skills(str(dst), skills_dst=str(dst))
    for s in SKILLS:
        assert (dst / s).is_dir(), "skill not copied to override dst: %s" % s


def test_write_vscode_user_mcp_idempotent(tmp_path):
    mod = _import_install_lib()
    user_dir = tmp_path / "Code" / "User"
    mcp = user_dir / "mcp.json"
    settings = user_dir / "settings.json"
    # first write
    mod.write_vscode_user_mcp(str(user_dir), str(settings), str(mcp))
    assert mcp.is_file()
    cfg = json.loads(mcp.read_text())
    assert cfg["servers"]["simplicio"]["command"] == "simplicio"
    # second write must merge, not clobber (idempotent)
    pre = mcp.read_text()
    mod.write_vscode_user_mcp(str(user_dir), str(settings), str(mcp))
    post = mcp.read_text()
    assert pre == post, "write_vscode_user_mcp not idempotent"


def test_vscode_global_install_wires_user_level(tmp_path):
    home = tmp_path / "home"
    target = tmp_path / "proj"  # unused for --global but required by cwd
    target.mkdir()
    r = subprocess.run(
        [sys.executable, INSTALL_LIB, "vscode", "--global",
         "--skip-operators", "--minimal"],
        capture_output=True, text=True, cwd=str(target),
        env=_safe_env(home), timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr

    mod = _import_install_lib()
    vdirs = mod.vscode_user_level_dirs(str(home))

    # generic home-level skills still land (regression guard)
    generic = os.path.join(home, ".claude", "skills")
    for s in SKILLS:
        assert os.path.isdir(os.path.join(generic, s)), "generic skill missing: %s" % s

    # #415: user-level skill surface must be wired
    for s in SKILLS:
        assert os.path.isdir(os.path.join(vdirs["skills"], s)), \
            "user-level skill missing: %s" % s

    # #415: user-level MCP server registered
    assert os.path.isfile(vdirs["mcp"]), "user-level mcp.json not written"
    cfg = json.loads(open(vdirs["mcp"], encoding="utf-8").read())
    assert "simplicio" in cfg.get("servers", {}), "simplicio MCP server not registered"
