"""Tests for the TOON (Token-Oriented Object Notation) encoder/decoder."""

from __future__ import annotations

import pytest

from simplicio.toon_codec import TOONDecodeError, from_toon, to_toon


def test_encodes_uniform_array_of_objects_as_tabular_block():
    value = {
        "items": [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
    }
    text = to_toon(value)
    assert "items[2]{id,name}:" in text
    assert "1,Alice" in text
    assert "2,Bob" in text


def test_encodes_scalar_array_inline():
    value = {"tags": ["a", "b", "c"]}
    assert to_toon(value) == "tags[3]: a,b,c"


def test_encodes_nested_object_yaml_style():
    value = {"name": "TOON", "address": {"city": "NYC", "region": "NY-US"}}
    text = to_toon(value)
    assert text.splitlines() == [
        "name: TOON",
        "address:",
        "  city: NYC",
        "  region: NY-US",
    ]


@pytest.mark.parametrize(
    "value",
    [
        {},
        [],
        {"a": 1, "b": [1, 2, 3], "c": {"d": "e"}},
        {"nested": {"deep": {"deeper": [1, 2, 3]}}},
        {
            "items": [
                {"id": 1, "name": "Alice", "role": "admin"},
                {"id": 2, "name": "Bob", "role": "user"},
                {"id": 3, "name": "Carol", "role": "user"},
            ]
        },
        # non-uniform: differing key sets -> compact JSON fallback
        {"items": [{"a": 1}, {"a": 1, "b": 2}]},
        # empty array
        {"items": []},
        # empty object value
        {"config": {}},
        # scalars requiring quoting (comma, colon, newline, leading space,
        # numeric-looking string, bool/null-looking string, empty string)
        {
            "a": "has, comma",
            "b": "has: colon",
            "c": "multi\nline",
            "d": " leading space",
            "e": "42",
            "f": "true",
            "g": "null",
            "h": "",
            "i": '"quoted already"',
        },
        {"n_int": 42, "n_float": 3.14, "n_neg": -7, "flag": True, "flag2": False, "nothing": None},
        # mixed-type array -> fallback
        {"mixed": [1, "two", 3.0, None, True]},
        # array containing a nested list/dict inside an element -> fallback
        {"items": [{"id": 1, "tags": ["x"]}, {"id": 2, "tags": ["y"]}]},
        # root-level uniform array of objects
        [{"id": 1}, {"id": 2}],
        # root-level scalar array
        [1, 2, 3],
        # root-level non-uniform array
        [{"a": 1}, "not-a-dict"],
    ],
)
def test_round_trip_lossless(value):
    encoded = to_toon(value)
    decoded = from_toon(encoded)
    assert decoded == value


def test_non_uniform_array_falls_back_to_compact_json():
    value = {"items": [{"a": 1, "b": 2}, {"a": 1}]}
    text = to_toon(value)
    assert "items[2]{" not in text
    assert "items: [" in text
    assert from_toon(text) == value


def test_empty_array_falls_back_to_compact_json_marker():
    value = {"items": []}
    text = to_toon(value)
    assert text == "items: []"
    assert from_toon(text) == value


def test_empty_object_value_is_compact():
    value = {"config": {}}
    text = to_toon(value)
    assert text == "config: {}"
    assert from_toon(text) == value


def test_empty_root_object_and_array():
    assert to_toon({}) == "{}"
    assert from_toon("{}") == {}
    assert to_toon([]) == "[]"
    assert from_toon("[]") == []


def test_realistic_precedent_fixture_round_trip():
    value = {
        "schema": "simplicio.precedent-index/v1",
        "items": [
            {
                "path": "src/ui/Login.tsx",
                "line": 12,
                "summary": "Login guard checks permission before render",
                "tags": ["react", "login", "permission"],
            },
            {
                "path": "src/payments.ts",
                "line": 3,
                "summary": "Payment helper",
                "tags": ["billing"],
            },
        ],
    }
    encoded = to_toon(value)
    # uniform array of objects (same key set, scalar-ish fields except tags
    # which is itself a list) -> falls back since "tags" is a nested list
    assert from_toon(encoded) == value


def test_invalid_toon_raises_decode_error():
    # header declares 2 fields but the row provides 3 values
    with pytest.raises(TOONDecodeError):
        from_toon("items[1]{a,b}:\n  1,2,3")


def test_unparseable_multiline_root_raises_decode_error():
    with pytest.raises(TOONDecodeError):
        from_toon("not valid toon at all\nmore garbage here")
