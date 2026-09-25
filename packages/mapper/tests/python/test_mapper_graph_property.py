"""Property-based regression coverage for the symbol-index line-number bug
(see ``SymbolLineNumberBlankLinesTest`` in ``test_mapper_graph.py`` and the
comment above the fix in ``simplicio_mapper/mapper/graph.py::_symbol_definitions_for_file``).

The bug: every language pattern in ``_symbol_definitions_for_file`` anchors on
``^\\s*<keyword>`` with ``re.MULTILINE``. Because ``\\s`` matches newlines
too, a definition preceded by blank lines let ``^`` anchor at an earlier
blank line and let ``\\s*`` swallow the intervening newlines -- shifting the
reported line number to that earlier blank line instead of the real
``def``/``class`` line. That corrupted every consumer of the reported line
(``ask callers/callees/tests-for``, call-graph self-call filtering, etc.).

Rather than hand-picking a couple of fixed source snippets (as the existing
unit tests do), this uses Hypothesis to generate many combinations of
leading blank lines, comment lines, and decorators before a ``def``/``class``
and cross-checks the reported line against Python's own ``ast`` module --
an oracle independent of the regex-based implementation under test. This is
a proof of concept for property-based testing on the parsing/transformation
surface named in the DoD framework (see ``DOD.md`` Layer 2); it does not aim
to cover the whole module.

Run with: python3 -m pytest tests/python/test_mapper_graph_property.py -q
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.graph import _symbol_definitions_for_file  # noqa: E402
from simplicio_mapper.models import ProjectFile  # noqa: E402

_VALID_NAMES = ["greet", "handler", "compute", "run_task", "build_widget", "helper_fn"]


def _make_project_file(text: str) -> ProjectFile:
    return ProjectFile(
        path="src/app.py",
        language="python",
        size_bytes=len(text),
        last_modified="",
        file_hash="",
        git_status="",
        roles=[],
        imports=[],
        exports=[],
    )


def _source_variations():
    return st.fixed_dictionaries(
        {
            "leading_blank_lines": st.integers(min_value=0, max_value=4),
            "comment_lines": st.integers(min_value=0, max_value=3),
            "decorated": st.booleans(),
            "kind": st.sampled_from(["function", "class"]),
            "name": st.sampled_from(_VALID_NAMES),
            "docstring": st.booleans(),
        }
    )


def _build_source(spec: dict) -> str:
    lines: list[str] = []
    if spec["docstring"]:
        lines.append('"""Sample module docstring."""')
        lines.append("")
    lines.extend([""] * spec["leading_blank_lines"])
    for i in range(spec["comment_lines"]):
        lines.append(f"# comment line {i}")
    if spec["decorated"]:
        lines.append("@staticmethod")
    if spec["kind"] == "function":
        lines.append(f"def {spec['name']}():")
        lines.append("    return 1")
    else:
        lines.append(f"class {spec['name']}:")
        lines.append("    pass")
    lines.append("")
    return "\n".join(lines) + "\n"


class SymbolLineMatchesAstAcrossFormattingVariationsTest(unittest.TestCase):
    """Hypothesis property: for any combination of leading blank lines,
    comments, decorators, and an optional module docstring, the line number
    ``_symbol_definitions_for_file`` reports for a top-level ``def``/``class``
    must equal the line Python's own ``ast`` module reports for that same
    node -- the independent oracle for "the real line of the definition".

    Subclasses ``unittest.TestCase`` (Hypothesis supports this directly) so
    the property runs under both this project's test runners:
    ``python3 -m unittest discover -s tests/python`` and ``pytest``.
    """

    @settings(max_examples=60, deadline=None)
    @given(_source_variations())
    def test_reported_line_matches_ast_oracle(self, spec: dict) -> None:
        text = _build_source(spec)

        tree = ast.parse(text)
        oracle: dict[str, int] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                oracle[node.name] = node.lineno

        self.assertIn(
            spec["name"],
            oracle,
            f"test setup bug: ast did not find {spec['name']!r} in generated source:\n{text}",
        )

        file = _make_project_file(text)
        reported = {
            item["name"]: item["line"] for item in _symbol_definitions_for_file(file, text)
        }

        self.assertIn(
            spec["name"],
            reported,
            f"_symbol_definitions_for_file did not find {spec['name']!r} in:\n{text}",
        )
        self.assertEqual(
            reported[spec["name"]],
            oracle[spec["name"]],
            f"line mismatch for {spec['name']!r}: reported={reported[spec['name']]} "
            f"ast_oracle={oracle[spec['name']]}\nsource:\n{text}",
        )


if __name__ == "__main__":
    unittest.main()
