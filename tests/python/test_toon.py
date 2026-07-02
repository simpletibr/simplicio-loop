"""Unit tests for simplicio_mapper.toon (TOON encoder/decoder, issues #144, #148).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from toon_contract_runner import strict_equal  # noqa: E402

from simplicio_mapper.toon import (  # noqa: E402
    TOONDecodeError,
    decode_toon,
    encode_toon,
    encode_toon_with_report,
)


class ToonRoundTripTest(unittest.TestCase):
    """decode_toon(encode_toon(x)) == x for a range of realistic fixtures."""

    def _assert_round_trip(self, value: object) -> None:
        encoded = encode_toon(value)
        self.assertIsInstance(encoded, str)
        decoded = decode_toon(encoded)
        self.assertEqual(decoded, value)
        # Type-strict on top of plain ``==`` — Python's ``True == 1`` would
        # let a bool-shortened-to-int mutation slip past a naive check
        # (autoresearch pilot finding, issue #151). See
        # toon_contract_runner.strict_equal's docstring.
        self.assertTrue(strict_equal(decoded, value), f"strict_equal failed for {value!r} -> {decoded!r}")

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

    def test_dict_valued_cells_still_fall_back_to_json(self) -> None:
        value = {
            "items": [
                {"id": 1, "meta": {"a": 1}},
                {"id": 2, "meta": {"b": 2}},
            ]
        }
        encoded = encode_toon(value)
        # Uniform keys, but a dict-valued cell disqualifies the tabular shape.
        self.assertNotIn("items[2]{", encoded)
        self.assertEqual(decode_toon(encoded), value)

    def test_list_of_lists_cells_still_fall_back_to_json(self) -> None:
        value = {
            "items": [
                {"id": 1, "grid": [[1, 2], [3, 4]]},
                {"id": 2, "grid": [[5, 6]]},
            ]
        }
        encoded = encode_toon(value)
        # A list-of-lists cell (not a list of scalars) disqualifies tabular.
        self.assertNotIn("items[2]{", encoded)
        self.assertEqual(decode_toon(encoded), value)

    def test_root_non_uniform_array_falls_back_to_json(self) -> None:
        value = [{"a": 1}, {"b": 2}]
        encoded = encode_toon(value)
        self.assertEqual(encoded, '[{"a":1},{"b":2}]')
        self.assertEqual(decode_toon(encoded), value)


class ToonListCellTabularTest(unittest.TestCase):
    """Cells whose value is a list of scalars still take the tabular path
    (issue #148 — this is the fix for the measured 4.5-8.4% vs ~40% gap:
    the mapper's real arrays are ``files[].exports/imports/roles`` /
    ``items[].tags``, i.e. exactly this shape)."""

    def _assert_round_trip(self, value: object) -> None:
        encoded = encode_toon(value)
        self.assertEqual(decode_toon(encoded), value)

    def test_list_of_scalars_cell_uses_tabular_block(self) -> None:
        value = {
            "files": [
                {"path": "a.py", "exports": ["run", "main"], "imports": []},
                {"path": "b.py", "exports": [], "imports": ["os", "sys"]},
            ]
        }
        self._assert_round_trip(value)
        encoded = encode_toon(value)
        self.assertIn("files[2]{path,exports,imports}:", encoded)
        self.assertIn("a.py,[run,main],[]", encoded)
        self.assertIn("b.py,[],[os,sys]", encoded)

    def test_list_of_scalars_cell_with_quoting_round_trips(self) -> None:
        value = {
            "items": [
                {"id": 1, "tags": ["needs,comma", "needs:colon", "true"]},
                {"id": 2, "tags": []},
            ]
        }
        self._assert_round_trip(value)
        encoded = encode_toon(value)
        self.assertIn("items[2]{id,tags}:", encoded)

    def test_root_array_with_list_cell_uses_tabular_block(self) -> None:
        value = [
            {"file": "a.py", "roles": ["entry", "cli"]},
            {"file": "b.py", "roles": []},
        ]
        self._assert_round_trip(value)
        encoded = encode_toon(value)
        self.assertTrue(encoded.startswith("[2]{file,roles}:"))

    def test_single_element_scalar_list_cell_not_ambiguous_with_scalar(self) -> None:
        # A one-element list cell ([1]) must decode as a list, not as the
        # bare scalar int 1 (loop's known [1]-ambiguity bug class, #149).
        value = {"items": [{"id": 1, "tags": [1]}]}
        self._assert_round_trip(value)


class ToonFallbackReportTest(unittest.TestCase):
    """``encode_toon_with_report`` surfaces which arrays fell back and why
    (issue #148 — previously 100% silent)."""

    def test_no_fallbacks_for_fully_tabular_payload(self) -> None:
        value = {"files": [{"path": "a.py", "tags": ["x"]}]}
        _text, fallbacks = encode_toon_with_report(value)
        self.assertEqual(fallbacks, [])

    def test_differing_keys_reports_reason_and_path(self) -> None:
        value = {"items": [{"a": 1}, {"b": 2}]}
        _text, fallbacks = encode_toon_with_report(value)
        self.assertEqual(fallbacks, [{"path": "$.items", "reason": "differing_keys"}])

    def test_mixed_types_reports_reason(self) -> None:
        value = {"items": [1, "two", {"three": 3}]}
        _text, fallbacks = encode_toon_with_report(value)
        self.assertEqual(fallbacks, [{"path": "$.items", "reason": "mixed_types"}])

    def test_nested_dict_value_reports_nested_containers_reason(self) -> None:
        value = {"items": [{"id": 1, "meta": {"a": 1}}, {"id": 2, "meta": {"b": 2}}]}
        _text, fallbacks = encode_toon_with_report(value)
        self.assertEqual(fallbacks, [{"path": "$.items", "reason": "nested_containers"}])

    def test_nested_path_reported_for_fallback_inside_object(self) -> None:
        value = {"meta": {"items": [{"a": 1}, {"b": 2}]}}
        _text, fallbacks = encode_toon_with_report(value)
        self.assertEqual(fallbacks, [{"path": "$.meta.items", "reason": "differing_keys"}])

    def test_root_array_fallback_reports_root_path(self) -> None:
        value = [{"a": 1}, {"b": 2}]
        _text, fallbacks = encode_toon_with_report(value)
        self.assertEqual(fallbacks, [{"path": "$", "reason": "differing_keys"}])

    def test_encode_toon_ignores_report_but_stays_identical(self) -> None:
        value = {"items": [{"a": 1}, {"b": 2}]}
        text_with_report, _ = encode_toon_with_report(value)
        self.assertEqual(encode_toon(value), text_with_report)


class ToonDecodeErrorContractTest(unittest.TestCase):
    """decode_toon never raises a bare IndexError/KeyError; every malformed
    or truncated input surfaces as TOONDecodeError (a ValueError), per the
    #148/#149 decode error contract."""

    def test_truncated_tabular_block_root_array_raises_value_error(self) -> None:
        # Header claims 2 rows, only 1 present.
        text = "[2]{file,lines}:\n  a.py,10"
        with self.assertRaises(TOONDecodeError):
            decode_toon(text)
        with self.assertRaises(ValueError):
            decode_toon(text)

    def test_truncated_tabular_block_nested_raises_value_error(self) -> None:
        text = "files[2]{path,lines}:\n  a.py,10"
        with self.assertRaises(TOONDecodeError):
            decode_toon(text)

    def test_malformed_array_header_raises_value_error(self) -> None:
        with self.assertRaises(TOONDecodeError):
            decode_toon("[2{file,lines}:\n  a.py,10\n  b.py,20")

    def test_malformed_entry_missing_colon_raises_value_error(self) -> None:
        with self.assertRaises(TOONDecodeError):
            decode_toon("a: 1\nb 2")

    def test_unterminated_array_count_bracket_raises_value_error(self) -> None:
        with self.assertRaises(TOONDecodeError):
            decode_toon("items[3:\n  a")

    def test_row_field_count_mismatch_raises_value_error(self) -> None:
        # Sprint's known bug class (#149): silently dropping excess values
        # instead of erroring. Canonical decoder must reject, not truncate.
        text = "files[1]{path,lines}:\n  a.py,10,extra"
        with self.assertRaises(TOONDecodeError):
            decode_toon(text)

    def test_unterminated_quoted_scalar_raises_value_error(self) -> None:
        with self.assertRaises(TOONDecodeError):
            decode_toon('name: "unterminated')

    def test_never_raises_bare_index_error(self) -> None:
        malformed_inputs = [
            "[2]{file,lines}:\n  a.py,10",  # truncated root tabular block
            "files[3]{path}:\n  a.py",  # truncated nested tabular block
            "items[3:\n  a",  # unterminated count bracket
            "items[3]{a,b:\n  1,2",  # unterminated field-list bracket
            "a: 1\nb 2",  # entry with no colon
        ]
        for text in malformed_inputs:
            with self.assertRaises(ValueError):
                try:
                    decode_toon(text)
                except IndexError:  # pragma: no cover - the bug this guards against
                    self.fail(f"decode_toon raised a bare IndexError for {text!r}")


if __name__ == "__main__":
    unittest.main()
