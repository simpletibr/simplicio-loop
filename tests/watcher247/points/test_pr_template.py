"""pr_template (pr): read PR template if exists, produce PR body that follows its headings."""
from simplicio_loop.watcher247 import points


def test_registered_at_pr_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "pr_template"]
    assert (info.stage, info.blocking, info.conditional) == ("pr", False, False)


def test_contract_without_template(point_contract, make_ctx, tmp_path):
    result = point_contract("pr_template", make_ctx(clone=tmp_path), expect="ok")
    assert isinstance(result.evidence, dict)
    assert "pr_body" in result.evidence or "template_found" in result.evidence


def test_pr_body_is_json_serializable(point_contract, make_ctx, tmp_path):
    result = point_contract("pr_template", make_ctx(clone=tmp_path), expect="ok")
    # JSON serialization is checked by conftest, this just documents the expectation
    assert isinstance(result.evidence.get("pr_body"), (str, type(None)))


def test_finds_github_pr_template(point_contract, make_ctx, tmp_path):
    (tmp_path / ".github").mkdir()
    template = """## Summary\nFill this in\n\n## Test plan\n- [ ] Item 1\n"""
    (tmp_path / ".github" / "pull_request_template.md").write_text(template)
    result = point_contract("pr_template", make_ctx(clone=tmp_path), expect="ok")
    assert result.evidence.get("template_found") in (True, "found", ".github/pull_request_template.md")


def test_finds_root_pull_request_template_md(point_contract, make_ctx, tmp_path):
    (tmp_path / "PULL_REQUEST_TEMPLATE.md").write_text("## Summary\nRoot template\n")
    result = point_contract("pr_template", make_ctx(clone=tmp_path), expect="ok")
    assert result.evidence.get("template_found") in (True, "found", "PULL_REQUEST_TEMPLATE.md")


def test_finds_docs_pr_template(point_contract, make_ctx, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "PULL_REQUEST_TEMPLATE.md").write_text("## Summary\nDocs template\n")
    result = point_contract("pr_template", make_ctx(clone=tmp_path), expect="ok")
    assert result.evidence.get("template_found") in (True, "found", "docs/PULL_REQUEST_TEMPLATE.md")


def test_without_a_clone_it_is_skipped(point_contract, make_ctx):
    result = point_contract("pr_template", make_ctx(), expect="skipped")
    assert result.reason_code == "no_clone"
