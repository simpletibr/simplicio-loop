"""Scope honesty: the runtime claims match the tree (#1815), and the tree carries no stale bytecode or release line (#1816).

A host is *wired* when `adapters/<host>/` ships code (and a `tests/host_<host>/` test). Every other
catalog entry is *listed*: a README under `adapters/` and, for most, an installer target that writes the
skills and the host's entry file. The number the public docs print is the number this tree measures.

#1821 extends that to every doc a user reads first (README, the 14 translations, PYPI.md, INSTALL.md,
docs/GUIDE.md, the project manifest, the installer docstring): each one that states a host count states
the measured wired/listed pair, and no stale blanket count survives.
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


def _hosts() -> list[dict]:
    """The catalog entries that are install hosts. A model provider (DeepSeek) is an entry, not a host."""
    return [e for e in _entries() if e["install"]["status"] != "provider"]


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
        if install["status"] == "provider":
            # DeepSeek is the only model provider: no installer target and no adapter code, and not a host.
            assert entry["id"] == "deepseek" and install["runtime"] is None, entry["id"]
            continue
        assert install["status"] == "listed", entry["id"]
        if install["runtime"] is not None:
            assert install["runtime"] in install_lib.RUNTIMES, entry["id"]


@pytest.mark.parametrize("doc", COUNT_DOCS)
def test_doc_states_the_measured_wired_and_listed_counts(doc: str) -> None:
    wired = len(_measured_wired())
    listed = len(_hosts()) - wired
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


# --- #1821: every owned doc prints the measured wired/listed pair, in every language -------------
TRANSLATIONS = tuple(sorted(f"READMEs/{p.name}" for p in (REPO / "READMEs").glob("*.md")))
# Docs that state the pair. The status words stay literal (`wired` / `listed`, the catalog values) in
# every language, so one language-neutral pattern reads all of them: "6 wired adapters", "29 listed
# hosts", "6 adaptadores `wired`", "29 hosts `listed`".
PAIR_DOCS = ("README.md", "PYPI.md", "INSTALL.md", "docs/GUIDE.md", "simplicio-loop.project.json") + TRANSLATIONS
# Docs that may state it (the installer docstring) and the instruction file that already does.
OWNED_DOCS = PAIR_DOCS + ("llms.txt", "scripts/install_lib.py")
STATUS_COUNT_RE = re.compile(r"(\d+)\s+(?:[^\s\d`]+\s+){0,3}`?(wired|listed)`?(?![\w-])", re.IGNORECASE)
STALE_PHRASES = ("35 runtimes", "35 hosts", "35-runtimes", "11 runtimes", "48 ext", "32 host", "3 guaranteed",
                 "32 best-effort", "32 best--effort", "35%20(3")
UNQUALIFIED_COUNT_RE = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"(?:twenty|thirty|forty|fifty)(?:[- ]\w+)?)[ -](?:distinct |agent )?(?:runtimes|hosts|host surfaces)\b"
    r"(?!\s+`?(?:wired|listed)\b)",  # "29 hosts `listed`": the qualifier may follow the noun
    re.IGNORECASE)


def _status_counts(text: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {"wired": set(), "listed": set()}
    for number, status in STATUS_COUNT_RE.findall(text):
        found[status.lower()].add(number)
    return found


def _measured_counts() -> tuple[str, str]:
    wired = len(_measured_wired())
    return str(wired), str(len(_hosts()) - wired)


@pytest.mark.parametrize("doc", OWNED_DOCS)
def test_owned_doc_carries_no_stale_or_unqualified_host_count(doc: str) -> None:
    text = _text(doc)
    lowered = text.lower()
    assert not [p for p in STALE_PHRASES if p in lowered], f"{doc}: stale count phrase"
    assert not UNQUALIFIED_COUNT_RE.findall(text), f"{doc}: say '<n> wired adapters' / '<n> listed hosts', not a blanket count"


@pytest.mark.parametrize("doc", PAIR_DOCS)
def test_owned_doc_prints_the_measured_wired_and_listed_pair(doc: str) -> None:
    wired, listed = _measured_counts()
    counts = _status_counts(_text(doc))
    assert counts["wired"] == {wired}, f"{doc}: wired count must be exactly {wired}, found {sorted(counts['wired'])}"
    assert counts["listed"] == {listed}, f"{doc}: listed count must be exactly {listed}, found {sorted(counts['listed'])}"


@pytest.mark.parametrize("doc", ("llms.txt", "scripts/install_lib.py"))
def test_doc_that_may_state_the_pair_never_states_a_wrong_one(doc: str) -> None:
    wired, listed = _measured_counts()
    counts = _status_counts(_text(doc))
    assert counts["wired"] <= {wired} and counts["listed"] <= {listed}, doc


def test_install_docs_do_not_call_every_installer_target_a_wired_host() -> None:
    # The installer targets include the listed hosts; only 6 of them are wired.
    for doc in ("INSTALL.md", "scripts/install_lib.py"):
        assert not re.search(r"install\.runtime`?\s+of\s+a\s+`?wired`?\s+host", _text(doc)), doc


def test_guide_wired_bullet_names_only_wired_hosts() -> None:
    guide = _text("docs/GUIDE.md")
    bullets = re.findall(r"^- \*\*Wired[^\n]*(?:\n(?!- |\n|#)[^\n]*)*", guide, flags=re.MULTILINE)
    assert bullets, "docs/GUIDE.md must have a '- **Wired ...' bullet in the runtimes section"
    wired_ids = set(_measured_wired())
    listed_names = [e["name"] for e in _hosts() if e["id"] not in wired_ids]
    for bullet in bullets:
        leaked = [n for n in listed_names if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", bullet)]
        assert not leaked, f"docs/GUIDE.md calls listed host(s) wired: {leaked}"


def test_pypi_runtime_line_does_not_present_listed_hosts_as_working() -> None:
    pypi = _text("PYPI.md")
    wired_ids = set(_measured_wired())
    listed_names = [e["name"] for e in _hosts() if e["id"] not in wired_ids and len(e["name"]) > 4]
    line = next((ln for ln in pypi.splitlines() if "wired" in ln.lower()), "")
    assert line, "PYPI.md must say which hosts are wired"
    unlabeled = [ln for ln in pypi.splitlines()
                 if "listed" not in ln.lower() and "wired" not in ln.lower()
                 and sum(1 for n in listed_names if n in ln) >= 3]
    assert not unlabeled, f"PYPI.md name-drops listed hosts as if they ran the loop: {unlabeled}"

