"""Mutation gate: check that code changes are well-tested via mutation score."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from simplicio_loop.review_gate import diffs
from simplicio_loop.review_gate.mutation import (
    Mutant,
    check_mutation,
    generate,
    run_mutants,
    sample,
)
from simplicio_loop.review_gate.model import FAIL, PASS, SKIPPED, CheckResult


class TestMutantBasic:
    """Mutant dataclass basics."""

    def test_mutant_has_required_fields(self):
        m = Mutant(path="a.py", line=5, kind="flip_cmp", original="x == y", mutated="x != y")
        assert m.path == "a.py" and m.line == 5 and m.kind == "flip_cmp"
        assert m.original == "x == y" and m.mutated == "x != y"

    def test_mutant_id_is_stable(self):
        m1 = Mutant(path="a.py", line=5, kind="flip_cmp", original="x == y", mutated="x != y")
        m2 = Mutant(path="a.py", line=5, kind="flip_cmp", original="x == y", mutated="x != y")
        assert m1.id == m2.id

    def test_mutant_id_differs_by_kind_line_or_path(self):
        base = Mutant(path="a.py", line=5, kind="flip_cmp", original="x == y", mutated="x != y")
        diff_kind = Mutant(path="a.py", line=5, kind="other", original="x == y", mutated="x != y")
        diff_line = Mutant(path="a.py", line=6, kind="flip_cmp", original="x == y", mutated="x != y")
        diff_path = Mutant(path="b.py", line=5, kind="flip_cmp", original="x == y", mutated="x != y")
        assert base.id != diff_kind.id and base.id != diff_line.id and base.id != diff_path.id

    def test_mutant_describe_is_short(self):
        m = Mutant(path="pkg/a.py", line=5, kind="flip_cmp", original="x == y", mutated="full source")
        desc = m.describe()
        assert "pkg/a.py" in desc and "5" in desc and "flip_cmp" in desc
        assert len(desc) < 100


class TestGenerate:
    """generate() produces mutants deterministically from AST."""

    def test_generate_empty_when_no_lines_match(self):
        source = "def f():\n    x = 1\n    return x\n"
        assert generate("a.py", source, []) == []

    def test_generate_flip_comparison(self):
        source = "def f(x, y):\n    if x == y:\n        return 1\n    return 0\n"
        mutants = generate("a.py", source, [2])
        assert any(m.kind == "flip_cmp" for m in mutants)
        assert any("==" in m.original and "!=" in m.original.replace("==", "!=") for m in mutants)

    def test_generate_and_or_flip(self):
        source = "def f(a, b):\n    return a and b\n"
        mutants = generate("a.py", source, [2])
        assert any(m.kind == "and_or" for m in mutants)

    def test_generate_bool_flip(self):
        source = "def f():\n    return True\n"
        mutants = generate("a.py", source, [2])
        assert any(m.kind == "bool_flip" for m in mutants)

    def test_generate_mutated_is_valid_python(self):
        source = "def f(x):\n    if x > 0:\n        return 1\n    return 0\n"
        mutants = generate("a.py", source, [2])
        for m in mutants:
            compile(m.mutated, m.path, "exec")  # Must not raise

    def test_generate_skips_invalid_mutants(self):
        source = "def f(x):\n    if x == 2:\n        pass\n"
        mutants = generate("a.py", source, [2])
        for m in mutants:
            try:
                compile(m.mutated, m.path, "exec")
            except SyntaxError:
                pytest.fail(f"Mutant {m.id} does not compile")


class TestSample:
    """sample() is stable and deterministic."""

    def test_sample_stable_seed(self):
        mutants = [
            Mutant("a.py", i, "kind", f"orig{i}", f"mut{i}")
            for i in range(1, 11)
        ]
        sample1 = sample(mutants, 5, "seed123")
        sample2 = sample(mutants, 5, "seed123")
        assert [m.id for m in sample1] == [m.id for m in sample2]

    def test_sample_different_seed_different_order(self):
        mutants = [
            Mutant("a.py", i, "kind", f"orig{i}", f"mut{i}")
            for i in range(1, 11)
        ]
        sample1 = sample(mutants, 5, "seed1")
        sample2 = sample(mutants, 5, "seed2")
        assert [m.id for m in sample1] != [m.id for m in sample2]

    def test_sample_n_greater_than_list_returns_all(self):
        mutants = [
            Mutant("a.py", i, "kind", f"orig{i}", f"mut{i}")
            for i in range(1, 6)
        ]
        result = sample(mutants, 100, "seed")
        assert len(result) == 5

    def test_sample_returns_ordered_by_id(self):
        mutants = [
            Mutant("a.py", i, "kind", f"orig{i}", f"mut{i}")
            for i in range(1, 11)
        ]
        result = sample(mutants, 5, "seed123")
        ids = [m.id for m in result]
        assert ids == sorted(ids)


class TestRunMutants:
    """run_mutants() applies, tests, and restores."""

    def test_run_mutants_kills_and_restores(self, tmp_path):
        """A mutant is killed if the test fails."""
        root = tmp_path / "code"
        root.mkdir()
        (root / "app.py").write_text("def f(x):\n    return x == 0\n")
        (root / "tests").mkdir()
        (root / "tests" / "test_app.py").write_text(
            "from app import f\ndef test_f():\n    assert f(0)\n    assert not f(1)\n"
        )
        mutant = Mutant(
            path="app.py",
            line=2,
            kind="flip_cmp",
            original="return x == 0",
            mutated="def f(x):\n    return x != 0\n",
        )
        results = run_mutants(
            root,
            [mutant],
            [sys.executable, "-m", "pytest", "-q", "-x", "tests"],
            timeout_each=30,
        )
        assert len(results) == 1
        m, status = results[0]
        assert m.id == mutant.id and status == "killed"
        assert (root / "app.py").read_text() == "def f(x):\n    return x == 0\n"

    def test_run_mutants_survives_if_test_passes(self, tmp_path):
        """A mutant survives if the test still passes."""
        root = tmp_path / "code"
        root.mkdir()
        (root / "app.py").write_text("def f(x):\n    return x + 0\n")
        (root / "tests").mkdir()
        (root / "tests" / "test_app.py").write_text(
            "from app import f\ndef test_f():\n    assert f(5) == 5\n"
        )
        mutant = Mutant(
            path="app.py",
            line=2,
            kind="arith_flip",
            original="return x + 0",
            mutated="def f(x):\n    return x - 0\n",
        )
        results = run_mutants(
            root,
            [mutant],
            [sys.executable, "-m", "pytest", "-q", "-x", "tests"],
            timeout_each=30,
        )
        assert len(results) == 1
        m, status = results[0]
        assert status == "survived"

    def test_run_mutants_timeout_counts_as_killed(self, tmp_path):
        """Timeout counts as killed."""
        root = tmp_path / "code"
        root.mkdir()
        (root / "app.py").write_text("def f(x):\n    return x == 0\n")
        (root / "tests").mkdir()
        (root / "tests" / "test_app.py").write_text(
            "import time\nfrom app import f\ndef test_slow():\n    time.sleep(10)\n    assert f(0)\n"
        )
        mutant = Mutant(
            path="app.py",
            line=2,
            kind="flip_cmp",
            original="return x == 0",
            mutated="def f(x):\n    return x != 0\n",
        )
        results = run_mutants(
            root,
            [mutant],
            [sys.executable, "-m", "pytest", "-q", "-x", "tests"],
            timeout_each=1,
        )
        assert len(results) == 1
        m, status = results[0]
        assert status == "timeout"

    def test_run_mutants_restores_on_exception(self, tmp_path):
        """Original is restored even on exception."""
        root = tmp_path / "code"
        root.mkdir()
        (root / "app.py").write_text("def f(x):\n    return x == 0\n")
        (root / "bad.sh").write_text("exit 1\n")
        mutant = Mutant(
            path="app.py",
            line=2,
            kind="flip_cmp",
            original="return x == 0",
            mutated="def f(x):\n    return x != 0\n",
        )
        results = run_mutants(
            root,
            [mutant],
            ["bash", "bad.sh"],
            timeout_each=1,
        )
        # Even if the test command doesn't exist or raises, original must be restored
        assert (root / "app.py").read_text() == "def f(x):\n    return x == 0\n"

    def test_run_mutants_returncode_5_is_survived(self, tmp_path):
        """returncode 5 (no tests collected) is survived."""
        root = tmp_path / "code"
        root.mkdir()
        (root / "app.py").write_text("def f(x):\n    return x == 0\n")
        (root / "tests").mkdir()
        (root / "tests" / "__init__.py").write_text("")
        mutant = Mutant(
            path="app.py",
            line=2,
            kind="flip_cmp",
            original="return x == 0",
            mutated="def f(x):\n    return x != 0\n",
        )
        # pytest returns 5 if no tests are collected
        results = run_mutants(
            root,
            [mutant],
            [sys.executable, "-m", "pytest", "-q", "-x", "tests"],
            timeout_each=30,
        )
        assert len(results) == 1
        m, status = results[0]
        assert status == "survived"


class TestCheckMutation:
    """check_mutation() generates, samples, runs, and reports."""

    def test_check_mutation_skipped_no_code_changes(self):
        """No code changes => SKIPPED."""
        changes = [
            diffs.FileChange("docs/a.md", "A", (1, 2)),
            diffs.FileChange("tests/test_a.py", "A", (1, 2)),
        ]
        result = check_mutation(Path("/tmp"), changes, [sys.executable, "-m", "pytest"], n=5)
        assert result.name == "mutation"
        assert result.status == SKIPPED
        assert "sem linha de producao mutavel" in " ".join(result.reasons)

    def test_check_mutation_pass_when_sufficient_kill_ratio(self, tmp_path):
        """Kill ratio >= min_kill => PASS."""
        root = tmp_path / "code"
        root.mkdir()
        (root / "app.py").write_text("def f(x, y):\n    return x == y and x > 0\n")
        (root / "tests").mkdir()
        (root / "tests" / "test_app.py").write_text(
            "from app import f\ndef test_true():\n    assert f(1, 1)\ndef test_false():\n    assert not f(1, 2)\n"
        )
        changes = [diffs.FileChange("app.py", "A", (2,))]
        result = check_mutation(
            root, changes, [sys.executable, "-m", "pytest", "-q", "-x", "tests"],
            n=2, min_kill=0.4
        )
        assert result.status == PASS
        assert result.measured["killed"] >= 1

    def test_check_mutation_fail_when_low_kill_ratio(self, tmp_path):
        """Kill ratio < min_kill => FAIL."""
        root = tmp_path / "code"
        root.mkdir()
        (root / "app.py").write_text("def f(x):\n    return x + 0\n")
        (root / "tests").mkdir()
        (root / "tests" / "test_app.py").write_text(
            "from app import f\ndef test_f():\n    pass\n"  # test does nothing
        )
        changes = [diffs.FileChange("app.py", "A", (2,))]
        result = check_mutation(
            root, changes, [sys.executable, "-m", "pytest", "-q", "-x", "tests"],
            n=3, min_kill=0.5
        )
        assert result.status == FAIL
        assert result.measured["killed"] < 2
        assert "sobreviventes" in " ".join(result.reasons).lower()

    def test_check_mutation_measured_has_required_fields(self, tmp_path):
        """measured dict has total, killed, survived, ratio, n, seed."""
        root = tmp_path / "code"
        root.mkdir()
        (root / "app.py").write_text("def f(x):\n    return x == 0\n")
        (root / "tests").mkdir()
        (root / "tests" / "test_app.py").write_text(
            "from app import f\ndef test_f():\n    assert f(0) and not f(1)\n"
        )
        changes = [diffs.FileChange("app.py", "A", (2,))]
        result = check_mutation(
            root, changes, [sys.executable, "-m", "pytest", "-q", "-x", "tests"],
            n=3, seed="test"
        )
        m = result.measured
        assert "total" in m and "killed" in m
        assert "survived" in m and isinstance(m["survived"], list)
        assert m["ratio"] == m["killed"] / m["total"] if m["total"] else 0
        assert m["n"] == 3 and m["seed"] == "test"

    def test_check_mutation_only_checks_added_lines(self, tmp_path):
        """Only added lines are mutated, not removed or unchanged."""
        root = tmp_path / "code"
        root.mkdir()
        (root / "app.py").write_text(
            "def f(x):\n    return x == 0 and x > -1\n    # removed line\n"
        )
        (root / "tests").mkdir()
        (root / "tests" / "test_app.py").write_text(
            "from app import f\ndef test_f():\n    assert f(0)\n"
        )
        changes = [diffs.FileChange("app.py", "M", (2,))]  # Only line 2 was added
        result = check_mutation(
            root, changes, [sys.executable, "-m", "pytest", "-q", "-x", "tests"],
            n=5
        )
        # All mutants should be from line 2 only
        if result.measured["survived"]:
            for desc in result.measured["survived"]:
                # Line number should be present in describe()
                assert "app.py:2" in desc

    def test_check_mutation_deleted_files_skipped(self, tmp_path):
        """Deleted (D) files are skipped."""
        changes = [diffs.FileChange("old.py", "D", ())]
        result = check_mutation(Path("/tmp"), changes, [sys.executable, "-m", "pytest"], n=1)
        assert result.status == SKIPPED
