# Restarted flow comparison — 2026-09-11

Status: qualification in progress; no new comparative winner or completed paid comparison arms.
See [measured release qualification](BENCHMARK_RELEASE_QUALIFICATION.md) for the
restarted native commands, resource receipts, and blockers.
Previous diagnostic observations remain separate and must not be reused as arms.

| Candidate | Real entry point | Comparison boundary |
|---|---|---|
| wave (default) | simplicio-loop wave --repo FIXTURE RUN_ID | governed wave with reconciliation barriers (substitui 'run') |
| batch automatic | simplicio-loop batch --repo FIXTURE RUN_ID | ten admitted tasks and final validation |
| serial | simplicio-loop batch --serial --repo FIXTURE RUN_ID | same tasks, one active lane |
| tasks | simplicio-loop tasks run --agent-command COMMAND --action-gate SCOPE | current implementation requires GitHub PR and authenticated merge evidence |
| Prism | installed PrismScheduler with a real worker | admission, dependency handling, proposals, edits and validation; not scratchpad arming |
| wave | production wave barrier with explicit batch width | distinguish policy variation from a distinct scheduler; never duplicate a Prism result |
| limited legacy control | bounded semaphore control | replace synthetic sleeps with the same real worker; not a public Loop command or legacy Hookwall storage |

All candidates require centrally prepared Mapper artifacts with real digests and
freshness verification. Fast off/on are separate variants, not replacements for
Mapper. No worker rebuilds central artifacts. A limited control has an explicit
recorded ceiling; all production candidates retain safe physical admission.

## Equal-work and cache contract

- Freeze one seed including task specifications before preparing Mapper. Every
  arm starts from identical source, task dependencies and independent tests.
- Fix the model to deepseek/deepseek-v4.1-flash and retain provider routing and
  generation IDs. No substitution without an explicit recorded decision.
- Place the exact producer-certified Mapper prefix before variable task content;
  record prefix digest, Mapper generation, context digest and actual request
  order. Reuse only while the matching generation remains valid.
- Request cache reuse through supported provider mechanisms, but do not claim
  that a prefix guarantees cache residency. Classify cold/warm by observed usage,
  not by the caller's intention. Absent cache fields remain unavailable.
- Run arms sequentially, rotate order across repetitions, and charge preparation,
  rejected proposals, repairs and final integration to each arm's totals.
- Do not compare tasks-run PR/merge completion to local implementation latency.
  Either use a common real delivery boundary or explicitly report stage-only
  comparisons without claiming complete tasks-run equivalence.

## Verified interface corrections

Installed Loop reports 3.43.10. `tasks --help` and `tasks run --help` execute even
though the prior generic top-level help traversal missed this forwarded surface.
`batch --help` documents both `--serial` and `--batch-size` (Prism wave width).
The historical `_legacy` function in bench/prism_benchmark_852.py is an asyncio
semaphore around synthetic work. Its old results cannot rank real implementations.

The tasks composition currently constructs CommandPipelineCoordinator before
intake. That coordinator requires an agent command even when the CLI dry-run
passes an empty command. Its delivery validation also requires PR URL, successful
checks and a locally verified merge bound to authority/fence. Fabricating these
receipts to make a simulated local task pass is not allowed.
