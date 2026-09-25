# TOON encoder autoresearch — pilot 1 run log

Pilot 1 of the `simplicio-autoresearch` skill pattern (Karpathy-style
mutate -> evaluate -> keep/revert via git, wesleysimplicio/simplicio-loop#95),
targeting `simplicio_mapper/toon.py` (issue #151). Branch:
`autoresearch/toon-encoder-20260702`, squashed into one commit on the
integration branch for this PR.

## Setup

- **Target**: `simplicio_mapper/toon.py`'s encode heuristics.
- **Baseline**: the state immediately after #148's manual fix (list-of-
  scalars cells now take the tabular path). The pilot starts *after* that
  deterministic fix, per the issue's own instruction — it optimizes what's
  left, it does not redo #148.
- **Gate** (`scripts/toon_autoresearch.py gate`): `tests.python.test_toon` +
  `tests.python.test_toon_contract` (round-trip + the full TOON-CONTRACT
  golden corpus, `fixtures/toon-golden/`) + `ruff check
  simplicio_mapper/toon.py`. Any failure -> reject, revert. No mutation is
  scored unless it clears the gate first.
- **Score** (`scripts/toon_autoresearch.py score`): sum of approximate
  tokens (same regex word-boundary tokenizer as `scripts/toon_benchmark.py`
  — see that script for why it's not `chars/4` and not a real BPE
  tokenizer) over `encode_toon()` of the 3 real survey artifacts
  (`.simplicio/project-map.json`, `precedent-index.json`,
  `flow-inventory.json`). Lower is better.
- **Baseline score**: **68417** approx tokens.

## Iteration 1 — `true`/`false` -> `1`/`0` (REJECTED, led to a kept side-fix)

**Mutation**: shorten boolean scalars from `true`/`false` to `1`/`0` in
`_format_scalar`. Cheap, syntactically valid, an obviously "shorter"
change — exactly the kind of shortcut a naive scoring-only loop would ship.

**Result**: rejected by the gate. `python -m unittest tests.python.test_toon
tests.python.test_toon_contract -q` failed — 2 tests asserting the literal
encoded string (`"active: true"`, `"GET,/users,true"`) broke.

**But**: this rejection was *not* caught by the primary invariant
(`decode_toon(encode_toon(x)) == x`), which is the mechanism issue #151
names as the anti-Goodhart gate ("um encoder mais curto porém lossy é
rejeitado pelo gate antes de qualquer score"). It was caught only
incidentally, by two unrelated format-string assertions. Checked directly:

```python
>>> decode_toon(encode_toon(True))   # under the mutation
1                                     # int, not bool
>>> 1 == True                        # Python's own quirk
True
>>> {"active": 1} == {"active": True}
True
```

Because `bool` is a subtype of `int` in Python and `True == 1`, a plain
`assertEqual(decoded, value)` round-trip check does **not** detect that the
mutation silently changed a value's *type* (`bool` -> `int`) even though it
changed nothing the equality operator can see. This is a real latent
blind spot in the round-trip gate itself — exactly "o que o loop encontrou
que o fix manual não viu" (the manual #148 fix never exercised this because
it never touched boolean formatting).

**Kept fix (not an encoder change — a gate hardening)**: added
`toon_contract_runner.strict_equal()`, a round-trip comparison that treats
`bool` and `int` as distinct types (recursing through dicts/lists), and
wired it into both `tests/python/test_toon.py`'s `_assert_round_trip` and
`tests/python/test_toon_contract.py`'s golden-corpus checks alongside the
plain `==` check. Re-running the mutation against the *hardened* gate:

```python
>>> strict_equal({"active": 1}, {"active": True})
False   # now caught directly by the round-trip invariant, not incidentally
```

`simplicio_mapper/toon.py` itself is unchanged by this iteration — the
mutation was reverted (`git checkout -- simplicio_mapper/toon.py`), never
committed. Only the test/gate hardening (`strict_equal` + 4 new regression
tests in `tests/python/test_toon_contract.py`'s `StrictEqualTest`) was kept.

## Iteration 2 — heterogeneous-keyset tabular grouping (IDENTIFIED, DEFERRED)

**Analysis, not a code mutation.** Measured where `project-map.json`'s
remaining post-#148 token budget goes: the single `$.agent_tree.children`
fallback (reason `nested_containers`, per `toon_fallbacks`) accounts for
**~23% of the whole document's compact-JSON size** (50,800 of 218,383
chars). Its elements are *almost* uniform — file-leaf nodes share
`{bh_address, agent_id, path, language, roles}`, but a handful of
directory nodes have `{bh_address, agent_id, module, children}` instead —
so `_is_uniform_object_array`'s all-or-nothing keyset check disqualifies
the entire array from the tabular path, and the whole 20-node tree
(recursively, hundreds of nodes) falls back to embedded JSON.

**Why this was not attempted as a mutation**: the only way to capture this
win is a new wire-format primitive — e.g. grouping array elements by
keyset into multiple back-to-back `[N]{fields}:` chunks under one array
entry, or a recursive/nested tabular block for tree-shaped data. Both are
**format extensions**, not an encoder heuristic tweak: they would require
amending `TOON-CONTRACT.md` (a version bump, per its own drift-gate
design) and regenerating every fixture in `fixtures/toon-golden/` that the
new rule touches, in every language that implements the contract. Shipping
that silently from an unattended mutate/evaluate loop — even one that
passes the current gate, since the current gate only checks *this repo's*
codec against *the current* contract, not cross-language compatibility —
would be exactly the kind of drift TOON-CONTRACT.md exists to prevent (see
its own "8 independent codecs, already diverging" motivation). It is
recorded here as a concrete, measured follow-up candidate for a deliberate
TOON-CONTRACT v2 proposal, not implemented in this pilot.

## Result

| | Score (approx tokens) |
|---|---:|
| Baseline (post-#148) | 68417 |
| Final (post-pilot) | 68417 |
| Delta | 0 (tied) |

**No encoder heuristic improvement survived the gate within the current
TOON-CONTRACT wire format.** This is an honest negative result on the
score axis — the pilot found no further safe win in `simplicio_mapper/toon.py`
itself beyond #148 — but it produced two things of real value:

1. A closed blind spot in the round-trip safety gate itself
   (`strict_equal`, bool/int type-strictness), which protects every future
   encoder change (autoresearch or human) from the same class of silent
   type-narrowing mutation.
2. A measured, concrete, and correctly-scoped-out structural finding
   (heterogeneous-keyset tabular grouping, ~23% of `project-map.json`) for
   a future deliberate TOON-CONTRACT v2 proposal, instead of an ad hoc
   wire-format change slipped in through a heuristic mutation loop.

`simplicio.savings-event/v1` emitted to `.receipts/` (repo-local,
gitignored execution evidence per AGENTS.md's receipt convention):
`source=autoresearch`, `baseline_score_tokens_approx=68417`,
`final_score_tokens_approx=68417`, `saved_tokens_approx=0`,
`mutation_kept=false`.

## Retrospective

- The anti-Goodhart gate is only as strong as its equality check. A loop
  optimizing purely for a shorter score needs a *type-aware*, not just
  *value-aware*, round-trip check, or it can find "improvements" a human
  reviewer would immediately reject on sight (`true`/`false` -> `1`/`0`
  reads as an obviously bad idea to a person; a scoring-only loop has no
  such instinct and would have shipped it here if the incidental format
  assertions hadn't happened to exist).
- The single largest remaining token-budget lever after #148
  (`agent_tree.children`'s heterogeneous keysets) is real and worth
  pursuing, but correctly belongs to a deliberate wire-format proposal
  process (TOON-CONTRACT.md's own versioning/drift discipline), not an
  unattended heuristic-mutation loop. Route: open a follow-up issue
  proposing "TOON-CONTRACT v2: heterogeneous-keyset tabular grouping",
  with `agent_tree.children` as the worked example and this log as
  supporting measurement.
