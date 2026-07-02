"""Unit tests for simplicio_mapper.toon (TOON encoder/decoder, issue #144).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.toon import decode_toon, encode_toon  # noqa: E402


class ToonRoundTripTest(unittest.TestCase):
    """decode_toon(encode_toon(x)) == x for a range of realistic fixtures."""

    def _assert_round_trip(self, value: object) -> None:
        encoded = encode_toon(value)
        self.assertIsInstance(encoded, str)
        decoded = decode_toon(encoded)
        self.assertEqual(decoded, value)

    def test_root_scalar_values(self) -> None:
        for value in (42, -3, 3.5, 0.0, True, False, None, "hello", ""):
            self._assert_round_trip(value)

    def test_scalar_strings_needing_quotes(self) -> None:
        for value in (
            "42",
            "true",
            "false",
            "null",
            "a,b",
            "a:b",
            "line1\nline2",
            "  leading-space",
            "trailing-space  ",
            '"already-quoted"',
            "{looks-like-json}",
            "[looks-like-json]",
        ):
            self._assert_round_trip(value)

    def test_flat_object(self) -> None:
        value = {"name": "mapper", "version": 3, "active": True, "notes": None}
        self._assert_round_trip(value)
        encoded = encode_toon(value)
        self.assertIn("name: mapper", encoded)
        self.assertIn("version: 3", encoded)
        self.assertIn("active: true", encoded)
        self.assertIn("notes: null", encoded)

    def test_nested_object(self) -> None:
        value = {
            "project": {
                "name": "simplicio-mapper",
                "meta": {"stack": "python", "confidence": 0.92},
            },
            "count": 2,
        }
        self._assert_round_trip(value)
        encoded = encode_toon(value)
        self.assertIn("project:\n  name: simplicio-mapper", encoded)
        self.assertIn("meta:\n    stack: python", encoded)

    def test_uniform_array_of_objects_uses_tabular_block(self) -> None:
        value = {
            "endpoints": [
                {"method": "GET", "path": "/users", "auth": True},
                {"method": "POST", "path": "/users", "auth": False},
                {"method": "DELETE", "path": "/users/1", "auth": True},
            ]
        }
        self._assert_round_trip(value)
        encoded = encode_toon(value)
        self.assertIn("endpoints[3]{method,path,auth}:", encoded)
        self.assertIn("GET,/users,true", encoded)
        # Tabular form should be materially shorter than compact JSON for
        # the same data (no repeated keys per row).
        import json

        self.assertLess(len(encoded), len(json.dumps(value)))

    def test_scalar_array_inline(self) -> None:
        value = {"tags": ["fast", "python", "cli"], "scores": [1, 2, 3]}
        self._assert_round_trip(value)
        encoded = encode_toon(value)
        self.assertIn("tags[3]: fast,python,cli", encoded)
        self.assertIn("scores[3]: 1,2,3", encoded)

    def test_empty_array_and_object_fallback(self) -> None:
        value = {"items": [], "meta": {}}
        self._assert_round_trip(value)
        encoded = encode_toon(value)
        self.assertIn("items: []", encoded)
        self.assertIn("meta: {}", encoded)

    def test_root_array_of_uniform_objects(self) -> None:
        value = [
            {"file": "a.py", "lines": 10},
            {"file": "b.py", "lines": 42},
        ]
        self._assert_round_trip(value)
        encoded = encode_toon(value)
        self.assertTrue(encoded.startswith("[2]{file,lines}:"))

    def test_root_array_of_scalars(self) -> None:
        value = ["a", "b", "c"]
        self._assert_round_trip(value)
        self.assertEqual(encode_toon(value), "[3]: a,b,c")

    def test_root_empty_array_and_object(self) -> None:
        self._assert_round_trip([])
        self._assert_round_trip({})
        self.assertEqual(encode_toon([]), "[]")
        self.assertEqual(encode_toon({}), "{}")

    def test_deeply_nested_realistic_fixture(self) -> None:
        value = {
            "schema": "simplicio.project-map/v1",
            "root": "/repo",
            "modules": [
                {"name": "cli", "files": 3, "layer": "interface"},
                {"name": "mapper", "files": 5, "layer": "core"},
            ],
            "meta": {
                "stack": "python",
                "confidence": 0.87,
                "notes": None,
                "flags": ["incremental", "silent"],
            },
            "warnings": [],
        }
        self._assert_round_trip(value)


class ToonNonUniformFallbackTest(unittest.TestCase):
    """Arrays that cannot be tabular must fall back to compact JSON."""

    def test_differing_keys_falls_back_to_json(self) -> None:
        value = {
            "items": [
                {"a": 1, "b": 2},
                {"a": 3, "c": 4},
            ]
        }
        encoded = encode_toon(value)
        self.assertIn('items: [{"a":1,"b":2},{"a":3,"c":4}]', encoded)
        self.assertEqual(decode_toon(encoded), value)

    def test_mixed_types_falls_back_to_json(self) -> None:
        value = {"items": [1, "two", {"three": 3}]}
        encoded = encode_toon(value)
        self.assertIn("items: [1,", encoded)
        self.assertEqual(decode_toon(encoded), value)

    def test_nested_containers_in_rows_falls_back_to_json(self) -> None:
        value = {
            "items": [
                {"id": 1, "tags": ["a", "b"]},
                {"id": 2, "tags": ["c"]},
            ]
        }
        encoded = encode_toon(value)
        # Uniform keys, but nested list values disqualify the tabular shape.
        self.assertNotIn("items[2]{", encoded)
        self.assertEqual(decode_toon(encoded), value)

    def test_root_non_uniform_array_falls_back_to_json(self) -> None:
        value = [{"a": 1}, {"b": 2}]
        encoded = encode_toon(value)
        self.assertEqual(encoded, '[{"a":1},{"b":2}]')
        self.assertEqual(decode_toon(encoded), value)


if __name__ == "__main__":
    unittest.main()
