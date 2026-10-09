"""Level, roles and independence of the approval (Parte de #1649)."""
import pytest

from simplicio_loop.review_gate import diffs, identity
from simplicio_loop.review_gate.model import ERROR, FAIL, PASS, Level

WORKER = identity.Agent("worker-3", "worker", "haiku-5.5", "ccr")
COORD = identity.Agent("squad-q-coordinator", "coordinator", "sonnet-5.5", "ccr")
AUTO = identity.AUTO_REVIEWER
OTHER = identity.Agent("rev-9", "independent-reviewer", "opus-5.5", "local")


def _c(path, status="M", added=(1,)):
    return diffs.FileChange(path, status, tuple(added))


@pytest.mark.parametrize("path", [
    "simplicio_loop/sandbox.py", "simplicio_loop/daemon/run.py", "simplicio_loop/auth_token.py", "scripts/uninstall.sh",
    "packages/mapper/simplicio_mapper/x.py", "simplicio_loop/login_check.py", "simplicio_loop/secret_scan.py"])
def test_security_paths_are_t2(path):
    assert identity.classify_level([_c(path)]) is Level.T2


def test_tests_of_security_modules_are_not_t2_and_names_match_by_word():
    assert identity.classify_level([_c("tests/test_sandbox.py"), _c("docs/SANDBOX.md")]) is Level.T0
    assert identity.classify_level([_c("simplicio_loop/tokenizer_cache.py")]) is Level.T1  # "tokenizer" is not "token"


def test_levels_t0_small_docs_and_tests_t1_code_or_big():
    assert identity.classify_level([_c("docs/A.md"), _c("tests/test_a.py")]) is Level.T0
    assert identity.classify_level([_c("docs/A.md", added=range(300))]) is Level.T1
    assert identity.classify_level([_c("simplicio_loop/util.py")]) is Level.T1


def test_self_approval_by_agent_or_by_role_is_rejected():
    same = identity.check_identity(WORKER, WORKER, Level.T1, None)
    assert same.status == FAIL and "auto-aprovacao" in same.reasons[0]
    same_role = identity.check_identity(WORKER, identity.Agent("worker-4", "worker", "haiku-5.5", "ccr"), Level.T1, None)
    assert same_role.status == FAIL and "papel" in same_role.reasons[0]
    assert identity.check_identity(WORKER, COORD, Level.T1, None).status == PASS
    assert identity.check_identity(WORKER, AUTO, Level.T1, None).status == PASS


def test_unknown_author_is_an_error_not_a_pass():
    result = identity.check_identity(identity.Agent("", "", "", ""), AUTO, Level.T1, None)
    assert result.status == ERROR and "autor" in result.reasons[0]


def test_t2_needs_an_independent_reviewer_of_another_role():
    assert identity.check_identity(WORKER, AUTO, Level.T2, None).status == FAIL
    assert "revisor independente" in identity.check_identity(WORKER, AUTO, Level.T2, None).reasons[0]
    assert identity.check_identity(WORKER, AUTO, Level.T2, AUTO).status == FAIL  # the gate alone is not independent
    assert identity.check_identity(WORKER, AUTO, Level.T2, WORKER).status == FAIL
    assert identity.check_identity(WORKER, AUTO, Level.T2, identity.Agent("w9", "worker", "x", "y")).status == FAIL
    ok = identity.check_identity(WORKER, AUTO, Level.T2, OTHER)
    assert ok.status == PASS and ok.measured["independent"] == "rev-9"


MARK = "REVISÃO INDEPENDENTE: APROVADA\nrevisor: rev-9\npapel: independent-reviewer\nmodelo: opus-5.5\nhost: local\nhead: abcdef1234"


def test_marker_binds_to_the_head_and_ignores_quotes():
    comments = [{"body": "> " + MARK.replace("\n", "\n> ")}, {"body": "ok\n" + MARK}]
    agent = identity.parse_independent_marker(comments, "abcdef1234567890")
    assert agent == OTHER
    assert identity.parse_independent_marker(comments, "0000000fffff") is None  # approval of another head
    assert identity.parse_independent_marker([{"body": "> " + MARK}], "abcdef1234567890") is None
    assert identity.parse_independent_marker([{"body": "revisao independente aprovada\nhead: abcdef1"}], "abcdef1") is None
