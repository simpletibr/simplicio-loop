"""The comment the gate posts on the PR (Parte de #1649)."""
from simplicio_loop.review_gate import comment, identity
from simplicio_loop.review_gate.model import ERROR, FAIL, PASS, SKIPPED, CheckResult, GateReport, Level

AUTHOR = identity.Agent("worker-3", "worker", "haiku-5.5", "ccr")


def _report(*checks, level=Level.T1, partial=False):
    return GateReport(7, 3, "abcdef1234567", level, tuple(checks), partial, 12.34)


def test_approved_comment_has_the_phrase_level_roles_numbers_and_commands():
    text = comment.render(_report(CheckResult("redgreen", PASS, (), {"tests": 4, "red": ["a", "b"], "elapsed_s": 1.5}),
                                  CheckResult("mutation", PASS, (), {"killed": 9, "total": 12})),
                          AUTHOR, identity.AUTO_REVIEWER, None, ["pytest novos em head e main"])
    first = text.splitlines()[0]
    assert first == "REVISÃO AUTOMÁTICA: APROVADA (nível 1)"
    for needle in ("worker-3", "haiku-5.5", "review-gate/auto", "9/12", "pytest novos em head e main", "12.3 s", "abcdef1"):
        assert needle in text


def test_rejected_comment_shows_every_cause_and_never_the_approval_phrase():
    text = comment.render(_report(CheckResult("redgreen", FAIL, ("11 testes novos passam em main",)),
                                  CheckResult("endpoint_compare", ERROR, ("flow_audit_failed: exit 2",)),
                                  CheckResult("docs", SKIPPED, ("nenhum doc",))), AUTHOR, identity.AUTO_REVIEWER, None, [])
    assert text.splitlines()[0] == "REVISÃO AUTOMÁTICA: REPROVADA (nível 1)"
    assert "APROVADA" not in text
    assert "11 testes novos passam em main" in text and "flow_audit_failed: exit 2" in text


def test_partial_pr_says_parte_de_and_t2_names_the_independent_reviewer():
    ind = identity.Agent("rev-9", "independent-reviewer", "opus-5.5", "local")
    text = comment.render(_report(CheckResult("coverage", PASS, (), {"uncovered": ["x"]}), level=Level.T2, partial=True),
                          AUTHOR, identity.AUTO_REVIEWER, ind, [])
    assert "(nível 2)" in text and "rev-9" in text and "PARCIAL" in text and "Parte de #3" in text


def test_squad_gate_reads_the_phrase_render_posts_and_nothing_else():
    """The comment is the contract between this module (which posts it) and `squads.squad_gate` (which reads it)."""
    from simplicio_loop import squads

    def level(body):
        found = squads._APPROVAL_LINE.search(body)
        return int(found.group(1)) if found else None

    approved = comment.render(_report(CheckResult("usage", PASS)), AUTHOR, identity.AUTO_REVIEWER, None, [])
    rejected = comment.render(_report(CheckResult("usage", FAIL, ("x",))), AUTHOR, identity.AUTO_REVIEWER, None, [])
    assert level(approved) == 1 and level(rejected) is None
    assert level("> REVISÃO AUTOMÁTICA: APROVADA (nível 1)") is None and level("APROVADO PELO SQUAD") is None