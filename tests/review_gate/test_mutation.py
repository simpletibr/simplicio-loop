"""Mutation sample of the review gate: AST mutants (never strings, comments or docstrings), run against the PR's tests."""
from __future__ import annotations

import sys
from pathlib import Path

from simplicio_loop.review_gate.diffs import FileChange
from simplicio_loop.review_gate.model import ERROR, FAIL, PASS, SKIPPED
from simplicio_loop.review_gate.mutation import KILLED, SURVIVED, TIMEOUT, Mutant, _Stamp, check_mutation, generate, run_mutants, sample

PYTEST = [sys.executable, "-m", "pytest", "-q", "-x", "--tb=no", "-p", "no:cacheprovider", "-o", "addopts=", "tests"]


def kinds(source: str, lines) -> set[str]:
    return {m.kind for m in generate("a.py", source, lines)}


def test_every_operator_has_a_mutant():
    source = ("def f(x, y):\n    if x == y and y:\n        return x + 1\n    flag = True\n    log(x)\n    return y if x else 0\n")
    assert kinds(source, range(1, 7)) == {"flip_cmp", "and_or", "negate_cond", "return_none", "arith_flip", "int_const", "bool_flip", "drop_call"}


def test_the_mutated_text_is_in_the_description():
    (m,) = [m for m in generate("pkg/a.py", "def f(x):\n    return x == 3\n", [2]) if m.kind == "flip_cmp"]
    assert (m.original, m.replacement, m.line) == ("x == 3", "x != 3", 2) and "pkg/a.py:2 flip_cmp" in m.describe()
    assert "x != 3" in m.source and "x == 3" not in m.source


def test_strings_comments_and_docstrings_are_never_mutated():
    source = ('def f(x):\n    """Return x == 1 and True; 7 or 3"""\n    # if x == 1 and True: return 5\n'
              '    return "x == 1 and True or 7"\n')
    assert [m.kind for m in generate("a.py", source, range(1, 5))] == ["return_none"]


def test_a_comparison_inside_a_string_on_a_target_line_gives_no_flip():
    assert kinds('def f(x):\n    msg = "a == b and 5"  # x == 2\n    return msg\n', [2]) == set()


def test_every_mutant_compiles_and_differs_from_the_source():
    source = "import os\n\ndef f(a, b):\n    while a < b and not os.path.exists('x'):\n        a += 1\n    return a if b else -1\n"
    mutants = generate("a.py", source, range(1, 7))
    assert len(mutants) >= 6
    for m in mutants:
        compile(m.source, "a.py", "exec")
        assert m.source != "" and m.original != m.replacement


def test_only_the_target_lines_are_mutated():
    source = "def f(x):\n    a = x == 1\n    b = x == 2\n    return a, b\n"
    assert {m.line for m in generate("a.py", source, [3])} == {3}
    assert generate("a.py", source, []) == []
    assert generate("a.py", source, [99]) == []


def test_chained_comparison_mutates_each_operator_apart():
    flips = [m for m in generate("a.py", "def f(a, b, c):\n    return a < b <= c\n", [2]) if m.kind == "flip_cmp"]
    assert sorted(m.replacement for m in flips) == ["a < b > c", "a >= b <= c"]


def test_unparsable_source_has_no_mutants():
    assert generate("a.py", "def f(:\n", [1]) == []


def test_generate_is_deterministic():
    source = "def f(x):\n    return x + 1 if x > 2 else 0\n"
    assert generate("a.py", source, [2]) == generate("a.py", source, [2])


def test_none_returns_and_bare_names_have_no_return_mutant():
    assert "return_none" not in kinds("def f():\n    return None\n", [2])
    assert "return_none" not in kinds("def f():\n    return\n", [2])


def test_sample_is_stable_and_bounded():
    pool = [Mutant("a.py", i, "k", f"o{i}", f"r{i}", f"s{i}") for i in range(30)]
    first = sample(pool, 7, "seed")
    assert len(first) == 7 and first == sample(list(reversed(pool)), 7, "seed")
    assert first != sample(pool, 7, "other") and sample(pool, 0, "seed") == [] and len(sample(pool, 99, "seed")) == 30


def make_project(tmp_path: Path, app: str, test: str) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "app.py").write_text(app)
    (tmp_path / "tests" / "test_app.py").write_text(test)
    return tmp_path


def test_run_mutants_kills_survives_and_restores(tmp_path):
    root = make_project(tmp_path, "def f(x):\n    return x == 0\n", "from app import f\n\ndef test_f():\n    assert f(0) and not f(1)\n")
    killer = generate("app.py", (root / "app.py").read_text(), [2])
    assert [s for _, s in run_mutants(root, killer, PYTEST, 60)] == [KILLED] * len(killer)
    assert (root / "app.py").read_text() == "def f(x):\n    return x == 0\n"
    (root / "tests" / "test_app.py").write_text("from app import f\n\ndef test_f():\n    assert True\n")
    assert {s for _, s in run_mutants(root, killer, PYTEST, 60)} == {SURVIVED}


def test_two_writes_in_the_same_second_get_different_whole_second_mtimes(tmp_path):
    """A .pyc stores the mtime in whole seconds and the size: a same-size mutant written in the same second would load the stale bytecode."""
    target, stamp, seen = tmp_path / "a.py", _Stamp(), []
    for text in ("x = 1\n", "x = 2\n", "x = 1\n"):
        stamp.write(target, text)
        seen.append(int(target.stat().st_mtime))
    assert seen[0] < seen[1] < seen[2] and target.read_text() == "x = 1\n"


def test_the_mutant_source_keeps_the_size_of_a_canonical_file(tmp_path):
    (flip,) = [m for m in generate("a.py", "def f(x):\n    return x == 0\n", [2]) if m.kind == "flip_cmp"]
    assert flip.source == "def f(x):\n    return x != 0\n"


def test_a_timeout_is_reported_and_is_not_a_kill(tmp_path):
    root = make_project(tmp_path, "def f(x):\n    return x == 0\n", "import time\nfrom app import f\n\ndef test_slow():\n    time.sleep(10)\n    assert f(0)\n")
    ((_, status),) = run_mutants(root, generate("app.py", (root / "app.py").read_text(), [2])[:1], PYTEST, 1)
    assert status == TIMEOUT


def test_the_file_is_restored_when_the_run_fails(tmp_path):
    root = make_project(tmp_path, "def f(x):\n    return x == 0\n", "")
    mutant = generate("app.py", (root / "app.py").read_text(), [2])[0]
    try:
        run_mutants(root, [mutant], ["/no/such/python", "-m", "pytest"], 5)
    except RuntimeError:
        pass
    assert (root / "app.py").read_text() == "def f(x):\n    return x == 0\n"


def test_no_tests_collected_is_a_survivor(tmp_path):
    root = make_project(tmp_path, "def f(x):\n    return x == 0\n", "x = 1\n")
    assert {s for _, s in run_mutants(root, generate("app.py", (root / "app.py").read_text(), [2]), PYTEST, 60)} == {SURVIVED}


def test_no_mutable_production_line_is_skipped(tmp_path):
    root = make_project(tmp_path, "X = 'a'\n", "")
    assert check_mutation(root, [FileChange("app.py", "A", (1,))], PYTEST).status == SKIPPED
    assert check_mutation(root, [FileChange("docs/a.md", "A", (1,)), FileChange("app.py", "D", ())], PYTEST).status == SKIPPED


def test_a_suite_that_does_not_pass_unmutated_is_an_error_not_a_pass(tmp_path):
    root = make_project(tmp_path, "def f(x):\n    return x == 0\n", "def test_f():\n    assert False\n")
    result = check_mutation(root, [FileChange("app.py", "A", (2,))], PYTEST)
    assert result.status == ERROR and "sem mutante" in result.reasons[0]


def test_tests_that_kill_the_mutants_pass_the_gate_with_the_count(tmp_path):
    root = make_project(tmp_path, "def f(x, y):\n    return x == y\n", "from app import f\n\ndef test_f():\n    assert f(1, 1)\n    assert not f(1, 2)\n")
    result = check_mutation(root, [FileChange("app.py", "A", (2,))], PYTEST, seed="s")
    assert result.status == PASS and result.measured["killed"] == result.measured["total"] >= 2 and result.measured["ratio"] == 1.0


def test_vacuous_tests_fail_the_gate_and_name_the_survivors(tmp_path):
    root = make_project(tmp_path, "def f(x, y):\n    return x == y\n", "from app import f\n\ndef test_f():\n    f(1, 1)\n")
    result = check_mutation(root, [FileChange("app.py", "A", (2,))], PYTEST, seed="s")
    assert result.status == FAIL and "app.py:2 flip_cmp" in result.reasons[0] and result.measured["killed"] == 0


def test_only_the_added_lines_are_mutated(tmp_path):
    root = make_project(tmp_path, "def f(x):\n    return x == 0\n\ndef g(x):\n    return x == 5\n",
                        "from app import f\n\ndef test_f():\n    assert f(0)\n    assert not f(1)\n")
    result = check_mutation(root, [FileChange("app.py", "M", (2,))], PYTEST, seed="s")
    assert result.status == PASS and all("app.py:2 " in line for line in result.measured["survived"]) and result.measured["candidates"] == 3


def test_the_tests_see_the_path_of_the_host_even_when_the_gate_passes_only_pythonpath(tmp_path):
    """#1641: a test that runs `git` failed in the baseline, because the env of the run was only PYTHONPATH."""
    root = make_project(tmp_path, "def f(x, y):\n    return x == y\n",
                        "import os\nfrom app import f\n\ndef test_f():\n    assert os.environ.get('PATH')\n    assert f(1, 1) and not f(1, 2)\n")
    result = check_mutation(root, [FileChange("app.py", "A", (2,))], PYTEST, seed="s", env={"PYTHONPATH": "."})
    assert result.status == PASS, result.reasons
