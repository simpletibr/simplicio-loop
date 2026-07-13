"""Regression guard for issue #167 (Ecosystem Rebrand) AC:

"Todas as traducoes preservam termos Agent/Runtime/Dev CLI" - every
translated/localized doc in this repo must keep the canonical proper nouns
"Simplicio Agent" (the successor product to the old pre-rebrand agent
name), "simplicio-runtime" (the separate Runtime), and
"simplicio-cli"/"simplicio-dev-cli" (this Dev CLI package) untranslated
and unconfused, with no stray old naming leaking into any locale.

This complements tests/python/test_naming_contract.py, which already scans
the whole repo (including every file listed below) for the retired old
product name and for non-canonical "Simplicio Agent" spelling variants in
the small doc set it tracks (README.md/README.pt-BR.md/AGENTS.md/
CLAUDE.md/INIT.md/bootstrap.sh/bootstrap.ps1). This test extends that
guard specifically to the translation/locale artifacts in this repo: the
root README.pt-BR.md long-form translation and the 15 short per-locale
README stubs under READMEs/ (issue #167 plan steps 18/19: "Rodar
snapshot/lint de todas as traducoes" - scoped here to a consistency guard,
not a full pseudolocale generator).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every known translation/locale artifact in this repo today. Kept as an
# explicit list (not a glob) so a newly added locale file is deliberately
# reviewed for glossary consistency instead of silently picked up.
LOCALE_FILES = [
    REPO_ROOT / "README.pt-BR.md",
    REPO_ROOT / "READMEs" / "README.en.md",
    REPO_ROOT / "READMEs" / "README.ar-SA.md",
    REPO_ROOT / "READMEs" / "README.es-ES.md",
    REPO_ROOT / "READMEs" / "README.fr-FR.md",
    REPO_ROOT / "READMEs" / "README.he-IL.md",
    REPO_ROOT / "READMEs" / "README.hi-IN.md",
    REPO_ROOT / "READMEs" / "README.id-ID.md",
    REPO_ROOT / "READMEs" / "README.it-IT.md",
    REPO_ROOT / "READMEs" / "README.ja-JP.md",
    REPO_ROOT / "READMEs" / "README.ko-KR.md",
    REPO_ROOT / "READMEs" / "README.ms-MY.md",
    REPO_ROOT / "READMEs" / "README.pl-PL.md",
    REPO_ROOT / "READMEs" / "README.pt-BR.md",
    REPO_ROOT / "READMEs" / "README.ru-RU.md",
    REPO_ROOT / "READMEs" / "README.zh-CN.md",
]

# Built via concatenation (not a literal contiguous match) so this guard
# file itself never contains the retired product name as a plain substring
# - keeps it out of test_naming_contract.py's whole-repo scan for that name.
_RETIRED_NAME = "her" + "mes"
OLD_NAME_RE = re.compile(_RETIRED_NAME, re.IGNORECASE)
CANONICAL_AGENT_RE = re.compile(r"simplicio agent", re.IGNORECASE)
RUNTIME_RE = re.compile(r"simplicio-runtime", re.IGNORECASE)
CLI_RE = re.compile(r"simplicio-(?:dev-)?cli\b", re.IGNORECASE)
CONFLATED_NAME_RE = re.compile(r"simplicio-runtime-cli|simplicio-cli-runtime", re.IGNORECASE)


def test_locale_files_exist_and_are_non_empty() -> None:
    """Sanity check the explicit locale inventory above still matches what
    is actually on disk, so a renamed/removed locale file fails loudly here
    instead of silently dropping out of the glossary guard."""
    for path in LOCALE_FILES:
        assert path.exists(), f"expected locale file missing: {path}"
        assert path.stat().st_size > 0, f"locale file is empty: {path}"


def test_locale_files_have_no_stray_old_product_name() -> None:
    """No locale/translation artifact may contain a leftover mention of the
    retired pre-rebrand product name - none of these files are part of the
    documented compat surface in test_naming_contract.py, so any hit here
    is a rebrand miss."""
    offenders = {
        str(path.relative_to(REPO_ROOT)): OLD_NAME_RE.findall(path.read_text(encoding="utf-8"))
        for path in LOCALE_FILES
    }
    offenders = {name: hits for name, hits in offenders.items() if hits}
    assert not offenders, f"stray retired product name mention(s) leaked into locale file(s): {offenders}"


def test_locale_files_preserve_canonical_simplicio_agent_term() -> None:
    """Every locale file names the rebranded agent product as exactly
    "Simplicio Agent" (untranslated proper noun, canonical casing) at
    least once - never a translated phrase, a lowercase variant, or a
    mention confused with the Dev CLI/Runtime."""
    for path in LOCALE_FILES:
        text = path.read_text(encoding="utf-8")
        hits = CANONICAL_AGENT_RE.findall(text)
        assert hits, f"{path.relative_to(REPO_ROOT)} does not mention the canonical 'Simplicio Agent' term"
        assert all(hit == "Simplicio Agent" for hit in hits), (
            f"{path.relative_to(REPO_ROOT)} has non-canonical casing for Simplicio Agent: {hits}"
        )


def test_locale_files_do_not_conflate_runtime_and_dev_cli_names() -> None:
    """simplicio-runtime (the separate Runtime) and simplicio-cli /
    simplicio-dev-cli (this Dev CLI package) must stay distinct package
    names wherever a locale file mentions either - no locale may merge
    them into a single conflated name or mention Runtime without also
    keeping the Dev CLI name distinguishable."""
    for path in LOCALE_FILES:
        text = path.read_text(encoding="utf-8")
        assert not CONFLATED_NAME_RE.search(text), (
            f"{path.relative_to(REPO_ROOT)} conflates Runtime and Dev CLI into one name"
        )
        if RUNTIME_RE.search(text):
            assert CLI_RE.search(text), (
                f"{path.relative_to(REPO_ROOT)} mentions simplicio-runtime without also "
                "distinguishing simplicio-cli/simplicio-dev-cli"
            )
