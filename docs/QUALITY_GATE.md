# Quality Gate (#283) — what is actually implemented

This is the operator-facing documentation issue #283 asked for
("Implementar Quality Gate obrigatório com TDD, testes completos, cobertura mínima e
benchmark"). It describes the real, shipped mechanism — not the issue's aspirational spec — and
says explicitly, for each item the issue asked for, whether it exists, is partial, or is
genuinely out of scope for this repo. For the receipt schema itself see
[`contracts/quality-gate/v1/SCHEMA.md`](../contracts/quality-gate/v1/SCHEMA.md); this document is
about the surrounding tooling: what produces and consumes that receipt.

## 1. The gate, end to end

```
scripts/quality_matrix.py build      -> quality-matrix.json (empty template)
scripts/quality_matrix.py populate   -> auto-fills unit/integration/system/regression/benchmark/coverage
scripts/quality_matrix.py tdd-red    -> tdd-red-receipt.json  (opt-in, policy.tdd_required)
scripts/quality_matrix.py tdd-green  -> tdd-green-receipt.json
scripts/quality_matrix.py check      -> evaluate_quality_matrix (self-reported verdict)
scripts/quality_matrix.py reverify   -> independent_reverify_quality_matrix (re-derived verdict)
scripts/watcher_verify.py verify     -> attaches quality_gate: VERIFIED|BLOCKED|NOT_PRESENT
simplicio_loop/oracle.py::evaluate_completion -> refuses COMPLETE unless quality-matrix.json is ready
```

No code path marks a work item `done`/`COMPLETE` while skipping this: `evaluate_completion` reads
`quality-matrix.json` unconditionally (issue #278's baseline, extended by #283). This document
covers the pieces #283 specifically added or is still missing.

### Hermetic core subprocess contract

`scripts/check.py --core-gate` runs each phase with a bounded subprocess lifecycle.
On Linux with procfs it additionally enables a subreaper and verifies escaped
descendants (including `setsid`/double-fork cases). On macOS and Windows the
same interface remains usable with a fresh process group; Windows terminates a
timed-out tree through `taskkill /T /F` when available and falls back to
terminating the phase leader if that command fails; POSIX uses the process
group. Those portable backends guarantee bounded capture and a terminated
leader, but do not claim whole-tree cleanup after a Windows `taskkill` failure
or Linux-only escaped-descendant discovery. A Linux host whose required
procfs/subreaper capability is unavailable reports the typed
`CAPABILITY_UNAVAILABLE[process_containment]` result instead of silently
claiming that the phase was contained.

## 2. Per-category test-runner split (`scripts/test_categories.py`)

**What exists:** `unit` / `integration` / `system` / `regression` are now separately invokable,
each with its own pass/fail:

```bash
python3 scripts/test_categories.py status                      # counts per category, JSON
python3 scripts/test_categories.py list --category unit         # which files, exactly
python3 scripts/test_categories.py run --category unit           # run just that category
python3 scripts/test_categories.py run --category integration --emit-json report.json
python3 scripts/test_categories.py selftest                      # proves the partition logic
```

`scripts/quality_matrix.py populate` now calls this for `unit`/`integration`/`system` the same
way it already called `regression_test_gate.py`/`perf_gate.py`/`coverage_gate.py` for the other
three lanes — every measurable lane (all but `implementation`, which is inherently
change-specific) is now auto-filled from a real, standalone gate script instead of requiring a
hand-typed status. `simplicio_loop/quality_matrix.py::independent_reverify_quality_matrix` also
live-reruns `unit`/`integration`/`system` the same way it already reran `regression`/`benchmark`,
so a claimed `pass` in any of these lanes is independently re-executed, not just re-parsed from a
self-reported string.

**How categorization works, honestly:** the script reads the **existing** filename convention —
`tests/test_*_unit.py`, `_integration.py`, `_system.py`, `_regression.py`. As of this PR **all 189**
files in `tests/` follow it (0 `uncategorized`): 76 `unit`, 69 `integration`, 37 `system`, 7
`regression`. Every file was renamed by actually reading its docstring, imports, and
subprocess/network usage — never guessed from its old name or swept in by keyword-matching test
names. An earlier draft of this tool tried exactly that (`pytest -k unit` against the whole
test-name corpus) and it was dropped because it is unreliable — it sweeps in unrelated tests whose
*name* happens to contain the substring, including slow/live/e2e tests that hang for minutes.
Only the deliberate suffix convention (now complete) is treated as ground truth; renaming to it is
what this PR did for the ~165 files that didn't yet have a suffix. `list --category uncategorized`
still exists and still reports honestly — it now returns nothing, and will again the moment a new
test file is added without a suffix.

**What this now means for coverage (Fase B):** with the convention complete, `unit`/`integration`
gained ~50 additional subprocess-free files that are fast enough to add to a measured coverage
scope without hitting the environment's live-test-hang/`WinError 6` issues (see § 3 below) — the
65-file scope `quality/coverage-baseline.json` now measures. The 37 `system` files (real
multi-process concurrency, live `gh`/GitHub e2e gated behind env vars, full-stack install/CI
black-box tests) are exactly the slice Fase A/B's scope rationale excludes for environment
reasons, not because they're uncategorized anymore — they are categorized, just not yet safe to
run unattended under coverage instrumentation in this sandboxed shell.

## 3. Coverage baseline and migration (issue's Fase A–D plan)

**Fase A (done, PR #401):** a real, measured baseline was recorded at
[`quality/coverage-baseline.json`](../quality/coverage-baseline.json) — produced by
`scripts/coverage_gate.py`, not invented: 16.60% global / 9.40% critical over the 21 files the
per-category split formalized at the time. `scripts/coverage_gate.py` gained a `--tests-path` flag
(repeatable) specifically so a defined subset like this can be measured reproducibly instead of
only ever running full-or-nothing; the flag defaults to `tests/` (the full tree) when omitted, so
existing `--tests-path`-less invocations (CI, `scripts/check.py`) are unaffected. That number is
preserved in the baseline file under `previous_baseline` for an honest before/after.

**Fase B (in progress, this PR):** the categorization convention (§2 above) is now 100% complete —
0 of 189 files uncategorized, up from 165. That let the measured coverage scope widen from 21 to
**65** files (every `unit`/`integration` file that makes no subprocess call and touches no live
network/multi-process concurrency), re-measured with the same `scripts/coverage_gate.py`:

- **global coverage: 16.60% -> 28.45%**
- **critical coverage: 9.40% -> 24.02%**
- all 757 tests in the new scope pass (`test_suite_returncode: 0`)

The full `tests/` tree (189 files, ~1775 tests, including live/e2e/network-touching suites) was
still NOT used for this baseline: in this repo's sandboxed CI-equivalent shell, running the newly
`system`-tagged files (real multi-process concurrency, live `gh` e2e, full install black-box
tests) and a handful of subprocess-heavy `integration` files under coverage instrumentation still
intermittently hangs (some wait on external state) or hits a Windows-sandbox-specific `WinError 6`
— both pre-existing environment limitations documented in Fase A, unchanged by this PR. The
measured numbers are still an honest under-estimate, not a claim about the whole codebase — 65 of
189 test files were exercised, chosen the same defined-subset-with-a-stated-rationale way Fase A
chose its 21. `coverage_gate.py` still does not compare a fresh run against this baseline file
automatically (no `--baseline-file` flag); wiring that comparison remains Fase B/C follow-up.

**Re-measured for 3.46.0 (#1379):** the release removed the Runtime/MCP, Hub and remote-worker
subsystems and 16 uncalled modules together with their tests, so the scope shrank from 65 to **47**
files (the 17 whose modules or tests were removed, plus `tests/test_cli_dispatch_unit.py`, whose 6
failures are an `OSError` on a read-only `/r` in this macOS environment and identical on a pristine
`origin/main`). Re-measured with the same `scripts/coverage_gate.py`: **global 16.76%, critical
25.13%**, all 522 tests in the scope pass. Those percentages are not comparable with the Fase B
ones above (the removed modules were the best-tested code); the Fase B numbers stay in the baseline
file under `previous_baseline`.

Genuinely still open for Fase B: the remaining 124 categorized-but-out-of-scope files (mostly
`system`) still need a safe way to be folded into a measured scope (or an explicit, separate
"system coverage" measurement), and modules with clear line-coverage gaps still need new tests —
neither is claimed done by this PR.

**Fase C (blocked, not by this repo):** `fail_under = 85` globally requires a fast, reliable
full-suite coverage run. That is blocked today by two things this PR found and only partially
fixed:
  1. `scripts/coverage_gate.py`'s critical-path percentage calculation crashed unconditionally on
     this environment (`coverage` 7.15.x + Python 3.14: the private `Coverage._analyze`/
     `_get_file_reporter` pair it used raised `TypeError: cannot use 'PythonFileReporter' as a
     dict key`) — **fixed in this PR**, replaced with the public `Coverage.analysis2()` API.
  2. Running the *entire* `tests/` tree under coverage in one shot is slow/flaky in a sandboxed
     shell for reasons unrelated to coverage itself (a handful of subprocess-spawning tests hit a
     `WinError 6` invalid-handle OSError on this specific host, and some live/e2e tests block on
     external state) — **not fixed**, out of scope for #283, tracked as a real, separate follow-up
     (the fix belongs in test isolation/environment hardening, not the quality gate).

**Fase D (not started):** evaluate raising the global target above 85% once B/C land. Nothing to
report yet.

## 4. Benchmark

Already covered by `scripts/perf_gate.py` (predates #283, extended by it): the committed baseline
lives at `scripts/perf_baseline.json` (regenerate deliberately with
`python3 scripts/perf_gate.py --update-baseline`, never silently). The issue's suggested path
`quality/benchmark-baseline.json` is not used — `perf_baseline.json` already is that file, just
alongside the script instead of under `quality/`, and `scripts/perf_gate.py --emit-json` gives
every consumer (`quality_matrix.py populate`, the independent reverifier) a structured,
reproducible verdict against it. Not renamed/moved in this PR to avoid an unrelated churn diff on
a file this issue didn't ask to change.

## 5. Multi-language adapters — N/A for this repo

Issue #283 §14 asks for adapters recognizing JS/TS, Rust, .NET, Go, and Java test/coverage/
benchmark tooling, explicitly allowing a "Python-first" initial phase. Checked for this PR: this
repository's only non-Python source surface is `packaging/npm/package.json`, a thin npm
**wrapper** that shells out to the installed Python package (no JS test suite, no `.ts`/`.js`
application code beyond that wrapper's `bin/` shim). There is no Rust, Go, .NET, or Java surface
at all (`Cargo.toml`/`go.mod`/`*.csproj`/`pom.xml`/`build.gradle` all absent). Building real
adapters for languages this repo does not contain would be speculative, untestable scaffolding —
explicitly scoped OUT rather than stubbed. If `simplicio-loop` is ever used to gate a *consuming*
project written in one of those languages, the adapter work belongs there, informed by that
project's real toolchain, not invented here against nothing.

## 6. CI job separation — not evidenced by this work

Issue #283 §13 asks for separate required GitHub Actions jobs (`unit`/`integration`/`system`/
`regression`/`coverage`/`benchmark`/`quality-gate`) with branch-protection wiring.
Two workflows currently exist (`simplicio-status-sync.yml` and `windows-progress-smoke.yml`), but
they do not provide this required-job separation, OIDC, or a release gate; they were not executed
or used as evidence for this work. The per-category split in §2 is the local piece that could back
future jobs (`python3 scripts/test_categories.py run --category unit` etc. as a job step per lane).

## 7. Verifying it locally

```bash
python3 scripts/test_categories.py selftest
python3 scripts/quality_matrix.py selftest
python3 scripts/coverage_gate.py --tests-path tests/test_quality_matrix_unit.py --diagnostics-dir /tmp/cov
python3 scripts/claims_audit.py
```
