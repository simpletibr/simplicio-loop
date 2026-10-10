"""The pytest that judges the PR is main's: a conftest, pytest config or plugin of the PR is never obeyed (#1649, review round).

A `conftest.py` in any folder of the PR runs inside the pytest of the gate and can rewrite the outcome of any test; it can
even tell the two trees apart by their cwd (`/base`, `/head`). So the gate copies none of them into main's tree, puts main's
version (or nothing) in the head tree, pins the pytest configuration and stops conftest collection at the tree.
"""
import sys
import textwrap

import pytest

from simplicio_loop.review_gate import diffs, redgreen
from simplicio_loop.review_gate.model import FAIL, PASS

OLD = "def add(a, b):\n    return a\n"
NEW = "def add(a, b):\n    return a + b\n"
TEST = "from mod import add\n\n\ndef test_add_sums():\n    assert add(1, 2) == 3\n\n\ndef test_add_zero():\n    assert add(0, 5) == 5\n"
FORGE = textwrap.dedent('''\
    import os

    import pytest


    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(item, call):
        report = (yield).get_result()
        if call.when == "call":  # tells the trees apart by the cwd the gate gave them
            report.outcome = "passed" if os.getcwd().endswith("/head") else "failed"
    ''')
ALL_PASS = FORGE.replace('"passed" if os.getcwd().endswith("/head") else "failed"', '"passed"')
NEVER_FIXED = "from mod import add\n\n\ndef test_add_is_fixed():\n    assert add(1, 2) == 3\n"
FIXTURE = "import pytest\n\n\n@pytest.fixture\ndef three():\n    return 3\n"
USES_FIXTURE = "from mod import add\n\n\ndef test_add_three(three):\n    assert add(1, 2) == three\n"


def _write(root, files):
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    return root


def _added(path, status="A", lines=9):
    return diffs.FileChange(path, status, tuple(range(1, lines + 1)))


MOD = diffs.FileChange("mod.py", "M", (2,))


def _check(tmp_path, base_files, head_files, changes, **kw):
    base, head = _write(tmp_path / "base", base_files), _write(tmp_path / "head", head_files)
    kw.setdefault("env", {"PYTHONPATH": "."})
    return redgreen.check_redgreen(base, head, changes, python=sys.executable, **kw), base, head


def test_the_forged_conftest_in_a_subfolder_cannot_turn_a_never_fixed_bug_into_a_pass(tmp_path):
    """The forgery of the review: production never fixed, tests/sub/conftest.py rewriting the report by tree, a real fix elsewhere."""
    result, base, head = _check(
        tmp_path, {"mod.py": OLD, "other.py": "def f():\n    return 1\n"},
        {"mod.py": OLD, "other.py": "def f():\n    return 2\n", "tests/sub/test_bug.py": NEVER_FIXED, "tests/sub/conftest.py": FORGE},
        [_added("tests/sub/test_bug.py"), _added("tests/sub/conftest.py"), diffs.FileChange("other.py", "M", (2,))])
    assert result.status == FAIL, result.reasons
    assert result.measured["head_failed"] == ["tests/sub/test_bug.py::test_add_is_fixed"]
    assert not (base / "tests" / "sub" / "conftest.py").exists()  # never copied over main
    assert not (head / "tests" / "sub" / "conftest.py").exists()  # and not obeyed on the head either
    assert "conftest" in result.reasons[0] and result.measured["pytest_infra_ignored"] == ["tests/sub/conftest.py"]


@pytest.mark.parametrize("path", ["tests/conftest.py", "conftest.py", "tests/a/b/c/conftest.py"])
def test_a_conftest_of_the_pr_is_never_copied_into_the_tree_of_main_wherever_it_is(tmp_path, path):
    result, base, head = _check(tmp_path, {"mod.py": OLD}, {"mod.py": NEW, "tests/test_mod.py": TEST, path: FORGE},
                                [_added("tests/test_mod.py"), _added(path), MOD])
    assert not (base / path).exists() and not (head / path).exists()
    assert result.status == PASS, result.reasons  # the honest tests are red on main and green with the change, under main's pytest
    assert result.measured["pytest_infra_ignored"] == [path]


def test_a_new_test_that_needs_the_conftest_of_the_pr_fails_honestly_and_the_message_says_so(tmp_path):
    result, _, _ = _check(tmp_path, {"mod.py": OLD}, {"mod.py": NEW, "tests/test_mod.py": USES_FIXTURE, "tests/conftest.py": FIXTURE},
                          [_added("tests/test_mod.py", lines=5), _added("tests/conftest.py"), MOD])
    assert result.status == FAIL
    assert result.measured["head_failed"] == ["tests/test_mod.py::test_add_three"]
    assert "conftest" in result.reasons[0] and "tests/conftest.py" in result.reasons[0] and "T2" in result.reasons[0]
    assert result.measured["red"] == ["tests/test_mod.py::test_add_three"]  # red on main as well: honest on both sides


def test_main_keeps_its_own_conftest_and_the_pr_cannot_replace_it(tmp_path):
    result, base, head = _check(
        tmp_path, {"mod.py": OLD, "tests/conftest.py": FIXTURE},
        {"mod.py": NEW, "tests/test_mod.py": USES_FIXTURE, "tests/conftest.py": FORGE},
        [_added("tests/test_mod.py", lines=5), diffs.FileChange("tests/conftest.py", "M", (1,)), MOD])
    assert result.status == PASS, result.reasons  # `three` comes from the conftest of main, loaded in both trees
    assert (base / "tests" / "conftest.py").read_text() == FIXTURE == (head / "tests" / "conftest.py").read_text()


def test_a_conftest_the_pr_deletes_is_back_in_the_head_tree_as_main_has_it(tmp_path):
    result, _, head = _check(
        tmp_path, {"mod.py": OLD, "tests/conftest.py": FIXTURE}, {"mod.py": NEW, "tests/test_mod.py": USES_FIXTURE},
        [_added("tests/test_mod.py", lines=5), diffs.FileChange("tests/conftest.py", "D", ()), MOD])
    assert result.status == PASS, result.reasons
    assert (head / "tests" / "conftest.py").read_text() == FIXTURE


def test_a_pytest_ini_of_the_pr_is_ignored_and_one_above_the_tree_is_never_read(tmp_path):
    broken = "[pytest]\nminversion = 99\n"
    (tmp_path / "pytest.ini").write_text(broken)  # above both trees: a search upward would find it
    result, base, head = _check(tmp_path, {"mod.py": OLD}, {"mod.py": NEW, "tests/test_mod.py": TEST, "pytest.ini": broken},
                                [_added("tests/test_mod.py"), _added("pytest.ini", lines=2), MOD])
    assert result.status == PASS, result.reasons
    assert not (base / "pytest.ini").exists() and not (head / "pytest.ini").exists()


def test_a_conftest_above_the_trees_is_not_collected(tmp_path):
    (tmp_path / "conftest.py").write_text(ALL_PASS)  # would make the tests that are red on main look vacuous
    result, _, _ = _check(tmp_path, {"mod.py": OLD}, {"mod.py": NEW, "tests/test_mod.py": TEST}, [_added("tests/test_mod.py"), MOD])
    assert result.status == PASS, result.reasons


def test_the_conftest_of_main_is_loaded_even_though_the_config_is_pinned(tmp_path):
    """`-c /dev/null` alone would move pytest's confcutdir to /dev and drop every conftest: the run sets it to the tree."""
    result, _, _ = _check(tmp_path, {"mod.py": OLD, "tests/conftest.py": FIXTURE},
                          {"mod.py": NEW, "tests/conftest.py": FIXTURE, "tests/test_mod.py": USES_FIXTURE},
                          [_added("tests/test_mod.py", lines=5), MOD])
    assert result.status == PASS, result.reasons


def test_pytest_is_started_with_the_conftest_cut_at_the_tree_and_the_config_pinned(tmp_path):
    seen = []
    _check(tmp_path, {"mod.py": OLD}, {"mod.py": NEW, "tests/test_mod.py": TEST}, [_added("tests/test_mod.py"), MOD],
           wrap=lambda argv: seen.append(argv) or argv)
    assert len(seen) == 2
    for argv in seen:
        args = argv[3:]
        assert args[args.index("--confcutdir") + 1] == "." and args[args.index("-c") + 1] == "/dev/null"
        assert args[args.index("--rootdir") + 1] == "." and "no:cacheprovider" in args


@pytest.mark.parametrize("name, text, expected", [
    ("pytest.ini", "", ["-c", "pytest.ini", "--rootdir", "."]),
    (".pytest.ini", "[pytest]\n", ["-c", ".pytest.ini", "--rootdir", "."]),
    ("pyproject.toml", "[tool.pytest.ini_options]\nx = 1\n", ["-c", "pyproject.toml", "--rootdir", "."]),
    ("pyproject.toml", "[project]\nname = 'x'\n", ["-c", "/dev/null", "--rootdir", "."]),
    ("tox.ini", "[pytest]\nx = 1\n", ["-c", "tox.ini", "--rootdir", "."]),
    ("tox.ini", "[tox]\nenvlist = py\n", ["-c", "/dev/null", "--rootdir", "."]),
    ("setup.cfg", "[tool:pytest]\nx = 1\n", ["-c", "setup.cfg", "--rootdir", "."]),
    ("setup.cfg", "[metadata]\nname = x\n", ["-c", "/dev/null", "--rootdir", "."]),
])
def test_the_pytest_config_of_the_tree_is_pinned_by_name_only_when_it_holds_a_pytest_section(tmp_path, name, text, expected):
    (tmp_path / name).write_text(text)
    assert redgreen._pytest_config(tmp_path) == expected


@pytest.mark.parametrize("path", ["tests/conftest.py", "a/b/conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml",
                                  "tests/pytest.ini", "tests/plugins.py", "tests/plugins/fake.py", "tests/pytest_plugins.py"])
def test_neutralize_puts_the_file_of_main_back_or_removes_it(tmp_path, path):
    base, head = _write(tmp_path / "base", {path: "main\n", "keep.py": "k\n"}), _write(tmp_path / "head", {path: "pr\n", "keep.py": "k2\n"})
    assert redgreen.neutralize_pytest_infra(base, head, [_added(path, "M"), diffs.FileChange("keep.py", "M", (1,))]) == [path]
    assert (head / path).read_text() == "main\n" and (head / "keep.py").read_text() == "k2\n"
    only_head = _write(tmp_path / "h2", {path: "pr\n"})
    redgreen.neutralize_pytest_infra(tmp_path / "b2", only_head, [_added(path)])
    assert not (only_head / path).exists()


def test_a_symlinked_conftest_of_the_pr_is_removed_without_touching_its_target(tmp_path):
    base, head = _write(tmp_path / "base", {"mod.py": OLD}), _write(tmp_path / "head", {"mod.py": NEW, "outside.txt": "keep\n"})
    (head / "tests" / "sub").mkdir(parents=True)
    (head / "tests" / "sub" / "conftest.py").symlink_to(head / "outside.txt")
    redgreen.neutralize_pytest_infra(base, head, [_added("tests/sub/conftest.py")])
    assert not (head / "tests" / "sub" / "conftest.py").is_symlink() and (head / "outside.txt").read_text() == "keep\n"


def test_a_test_file_is_never_written_through_a_symlink_of_the_tree_of_main(tmp_path):
    (tmp_path / "secret.txt").write_text("main\n")
    base, head = _write(tmp_path / "base", {"mod.py": OLD}), _write(tmp_path / "head", {"mod.py": NEW, "tests/test_mod.py": TEST})
    (base / "tests").mkdir()
    (base / "tests" / "test_mod.py").symlink_to(tmp_path / "secret.txt")
    result = redgreen.check_redgreen(base, head, [_added("tests/test_mod.py"), MOD], python=sys.executable, env={"PYTHONPATH": "."})
    assert result.status == PASS, result.reasons
    assert (tmp_path / "secret.txt").read_text() == "main\n"


def test_a_helper_module_beside_the_tests_is_still_copied_to_main(tmp_path):
    helper = "def expected():\n    return 3\n"
    test = "from helpers import expected\nfrom mod import add\n\n\ndef test_add():\n    assert add(1, 2) == expected()\n"
    result, base, _ = _check(tmp_path, {"mod.py": OLD}, {"mod.py": NEW, "tests/helpers.py": helper, "tests/test_mod.py": test},
                             [_added("tests/helpers.py", lines=2), _added("tests/test_mod.py", lines=6), MOD], env={"PYTHONPATH": ".:tests"})
    assert result.status == PASS, result.reasons
    assert (base / "tests" / "helpers.py").read_text() == helper
