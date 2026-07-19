# Definition of Done — 4-layer framework (issue #246, hub #579)

This document operationalizes a 4-layer Definition of Done rolled out across
the Simplicio ecosystem. It complements — never replaces — the existing
per-PR DoD checklist in `AGENTS.md`/`CLAUDE.md`; that checklist is Layer 1
made concrete for this repo. Read `AGENTS.md` first.

## Why this exists: two real bugs, same session

The 4-layer framework was not written from theory. It exists because two
real, silent-corruption bugs were found and fixed in this same working
session, and both would have shipped past a DoD that only checks "tests are
green" and "coverage is high":

1. **`simplicio/mechanical_edit.py` — silent file corruption
   (commit `d24e18c`).** `_operation_order()` required *every* operation in
   the whole plan to carry an integer `order` before honoring any of them,
   while `_validate_overlaps()` only requires both operations on the *same
   path* to be explicitly ordered before permitting their ranges to overlap.
   That mismatch let a plan pass validation — an explicitly ordered,
   dependent pair of edits on one file, where the second op's line numbers
   were computed against the state *after* the first — and then get applied
   **out of order**, against the wrong, pre-shift line numbers, the moment
   the plan also touched an unrelated file with any operation lacking
   `order` (e.g. `create_file`, which never carries one). Reproduced live
   via `simplicio-py mechanical-edit --apply`: a 3-operation plan touching
   two files corrupted the untouched-looking file into a duplicated/garbled
   line while reporting `status: ok` with **zero errors**. A unit test
   asserting "the fixed regression input now passes" would not have caught
   the general class of the bug — only a property across random N-file,
   random-order plans does (see Layer 2 below).
2. **`simplicio_mapper/mapper/graph.py` — wrong symbol line numbers
   (commit `464cc03` in `simplicio-mapper`).** Every language pattern in
   `_symbol_definitions_for_file` anchored on `^\s*<keyword>` with
   `re.MULTILINE`. Since `\s` also matches newlines, a definition preceded
   by one or more blank lines let `^` anchor at an earlier blank line and
   let `\s*` swallow the intervening newlines, shifting the reported symbol
   line to that blank line instead of the real `def`/`class` line. This hit
   the common case — any top-level function preceded by PEP8 blank lines, or
   a module docstring — and corrupted every consumer of symbol-index line
   numbers: `ask callers/callees/tests-for`, and the call-graph's same-line
   self-call filter, which **silently fabricated** "function calls itself"
   edges because the filter's line comparison stopped matching. Exit code
   was 0; status was "ok"; the output was simply wrong.

Both bugs share the same shape: **the tool reported success while producing
a wrong result**, on a class of input (multi-file plans; symbols preceded by
blank lines) that a narrow, hand-picked unit test would not exercise by
construction. That is exactly what Layer 2 (property/invariant testing,
fixtures with real code) exists to catch, and exactly why Layer 1's "green
tests" is necessary but insufficient.

## Layer 1 — Universal (every PR, every repo, no exceptions)

- Implementation matches the accepted scope — no silent extra refactor.
- Unit tests for the touched logic.
- Regression test for every bug fixed (not just the fix — a test that fails
  on the pre-fix code and passes on the post-fix code; see both examples
  above, plus the generalized Hypothesis version for #1).
- Coverage with a **real, mechanically-enforced** gate — not a number quoted
  in a PR description. See "Coverage gate: current state" below for exactly
  what "mechanical" means in this repo right now.
- Evidence of real execution: actual command + actual output, not "should
  work."
- Adversarial verification pass after green: re-read the acceptance
  criteria against the actual result, exercise the feature for real plus one
  edge case and one error path.
- No secret, no stray `print()`/debug output, no unowned/undated TODO.

### Coverage gate: current state (issue #246)

`[tool.coverage.report].fail_under = 85` and
`[tool.coverage.simplicio_critical]` (90% floor on `cli.py`, `pipeline.py`,
`mechanical_edit.py`, `mapper.py`, `execution_contract.py`, `doctor.py`) were
already added to `pyproject.toml` in commit `62ebd81` (#205), together with
`scripts/coverage_gate.py`. That commit also wired a dedicated `coverage` CI
job. **Hours later, the same day, commit `d7ff8c9` removed
`.github/workflows/` entirely** — GitHub Actions billing lockout plus a
decision to centralize CI/CD around `simplicio-runtime` — which deleted that
job along with every other workflow in this repo. `AGENTS.md`/`CLAUDE.md`
still described this as "CI's `python` job runs `pytest` without `--cov`,"
which was already stale on top of being incomplete: there is currently **no
`.github/workflows/ci.yml` in this repo at all**.

Since GitHub Actions cannot run here right now regardless of what YAML
exists (billing lockout), re-adding a workflow file would not be a real
gate — it would be a file that never executes. The real, mechanically
enforced gate as of this issue lives in
`.claude/hooks/pre-commit.sh`/`.ps1`: when `pytest-cov` is installed, every
commit touching a staged `.py` file now runs
`pytest -q --cov=simplicio --cov-report=term-missing --cov-fail-under=85`
and blocks the commit if the floor is missed (falls back to plain
`pytest -q -x` if `pytest-cov` isn't installed, rather than silently
skipping the whole test run). Verified locally at 85.71% total coverage
before wiring this in. The stricter 90%-critical check
(`scripts/coverage_gate.py`) is **not** wired into the hook because it
currently fails (`mechanical_edit.py` 71%, `doctor.py` 73%,
`execution_contract.py` 88%, `pipeline.py` 87.5%) — closing that gap is
real work, tracked in the Layer 3/4 issue below, not something to fake past
via a lower bar.

The workflow-removal regression was closed during the `main` branch migration
(issue #98): the obsolete tests that opened `.github/workflows/*.yml` were
replaced by local-gate and branch-contract tests. No test now requires a
GitHub Actions file to exist.

## Layer 2 — Risk-surface-driven (declared per PR)

Applied when the surface actually present in the diff calls for it — declare
which apply in the PR description, do not skip silently:

- **Property/fuzz testing** for parsing, transformation, or partitioning
  logic (Hypothesis in this repo — see
  `tests/python/test_mechanical_edit.py`'s
  `test_explicit_order_survives_any_shuffle_of_unordered_ops_across_n_files`,
  added by this issue, which generalizes the `d24e18c` regression across a
  random number of ordered files, a random number of unordered "noise"
  files, and every permutation of the combined operation list).
- **Fixtures with real code** for anything doing code analysis (mirrors the
  `mapper/graph.py` bug class — a hand-crafted one-liner input hides bugs
  that only show up on code shaped like what people actually write:
  docstrings, blank-line spacing, multi-line signatures).
- **Invariant review** whenever two code paths process the same collection —
  exactly the `_operation_order()` vs `_validate_overlaps()` mismatch: two
  functions each independently decided what "explicitly ordered" means for
  the same operation list, and nobody checked they agreed at the same
  granularity.
- **Assertions on the observable result**, not just status/exit-code — both
  bugs above returned `status: ok` / exit 0 while producing wrong output.
  "The command exited zero" is not evidence; "the file byte-for-byte matches
  what correct ordering produces" is.
- **Benchmark with baseline + gate** for any change touching a hot path
  (`precedent.py`'s embedding/ranking path, `mapper.py`'s symbol scan,
  `pipeline.py`'s run loop) — `bench.py` is the existing harness; see the
  Layer 3/4 issue for turning its single-run numbers into a real gate.
- **Invocation-mode matrix** for CLI commands with more than one entry shape
  (`simplicio-cli` / `simplicio-py` / `simplicio-dev-cli` all resolve to the
  same `main()` — a change verified against only one alias is not verified).
- **E2E with evidence** when the change touches the embedded Playwright
  starter harness (`tests/e2e/`) — this is rare for work inside `simplicio/`
  itself.

## Layer 3 — Sprint/release cadence

Not required per-PR; required periodically so debt doesn't accumulate
silently:

- **Mutation testing** (`mutmut`) on the modules most likely to have this
  exact "reports success, silently wrong" failure shape — starting with the
  two modules that had a real bug this session: `mechanical_edit.py` and
  `precedent.py`.
- **Flaky-test quarantine** — a test that fails intermittently is worse than
  one that fails always; tag and track, don't ignore.
- **Documentation anti-rot** — this issue itself is a case study: two
  "known gap" paragraphs in `AGENTS.md`/`CLAUDE.md` had drifted out of sync
  with reality (first missing `--cov`, then the entire CI workflow directory
  being gone) without anyone flagging it. A periodic doc-vs-reality pass
  catches this class before it misleads the next task.

## Layer 4 — Ecosystem/release

Cross-repo and release-level checks, generally too expensive to run per-PR:

- **Contract tests** between repos that exchange a schema — this repo
  consumes `simplicio.map-result/v1` (from `simplicio-mapper`) and produces
  `simplicio.mechanical-edit/v1` (consumed by callers like
  `simplicio-loop`/`simplicio-runtime`). A schema change on either side
  needs a test that fails when the two sides disagree, not just when either
  side's own tests pass.
- **Eval / pass-rate** for the parts of this repo that route through an LLM
  (`task`/`run`, precedent + skill-router selection) — a single successful
  run proves nothing about reliability; `bench.py` is the seed for turning
  that into an N-run pass-rate.
- **Canary against real external dependencies** — PyPI publish, the
  `simplicio` native runtime binary delegation path (`_try_native_edit`),
  the optional provider SDKs.
- **Hermetic build + provenance** for the published `simplicio-cli` wheel.
- **Telemetry with a path back** — `simplicio/observability.py`'s
  `emit_event`/`.simplicio/events.jsonl` already exists for this; the open
  work is making sure a production failure surfaces back to a fixable
  report, not just a log line nobody reads.

Full step-by-step plan for Layers 3/4 (mutation testing priorities, the
contract-test approach for both schema directions, and the eval-harness plan
for `bench.py`): see #247 (references #246 and hub issue
`simplicio-loop#579`).
