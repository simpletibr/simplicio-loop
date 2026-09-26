# Technical-debt notifications

The loop distinguishes a **safe capability degradation** from a **hard execution blocker**.

Safe degradations use the versioned `simplicio.technical-debt/v1` contract. They are persisted
under each run as:

- `.simplicio-loop/.../technical-debt.jsonl` — append-only observations;
- `.simplicio-loop/.../technical-debt.json` — deduplicated current index;
- `state.json` and `events.jsonl` — progress/status projection.

A repeated observation keeps one fingerprinted notice and increments `occurrences`. The notice
contains its reason, severity, current status, and the next action required to remove the debt.

## Safe examples

- automatic fan-out is disabled or unavailable;
- a repository cannot provide isolated worktrees, so the safe serial lane is used;
- overlapping task targets prevent parallel execution;
- an optional telemetry/reporting capability is unavailable;
- a drain item is quarantined while unrelated items continue.

These conditions set `degraded: true` and surface `technical_debt_count`, but do not turn a
running run into `BLOCKED`.

## Hard blockers remain fail-closed

The notification path must never downgrade:

- safety, privacy, or authorization failures;
- budget exhaustion;
- source/plan drift;
- invalid or stale mutation authority;
- stale leases/fences;
- invalid receipts;
- corrupted task contracts;
- mandatory quality or evidence failures;
- a configured remote queue becoming unavailable.

A debt notice is advisory and never counts as acceptance-criteria evidence or completion proof.
The oracle still requires fresh operator, evidence, watcher, delivery, and completion receipts.
