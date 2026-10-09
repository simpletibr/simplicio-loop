"""Check that new public symbols are referenced outside tests."""
from __future__ import annotations

import ast
import pathlib
from typing import Mapping, Sequence

from .diffs import FileChange, kind_of
from .model import CheckResult, PASS, FAIL, SKIPPED, ERROR


def public_names(source: str) -> dict[str, int]:
    """Extract public symbols from source code.

    Returns a dict mapping symbol name -> line number (1-indexed) of its definition.
    Ignores names starting with `_` (private) and dunders.

    Raises SyntaxError if the source is invalid.
    """
    names: dict[str, int] = {}
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            if not node.name.startswith("_"):
                names[node.name] = node.lineno
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                names[node.name] = node.lineno
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    names[target.id] = node.lineno

    return names


def check_usage(
    root: pathlib.Path,
    changes: Sequence[FileChange],
    base_public: Mapping[str, frozenset[str]],
) -> CheckResult:
    """Verify new public symbols have references outside tests.

    Args:
        root: Repository root (HEAD).
        changes: File changes from the PR.
        base_public: Mapping of path -> public symbols in the base branch.

    Returns:
        CheckResult with status PASS/FAIL/ERROR/SKIPPED.
    """
    code_changes = [c for c in changes if c.kind == "code"]

    if not code_changes:
        return CheckResult("usage", SKIPPED, ("sem codigo de producao alterado",))

    reasons: list[str] = []
    new_symbols_count = 0
    new_modules_count = 0

    for change in code_changes:
        path = pathlib.Path(change.path)
        full_path = root / path

        # Get the source code of the file
        try:
            source = full_path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError):
            if change.status == "D":
                continue  # Deleted files are OK
            return CheckResult("usage", ERROR, (f"nao conseguiu ler {path}",))
        except Exception as e:
            return CheckResult("usage", ERROR, (f"erro ao ler {path}: {e}",))

        # Parse the file
        try:
            current_names = public_names(source)
        except SyntaxError as e:
            return CheckResult("usage", ERROR, (f"SyntaxError em {path}: {e}",))

        # Determine which symbols are new
        base_names = base_public.get(change.path, frozenset())

        if change.status == "A":
            # New file: all symbols are new
            new_in_file = set(current_names.keys())
            is_module = path.name not in ("__init__.py", "__main__.py")
            if is_module and not current_names:
                # Empty module (no public symbols but is a module file)
                # This counts as a new module
                new_modules_count += 1
                # Check if it's imported
                if not _has_importer(root, change.path):
                    reasons.append(f"modulo novo `{change.path}` sem importador")
        else:
            # Modified file: only newly added symbols (by line number)
            new_in_file = set()
            for name, lineno in current_names.items():
                if name not in base_names and lineno in change.added:
                    new_in_file.add(name)

        new_symbols_count += len(new_in_file)

        # Check if new symbols are referenced outside tests
        for symbol in new_in_file:
            if not _is_used_outside_tests(root, change.path, symbol):
                lineno = current_names[symbol]
                reasons.append(f"simbolo novo `{symbol}` ({change.path}:{lineno}) sem chamador fora dos testes")

    if reasons:
        return CheckResult("usage", FAIL, tuple(reasons))

    return CheckResult("usage", PASS, measured={
        "new_symbols": new_symbols_count,
        "new_modules": new_modules_count,
        "unused": [],
    })


def _is_used_outside_tests(root: pathlib.Path, symbol_file: str, symbol_name: str) -> bool:
    """Check if a symbol is referenced (by name or via import) outside test files."""
    symbol_dir = pathlib.Path(symbol_file).parent

    # Scan all Python files in the repo (excluding tests, .git, venv, __pycache__)
    exclude_dirs = {".git", ".simplicio-loop", "venv", "__pycache__", ".pytest_cache", ".mypy_cache"}
    exclude_prefixes = ("test_", "conftest.py")

    for py_file in root.rglob("*.py"):
        if any(p in py_file.parts for p in exclude_dirs):
            continue

        rel_path = py_file.relative_to(root)
        if kind_of(str(rel_path)) == "test":
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # Parse and search for references
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        if _contains_reference(tree, symbol_name, symbol_file, py_file, root):
            return True

    return False


def _contains_reference(tree: ast.AST, symbol_name: str, symbol_file: str, py_file: pathlib.Path, root: pathlib.Path) -> bool:
    """Check if the AST contains a reference to the symbol, excluding self-references."""
    symbol_path = pathlib.Path(symbol_file)
    py_rel = py_file.relative_to(root)

    for node in ast.walk(tree):
        # Check for Name references (e.g., `symbol_name` in code)
        if isinstance(node, ast.Name) and node.id == symbol_name:
            # Exclude self-references in the same file
            if py_rel != symbol_path:
                return True

        # Check for Attribute references (e.g., `module.symbol_name`)
        if isinstance(node, ast.Attribute) and node.attr == symbol_name:
            if py_rel != symbol_path:
                return True

        # Check for ImportFrom (e.g., `from module import symbol_name`)
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == symbol_name or alias.asname == symbol_name:
                    if py_rel != symbol_path:
                        return True

        # Check for Import (e.g., `import a.b.mod` where mod is the file)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if symbol_file.replace("/", ".").replace(".py", "") in alias.name:
                    return True

    return False


def _has_importer(root: pathlib.Path, module_file: str) -> bool:
    """Check if a new module is imported in non-test code."""
    module_path = pathlib.Path(module_file)
    module_name = module_path.stem  # e.g., "newmod" from "mymod/newmod.py"
    module_dot_name = module_file.replace("/", ".").replace(".py", "")

    exclude_dirs = {".git", ".simplicio-loop", "venv", "__pycache__", ".pytest_cache", ".mypy_cache"}

    for py_file in root.rglob("*.py"):
        if any(p in py_file.parts for p in exclude_dirs):
            continue

        rel_path = py_file.relative_to(root)
        if kind_of(str(rel_path)) == "test":
            continue

        # Skip the module file itself
        if rel_path == module_path:
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except Exception:
            continue

        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            # Check for `from a.b import mod` or `from .mod import x`
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == module_name or alias.asname == module_name:
                        return True

            # Check for `import a.b.mod`
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if module_dot_name in alias.name or alias.name.endswith(module_name):
                        return True

    return False
