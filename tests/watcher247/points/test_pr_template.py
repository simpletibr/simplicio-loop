"""pr_template (pr): the PR body is the repo's PR template, kept verbatim, filled with the run evidence."""
import pytest

from simplicio_loop.watcher247 import points
from simplicio_loop.watcher247.points import pr_template

TEMPLATE = "## Summary\nFill this in\n\n## Test plan\n- [ ] Item 1\n"
ISSUE = {"number": 42, "title": "Fix the login timeout"}


def _expected(summary="Fix the login timeout", verify="pytest -q: 12 passed", template=TEMPLATE):
    return (template.rstrip() + "\n\n---\n\n### Summary\n" + summary + "\n\nParte de #42\n\n"
            "### How to verify\n" + verify + "\n")


def test_registered_at_pr_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "pr_template"]
    assert (info.stage, info.blocking, info.conditional) == ("pr", False, False)


def test_without_a_template_there_is_no_body(point_contract, make_ctx, tmp_path):
    result = point_contract("pr_template", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")
    assert result.evidence == {"template_found": None, "pr_body": None}


def test_without_a_clone_it_is_skipped(point_contract, make_ctx):
    result = point_contract("pr_template", make_ctx(), expect="skipped")
    assert result.reason_code == "no_clone"


@pytest.mark.parametrize("relative", [
    ".github/pull_request_template.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "PULL_REQUEST_TEMPLATE.md",
    "pull_request_template.md",
    "docs/PULL_REQUEST_TEMPLATE.md",
])
def test_template_in_every_location_and_case_is_filled_with_the_run_evidence(
        point_contract, make_ctx, tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE)
    ctx = make_ctx(clone=tmp_path, issue=ISSUE, verify="pytest -q: 12 passed")
    result = point_contract("pr_template", ctx, expect="ok")
    assert result.evidence["template_found"] == relative
    assert result.evidence["pr_body"] == _expected()
    assert result.evidence["dropped_sections"] == []


def test_plan_text_is_the_summary_over_the_issue_title(point_contract, make_ctx, tmp_path):
    (tmp_path / "PULL_REQUEST_TEMPLATE.md").write_text(TEMPLATE)
    ctx = make_ctx(clone=tmp_path, issue=ISSUE, plan="Retry the login call twice", verify="ok")
    result = point_contract("pr_template", ctx, expect="ok")
    assert result.evidence["pr_body"] == _expected(summary="Retry the login call twice", verify="ok")


def test_the_run_evidence_is_left_out_when_the_run_has_none(point_contract, make_ctx, tmp_path):
    (tmp_path / "PULL_REQUEST_TEMPLATE.md").write_text(TEMPLATE)
    result = point_contract("pr_template", make_ctx(clone=tmp_path), expect="ok")
    assert result.evidence["pr_body"] == TEMPLATE.rstrip() + "\n\n---\n"


def test_sections_that_ask_for_secrets_are_skipped(point_contract, make_ctx, tmp_path):
    template = ("## Summary\nFill this in\n\n## API key / token\nPaste your token here\n\n"
                "### Where it is stored\nin the vault\n\n## Checklist\n- [ ] No secrets committed\n")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "pull_request_template.md").write_text(template)
    ctx = make_ctx(clone=tmp_path, issue=ISSUE, verify="ok")
    result = point_contract("pr_template", ctx, expect="ok")
    kept = "## Summary\nFill this in\n\n## Checklist\n- [ ] No secrets committed\n"
    assert result.evidence["pr_body"] == _expected(verify="ok", template=kept)
    assert result.evidence["dropped_sections"] == ["API key / token"]


def test_drop_secret_sections_stops_at_the_next_heading_of_the_same_level():
    kept, dropped = pr_template.drop_secret_sections("intro\n## Password\nsecret\n## After\nkeep")
    assert (kept, dropped) == ("intro\n## After\nkeep", ["Password"])
