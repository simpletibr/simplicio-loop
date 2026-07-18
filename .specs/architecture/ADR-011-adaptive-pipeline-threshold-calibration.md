# ADR-010: Local, per-machine calibration for the sync/async pipeline dispatch threshold (Phase-0 of a Hub-governed adaptive planner)

> Addresses https://github.com/wesleysimplicio/simplicio-mapper/issues/279
> ("[P0][Performance] Tornar pipeline sync/async adaptativo e governado pelo
> Hub com benchmark por plataforma"), scoped as a Phase-0 increment. Issue
> #279 itself is a large, 16-step epic (parent:
> https://github.com/wesleysimplicio/simplicio-loop/issues/555) describing a
> full adaptive Execution Planner (auto/sync/async/thread/process/hub
> profiles, Hub-issued global permits, single-flight, structured
> cancellation, autotuning policy). This ADR does **not** implement that
> epic -- it proposes a design for genuine per-platform/per-machine
> adaptivity and ships the one safe, additive slice of it that is real and
> buildable today: a local, opt-in calibration command. See "Não escopo"
> below for what is explicitly deferred and why.

---

## Status

`Proposto` (design + Phase-0 slice implemented in this PR; the rest of issue
#279's 16-step plan is intentionally NOT implemented here -- see "Plano de
adoção")

---

## Data

2026-07-18

---

## Autores

- wesleysimplicio
- Claude (claude-sonnet-5)

---

## Contexto

ADR-009 (`ADR-009-async-mapping-pipeline.md`) already implements and honestly
documents a size-based sync/async dispatch in
`simplicio_mapper/mapper/emit.py::build_artifacts`: a cheap file-count probe
(`_fast_file_count`) routes trees below
`SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES` (default **600**) through the
plain synchronous pipeline, and at/above it through the bounded-concurrency
async pipeline. That default was measured once
(`scripts/async_pipeline_dispatch_benchmark.py`, Windows, Python 3.14.5,
this machine) and ADR-009 says so explicitly in its own "Critério de
revisão": *"The size-based dispatch threshold itself is also not a closed
question forever: it is a measured default on one machine/filesystem,
tunable via the same env var, and should be revisited if a future, less
noisy benchmarking environment (or real-world usage data) suggests a
different crossover point."*

Issue #279 names this gap directly and asks for real adaptivity: the
threshold should reflect the machine/filesystem it runs on (different CPU
core counts, disk types -- SSD/NVMe/network filesystem -- and OS scheduler
behavior all plausibly shift where async's thread-pool overhead stops
dominating I/O-wait savings), not a single constant measured once on one
Windows machine and shipped to everyone.

Issue #279 additionally asks for **Hub governance** -- an external
authority (referenced elsewhere in this repo's issue tracker as the
`simplicio-loop` "Loop Hub" product, parent epic
https://github.com/wesleysimplicio/simplicio-loop/issues/555) issuing
global permits, single-flight coordination, and workload-aware routing
across sync/async/thread/process/hub execution profiles.

**Honest finding from this pass**: searching this repo (`docs/`,
`AGENTS.md`, `CLAUDE.md`, `.specs/`) for an existing, callable "Hub"
integration point turned up **no real API surface in this repository** --
no client, no protocol document, no env var, no stub -- only the issue
tracker's own references to a *separate*, not-yet-integrated product
(`simplicio-loop`'s Loop Hub). This ADR does not invent one. Per this
task's own explicit instruction, the Hub side is treated as **real but not
yet integrated here**: this repo's dispatch logic is designed to be
governable by an external authority later (a single, narrow read point --
see "Shape of a future Hub hook" below) but is **self-governing by default**
until that integration exists. Fabricating a fictional Hub client/protocol
now would be worse than admitting the gap, since it would give false
confidence that governance already works.

Given the epic's real scope (16 plan steps: frozen benchmark corpus across
platforms, I/O/CPU/write-critical stage separation, an `ExecutionProfile`
enum with 6 profiles, Hub-issued global permits for file I/O/CPU/cache
writes, single-flight result handles, canonical-map/overlay integration,
thread-local SQLite lifecycle across persistent workers, structured
cancellation with quarantine, shadow rollout, versioned autotuning policy),
attempting all of it in one PR would repeat exactly the mistake ADR-008 and
ADR-009 already explicitly avoided earlier in this repo's history: an
unreviewable mega-diff touching the hot path of every `index`/`map`/`scan`
command, with no incremental review checkpoint. See "Alternativas
consideradas" below.

---

## Decisão

### Design proposal for genuine per-platform adaptivity (not implemented yet beyond Phase-0)

The following design is proposed as the target shape for the remaining
steps of issue #279's plan, to be implemented incrementally in follow-up
PRs, each independently reviewable:

1. **Per-machine calibration, not a single global constant** (this PR's
   Phase-0 slice, see "Decisão de implementação" below): the crossover
   point is measured locally, once, and cached -- not hardcoded for every
   platform.
2. **Per-platform benchmark corpus** (deferred, plan step 1): a frozen
   small/medium/large synthetic-tree corpus, run identically across
   Linux/macOS/Windows and local-disk/network-filesystem variants, so the
   calibration command's synthetic trees are validated against a known
   reference rather than only this Windows sandbox's numbers. ADR-009
   already has Linux-verified test-matrix execution
   (`docs/async-pipeline-after-benchmark-linux-container.md`) but no
   Linux-measured *dispatch threshold* -- that gap is what this step would
   close.
3. **`ExecutionProfile` enum** (deferred, plan step 4): `auto | sync | async
   | thread | process | hub`, generalizing today's binary sync/async
   dispatch. Today's dispatch is effectively `ExecutionProfile.auto`
   restricted to two of the six profiles (`sync`/`async`); `thread` (a
   bounded `ThreadPoolExecutor` without the full `asyncio` event-loop
   machinery), `process` (CPU-bound work routed to a process pool or the
   Rust runtime, see ADR-002), and `hub` (delegated to an external
   coordinator) are real future profiles this repo does not implement yet.
4. **Shape of a future Hub hook**: a single, narrow, optional read point --
   e.g. `resolve_execution_profile(cwd, file_count, platform_info) ->
   ExecutionProfile | None` -- that this repo's dispatcher would consult
   *before* its own local calibration/default, returning `None` when no Hub
   is configured or reachable (fail-open to local self-governance,
   mirroring this repo's existing `simplicio` native-delegation pattern in
   `simplicio_mapper/query.py`: `shutil.which`-style presence check,
   timeout, kill-switch env var, automatic fallback on ANY failure --
   never a silent fake-pass). This is a *design*, not code shipped in this
   PR: no Hub client exists to call, and inventing one without a real
   protocol to integrate against would be speculative infrastructure this
   repo's own conventions (`AGENTS.md`: "Antes de adicionar dependência
   nova: pergunta ao usuário") explicitly discourage.
5. **Autotuning policy, versioned and reproducible** (deferred, plan step
   16): once real per-platform corpus data (step 2) and calibration
   telemetry (step 1's local calibration, aggregated across many machines
   if a Hub exists to aggregate it) accumulate, a policy that adjusts the
   default without requiring a code release -- explicitly out of scope
   until there is real data to base it on.

### Decisão de implementação (this PR's actual Phase-0 slice)

Ship exactly one new, safe, additive piece, matching this task's own scoping
instruction:

- **New module** `simplicio_mapper/mapper/pipeline_calibration.py`:
  - `run_calibration(sizes, runs, default_threshold) -> dict` -- reuses the
    same measurement *methodology* as
    `scripts/async_pipeline_dispatch_benchmark.py`'s crossover table
    (forcing sync/async explicitly via the existing
    `SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES` env var, on synthetic
    Python trees, same-revision like-for-like comparison) but is
    implemented as installed package code, not a dependency on the
    `scripts/` directory (which is not shipped in the built wheel/npm
    package). Picks the smallest measured size where async's median wall
    time beats sync's as the recommended threshold; **falls back to the
    existing hardcoded default if async never wins at any measured size**
    (fail-safe: calibration never invents an unmeasured win).
  - `write_calibration(cwd, payload, output_dir) -> str` -- atomic write
    (tmp file + `os.replace`, matching `emit.py::_write_json_stable`'s
    existing convention) to `<cwd>/<output_dir>/pipeline-calibration.json`.
  - `load_calibrated_threshold(cwd, output_dir) -> int | None` -- fail-safe
    reader: ANY problem (missing file, corrupt JSON, wrong schema, non-int
    or non-positive threshold) returns `None`, never raises.
- **`emit.py::_async_pipeline_min_files`** now resolves the threshold in
  this order: (1) `SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES` env var
  (unchanged, highest priority, exactly as before this issue); (2) a valid
  calibration file at `<output_dir>/pipeline-calibration.json`, if `cwd` is
  known; (3) the hardcoded default (600), exactly today's behavior. **No
  calibration file present = byte-for-byte unchanged behavior** -- this is
  the fail-safe property the task explicitly required.
- **New CLI verb** `simplicio-mapper benchmark pipeline-threshold [path]
  [--sizes N,N,N] [--runs N] [--out DIR] [--json]`
  (`simplicio_mapper/cli/_benchmark.py`), dispatched before `_parse_args`
  in `cli/__init__.py::main` -- same shape as the existing
  `contract`/`doctor`/`canonical` sub-verb dispatches (a sub-verb + flags,
  not the usual `<command> <root>` shape). Runs the calibration and writes
  the cache file; this is the one concrete, real, useful deliverable this
  PR ships.

This closes the "not per-platform" gap **concretely** (a user on Linux,
macOS, an NVMe drive, or a network filesystem gets a threshold measured on
*their* machine, not a number measured once on a Windows sandbox) without
inventing any Hub infrastructure that does not exist.

---

---

## Atualização: `ExecutionProfile` decision layer (issue #279, follow-up slice)

> Adds a second, independently landed increment on top of the Phase-0
> calibration slice above. Both slices are additive and compose: this one
> does not change calibration's file format or precedence rules, it only
> centralizes the sync/async *decision* that already consumed calibration
> data inline inside `emit.py::build_artifacts`.

**Gap this closes**: before this increment, `build_artifacts` computed the
threshold (`_async_pipeline_min_files`) and then compared it against
`file_count` with a bare `if file_count >= threshold` inline in `emit.py`.
That inline comparison was correct but not reusable, not independently
testable without going through the whole artifact-building pipeline, and
left no single place for future profiles (Hub-governed routing, additional
local profiles) to hook into without editing `emit.py`'s dispatch body
again.

**What shipped** (`simplicio_mapper/mapper/execution_planner.py`):

- `ExecutionProfile` (`StrEnum`): `auto`, `sync`, `async` are the profiles
  this repo actually executes. `thread`, `process`, `hub` are also declared
  as enum members -- **explicitly reserved, not-yet-implemented** vocabulary
  matching the target design already described earlier in this ADR ("3.
  `ExecutionProfile` enum (deferred, plan step 4)"). Declaring them as enum
  values lets `SIMPLICIO_MAPPER_EXECUTION_PROFILE` accept and recognize
  those names today (so a caller/operator can start writing config for them
  now) while `plan_execution` deterministically routes any of the three
  reserved values to the same `auto` sync/async decision, never fabricating
  thread-pool, process-pool, or Hub-backed execution that does not exist.
  This is the same "no fictional Hub client" discipline the ADR's original
  "Alternativa B" already rejected -- extended to say the same about
  `thread`/`process` too.
- `plan_execution(file_count: int, threshold: int) -> ExecutionPlan` -- a
  pure function, no I/O, no environment reads beyond
  `SIMPLICIO_MAPPER_EXECUTION_PROFILE` / the async kill switch (both read
  once, synchronously, at call time): given a file count and an
  already-resolved threshold (still produced by
  `_async_pipeline_min_files`, calibration file included, unchanged), it
  returns an `ExecutionPlan` recording `requested_profile`,
  `selected_profile`, a human-readable `reason`, and `source` (`env` /
  `auto` / `fallback` / `kill-switch`). Every branch (explicit sync,
  explicit async, reserved-profile fallback, kill-switch override, auto
  above/below threshold) is unit-tested independently of any file I/O or
  pipeline execution -- see `tests/python/test_execution_planner.py`,
  100% branch coverage on this module in isolation.
- `ExecutionPlan.to_receipt()` -- closes plan step 14 ("Publicar route
  receipt com perfil escolhido e motivo") for the sync/async case: every
  `build_artifacts()` call now attaches an `execution_plan` key to its
  returned artifact dict (schema `simplicio.execution-plan/v1`), so any
  caller/receipt consumer can see which profile was selected and why
  without re-deriving the decision. This was listed as an open "Não
  escopo" item earlier in this ADR; it is implemented now, for the
  sync/async profiles only -- Hub-issued receipts remain out of scope,
  since no Hub exists to issue them.
- **Wiring**: `emit.py::build_artifacts` now computes
  `threshold = _async_pipeline_min_files(...)` and
  `file_count = _fast_file_count(...)` exactly as before, then calls
  `plan_execution(file_count, threshold)` once and dispatches on
  `plan.selected_profile` instead of re-deriving the sync/async choice
  inline. This is a behavior-preserving refactor: the same threshold
  precedence chain (env var > calibration file > hardcoded default), the
  same `_fast_file_count` probe, and the same two code paths
  (`_build_artifacts_sync` / `async_pipeline.build_artifacts_async`) are
  invoked under the same conditions as before -- proven by the existing
  `tests/python/test_pipeline_dispatch.py` suite passing unchanged (see
  "Testes" below) plus the new
  `ExecutionPlannerIntegrationTest.test_build_artifacts_publishes_route_receipt`
  /`test_kill_switch_routes_large_tree_to_sync` integration tests.
- **New operational controls**: `SIMPLICIO_MAPPER_EXECUTION_PROFILE`
  (explicit override: `sync`/`async` take effect immediately; `auto`,
  unset, or unrecognized values fall through to the calibrated/hardcoded
  auto decision) and `SIMPLICIO_MAPPER_NO_ASYNC_PIPELINE` (async kill
  switch: forces `sync` unconditionally, even overriding an explicit
  `async` request -- the one setting nothing else can override, by
  design, for an operational rollback that must always win). Documented in
  `docs/local-setup.md`.

**Still not implemented** (unchanged from this ADR's original "Não
escopo", restated precisely so this update does not overclaim): `thread`
and `process` profiles have no real thread-pool/process-pool backing code
yet -- they are recognized configuration vocabulary that currently no-ops
to the `auto` sync/async decision, not working execution modes. `hub` has
no Hub client to call, same as before. Cross-platform calibration corpus,
structured cancellation quarantine beyond ADR-009's existing coverage,
single-flight/global permits, and versioned autotuning policy remain fully
unimplemented, exactly as this ADR already said. Shadow-rollout comparison
between profiles (plan step 15) is now implemented separately in
`simplicio_mapper/mapper/pipeline_shadow.py` (`benchmark shadow-rollout`
CLI verb) -- it deliberately never auto-promotes a candidate profile and is
not wired into `plan_execution`'s decision.

---

## Consequências

### Positivas (+)

- Directly answers issue #279's most concrete, buildable-today complaint
  (ADR-009's own admitted gap: "não existe... tuning por plataforma") with
  working code, not just another design document.
- Zero risk to existing behavior: the calibration file is opt-in, and its
  absence is byte-for-byte identical to pre-#279 dispatch (verified by
  `CalibrationOverrideTest.test_no_calibration_file_keeps_hardcoded_default`
  in `tests/python/test_pipeline_dispatch.py`).
- Gives a real target shape (the `ExecutionProfile` design + the explicit,
  non-fictional treatment of "Hub not integrated yet") for the epic's
  remaining steps to build on incrementally, the same pattern ADR-008/
  ADR-009 already used successfully in this repo.

### Negativas (-)

- This PR does **not** close issue #279 -- it is an explicit, scoped
  Phase-0 slice of a 16-step epic. A reader tracking only closed issues
  will see no visible epic-level progress unless they read this ADR/PR.
  Fifteen of the sixteen listed plan steps remain unimplemented, including
  the parts issue #279 arguably cares most about (Hub governance,
  cross-platform frozen corpus, structured cancellation quarantine,
  autotuning policy).
- The calibration command's own synthetic-tree measurement is still
  Windows-verified only in this sandbox (same platform-coverage caveat
  ADR-009 already carries) -- it measures accurately on *whatever* machine
  runs it, which is the point, but this PR itself did not gain access to a
  Linux/macOS runner to prove the command behaves identically there.
- No Hub exists to govern anything yet; the design in "Shape of a future
  Hub hook" is unimplemented and unverified against a real protocol.

### Neutras / observações

- The calibration file is scoped per `(cwd, output_dir)`, not global to the
  machine -- a deliberate choice, since different repos on the same machine
  may have very different typical file-tree shapes/filesystem locations
  (e.g. one repo on a fast local SSD, another on a mounted network share)
  and a single machine-wide threshold would conflate them.
- `run_calibration`'s synthetic-tree generator is deliberately simpler than
  `scripts/async_pipeline_after_benchmark.py`'s own (fewer helper-function
  variations per module) since it only needs to reproduce the sync/async
  crossover signal for calibration purposes, not serve as a full
  benchmark-grade corpus -- the frozen, validated corpus from plan step 1
  above is still a real, deferred need.

---

## Alternativas consideradas

### Alternativa A -- Implement the full 16-step epic in one PR

- Descartada, per this task's explicit scoping instruction and this repo's
  own established convention (see ADR-008/ADR-009's identical reasoning):
  an unreviewable mega-diff touching the hot path of every `index`/`map`/
  `scan` command, mixing Hub-protocol design (unproven), a 6-profile
  execution planner, structured cancellation, and cross-platform corpus
  work in one change would make DoD's "coverage >= 88%" and system-level
  test requirements far harder to satisfy honestly, and any regression
  much harder to attribute.

### Alternativa B -- Invent a fictional Hub client now, wire it in as a stub

- Have `_async_pipeline_min_files` call a speculative
  `simplicio_hub.get_execution_profile(...)` that always returns `None`
  today (no real Hub to call).
- Descartada: this task's own instructions are explicit that inventing a
  fictional Hub API is worse than admitting the gap. A stub client with no
  real protocol behind it invites future code to silently assume the Hub
  path is tested/working when it is neither -- exactly the kind of
  "mockar pra fazer passar" this repo's `AGENTS.md` prohibits. The design
  section above documents the intended shape without shipping unverifiable
  code.

### Alternativa C -- Auto-run calibration silently on every `index`/`map`/`scan` invocation

- Have `build_artifacts` calibrate itself transparently the first time it
  runs in a new `cwd`/`output_dir`, no explicit command needed.
- Descartada (for now): this would add a real, uncontrolled latency spike
  (multiple synthetic-tree `build_artifacts()` runs) to a user's *first*
  real command invocation, with no way to opt out short of an env var --
  worse UX than an explicit, clearly-named, user-initiated calibration
  command. Revisit if user feedback shows the explicit command is
  discovered too rarely to be useful.

### Alternativa D -- Não fazer nada (status quo)

- Keep the single hardcoded Windows-measured 600 default with no local
  override mechanism.
- Descartada as a permanent answer (issue #279's own diagnosis is correct:
  a single-machine-measured constant is not genuinely adaptive), but this
  is exactly what ships for anyone who does not run the new calibration
  command -- by design, so this PR's risk is zero for every existing user
  until they opt in.

---

## Não escopo (explicitly deferred, not silently dropped)

Per issue #279's own 16-step plan and acceptance criteria, the following
remain **open, unimplemented follow-up work**, tracked here rather than
hidden. Two items below (marked **DONE**) were closed by the
"`ExecutionProfile` decision layer" update above and are kept in this list,
struck through rather than deleted, so the history of what got closed and
when stays visible in this ADR:

- Frozen per-platform benchmark corpus (plan step 1) and Linux/macOS
  dispatch-threshold measurements (only Windows is calibrated/verified by
  this PR's own testing).
- I/O-bound vs. CPU-bound vs. single-writer stage separation beyond what
  ADR-009 already documents (plan step 2 -- ADR-009's own profiling already
  covers most of this; no new stage-separation work in this PR).
- ~~`ExecutionProfile` enum with `thread`/`process`/`hub` profiles (plan
  step 4)~~ -- **DONE (partially)**: the enum now exists
  (`simplicio_mapper/mapper/execution_planner.py`) with all six values
  recognized as configuration vocabulary, but only `sync`/`async` have real
  execution behind them; `thread`/`process`/`hub` deterministically
  fall back to the `auto` sync/async decision and remain genuinely
  unimplemented (no thread pool, no process pool, no Hub client) -- see the
  update section above for the exact honesty boundary.
- Any real Hub integration (plan steps 9-11): global permits, single-flight
  result handles across worktrees, canonical-map/overlay composition tied
  to Hub-issued execution decisions. **No Hub client exists in this repo.**
- Structured cancellation quarantine beyond what ADR-009's
  `CancellationTest` already covers (plan step 13).
- ~~Route receipts publishing the chosen profile + reason (plan step
  14)~~ -- **DONE**: `ExecutionPlan.to_receipt()` attaches an
  `execution_plan` (schema `simplicio.execution-plan/v1`) entry to every
  `build_artifacts()` result, recording `requested_profile`,
  `selected_profile`, and `reason`. Scoped to the sync/async profiles this
  repo actually runs -- there is still no Hub to publish a receipt to
  external governance.
- Shadow rollout comparing a candidate profile without promoting it (plan
  step 15).
- Versioned, reproducible autotuning policy (plan step 16) -- there is no
  data yet (single-machine calibration files, not aggregated) to base one
  on.
- The full cross-platform/cross-condition test matrix issue #279 lists
  (cold/warm/incremental, cache hit/miss/corrupt, symlink/permission/file-
  removed-during-scan, cancel/timeout/process-crash, 10+ concurrent
  clients, CPU/RAM/I/O pressure, Hub available/unavailable/incompatible,
  property/fuzz chunking tests) is **not** run against this Phase-0 slice
  beyond the calibration module's own focused unit/integration/system
  tests (see "Testes" below) -- that full matrix targets the eventual
  Execution Planner, which this PR does not implement.

---

## Testes

- **Unit** (`tests/python/test_pipeline_calibration.py`): calibration-file
  read/write round trip; every fail-safe rejection branch of
  `load_calibrated_threshold` (missing file, corrupt JSON, non-dict JSON,
  wrong schema, missing/non-integer/boolean/non-positive threshold, all
  return `None` rather than raising); `write_calibration`'s atomic-write
  behavior (no stray `.tmp-*` file left behind, creates the output
  directory if missing); `run_calibration`'s real measurement path at
  tiny, fast sizes (well-formed payload shape, honest fallback to the
  caller-supplied default when async never wins at tiny sizes, does not
  leak or clobber a pre-existing env var override).
- **Integration** (`tests/python/test_pipeline_dispatch.py`, new
  `CalibrationOverrideTest` class): confirms the full precedence chain in
  `emit.py::_async_pipeline_min_files` -- no calibration file keeps the
  hardcoded default; a valid calibration file overrides it; the env var
  still wins over the calibration file; `build_artifacts()`'s real
  dispatch routing honors a cached calibrated threshold end to end.
- **System** (`tests/python/test_cli_benchmark.py`): drives the real
  `simplicio_mapper.cli.main()` entry point end to end -- usage/error
  paths for a missing or unknown `benchmark` sub-verb; a real
  `benchmark pipeline-threshold` invocation against a temp directory that
  actually writes `.simplicio/pipeline-calibration.json` (both `--json`
  and human-readable output modes verified); `--out` flag honored; a
  follow-up real `build_artifacts()` call against the same directory
  confirmed to honor the freshly written calibration file.
- **Regression**: the entire pre-existing
  `tests/python/test_pipeline_dispatch.py` suite (dispatch routing,
  boundary tests, byte-identical-output-across-dispatch tests,
  `_fast_file_count` probe tests) passes unchanged -- `_async_pipeline_min_files()`
  called with zero arguments (as every pre-existing test does) still
  returns the hardcoded 600 default exactly as before this issue, since no
  `cwd` means no calibration-file lookup is attempted.
- **Perf benchmark**: the calibration command *is* the benchmark -- it
  measures real `build_artifacts()` wall time, sync vs. async, forced via
  the same env var the production dispatcher reads, at each configured
  synthetic-tree size, and reports the crossover directly in its own
  output/receipt (`sizes_measured`, `recommended_threshold`, `calibrated`
  fields).
- **Coverage**: `simplicio_mapper/mapper/pipeline_calibration.py` reaches
  99% branch coverage in isolation
  (`python -m pytest tests/python/test_pipeline_calibration.py
  tests/python/test_pipeline_dispatch.py tests/python/test_cli_benchmark.py
  --cov=simplicio_mapper.mapper.pipeline_calibration --cov-report=term`).
  A full-repo `python -m unittest discover -s tests/python` run (979
  tests) shows only pre-existing, unrelated failures (Windows console
  Unicode-encoding assertions in `test_parity.py`'s Node-shim tests, and
  two `ModuleNotFoundError`s for `scripts.*` test helpers that predate this
  PR) -- none touch `pipeline_calibration.py`, `emit.py`'s dispatch logic,
  or the new `benchmark` CLI surface. A full-repo `pytest --cov` run in
  this specific sandbox additionally shows a larger number of environment-
  flaky failures (`git`-subprocess `OSError`s in canonical/identity tests,
  reproducible only under `pytest`, not under `unittest discover`, in this
  heavily-loaded shared sandbox running many concurrent agent worktrees) --
  reported honestly here rather than hidden, and unrelated to this PR's
  diff (none of the failing test files were touched by this change).

---

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-mapper/issues/279
- Parent epic: https://github.com/wesleysimplicio/simplicio-loop/issues/555
- Related: #236 (canonical map/overlays, ADR-008),
  wesleysimplicio/simplicio-loop#497
- Prerequisite ADR: `ADR-009-async-mapping-pipeline.md` (the size-based
  dispatch this ADR adds a calibrated override on top of)
- Files added/changed: `simplicio_mapper/mapper/pipeline_calibration.py`
  (new), `simplicio_mapper/mapper/emit.py`
  (`_async_pipeline_min_files`/`build_artifacts`), `simplicio_mapper/cli/_benchmark.py`
  (new), `simplicio_mapper/cli/__init__.py` (dispatch wiring),
  `simplicio_mapper/cli/_shared.py` (HELP_TEXT)
- Tests: `tests/python/test_pipeline_calibration.py` (new),
  `tests/python/test_cli_benchmark.py` (new),
  `tests/python/test_pipeline_dispatch.py` (`CalibrationOverrideTest`,
  extended)

### Links (execution-profile decision-layer update)

- Files added/changed: `simplicio_mapper/mapper/execution_planner.py`
  (new -- `ExecutionProfile`, `ExecutionPlan`, `plan_execution`),
  `simplicio_mapper/mapper/emit.py` (`build_artifacts` now dispatches via
  `plan_execution` instead of an inline threshold comparison),
  `simplicio_mapper/mapper/pipeline_shadow.py` (doc cross-reference only),
  `docs/local-setup.md` (`SIMPLICIO_MAPPER_EXECUTION_PROFILE` /
  `SIMPLICIO_MAPPER_NO_ASYNC_PIPELINE` documented).
- Tests: `tests/python/test_execution_planner.py` (new --
  `ExecutionPlannerUnitTest` covers every `plan_execution` branch including
  the unrecognized-env-value fallback; `ExecutionPlannerIntegrationTest`
  covers the real `build_artifacts()`/`write_mapping_artifacts()` route
  receipt and kill-switch dispatch end to end). 100% branch coverage on
  `execution_planner.py` in isolation
  (`python -m pytest tests/python/test_execution_planner.py
  --cov=simplicio_mapper.mapper.execution_planner --cov-report=term-missing`).
  Full pre-existing `tests/python/test_pipeline_dispatch.py`,
  `test_pipeline_calibration.py`, and `test_pipeline_shadow.py` suites pass
  unchanged, confirming this was a behavior-preserving refactor.
- Perf benchmark: not applicable -- this is a pure refactor of an existing
  inline comparison into a named, independently testable decision function.
  No new I/O, no new timing-sensitive code path, and no change to which
  branch (`sync`/`async`) is selected for any given `(file_count,
  threshold)` pair, so there is nothing new to benchmark.
