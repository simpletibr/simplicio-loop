# Issue #691 local evidence

Date: 2026-09-07. Repository: `wesleysimplicio/simplicio-dev-cli`.

## Delivered locally

- Dev CLI-owned `TextEdit`, single-anchor replacement, canonical edit-plan and
  versioned receipt APIs.
- Mapper binding contains repository id, generation, source-tree id, and
  source hashes; plans copy expected hashes into their first operation for each
  file.
- Typed fail-closed conflicts for missing target/anchor, ambiguous anchor,
  hash drift, invalid path, unsupported scaffold, and malformed plans.
- Pure deterministic scaffold plans for Rust crate/binary, Python package, and
  Node package, plus a versioned scaffold receipt serializer.
- Canonical `simplicio edit` plans use the Dev CLI kernel and do not delegate
  to the legacy native Mapper edit vocabulary.
- The legacy Runtime adapter accepts the installed Runtime v3.8.47
  `success`/`final_status` receipt after human-readable dry-run text, while
  refusing translation when Dev CLI hash or Mapper-binding semantics would be
  lost.
- JSON schemas are checked-in below `contracts/`; the ownership boundary and
  Runtime handoff are documented in
  `docs/deterministic-edit-scaffold.md`.

## Validation

| Check | Result |
|---|---|
| Issue/focused regression and command snapshots | 167 passed, 2 skipped |
| Independent adversarial pass | PASS: real canonical CLI apply, hash drift, ambiguous anchor, workspace escape, four stable scaffolds |
| Edit-kernel benchmark | 10 x 1,000 calls; median 30.044 microseconds/call, min 28.154, max 35.545 |
| Full local pytest with coverage | 2,745 passed, 22 skipped, 21 unrelated environment/baseline failures |
| Full global coverage | 85.56%, above the 85% floor |
| Final relevant module coverage | `mechanical_edit.py` 90.70%; `scaffold_contract.py` 93.24% |
| Generated dependency documentation | PASS |

The full-suite failures are pre-existing/environmental: unavailable installed
CLI/Mapper entrypoints, disabled provider smoke, stale effect-boundary
baseline, unrelated package-data/template fixtures, and existing benchmark
or doctor assumptions. They do not touch the #691 focused suite. The existing
critical coverage gate also remains blocked by the unrelated
`simplicio/mapper.py` 85.46% versus 90% floor.

The coverage gate passes the global floor and the changed critical
`mechanical_edit.py` module; it remains red only for the pre-existing critical
`simplicio/mapper.py` module at 85.46% versus 90%.

`ruff check .` and `ruff format --check .` remain red on pre-existing files;
all changed Python files pass targeted Ruff checks. `mypy simplicio` reports
the repository's existing 12 errors in six unrelated modules. Package build
could not run because the environment has no `build` module; installing a
new dependency was not authorized.

## External conformance boundary

No hosted GitHub check, Runtime #5525 implementation, or live
Loop -> Runtime -> Dev CLI E2E was available in this checkout. The local
offline/effect boundary reuses `simplicio.mechanical_edit.execute_plan`, but
cross-repository Runtime conformance remains unverified and is not claimed as
local evidence.
