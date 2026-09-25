"""Unit tests for bench/sp_output_schema.py.

Covers the v1 contract documented in docs/specs/STRUCTURED_OUTPUT_v1.md:
- 6-field schema (artifact, files_changed, behaviors_added,
  expected_oracle_pass, confidence, concerns)
- Tolerant parser (5 input shapes from §3 of the spec)
- Behavior signature determinism
- Modal vote with parsed + unparsed mix
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# bench/ is not a package; add to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench"))

from sp_output_schema import (  # noqa: E402
    STRUCTURED_OUTPUT_INSTRUCTION,
    STRUCTURED_OUTPUT_MARKER,
    StructuredResponse,
    behavior_modal_vote,
)

# ----- marker / instruction surface ----- #


def test_marker_is_canonical_string():
    assert STRUCTURED_OUTPUT_MARKER == "[STRUCTURED_OUTPUT=v1]"


def test_instruction_mentions_all_six_fields():
    inst = STRUCTURED_OUTPUT_INSTRUCTION
    for field in (
        "artifact",
        "files_changed",
        "behaviors_added",
        "expected_oracle_pass",
        "confidence",
        "concerns",
    ):
        assert field in inst, f"instruction missing field: {field}"


# ----- parser: §3 of the spec, 5 input shapes ----- #


def _example_payload():
    return {
        "artifact": "<?php\nclass X {}\n",
        "files_changed": ["src/X.php"],
        "behaviors_added": ["X::foo"],
        "expected_oracle_pass": ["test_foo"],
        "confidence": 0.85,
        "concerns": ["lib not declared"],
    }


def test_parses_bare_json():
    r = StructuredResponse.from_text(json.dumps(_example_payload()))
    assert r.parse_ok is True
    assert r.artifact.startswith("<?php")
    assert r.files_changed == ["src/X.php"]
    assert r.behaviors_added == ["X::foo"]
    assert r.expected_oracle_pass == ["test_foo"]
    assert r.confidence == 0.85
    assert r.concerns == ["lib not declared"]


def test_parses_fenced_json():
    payload = json.dumps(_example_payload())
    fenced = f"Here is the result:\n\n```json\n{payload}\n```\n\nLet me know."
    r = StructuredResponse.from_text(fenced)
    assert r.parse_ok is True
    assert r.behaviors_added == ["X::foo"]


def test_parses_json_with_prose_around():
    payload = json.dumps(_example_payload())
    prose = f"Sure, here you go:\n\n{payload}\n\nDone."
    r = StructuredResponse.from_text(prose)
    assert r.parse_ok is True
    assert r.files_changed == ["src/X.php"]


def test_falls_back_on_pure_text():
    r = StructuredResponse.from_text("just some code")
    assert r.parse_ok is False
    assert r.artifact == "just some code"
    assert r.files_changed == []
    assert r.confidence == 0.0


def test_falls_back_on_malformed_json():
    r = StructuredResponse.from_text('{artifact: "missing quotes"')
    assert r.parse_ok is False
    assert r.artifact == '{artifact: "missing quotes"'


def test_promotes_alternate_artifact_field_names():
    """Spec §3: 'code'/'content'/'output'/'diff' get promoted when
    'artifact' is missing — common small-model drift."""
    for alt in ("code", "content", "output", "diff"):
        payload = {alt: "x = 1", "files_changed": []}
        r = StructuredResponse.from_text(json.dumps(payload))
        assert r.parse_ok is True, f"failed to promote {alt}"
        assert r.artifact == "x = 1"


def test_handles_empty_input():
    r = StructuredResponse.from_text("")
    assert r.parse_ok is False
    assert "empty" in (r.parse_error or "").lower()


def test_handles_no_opening_brace():
    r = StructuredResponse.from_text("no json here at all")
    assert r.parse_ok is False


def test_handles_unbalanced_braces():
    r = StructuredResponse.from_text('{"artifact": "x"')  # missing close
    assert r.parse_ok is False


def test_confidence_clamped_to_unit_interval():
    for raw, expected in [(2.0, 1.0), (-0.5, 0.0), (0.5, 0.5)]:
        payload = {"artifact": "x", "confidence": raw}
        r = StructuredResponse.from_text(json.dumps(payload))
        assert r.confidence == expected, f"{raw} should clamp to {expected}"


def test_confidence_falls_back_on_garbage():
    payload = {"artifact": "x", "confidence": "high"}
    r = StructuredResponse.from_text(json.dumps(payload))
    assert r.confidence == 0.0


def test_missing_array_fields_default_to_empty():
    payload = {"artifact": "x"}  # only required-looking field
    r = StructuredResponse.from_text(json.dumps(payload))
    assert r.parse_ok is True
    assert r.files_changed == []
    assert r.behaviors_added == []
    assert r.expected_oracle_pass == []
    assert r.concerns == []


def test_root_is_array_rejected():
    r = StructuredResponse.from_text("[1, 2, 3]")
    assert r.parse_ok is False


# ----- behavior signature: §4 ----- #


def test_behavior_signature_is_deterministic():
    p = _example_payload()
    r1 = StructuredResponse.from_text(json.dumps(p))
    r2 = StructuredResponse.from_text(json.dumps(p))
    assert r1.behavior_signature() == r2.behavior_signature()
    assert len(r1.behavior_signature()) == 12


def test_signature_ignores_artifact_text():
    """Two responses with same behaviors but different artifact wording
    must share the same signature. Spec §4."""
    base = _example_payload()
    r1 = StructuredResponse.from_text(json.dumps(base))
    r2_payload = {**base, "artifact": "totally different prose"}
    r2 = StructuredResponse.from_text(json.dumps(r2_payload))
    assert r1.behavior_signature() == r2.behavior_signature()


def test_signature_changes_with_behaviors():
    base = _example_payload()
    r1 = StructuredResponse.from_text(json.dumps(base))
    r2_payload = {**base, "behaviors_added": ["X::foo", "X::bar"]}
    r2 = StructuredResponse.from_text(json.dumps(r2_payload))
    assert r1.behavior_signature() != r2.behavior_signature()


def test_signature_sorts_arrays():
    """Same set of behaviors in different order → same signature."""
    base = _example_payload()
    p1 = {**base, "behaviors_added": ["X::a", "X::b"]}
    p2 = {**base, "behaviors_added": ["X::b", "X::a"]}
    r1 = StructuredResponse.from_text(json.dumps(p1))
    r2 = StructuredResponse.from_text(json.dumps(p2))
    assert r1.behavior_signature() == r2.behavior_signature()


# ----- modal vote: §6 ----- #


def test_modal_vote_picks_winning_signature():
    base = _example_payload()
    p_majority = json.dumps(base)
    p_loner = json.dumps({**base, "behaviors_added": ["Y::different"]})
    responses = [
        StructuredResponse.from_text(p_majority),
        StructuredResponse.from_text(p_majority),
        StructuredResponse.from_text(p_majority),
        StructuredResponse.from_text(p_loner),
    ]
    winner, modal, uniq, diag = behavior_modal_vote(responses)
    assert modal == 3
    assert uniq == 2
    assert winner.behaviors_added == ["X::foo"]


def test_modal_vote_tiebreaks_on_confidence():
    """Two responses in the modal group: highest confidence wins."""
    p_low = json.dumps({**_example_payload(), "confidence": 0.3, "artifact": "low-conf code"})
    p_high = json.dumps({**_example_payload(), "confidence": 0.9, "artifact": "high-conf code"})
    responses = [
        StructuredResponse.from_text(p_low),
        StructuredResponse.from_text(p_high),
    ]
    winner, _, _, _ = behavior_modal_vote(responses)
    assert winner.confidence == 0.9
    assert winner.artifact == "high-conf code"


def test_modal_vote_mixes_parsed_and_unparsed():
    """Parsed responses with same behavior group together.
    Unparsed responses (parse_ok=False) get raw:hash signature each."""
    p = json.dumps(_example_payload())
    responses = [
        StructuredResponse.from_text(p),
        StructuredResponse.from_text(p),
        StructuredResponse.from_text("free text 1"),
        StructuredResponse.from_text("free text 2"),
    ]
    winner, modal, uniq, diag = behavior_modal_vote(responses)
    # 2 parsed (same sig) + 2 unparsed (different raw hashes) = 3 groups
    assert uniq == 3
    assert modal == 2  # parsed group is the modal
    assert winner.parse_ok is True
    assert diag["parse_ok_count"] == 2
    assert diag["parse_failed_count"] == 2


def test_modal_vote_empty_list():
    winner, modal, uniq, diag = behavior_modal_vote([])
    assert winner is None
    assert modal == 0
    assert uniq == 0


def test_modal_vote_single_response():
    p = json.dumps(_example_payload())
    r = StructuredResponse.from_text(p)
    winner, modal, uniq, _ = behavior_modal_vote([r])
    assert winner is r
    assert modal == 1
    assert uniq == 1


# ----- diagnostics surface ----- #


def test_diag_includes_winner_self_expectation():
    """For parse-vs-oracle disagreement detection: winner's claimed
    passing tests are exposed in diagnostics."""
    base = _example_payload()
    r = StructuredResponse.from_text(json.dumps(base))
    _, _, _, diag = behavior_modal_vote([r])
    assert diag["winner_self_expected"] == ["test_foo"]
    assert diag["winner_confidence"] == 0.85
