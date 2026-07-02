# TOON-CONTRACT — the shared TOON codec spec for the Simplicio ecosystem

Status: v1 (issue #149). Canonical host: `simplicio-mapper` (this repo) — the
ecosystem's principal producer of LLM survey context. Vendor this file
verbatim into any other repo that ships its own TOON codec, the same way
`YOOL_TUPLE_HAMT.md` is vendored (see `scripts/sync_toon_contract.py` in
this repo for the drift check on the canonical copy; a consuming repo's own
vendoring/sync tooling is out of scope here — see "Cross-repo adoption"
below).

## Why this document exists

The TOON rollout (#144) produced **8 independent codec implementations in 3
languages** across the ecosystem: `simplicio_mapper/toon.py` (this repo),
`agent/toon_codec.py`, `simplicio/toon_codec.py` (dev-cli), `scripts/toon_codec.py`
(loop), `lib/format/toon.ts` (marketing), `kernel/utils/toon_codec.py` (prompt),
`sendsprint/llm/toon_codec.py` (sprint), `src/toon_encode.rs` (runtime).

Drift is not hypothetical — it is already manifest as verified, divergent bugs:

| Repo | Bug (verified in code) |
|---|---|
| marketing | `needsQuoting` (`lib/format/toon.ts:58-65`) misses strings that both start and end with a quote character — `"quoted"` round-trips lossy |
| mapper (this repo, pre-#148) | `decode_toon` raised a bare `IndexError` on a truncated tabular block (`toon.py:252-261`, `:226-232`) |
| sprint | encoder emits unsanitized dict keys; decoder ignores a row/field-count mismatch and silently drops excess values |
| loop | an unquoted scalar that looks like `[1]` decodes as a one-element list instead of the string/number `[1]` (documented in the file itself, `scripts/toon_codec.py:33-42`) |

Each repo only tests its own happy paths. As cross-consumption seams close
(dev-cli/loop consuming mapper TOON, runtime serving TOON over MCP), one
repo's encoder meets another repo's decoder — every divergence becomes
silent prompt corruption instead of a loud test failure.

## 1. Scope

This contract fixes the **wire format** and the **error contract** for any
TOON codec in the Simplicio ecosystem. It does not mandate an
implementation language or library — only observable behavior, verified by
the golden corpus at `fixtures/toon-golden/` (§6).

## 2. Flag convention — `SIMPLICIO_TOON`

- Any tool that can emit either JSON or TOON for the same payload MUST gate
  the choice behind an env var in the `SIMPLICIO_TOON` family (e.g.
  `SIMPLICIO_TOON=1` / `SIMPLICIO_TOON=0`), in addition to any explicit CLI
  flag (this repo's is `--for-llm toon`).
- The flag MUST be read **once per session/process**, not per call. For any
  agent/chat surface where prompt caching matters (e.g. simplicio-agent),
  switching the wire format mid-conversation invalidates the cached prefix
  — trading a one-time ~40% token win for the loss of a much larger
  (~75%+) prompt-cache discount on every subsequent turn is a net loss.
  Kill-switch semantics: an operator can force JSON globally by unsetting/
  zeroing the flag; a codec MUST NOT re-decide the format per invocation
  once a session has started emitting one format.

## 3. Fallback report — `toon_fallbacks`

Any array that cannot take the tabular or inline-scalar shape (§4) MUST NOT
silently disappear into embedded JSON. Every codec MUST be able to report,
on request, the set of arrays that fell back and why:

```json
{"toon_fallbacks": [{"path": "$.items", "reason": "differing_keys"}]}
```

- `path` — `$` for the root value, dotted below it (e.g. `$.meta.items`).
  List indices are not enumerated individually; the array itself is one
  fallback entry.
- `reason` — one of `differing_keys`, `mixed_types`, `nested_containers`
  (a dict-valued cell, or a list-of-non-scalars cell), or an
  implementation-specific string if none of those apply. New reasons MAY be
  added; consumers MUST NOT hard-fail on an unrecognized reason string.
- A codec that only exposes an encode-to-string API (no separate report
  channel) MUST at minimum log the report (e.g. to stderr as the JSON
  above) rather than discard it — this repo's `--for-llm toon` does this
  automatically on every command (index/inspect/handoff/ask) that supports
  it. This closes the open DoD item from #144/#88/#75/#93/#301: "log do
  motivo", which was silent in every implementation as of #148.

## 4. Encoding rules

- **Objects** render as `key: value` lines, 2-space indent per nesting
  level. A non-empty nested object renders as `key:` followed by an
  indented block; an empty object renders inline as `key: {}`.
- **Uniform object arrays** — every element is a dict, all elements share
  the exact same key set, and every value is either a scalar or a **list of
  scalars** (not a dict, not a list containing a dict/list) — render as a
  tabular block:

  ```
  key[N]{field1,field2}:
    v1,v2
    v3,v4
  ```

  A cell whose value is a list of scalars renders as a bracketed,
  comma-separated group inline in the row: `[a,b,c]`. An empty list cell is
  `[]`. This is the fix landed in #148: the mapper's own real arrays
  (`files[].exports/imports/roles`, `precedent-index.items[].tags`) are
  exactly this shape, and rejecting list cells from the tabular path is
  what caused the measured 4.5–8.4% reduction instead of the ~40% upstream
  benchmark.
- **Scalar arrays** render as an inline list: `key[N]: v1,v2,v3`.
- **Non-uniform arrays** (differing keys, a mix of dict and non-dict
  elements, or a dict-valued cell / list-of-non-scalars cell inside an
  otherwise-uniform element set) fall back to embedded compact JSON for
  that value, and MUST be recorded per §3 — never silently.
- **Empty array**: `key: []`. **Empty object**: `key: {}`.
- **Scalars** are unquoted unless quoting is required to stay unambiguous:
  empty string; leading/trailing whitespace; contains a comma, colon,
  newline, `{`, `[`, or `]`; starts with a literal `"` character (the
  marketing bug in §0 — a string starting **and** ending with `"` still
  needs quoting, both ends, or the round trip is lossy); equals the bare
  literal `true`/`false`/`null`; or parses as a number. Quoting uses
  standard JSON string escaping (`json.dumps`-equivalent).

## 5. Decode error contract

- `decode(text)` for malformed or truncated `text` MUST raise a typed error
  that is a `ValueError` (Python) / `Error` subclass with a stable
  discriminator (JS/TS) / typed error (Rust) — **never** an untyped
  index/key/attribute-style error that leaks the implementation's internal
  parsing state (`IndexError`, `KeyError`, `undefined is not a function`,
  a Rust panic).
- A tabular block whose declared row count (`[N]`) exceeds the number of
  data lines actually present is truncated input → decode error, not a
  partial/garbage result.
- A tabular row whose value count does not match the declared field count
  is a row/field mismatch → decode error. **Do not silently drop excess
  values or leave missing fields unset** (the sprint bug in §0) — either
  behavior hides real data loss from the caller.
- A bare `[1]`-shaped token (or any single-element scalar list) inside a
  tabular cell decodes as a **one-element list**, never as the scalar
  `1`/`"[1]"` — this is unambiguous by construction because any scalar
  string that genuinely starts with `[` is quoted at encode time (§4), so
  an *unquoted* leading `[` in a cell only ever comes from the list-cell
  encoding. A codec whose quoting rule does not cover `[`/`]` (the loop bug
  in §0) MUST fix the quoting rule, not special-case `[1]` in the decoder.
- `decode(encode(x)) == x` for every JSON-compatible `x`. This is the
  primary invariant checked by the golden corpus (§6).

## 6. Golden corpus — `fixtures/toon-golden/`

```
fixtures/toon-golden/
  manifest.json           # case index: id, description, tags, kind (valid|invalid)
  valid/<case-id>/input.json     # JSON value
  valid/<case-id>/expected.toon  # canonical TOON encoding (produced by this
                                  # repo's simplicio_mapper.toon.encode_toon)
  invalid/<case-id>/input.toon   # malformed/truncated TOON text
  invalid/<case-id>/meta.json    # {"error_class": "ValueError", "reason_contains": "..."}
```

A conformant codec, run against every `valid/*` case, MUST:
1. Encode `input.json` and decode its own output back to `input.json`
   (round-trip lossless) — byte-identical match to `expected.toon` is
   encouraged but not required across languages (whitespace/ordering
   details may differ); losslessness is the hard requirement.
2. Decode `expected.toon` back to `input.json` exactly.

And, against every `invalid/*` case:
3. Raise a decode error matching `meta.json`'s `error_class` family (a
   `ValueError`-equivalent, never a bare index/key error per §5).

This repo's runner: `scripts/toon_contract_runner.py` (Python, wired into
`tests/python/test_toon_contract.py`) and `tests/unit/toon-contract.test.js`
(Node — see that file's header for why it currently reports a labeled skip
rather than a fake pass: this repo has no Node TOON codec yet, tracked by
the pre-existing parity NOTE in `bin/map.js`).

## 7. Drift gate

`scripts/sync_toon_contract.py check` hashes this file plus the golden
corpus and compares it against the committed `fixtures/toon-golden/.contract-hash`.
Run `scripts/sync_toon_contract.py update` after any change to this file or
the corpus, and commit the updated hash in the same change — this catches
edits to the contract or its fixtures that were not accompanied by a
deliberate re-sync. It does **not** vendor into or verify the other 7
ecosystem repos' copies; that is per-repo follow-up (see below).

## 8. Cross-repo adoption (tracked, not done in this change)

Per-repo adoption issues (vendor this file, fix the bug in §0 assigned to
that repo, wire the golden corpus into that repo's own test runner) are
follow-up work, not implemented by this PR — this PR only lands the spec
and the corpus in the canonical host (`simplicio-mapper`). See the parent
issue (#149) for the target list: `simplicio-loop-marketing` (`toon.ts`
quoting bug), `simplicio-sprint` (`toon_codec.py` row-mismatch bug),
`simplicio-loop` (`toon_codec.py` `[1]`-ambiguity bug), plus the remaining
4 repos for spec adoption without a known bug of their own yet.
