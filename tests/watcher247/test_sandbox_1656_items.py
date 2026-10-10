"""Parte de #1656 (itens 3 a 6) e #1570 (passo 2): auditoria do que ainda esta aberto.

- Item 4 (satisfeito pelo codigo em proc.run): os dois testes abaixo passam porque o codigo esta certo. Cada um tem um mutante
  temporario que precisa fazê-lo falhar.
- Item 3, item 5 e #1570 passo 2 (NAO satisfeitos): xfail(strict=True) com o teste exato que um humano precisa fazer passar.
- Item 6 (teste flaky): sem teste novo; os limites fixos estao em tests/watcher247/test_sandbox_proc.py (timeout=60 e =120).
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import proc, sandbox, worktrees

from .sandbox_rig import bwrap_skip_reason, scratch

real_bwrap = pytest.mark.skipif(bool(bwrap_skip_reason()), reason=bwrap_skip_reason() or "bwrap")


def _fake_git(root: Path) -> Path:
    """A `git` that prints its environment, so the test sees what proc.run hands a git child."""
    bin_dir = root / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "git"
    fake.write_text("#!/bin/sh\nenv\n")
    fake.chmod(0o755)
    return bin_dir


def _env_lines(output: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def test_git_env_goes_to_git_in_an_item_worktree_and_never_to_another_program(tmp_path):
    """Q06 (#1656 item 4): GIT_DIR / GIT_COMMON_DIR / GIT_WORK_TREE only for `git`, not for any program run in the worktree."""
    item = tmp_path / "work" / "demo.wt" / "31"
    item.mkdir(parents=True)
    bin_dir = _fake_git(tmp_path)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}

    as_git = _env_lines(asyncio.run(proc.run(["git", "status"], cwd=item, env=env)).stdout)
    as_other = _env_lines(asyncio.run(proc.run(["env"], cwd=item, env=env)).stdout)

    assert as_git["GIT_DIR"] == str(tmp_path / "work" / "demo" / ".git" / "worktrees" / "31")  # the control: git gets it
    assert not [name for name in as_other if name.startswith("GIT_")], as_other


def test_git_env_is_added_to_the_service_env_and_never_replaces_it(tmp_path):
    """Q08 (#1656 item 4): injecting GIT_* keeps PATH, HOME and the other service variables, so `git push` still has its token."""
    item = tmp_path / "work" / "demo.wt" / "31"
    item.mkdir(parents=True)
    bin_dir = _fake_git(tmp_path)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": "/service/home", "GH_TOKEN": "token-for-the-test"}

    seen = _env_lines(asyncio.run(proc.run(["git", "push"], cwd=item, env=env)).stdout)

    assert seen["HOME"] == "/service/home" and seen["GH_TOKEN"] == "token-for-the-test" and seen["PATH"] == env["PATH"]
    assert seen["GIT_WORK_TREE"] == str(item)


@pytest.mark.xfail(strict=True, reason=(
    "#1656 item 3 NAO satisfeito: sandbox.worktree_binds liga objects/ como leitura e escrita para todo item, entao um item "
    "apaga um .idx de pack e a base e os outros itens do repo ficam quebrados (git cat-file: rc 128). Ajuste humano: objetos "
    "por item com alternates somente leitura para a base, ou detectar base corrompida e reclonar."))
@real_bwrap
def test_an_item_cannot_delete_a_pack_index_of_the_shared_objects(tmp_path):
    with scratch("sbx-1656-i3-") as root:
        state = root / "state"
        clone = root / "work" / "demo.wt" / "31"
        pack = root / "work" / "demo" / ".git" / "objects" / "pack"
        for folder in (state, clone, pack):
            folder.mkdir(parents=True)
        index = pack / "pack-1656.idx"
        index.write_bytes(b"\x00")
        argv = sandbox.wrap(["sh", "-c", 'rm -f "$1"', "sh", str(index)], clone=clone, state_dir=state, platform="linux", environ={})
        done = subprocess.run(argv, env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=60)
        assert done.returncode != 0 and index.exists(), done.stderr


@pytest.mark.xfail(strict=True, reason=(
    "#1656 item 5 NAO satisfeito: worktrees._repo_dir testa o sufixo .wt/.state sem distinguir caixa, entao 'foo.WT', 'x.Wt' e "
    "'foo.State' sao aceitos como nome de repo. Ajuste humano: comparar repo.lower()."))
@pytest.mark.parametrize("name", ["foo.WT", "x.Wt", "foo.State"])
def test_a_repo_name_with_the_wt_or_state_suffix_in_any_case_is_refused(name):
    with pytest.raises(ValueError):
        worktrees._repo_dir(name)


@pytest.mark.xfail(strict=True, reason=(
    "#1570 passo 2 NAO satisfeito: turbo (host_mode.py:213 e :229) e tick.py:145 chamam sandbox.wrap sem home=, entao o HOME "
    "inteiro segue legivel (somente leitura). Ajuste humano: passar um HomeView por familia, depois de medir o que turbo, "
    "verify e test_cmd leem de HOME (squad_flow.py:251 tambem chama wrap sem home=, fora do escopo desta PR)."))
@real_bwrap
def test_a_turbo_run_cannot_read_a_login_file_in_home(tmp_path):
    with scratch("sbx-1570-") as root:
        state = root / "state"
        clone = root / "work" / "demo.wt" / "31"
        home = root / "home"
        for folder in (state, clone, home / ".simplicio"):
            folder.mkdir(parents=True)
        (home / ".simplicio" / "login.json").write_text("FAKE-LOGIN")
        argv = sandbox.wrap(["sh", "-c", 'cat "$HOME/.simplicio/login.json"'], clone=clone, state_dir=state, platform="linux",
                            environ={})
        done = subprocess.run(argv, env={"PATH": "/usr/bin:/bin", "HOME": str(home)}, capture_output=True, text=True, timeout=60)
        assert done.returncode != 0 and "FAKE-LOGIN" not in done.stdout, done.stdout
