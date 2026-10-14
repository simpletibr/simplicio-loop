"""relation_id stays byte-identical to the json.dumps identity it replaced (#1631): ids are persisted in artifacts."""

from __future__ import annotations

import hashlib
import json
import unittest
from typing import Any

from simplicio_mapper.relations import relation_id, relation_identity


def _legacy_relation_id(edge: dict[str, Any]) -> str:
    encoded = json.dumps(
        relation_identity(edge), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_CALL = {
    "type": "calls",
    "source_file": "src/app.py",
    "source_symbol": "pkg.run",
    "target_file": "src/util.py",
    "target_symbol": "util.helper",
    "line": 12,
    "target_candidates": ["src/util.py::helper"],
    "evidence_class": "lexical_unique",
    "resolution_status": "resolved",
    "provenance": {"method": "symbol-name-lookup"},
    "confidence": None,
}

_EDGES: list[dict[str, Any]] = [
    dict(_CALL),
    {**_CALL, "source_symbol": "módulo.função_ç", "target_symbol": "🙂.run", "target_candidates": ["ß/€.py::x", "日本.py::y"]},
    {**_CALL, "source_symbol": None, "target_symbol": None, "line": None, "type": None, "import": None},
    {**_CALL, "source_file": r"src\pkg\mod.py", "target_file": r"lib\x.py", "import": r"from a\b import c"},
    {**_CALL, "source_file": "./a/b.py", "target_file": "././c.py"},
    {**_CALL, "source_file": "/abs/path.py", "target_file": "  "},
    {**_CALL, "source_file": "", "target_file": None},
    {**_CALL, "source_file": None, "target_file": "src/util.py"},
    {**_CALL, "import": 'quote"and\\back', "source_symbol": "tab\tnl\n", "target_symbol": "\x00\x1f\x7f  "},
    {**_CALL, "target_candidates": []},
    {**_CALL, "target_candidates": None},
    {k: v for k, v in _CALL.items() if k != "target_candidates"},
    {**_CALL, "target_candidates": ("a.py::f", "b.py::f")},
    {**_CALL, "target_candidates": ["a.py::f", None, 3]},
    {**_CALL, "target_candidates": {"b": 1, "a": [2, None]}},
    {**_CALL, "line": 0},
    {**_CALL, "line": -1},
    {**_CALL, "line": True},
    {**_CALL, "line": 3.0},
    {**_CALL, "line": 2**70},
    {**_CALL, "line": "7"},
    {**_CALL, "type": "imports", "target_symbol": None, "import": "from x import y"},
    {**_CALL, "type": ""},
]


class RelationIdEncodingTests(unittest.TestCase):
    def test_relation_id_matches_legacy_json_identity(self) -> None:
        for edge in _EDGES:
            with self.subTest(edge=edge):
                self.assertEqual(relation_id(edge), _legacy_relation_id(edge))
