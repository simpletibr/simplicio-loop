"""Unit tests for the simplicio.agent-handoff/v1 contract and its validator (#1608, part A).

No file is written or read here by the module under test: write/read/CLI belong to part B.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from simplicio_loop import agent_handoff as ah
from simplicio_loop.input_ceiling import estimate_tokens

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "contracts" / "agent-handoff" / "v1"
PACKED = REPO / "simplicio_loop" / "_contracts" / "agent-handoff" / "v1"
FIXTURES = SRC / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def schema():
    return json.loads((SRC / "schema.json").read_text(encoding="utf-8"))


def schema_errors(doc):
    return list(jsonschema.Draft202012Validator(schema()).iter_errors(doc))


# --- the schema file and its packaged copy ---------------------------------------------------------------------------

def test_schema_is_a_valid_draft_2020_12_schema_and_is_closed():
    s = schema()
    jsonschema.Draft202012Validator.check_schema(s)
    assert s["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert s["additionalProperties"] is False
    assert s["properties"]["schema"] == {"const": "simplicio.agent-handoff/v1"}
    for name in ("agent", "done", "tokens", "lease"):
        assert s["properties"][name]["additionalProperties"] is False


def test_packaged_schema_is_byte_identical_to_the_source_schema():
    assert (SRC / "schema.json").read_bytes() == (PACKED / "schema.json").read_bytes()


def test_contract_doc_exists_and_names_the_contract():
    text = (SRC / "SCHEMA.md").read_text(encoding="utf-8")
    assert "contract: agent-handoff/v1" in text and "simplicio.agent-handoff/v1" in text


# --- valid fixtures --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["valid-measured.json", "valid-estimated.json"])
def test_valid_fixtures_pass_schema_and_validator(name):
    doc = load(name)
    assert schema_errors(doc) == []
    ah.validate_handoff(doc)


def test_valid_fixtures_cover_both_bases():
    assert load("valid-measured.json")["tokens"]["basis"] == "MEASURED"
    assert load("valid-estimated.json")["tokens"]["basis"] == "ESTIMATED"


# --- invalid fixtures: the schema alone rejects these ----------------------------------------------------------------

SCHEMA_LEVEL = [
    "invalid-extra-field.json",
    "invalid-measured-with-estimator.json",
    "invalid-estimated-without-estimator.json",
    "invalid-estimated-with-cache-counts.json",
    "invalid-continuation-zero.json",
]


@pytest.mark.parametrize("name", SCHEMA_LEVEL)
def test_schema_rejects_and_validator_reports_schema_invalid(name):
    doc = load(name)
    assert schema_errors(doc) != []
    with pytest.raises(ah.HandoffError) as exc:
        ah.validate_handoff(doc)
    assert exc.value.reason_code == "handoff_schema_invalid"


# --- rules the schema does not cover ---------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["invalid-path-absolute.json", "invalid-path-dotdot.json",
                                  "invalid-path-simplicio-prefix.json"])
def test_path_fixtures_pass_the_schema_and_fail_the_path_rule(name):
    doc = load(name)
    assert schema_errors(doc) == []
    with pytest.raises(ah.HandoffError) as exc:
        ah.validate_handoff(doc)
    assert exc.value.reason_code == "handoff_path_invalid"


def test_measured_total_must_include_the_cache_counts():
    doc = load("invalid-total-not-sum.json")
    assert schema_errors(doc) == []
    with pytest.raises(ah.HandoffError) as exc:
        ah.validate_handoff(doc)
    assert exc.value.reason_code == "handoff_tokens_inconsistent"


def _with_path(path):
    doc = load("valid-measured.json")
    doc["done"]["files"][0]["path"] = path
    return doc


@pytest.mark.parametrize("path", [
    "/etc/passwd", "/", "..", "../x", "a/../b", "a/..", "./a", "a/./b", "a//b", "a/", "a\\b", "C:\\x", "C:/x",
    ".simplicio", ".simplicio/x.json", ".SIMPLICIO/x.json", "a\x00b",
])
def test_bad_file_paths_are_rejected(path):
    with pytest.raises(ah.HandoffError) as exc:
        ah.validate_handoff(_with_path(path))
    assert exc.value.reason_code == "handoff_path_invalid"


@pytest.mark.parametrize("path", [
    "simplicio_loop/input_ceiling.py", ".simplicio-loop/orchestrator/handoff/run-1/1.json", "a.b/c-d_e/f", "README.md",
    "dir/.simplicio-loop/x", "dir/.simplicio/x",
])
def test_good_file_paths_are_accepted(path):
    ah.validate_handoff(_with_path(path))


def _big(items):
    doc = load("valid-measured.json")
    doc["next_steps"] = [("Read the module and explain every branch in detail number %d. " % i) * 12 for i in range(items)]
    return doc


def test_oversized_handoff_is_rejected_by_the_estimated_token_size():
    doc = _big(50)
    assert schema_errors(doc) == []
    assert estimate_tokens(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)) > ah.MAX_HANDOFF_TOKENS
    with pytest.raises(ah.HandoffError) as exc:
        ah.validate_handoff(doc)
    assert exc.value.reason_code == "handoff_too_large"


def test_max_handoff_tokens_is_6000():
    assert ah.MAX_HANDOFF_TOKENS == 6000


def test_size_limit_is_inclusive(monkeypatch):
    doc = load("valid-measured.json")
    size = estimate_tokens(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    monkeypatch.setattr(ah, "MAX_HANDOFF_TOKENS", size)
    ah.validate_handoff(doc)
    monkeypatch.setattr(ah, "MAX_HANDOFF_TOKENS", size - 1)
    with pytest.raises(ah.HandoffError) as exc:
        ah.validate_handoff(doc)
    assert exc.value.reason_code == "handoff_too_large"


def test_validator_does_not_change_its_input():
    doc = load("valid-estimated.json")
    before = copy.deepcopy(doc)
    ah.validate_handoff(doc)
    assert doc == before


@pytest.mark.parametrize("bad", [None, [], "x", 5])
def test_non_object_documents_are_schema_invalid(bad):
    with pytest.raises(ah.HandoffError) as exc:
        ah.validate_handoff(bad)
    assert exc.value.reason_code == "handoff_schema_invalid"


@pytest.mark.parametrize("key,value", [
    ("run_id", ".."), ("run_id", "."), ("run_id", "a/b"), ("run_id", ""), ("run_id", "x" * 129),
    ("reason", "because"), ("schema", "simplicio.agent-handoff/v2"), ("created_at", "yesterday"),
    ("acceptance_criteria", []), ("next_steps", []),
])
def test_other_field_violations_are_schema_invalid(key, value):
    doc = load("valid-measured.json")
    doc[key] = value
    with pytest.raises(ah.HandoffError) as exc:
        ah.validate_handoff(doc)
    assert exc.value.reason_code == "handoff_schema_invalid"


def test_lease_uses_the_claim_field_names_and_never_the_token():
    doc = load("valid-measured.json")
    assert set(doc["lease"]) == {"key", "owner"}
    doc["lease"]["owner_token"] = "abc"
    with pytest.raises(ah.HandoffError):
        ah.validate_handoff(doc)


# --- where a handoff lives -------------------------------------------------------------------------------------------

def test_handoff_path_layout(tmp_path):
    p = ah.handoff_path(tmp_path, "run-1.2_A", 3)
    assert p == tmp_path / ".simplicio-loop" / "orchestrator" / "handoff" / "run-1.2_A" / "3.json"
    assert ".simplicio" not in p.parts
    assert not p.exists() and not (tmp_path / ".simplicio-loop").exists()


def test_handoff_path_accepts_the_longest_run_id(tmp_path):
    assert ah.handoff_path(tmp_path, "x" * 128, 1).parent.name == "x" * 128


@pytest.mark.parametrize("run_id", ["", ".", "..", "../x", "x/..", "a/b", "a\\b", "a b", "x" * 129, "é", "a\x00b", "a\n", None, 5])
def test_handoff_path_rejects_unsafe_run_ids(tmp_path, run_id):
    with pytest.raises(ah.HandoffError) as exc:
        ah.handoff_path(tmp_path, run_id, 1)
    assert exc.value.reason_code == "handoff_run_id_invalid"


@pytest.mark.parametrize("n", [0, -1, True, 1.0, "1", None])
def test_handoff_path_rejects_bad_continuation_numbers(tmp_path, n):
    with pytest.raises(ah.HandoffError) as exc:
        ah.handoff_path(tmp_path, "run-1", n)
    assert exc.value.reason_code == "handoff_continuation_invalid"


# --- reviewer additions (#1613) ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mutate", [
    lambda d: d.__setitem__("run_id", "abc\n"),
    lambda d: d.__setitem__("created_at", "2026-10-09T17:00:00Z\n"),
    lambda d: d["done"]["files"][0].__setitem__("sha256", "a" * 64 + "\n"),
])
def test_patterns_do_not_accept_a_trailing_newline(mutate):
    doc = json.loads((FIXTURES / "valid-measured.json").read_text(encoding="utf-8"))
    mutate(doc)
    with pytest.raises(ah.HandoffError):
        ah.validate_handoff(doc)
