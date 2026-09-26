# Queue workflow benchmark and execution policy

## Restarted native-release qualification

The [new qualification report](BENCHMARK_RELEASE_QUALIFICATION.md) records real
`run`, `batch --serial`, `resume`, and `tasks` probes, exact commands, CPU/RAM,
dependency repair, capacity refusals, and 107 help checks. The full equal-work
comparison is **incomplete**. No fastest/cheapest default has been proven; the
diagnostic numbers below are not replacement comparison arms.

## Latest verified checkpoint — 2026-09-11

**Open the results:** [interactive report and charts](../.lavish/queue-benchmark-20260911/report.html),
[all measured command stages](../.lavish/queue-benchmark-20260911/diagnostics.md),
and [machine-readable metrics plus input hashes](../.lavish/queue-benchmark-20260911/summary.json).

| Observed diagnostic metric | Value |
|---|---:|
| Independently verified tasks | 10 / 10 |
| Paid provider responses, including rejected format | 11 |
| Input tokens | 35,654 |
| Output tokens, including reasoning | 4,694 |
| Reasoning tokens (subset, do not add again) | 3,916 |
| Cached input tokens | 1,920 |
| Cache-write tokens | 0 |
| Provider-reported total cost | USD 0.01576452 |
| Provider response latency p50, nearest rank | 3.509253416 s |
| Provider response latency p99, nearest rank | 5.653904333 s |
| Resource-instrumented stages | 48 |
| Sum of instrumented-stage local CPU | 14.597821 CPU-seconds |
| Maximum sampled process-tree RSS among instrumented stages | 122,322,944 bytes |
| Machine | macOS 26.3 / ARM64 / 8 logical CPUs / 8 GiB RAM |

Latency quantiles describe eleven heterogeneous diagnostic calls, including the
rejected proposal, not task end-to-end latency or an equivalent workflow arm.
The p99 is the sample maximum and has no credible tail estimate here. The cache
hit was observed on the explicit ADO-303 repair (1,920 of 2,158 prompt tokens),
not inferred from Mapper reuse. It does not establish comparative savings.
The cost excludes this supervising agent and its subagents, local electricity,
and any uninstrumented work. It includes all eleven recorded OpenRouter calls.
CPU/RSS cover only the 48 recorded stages, not the entire session: the initial
two pilots lack complete resource sampling. CPU-seconds are local, not provider
compute. RSS is a sampled maximum (100 ms), not a precise OS high-water mark.

**Capacity correction:** the published source's CLI `main()` already resolves
`--slots 0` using `recommend_prism_slots()`. The narrower direct Python call
`arm(slots=0)` previously clamped it to one. The local patch centralizes auto
resolution in `arm()` and rejects negative slots consistently. The earlier
claim that the CLI itself clamped zero to one was incorrect. This small API
consistency fix is not evidence that all commands have safe adaptive saturation.

The diagnostic fixture now passes **all ten independent behavioral checks**,
including the test task's rejection of the original mutant. Evidence:
`.simplicio-loop/benchmark/queue-final-verification-20260911/stdout.txt` and its
resource `receipt.json`. This completes the diagnostic implementation pilot,
**not** the equivalent-arm Loop performance comparison. There is still no
qualified fastest/cheapest production default. The sections below preserve the
chronological observations; earlier zero/seven-task counts are historical.

The last three accepted attempts are `diagnostic-ADO303-repair`,
`diagnostic-GH101-requirements`, and `diagnostic-GH104-requirements` under
`.simplicio-loop/benchmark/`. ADO-303 used one explicit format repair after a terminal
response; both paid calls count. No unresolved request was retried. GH-101 and
GH-104 initially failed Mapper lexical-coverage gates (0.182 and 0.154 versus
0.200). Reading the task file alone did not fix GH-104. The fixture then received
two input-only requirement documents under `requirements/`, central artifacts
were refreshed, and both handoffs passed without reducing the gate. These
fixture changes disqualify this sequence as an unchanged-fixture arm comparison.

The installed release remains distinct from local source changes. The final
focused selection has 24 passing tests (8 importlib deprecation warnings),
covering instrumentation, aggregation, repair guards and Prism arming. The
token-budget-only gate passes; `git diff --check` passes. The OpenRouter-key
pattern scan over the edited reporting paths found no credential occurrences.
Neither observation certifies the complete repository suite or all CLI flows.

The full `scripts/check.py` invocation exited 1: the first three reported shards
had 90 passes, 69 passes, then 51 passes and one failure in
`test_batch_crash_recovery_system.py::test_orchestrator_crash_mid_batch_is_recovered_by_a_fresh_process`
(process A exited before journaling item 0). Evidence:
`.simplicio-loop/spill/1789138614-python-ccadfa6775bf.log`.
During that check a parallel worker invoked a checkpoint that stashed the dirty
tree (`f27e524d44945ba03368fba4a1b2749b47a42704`). The source/report were recovered,
and ignored benchmark receipts remained intact. Because the source state changed
during execution, this check is not a reproducible validation of the final patch.
It is a failed observation, never a green release gate. Further broad validation
must use an isolated frozen checkout; workers must not stash the shared tree.

Additional read-only functional probes are stored as `cli-probe-doctor-resource`
and `cli-probe-economy-status`. Resource doctor returned exit 2 with
`RESOURCE_FABRIC_NOT_STARTED`, effects not attempted. Economy status returned
exit 0, detected 8 CPUs, and proposed 8 operator workers, 7 Prism slots and 16
async-I/O concurrency. These recommendations are not proof of safe saturation.
It also proposed `SIMPLICIO_REQUIRE_MCP=1` and `SIMPLICIO_MCP_FORCE=1`, contradicting
the intended CLI-only mode; this profile was inspected, not applied. Both probes
ran while the repository check was active, so their resource timings are
diagnostic observations, not isolated performance samples.

## Required operating policy

Mapper is mandatory in every Loop work-execution flow, including standalone,
Prism, sequential, and Fast-assisted routes. Prepare the context centrally;
workers consume the matching generation and digest read-only. Refresh centrally
after relevant source changes. Missing or stale context blocks execution.
Read-only diagnostics and help must remain usable to repair missing dependencies.
Runtime remains optional for ordinary Loop orchestration. Fast accelerates
retrieval from compatible Mapper artifacts; it does not replace Mapper.

Use automatic machine capacity by default. Logical task count is not physical
concurrency. Physical admission must preserve foreground responsiveness and
respect CPU, memory, disk, leases and conflicting edits. A positive explicit
worker setting is a user ceiling, not permission to bypass physical admission.

Context reduction and provider prompt caching are separate measurements. Put
stable, bounded Mapper context before variable task instructions; keep that
prefix byte-identical while its generation remains valid. Record input, cached
input, output, reasoning tokens and cost from provider usage receipts. Missing
fields are unavailable, never zero. Do not infer a cache hit from local reuse.

## Equal-work experiment

Use one frozen fixture and these ten tasks. The sources are local simulated
records, not live tickets or evidence of remote adapter authentication.

| ID | Simulated source | Work | Independent acceptance check |
|---|---|---|---|
| GH-101 | GitHub | Create slugify | Case, surrounding whitespace, repeated whitespace |
| GH-102 | GitHub | Fix total | Empty input, negatives, positive list |
| GH-103 | GitHub | Locate timeout | Exact pointer `/network/timeout_seconds`, value 30 |
| GH-104 | GitHub | Add total tests | Tests pass against correct code and reject original bug |
| JIRA-201 | Jira | Create stable unique | Repeated values retain first-occurrence order |
| JIRA-202 | Jira | Fix clamp | Below, within and above range |
| JIRA-203 | Jira | Document timeout | Value 30 and seconds agree with configuration |
| ADO-301 | Azure DevOps | Locate deprecated endpoints | Exact sorted names `legacy`, `v0` |
| ADO-302 | Azure DevOps | Create median | Odd/even lists and unsorted input |
| ADO-303 | Azure DevOps | Fix boolean parsing | True/false case variants; invalid input rejected |

GH-104 depends on GH-102. Keep the same dependency in every arm. Any composed
result needs a final verification; worker success alone is insufficient.

| Arm | Mapper | Fast | Execution |
|---|---|---|---|
| A | Required, central | Off | Sequential reference |
| B | Required, central | Off | Prism/wave, automatic physical capacity |
| C | Required, central | On | Sequential reference |
| D | Required, central | On | Prism/wave, automatic physical capacity |

The serial reference intentionally limits overlap to quantify the benefit of
parallel execution. All production candidates use automatic admission. Do not
run competing arms concurrently. Rotate arm order between repetitions to reduce
time-of-day and cache-order bias. Pin release, provider/model and request settings.
Record cold preparation separately and include it in end-to-end totals.

## Commands and evidence

1. `simplicio-loop --version`: identify the installed release; hash package files.
2. `simplicio-loop preflight --json`: inspect operator availability.
3. `python3 bench/queue_workflow_benchmark.py --prepare`: create isolated simulated
   source records and ten task contracts; measure central Mapper scan/inspect.
   This command is preparation only, not task completion.
4. `simplicio-mapper handoff <fixture> --goal <goal> --json`: bind bounded task
   context to the centrally prepared generation; verify freshness and digests.
5. `simplicio-loop run --task <task.md> --repo <fixture>`: establish the real run
   and required planning/authority receipts; inspect actual outcome before dispatch.
6. `simplicio-loop tick --repo <fixture> --task-index <n> <run-id>`: sequential
   task execution, or `simplicio-loop batch --repo <fixture> --batch-size 10
   --max-workers 0 <run-id>` for automatic concurrency after valid run admission.
7. `simplicio-loop verify --help` and the independent task verifier: prove output
   correctness; record final composed verification and all retries.
8. `simplicio savings report --repo <fixture> --json`: use only run-attributable,
   provider-backed spend when comparing model cost.

Help probes and static inventories are command coverage, not execution coverage.
Install/publish/cancel/rollback commands are not repeated for each coding task.
Mark each interface as executed, help-only, blocked, or not applicable.

### Exhaustive interface coverage and bounded combination coverage

Inventory every public installed entry point, command and nested subcommand
from the pinned release. Reconcile that inventory against the documented CLI;
file counts and private Python functions are not public command counts. Locate
Prism and wave explicitly, including interfaces exposed outside the top-level
`simplicio-loop` parser. Do not infer that either is a top-level command.

Maintain one coverage row per interface and scenario: exact argv, preconditions,
fixture revision, Mapper generation/digest, expected outcome, actual outcome,
receipt path, and independent verification. Distinguish `not-run`, `help-only`,
`executed-unverified`, `verified`, `blocked`, and `not-applicable`. A successful
help probe cannot promote a row to executed or verified.

Exercise valid workflow compositions, not an arbitrary Cartesian product:

- Entry routes: task/run, tick, batch, queue/drain, resume and single-task-fast,
  wherever supported by the pinned release and its actual contracts.
- Scheduling: serial control, native automatic admission, Prism and wave;
  distinguish separate implementations before treating them as separate arms.
- Context: mandatory central Mapper, with and without compatible Fast;
  valid cold and reused generations, plus stale-generation rejection tests.
- Dependency patterns: independent tasks, ordered dependencies and conflicting
  file edits. Never change a workload pattern within a paired comparison.
- Lifecycle: checkpoint/resume, bounded retry, cancellation and recovery on
  disposable owned fixtures; do not cancel unrelated user processes.
- Integration: standalone and Runtime-backed when available; local simulated
  source records do not certify live GitHub/Jira/Azure DevOps adapters.

Use pairwise coverage for compatible dimensions, then explicitly cover
high-risk interactions: stale context plus resume, dependent tasks plus wave,
conflicting edits plus batch, and physical pressure plus cancellation.
Record excluded combinations and reasons. This is bounded combinatorial
coverage, never a claim that every possible argument permutation was tested.
Publishing, deployment and external ticket mutation require their own authorized
target; document their coverage separately from the coding-performance ranking.

Freeze the coverage matrix before timed trials. First prove functional parity,
then benchmark qualifying routes with the same ten tasks, provider settings and
verification gates. Separate provider-cache cold/warm observations from local
Mapper/Fast reuse. Charge preparation, retries and final integration verification
to end-to-end cost and time, while also reporting those stages individually.

## Metrics and promotion rule

Every command receipt includes argv without secrets, working directory, exit
code, monotonic duration, stdout/stderr artifacts, version and digest. Capture
per-task queue wait, execution and verification separately. Sample CPU and RSS
for the coordinator and owned child process tree; a process-wide RSS high-water
mark cannot be assigned to each worker. Report sampling interval and missing data.

Collect task latency p50/p99, batch makespan, successful tasks per minute,
CPU-seconds, peak/mean RSS, retries, provider input/output/cache/reasoning tokens,
and actual cost per verified task. With ten samples, nearest-rank p99 equals the
maximum and is exploratory. Use repeated batches before selecting a default.

Only arms delivering the same ten verified outputs qualify. Report the fastest
and cheapest qualifying arms separately; if different, show their tradeoff.
No winning production default has been established by this session yet.

## Current evidence and corrections

Global Loop was upgraded from 3.43.8 to release 3.43.10 and its version verified.
The new preparation run compiled all ten task contracts and executed central
Mapper scan/inspect successfully. Its artifacts are under
`.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/`.
No task implementation or provider call is represented by these preparation times.

The earlier `prism-run.json` measures synthetic `asyncio.sleep` scheduling only.
S1 is an asyncio semaphore control, not a public legacy command. S4 reuses S2's
result rather than executing an independent fallback trial. The script hardcodes
Runtime protocol incompatibility after a version probe, so that result cannot
prove the installed Runtime lacks a particular feature. The previously quoted
1.039 ms telemetry overhead belongs to an older checked-in receipt, not the new
30-event/3-sample execution. Do not use any of these as a production recommendation.

The source capacity changes are uncommitted and are not included in the installed
3.43.10 release. Nine worker-demand tests passed. Broader focused validation
reported 29 passes and one failure in owned-process termination under pressure;
the failing worker reports a TypeError before producing shutdown evidence.
This remains an unresolved validation failure.

### Actual release execution probes (2026-09-11, 14:04 UTC)

These are failed admission/verification probes, not timed provider trials.
The installed executable reports 3.43.10 and loads
`/opt/homebrew/lib/python3.14/site-packages/simplicio_loop`.
Its Prism scheduler SHA-256 is
`9e498473d8205f54abb082c0b2a4fd276fb94d802b9f6e0f06e869b54acf24df`.
A fresh environment check reports `OPENROUTER_API_KEY` absent. No authenticated
OpenRouter request has been executed by this benchmark.

Both probes used the existing fixture and this command shape:

```text
simplicio-loop run --task <root>/<ID>.md --repo <root>/fixture --delivery implemented --result-file <root>/run-<ID>.json
```

Here `<root>` is `.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z`.

| Task | Run ID | Actual result | Full output |
|---|---|---|---|
| GH-101 (create) | run-20260911-140438-7p4izo65 | Exit 20, BLOCKED: mapper-derived plan rejected `target_missing_without_to_create:src/slug.py` | `.simplicio-loop/spill/1789135480-sh-940c27561006.log` |
| GH-102 (edit) | run-20260911-140449-2ncdndnm | Exit 20, BLOCKED: planning and operator dry-run completed, then independent watcher unavailable | `.simplicio-loop/spill/1789135492-sh-22d354884ef9.log` |

Outcome receipts are `<root>/run-GH-101.json` and `<root>/run-GH-102.json`.
The fixture has no `scripts/watcher_verify.py`, which the inspected `verify_run`
implementation requires. This is a benchmark fixture prerequisite, not evidence
that every installed Loop workflow is broken. The creation failure also needs
classification between task-contract setup and release behavior before assigning
root cause. Neither probe delivered a task or proves a provider defect.

The supervising shell additionally reported degraded failure-ledger persistence
(read-only filesystem and lock timeout). Preserve these diagnostics separately
from the Loop exit code; do not delete locks to make the trial pass.

Input/output/cache/reasoning tokens, provider latency, CPU-seconds, sampled RSS,
and cost per delivered task are unavailable for these probes. Tool round-trip
wall times are not model latency. There is no eligible arm and no measured
fastest/cheapest default. Next prerequisites are secure provider authentication,
a real independent fixture verifier, valid creation intents, and a live provider
worker integrated with the admitted Loop route. Do not substitute a standalone
HTTP benchmark and label it a complete Loop benchmark.

### Resumed-session provider and routing checks

The resumed session received `OPENROUTER_API_KEY`. The new
`bench/openrouter_preflight.py` reads it from the environment and does not persist
the credential or authentication response body. Both authenticated `/key` and
`/models` requests succeeded, and the exact requested model
`deepseek/deepseek-v4.1-flash` exists. Evidence:
`.simplicio-loop/benchmark/openrouter-preflight-20260911.json`.
These are metadata requests, not completions; completion calls remain zero.
Provider access is no longer a blocker.

The bounded CLI help sweep completed 105 help invocations across 12 installed
entry points. Evidence is
`.simplicio-loop/benchmark/cli-coverage-bounded-20260911/coverage.json`.
This is not 105 functionally verified workflows. Forwarding wrappers that repeat
parent help require manual reconciliation. The earlier unbounded sweep expanded
such repeated help and was terminated; its inflated count is invalid coverage.
The discovery unit tests passed: `python3 -m pytest -q
tests/test_benchmark_help_discovery.py` (3 passed).

Additional actual execution probes:

| Invocation | Observed outcome | Evidence under `.simplicio-loop/spill/` |
|---|---|---|
| `tick --task-index 1` on `run-20260911-140449-2ncdndnm` | Exit 1: `LEGACY_HOOKWALL_READ_ONLY`, before operator effect | `1789136839-simplicio-loop-41fe3be1bb01.log` |
| New GH-102 `run` with `SIMPLICIO_STORAGE_ROUTE=mapper` | Exit 20: `mapper_replay_failed:STORE_NOT_INITIALIZED` | `1789136869-env-d00126986fc4.log` |
| `queue --route mapper --mapper-init status` against the fixture | Exit 0, operations API response | Command output observed; not a completion receipt |
| Mapper `tick --task-index 1` on `run-20260911-142746-7pd78ywz` | Exit 1: `HookwallBlocked: stale_fence`, before operator effect | `1789136879-env-41bd4912fb63.log` |
| New GH-102 Mapper `run` after queue initialization | Exit 20: `STORE_NOT_INITIALIZED` still reported | `1789136888-env-393c4536b2ce.log` |

All commands target `<root>/fixture` as defined above; the new runs use the same
GH-102 task contract and `--delivery implemented`. Do not alter frozen route
receipts, fabricate fences, or bypass Hookwall to produce timing samples.
The successful queue initialization did not establish that run dispatch resolved
the same operations store. Store selection/admission needs reconciliation before
the execution benchmark can proceed. These failures are not measurements of
OpenRouter, Prism throughput, or delivered-task cost. No winning standard is
established; the end-to-end benchmark remains incomplete.

### First live model-worker observation and narrowed storage diagnosis

Changing only the invocation working directory to the fixture removed
`STORE_NOT_INITIALIZED`: new run `run-20260911-143204-xop6dbry` reached
`watcher_unavailable` instead. Its operator remained `dry_run`. Source inspection
shows `_dispatch_journal_backend` resolves its Mapper database from `Path.cwd()`;
this explains why initializing the fixture store did not satisfy a dispatch
started in the parent repository. This diagnosis does not resolve leases or
complete execution. The published package was not modified for this probe.

`python3 bench/verify_queue_fixture.py --repo <root>/fixture` now independently
checks the ten behaviors and correctly rejected all ten unfinished tasks.
Evidence: `.simplicio-loop/spill/1789137165-python3-817de04374a8.log`.
The verifier is not yet wired into the Loop watcher receipt protocol.

`bench/openrouter_worker_probe.py` made one real proposal request for GH-102,
using that run's recorded Mapper context. It did not apply files or claim a task
delivery. Receipt: `.simplicio-loop/benchmark/openrouter-worker-GH-102.json`.

| Metric | Observed value |
|---|---:|
| Exact model | `deepseek/deepseek-v4.1-flash` |
| Actual routed provider | SiliconFlow |
| Request-to-complete-response wall time | 3.983171833 seconds |
| Input tokens | 16,297 |
| Completion tokens (including reasoning) | 96 |
| Reasoning tokens (subset of completion) | 73 |
| Cached input tokens | 0 |
| Cache-write tokens | 0 |
| Provider-reported cost | USD 0.0050043 |
| Verified delivered tasks | 0 |

Generation ID: `gen-1789137197-EbUUQo7rCUWcPvmpx2IR`. These are actual usage
fields, not estimates derived from catalog pricing. Do not add reasoning tokens
again to total completion tokens. A single response does not support a p50/p99
comparison or a winning workflow. CPU/RAM and TTFT were not sampled in this probe.

The input is large for a two-line function repair: the probe supplied the raw
Mapper context receipt, not an optimized task-bounded handoff. This establishes
a concrete candidate for measurement, not proven savings: compare a certified,
bounded Mapper handoff and stable prefix against this diagnostic input while
holding task correctness constant. Mandatory Mapper does not imply sending its
entire diagnostic receipt to the model. This probe is outside the qualified
end-to-end ranking and must not be counted as a complete Loop benchmark arm.

### First applied and independently verified proposal

The GH-102 response was compiled by `bench/proposal_to_edit_plan.py`, which
checks completion, the task write set, path containment and Python syntax without
applying anything. The installed Dev CLI accepts a single-file native plan with
`file` and `operations`; native replacement requires `find`/`with`, not
`old`/`new`. Failed preparatory plan versions remain preserved as diagnostics.
Use absolute plan and repository paths: relative paths were duplicated during
the observed native delegation.

The Dev CLI dry-run returned `native_delegation_invalid_result` after the format
was corrected. A direct native invocation of `simplicio edit --repo <fixture>
--plan <absolute GH-102-validated-edit-plan.json>` applied the one replacement.
This command applies by default; it was not a read-only inspection. The native
writer reported source SHA-256 changing from
`d3410e41e520be190c95bd5d8b61a74983b4b559301e52d96d1ac0164fae96da`
to `3251dbf18617cd67c47707cb9bd1611dbac212ff0ee9814a75b8ce1f34b85aad`.

`python3 bench/verify_queue_fixture.py --repo <fixture> --task GH-102` exited 0.
The observed diff changes only `return len(values)` to `return sum(values)`.
Thus one model-generated implementation is behaviorally verified, but no Loop
completion receipt has been established. It is a diagnostic composed route
(Mapper context, OpenRouter proposal, native Runtime edit, independent checks),
not a completed `tick`/`batch` arm. Its earlier provider cost cannot be presented
as full end-to-end cost or the winning ten-task workflow. Nine fixture tasks
remain unfinished, and the central Mapper context must be refreshed before
further source-dependent work on this now-changed fixture.

### Bounded-context preparation and second verified implementation

After central Mapper refresh, `bench/prepare_queue_contexts.py` tested ten
handoffs at each of 1,200, 6,000 and 12,000 envelope tokens, with `--limit 2`
and `--execution-context`. Evidence directories are
`.simplicio-loop/benchmark/bounded-contexts-20260911`,
`.simplicio-loop/benchmark/bounded-contexts-6000-20260911`, and
`.simplicio-loop/benchmark/bounded-contexts-12000-20260911`.
Only the last configuration produced ready handoffs (seven of ten). GH-101,
GH-104 and JIRA-203 still requested broader context and were not submitted.
Exit code zero alone did not prove readiness: the JSON gate was also checked.

The worker's `--handoff` mode requires a ready parent handoff and a sufficient,
non-abstaining execution context. It sends the producer's execution-context
object, not the complete diagnostic wrapper. It records both parent and sent
context digests. GH-103 used this mode and produced the exact expected JSON
pointer/value answer, applied by native `simplicio edit` and independently
verified with `verify_queue_fixture.py --task GH-103` (exit 0).

Provider receipt: `.simplicio-loop/benchmark/openrouter-worker-GH-103.json`.
Actual request time was 3.890690084 seconds; input 1,725 tokens; completion 429
tokens including 393 reasoning tokens; cached input 0; reported cost USD
0.0010323; actual provider SiliconFlow. This is a different task from GH-102,
so their token/cost difference is not an equal-work savings measurement.
Two diagnostic implementations are now independently verified. Eight tasks,
Loop completion integration, equivalent-arm repeats and full resource sampling
remain. The fixture changed again; refresh centrally before further retrieval.
The bridge and help tests still pass (7 tests). Native create operations require
`text`, while replace uses `find`/`with`; the bridge now emits those fields.

### Resource instrumentation readiness

`bench/measure_command.py` now records each owned command's exact argv, cwd,
exit code, wall time, stdout/stderr files, 100 ms process-tree RSS samples,
time-weighted RSS, system-accounted reaped-child CPU time, and sampled CPU lower
bound. Host available RAM, load and CPU utilization are separate observations.
Short-lived children may escape sampling; summed RSS may include shared pages;
the sampled maximum is not an exact OS peak. No provider tokens are inferred.
Timeouts stop only the newly owned process group and are marked explicitly.

The instrumentation dependency is isolated in
`.simplicio-loop/benchmark/telemetry-venv` (psutil 7.2.2), not added to production
dependencies or the global Loop release. Resource, proposal and help tests passed
with this environment: 10 passed in 0.43 seconds. A real GH-103 verification was
measured separately under `.simplicio-loop/benchmark/resource-verifier-pilot`; it is
not a full provider/task measurement and is not included in any arm ranking.

After GH-103, central Mapper scan and handoffs were refreshed under
`.simplicio-loop/benchmark/contexts-after-GH103`. The native-shell entrypoint is now
blocked by the active host hook; commands were moved to the permitted Simplicio
MCP transport. That transport's environment probe reported the OpenRouter key
absent, unlike the earlier CLI child environment used by the two paid probes.
No additional paid request was attempted and no credential was put in argv.
This transport mismatch is a current prerequisite for further provider trials;
the earlier successful authentication receipts remain historical evidence.

### CLI-only continuation: seven independently verified tasks

The user clarified that MCP is not required. A fresh governed native CLI probe
succeeded with the key present, and paid execution resumed through that CLI.
The earlier MCP environment mismatch is not a blocker for this available route.

JIRA-201 was proposed, applied and independently verified with separate resource
receipts in `resource-worker-JIRA201`, `resource-apply-JIRA201`, and
`resource-verify-JIRA201` under `.simplicio-loop/benchmark`. Its provider receipt is
`openrouter-worker-JIRA-201.json`: 5.192997791 seconds, 1,670 input tokens,
716 completion tokens (647 reasoning), zero cached input, USD 0.0013602.

`bench/run_diagnostic_task.py` now automates central scan, readiness-checked
handoff, measured model request, bounded proposal compilation, native application
and independent verification. It explicitly records `eligible_loop_cli_arm:false`:
it is a composed diagnostic route, not an invented `tick`/`batch` completion.
It never automatically retries a provider request, overwrites a prior measurement,
or applies a proposal outside the task's write set. The later explicit repair
accepts only terminal responses rejected for a missing `files` envelope.

Pilot directories `diagnostic-JIRA202`, `diagnostic-JIRA203`, `diagnostic-ADO301`
and `diagnostic-ADO302` each contain a successful summary plus all five stage
resource receipts. JIRA-202 measured 5.196314167 seconds end-to-end for this
diagnostic route and USD 0.0008724 provider cost. These task-specific observations
do not replace repeated equal-work arm comparisons.

The consolidated independent verifier now reports seven passes and three
failures (GH-101, GH-104, ADO-303). Evidence:
`.simplicio-loop/spill/1789137919-python3-0f37bb9c01e7.log`.
ADO-303 returned a root-level path/content object instead of the required
`files` object; the proposal was rejected before application. Its earlier generic
error said scope escape, but inspection proves a response-shape failure, not an
extra-file request. The validator now distinguishes these errors. Preserve that
paid response and its cost in `diagnostic-ADO303/provider.json`.
GH-101's new attempt stopped at Mapper readiness without calling the provider
(`diagnostic-GH101/summary.json`). No winning standard is established yet.
