"""Static look at the test functions of a module: which ones can fail, and which ones nobody runs (Parte de #1649).

A test is VACUOUS when nothing in it can fail: no `assert`, or only asserts of a constant that is true (`assert True`,
`assert 1`, `assert "x"`, `assert 1 == 1`, `assert (x, "message")`), a body of `pass` / `...` / a docstring, or a body that
only calls `print`. These count as something that can fail:
- an `assert` whose test reads a name, an attribute, a call or any other non-constant (also a constant that is false);
- a `raise` statement;
- a call named `assert*` (`self.assertEqual`, `mock.assert_called_once`), `raises`, `warns`, `fail`, or starting with `check`,
  `verify`, `expect`, `ensure`, `validate` (an imported helper that asserts for the test);
- a call to a function of the same module whose body can fail (any depth).

A test is SKIPPED when something stops it before it runs: a `skip` / `xfail` / `expectedFailure` decorator (on the function, on
its class, or `pytestmark` of the module), a `skipif` / `skipIf` whose condition is a true constant, or a top-level
`pytest.skip()` / `pytest.xfail()` / `self.skipTest()` in its body. A skipped test is no evidence.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

_SKIP_NAMES = frozenset({"skip", "xfail", "expectedFailure"})
_COND_SKIP_NAMES = frozenset({"skipif", "skipIf", "skipUnless"})
_FAIL_CALLS = frozenset({"raises", "warns", "fail", "deprecated_call"})
_FAIL_PREFIXES = ("assert", "check", "verify", "expect", "ensure", "validate")
_CONSTANT_NODES = (ast.Constant, ast.Compare, ast.BoolOp, ast.UnaryOp, ast.Tuple, ast.List, ast.Set, ast.Dict, ast.cmpop,
                   ast.boolop, ast.unaryop, ast.expr_context)


@dataclass(frozen=True)
class TestFunc:
    __test__ = False  # not a pytest class
    qualname: str  # `name` or `Class::name`
    first: int  # first line (the first decorator counts)
    last: int
    vacuous: bool
    skipped: bool
    terms: str  # name, docstring, identifiers and strings of the body, one text

    @property
    def usable(self) -> bool:
        """Whether the test can be evidence: it runs and it can fail."""
        return not self.vacuous and not self.skipped


def is_test_class(node: ast.ClassDef) -> bool:
    """A class pytest collects: `Test*`, or a `unittest.TestCase` (any name)."""
    return node.name.startswith("Test") or any(_last(base) == "TestCase" for base in node.bases)


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _last(node: ast.AST) -> str:
    return _dotted(node).rsplit(".", 1)[-1]


def _constant_truthy(test: ast.expr) -> bool:
    """Whether an assert can never fail: a non-empty tuple, or an expression of constants only that is true."""
    if isinstance(test, ast.Tuple) and test.elts:
        return True
    if not all(isinstance(n, _CONSTANT_NODES) for n in ast.walk(test)):
        return False
    try:  # constants and comparisons only: no name, no call, no arithmetic is evaluated here
        return bool(eval(compile(ast.Expression(test), "<assert>", "eval"), {"__builtins__": {}}))  # noqa: S307
    except Exception:  # noqa: BLE001
        return False


def _truthy(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and bool(node.value)


def _skips(decorators: list[ast.expr]) -> bool:
    for deco in decorators:
        name = _last(deco)
        if name in _SKIP_NAMES:
            return True
        if name in _COND_SKIP_NAMES and isinstance(deco, ast.Call) and deco.args:
            truthy = _truthy(deco.args[0])
            if truthy == (name != "skipUnless"):
                return True
    return False


def _marks_skip(value: ast.expr) -> bool:
    items = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
    return _skips(list(items))


def _stops_itself(body: list[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and _last(stmt.value) in {"skip", "xfail", "skipTest"}:
            return True
    return False


def _checking_calls(tree: ast.AST) -> set[str]:
    """Names of the functions of the module whose body can fail, to the fixed point."""
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    known: set[str] = set()
    for _ in range(len(funcs) + 1):
        grown = {f.name for f in funcs if f.name not in known and _can_fail(f, known)}
        if not grown:
            break
        known |= grown
    return known


def _can_fail(node: ast.AST, helpers: set[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assert) and not _constant_truthy(sub.test):
            return True
        if isinstance(sub, ast.Raise):
            return True
        if isinstance(sub, ast.Call):
            name = _last(sub)
            if name in _FAIL_CALLS or name in helpers or name.lower().startswith(_FAIL_PREFIXES):
                return True
    return False


def _terms(node: ast.AST) -> str:
    out: list[str] = [getattr(node, "name", "")]
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.append(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.append(sub.attr)
        elif isinstance(sub, ast.arg):
            out.append(sub.arg)
        elif isinstance(sub, ast.keyword) and sub.arg:
            out.append(sub.arg)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(sub.name)
    return " ".join(out)


def _span(node: ast.AST) -> tuple[int, int]:
    first = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", ()))])
    return first, node.end_lineno


def has_check(source: str) -> bool:
    """Whether some statement of the module (lines of a test that are not a whole function) can fail. Raises SyntaxError."""
    tree = ast.parse(source)
    return _can_fail(tree, _checking_calls(tree))


def analyze(source: str) -> list[TestFunc]:
    """The test functions of `source` (module level and `Test*` classes), in order. Raises SyntaxError on a module that does not parse."""
    tree = ast.parse(source)
    helpers = _checking_calls(tree)
    module_skip = any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
                      and _marks_skip(n.value) for n in tree.body)
    found: list[TestFunc] = []

    def visit(body: list[ast.stmt], prefix: str, skipped: bool) -> None:
        class_skip = skipped or any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
                                    and _marks_skip(n.value) for n in body)
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                first, last = _span(node)
                stopped = class_skip or _skips(node.decorator_list) or _stops_itself(node.body)
                found.append(TestFunc(prefix + node.name, first, last, not _can_fail(node, helpers), stopped, _terms(node)))
            elif isinstance(node, ast.ClassDef) and is_test_class(node):
                visit(node.body, f"{prefix}{node.name}::", class_skip or _skips(node.decorator_list))

    visit(tree.body, "", module_skip)
    return found
