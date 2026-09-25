# Plan Compiler Benchmark (issue #166)

Publishes processes/calls/tokens/latency/success for two things that both
exist in this repo today, run with `bench/plan_compiler_benchmark.py`:

- **before** — `simplicio.pipeline.run_task`, the live task-execution path
  `simplicio-cli` actually runs today.
- **after** — `simplicio.plan_compiler.compile_task_spec_to_plan()` +
  `PlanDAG.validate()`, the deterministic compile step added across issue
  #166's slices.

## Hypothesis under test

> "Compiling a TaskSpec through PlanDAG first reduces process/model overhead
> without losing verification rigor."

**Result: mixed / not fully testable yet — documented here, not hidden.**
`plan_compiler` has **zero call sites** in `cli.py` or `pipeline.py` as of
this benchmark (confirmed by grep and by PR #178/#180's own finding). It is
not wired into the live execution path. So:

- The "0 subprocess/model calls" number for the compile step is real and
  reproducible, but it is not yet a claim about a shipped user-facing speedup
  — plan_compiler currently does no work a user's task depends on. Comparing
  it to the live pipeline's call count is an honest "what does each thing
  cost in isolation today" measurement, not a same-task A/B.
- **No end-to-end task-success-rate comparison is possible today.** Both
  numbers below report success/validity for *their own* definition of
  success (patch applied + verified, vs. compiled plan passes `validate()`)
  — there is no shared task where both paths produce a comparable pass/fail
  outcome, because only one of them (the pipeline) currently touches a real
  task outcome. Making that comparison meaningful requires wiring
  `plan_compiler` into `pipeline.py`/`cli.py` — a separate, larger
  integration slice, tracked by the still-unchecked #166 ACs ("No modo
  integrado, zero escrita/commit fora da Effect API do Runtime", etc.).

## Measured numbers (real run on this machine)

Run: `python3 bench/plan_compiler_benchmark.py`, `sys.executable` as the
verify command interpreter, 2026-07-13.

### Before — `pipeline.run_task` (today's live path)

5 iterations, each a fresh tmp worktree, fake `generate()` returning a fixed
1-line unified diff, real `git apply` + real verify-test-command subprocess,
impact tests stubbed to "not needed" (so this is the *minimum* real cost —
a run with impact tests executing for real, or with retries, is higher):

| Metric | Value |
|---|---|
| Processes (subprocess.run) per run | 3 (git apply --check, git apply, verify test cmd) |
| Model calls (`generate()`) per run | 1 |
| Latency p50 | 77.0 ms |
| Latency p95 | 98.6 ms |
| Latency mean / min / max | 81.8 / 72.2 / 98.6 ms |
| Task success rate | 5/5 = 100% (patch applied + verified) |

### After — `compile_task_spec_to_plan` + `PlanDAG.validate` (compile-only)

3 representative TaskSpecs (single-AC, multi-AC + multi-verifier, budgeted)
× 40 repeats = 120 iterations, each wrapped in the same
subprocess/socket-forbidding guard used by
`tests/python/test_plan_compiler_dry_run.py` (issue #166 slice 3) so "0
calls" is asserted, not just counted-and-hoped:

| Metric | Value |
|---|---|
| Processes (subprocess.run/Popen) per run | 0 (asserted — raises if any occurs) |
| Model calls per run | 0 |
| Latency p50 | 0.025 ms |
| Latency p95 | 0.031 ms |
| Latency mean / min / max | 0.029 / 0.023 / 0.244 ms |
| Compile success rate | 120/120 = 100% (`validate()` passes for every fixture) |

Raw JSON output (schema `simplicio.dev-cli-plan-compiler-benchmark/v1`) is
reproducible by re-running the script; it is not committed as a fixture
since a fresh run on a different machine will show different absolute
latency numbers (the shape — 3 vs. 0 processes, ms vs. µs — is the durable
finding, not the exact milliseconds).

## What actually improved

The compile-only path takes 0 subprocess calls and 0 model calls, roughly
3 orders of magnitude faster in wall-clock than the live pipeline's
happy-path minimum (µs vs. tens of ms) — expected, since it is pure Python
with no I/O, by construction (issue #172's effect-freedom proof, reused
here).

## What did NOT improve / is not yet comparable

- This is not a "same task, faster" result for any user-facing operation
  today, because no user-facing operation runs through `plan_compiler` yet.
  Nothing in `cli.py` calls it.
- Task success rate is not comparable across the two paths — they measure
  success for different things (applied+verified patch vs. valid PlanDAG).
- Retry behavior, impact-test cost, and model-call cost under real
  variability (`MAX_ATTEMPTS` up to 5 in `pipeline.run_task`) are not
  captured by this benchmark's single-attempt happy path; a full integration
  benchmark once `plan_compiler` is wired in should also cover the retry
  loop.

## Safety/evidence: no shortcut taken for these numbers

No verification or safety check was skipped to produce the "0 calls"/latency
numbers above:

- `PlanDAG.validate()`'s rejection checks (duplicate/orphan/cyclic nodes,
  missing effect authority, irreversible-effect-without-gate, AC coverage,
  budget ceiling — see `simplicio/plan_compiler/models.py::PlanDAG.validate`)
  run unconditionally in the compile-only path measured above; the benchmark
  calls `plan.validate(...)` explicitly and would raise `PlanValidationError`
  on any fixture that failed those checks (none did — see 100% compile
  success rate).
- The legacy pipeline path measured above ran with impact-test verification
  present in the code path (`pipeline._run_impact_tests` is stubbed to
  return `IMPACT_RESULT_NOT_NEEDED`, a real, valid outcome the pipeline
  itself supports when no callers are found — it is not a bypass of the
  primary git-apply + verify-test-command checks, which ran for real via
  subprocess).
- No latency number here trades away a check: the compile-only path is fast
  because it does strictly less work (no process/model I/O), not because a
  check was disabled.

## How to reproduce

```bash
python3 bench/plan_compiler_benchmark.py
```

Smoke-tested (not perf-gated) by
`tests/python/test_plan_compiler_benchmark_smoke.py`.
