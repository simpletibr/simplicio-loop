"""sp_output_schema.py — standardized LLM output contract for sp fan-out.

Two goals:

1. **Make modal-vote work better.** Free-text output → modal on raw string →
   uniq=1 collapse when 200 subagents converge on same wording, even if
   they meant different things. Structured output → modal on the SET of
   behaviors → distinct outputs with same behaviors agree, distinct
   behaviors disagree.

2. **Cheaper oracle eval.** Run the oracle (phpunit/regex) only on the
   modal-vote winner, not on every subagent. With free text we needed
   to score every one; with structured output we group by behavior
   signature and only score the modal group.

Schema v1 (when `[STRUCTURED_OUTPUT=v1]` marker is in the prompt):

  ```json
  {
    "artifact": "<the file/diff/code content>",
    "files_changed": ["src/a.py", ...],
    "behaviors_added": ["foo()", "bar.baz", ...],
    "expected_oracle_pass": ["test_a", "pattern_x", ...],
    "confidence": 0.0..1.0,
    "concerns": ["lib X may not be installed", ...]
  }
  ```

The `artifact` field carries the actual deliverable (PHP code, diff, etc.).
Everything else is the model's self-report — used for aggregation, not for
correctness. The oracle (phpunit/regex) is still the truth.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


STRUCTURED_OUTPUT_MARKER = "[STRUCTURED_OUTPUT=v1]"


STRUCTURED_OUTPUT_INSTRUCTION = """
[OUTPUT FORMAT — STRUCTURED v1]
Your entire response MUST be a single JSON object. The JSON object MUST have
these exact fields:

  - "artifact": (string) the complete deliverable (file content, diff, code)
  - "files_changed": (array of strings) paths the artifact touches
  - "behaviors_added": (array of strings) function/method names you added,
                       in `ClassName::method` or `module.function` form
  - "expected_oracle_pass": (array of strings) tests/patterns you EXPECT
                            will pass with this artifact
  - "confidence": (float 0.0 to 1.0) your self-rated confidence
  - "concerns": (array of strings) things you are unsure about

The "artifact" field is the only field consumed downstream — the others
are aggregated across N parallel subagents to vote on the best output.
Do NOT include code fences around the JSON. Do NOT include prose before
or after. Start with `{` and end with `}`. Nothing else.
"""


@dataclass
class StructuredResponse:
    """Parsed view of a structured sp output."""
    artifact: str
    files_changed: list[str] = field(default_factory=list)
    behaviors_added: list[str] = field(default_factory=list)
    expected_oracle_pass: list[str] = field(default_factory=list)
    confidence: float = 0.0
    concerns: list[str] = field(default_factory=list)
    parse_ok: bool = True
    parse_error: Optional[str] = None

    @classmethod
    def from_text(cls, text: str) -> "StructuredResponse":
        """Tolerant parser: strips fences if present, finds the first
        balanced JSON object, falls back to text-as-artifact if parsing
        fails. Small models often miss the JSON contract."""
        if not text:
            return cls(artifact="", parse_ok=False, parse_error="empty response")
        cleaned = text
        # Strip ``` fences if present (LLMs love them despite instructions)
        fenced = re.search(r"```(?:json)?\s*\n(.*?)```", cleaned, re.DOTALL)
        if fenced:
            cleaned = fenced.group(1)
        # Find balanced { ... }
        start = cleaned.find("{")
        if start < 0:
            return cls(artifact=text, parse_ok=False,
                       parse_error="no '{' in response")
        depth = 0
        end = -1
        for i in range(start, len(cleaned)):
            c = cleaned[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            return cls(artifact=text, parse_ok=False,
                       parse_error="unbalanced braces")
        try:
            payload = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as e:
            return cls(artifact=text, parse_ok=False,
                       parse_error=f"json error: {e}")
        if not isinstance(payload, dict):
            return cls(artifact=text, parse_ok=False,
                       parse_error="root is not an object")
        artifact = payload.get("artifact")
        if not isinstance(artifact, str):
            # Some models put the artifact in another field name
            for alt in ("code", "content", "output", "diff"):
                if isinstance(payload.get(alt), str):
                    artifact = payload[alt]
                    break
        if not isinstance(artifact, str):
            return cls(artifact=text, parse_ok=False,
                       parse_error="no string 'artifact' field")
        def _slist(k):
            v = payload.get(k)
            return [str(x) for x in v] if isinstance(v, list) else []
        try:
            conf = float(payload.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        return cls(
            artifact=artifact,
            files_changed=_slist("files_changed"),
            behaviors_added=_slist("behaviors_added"),
            expected_oracle_pass=_slist("expected_oracle_pass"),
            confidence=max(0.0, min(1.0, conf)),
            concerns=_slist("concerns"),
            parse_ok=True,
        )

    def behavior_signature(self) -> str:
        """Hash the BEHAVIOR (not the artifact text) so two artifacts that
        do the same thing collapse to one vote even if the strings differ.
        Stable across whitespace + comment variations."""
        sig_input = json.dumps({
            "files": sorted(self.files_changed),
            "behaviors": sorted(self.behaviors_added),
            "expected": sorted(self.expected_oracle_pass),
        }, sort_keys=True)
        return hashlib.sha256(sig_input.encode("utf-8")).hexdigest()[:12]


def behavior_modal_vote(responses: list[StructuredResponse]) -> tuple[
    Optional[StructuredResponse], int, int, dict]:
    """Vote on the SET OF BEHAVIORS rather than the raw artifact text.
    Picks the highest-confidence member of the modal behavior group.

    Returns: (winner, modal_count, unique_behavior_signatures, diagnostics)
    """
    if not responses:
        return None, 0, 0, {"reason": "no responses"}
    # Bucket by behavior signature; fall back to artifact hash for unparsed
    by_sig: dict[str, list[StructuredResponse]] = {}
    for r in responses:
        if r.parse_ok:
            sig = r.behavior_signature()
        else:
            sig = "raw:" + hashlib.sha256(
                r.artifact.encode("utf-8")
            ).hexdigest()[:12]
        by_sig.setdefault(sig, []).append(r)
    sig_counts = Counter({sig: len(rs) for sig, rs in by_sig.items()})
    winning_sig, modal_count = sig_counts.most_common(1)[0]
    group = by_sig[winning_sig]
    # Pick the highest-confidence member of the winning group as representative
    winner = max(group, key=lambda r: (r.confidence, len(r.artifact)))
    diagnostics = {
        "parse_ok_count": sum(1 for r in responses if r.parse_ok),
        "parse_failed_count": sum(1 for r in responses if not r.parse_ok),
        "behavior_groups": len(by_sig),
        "winning_signature": winning_sig,
        "winner_confidence": winner.confidence,
        "winner_self_expected": winner.expected_oracle_pass,
    }
    return winner, modal_count, len(by_sig), diagnostics
