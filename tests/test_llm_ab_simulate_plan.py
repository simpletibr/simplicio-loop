"""The wave arm writes every edit plan up front: plan N+1 is generated
against the file content plan N will leave, computed without touching disk."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bench", "llm_ab"))
import runner_loop  # noqa: E402


def test_simulate_plan_applies_find_replace_to_content_map():
    files = {"cadastro.html": "<!-- PH -->\n"}
    plan = {"operations": [{"path": "cadastro.html", "find": "<!-- PH -->", "replace": "<form></form>"}]}
    assert runner_loop.simulate_plan(files, plan) == {"cadastro.html": "<form></form>\n"}
    assert files == {"cadastro.html": "<!-- PH -->\n"}


def test_simulate_plan_rejects_find_that_is_missing_or_not_unique():
    files = {"a.html": "<p>x</p><p>x</p>"}
    for find in ("<p>y</p>", "<p>x</p>"):
        plan = {"operations": [{"path": "a.html", "find": find, "replace": "z"}]}
        try:
            runner_loop.simulate_plan(files, plan)
        except ValueError as exc:
            assert "a.html" in str(exc)
        else:
            raise AssertionError("expected ValueError for find=%r" % find)
