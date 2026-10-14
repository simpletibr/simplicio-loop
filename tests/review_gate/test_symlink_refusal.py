"""A PR that adds or retargets a symlink is refused before any tree is made: the gate never follows a link (Parte de #1649, m5)."""
from __future__ import annotations

from simplicio_loop.review_gate import diffs, gate, identity, isolation
from simplicio_loop.review_gate.model import FAIL
from tests.review_gate import scenario

WORKER = identity.Agent("worker-1", "worker", "haiku-5.5", "local")

SYMLINK_DIFF = """diff --git a/pkg/secret.py b/pkg/secret.py
new file mode 120000
index 0000000..1111111
--- /dev/null
+++ b/pkg/secret.py
@@ -0,0 +1 @@
+/etc/passwd
\\ No newline at end of file
diff --git a/pkg/link.py b/pkg/link.py
index 222..333 120000
--- a/pkg/link.py
+++ b/pkg/link.py
@@ -1 +1 @@
-a.py
\\ No newline at end of file
+/etc/passwd
\\ No newline at end of file
diff --git a/pkg/a.py b/pkg/a.py
index 444..555 100644
--- a/pkg/a.py
+++ b/pkg/a.py
@@ -1 +1 @@
-x = 0
+x = 1
"""


def test_parse_diff_flags_a_symlink_entry_by_its_mode():
    files = {f.path: f for f in diffs.parse_diff(SYMLINK_DIFF)}
    assert files["pkg/secret.py"].symlink and files["pkg/secret.py"].status == "A"
    assert files["pkg/link.py"].symlink and files["pkg/link.py"].status == "M"
    assert not files["pkg/a.py"].symlink


def _link(repo, links):
    for name, target in links.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.exists():
            path.unlink()
        path.symlink_to(target)


def _gate(tmp_path, monkeypatch, base_links, head_links):
    def no_jail(*_a, **_k):
        raise AssertionError("a refused PR needs no jail")

    monkeypatch.setattr(isolation, "make_jail", no_jail)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    scenario.git(repo, "init", "-q", "-b", "main")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _link(repo, base_links)
    scenario.git(repo, "add", "-A")
    scenario.git(repo, "commit", "-q", "-m", "base")
    base = scenario.git(repo, "rev-parse", "HEAD")
    scenario.git(repo, "checkout", "-q", "-b", "loop/issue-5")
    _link(repo, head_links)
    scenario.git(repo, "add", "-A")
    scenario.git(repo, "commit", "-q", "--allow-empty", "-m", "head")
    head = scenario.git(repo, "rev-parse", "HEAD")
    report = gate.run_gate(gate.GateInput(repo=repo, pr=11, issue=None, issue_body="", pr_body="", base=base, head=head, author=WORKER))
    return report, repo


def _refused(report, repo, paths):
    assert not report.approved
    assert [c.name for c in report.checks] == ["diff"] and report.checks[0].status == FAIL
    check = report.checks[0]
    assert check.reasons[0].startswith("symlink_refused") and check.measured["reason_code"] == "symlink_refused"
    assert check.measured["paths"] == paths
    assert not (repo / ".simplicio-loop" / "review-gate" / f"pr-11-{report.head[:7]}").exists()


def test_a_pr_that_adds_a_symlink_to_etc_passwd_is_refused_without_following_it(tmp_path, monkeypatch):
    report, repo = _gate(tmp_path, monkeypatch, base_links={}, head_links={"pkg/secret.py": "/etc/passwd"})
    _refused(report, repo, ["pkg/secret.py"])


def test_a_pr_that_changes_a_symlink_target_to_etc_passwd_is_refused(tmp_path, monkeypatch):
    report, repo = _gate(tmp_path, monkeypatch, base_links={"pkg/link.py": "a.py"}, head_links={"pkg/link.py": "/etc/passwd"})
    _refused(report, repo, ["pkg/link.py"])
