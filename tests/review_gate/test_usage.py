"""Tests for usage: ensure new public symbols are referenced outside tests."""
from __future__ import annotations

import pathlib
import pytest

from simplicio_loop.review_gate.diffs import FileChange
from simplicio_loop.review_gate.model import CheckResult, PASS, FAIL, SKIPPED, ERROR
from simplicio_loop.review_gate.usage import public_names, check_usage


class TestPublicNames:
    """Extract public symbols from source."""

    def test_function_def(self):
        source = "def foo(x):\n    return x\n"
        names = public_names(source)
        assert "foo" in names
        assert names["foo"] == 1

    def test_async_function(self):
        source = "async def bar():\n    pass\n"
        names = public_names(source)
        assert "bar" in names
        assert names["bar"] == 1

    def test_class_def(self):
        source = "class Thing:\n    pass\n"
        names = public_names(source)
        assert "Thing" in names
        assert names["Thing"] == 1

    def test_assignment(self):
        source = "VERSION = '1.0'\nconfig = {}\n"
        names = public_names(source)
        assert "VERSION" in names
        assert "config" in names
        assert names["VERSION"] == 1
        assert names["config"] == 2

    def test_ignores_private_names(self):
        source = "def _private():\n    pass\n_var = 1\n"
        names = public_names(source)
        assert "_private" not in names
        assert "_var" not in names

    def test_ignores_dunders(self):
        source = "def __init__():\n    pass\n"
        names = public_names(source)
        assert "__init__" not in names

    def test_mixed_symbols(self):
        source = """
def do_thing():
    pass

class MyClass:
    pass

VERSION = "1.0"

def _helper():
    pass
"""
        names = public_names(source)
        assert set(names.keys()) == {"do_thing", "MyClass", "VERSION"}


class TestCheckUsage:
    """Verify new public symbols have references outside tests."""

    def test_pass_all_symbols_used(self, tmp_path):
        """A new symbol that is used in non-test code passes."""
        # Create root structure
        (tmp_path / "mymod").mkdir()
        (tmp_path / "mymod" / "__init__.py").write_text("")
        (tmp_path / "mymod" / "impl.py").write_text("def new_func():\n    pass\n")
        (tmp_path / "mymod" / "caller.py").write_text("from mymod.impl import new_func\nnew_func()\n")

        changes = [FileChange("mymod/impl.py", "A", (1,))]
        base_public = {}  # new file

        result = check_usage(tmp_path, changes, base_public)
        assert result.status == PASS
        assert result.name == "usage"

    def test_fail_unused_symbol(self, tmp_path):
        """A new symbol with no external references fails."""
        (tmp_path / "mymod").mkdir()
        (tmp_path / "mymod" / "__init__.py").write_text("")
        (tmp_path / "mymod" / "impl.py").write_text("def unused_func():\n    pass\n")

        changes = [FileChange("mymod/impl.py", "A", (1,))]
        base_public = {}

        result = check_usage(tmp_path, changes, base_public)
        assert result.status == FAIL
        assert "unused_func" in str(result.reasons)

    def test_ignores_test_references(self, tmp_path):
        """References only in test files do not count."""
        (tmp_path / "mymod").mkdir()
        (tmp_path / "mymod" / "__init__.py").write_text("")
        (tmp_path / "mymod" / "impl.py").write_text("def test_only_func():\n    pass\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_impl.py").write_text("from mymod.impl import test_only_func\ntest_only_func()\n")

        changes = [FileChange("mymod/impl.py", "A", (1,))]
        base_public = {}

        result = check_usage(tmp_path, changes, base_public)
        assert result.status == FAIL

    def test_new_module_without_importers(self, tmp_path):
        """A new module without importers fails."""
        (tmp_path / "mymod").mkdir()
        (tmp_path / "mymod" / "__init__.py").write_text("")
        (tmp_path / "mymod" / "newmod.py").write_text("VERSION = '1.0'\n")

        changes = [FileChange("mymod/newmod.py", "A", (1,))]
        base_public = {}

        result = check_usage(tmp_path, changes, base_public)
        assert result.status == FAIL
        assert "newmod" in str(result.reasons)

    def test_new_module_with_importers(self, tmp_path):
        """A new module with importers passes."""
        (tmp_path / "mymod").mkdir()
        (tmp_path / "mymod" / "__init__.py").write_text("")
        (tmp_path / "mymod" / "newmod.py").write_text("VERSION = '1.0'\n")
        (tmp_path / "mymod" / "caller.py").write_text("from mymod import newmod\nprint(newmod.VERSION)\n")

        changes = [FileChange("mymod/newmod.py", "A", (1,))]
        base_public = {}

        result = check_usage(tmp_path, changes, base_public)
        assert result.status == PASS

    def test_skipped_when_no_code_changes(self, tmp_path):
        """No code changes means skipped."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "README.md").write_text("# Hello\n")

        changes = [FileChange("docs/README.md", "M", (1,))]
        base_public = {}

        result = check_usage(tmp_path, changes, base_public)
        assert result.status == SKIPPED
        assert "sem codigo" in str(result.reasons).lower()

    def test_modified_symbol_validation(self, tmp_path):
        """Symbols modified (not added) are checked only if they are new."""
        (tmp_path / "mymod").mkdir()
        (tmp_path / "mymod" / "__init__.py").write_text("")
        (tmp_path / "mymod" / "impl.py").write_text("def old_func():\n    pass\n\ndef new_func():\n    pass\n")

        changes = [FileChange("mymod/impl.py", "M", (3, 4))]
        base_public = {"mymod/impl.py": frozenset(["old_func"])}

        result = check_usage(tmp_path, changes, base_public)
        # new_func is new but not used -> should fail
        assert result.status == FAIL

    def test_attribute_references(self, tmp_path):
        """Attribute access (e.g., module.symbol) counts as reference."""
        (tmp_path / "mymod").mkdir()
        (tmp_path / "mymod" / "__init__.py").write_text("")
        (tmp_path / "mymod" / "impl.py").write_text("class Thing:\n    pass\n")
        (tmp_path / "mymod" / "caller.py").write_text("import mymod.impl\nx = mymod.impl.Thing()\n")

        changes = [FileChange("mymod/impl.py", "A", (1,))]
        base_public = {}

        result = check_usage(tmp_path, changes, base_public)
        assert result.status == PASS

    def test_error_on_syntax_error(self, tmp_path):
        """Syntax errors are reported as ERROR."""
        (tmp_path / "mymod").mkdir()
        (tmp_path / "mymod" / "__init__.py").write_text("")
        (tmp_path / "mymod" / "bad.py").write_text("def broken(\n")

        changes = [FileChange("mymod/bad.py", "A", (1,))]
        base_public = {}

        result = check_usage(tmp_path, changes, base_public)
        assert result.status == ERROR
        assert "SyntaxError" in str(result.reasons)


# --- the gate runs with its root inside `.simplicio-loop/review-gate/<pr>/head`, so every test below uses that root ---

GATE_ROOT = pathlib.Path(".simplicio-loop") / "review-gate" / "pr-1-abc1234" / "head"
PKG = {"mymod/__init__.py": ""}


@pytest.fixture(params=["inside-gate-dir", "plain"])
def gate_tmp(request, tmp_path):
    """The root of the tree under check: inside `.simplicio-loop/review-gate/...` as the gate has it, or a plain directory."""
    base = tmp_path / GATE_ROOT if request.param == "inside-gate-dir" else tmp_path
    base.mkdir(parents=True, exist_ok=True)
    return base


def make_root(gate_tmp, files):
    root = gate_tmp
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def run_new(gate_tmp, files, new="mymod/impl.py", status="A", lines=None, base=None):
    """check_usage over one changed file; by default every line of it is new."""
    root = make_root(gate_tmp, files)
    added = lines if lines is not None else tuple(range(1, len(files[new].splitlines()) + 1))
    return check_usage(root, [FileChange(new, status, added)], base or {})


def reasons_of(result):
    return " | ".join(result.reasons)


IMPL = {**PKG, "mymod/impl.py": "def new_func():\n    return 1\n", "mymod/other.py": "VALUE = 1\n",
        "othermod/impl2.py": "def new_func():\n    return 2\n"}


class TestPublicNamesScope:
    """Only module-level and class-body definitions are public symbols."""

    def test_function_locals_are_not_public(self):
        assert public_names("def api():\n    total = 1\n    return total\n") == {"api": 1}

    def test_functions_nested_in_functions_are_not_public(self):
        assert set(public_names("def api():\n    def inner():\n        pass\n    return inner\n")) == {"api"}

    def test_classes_nested_in_functions_are_not_public(self):
        assert set(public_names("def api():\n    class Local:\n        pass\n    return Local\n")) == {"api"}

    def test_class_members_are_public(self):
        source = "class Box:\n    LIMIT = 3\n    def run(self):\n        pass\n    def _hidden(self):\n        pass\n"
        assert public_names(source) == {"Box": 1, "LIMIT": 2, "run": 3}

    def test_members_of_private_classes_are_not_public(self):
        assert public_names("class _Impl:\n    def go(self):\n        pass\n") == {}

    def test_annotated_assignment(self):
        assert public_names("LIMIT: int = 3\n_hidden: int = 4\nlabel: str\n") == {"LIMIT": 1, "label": 3}

    def test_definitions_inside_module_blocks_count(self):
        source = ("try:\n    import fast\nexcept ImportError:\n    def fallback():\n        pass\n"
                  "if True:\n    class Cond:\n        pass\n")
        assert set(public_names(source)) == {"fallback", "Cond"}

    def test_method_of_a_class_inside_a_function_is_not_public(self):
        assert set(public_names("def make():\n    class K:\n        def m(self):\n            pass\n    return K\n")) == {"make"}


class TestRootInsideGateDir:
    def test_callers_are_found_when_the_root_is_inside_simplicio_loop(self, gate_tmp):
        files = {**IMPL, "mymod/caller.py": "from mymod.impl import new_func\nnew_func()\n"}
        assert run_new(gate_tmp, files).status == PASS

    def test_a_file_that_is_not_called_still_fails_there(self, gate_tmp):
        result = run_new(gate_tmp, IMPL)
        assert result.status == FAIL
        assert "new_func" in reasons_of(result)

    def test_tests_under_the_gate_root_do_not_count(self, gate_tmp):
        files = {**IMPL, "tests/test_impl.py": "from mymod.impl import new_func\n\n\ndef test_it():\n    new_func()\n"}
        assert run_new(gate_tmp, files).status == FAIL

    @pytest.mark.parametrize("folder", ["node_modules/x", ".venv/lib", "venv/lib", "build", "dist", ".git/hooks",
                                        ".simplicio-loop/old", "__pycache__"])
    def test_callers_in_vendored_or_generated_dirs_do_not_count(self, gate_tmp, folder):
        files = {**IMPL, f"{folder}/caller.py": "from mymod.impl import new_func\nnew_func()\n"}
        assert run_new(gate_tmp, files).status == FAIL


CALLERS_THAT_COUNT = [
    "from mymod.impl import new_func\nnew_func()\n",
    "from mymod.impl import new_func as nf\nnf()\n",
    "from .impl import new_func\n",
    "from . import impl\nimpl.new_func()\n",
    "from mymod import impl\nimpl.new_func()\n",
    "from mymod import impl as m\nm.new_func()\n",
    "import mymod.impl\nmymod.impl.new_func()\n",
    "import mymod.impl as m\nm.new_func()\n",
]
CALLERS_THAT_DO_NOT = [
    "new_func = 3\nprint(new_func)\n",  # a loose name is not a reference to the module's symbol
    "def go(obj):\n    return obj.new_func()\n",  # an attribute of something unrelated
    "from othermod.impl2 import new_func\nnew_func()\n",  # same name, another module
    "import mymod.other as m\nm.new_func()\n",  # an alias of another module
    "from mymod import other\nother.new_func()\n",
    "import mymod.impl\nmymod.other.new_func()\n",  # imported impl but reached through another module
    "from mymod.impl import another_name\nanother_name()\n",  # the module is imported, the symbol is not
    "from mymod import impl\nimpl.another_name()\n",
]


class TestResolution:
    @pytest.mark.parametrize("caller", CALLERS_THAT_COUNT)
    def test_reference_that_resolves_to_the_module_counts(self, gate_tmp, caller):
        assert run_new(gate_tmp, {**IMPL, "mymod/caller.py": caller}).status == PASS

    @pytest.mark.parametrize("caller", CALLERS_THAT_DO_NOT)
    def test_reference_that_does_not_resolve_to_the_module_does_not_count(self, gate_tmp, caller):
        assert run_new(gate_tmp, {**IMPL, "mymod/caller.py": caller}).status == FAIL

    def test_src_layout_absolute_and_relative_imports(self, gate_tmp):
        files = {"src/pkg/__init__.py": "", "src/pkg/impl.py": "def new_func():\n    return 1\n"}
        callers = ("from pkg.impl import new_func\n", "from .impl import new_func\n", "from pkg import impl\nimpl.new_func()\n")
        for n, caller in enumerate(callers):
            sub = gate_tmp / f"case{n}"
            assert run_new(sub, {**files, "src/pkg/caller.py": caller}, new="src/pkg/impl.py").status == PASS

    def test_relative_import_two_levels_up(self, gate_tmp):
        files = {**PKG, "mymod/impl.py": "def new_func():\n    return 1\n", "mymod/sub/__init__.py": "",
                 "mymod/sub/caller.py": "from ..impl import new_func\n"}
        assert run_new(gate_tmp, files).status == PASS

    def test_symbol_defined_in_a_package_init_is_imported_from_the_package(self, gate_tmp):
        files = {"mymod/__init__.py": "def helper():\n    return 1\n", "main.py": "from mymod import helper\nhelper()\n"}
        assert run_new(gate_tmp, files, new="mymod/__init__.py").status == PASS

    def test_a_reference_from_a_test_next_to_a_real_one_still_passes(self, gate_tmp):
        files = {**IMPL, "mymod/caller.py": "from mymod.impl import new_func\n", "tests/test_x.py": "from mymod.impl import new_func\n"}
        assert run_new(gate_tmp, files).status == PASS

    def test_a_module_whose_name_only_ends_like_the_import_is_another_module(self, gate_tmp):
        files = {**PKG, "mymod/superimpl.py": "def new_func():\n    return 1\n", "mymod/caller.py": "from impl import new_func\nimport impl\n"}
        assert run_new(gate_tmp, files, new="mymod/superimpl.py").status == FAIL

    def test_import_in_a_script_dir_resolves_by_dotted_suffix(self, gate_tmp):
        files = {"scripts/tool.py": "def new_func():\n    return 1\n", "scripts/run.py": "from tool import new_func\nnew_func()\n"}
        assert run_new(gate_tmp, files, new="scripts/tool.py").status == PASS

    def test_relative_import_at_the_top_level(self, gate_tmp):
        files = {"mod.py": "def new_func():\n    return 1\n", "main.py": "from . import mod\nmod.new_func()\n"}
        assert run_new(gate_tmp, files, new="mod.py").status == PASS

    def test_callers_in_docs_python_do_not_count(self, gate_tmp):
        files = {**IMPL, "docs/example.py": "from mymod.impl import new_func\nnew_func()\n"}
        assert run_new(gate_tmp, files).status == FAIL

    def test_unparseable_neighbour_files_are_ignored(self, gate_tmp):
        files = {**IMPL, "mymod/broken.py": "def broken(\n", "mymod/caller.py": "from mymod.impl import new_func\n"}
        assert run_new(gate_tmp, files).status == PASS

    def test_undecodable_neighbour_files_are_ignored(self, gate_tmp):
        root = make_root(gate_tmp, {**IMPL, "mymod/caller.py": "from mymod.impl import new_func\n"})
        (root / "mymod" / "binary.py").write_bytes(b"\xff\xfe\x00bad")
        assert check_usage(root, [FileChange("mymod/impl.py", "A", (1, 2))], {}).status == PASS


class TestUnreadableNeighbours:
    @pytest.mark.parametrize("name", ["dead.py", "dead.json"])
    def test_a_dangling_symlink_is_ignored(self, gate_tmp, name):
        root = make_root(gate_tmp, {**IMPL, "mymod/caller.py": "from mymod.impl import new_func\n"})
        (root / name).symlink_to(root / "nowhere")
        assert check_usage(root, [FileChange("mymod/impl.py", "A", (1, 2))], {}).status == PASS
        (root / "mymod" / "caller.py").unlink()
        assert check_usage(root, [FileChange("mymod/impl.py", "A", (1, 2))], {}).status == FAIL


class TestSameFile:
    def test_helper_used_by_a_public_function_of_the_same_file(self, gate_tmp):
        files = {**PKG, "mymod/impl.py": "def helper():\n    return 1\n\n\ndef api():\n    return helper()\n",
                 "mymod/caller.py": "from mymod.impl import api\napi()\n"}
        assert run_new(gate_tmp, files).status == PASS

    def test_top_of_an_uncalled_chain_is_reported(self, gate_tmp):
        files = {**PKG, "mymod/impl.py": "def top():\n    return low()\n\n\ndef low():\n    return 1\n"}
        result = run_new(gate_tmp, files)
        assert result.status == FAIL
        assert "`top`" in reasons_of(result)

    def test_recursion_is_not_a_caller(self, gate_tmp):
        files = {**PKG, "mymod/impl.py": "def rec(n):\n    return rec(n - 1)\n"}
        assert run_new(gate_tmp, files).status == FAIL

    def test_main_guard_call_counts(self, gate_tmp):
        files = {**PKG, "mymod/impl.py": "def main():\n    return 0\n\n\nif __name__ == '__main__':\n    main()\n"}
        assert run_new(gate_tmp, files).status == PASS

    def test_constant_read_by_a_function_of_the_same_file(self, gate_tmp):
        files = {**PKG, "mymod/impl.py": "LIMIT = 3\n\n\ndef _cap(x):\n    return min(x, LIMIT)\n"}
        assert run_new(gate_tmp, files).status == PASS

    def test_constant_that_is_only_written_elsewhere_in_the_file_is_unused(self, gate_tmp):
        source = "LIMIT = 3\n\n\ndef reset():\n    global LIMIT\n    LIMIT = 0\n"
        files = {**PKG, "mymod/impl.py": source, "mymod/caller.py": "from mymod.impl import reset\nreset()\n"}
        result = run_new(gate_tmp, files)
        assert result.status == FAIL
        assert result.reasons == ("simbolo novo `LIMIT` (mymod/impl.py:1) sem chamador fora dos testes",)

    def test_attribute_with_the_name_in_the_same_file_counts(self, gate_tmp):
        source = "def helper():\n    return 1\n\n\ndef api(box):\n    return box.helper()\n"
        files = {**PKG, "mymod/impl.py": source, "mymod/caller.py": "from mymod.impl import api\napi(1)\n"}
        assert run_new(gate_tmp, files).status == PASS

    def test_constant_only_assigned_is_unused(self, gate_tmp):
        files = {**PKG, "mymod/impl.py": "LIMIT = 3\nLIMIT = LIMIT + 1\n"}
        assert run_new(gate_tmp, files).status == FAIL

    def test_property_setter_decorator_is_not_a_caller(self, gate_tmp):
        source = ("class Box:\n    def __init__(self):\n        self._w = 0\n\n    @property\n    def width(self):\n"
                  "        return self._w\n\n    @width.setter\n    def width(self, value):\n        self._w = value\n")
        files = {**PKG, "mymod/impl.py": source}
        result = run_new(gate_tmp, files, status="M", lines=tuple(range(5, 12)), base={"mymod/impl.py": frozenset(["Box"])})
        assert result.status == FAIL
        assert "width" in reasons_of(result)

    def test_a_function_locals_are_not_reported(self, gate_tmp):
        files = {**PKG, "mymod/impl.py": "def api():\n    total = 1\n    return total\n", "mymod/caller.py": "from mymod.impl import api\napi()\n"}
        assert run_new(gate_tmp, files).status == PASS


class TestMembers:
    ENGINE = "class Engine:\n    LIMIT = 3\n\n    def start(self):\n        return 1\n"

    def test_methods_of_a_new_class_are_covered_by_the_class(self, gate_tmp):
        files = {**PKG, "mymod/impl.py": self.ENGINE, "mymod/caller.py": "from mymod.impl import Engine\nEngine()\n"}
        result = run_new(gate_tmp, files)
        assert result.status == PASS
        assert result.measured["new_symbols"] == 3

    def test_unused_new_class_is_reported_once(self, gate_tmp):
        result = run_new(gate_tmp, {**PKG, "mymod/impl.py": self.ENGINE})
        assert result.status == FAIL
        assert result.reasons == ("simbolo novo `Engine` (mymod/impl.py:1) sem chamador fora dos testes",)

    def test_new_method_of_an_old_class_needs_an_attribute_reference(self, gate_tmp):
        source = "class Engine:\n    def old(self):\n        return 0\n\n    def start(self):\n        return 1\n"
        base = {"mymod/impl.py": frozenset(["Engine", "old"])}
        unused = run_new(gate_tmp, {**PKG, "mymod/impl.py": source}, status="M", lines=(5, 6), base=base)
        assert unused.status == FAIL
        assert "membro novo `Engine.start`" in reasons_of(unused)
        files = {**PKG, "mymod/impl.py": source, "mymod/caller.py": "def go(e):\n    e.start()\n"}
        assert run_new(gate_tmp / "ok", files, status="M", lines=(5, 6), base=base).status == PASS

    def test_new_method_called_through_self_in_the_same_file(self, gate_tmp):
        source = ("class Engine:\n    def old(self):\n        return self.start()\n\n    def start(self):\n        return 1\n")
        base = {"mymod/impl.py": frozenset(["Engine", "old"])}
        assert run_new(gate_tmp, {**PKG, "mymod/impl.py": source}, status="M", lines=(5, 6), base=base).status == PASS

    def test_new_method_is_not_called_by_itself(self, gate_tmp):
        source = "class Engine:\n    def old(self):\n        return 0\n\n    def start(self):\n        return self.start()\n"
        base = {"mymod/impl.py": frozenset(["Engine", "old"])}
        assert run_new(gate_tmp, {**PKG, "mymod/impl.py": source}, status="M", lines=(5, 6), base=base).status == FAIL

    def test_new_field_of_an_old_class_counts_when_passed_by_keyword(self, gate_tmp):
        source = "class Config:\n    retries: int = 1\n    timeout: int = 5\n"
        base = {"mymod/impl.py": frozenset(["Config", "retries"])}
        files = {**PKG, "mymod/impl.py": source, "mymod/caller.py": "from mymod.impl import Config\nConfig(timeout=3)\n"}
        assert run_new(gate_tmp, files, status="M", lines=(3,), base=base).status == PASS
        assert run_new(gate_tmp / "no", {**PKG, "mymod/impl.py": source}, status="M", lines=(3,), base=base).status == FAIL

    def test_new_method_of_a_private_class_is_not_checked(self, gate_tmp):
        source = "class _Impl:\n    def go(self):\n        return 1\n"
        assert run_new(gate_tmp, {**PKG, "mymod/impl.py": source, "mymod/user.py": "from mymod import impl\n"}).status == PASS

    def test_a_method_call_inside_a_test_does_not_count(self, gate_tmp):
        source = "class Engine:\n    def old(self):\n        return 0\n\n    def start(self):\n        return 1\n"
        base = {"mymod/impl.py": frozenset(["Engine", "old"])}
        files = {**PKG, "mymod/impl.py": source, "tests/test_e.py": "def test_e(e):\n    e.start()\n"}
        assert run_new(gate_tmp, files, status="M", lines=(5, 6), base=base).status == FAIL


class TestWhatIsNew:
    SOURCE = "def old_func():\n    return 1\n\n\ndef fresh():\n    return 2\n"

    def test_symbol_known_from_the_base_is_not_new_even_if_its_lines_changed(self, gate_tmp):
        base = {"mymod/impl.py": frozenset(["old_func", "fresh"])}
        result = run_new(gate_tmp, {**PKG, "mymod/impl.py": self.SOURCE}, status="M", lines=(1, 2, 5, 6), base=base)
        assert result.status == PASS
        assert result.measured["new_symbols"] == 0

    def test_symbol_on_lines_the_pr_did_not_add_is_not_new(self, gate_tmp):
        result = run_new(gate_tmp, {**PKG, "mymod/impl.py": self.SOURCE}, status="M", lines=(2,), base={"mymod/impl.py": frozenset()})
        assert result.status == PASS

    def test_new_symbol_on_added_lines_of_a_modified_file_is_checked(self, gate_tmp):
        base = {"mymod/impl.py": frozenset(["old_func"])}
        result = run_new(gate_tmp, {**PKG, "mymod/impl.py": self.SOURCE}, status="M", lines=(5, 6), base=base)
        assert result.status == FAIL
        assert result.reasons == ("simbolo novo `fresh` (mymod/impl.py:5) sem chamador fora dos testes",)

    def test_modified_file_missing_from_base_public_counts_every_added_symbol(self, gate_tmp):
        result = run_new(gate_tmp, {**PKG, "mymod/impl.py": self.SOURCE}, status="M", lines=(1, 2, 5, 6))
        assert result.status == FAIL
        assert "old_func" in reasons_of(result) and "fresh" in reasons_of(result)


REGISTERED = [
    "@app.route('/')\ndef new_func():\n    return 1\n",
    "@click.command()\ndef new_func():\n    return 1\n",
    "@pytest.fixture\ndef new_func():\n    return 1\n",
    "@registry.register('x')\nclass new_func:\n    pass\n",
    "@functools.lru_cache\n@app.task\ndef new_func():\n    return 1\n",
]
NEUTRAL = ["@functools.lru_cache(maxsize=1)", "@lru_cache", "@dataclass", "@dataclass(frozen=True)", "@overload", "@abstractmethod",
           "@wraps(print)", "@property", "@staticmethod", "@classmethod", "@cached_property", "@functools.cache",
           "@functools.total_ordering", "@functools.singledispatch", "@functools.partial"]


class TestRegistration:
    @pytest.mark.parametrize("source", REGISTERED)
    def test_decorator_that_hands_it_to_a_framework_counts_as_used(self, gate_tmp, source):
        assert run_new(gate_tmp, {**PKG, "mymod/impl.py": source}).status == PASS

    @pytest.mark.parametrize("decorator", NEUTRAL)
    def test_neutral_decorators_do_not_count_as_registration(self, gate_tmp, decorator):
        assert run_new(gate_tmp, {**PKG, "mymod/impl.py": f"{decorator}\ndef new_func():\n    return 1\n"}).status == FAIL

    def test_decorator_that_is_not_a_name_counts_as_registration(self, gate_tmp):
        source = "@registry[0]\ndef new_func():\n    return 1\n"
        assert run_new(gate_tmp, {**PKG, "mymod/impl.py": source}).status == PASS


class TestCitations:
    @pytest.mark.parametrize("text", ['"mymod.impl:new_func"', '"new_func"', '"mymod.impl.new_func"', "'a:new_func'"])
    def test_string_that_names_the_symbol_counts(self, gate_tmp, text):
        files = {**IMPL, "mymod/table.py": f"PLUGINS = [{text}]\n"}
        assert run_new(gate_tmp, files).status == PASS

    @pytest.mark.parametrize("text", ['"new_func_extra"', '"call new_func now"', '"xnew_func"', '"Xnew_func:"', '""'])
    def test_string_that_only_contains_the_name_does_not_count(self, gate_tmp, text):
        files = {**IMPL, "mymod/table.py": f"PLUGINS = [{text}]\n"}
        assert run_new(gate_tmp, files).status == FAIL

    def test_all_in_another_module_does_not_count(self, gate_tmp):
        assert run_new(gate_tmp, {**IMPL, "mymod/pub.py": '__all__ = ["new_func"]\n'}).status == FAIL
        assert run_new(gate_tmp / "t", {**IMPL, "mymod/pub.py": '__all__ = ("new_func",)\n__all__ += ["new_func"]\n'}).status == FAIL

    def test_all_in_the_defining_module_does_not_count(self, gate_tmp):
        files = {**PKG, "mymod/impl.py": '__all__: list[str] = ["new_func"]\n\n\ndef new_func():\n    return 1\n'}
        assert run_new(gate_tmp, files).status == FAIL

    def test_docstring_equal_to_the_name_does_not_count(self, gate_tmp):
        files = {**IMPL, "mymod/doc.py": '"""new_func"""\n\n\nclass K:\n    """mymod.new_func"""\n\n    def m(self):\n        "new_func"\n'}
        assert run_new(gate_tmp, files).status == FAIL

    def test_string_inside_the_symbols_own_body_does_not_count(self, gate_tmp):
        files = {**PKG, "mymod/impl.py": 'def new_func():\n    return "new_func"\n'}
        assert run_new(gate_tmp, files).status == FAIL

    def test_string_in_a_test_does_not_count(self, gate_tmp):
        assert run_new(gate_tmp, {**IMPL, "tests/test_t.py": 'NAMES = ["new_func"]\n'}).status == FAIL

    @pytest.mark.parametrize("config", ["pyproject.toml", "setup.cfg", "tox.ini", "ci.yml", "ci.yaml", "package.json", "conf/app.toml"])
    def test_name_in_a_config_file_counts(self, gate_tmp, config):
        files = {**IMPL, config: "[project.scripts]\nrun = mymod.impl:new_func\n"}
        assert run_new(gate_tmp, files).status == PASS

    @pytest.mark.parametrize("config", ["tests/data.json", "test/data.json", "docs/site.yaml", ".simplicio-loop/state.json", "node_modules/p/package.json",
                                        "notes.txt", "README.md", "mymod/data.csv"])
    def test_name_in_ignored_places_does_not_count(self, gate_tmp, config):
        assert run_new(gate_tmp, {**IMPL, config: "run = mymod.impl:new_func\n"}).status == FAIL

    @pytest.mark.parametrize("text", ["new_func_two", "xnew_func", "new_funcs", "NEW_FUNC", "new-func"])
    def test_config_needs_the_whole_word(self, gate_tmp, text):
        assert run_new(gate_tmp, {**IMPL, "pyproject.toml": f"run = {text}\n"}).status == FAIL

    def test_undecodable_config_file_does_not_break_the_check(self, gate_tmp):
        root = make_root(gate_tmp, IMPL)
        (root / "blob.json").write_bytes(b"\xff\xfe\x00 nothing here \xff")
        result = check_usage(root, [FileChange("mymod/impl.py", "A", (1, 2))], {})
        assert result.status == FAIL
        (root / "blob.json").write_bytes(b"\xff\xfe\x00 new_func \xff")
        assert check_usage(root, [FileChange("mymod/impl.py", "A", (1, 2))], {}).status == PASS

    def test_config_word_next_to_punctuation_counts(self, gate_tmp):
        assert run_new(gate_tmp, {**IMPL, "pyproject.toml": 'run = "a.b:new_func"\n'}).status == PASS
        assert run_new(gate_tmp / "j", {**IMPL, "app.json": '{"entry": "new_func"}'}).status == PASS


class TestModules:
    def test_new_module_whose_only_importer_is_a_test_fails(self, gate_tmp):
        files = {**PKG, "mymod/newmod.py": "_PRIVATE = 1\n", "tests/test_n.py": "from mymod import newmod\n"}
        result = run_new(gate_tmp, files, new="mymod/newmod.py")
        assert result.status == FAIL
        assert result.reasons == ("modulo novo `mymod/newmod.py` sem importador",)
        assert result.measured == {"new_symbols": 0, "new_modules": 1, "unused": ["mymod/newmod.py"]}

    @pytest.mark.parametrize("importer", ["from mymod import newmod\n", "import mymod.newmod\n", "from mymod.newmod import x\n",
                                          "from . import newmod\n", "from .newmod import x\n", "import mymod.newmod as n\n"])
    def test_new_module_with_a_real_importer_passes(self, gate_tmp, importer):
        files = {**PKG, "mymod/newmod.py": "_PRIVATE = 1\n", "mymod/user.py": importer}
        result = run_new(gate_tmp, files, new="mymod/newmod.py")
        assert result.status == PASS
        assert result.measured["new_modules"] == 1

    def test_importing_another_module_with_the_same_name_does_not_count(self, gate_tmp):
        files = {**PKG, "mymod/newmod.py": "_PRIVATE = 1\n", "mymod/user.py": "from elsewhere import newmod\nimport other.newmod\n"}
        assert run_new(gate_tmp, files, new="mymod/newmod.py").status == FAIL

    def test_a_top_level_module_does_not_import_itself(self, gate_tmp):
        assert run_new(gate_tmp, {"newmod.py": "import newmod\n_X = 1\n"}, new="newmod.py").status == FAIL

    def test_the_module_does_not_import_itself(self, gate_tmp):
        files = {**PKG, "mymod/newmod.py": "_PRIVATE = 1\nfrom mymod import newmod\n"}
        assert run_new(gate_tmp, files, new="mymod/newmod.py").status == FAIL

    @pytest.mark.parametrize("name", ["__init__.py", "__main__.py"])
    def test_new_init_and_main_need_no_importer(self, gate_tmp, name):
        result = run_new(gate_tmp, {"mymod/__init__.py": "", f"mymod/{name}": "_X = 1\n"}, new=f"mymod/{name}")
        assert result.status == PASS
        assert result.measured["new_modules"] == 0

    def test_modified_module_without_public_symbols_needs_no_importer(self, gate_tmp):
        files = {**PKG, "mymod/mod.py": "_PRIVATE = 2\n"}
        result = run_new(gate_tmp, files, new="mymod/mod.py", status="M", lines=(1,))
        assert result.status == PASS
        assert result.measured["new_modules"] == 0

    def test_new_empty_module_is_judged_by_its_importer(self, gate_tmp):
        assert run_new(gate_tmp, {**PKG, "mymod/empty.py": ""}, new="mymod/empty.py", lines=(1,)).status == FAIL
        files = {**PKG, "mymod/empty.py": "", "mymod/user.py": "from mymod import empty\n"}
        assert run_new(gate_tmp / "ok", files, new="mymod/empty.py", lines=(1,)).status == PASS

    def test_module_with_public_symbols_is_judged_by_symbol_not_by_importer(self, gate_tmp):
        files = {**PKG, "mymod/newmod.py": "def f():\n    return 1\n", "mymod/user.py": "from mymod.newmod import f\nf()\n"}
        result = run_new(gate_tmp, files, new="mymod/newmod.py")
        assert result.status == PASS
        assert result.measured["new_modules"] == 1


class TestResultShape:
    def test_fail_lists_the_unused_symbols_for_the_comment(self, gate_tmp):
        result = run_new(gate_tmp, IMPL)
        assert result.measured == {"new_symbols": 1, "new_modules": 1, "unused": ["mymod/impl.py:new_func"]}

    def test_pass_measures_new_symbols_and_modules(self, gate_tmp):
        files = {**IMPL, "mymod/caller.py": "from mymod.impl import new_func\n"}
        assert run_new(gate_tmp, files).measured == {"new_symbols": 1, "new_modules": 1, "unused": []}

    def test_deleted_files_are_skipped(self, gate_tmp):
        root = make_root(gate_tmp, PKG)
        result = check_usage(root, [FileChange("mymod/gone.py", "D", ())], {})
        assert result.status == PASS
        assert result.measured["new_symbols"] == 0

    def test_missing_file_is_an_error(self, gate_tmp):
        result = check_usage(make_root(gate_tmp, PKG), [FileChange("mymod/gone.py", "M", (1,))], {})
        assert result.status == ERROR
        assert "mymod/gone.py" in reasons_of(result)

    def test_undecodable_changed_file_is_an_error(self, gate_tmp):
        root = make_root(gate_tmp, PKG)
        (root / "mymod" / "bin.py").write_bytes(b"\xff\xfe\x00bad")
        result = check_usage(root, [FileChange("mymod/bin.py", "A", (1,))], {})
        assert result.status == ERROR
        assert "erro ao ler" in reasons_of(result)

    def test_syntax_error_in_changed_file_names_the_file(self, gate_tmp):
        result = run_new(gate_tmp, {**PKG, "mymod/bad.py": "def broken(\n"}, new="mymod/bad.py")
        assert result.status == ERROR
        assert "SyntaxError em mymod/bad.py" in reasons_of(result)

    def test_non_code_changes_are_ignored_next_to_code(self, gate_tmp):
        files = {**IMPL, "mymod/caller.py": "from mymod.impl import new_func\n", "docs/a.md": "# a\n", "tests/test_x.py": "def test_x():\n    pass\n"}
        root = make_root(gate_tmp, files)
        changes = [FileChange("docs/a.md", "A", (1,)), FileChange("tests/test_x.py", "A", (1, 2)), FileChange("mymod/impl.py", "A", (1, 2))]
        assert check_usage(root, changes, {}).status == PASS

    def test_every_code_file_of_the_pr_is_checked(self, gate_tmp):
        files = {**IMPL, "mymod/second.py": "def other_func():\n    return 1\n"}
        root = make_root(gate_tmp, files)
        result = check_usage(root, [FileChange("mymod/impl.py", "A", (1, 2)), FileChange("mymod/second.py", "A", (1, 2))], {})
        assert result.status == FAIL
        assert len(result.reasons) == 2
        assert result.measured["unused"] == ["mymod/impl.py:new_func", "mymod/second.py:other_func"]
