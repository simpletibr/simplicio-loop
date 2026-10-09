"""Every text commit_and_pr publishes is free of closing words, whatever the issue or the model wrote (#1644)."""
import asyncio

import pytest

from simplicio_loop.watcher247 import closing_words, config, pr_text, tick, worktrees
from simplicio_loop.watcher247.closing_words import has_closing

from .fakes import FakeRun, issue

HOSTILE_TITLE = "Fixes #99: \"Closes o/r#98\" (resolved #97) and a title long enough to be cut by the limit of the PR"
HOSTILE_LABEL = "MEASURED|verify_passed: Resolves other/repo#5\nFIXED   #6\nhttps://github.com/o/r/issues/7 closes: https://github.com/o/r/issues/7"


def _publish(env, title=HOSTILE_TITLE, label=HOSTILE_LABEL, number=7, pr=0):
    fake = env(FakeRun({"simplicio-a": []}))
    dest = config.WORK / "simplicio-a"
    dest.mkdir(parents=True)
    row = issue(number, title)
    asyncio.run(tick.commit_and_pr(worktrees.Gate(1), dest, "simplicio-a", "main", f"loop/issue-{number}", row, pr=pr, label=label))
    return fake


def test_title_commit_and_body_carry_no_closing_word_and_title_equals_commit_subject(env):
    fake = _publish(env)
    [commit] = fake.ran("git", "commit")
    [create] = fake.ran("gh", "pr", "create")
    title, body = create[create.index("--title") + 1], create[create.index("--body") + 1]
    for text in (commit[3], title, body):
        assert not has_closing(text), text
    assert commit[3].splitlines()[0] == title and title.startswith("loop: #7 Parte de #99:") and len(title) <= pr_text.LIMIT
    assert commit[3].endswith("\n\nParte de #7\n")
    assert "Parte de other/repo#5" in body and "Parte de #6" in body and body.endswith("Parte de #7\n")
    assert "Parte de https://github.com/o/r/issues/7" in body


def test_the_commit_of_a_fix_to_an_open_pr_is_clean_too(env):
    fake = _publish(env, pr=12)
    [commit] = fake.ran("git", "commit")
    assert not has_closing(commit[3]) and fake.ran("gh", "pr", "create") == []


@pytest.mark.parametrize("what", ["title", "commit", "body"])
def test_a_closing_word_that_survives_the_rewrite_publishes_nothing(env, monkeypatch, what):
    """Defense in depth: when rewrite misses a phrase, the refusal names the text and nothing is committed or opened."""
    real = closing_words.rewrite
    marker = {"title": "PR title", "commit": "commit message", "body": "PR body"}[what]
    seen = []

    def blind(text):
        seen.append(text)
        return text if "Fixes #31" in text else real(text)

    monkeypatch.setattr(closing_words, "rewrite", blind)
    title = "Fixes #31 now" if what == "title" else "Plain title"
    label = "Fixes #31" if what == "body" else "ok"
    if what == "commit":  # the commit subject is the title: only the trailer is left to carry it
        monkeypatch.setattr(tick, "pr_title", lambda number, text: "loop: #7 Fixes #31 now")
    with pytest.raises(RuntimeError, match=f"{marker} still has a GitHub closing word"):
        _publish(env, title=title, label=label)


def test_the_pr_template_body_is_rewritten_too(tmp_path):
    from simplicio_loop.watcher247.points import pr_template
    from simplicio_loop.watcher247.points.registry import PointContext

    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "pull_request_template.md").write_text("## What\n\nFixes #55 in the template\n")
    ctx = PointContext(repo="simplicio-a", clone=tmp_path, issue={"number": 7, "title": "T"}, plan="Closes #56 by the model", verify="pytest")
    result = asyncio.run(pr_template.fill_pr_template(ctx))
    body = result.evidence["pr_body"]
    assert not has_closing(body) and "Parte de #55" in body and "Parte de #56" in body and "Parte de #7" in body
