"""LibCST helpers shared by deterministic Python scratch executors."""

from __future__ import annotations


class LibCSTUnavailable(RuntimeError):
    """Raised when libcst is not installed in the active environment."""


def _cst():
    try:
        import libcst as cst
        from libcst.helpers import get_full_name_for_node
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised by deployments without libcst
        raise LibCSTUnavailable("libcst is not installed") from exc
    return cst, get_full_name_for_node


def format_module(source: str) -> str:
    """Round-trip source through LibCST so generated Python stays concrete-syntax valid."""
    cst, _ = _cst()
    return cst.parse_module(source or "\n").code


def ensure_from_import(source: str, module: str, name: str) -> str:
    """Ensure ``from <module> import <name>`` exists, preserving existing import blocks."""
    cst, get_full_name_for_node = _cst()

    class ImportTransformer(cst.CSTTransformer):
        changed = False

        def leave_ImportFrom(self, original_node, updated_node):  # type: ignore[no-untyped-def]
            if original_node.module is None:
                return updated_node
            if get_full_name_for_node(original_node.module) != module:
                return updated_node
            names = updated_node.names
            if not isinstance(names, tuple):
                return updated_node
            imported = {
                get_full_name_for_node(alias.name) for alias in names if get_full_name_for_node(alias.name)
            }
            if "*" in imported or name in imported:
                self.changed = True
                return updated_node
            if names:
                *head, last = names
                names = (
                    *head,
                    last.with_changes(comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" "))),
                    cst.ImportAlias(cst.Name(name)),
                )
            else:
                names = (cst.ImportAlias(cst.Name(name)),)
            self.changed = True
            return updated_node.with_changes(names=names)

    tree = cst.parse_module(source or "\n")
    transformer = ImportTransformer()
    updated = tree.visit(transformer)
    if transformer.changed:
        return updated.code

    import_stmt = cst.parse_statement(f"from {module} import {name}\n")
    body = list(updated.body)
    insert_at = _import_insert_index(body, cst)
    body.insert(insert_at, import_stmt)
    return updated.with_changes(body=body).code


def append_statement_to_class(source: str, class_name: str, statement: str) -> str | None:
    """Append a concrete statement to a class body using LibCST."""
    cst, _ = _cst()

    class ClassAppender(cst.CSTTransformer):
        changed = False

        def leave_ClassDef(self, original_node, updated_node):  # type: ignore[no-untyped-def]
            if original_node.name.value != class_name:
                return updated_node
            if not isinstance(updated_node.body, cst.IndentedBlock):
                return updated_node
            next_statement = cst.parse_statement(statement)
            body = [item for item in updated_node.body.body if not _is_pass(item, cst)]
            body.append(next_statement)
            self.changed = True
            return updated_node.with_changes(body=updated_node.body.with_changes(body=tuple(body)))

    tree = cst.parse_module(source or "\n")
    transformer = ClassAppender()
    updated = tree.visit(transformer)
    return updated.code if transformer.changed else None


def append_module_statements(source: str, statements: str) -> str:
    """Append one or more top-level statements to a module using LibCST."""
    cst, _ = _cst()
    tree = cst.parse_module(source or "\n")
    additions = list(cst.parse_module(statements).body)
    body = [*tree.body, *additions]
    return tree.with_changes(body=body).code


def insert_module_statement_after_imports(source: str, statement: str) -> str:
    """Insert a top-level statement immediately after imports/docstring."""
    cst, _ = _cst()
    tree = cst.parse_module(source or "\n")
    body = list(tree.body)
    body.insert(_import_insert_index(body, cst), cst.parse_statement(statement))
    return tree.with_changes(body=body).code


def _import_insert_index(body, cst) -> int:  # type: ignore[no-untyped-def]
    insert_at = 0
    for index, statement in enumerate(body):
        if _is_docstring(statement, cst) or _is_import(statement, cst):
            insert_at = index + 1
            continue
        break
    return insert_at


def _is_docstring(statement, cst) -> bool:  # type: ignore[no-untyped-def]
    if not isinstance(statement, cst.SimpleStatementLine) or len(statement.body) != 1:
        return False
    expr = statement.body[0]
    return isinstance(expr, cst.Expr) and isinstance(expr.value, cst.SimpleString)


def _is_import(statement, cst) -> bool:  # type: ignore[no-untyped-def]
    return isinstance(statement, cst.SimpleStatementLine) and any(
        isinstance(item, (cst.Import, cst.ImportFrom)) for item in statement.body
    )


def _is_pass(statement, cst) -> bool:  # type: ignore[no-untyped-def]
    return isinstance(statement, cst.SimpleStatementLine) and any(
        isinstance(item, cst.Pass) for item in statement.body
    )
