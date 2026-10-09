"""repo_conventions (intake): the clone's conventions, mined by simplicio_loop.repo_conventions."""
import subprocess

from simplicio_loop.watcher247 import points

TICKET = r"\b([A-Z][A-Z0-9]+-\d+)\b"  # the ticket pattern the miner reports


def _git(path, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=path, check=True,
                   capture_output=True)


def _summary(point_contract, make_ctx, clone):
    return point_contract("repo_conventions", make_ctx(clone=clone), expect="ok").evidence["summary"]


def test_registered_at_intake_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "repo_conventions"]
    assert (info.stage, info.blocking, info.conditional) == ("intake", False, False)


def test_without_a_clone_it_is_skipped(point_contract, make_ctx):
    result = point_contract("repo_conventions", make_ctx(), expect="skipped")
    assert result.reason_code == "no_clone"


def test_a_clone_without_conventions_degrades_to_the_default(point_contract, make_ctx, tmp_path):
    assert _summary(point_contract, make_ctx, tmp_path) == (
        "conventions: source=default conf=0.00"
        " | branch={type}/{slug} commit=conventional(scopes:-) ticket=- pr-sections=0  [b=0 c=0 pr=0]"
        " | architecture: docs=0 test=- lint=-")


def test_documented_conventional_commits_and_the_test_command_are_reported(
        point_contract, make_ctx, tmp_path):
    (tmp_path / "CONTRIBUTING.md").write_text("# Contributing\n\nWe use Conventional Commits.\n")
    (tmp_path / "AGENTS.md").write_text("# Agents\n")
    (tmp_path / "Makefile").write_text("test:\n\tpytest\nlint:\n\truff check .\n")
    assert _summary(point_contract, make_ctx, tmp_path) == (
        "conventions: source=config conf=0.00"
        " | branch={type}/{slug} commit=conventional(scopes:-) ticket=- pr-sections=0  [b=0 c=0 pr=0]"
        " | architecture: docs=2 test=make test lint=make lint")


def test_github_contributing_is_read_for_the_conventional_commits_hint(
        point_contract, make_ctx, tmp_path):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CONTRIBUTING.md").write_text("Follow commitizen.\n")
    assert _summary(point_contract, make_ctx, tmp_path).startswith("conventions: source=config conf=0.00 | ")


def test_git_history_gives_the_branch_scheme_commit_style_and_pr_sections(
        point_contract, make_ctx, tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    for number in range(1, 9):
        _git(tmp_path, "commit", "-q", "--allow-empty", "-m", f"feat(auth): step {number}")
    for number in range(1, 4):
        _git(tmp_path, "branch", f"feat/JIRA-{number}-thing")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text("## Summary\n\n## Test plan\n")
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
    assert _summary(point_contract, make_ctx, tmp_path) == (
        "conventions: source=history conf=1.00"
        f" | branch={{type}}/{{slug}} commit=conventional(scopes:auth) ticket={TICKET} pr-sections=2  [b=3 c=8 pr=0]"
        " | architecture: docs=0 test=make test lint=-")
