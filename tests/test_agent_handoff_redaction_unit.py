"""Secret redaction of the free text of a handoff (#1608, part B). The fake secrets are built at run time from pieces."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from simplicio_loop import agent_handoff as ah

FIXTURES = Path(__file__).resolve().parent.parent / "contracts" / "agent-handoff" / "v1" / "fixtures"
KEY = "sk-" + "A1b2C3d4" * 4
PAT = "ghp_" + "a1B2c3D4e5" * 3
FLAG_SECRET = "hunter2" + "hunter2"


def doc():
    return json.loads((FIXTURES / "valid-measured.json").read_text(encoding="utf-8"))


FREE_TEXT = [
    ("/objective", lambda d, v: d.__setitem__("objective", v)),
    ("/acceptance_criteria/0", lambda d, v: d["acceptance_criteria"].__setitem__(0, v)),
    ("/done/commands/0/command", lambda d, v: d["done"]["commands"][0].__setitem__("command", v)),
    ("/done/commands/0/summary", lambda d, v: d["done"]["commands"][0].__setitem__("summary", v)),
    ("/next_steps/0", lambda d, v: d["next_steps"].__setitem__(0, v)),
    ("/open_questions/0", lambda d, v: d["open_questions"].append(v)),
]


@pytest.mark.parametrize("pointer,put", FREE_TEXT, ids=[p for p, _ in FREE_TEXT])
def test_every_free_text_field_is_redacted(pointer, put):
    d = doc()
    put(d, "call the api with %s and keep going" % KEY)
    clean, changed = ah.redact_handoff(d)
    assert KEY not in json.dumps(clean)
    assert changed == [pointer]
    ah.validate_handoff(clean)  # what write stores must still be a valid handoff


@pytest.mark.parametrize("secret", [KEY, PAT, "AKIA" + "ABCDEFGHIJKLMNOP", "mail bob@example.com",
                                    "password=" + FLAG_SECRET, "https://user:pw12345@host.example/x"])
def test_known_secret_shapes_are_masked(secret):
    d = doc()
    d["objective"] = "context " + secret
    clean, changed = ah.redact_handoff(d)
    assert changed == ["/objective"]
    assert clean["objective"] != d["objective"]
    assert clean["objective"].startswith("context ")


def test_secret_flag_of_a_command_is_masked():
    d = doc()
    d["done"]["commands"][0]["command"] = "deploy --token %s --env prod" % FLAG_SECRET
    clean, _ = ah.redact_handoff(d)
    assert FLAG_SECRET not in clean["done"]["commands"][0]["command"]
    assert clean["done"]["commands"][0]["command"].startswith("deploy --token ")
    assert clean["done"]["commands"][0]["command"].endswith(" --env prod")


def test_the_input_is_not_changed_and_the_copy_is_deep():
    d = doc()
    d["next_steps"][0] = "use %s" % KEY
    before = copy.deepcopy(d)
    clean, _ = ah.redact_handoff(d)
    assert d == before
    clean["done"]["commands"][0]["summary"] = "changed"
    assert d == before


def test_a_clean_document_comes_back_equal_with_no_changes():
    d = doc()
    clean, changed = ah.redact_handoff(d)
    assert clean == d and changed == []


def test_identifiers_numbers_and_the_lease_are_never_touched():
    d = doc()
    d["lease"] = {"key": "issue-1608", "owner": "bob@example.com"}
    d["task_id"] = "T-1608-B"
    clean, changed = ah.redact_handoff(d)
    assert clean["lease"] == {"key": "issue-1608", "owner": "bob@example.com"}
    assert clean["task_id"] == "T-1608-B"
    assert clean["done"]["files"] == d["done"]["files"]
    assert clean["tokens"] == d["tokens"]
    assert changed == []


def test_several_fields_report_all_pointers_in_document_order():
    d = doc()
    d["objective"] = "x " + KEY
    d["next_steps"] = ["fine", "token " + PAT]
    clean, changed = ah.redact_handoff(d)
    assert changed == ["/objective", "/next_steps/1"]
    assert clean["next_steps"][0] == "fine"


def test_a_field_of_the_wrong_shape_is_left_for_the_validator():
    d = doc()
    d["objective"] = 5
    d["next_steps"] = "not a list"
    d["done"]["commands"] = ["not an object"]
    clean, changed = ah.redact_handoff(d)
    assert clean == d and changed == []
    with pytest.raises(ah.HandoffError) as exc:
        ah.validate_handoff(clean)
    assert exc.value.reason_code == "handoff_schema_invalid"


def test_a_document_that_is_not_an_object_is_refused():
    with pytest.raises(ah.HandoffError) as exc:
        ah.redact_handoff(["objective"])
    assert exc.value.reason_code == "handoff_schema_invalid"
