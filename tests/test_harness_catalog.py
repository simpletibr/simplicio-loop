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


# --- detect and llm: how the hybrid mode recognises a host and calls its headless CLI (3.47.0) --------------------------

LLM_STATUSES = {"verified", "documented", "host-mode"}
HARNESSES_DOC = REPO / "docs" / "HARNESSES.md"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _headless() -> list[dict]:
    return [e for e in _entries() if e["llm"]["status"] != "host-mode"]


def test_every_llm_entry_has_a_valid_status_and_its_evidence() -> None:
    for entry in _entries():
        llm = entry["llm"]
        assert llm["status"] in LLM_STATUSES, entry["id"]
        if llm["status"] == "verified":  # run locally: a date and the version that ran
            assert DATE_RE.match(llm["verified_on"]) and llm["verified_version"].strip(), entry["id"]
        if llm["status"] == "documented":  # from the host's own docs: the URL of the page
            assert llm["source"].startswith("https://"), entry["id"]
        if llm["status"] == "host-mode":  # no headless one-shot: nothing to run
            assert "argv" not in llm and llm.get("notes", "").strip(), entry["id"]


def test_every_headless_entry_names_a_command_a_parser_and_consistent_placeholders() -> None:
    from simplicio_loop import turbo_host_llm as hl

    assert _headless()
    for entry in _headless():
        llm = entry["llm"]
        assert llm["binary"] == llm["argv"][0] and all(isinstance(a, str) for a in llm["argv"]), entry["id"]
        assert llm["prompt"] in {"stdin", "arg"} and llm["system"] in {"flag", "agent", "prompt"}, entry["id"]
        assert llm["output"] in {"json", "jsonl", "text"} and llm["parse"] in hl.PARSERS, entry["id"]
        assert ("{prompt}" in llm["argv"]) == (llm["prompt"] == "arg"), entry["id"]
        assert ("{system}" in llm["argv"]) == (llm["system"] == "flag"), entry["id"]
        assert ("{model}" in llm.get("model_args", [])) or "model_args" not in llm, entry["id"]
        assert llm["network"] and llm["tools"], entry["id"]
        if llm["parse"] == "json":
            assert llm["paths"].get("text"), entry["id"]
        if llm.get("setup"):
            assert llm["setup"] in hl.SETUPS, entry["id"]


def test_detect_is_null_or_lists_env_markers_and_process_names() -> None:
    for entry in _entries():
        detect = entry["detect"]
        if detect is None:
            assert entry["llm"]["status"] == "host-mode", entry["id"]  # a host that can be called can be recognised
            continue
        assert set(detect) <= {"env", "process", "observed_on", "source"}, entry["id"]
        assert detect.get("env") or detect.get("process"), entry["id"]
        assert all(re.fullmatch(r"[A-Z][A-Z0-9_]*(=.*)?", rule) for rule in detect.get("env", [])), entry["id"]
        assert all(name == name.lower() and "/" not in name for name in detect.get("process", [])), entry["id"]


def test_the_two_hosts_measured_on_the_session_side_keep_their_observed_markers() -> None:
    by_id = {e["id"]: e for e in _entries()}
    assert "OPENCODE=1" in by_id["opencode"]["detect"]["env"] and by_id["opencode"]["detect"]["observed_on"]
    assert "CLAUDECODE=1" in by_id["claude-code"]["detect"]["env"] and by_id["claude-code"]["detect"]["observed_on"]


def test_the_measured_fixed_overhead_of_the_heavy_hosts_is_on_record() -> None:
    by_id = {e["id"]: e["llm"] for e in _entries()}
    assert by_id["hermes"]["overhead_tokens"] > 10000 and by_id["antigravity"]["overhead_tokens"] > 20000
    assert by_id["opencode"]["overhead_tokens"] < 1000


def _row(entry_id: str) -> str:
    rows = [line for line in HARNESSES_DOC.read_text(encoding="utf-8").splitlines() if line.startswith(f"| `{entry_id}` |")]
    assert len(rows) == 1, (entry_id, rows)
    return rows[0]


def test_harnesses_doc_has_one_row_per_entry_with_its_status_and_command() -> None:
    import shlex

    for entry in _entries():
        row = _row(entry["id"])
        assert f"| {entry['llm']['status']} |" in row, entry["id"]
        if entry["llm"]["status"] != "host-mode":
            assert shlex.join(entry["llm"]["argv"]) in row, entry["id"]


def test_harnesses_doc_states_the_counts_per_status() -> None:
    text = HARNESSES_DOC.read_text(encoding="utf-8")
    entries = _entries()
    counts = {status: sum(1 for e in entries if e["llm"]["status"] == status) for status in LLM_STATUSES}
    line = (f"{len(entries)} hosts: {counts['verified']} verified, {counts['documented']} documented, "
            f"{counts['host-mode']} host-mode")
    assert line in text


# What makes each auto-selected host safe to hand untrusted repository text to: an explicit tools-off (or read-only) marker.
# A host that keeps its tools is `"auto": false` and is only used when SIMPLICIO_TURBO_LLM names it.
TOOLS_OFF = {
    "claude-code": lambda llm: llm["argv"][llm["argv"].index("--tools") + 1] == "",
    "opencode": lambda llm: llm["env"]["OPENCODE_PERMISSION"] == '{"*":"deny"}' and llm["setup"] == "opencode",
    "pi": lambda llm: "--no-tools" in llm["argv"],
    "oh-my-pi": lambda llm: "--no-tools" in llm["argv"],
    "openclaw": lambda llm: llm["argv"][1:4] == ["infer", "model", "run"],
    "codex": lambda llm: llm["argv"][llm["argv"].index("--sandbox") + 1] == "read-only",
    "cursor": lambda llm: llm["argv"][llm["argv"].index("--mode") + 1] == "ask",
    "kiro": lambda llm: "--trust-tools=read,grep" in llm["argv"],
    "qwen-code": lambda llm: llm["argv"][llm["argv"].index("--exclude-tools") + 1] == "shell,write,edit",
    "droid": lambda llm: llm["argv"][1] == "exec" and "--auto" not in llm["argv"],  # exec is read-only unless --auto
}
KEEPS_TOOLS = {"antigravity", "hermes", "goose", "auggie", "continue", "grok", "github-copilot", "gemini", "kimi", "mistral-vibe"}


def test_every_auto_selected_host_has_an_explicit_tools_off_marker() -> None:
    for entry in _headless():
        llm = entry["llm"]
        if llm.get("auto") is False:
            continue
        assert entry["id"] in TOOLS_OFF, f"{entry['id']} is auto-selected without a tools-off marker: add one or set auto false"
        assert TOOLS_OFF[entry["id"]](llm), entry["id"]


def test_hosts_that_may_keep_their_tools_are_opt_in() -> None:
    off = {e["id"] for e in _headless() if e["llm"].get("auto") is False}
    assert off == KEEPS_TOOLS
    assert not off & set(TOOLS_OFF)
    for entry in _entries():
        assert entry["llm"].get("auto", True) in (True, False), entry["id"]
        if entry["llm"]["status"] == "host-mode":
            assert "auto" not in entry["llm"], entry["id"]


def test_harnesses_doc_says_which_hosts_are_auto_selected() -> None:
    for entry in _headless():
        row = _row(entry["id"])
        assert f"| {'no' if entry['llm'].get('auto') is False else 'yes'} |" in row, entry["id"]
