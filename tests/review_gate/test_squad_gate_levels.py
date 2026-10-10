"""squad_gate: a T2 approval needs a marker of an independent reviewer bound to the head (Parte de #1649)."""
from simplicio_loop import squads

ME = {"login": "bot"}
APPROVE = "REVISÃO AUTOMÁTICA: APROVADA (nível {n})\n\nPapeis:\n- autor: worker-3 (worker, haiku-5.5, ccr)\n"
MARK = "REVISÃO INDEPENDENTE: APROVADA\nrevisor: {who}\npapel: {role}\nmodelo: opus-5.5\nhost: local\nhead: abc1234"


def _pr(level, *extra):
    comments = [{"id": "a", "createdAt": "2026-10-09T02:00:00Z", "author": ME, "body": APPROVE.format(n=level)}, *extra]
    return {"commits": [{"oid": "abc1234567890", "committedDate": "2026-10-09T01:00:00Z"}], "comments": comments}


def _mark(who="rev-9", role="independent-reviewer", author=ME, head=None):
    body = MARK.format(who=who, role=role) if head is None else MARK.format(who=who, role=role).replace("abc1234", head)
    return {"id": "m", "createdAt": "2026-10-09T02:01:00Z", "author": author, "body": body}


def test_t0_and_t1_need_no_independent_marker_and_report_the_level():
    for level in (0, 1):
        verdict = squads.squad_gate(_pr(level), approvers=["bot"])
        assert verdict["approved"] and verdict["level"] == level


def test_t2_without_marker_is_blocked():
    verdict = squads.squad_gate(_pr(2), approvers=["bot"])
    assert not verdict["approved"] and verdict["reason"] == "independent_review_missing"


def test_t2_with_a_valid_marker_is_approved():
    assert squads.squad_gate(_pr(2, _mark()), approvers=["bot"])["approved"]


def test_t2_marker_must_be_independent_authorized_and_for_this_head():
    gate = lambda *c: squads.squad_gate(_pr(2, *c), approvers=["bot"])  # noqa: E731
    assert gate(_mark(who="worker-3"))["reason"] == "independent_review_missing"  # the author
    assert gate(_mark(who="review-gate/auto", role="automatic-reviewer"))["reason"] == "independent_review_missing"
    assert gate(_mark(head="zzzzzzz"))["reason"] == "independent_review_missing"  # another head
    assert gate(_mark(author={"login": "stranger"}))["reason"] == "independent_review_missing"  # unauthorized account
