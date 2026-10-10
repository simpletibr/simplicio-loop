"""#1656: the sandbox section of docs/WATCHER_247.md lists exactly what the item can write, and the HOME folders of every family."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import config, host_mode, sandbox

DOC = Path(__file__).resolve().parents[2] / "docs" / "WATCHER_247.md"
WRITE_HEADING = "**O que o item pode escrever (lista exata)**"
HOME_HEADING = "**`HOME` do planner por família**"


def section(start: str, stop: str) -> str:
    text = DOC.read_text(encoding="utf-8")
    return text[text.index(start):text.index(stop, text.index(start))]


def rows(block: str) -> list[list[str]]:
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in block.splitlines()
            if line.startswith("|") and not line.startswith("|--") and not line.startswith("| Caminho") and not line.startswith("| Família")]


@pytest.fixture
def real_wrap(tmp_path, monkeypatch):
    """The argv wrap builds for an item with every folder present, planner of `claude`."""
    monkeypatch.setattr(sandbox.shutil, "which", lambda binary: "/usr/bin/bwrap")
    home = tmp_path / "home"
    for name in (*host_mode.FAMILY_HOME["claude"]["rw"], ".local/share/claude"):
        (home / name).mkdir(parents=True)
    state = tmp_path / "state"
    clone, common = state / "work" / "demo.wt" / "31", state / "work" / "demo" / ".git"
    for folder in (clone, common / "worktrees" / "31", common / "objects", common / "simplicio"):
        folder.mkdir(parents=True)
    view = sandbox.HomeView(home, **host_mode.FAMILY_HOME["claude"])
    argv = sandbox.wrap(["claude"], clone=clone, state_dir=state, platform="linux", environ={}, home=view)
    return argv, {"home": home, "state": state, "clone": clone, "common": common}


def writable_tokens(argv: list[str], where: dict) -> set[str]:
    """The writable binds of the argv, named the way the doc names them."""
    names = {where["clone"]: "<WORK>/<repo>.wt/<issue>", where["common"] / "worktrees" / "31": "<git-dir>/worktrees/<issue>",
             where["common"] / "objects": "<git-dir>/objects", where["common"] / "simplicio": "<git-dir>/simplicio"}
    tokens = set()
    for i, arg in enumerate(argv):
        if arg in ("--bind", "--bind-try"):
            path = Path(argv[i + 1])
            tokens.add(names.get(path, "<HOME>/<pasta da família>" if path.is_relative_to(where["home"]) else str(path)))
    return tokens


def test_the_doc_lists_exactly_the_writable_binds_of_wrap(real_wrap):
    argv, where = real_wrap
    table = rows(section(WRITE_HEADING, "Todo o resto"))
    documented = {token for row in table if row[1].startswith("sim") for token in re.findall(r"`([^`]+)`", row[0])}
    assert documented == writable_tokens(argv, where)  # the rows that say "sim"; the tmpfs row says it never reaches the host
    assert [row[1] for row in table if not row[1].startswith("sim")] == ["tmpfs privado"]


def test_the_doc_names_every_state_file_as_read_only():
    text = section("Todo o resto", HOME_HEADING)
    state_files = [path.name for path in (config.CLAIMS, config.BUDGET, config.STOP, config.STATUS, config.FIXES, config.BASELINE, config.DISABLED)]
    for name in (*state_files, "work/", "logs/", "opencode/"):
        assert f"`{name}`" in text, name
    assert "somente leitura" in text and "não cria `STOP`" in text


def test_the_doc_lists_the_home_folders_of_every_family():
    table = {row[0].strip("`"): row[1] for row in rows(section(HOME_HEADING, "Binário fora do `HOME`"))}
    assert set(table) == set(host_mode.FAMILY_HOME)
    for family, entry in host_mode.FAMILY_HOME.items():
        for name in (*entry["rw"], *entry.get("ro", ()), *entry.get("hide", ())):
            assert f"`~/{name}`" in table[family], (family, name)
