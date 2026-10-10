"""squad_gate: a T2 approval needs a marker of an independent reviewer bound to the head (Parte de #1649)."""
from simplicio_loop import squads

ME = {"login": "bot"}
OID = "abc1234" + "5" * 33
APPROVE = ("REVISÃO AUTOMÁTICA: APROVADA (nível {n})\n\nPapeis:\n- autor: worker-3 (worker, haiku-5.5, ccr)\n\n"
           "<!-- simplicio-loop:squad-approval:" + OID + " -->")
MARK = "REVISÃO INDEPENDENTE: APROVADA\nrevisor: {who}\npapel: {role}\nmodelo: opus-5.5\nhost: local\nhead: " + OID


def _pr(level, *extra, files=None):
    comments = [{"id": "a", "createdAt": "2026-10-09T02:00:00Z", "author": ME, "body": APPROVE.format(n=level)}, *extra]
    pr = {"commits": [{"oid": OID, "committedDate": "2026-10-09T01:00:00Z"}], "comments": comments}
    return pr if files is None else {**pr, "files": [{"path": p} for p in files]}


def _mark(who="rev-9", role="independent-reviewer", author=ME, head=None):
    body = MARK.format(who=who, role=role) if head is None else MARK.format(who=who, role=role).replace(OID, head)
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


def test_a_diff_with_a_start_up_hook_or_installed_metadata_needs_t2_whatever_the_comment_says():
    for path in ("pytest.toml", ".pytest.toml", "sitecustomize.py", "usercustomize.py", "tests/x.pth", "pkg.egg-info/entry_points.txt",
                 "pkg-1.0.dist-info/entry_points.txt"):
        low = squads.squad_gate(_pr(1, files=["src/app.py", path]), approvers=["bot"])
        assert not low["approved"] and low["reason"] == "level_below_diff" and low["level"] == 2, path
        assert squads.squad_gate(_pr(2, _mark(), files=["src/app.py", path]), approvers=["bot"])["approved"], path


def test_a_diff_with_a_nested_conftest_or_pytest_config_needs_t2_whatever_the_comment_says():
    for path in ("tests/sub/conftest.py", "tests/Sub/CONFTEST.py", "pytest.ini", "tox.ini", "tests/plugins/x.py"):
        low = squads.squad_gate(_pr(1, files=["src/app.py", path]), approvers=["bot"])
        assert not low["approved"] and low["reason"] == "level_below_diff" and low["level"] == 2, path
        assert squads.squad_gate(_pr(2, _mark(), files=["src/app.py", path]), approvers=["bot"])["approved"], path
