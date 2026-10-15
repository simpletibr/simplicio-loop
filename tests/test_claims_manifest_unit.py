"""Unit tests for `scripts/claims_manifest.py` — the single source of truth for quantitative
claims (#96), imported by `claims_audit.py` check 8. In-process, no subprocess.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import claims_manifest  # noqa: E402


def test_every_claim_has_required_fields():
    for c in claims_manifest.CLAIMS:
        for field in ("id", "doc", "text_glob", "status", "receipt", "note"):
            assert field in c, "claim %s missing %s" % (c.get("id", "?"), field)


def test_claim_ids_are_unique():
    ids = [c["id"] for c in claims_manifest.CLAIMS]
    assert len(ids) == len(set(ids))


def test_claim_status_is_valid():
    for c in claims_manifest.CLAIMS:
        assert c["status"] in ("verified", "unverified"), c


def test_unverified_claim_without_receipt_has_no_receipt_path():
    for c in claims_manifest.CLAIMS:
        if c["status"] == "unverified":
            assert c["receipt"] is None or isinstance(c["receipt"], str)


def test_quant_re_matches_percentages():
    assert claims_manifest.QUANT_RE.search("93% saved")
    assert claims_manifest.QUANT_RE.search("up to 90%")
    assert claims_manifest.QUANT_RE.search("40-60% fewer")


def test_quant_re_does_not_match_url_encoding():
    assert not claims_manifest.QUANT_RE.search("path%20with%20spaces")
    assert not claims_manifest.QUANT_RE.search("bench%20%25%20encoded")


def test_extract_claims_runs_against_real_repo_without_crashing():
    unknown = claims_manifest.extract_claims()
    assert isinstance(unknown, list)


def test_extract_claims_finds_nothing_new_in_an_empty_repo(tmp_path):
    unknown = claims_manifest.extract_claims(doc_root=str(tmp_path))
    assert unknown == []


def test_extract_claims_flags_undocumented_claim(tmp_path):
    (tmp_path / "README.md").write_text("We saw a 77% improvement in latency.\n", encoding="utf-8")
    unknown = claims_manifest.extract_claims(doc_root=str(tmp_path))
    assert any("77%" in match for _doc, match in unknown)


# ---- #1814: the audit must cover PYPI.md, training/**/*.md and video/ -------------------------
def _flagged(doc_root):
    return claims_manifest.extract_claims(doc_root=str(doc_root))


def test_pypi_md_unbacked_percentage_fails_audit(tmp_path):
    (tmp_path / "PYPI.md").write_text("Drains any queue at up to 96% fewer tokens.\n", encoding="utf-8")
    flagged = _flagged(tmp_path)
    assert any(doc == "PYPI.md" and "96%" in m for doc, m in flagged), flagged


def test_pypi_md_percentage_is_not_masked_by_another_docs_manifest_entry(tmp_path):
    # README.md carries manifest entries such as "96%+ de cache hit" and "99%"; a manifest entry
    # for README.md must never vouch for the same digits in PYPI.md.
    for pct in ("96%", "99%", "93%"):
        (tmp_path / "PYPI.md").write_text("Headline: %s fewer tokens.\n" % pct, encoding="utf-8")
        assert any(doc == "PYPI.md" for doc, _m in _flagged(tmp_path)), pct


def test_pypi_md_without_percentages_is_clean(tmp_path):
    (tmp_path / "PYPI.md").write_text("Savings are measured, see bench/llm_ab. n=4 tasks.\n", encoding="utf-8")
    assert _flagged(tmp_path) == []


def test_training_markdown_percentage_fails_audit(tmp_path):
    d = tmp_path / "training" / "simplicio-27b"
    d.mkdir(parents=True)
    (d / "README.md").write_text("| Aider | **96.5%** |\n| Hit rate | 100.0% (5/5) |\n", encoding="utf-8")
    flagged = [m for doc, m in _flagged(tmp_path) if doc.replace("\\", "/") == "training/simplicio-27b/README.md"]
    assert len(flagged) >= 2, flagged  # decimal scores, including the ".0%" ones, must not slip through


def test_video_python_percentage_fails_audit_but_css_percentages_do_not(tmp_path):
    d = tmp_path / "video"
    d.mkdir()
    (d / "build_composition.py").write_text(
        'BADGES = ["MIT", "96% fewer tokens"]\n'
        'HTML = "<style>.a{width:100%;background:linear-gradient(transparent 60%,#000 82%)}</style><p>ok</p>"\n',
        encoding="utf-8",
    )
    flagged = [m for doc, m in _flagged(tmp_path) if doc.replace("\\", "/") == "video/build_composition.py"]
    assert flagged == ["96%"], flagged


def test_video_caption_json_percentage_fails_audit(tmp_path):
    d = tmp_path / "video" / "lang"
    d.mkdir(parents=True)
    (d / "en.json").write_text('{"scenes":[{"caption":"up to 96% fewer tokens"}]}', encoding="utf-8")
    assert any(doc.replace("\\", "/") == "video/lang/en.json" for doc, _m in _flagged(tmp_path))


def test_scan_targets_include_pypi_training_and_video():
    targets = {doc.replace("\\", "/") for doc, _strict in claims_manifest.claim_scan_targets()}
    assert "PYPI.md" in targets
    assert "training/simplicio-27b/README.md" in targets
    assert "video/build_composition.py" in targets
    assert {"README.md", "AGENTS.md"} <= targets  # legacy scope is kept


def test_real_repo_has_no_unbacked_claim_in_new_scan_scope():
    new_scope = ("PYPI.md", "training/", "video/")
    bad = [(d, m) for d, m in claims_manifest.extract_claims() if d.replace("\\", "/").startswith(new_scope)]
    assert bad == [], bad


def test_headline_percentages_are_gone_from_owned_docs():
    for rel in ("PYPI.md", "video/build_composition.py", "video/lang/en.json", "video/lang/pt-BR.json",
                "video/lang/es.json", "video/lang/zh-CN.json", "video/storyboard.master.json"):
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            text = fh.read()
        assert "96%" not in text, rel
        assert "93%" not in text, rel
        assert "11 runtimes" not in text and "48 ext" not in text, rel


def test_guide_headline_token_savings_percentages_are_gone():
    with open(os.path.join(REPO, "docs", "GUIDE.md"), encoding="utf-8") as fh:
        text = fh.read()
    for needle in ("90.3%", "96.7%", "96%+", "90%25%20fewer", "~90% fewer", "90.0% de reaproveitamento",
                   "95.0% de reaproveitamento", "até **90%**"):
        assert needle not in text, "unbacked headline still in docs/GUIDE.md: %s" % needle


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_claims_manifest_unit")
