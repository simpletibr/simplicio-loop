"""Harness catalog: one entry per agent host, and an install path for every host that has one.

`simplicio_loop/_catalog/harnesses.json` is the single list of hosts. These tests pin it to the
upstream registry, tie it to the installer, the adapter directories and the matrix document, and
install every `wired` runtime into a throwaway target.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import install_lib, install_plan

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "simplicio_loop" / "_catalog" / "harnesses.json"
ADAPTERS = REPO / "adapters"
MATRIX = ADAPTERS / "MATRIX.md"

# Host ids declared by simpletibr/simplicio `plugins/simplicio/host-surfaces.json` at the commit
# recorded in the catalog's `upstream.sha`.
UPSTREAM_IDS = (
    "claude-code", "codex", "grok", "cursor", "github-copilot", "opencode", "mimo-code", "amp",
    "openclaude", "antigravity", "pi", "oh-my-pi", "hermes", "devin", "goose", "auggie",
    "autohand", "charm", "cline", "codebuff", "command-code", "continue", "droid", "kilocode",
    "kimi", "kiro", "mistral-vibe", "qwen-code", "rovo-dev", "gemini", "vscode", "orca-dev",
)
# Adapters that exist only in simplicio-loop.
LOOP_ONLY_IDS = ("aider", "deepseek", "openclaw")

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
ENTRY_KEYS = {"id", "name", "aliases", "install", "detect", "llm"}
INSTALL_KEYS = {"status", "runtime", "surface", "source"}


def _catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _entries() -> list[dict]:
    return _catalog()["harnesses"]


def _names(entry: dict) -> list[str]:
    return [entry["id"], *entry["aliases"]]


def _adapter_dirs(entry: dict) -> list[Path]:
    return [ADAPTERS / name for name in _names(entry) if (ADAPTERS / name).is_dir()]


def _readmes(entry: dict) -> list[str]:
    return [(d / "README.md").read_text(encoding="utf-8") for d in _adapter_dirs(entry)
            if (d / "README.md").is_file()]


WIRED = [(e["id"], e["install"]["runtime"]) for e in _entries() if e["install"]["status"] == "wired"]


def test_catalog_pins_the_upstream_registry() -> None:
    data = _catalog()
    assert data["schema"] == "simplicio.harnesses/v1"
    assert data["upstream"]["repo"] == "simpletibr/simplicio"
    assert data["upstream"]["path"] == "plugins/simplicio/host-surfaces.json"
    assert re.fullmatch(r"[0-9a-f]{40}", data["upstream"]["sha"])


def test_every_upstream_id_is_listed_exactly_once() -> None:
    ids = [e["id"] for e in _entries()]
    for host in UPSTREAM_IDS:
        assert ids.count(host) == 1, host
    assert len(ids) == len(set(ids))
    assert sorted(set(ids) - set(UPSTREAM_IDS)) == sorted(LOOP_ONLY_IDS)


def test_every_entry_is_valid() -> None:
    for entry in _entries():
        assert ENTRY_KEYS <= set(entry), entry["id"]
        assert NAME_RE.match(entry["id"]), entry["id"]
        assert entry["name"].strip(), entry["id"]
        assert isinstance(entry["aliases"], list)
        assert all(NAME_RE.match(alias) for alias in entry["aliases"]), entry["id"]
        install = entry["install"]
        assert INSTALL_KEYS <= set(install), entry["id"]
        assert install["status"] in {"wired", "manual"}, entry["id"]
        if install["status"] == "wired":
            assert isinstance(install["runtime"], str) and install["runtime"], entry["id"]
        else:
            assert install["runtime"] is None, entry["id"]
        assert install["surface"].strip(), entry["id"]
        assert install["source"].startswith("https://"), entry["id"]
        assert isinstance(entry["llm"], dict) and "status" in entry["llm"], entry["id"]


def test_ids_and_aliases_never_collide() -> None:
    names = [name for entry in _entries() for name in _names(entry)]
    assert len(names) == len(set(names))


def test_every_adapter_directory_maps_to_one_catalog_entry() -> None:
    for adapter in sorted(p.name for p in ADAPTERS.iterdir() if p.is_dir() and p.name != "__pycache__"):
        owners = [e["id"] for e in _entries() if adapter in _names(e)]
        assert len(owners) == 1, (adapter, owners)


def test_every_entry_has_an_adapter_readme_that_covers_the_loop() -> None:
    for entry in _entries():
        readmes = _readmes(entry)
        assert readmes, entry["id"]
        assert any('simplicio-loop "<task>"' in text and "loop drive" in text.lower()
                   for text in readmes), entry["id"]


def test_manual_entries_list_exact_steps_in_their_readme() -> None:
    manual = [e for e in _entries() if e["install"]["status"] == "manual"]
    assert manual
    for entry in manual:
        assert any("```" in text for text in _readmes(entry)), entry["id"]


def test_wired_runtime_is_an_installer_target_named_like_its_adapter() -> None:
    for entry in _entries():
        runtime = entry["install"]["runtime"]
        if runtime is None:
            continue
        assert runtime in _names(entry), entry["id"]
        assert runtime in install_lib.RUNTIMES, entry["id"]
        assert (ADAPTERS / runtime).is_dir(), entry["id"]


def test_every_installer_runtime_belongs_to_one_catalog_entry() -> None:
    for runtime in install_lib.RUNTIMES:
        owners = [e["id"] for e in _entries() if runtime in _names(e)]
        assert len(owners) == 1, (runtime, owners)


def test_surface_names_the_files_the_installer_writes() -> None:
    for entry in _entries():
        runtime = entry["install"]["runtime"]
        if runtime is None:
            continue
        surface = entry["install"]["surface"]
        assert ".claude/skills/" in surface, entry["id"]
        entry_file = install_lib.RUNTIMES[runtime]["entry"]
        if entry_file:
            assert entry_file in surface, entry["id"]


def test_dry_run_plan_knows_every_entry_file() -> None:
    expected = {rt: cfg["entry"] for rt, cfg in install_lib.RUNTIMES.items() if cfg["entry"]}
    assert install_plan.ENTRY_FILES == expected


def test_wheel_installer_never_advertises_a_host_the_catalog_does_not_wire() -> None:
    from simplicio_loop.install import planner

    assert set(planner.HOSTS) <= {runtime for _, runtime in WIRED}


def test_both_launchers_delegate_every_runtime_to_the_python_installer() -> None:
    runtimes = {runtime for _, runtime in WIRED}
    for launcher in ("install.sh", "install.ps1"):
        text = (REPO / "scripts" / launcher).read_text(encoding="utf-8")
        assert "install_lib.py" in text, launcher
        assert not [r for r in runtimes if re.search(rf"(?<![\w-]){re.escape(r)}(?![\w-])", text)], launcher


def test_matrix_has_one_row_per_catalog_entry() -> None:
    rows = [line for line in MATRIX.read_text(encoding="utf-8").splitlines() if line.startswith("|")]
    for entry in _entries():
        links = [f"]({d.name}/README.md)" for d in _adapter_dirs(entry)]
        matching = [row for row in rows if any(link in row for link in links)]
        assert len(matching) == 1, (entry["id"], matching)
        status = entry["install"]["status"]
        assert re.search(rf"\b{status}\b", matching[0]), (entry["id"], status)


def _tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _install(runtime: str, target: Path, home: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), SIMPLICIO_HOME=str(home),
               SIMPLICIO_NO_BROWSER="1")
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "install_lib.py"), runtime, "--target", str(target),
         "--skip-operators", "--minimal"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(target),
        stdin=subprocess.DEVNULL, timeout=120, check=False)


@pytest.mark.parametrize("runtime", [runtime for _, runtime in WIRED])
def test_wired_runtime_installs_into_a_throwaway_target_and_is_idempotent(
        runtime: str, tmp_path: Path) -> None:
    target, home = tmp_path / "project", tmp_path / "home"
    target.mkdir()
    home.mkdir()

    first = _install(runtime, target, home)
    assert first.returncode == 0, first.stdout + first.stderr
    for skill in install_lib.SKILLS:
        assert (target / ".claude" / "skills" / skill / "SKILL.md").is_file(), skill
    entry_file = install_lib.RUNTIMES[runtime]["entry"]
    if entry_file:
        body = (target / entry_file).read_text(encoding="utf-8")
        assert body.count(install_lib.MARK_A) == 1 and body.count(install_lib.MARK_B) == 1
    before = _tree(target)

    second = _install(runtime, target, home)
    assert second.returncode == 0, second.stdout + second.stderr
    assert _tree(target) == before
    assert not [p for p in home.rglob("*") if p.is_file() and ".local" not in p.parts]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh is not installed")
def test_powershell_launcher_installs_a_new_runtime(tmp_path: Path) -> None:
    target, home = tmp_path / "project", tmp_path / "home"
    target.mkdir()
    home.mkdir()
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), SIMPLICIO_HOME=str(home),
               SIMPLICIO_NO_BROWSER="1")
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(REPO / "scripts" / "install.ps1"), "continue",
         "-Target", str(target), "-SkipOperators", "--minimal"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
        stdin=subprocess.DEVNULL, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / ".continue" / "rules" / "simplicio-loop.md").is_file()
    assert (target / ".claude" / "skills" / "simplicio-loop" / "SKILL.md").is_file()
