"""A protected path is T2 at the review gate, and the automatic gate alone never approves it (#1567).

`squad_flow._review` (protected, not edited here) hands the verdict to `review_gate.identity`: a change to a path that
`plan_paths` protects is T2, and `check_identity` fails a T2 change with no independent reviewer, whatever the tests say.
This file pins that chain; it changes no production code.
"""
from simplicio_loop import plan_paths
from simplicio_loop.review_gate import diffs, identity
from simplicio_loop.review_gate.model import FAIL, PASS, Level

PATH = ".github/workflows/x.yml"
WORKER = identity.Agent("squad-q/worker-3", "worker", "haiku-5.5", "watcher247")
INDEPENDENT = identity.Agent("rev-9", "independent-reviewer", "opus-5.5", "local")


def _level() -> Level:
    return identity.classify_level([diffs.FileChange(PATH, "M", ("on: pull_request_target",))])


def test_the_protected_workflow_is_protected_and_t2():
    assert plan_paths.protected_refusal(PATH) is not None
    assert _level() is Level.T2


def test_the_automatic_gate_alone_cannot_approve_it_even_with_green_tests():
    result = identity.check_identity(WORKER, identity.AUTO_REVIEWER, _level(), independent=None)
    assert result.status == FAIL
    assert any("nivel T2" in reason and "o portao automatico sozinho nao aprova" in reason for reason in result.reasons)


def test_an_independent_reviewer_is_what_lets_it_pass():
    assert identity.check_identity(WORKER, identity.AUTO_REVIEWER, _level(), independent=INDEPENDENT).status == PASS
