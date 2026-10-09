import json
from pathlib import Path

import pytest

from simplicio_loop import agent_handoff as ah

FIXTURES = Path(__file__).resolve().parent.parent / "contracts" / "agent-handoff" / "v1" / "fixtures"


# --- kills the mutants that survived the first review (#1613 audit)
@pytest.mark.parametrize("delta", [-1, 1])
def test_measured_prompt_tokens_must_equal_the_sum_in_both_directions(delta):
    doc = json.loads((FIXTURES / "valid-measured.json").read_text(encoding="utf-8"))
    doc["tokens"]["prompt_tokens"] += delta
    with pytest.raises(ah.HandoffError) as exc:
        ah.validate_handoff(doc)
    assert exc.value.reason_code == "handoff_tokens_inconsistent"


@pytest.mark.parametrize("field,value", [("role", "wizard"), ("family", ""), ("model", "")])
def test_agent_fields_are_closed(field, value):
    doc = json.loads((FIXTURES / "valid-measured.json").read_text(encoding="utf-8"))
    doc["agent"][field] = value
    with pytest.raises(ah.HandoffError):
        ah.validate_handoff(doc)


def test_reason_is_one_of_the_three_values():
    doc = json.loads((FIXTURES / "valid-measured.json").read_text(encoding="utf-8"))
    doc["reason"] = "whatever"
    with pytest.raises(ah.HandoffError):
        ah.validate_handoff(doc)
