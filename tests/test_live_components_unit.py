"""Unit contract for the Simplicio Live web-component kit (issue #1399).

Browser behaviour (rendering, keyboard, axe-core) lives in test_live_components_e2e_system.py;
these checks need no browser: phase-icon parity with the CLI, the component inventory,
design tokens, reduced motion, CSP-safe rendering, zero runtime dependencies and the
80 KB gzip budget.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import pytest

from simplicio_loop.dashboard import CATALOG_PAGE, COMPONENTS_DIR, STATIC_DIR
from simplicio_loop.dashboard import phase_meta
from simplicio_loop.progress import PHASE_META, PHASES, _ascii

ROOT = Path(__file__).resolve().parents[1]
TAGS = (
    "sl-stage-rail", "sl-gate-badge", "sl-lane-swimlane", "sl-timeline", "sl-sparkline", "sl-donut",
    "sl-heatmap", "sl-log-viewer", "sl-json-tree", "sl-diff-view", "sl-kpi-card", "sl-alert-toast",
    "sl-command-palette", "sl-calendar", "sl-connection-dot",
)
STATES = ("RUNNING", "PASS", "FAIL", "UNVERIFIED", "STALLED", "BLOCKED")
BUDGET_BYTES = 80 * 1024


def _js_files():
    return sorted(COMPONENTS_DIR.glob("*.js"))


def _gzip_size(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), compresslevel=9))


def test_phase_meta_module_matches_the_cli_phase_meta():
    assert phase_meta.sync(check=True), "run: python -m simplicio_loop.dashboard.phase_meta"
    text = phase_meta.MODULE_PATH.read_text(encoding="utf-8")
    for phase, (icon, label) in PHASE_META.items():
        assert json.dumps(phase) in text and icon in text and label in text
    assert json.dumps(list(PHASES), ensure_ascii=False) in text


def test_phase_meta_check_reports_drift_without_writing(tmp_path):
    stale = tmp_path / "phase-meta.js"
    stale.write_text("// stale\n", encoding="utf-8")
    assert phase_meta.sync(stale, check=True) is False
    assert stale.read_text(encoding="utf-8") == "// stale\n"
    assert phase_meta.sync(stale) is False
    assert stale.read_text(encoding="utf-8") == phase_meta.render_module()
    assert phase_meta.sync(stale, check=True) is True


def test_phase_meta_cli_check_exit_codes(capsys):
    assert phase_meta.main(["--check"]) == 0
    assert "current" in capsys.readouterr().out


def test_phase_meta_covers_every_lifecycle_phase_with_an_ascii_fallback():
    for phase in (*PHASES, "blocked", "cancelled", "awaiting_decision"):
        icon, label = PHASE_META[phase]
        assert label and _ascii(icon).isascii(), phase


@pytest.mark.parametrize("tag", TAGS)
def test_every_component_has_one_module_registered_by_index_and_shown_in_the_catalog(tag):
    module = COMPONENTS_DIR / f"{tag}.js"
    source = module.read_text(encoding="utf-8")
    assert source.count(f'define("{tag}"') == 1
    assert f'"./{tag}.js"' in (COMPONENTS_DIR / "index.js").read_text(encoding="utf-8")
    catalog = (STATIC_DIR / "catalog.js").read_text(encoding="utf-8")
    assert f'tag: "{tag}"' in catalog and f"<{tag}" in catalog


def test_catalog_page_loads_tokens_and_offers_the_three_themes():
    html = CATALOG_PAGE.read_text(encoding="utf-8")
    assert 'href="components/simplicio-live.css"' in html and 'src="catalog.js"' in html
    for theme in ("dark", "light", "contrast"):
        assert f'value="{theme}"' in html
    assert 'name="compare"' in html


def test_catalog_exercises_every_state_for_state_driven_components():
    catalog = (STATIC_DIR / "catalog.js").read_text(encoding="utf-8")
    sections = re.split(r"\n  \{\n    tag: ", catalog)
    by_tag = {s.split('"')[1]: s for s in sections[1:]}
    for tag in ("sl-stage-rail", "sl-gate-badge", "sl-timeline", "sl-alert-toast", "sl-kpi-card", "sl-calendar", "sl-donut"):
        body = by_tag[tag]
        missing = [s for s in STATES if s not in body]
        if tag == "sl-stage-rail":  # off-rail states are driven by phase, not by the state keyword
            missing = [s for s in missing if s not in ("BLOCKED", "UNVERIFIED", "PASS")]
            assert 'phase="blocked"' in body and 'phase="done"' in body and "receipt-ready" in body
        assert not missing, (tag, missing)
    for status in ("live", "connecting", "stale", "offline"):
        assert f'status="{status}"' in by_tag["sl-connection-dot"]


def test_tokens_define_every_state_in_every_theme_and_respect_user_preferences():
    css = (COMPONENTS_DIR / "simplicio-live.css").read_text(encoding="utf-8")
    contrast = css.split('[data-sl-theme="contrast"] {', 1)[1].split("}", 1)[0]
    for state in (*STATES, "PENDING"):
        token = f"--sl-state-{state.lower()}:"
        assert re.search(re.escape(token) + r" light-dark\(#[0-9a-f]{6}, #[0-9a-f]{6}\)", css), state
        assert token in contrast, state
    for needle in ('[data-sl-theme="dark"]', '[data-sl-theme="light"]', "prefers-color-scheme",
                   "prefers-contrast: more", "prefers-reduced-motion: reduce", "--sl-step-0", "--sl-space-4",
                   "--sl-radius-panel", "--sl-dur-base"):
        assert needle in css, needle


def _media_blocks(text: str, query: str):
    spans, start = [], 0
    while (at := text.find(query, start)) != -1:
        open_at = text.index("{", at)
        depth, i = 0, open_at
        while True:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            if depth == 0:
                break
            i += 1
        spans.append((open_at, i))
        start = i
    return spans


@pytest.mark.parametrize("path", _js_files(), ids=lambda p: p.name)
def test_animations_only_run_when_the_user_allows_motion(path):
    text = path.read_text(encoding="utf-8")
    allowed = _media_blocks(text, "@media (prefers-reduced-motion: no-preference)")
    for match in re.finditer(r"\banimation:", text):
        assert any(a < match.start() < b for a, b in allowed), f"{path.name}: animation outside no-preference"


@pytest.mark.parametrize("path", _js_files(), ids=lambda p: p.name)
def test_components_have_no_runtime_dependencies_and_no_inline_styles(path):
    text = path.read_text(encoding="utf-8")
    specifiers = re.findall(r"""(?:import|export)\s[^;]*?from\s+["']([^"']+)["']|import\s+["']([^"']+)["']""", text)
    for spec in (s for pair in specifiers for s in pair if s):
        assert spec.startswith("./") and spec.endswith(".js"), f"{path.name}: {spec}"
    assert "fetch(" not in text and "http://" not in text and "https://" not in text.replace("https?", "")
    assert 'style="' not in text, f"{path.name}: use data-css (CSP style-src) instead of inline style"
    assert "innerHTML = this.render()" not in text or path.name == "base.js"


def test_npm_manifest_has_no_dependencies_and_exports_the_kit():
    manifest = json.loads((COMPONENTS_DIR / "package.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "@simplicio/live-components"
    assert manifest["type"] == "module" and manifest["exports"]["."] == "./index.js"
    assert manifest["dependencies"] == {} and "devDependencies" not in manifest
    assert manifest["private"] is True  # publishing is a release decision (see docs/DASHBOARD_DESIGN.md)


def test_total_weight_is_under_80_kb_gzip():
    files = [p for p in COMPONENTS_DIR.rglob("*") if p.is_file()]
    total = sum(_gzip_size(p) for p in files)
    assert total < BUDGET_BYTES, f"{total} bytes gzip >= {BUDGET_BYTES}"


def test_bundled_fonts_ship_with_their_licence():
    fonts = COMPONENTS_DIR / "fonts"
    assert sorted(p.name for p in fonts.glob("*.woff2")) == [
        "atkinson-hyperlegible-mono-400.woff2", "atkinson-hyperlegible-next-450-750.woff2"]
    for licence in fonts.glob("OFL-*.txt"):
        assert "SIL Open Font License, Version 1.1" in licence.read_text(encoding="utf-8")
    assert len(list(fonts.glob("OFL-*.txt"))) == 2


def test_frontend_design_skill_is_installed_with_its_licence():
    skill = ROOT / ".claude" / "skills" / "frontend-design"
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: frontend-design\n")
    assert "Apache License" in (skill / "LICENSE.txt").read_text(encoding="utf-8")


def test_design_direction_is_documented():
    doc = (ROOT / "docs" / "DASHBOARD_DESIGN.md").read_text(encoding="utf-8")
    for heading in ("## Aesthetic direction", "## Token system", "## Plan review", "## Components", "## Accessibility"):
        assert heading in doc, heading
    assert "frontend-design" in doc
    for tag in TAGS:
        assert f"`<{tag}>`" in doc, tag
