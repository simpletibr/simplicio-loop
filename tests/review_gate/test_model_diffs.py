"""Contract of the review gate and the diff reader (Parte de #1649)."""
import subprocess

import pytest

from simplicio_loop.review_gate import diffs, model

DIFF = """diff --git a/pkg/a.py b/pkg/a.py
index 111..222 100644
--- a/pkg/a.py
+++ b/pkg/a.py
@@ -3,0 +4,2 @@ def f():
+    x = 1
+    y = 2
@@ -10 +13 @@ def g():
-    old
+    new
diff --git a/tests/test_a.py b/tests/test_a.py
new file mode 100644
--- /dev/null
+++ b/tests/test_a.py
@@ -0,0 +1,2 @@
+def test_a():
+    assert 1
diff --git a/docs/old.md b/docs/old.md
deleted file mode 100644
--- a/docs/old.md
+++ /dev/null
@@ -1,2 +0,0 @@
-a
-b
"""


def test_parse_diff_lines_status_and_removed():
    files = {f.path: f for f in diffs.parse_diff(DIFF)}
    assert files["pkg/a.py"].added == (4, 5, 13) and files["pkg/a.py"].removed == 1
    assert files["pkg/a.py"].status == "M"
    assert files["tests/test_a.py"].status == "A" and files["tests/test_a.py"].added == (1, 2)
    assert files["docs/old.md"].status == "D" and files["docs/old.md"].removed == 2


@pytest.mark.parametrize("path,kind", [
    ("tests/x/test_y.py", "test"), ("pkg/test_z.py", "test"), ("pkg/conftest.py", "test"), ("pkg/mod.py", "code"),
    ("scripts/x.py", "code"), ("docs/A.md", "docs"), ("README.md", "docs"), ("pyproject.toml", "other")])
def test_kind_of(path, kind):
    assert diffs.kind_of(path) == kind


def test_changed_files_uses_merge_base(tmp_path):
    def git(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=tmp_path, check=True,
                       capture_output=True)
    git("init", "-q", "-b", "main")
    (tmp_path / "a.py").write_text("x = 1\n")
    git("add", "."); git("commit", "-qm", "base")
    git("checkout", "-qb", "feat")
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    git("commit", "-qam", "feat")
    git("checkout", "-q", "main")
    (tmp_path / "other.py").write_text("z = 1\n")
    git("add", "."); git("commit", "-qm", "main moves on")
    changes = diffs.changed_files(tmp_path, "main", "feat")
    assert [(c.path, c.added) for c in changes] == [("a.py", (2,))]


def test_changed_files_raises_with_the_cause(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    with pytest.raises(RuntimeError, match="git diff main...feat failed"):
        diffs.changed_files(tmp_path, "main", "feat")


def test_check_result_rules():
    with pytest.raises(ValueError):
        model.CheckResult("x", model.FAIL)
    with pytest.raises(ValueError):
        model.CheckResult("x", "weird")
    assert model.CheckResult("x", model.ERROR, ("boom",)).blocking
    assert not model.CheckResult("x", model.SKIPPED, ("n/a",)).blocking


def test_report_approves_only_with_checks_and_no_blocker():
    ok = model.CheckResult("a", model.PASS)
    bad = model.CheckResult("b", model.FAIL, ("why",))
    mk = lambda checks: model.GateReport(1, 2, "abc", model.Level.T1, tuple(checks))  # noqa: E731
    assert mk([ok]).approved and not mk([ok, bad]).approved and not mk([]).approved
    assert mk([ok, bad]).to_dict()["checks"][1]["reasons"] == ["why"]
    assert model.Level.T2.number == 2
