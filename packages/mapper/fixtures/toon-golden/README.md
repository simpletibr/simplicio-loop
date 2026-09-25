# TOON golden corpus

Conformance fixtures for `TOON-CONTRACT.md` (issue #149). See that document
for the full spec; this file only describes the corpus layout.

```
manifest.json            case index (id, tags, description) for valid/invalid
valid/<case-id>/input.json     JSON value
valid/<case-id>/expected.toon  canonical TOON encoding (produced by this
                                repo's simplicio_mapper.toon.encode_toon —
                                the canonical reference implementation)
invalid/<case-id>/input.toon   malformed/truncated TOON text
invalid/<case-id>/meta.json    {"error_class": "...", "reason_contains": "...", "description": "..."}
```

Run the conformance check for this repo's codec:

```bash
python3 scripts/toon_contract_runner.py
# or via the test suite:
python3 -m unittest tests.python.test_toon_contract
```

A `valid` case passes when:

1. `decode(encode(input.json)) == input.json` (round-trip lossless), and
2. `decode(expected.toon) == input.json`.

Byte-identical match between a fresh `encode(input.json)` and the committed
`expected.toon` is checked too for this repo's own codec (it is the
reference implementation), but is **not** a cross-language requirement —
another repo's codec may format whitespace/ordering differently as long as
losslessness holds.

An `invalid` case passes when `decode(input.toon)` raises an error matching
`meta.json`'s `error_class` (always a `ValueError`-equivalent, never a bare
index/key error — see `TOON-CONTRACT.md` §5).

After editing this corpus or `TOON-CONTRACT.md`, run
`python3 scripts/sync_toon_contract.py update` and commit the resulting
`.contract-hash` change — `scripts/sync_toon_contract.py check` (wired into
`scripts/check-version-sync.js`'s sibling checks / CI) fails the build if
the two drift apart.
