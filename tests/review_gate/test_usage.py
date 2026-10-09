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
