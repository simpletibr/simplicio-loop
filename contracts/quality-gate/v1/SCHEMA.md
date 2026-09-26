<!-- simplicio-contract:begin -->
contract: quality-gate/v1
schema: simplicio.contract-doc/v1
purpose: This directory documents the JSON contract the loop's **Quality Gate** reads to decide whether a work item may ever be reported `COMPLETE`.
rules: The JSON schema next to this file is authoritative; mutable data lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# `simplicio.quality-matrix/v1` — the Quality Gate receipt (#283)

This directory documents the JSON contract the loop's **Quality Gate** reads to decide
whether a work item may ever be reported `COMPLETE`. It is the schema referenced by
issue #283 ("Implementar Quality Gate obrigatório com TDD, testes completos, cobertura
mínima e benchmark") and matches the real implementation, not an aspirational spec:

* implementation: `simplicio_loop/quality_matrix.py` (`evaluate_quality_matrix`,
  `build_quality_matrix_template`, `classify_change_type`, `default_policy_for_change_type`,
  `independent_reverify_tdd_lane`, `independent_reverify_quality_matrix`)
* CLI: `scripts/quality_matrix.py` (`build` / `check` / `classify` / `populate` / `tdd-red` /
  `tdd-green` / `reverify` / `selftest`)
* consumer: `simplicio_loop/oracle.py::evaluate_completion` — the completion oracle
  refuses `COMPLETE` unless this receipt evaluates `ready: true` (issue #278, extended
  here). There is no code path that marks a work item done while skipping this gate.
* independent re-verifier: `scripts/watcher_verify.py cmd_verify` attaches a `quality_gate`
  block (`VERIFIED` / `BLOCKED` / `NOT_PRESENT`) to the watcher receipt, computed by
  `independent_reverify_quality_matrix` — see § 4 below.
* schema: [`schema.json`](./schema.json) (JSON Schema draft-07)

## Baseline (#278) — always enforced

Every receipt must supply `requirements.implementation`, `.unit`, `.integration`,
`.system`, `.regression`, and `.benchmark`, each `{"status": "pass", "proof_ref": "<non-empty>"}`,
plus `coverage.measured >= coverage_threshold` (default 85%). Any lane missing, failing,
or without a `proof_ref` blocks with a distinct `reason_code` (e.g. `quality_unit_missing`,
`quality_unit_failed`, `quality_unit_unproven`). A missing/unreadable receipt blocks with
`quality_matrix_missing`. This is unconditional and was already wired into the completion
oracle before #283 — #283 does not weaken it.

## #283 additions — strictly additive, opt-in, zero regression

A receipt that omits `policy` entirely, and never sets a `tdd` requirement or a
`not_applicable` status, behaves **exactly** as the #278 baseline above. The additions
below only activate when a receipt explicitly opts in:

### 1. TDD RED → GREEN evidence (`policy.tdd_required`)

Set `policy.tdd_required: true` to require a `requirements.tdd` entry with:

```json
{"status": "pass", "red_proof_ref": "tests/test_x.py::test_feature (failed pre-impl)",
 "green_proof_ref": "tests/test_x.py::test_feature (passed post-impl)"}
```

`red_proof_ref` and `green_proof_ref` must both be non-empty **and different from each
other** — a single ref cannot prove both a failing-before and a passing-after state.
Failure reason codes: `quality_tdd_missing`, `quality_tdd_failed`,
`quality_tdd_red_missing`, `quality_tdd_green_missing`, `quality_tdd_red_green_identical`.

### 2. Justified `NOT_APPLICABLE` benchmark (`policy.allow_justified_not_applicable`)

Only the `benchmark` lane (`NOT_APPLICABLE_ELIGIBLE` in `quality_matrix.py`) may be
excused, and only when **both** `policy.allow_justified_not_applicable: true` **and** a
non-empty `requirements.benchmark.justification` are present:

```json
{"policy": {"allow_justified_not_applicable": true},
 "requirements": {"benchmark": {"status": "not_applicable",
                                 "justification": "no perf-sensitive code path touched"}}}
```

Any other lane set to `not_applicable`, or `benchmark` set to `not_applicable` without
the policy flag or without a justification, blocks with
`quality_<lane>_not_applicable_unjustified`.

### 3. Deterministic change classification

`classify_change_type(title, labels) -> "bug"|"fix"|"feat"|"chore"|"task"` is a
label-authoritative, title-fallback classifier (no LLM call) used to derive a sane
default policy via `default_policy_for_change_type`:

| change_type | `tdd_required` | `allow_justified_not_applicable` |
|---|---|---|
| `feat` / `fix` / `bug` / `task` | `true` | `false` |
| `chore` (docs/refactor/CI, no behavior change) | `false` | `true` |

`scripts/quality_matrix.py build --run-dir <dir> --change-type <type>` seeds a template
with that policy pre-filled; `scripts/quality_matrix.py classify --title "..." --label L`
prints the classification + derived policy standalone.

## 4. Auto-populating the receipt (`scripts/quality_matrix.py populate`)

```bash
python3 scripts/quality_matrix.py populate --run-dir <dir> --base origin/main \
    [--benchmark-na "justification"] [--change-type feat] \
    [--skip-regression] [--skip-benchmark] [--skip-coverage]
```

Runs the real gate scripts and writes their MEASURED output straight into the receipt,
instead of requiring a hand-typed `status`/`proof_ref`:

| lane | source | written fields |
|---|---|---|
| `regression` | `scripts/regression_test_gate.py --base <base> --emit-json <run>/regression-gate-report.json` | `status` (pass/fail from the real exit code), `proof_ref` (report path), `detail` |
| `benchmark` | `scripts/perf_gate.py --emit-json <run>/benchmark-gate-report.json`, or `--benchmark-na "..."` to excuse it as justified `NOT_APPLICABLE` (also flips `policy.allow_justified_not_applicable` on) | `status`, `proof_ref`/`justification`, `detail` |
| `coverage` | `scripts/coverage_gate.py --emit-json <run>/coverage-gate-report.json` | `coverage.measured` (the real `global_pct`), `coverage.report_ref` (report path) |

`implementation`/`unit`/`integration`/`system` have no dedicated standalone gate script in
this repo yet (no per-category test-runner split exists — see the issue's Fase B/C
migration plan), so `populate` leaves those lanes untouched; they still require a
manual/injected `status`/`proof_ref` until a per-category runner exists.

## 5. Structurally re-checkable TDD RED/GREEN evidence (`tdd-red` / `tdd-green`)

```bash
python3 scripts/quality_matrix.py tdd-red  --run-dir <dir> --test-id "tests/test_x.py::test_feature"
python3 scripts/quality_matrix.py tdd-green --run-dir <dir> --test-id "tests/test_x.py::test_feature"
```

`tdd-red` runs the given pytest node id right now and FAILS CLOSED (rejects, non-zero exit)
if it doesn't actually fail — a RED receipt can only be captured while the fix is genuinely
absent. It writes `<run>/tdd-red-receipt.json` with the raw `exit_code`, `commit_sha` and
`test_id`. `tdd-green` re-runs the same node id and FAILS CLOSED unless it now passes, a
prior matching RED receipt exists for the same `test_id`, and the current commit differs
from the RED commit (proving the implementation actually changed in between); it writes
`<run>/tdd-green-receipt.json`. The receipt's `requirements.tdd.red_proof_ref`/
`green_proof_ref` should point at these two files.

## 6. Independent re-verification (`reverify` / the watcher's `quality_gate` block)

```bash
python3 scripts/quality_matrix.py reverify --run-dir <dir> [--no-rerun]
```

`independent_reverify_quality_matrix` re-derives the verdict from RAW evidence instead of
trusting the receipt's self-reported `status` string:

* **TDD** (`independent_reverify_tdd_lane`): loads the JSON files `red_proof_ref`/
  `green_proof_ref` point to and validates their raw fields — RED's `exit_code` must be
  non-zero, GREEN's must be zero, both must share the same `test_id`, and they must come
  from two *different* commits. A receipt claiming `"status": "pass"` with no resolvable
  backing file, or with contradictory raw fields, is rejected
  (`quality_tdd_reverify_receipt_missing`, `_red_not_failing`, `_green_not_passing`,
  `_test_id_mismatch`, `_no_commit_delta`).
* **regression** / **benchmark**: when claimed `"pass"` (not excused `NOT_APPLICABLE`),
  `scripts/regression_test_gate.py`/`scripts/perf_gate.py` are re-executed live, right now
  (`rerun=True`, the default) — there is no time-travel problem re-running these, unlike
  TDD's RED state which the implementation has since overwritten. A claim that no longer
  holds is `quality_<lane>_reverify_mismatch`. `--no-rerun` skips this (cheaper, but only
  re-checks the TDD lane).
* **coverage**: not independently re-run by default (a full suite-under-coverage pass is
  too slow to repeat on every watcher tick); `populate` still persists the raw
  `coverage.report_ref` artifact so a `--deep`-style re-verifier can be added later.

`scripts/watcher_verify.py cmd_verify` calls this automatically whenever
`<run>/quality-matrix.json` exists, and attaches the result to the watcher receipt as:

```json
{"quality_gate": "VERIFIED", "quality_gate_detail": { "...": "full independent_reverify_quality_matrix output" }}
```

(`"BLOCKED"` when re-verification disagrees with the claim, `"NOT_PRESENT"` when this run
has no quality-matrix.json at all — the oracle's own quality-matrix gate already fails
closed on that case separately). A `BLOCKED` quality gate is folded into the watcher's
overall `match`/`status`, so a claim the independent pass can't confirm blocks the same way
a missing challenge or a stale commit already did.

## 7. The literal `simplicio.quality-gate/v1` envelope (`run_id`, `work_item`, nested `tests`)

The issue body's example schema shows `run_id`, `work_item` (`source`/`id`/`type`/`title`),
and the four test-category lanes nested under a `tests` object rather than flat under
`requirements`. All three are now supported, additively, on top of the same receipt:

```bash
python3 scripts/quality_matrix.py build --run-dir <dir> --change-type feat \
    --run-id abc123 --work-item-source github --work-item-id 283 \
    --work-item-type feat --work-item-title "Quality Gate obrigatório"
```

* `run_id` (string) and `work_item` (`{source, id, type, title}`) are recorded verbatim
  when the CLI flags are given; omitting them keeps `run_id: ""`/`work_item: {}` (never
  fabricated placeholders). `scripts/quality_matrix.py populate` accepts the same flags and
  only fills them in when the existing receipt does not already have them set.
* `tests.unit`/`.integration`/`.system`/`.regression` is a nested mirror of the same four
  `requirements.<lane>` entries, kept in lockstep by
  `simplicio_loop.quality_matrix.sync_tests_envelope` (called by
  `build_quality_matrix_template` and by `scripts/quality_matrix.py populate` after it
  writes `requirements.regression`). `evaluate_quality_matrix` and
  `independent_reverify_quality_matrix` read a lane from **either** the flat
  `requirements.<lane>` entry (canonical, wins if both present) **or** the nested
  `tests.<lane>` entry — a receipt authored in either shape evaluates identically, so
  external tooling that only knows the issue's literal envelope example can write
  `tests.unit`/etc. directly without needing to also duplicate it under `requirements`.

## Not yet covered by this contract

* CI wiring (`.github/workflows/`) was removed repo-wide in #311 (unrelated billing
  reasons) — there is currently no GitHub Actions workflow to publish coverage/benchmark
  artifacts or gate a PR merge on them. `populate`/`reverify` are runnable locally / from
  any external CI this repo is later wired into.
* a live, un-cached independent re-run of `coverage_gate.py` on every watcher tick (see §6).
* per-category (`unit`/`integration`/`system`) test-runner split — `populate` cannot
  auto-fill those lanes until one exists (issue's Fase B/C migration).
