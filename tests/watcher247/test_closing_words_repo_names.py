"""A closing word inside the NAME of a repo is not a closing word (#1644, found by the review of #1718).

`sanitize` is the one door of every PR text. Before: `Closes acme/fix#4` became `Parte de acme/fix#4` and then the check found
`fix#4` again and raised `RuntimeError` (the delivery of the PR stopped), and `see acme/fixes#4` was mangled to
`see acme/Parte de #4`. A plain `owner/repo#N` reference must stay as written; a real keyword before it still counts.
"""
from __future__ import annotations

import signal
import time

import pytest

from simplicio_loop.watcher247.closing_words import has_closing, rewrite, sanitize


@pytest.mark.parametrize("text", [
    "see acme/fixes#4", "acme/fix#4", "o/closes#1 and o/resolved#2", "(acme/Fix#9)", "x.y/fixed#3", "a-b/close#7,",
])
def test_a_repo_whose_name_is_a_keyword_is_a_plain_reference(text):
    assert has_closing(text) is False
    assert rewrite(text) == text
    assert sanitize(text, "PR body") == text


@pytest.mark.parametrize("text,expected", [
    ("Closes acme/fix#4", "Parte de acme/fix#4"),
    ("fixes: o/closes#5", "Parte de o/closes#5"),
    ("Resolved acme/resolve#6 and see acme/fixes#4", "Parte de acme/resolve#6 and see acme/fixes#4"),
    ("acme/fix#4 closes #9", "acme/fix#4 Parte de #9"),
    ("closes/fixes #4", "closes/Parte de #4"),  # no `#` right after the repo name: the second word is a real keyword
])
def test_a_real_keyword_before_such_a_reference_is_still_rewritten_and_never_raises(text, expected):
    assert rewrite(text) == expected
    assert sanitize(text, "PR body") == expected


def test_the_plain_reference_branch_stays_linear():
    def stuck(signum, frame):
        raise AssertionError("sanitize does not return: the scan is not linear")

    previous = signal.signal(signal.SIGALRM, stuck)  # a quadratic scan would take minutes here: fail fast instead
    try:
        for text in ("a" * 200_000, "a." * 100_000, "a-/" * 70_000, "a/b" * 70_000, " ".join(["closes"] * 30_000)):
            signal.alarm(10)
            started = time.perf_counter()
            sanitize(text, "PR body")
            signal.alarm(0)
            assert time.perf_counter() - started < 1.0, len(text)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
