"""Scope honesty: the runtime claims match the tree (#1815), and the tree carries no stale bytecode or release line (#1816).

A host is *wired* when `adapters/<host>/` ships code (and a `tests/host_<host>/` test). Every other
catalog entry is *listed*: a README under `adapters/` and, for most, an installer target that writes the
skills and the host's entry file. The number the public docs print is the number this tree measures.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from scripts import install_lib

REPO = Path(__file__).resolve().parents[1]
ADAPTERS = REPO / "adapters"
CATALOG = REPO / "simplicio_loop" / "_catalog" / "harnesses.json"

# Docs that must state the counts, and every public doc that must not state a blanket host count.
COUNT_DOCS = ("AGENTS.md", "llms.txt", "adapters/MATRIX.md")
PUBLIC_DOCS = COUNT_DOCS + ("README.md",) + tuple(
    sorted(f"READMEs/{p.name}" for p in (REPO / "READMEs").glob("*.md")))

WIRED_COUNT_RE = re.compile(r"\b(\d+) wired adapters?\b")
LISTED_COUNT_RE = re.compile(r"\b(\d+) listed hosts?\b")
BLANKET_COUNT_RE = re.compile(r"\b(?:\d{2}|thirty[- ]\w+)\s+(?:agent hosts|runtimes)\b", re.IGNORECASE)
RELEASE_LINE_RE = re.compile(r"Current release|\bLoop \d+\.\d+\.\d+\b")


def _entries() -> list[dict]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))["harnesses"]


def _adapter_dirs(entry: dict) -> list[Path]:
    return [ADAPTERS / name for name in [entry["id"], *entry["aliases"]] if (ADAPTERS / name).is_dir()]


def _has_code(adapter: Path) -> bool:
    return any(p.is_file() and p.name.lower() != "readme.md" and "__pycache__" not in p.parts
               for p in adapter.rglob("*"))


def _measured_wired() -> list[str]:
    return sorted(e["id"] for e in _entries() if any(_has_code(d) for d in _adapter_dirs(e)))


def _text(doc: str) -> str:
    return (REPO / doc).read_text(encoding="utf-8")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def _require_git_checkout() -> None:
    probe = _git("rev-parse", "--is-inside-work-tree")
    if probe.returncode != 0:
        pytest.skip("not a git checkout")


def test_every_wired_adapter_has_its_own_host_test() -> None:
    measured = _measured_wired()
    assert measured, "no adapter ships code"
    for entry in (e for e in _entries() if e["id"] in measured):
        for adapter in (d for d in _adapter_dirs(entry) if _has_code(d)):
            tests = list((REPO / "tests" / f"host_{adapter.name}").glob("test_*.py"))
            assert tests, f"wired adapter {adapter.name} has no tests/host_{adapter.name}/test_*.py"


def test_catalog_marks_an_entry_wired_only_when_its_adapter_ships_code() -> None:
    wired = sorted(e["id"] for e in _entries() if e["install"]["status"] == "wired")
    assert wired == _measured_wired()


def test_every_other_entry_is_listed_and_a_listed_installer_target_ships_no_adapter_code() -> None:
    measured = set(_measured_wired())
    for entry in _entries():
        if entry["id"] in measured:
            continue
        install = entry["install"]
        assert install["status"] == "listed", entry["id"]
        if install["runtime"] is not None:
            assert install["runtime"] in install_lib.RUNTIMES, entry["id"]


@pytest.mark.parametrize("doc", COUNT_DOCS)
def test_doc_states_the_measured_wired_and_listed_counts(doc: str) -> None:
    wired = len(_measured_wired())
    listed = len(_entries()) - wired
    text = _text(doc)
    assert set(WIRED_COUNT_RE.findall(text)) == {str(wired)}, f"{doc}: wired count must be {wired}"
    assert set(LISTED_COUNT_RE.findall(text)) == {str(listed)}, f"{doc}: listed count must be {listed}"


@pytest.mark.parametrize("doc", PUBLIC_DOCS)
def test_public_doc_never_counts_listed_hosts_as_working_runtimes(doc: str) -> None:
    text = _text(doc)
    assert not BLANKET_COUNT_RE.findall(text), doc
    wired = str(len(_measured_wired()))
    assert set(WIRED_COUNT_RE.findall(text)) <= {wired}, doc


def test_no_bytecode_is_tracked() -> None:
    _require_git_checkout()
    tracked = [p for p in _git("ls-files", "-z", "--", "*.pyc", "*.pyo").stdout.split("\0") if p]
    assert tracked == []


@pytest.mark.parametrize("path", [
    "packages/mapper/tests/fixtures/ctx-pack-host/__pycache__/sample.cpython-314.pyc",
    "legacy/old.pyc",
])
def test_bytecode_is_ignored(path: str) -> None:
    _require_git_checkout()
    assert _git("check-ignore", "--no-index", "-q", path).returncode == 0, path


@pytest.mark.parametrize("doc", ("AGENTS.md", "llms.txt"))
def test_instruction_files_carry_no_release_line(doc: str) -> None:
    assert not RELEASE_LINE_RE.findall(_text(doc)), f"{doc} must not state a version; pyproject.toml owns it"
