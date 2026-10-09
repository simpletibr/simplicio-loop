"""repo_conventions (intake): read target repo's conventions for branch rules, commit style, test command."""
from simplicio_loop.watcher247 import points


def test_registered_at_intake_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "repo_conventions"]
    assert (info.stage, info.blocking, info.conditional) == ("intake", False, False)


def test_contract_with_contributing(point_contract, make_ctx, tmp_path):
    (tmp_path / "CONTRIBUTING.md").write_text("# Contributing\n\nBranch rules: main only\n")
    result = point_contract("repo_conventions", make_ctx(clone=tmp_path), expect="ok")
    assert isinstance(result.evidence, dict)
    assert "summary" in result.evidence
    assert result.reason_code is None


def test_without_conventions_is_still_ok(point_contract, make_ctx, tmp_path):
    result = point_contract("repo_conventions", make_ctx(clone=tmp_path), expect="ok")
    assert isinstance(result.evidence, dict)
    assert "summary" in result.evidence


def test_without_a_clone_it_is_skipped(point_contract, make_ctx):
    result = point_contract("repo_conventions", make_ctx(), expect="skipped")
    assert result.reason_code == "no_clone"


def test_reads_contributing_agents_and_github_files(point_contract, make_ctx, tmp_path):
    (tmp_path / "CONTRIBUTING.md").write_text("# Contributing\nBranch: develop\n")
    (tmp_path / "AGENTS.md").write_text("# Agents\nCommit scope: [scope]\n")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CONTRIBUTING.md").write_text("# GitHub Contributing\nTest: pytest\n")
    result = point_contract("repo_conventions", make_ctx(clone=tmp_path), expect="ok")
    summary = result.evidence.get("summary", "")
    assert isinstance(summary, str)
    assert len(summary) > 0
