"""README positioning (#1821): the pitch leads with the deterministic operators, and every number is backed.

Loop orchestration is a commodity; the differentiated parts are `simplicio-mapper` (survey),
`simplicio-dev-cli` (deterministic apply) and impact-based test selection (`scripts/impact_tests.py`,
which `scripts/check.py` uses). The README and its 14 translations present them as tools any harness
can call, with the loop as one consumer. A percentage may stay only when the claims manifest backs it
with a verified receipt, and the manifest must not vouch for text the docs no longer carry.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import claims_manifest  # noqa: E402

README = "README.md"
TRANSLATIONS = tuple(sorted(f"READMEs/{p.name}" for p in (REPO / "READMEs").glob("*.md")))
ALL_READMES = (README,) + TRANSLATIONS

# The three calls every README shows verbatim (the commands are language-neutral).
OPERATOR_CALLS = (
    'simplicio-mapper handoff . --goal "trace the authentication flow" --token-budget 1200 --json',
    "simplicio-dev-cli edit --root . --plan plan.json --apply --check \"<tests>\" --json",
    "python3 scripts/impact_tests.py --base origin/main --json",
)
SAVINGS_CLAIM_RE = re.compile(
    r"\d[\d.,]*\s*(?:%|x|×|k|M)?\s*(?:fewer|less|faster|cheaper|saved|savings|tokens)\b", re.IGNORECASE)
LINK_RE = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _tagline(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("**") and line.rstrip().endswith("**"):
            return line
    return ""


def _h2_sections(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def _slug(heading: str) -> str:
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    return {_slug(m.group(1)) for m in re.finditer(r"^#{1,6} (.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)}


@pytest.mark.parametrize("doc", ALL_READMES)
def test_readme_tagline_leads_with_the_three_operators(doc: str) -> None:
    tagline = _tagline(_text(doc))
    assert tagline, f"{doc}: no bold tagline"
    for needle in ("simplicio-mapper", "simplicio-dev-cli", "impact_tests"):
        assert needle in tagline, f"{doc}: tagline must name {needle}"


def test_readme_no_longer_defines_the_product_as_the_issue_to_pr_loop() -> None:
    tagline = _tagline(_text(README))
    assert not tagline.lower().startswith("**simplicio-loop turns github issues"), tagline


@pytest.mark.parametrize("doc", ALL_READMES)
def test_first_section_is_the_operators_with_a_runnable_call_each(doc: str) -> None:
    sections = _h2_sections(_text(doc))
    assert sections, doc
    heading, body = sections[0]
    for call in OPERATOR_CALLS:
        assert call in body, f"{doc}: first section ({heading!r}) must show `{call}`"


def test_loop_section_comes_after_the_operators_and_before_install() -> None:
    headings = [h for h, _ in _h2_sections(_text(README))]
    assert headings[0] == "The operators", headings
    assert headings[1].startswith("The loop"), headings
    assert headings.index("Install") > 1, headings
    for kept in ("Install", "Use it", "How it works"):
        assert kept in headings, f"{kept} section lost: {headings}"


def test_readme_keeps_the_use_it_commands_that_exist() -> None:
    text = _text(README)
    for needle in ("pip install simplicio-loop", "simplicio-loop install", "simplicio-loop doctor",
                   "/simplicio-loop finish all the open issues", "simplicio-loop watch247 --once --dry-run",
                   "simplicio-loop dashboard --status", "simplicio-loop dashboard --stop",
                   "docs/WATCHER_247.md", "docs/DASHBOARD.md"):
        assert needle in text, needle


def test_readme_says_where_impact_selection_lives_and_who_uses_it() -> None:
    text = _text(README)
    assert "scripts/check.py" in text
    assert "scripts/impact_tests.py" in text
    # Not in the wheel: the README must say it is a checkout script.
    assert re.search(r"checkout", text, re.IGNORECASE)


@pytest.mark.parametrize("doc", ALL_READMES)
def test_readme_carries_no_percentage_the_manifest_does_not_verify(doc: str) -> None:
    verified = [c["text_glob"].lower().replace(" ", "") for c in claims_manifest.CLAIMS
                if c["doc"] == doc and c["status"] == "verified" and c["receipt"]]
    bad = []
    for m in claims_manifest.STRICT_QUANT_RE.finditer(claims_manifest._claim_text(doc, _text(doc))):
        if not any(m.group(0).lower().replace(" ", "") in v for v in verified):
            bad.append(m.group(0))
    assert bad == [], f"{doc}: unbacked number(s) {bad}"


@pytest.mark.parametrize("doc", ALL_READMES)
def test_readme_makes_no_numeric_savings_claim(doc: str) -> None:
    text = _text(doc)
    stripped = re.sub(r"https?://\S+", " ", text)
    assert SAVINGS_CLAIM_RE.findall(stripped) == [], doc
    for stale in ("96%", "90.3", "93%", "fewer tokens", "96.7"):
        assert stale not in text, f"{doc}: {stale}"


def test_the_pitch_points_at_the_raw_benchmark_results_instead_of_quoting_them() -> None:
    text = _text(README)
    assert "bench/llm_ab" in text
    assert (REPO / "bench" / "llm_ab" / "results").is_dir()
    assert (REPO / "packages" / "mapper" / "README.md").is_file()
    assert (REPO / "packages" / "dev-cli" / "README.md").is_file()
    assert "packages/mapper/README.md" in text and "packages/dev-cli/README.md" in text


@pytest.mark.parametrize("doc", ALL_READMES)
def test_every_relative_link_and_anchor_resolves(doc: str) -> None:
    base = (REPO / doc).parent
    broken = []
    for target in LINK_RE.findall(_text(doc)):
        if re.match(r"[a-z][a-z0-9+.-]*:", target):
            continue
        path_part, _, fragment = target.partition("#")
        resolved = (base / path_part) if path_part else (REPO / doc)
        if not resolved.exists():
            broken.append(target)
        elif fragment and resolved.suffix == ".md" and fragment not in _anchors(resolved):
            broken.append(target)
    assert broken == [], f"{doc}: {broken}"


def test_manifest_entries_point_at_text_their_doc_still_carries() -> None:
    def squash(s: str) -> str:
        return re.sub(r"\s+", "", s.lower())

    stale = []
    for claim in claims_manifest.CLAIMS:
        doc = REPO / claim["doc"]
        if not doc.is_file() or squash(claim["text_glob"]) not in squash(doc.read_text(encoding="utf-8")):
            stale.append(claim["id"])
    assert stale == [], f"manifest vouches for text its doc no longer carries: {stale}"


def test_manifest_keeps_at_least_one_receipt_backed_entry_and_no_savings_headline() -> None:
    assert claims_manifest.CLAIMS, "check 8 fails on an empty manifest"
    for claim in claims_manifest.CLAIMS:
        assert claim["status"] == "verified" and claim["receipt"], claim["id"]
        assert (REPO / claim["receipt"]).is_file(), claim["id"]
        assert not re.search(r"fewer|saved|savings|tokens", claim["text_glob"], re.IGNORECASE), claim["id"]


if __name__ == "__main__":
    sys.exit(pytest.main([os.path.abspath(__file__), "-q"]))
