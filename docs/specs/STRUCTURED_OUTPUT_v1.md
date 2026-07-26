# Structured Output v1 — canonical spec

> **Status:** v1 (frozen). New optional fields require v1.x; removing or
> renaming fields requires v2.
> **Owner:** `simplicio-dev-cli`. Reference impl in
> [`bench/sp_output_schema.py`](../../bench/sp_output_schema.py).
> **Adopters:** `simplicio-dev-cli` bench (today). Proposed for
> `simplicio-prompt` runtime template (upstream PR pending).
> **Date:** 2026-05-30.

---

## 1. Why this exists

A fan-out runtime that produces N text outputs has two hard problems:

1. **Modal-vote on raw strings collapses to `uniq=1`** when N copies of the
   same model converge on identical wording (even if they meant different
   things across runs). Vote on the BEHAVIOR, not the bytes.
2. **Oracle eval cost scales linearly with N.** Running PHPUnit / pytest /
   ruff on every one of 200 candidates is wasteful; running the oracle on
   the modal-vote winner alone is enough — IF the modal is correctly
   chosen.

Structured Output v1 solves both: every subagent emits a fixed-shape JSON
object; the aggregator votes on the `(files_changed, behaviors_added,
expected_oracle_pass)` triple; the highest-confidence candidate in the
winning group goes to the oracle.

## 2. The contract

### 2.1 Trigger

When the prompt sent to the LLM contains the literal marker:

```
[STRUCTURED_OUTPUT=v1]
```

the LLM **MUST** respond with a single top-level JSON object matching the
schema below. The marker is the only opt-in signal; no marker → no
structured output expected.

### 2.2 Schema

```json
{
  "artifact":              "string  (REQUIRED)",
  "files_changed":         "string[] (REQUIRED, MAY be empty)",
  "behaviors_added":       "string[] (REQUIRED, MAY be empty)",
  "expected_oracle_pass":  "string[] (REQUIRED, MAY be empty)",
  "confidence":            "number 0.0..1.0 (REQUIRED)",
  "concerns":              "string[] (REQUIRED, MAY be empty)"
}
```

### 2.3 Field semantics

| Field | Type | Description |
|---|---|---|
| `artifact` | string | The deliverable verbatim — file content, unified diff, or code block. This is the ONLY field the oracle consumes. |
| `files_changed` | string[] | Paths (relative to repo root) the artifact would modify. |
| `behaviors_added` | string[] | Functions/methods/symbols the artifact introduces, in `ClassName::method` or `module.function` form. Stable key for aggregation. |
| `expected_oracle_pass` | string[] | Tests/patterns the LLM EXPECTS will pass after the artifact lands. Used for parse-vs-oracle disagreement detection. |
| `confidence` | float | LLM's self-rated confidence in `[0.0, 1.0]`. Tiebreaker in modal vote. |
| `concerns` | string[] | Things the LLM is unsure about. Audit-only; does not affect vote. |

### 2.4 Output rules

- Response **MUST** start with `{` and end with `}`. No prose before/after.
- No code fences (\`\`\`json …\`\`\`) around the root JSON. The parser tolerates
  them as a fallback but the contract requires bare JSON.
- The `artifact` field carries the FULL deliverable. Do not abbreviate.
- All array fields **MUST** be present (use `[]` when empty), not absent.
- All field names are case-sensitive: lowercase + underscore.
- Extra fields are accepted but ignored. Reserved for future minor versions.

## 3. Parser tolerance

The reference parser
(`bench/sp_output_schema.py::StructuredResponse.from_text`) is **lenient by
design** to absorb small-model behavior. The contract above is the
authoring guide; the parser handles the inevitable drift:

| Input shape | Behaviour |
|---|---|
| Bare JSON (the contract) | `parse_ok=True` — every field populated |
| JSON wrapped in \`\`\`json … \`\`\` fences | Fence stripped, `parse_ok=True` |
| JSON preceded/followed by prose | First balanced `{…}` extracted, `parse_ok=True` |
| Plain text, no JSON at all | `parse_ok=False`, `artifact=text`, every other field empty/default |
| Malformed JSON (unbalanced braces, bad escapes) | `parse_ok=False`, fallback to raw text as artifact |
| JSON with `artifact` missing but `code` / `content` / `output` / `diff` present | One of those is promoted to `artifact`, `parse_ok=True` |
| `confidence` is string / out of range | Clamped to `[0.0, 1.0]`, falls to `0.0` if unparseable |

The intent: **never crash on output drift; always have an artifact to send
to the oracle.** Whether the modal-vote-by-behavior path actually engages
depends on `parse_ok` — when most parses fail (small models), aggregation
falls back to raw-text modal.

## 4. Behavior signature (used by aggregator)

```python
sig = sha256(
    json.dumps(
        {
            "files": sorted(files_changed),
            "behaviors": sorted(behaviors_added),
            "expected": sorted(expected_oracle_pass),
        },
        sort_keys=True,
    )
)[:12]
```

Two responses with identical `(files, behaviors, expected)` triples share a
signature regardless of artifact wording. The modal-vote-winner is the
candidate with the highest `confidence` in the largest signature group.

Responses where `parse_ok=False` get a degenerate signature of
`raw:<sha256(artifact)[:12]>` so they collapse only with byte-identical
fallbacks.

## 5. Worked examples

### 5.1 Valid response (contract-conforming)

```json
{"artifact":"<?php\n\ndeclare(strict_types=1);\n\nnamespace App\\Core;\n\nfinal class PasswordPolicy\n{\n    public static function isStrong(string $p): bool\n    {\n        return strlen($p) >= 12;\n    }\n}\n","files_changed":["src/Core/PasswordPolicy.php"],"behaviors_added":["App\\Core\\PasswordPolicy::isStrong"],"expected_oracle_pass":["test_isStrong_passes_on_12_chars","test_isStrong_fails_on_short"],"confidence":0.85,"concerns":["constant 12 not policy-configurable yet"]}
```

### 5.2 Tolerated drift (fenced + prose — still parses)

````
Here is my answer:

```json
{"artifact":"...","files_changed":[],"behaviors_added":["X::foo"],"expected_oracle_pass":[],"confidence":0.7,"concerns":[]}
```

Let me know if you need anything else!
````

### 5.3 Total failure (parser fallback)

```
public function isStrong($password) { return strlen($password) >= 12; }
```

→ `parse_ok=False`, `artifact="public function ..."`, all other fields
empty. The oracle still receives a candidate, but behavior-modal-vote
falls back to raw-text aggregation for this response.

## 6. Modal-vote algorithm

Pseudocode:

```python
def behavior_modal_vote(responses):
    groups = {}
    for r in responses:
        sig = r.behavior_signature() if r.parse_ok else f"raw:{hash(r.artifact)}"
        groups.setdefault(sig, []).append(r)
    winning_sig, count = most_common(group_sizes)
    winner = max(groups[winning_sig], key=lambda r: (r.confidence, len(r.artifact)))
    return winner, count, len(groups)
```

**Key invariants:**

- Modal-group always contains ≥1 response (no empty winners).
- Tie on signature count: implementation picks the first by stable sort
  (deterministic, but the choice is arbitrary; both winners are
  behavior-equivalent so it doesn't matter to the oracle).
- `confidence` is ONLY a tiebreaker; it cannot promote a non-modal
  candidate over the modal winner. Modal count dominates.

## 7. Versioning

- **v1.0** — current shape. 6 fields. Frozen.
- **v1.x** — additive minors. New OPTIONAL fields allowed. Existing fields
  cannot change type or semantics. Parser ignores unknown fields, so a v1.0
  consumer reading v1.1 output works.
- **v2.0** — required only for breaking changes (field removal/rename,
  type change). Different marker: `[STRUCTURED_OUTPUT=v2]`.

The marker version is the source of truth; the JSON itself does not carry
a version field (intentional — keeps the contract minimal).

## 8. Adoption checklist

For a downstream runtime (e.g., `simplicio-prompt`) to adopt:

- [ ] Add `[STRUCTURED_OUTPUT=v1]` to its `prompts/agent-runtime-execution-prompt.md`
      OR provide a flag that injects the marker conditionally.
- [ ] Document the schema in its README.
- [ ] Implement a parser equivalent to `StructuredResponse.from_text` (or
      vendor `sp_output_schema.py` directly under MIT).
- [ ] Verify on at least one mid-tier model that `parse_ok` rate is ≥80%.
      Smaller models (≤7B) will often fail; that's the parser's fallback
      job, not a contract violation.

## 9. Non-goals

- Validation of the artifact field's *correctness*. The oracle does that.
- Cross-language type safety. JSON is enough; we don't want Protobuf here.
- Streaming. v1 is one-shot only. Streaming variants belong in v2.

## 10. History

- 2026-05-30 — v1 initial spec. Reference implementation
  `bench/sp_output_schema.py`. First adopter: `bench/sp_fanout_helper.py`
  via `sp_fanout_escalating(structured=True)` (default).
