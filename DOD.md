# DOD.md — the canonical 4-layer Definition of Done

> This is the **canonical source** referenced by every other repo in the ecosystem
> (`simplicio-mapper`, `simplicio-dev-cli`, `simplicio-runtime`, `simplicio-agent`,
> `simplicio-sprint`, `simplicio-loop-marketing`, `simplicio-local-any-llm-16gb`, and the rest —
> see issue [#579](https://github.com/simpletibr/simplicio-loop/issues/579)). Each of those
> repos ADOPTS this framework, translated into their own stack's tooling; this file is where the
> framework itself is DEFINED. Do not fork the layer definitions per repo — fork the *tool
> mapping* (Hypothesis vs proptest vs fast-check vs libFuzzer) and link back here.

## Why this exists

Two real bugs, found in the same bug-hunt session, in two repos that already had a documented
7-pillar DoD (implementation + unit + integration + system + regression + perf-benchmark +
coverage ≥85-90%) and green CI:

1. **`simplicio-dev-cli` / `mechanical_edit.py`** — `_operation_order()` decided whether to honor
   an explicit `order` field by checking `all(...)` over the **whole plan**, while
   `_validate_overlaps()` decides overlap **per file**. A multi-file plan with correct explicit
   ordering in file A, plus any order-less operation in file B (e.g. a plain `create_file`),
   applied A's edits out of order — **silently corrupting the file while reporting
   `"status": "ok"`**.
2. **`simplicio-mapper` / `mapper/graph.py`** — the symbol-detection regex anchors on `^\s*` under
   `re.MULTILINE`. Because `\s` also matches `\n`, a definition preceded by blank line(s) — the
   single most common PEP8 pattern in existence — has `match.start()` land on the blank line, not
   the real `def`/`class` line, **silently corrupting the reported line number in nearly every
   real `symbol-index.json`/`call-graph.json`**, including fabricating phantom self-call edges in
   the call graph.

Both are now fixed. The point of this document is not the bugs — it is **why the existing DoD
did not catch either one**, and what closes that gap mechanically instead of by exhortation:

- **Coverage% measures executed lines, not exercised scenarios.** Both offending lines already
  had test coverage — never with the *combination* or *input shape* that exposes the bug.
- **Both are interaction bugs between two functions with different granularity of scope**
  (whole-plan vs per-file). No unit test of either function in isolation catches this.
- **Minimal test fixtures hide real-format bugs.** The mapper bug only appears on idiomatic PEP8
  code (docstring + blank line before `def`), never on compact hand-written snippets.
- **The tested success criterion was "did not crash" / "status ok", not "is the final content
  correct."** The dev-cli bug reported success while corrupting the file.
- Regression testing, by definition, only catches what was already seen once.

No single layer below closes all of this alone. The four layers are complementary: Layer 1 is
the floor every change stands on; Layer 2 targets exactly the blind spot the two real bugs fell
into; Layers 3-4 catch what only shows up in aggregate or across repo boundaries.

## The 4 layers

```
Layer 1 — Universal            every issue, every PR, no exception
Layer 2 — Risk-surface         declared per-PR, triggered by what the diff touches
Layer 3 — Test-quality         per sprint/release, questions the tests themselves
Layer 4 — Ecosystem            per release, questions the boundary between repos
```

### Layer 1 — Universal (every issue, every PR)

Non-negotiable floor. No "TRIVIAL/SMALL" exception skips any of these.

| # | Requirement | Mechanical gate |
|---|---|---|
| 1.1 | Implementation | the actual code change, scoped to the task — no hidden refactor |
| 1.2 | Unit tests | cover the isolated logic touched |
| 1.3 | Regression test | every real bug fixed gets a test that fails on the old code and passes on the new one — not just "the fix", the *regression proof* |
| 1.4 | Coverage gate, enforced in CI | a real `--cov-fail-under`/equivalent threshold that BLOCKS merge, not a number quoted in a PR description that nobody re-checks |
| 1.5 | Evidence of real execution | command output, generated artifact, or recorded run — never "I didn't run it but it should work" |
| 1.6 | Adversarial verification pass, post-green | one ORTHOGONAL pass after the gate is green — re-read the AC against the result, exercise one edge case, exercise one error path — not a repeat of the same check that just passed |
| 1.7 | No secret / no debug print / no orphan TODO | `git diff` scanned for credentials, `print()`/`console.log()` left in library code, and any TODO without an owner+deadline |

This layer is deliberately close to (and does not replace) each repo's existing 7-pillar DoD —
it is the floor that DoD already tried to build, restated so every repo in the ecosystem points
at the same floor instead of eleven near-identical copies drifting apart.

### Layer 2 — Risk-surface (declared per-PR, per issue #579)

Triggered by **what the diff touches**, not by ceremony. A PR that touches none of these
surfaces skips this layer explicitly (state that in the PR, don't leave it silently blank — see
`scripts/deep_correctness_gate.py` below, which checks for an explicit answer either way).

| # | Requirement | Trigger | Mechanical gate |
|---|---|---|---|
| 2.1 | Property-based testing / fuzzing | the diff touches parsing, structured-data transformation (edit plans, graphs, trees, ASTs), or any code where two components process the same structure via different code paths | Hypothesis (Python) / `proptest`+`cargo-fuzz` (Rust) / `fast-check` (TypeScript) / libFuzzer+AFL++ (C/C++) generates combinations instead of relying only on hand-written examples — need not cover 100% of the code, only the "processes a complex structure" paths |
| 2.2 | Fixture with real code, not minimalist snippets | the change analyzes/transforms source code | at least one test case uses a real, idiomatic sample (not an artificial 3-line snippet) — this is where format bugs like the mapper's blank-line regex actually surface |
| 2.3 | Invariant-review checklist | two functions/modules process the same collection/structure with different logic | the PR explicitly answers: **"do these two functions use the same granularity/partitioning key?"** — this is the exact question that would have caught both real bugs, and it needs no new test to work |
| 2.4 | Assertion on the observable result, not the self-reported status | integration/system tests apply a change and check success | the test reads the *actual final content* (file bytes, generated artifact, output value) — never only the tool's exit code / `"status": "ok"` field, which is exactly what the dev-cli bug faked |
| 2.5 | Benchmark with baseline + gate | the change touches a hot path (retrieval, indexing, parsing at scale) | a measured number compared against a committed baseline, not an ad hoc "seems fine" |
| 2.6 | Invocation-mode matrix | the surface has more than one entry point (CLI flag combos, sync/async, local/remote fan-out tiers) | enumerate the modes actually exercised and which were skipped, so "works" doesn't silently mean "works in the one mode I tried" |
| 2.7 | E2E with evidence | the change alters an end-to-end observable flow (UI, CLI-against-a-real-fixture, scaffolder) | trace + screenshot + video, or the CLI/lib equivalent (captured stdout, generated artifact, targeted test run) — see each repo's own DoD for what "evidence" means for a non-browser surface |

### Layer 3 — Test-quality (per sprint / release)

Questions the *tests themselves*, not the code under test. Green tests over a weak suite is the
mechanism that let both real bugs through disguised as "covered."

| # | Requirement | Mechanical gate |
|---|---|---|
| 3.1 | Mutation testing | a sampled mutation-testing run (`mutmut`/`cosmic-ray` Python, `cargo-mutants` Rust, `stryker` TS, PIT-style for others) on the sprint's touched modules — a suite that stays green under a real mutant is a suite that wasn't actually checking that line |
| 3.2 | Flaky-test quarantine with a deadline | any test flagged flaky (`scripts/flaky_gate.py`-style repeat-run detection) gets quarantined with an owner and an expiry date, never silently skipped forever |
| 3.3 | Documentation anti-rot | docs that cite a command/flag/schema are checked against the real CLI/contract (this repo's own `scripts/claims_audit.py` check 9, "prose-commands-valid", is the reference implementation) — a doc drifting from the code it describes is a released bug in the making |

### Layer 4 — Ecosystem (per release)

Questions the *boundary between repos* — nothing inside a single repo's test suite can catch a
contract break at the seam between two of them.

| # | Requirement | Mechanical gate |
|---|---|---|
| 4.1 | Contract tests between repos | the schema/CLI surface one repo exposes (`simplicio.loop-execution/v1`, `--describe-cli`, `simplicio.savings-event/v1`, etc.) is validated by BOTH the producer and the consumer's test suite, not asserted in prose on one side only |
| 4.2 | Pass-rate eval for any LLM-touching component | a component whose correctness depends on model output (skill routing, precedent retrieval, prompt-driven codegen) is scored against a fixed eval set with a tracked pass-rate, not "it looked right in the one example I tried" |
| 4.3 | Canary against a real external dependency | a scheduled, low-frequency real call against the actual external service/API a component depends on (not a mock) — catches drift the mocked test suite structurally cannot see |
| 4.4 | Hermetic build + provenance | the release artifact is built from a clean checkout with pinned dependencies and its origin (commit, builder, timestamp) is recorded — a build that can't be reproduced can't be trusted to match its own test run |
| 4.5 | Telemetry with a path back to the fix | a production signal (error rate, savings-event ledger, completion-oracle) that regresses has a documented path to the issue/PR that will address it — telemetry that nobody routes anywhere is not a gate, it's a graveyard |

## What is mechanically enforced today vs. proposed

Layers 1-2's mechanically-checkable subset is enforced today by
[`scripts/deep_correctness_gate.py`](scripts/deep_correctness_gate.py) (see its own docstring for
the exact checks and their heuristics, and `tests/test_deep_correctness_gate_unit.py` for the
proof). It does **not** attempt to automate all of Layers 1-2 — mutation testing, real contract
tests, and LLM pass-rate evals are bigger than a single mechanical script and are tracked as
follow-up work in issue #579's comment thread, not faked here as "done."

What it checks mechanically, today:

- **1.3 (regression test on a fix)** — a `fix:`/`fix(scope):` commit message in the range being
  checked must be accompanied by a diff hunk that *adds* lines to a test-shaped file path.
- **2.3 (invariant question answered)** — when a PR body is supplied, it must contain a non-empty
  `## Invariant(e)` section (English or Portuguese heading) — presence of an explicit answer, not
  a judgment on whether the answer is correct.
- **1.4 (coverage gate enforced in CI)** — the target repo's `.github/workflows/*.yml` must
  contain a real coverage-gate signal (`--cov-fail-under`, `coverage_gate.py`, `codecov-action`,
  etc.), not merely a coverage number asserted in a doc.

Everything else in Layers 1-2, and all of Layers 3-4, remains a per-repo/PR human-and-checklist
practice today. Turning more of it mechanical (mutation testing in CI, contract-test wiring, a
`loop_journal.py`/`task_anchor.py` gate hook) is exactly the follow-up scoped in issue #579.
