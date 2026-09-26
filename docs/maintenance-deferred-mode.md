# Maintenance-deferred / backlog-only mode

Use this mode when a control-plane substrate is frozen for maintenance but the broader loop must keep making progress. It converts discovered correction work into a durable receipt and leaves mutation for a later maintenance window.

## Active run -> backlog-only correction capture -> broader goal continues

The maintenance-deferred flow has three distinct stages:

1. Start a normal run while the broader goal is still active.
2. When the run discovers a correction that cannot safely mutate the frozen control plane, capture it with `maintenance-deferred --mode maintenance_deferred --disposition backlog_only`.
3. Resume the run after the maintenance window so the broader goal continues with a fresh mapper/operator pass instead of a fake completion.

The correction stays measurable because the run writes a dedicated receipt and explicitly keeps `completion.ready=false`. The broader goal also stays alive because the next step becomes `resume_from_maintenance_receipt`, not `done`.

## Example commands

```powershell
python -m simplicio_loop.cli run --repo . --task task.md
python -m simplicio_loop.cli maintenance-deferred --repo . <run-id> `
  --mode maintenance_deferred `
  --disposition backlog_only `
  --correction-summary "Runtime scheduler correction discovered" `
  --deferral-reason "Active control-plane run is frozen" `
  --resume-instruction "Re-arm from maintenance-receipt.json" `
  --resume-instruction "Run the operator after the maintenance window"
python -m simplicio_loop.cli resume --repo . <run-id>
```

The command writes `.simplicio-loop/orchestrator/runs/<run-id>/maintenance-receipt.json` with the correction, reason, resume instructions, timestamp, and evidence status. It sets `completion.ready=false`, marks the operator `backlog_only`, and advances `next_action=resume_from_maintenance_receipt`. No mutation operator is invoked and a completion promise remains rejected until the normal evidence and watcher gates pass.

### Requesting a local-only run

`--delivery` accepts one of `implemented, verified, pr-open, merge-ready, merged, released,
deployed` (see `simplicio_loop.cli run --help`); pass `--delivery implemented` when you only want
the change applied and verified locally, without requiring a PR/merge/release to be considered
satisfied:

```bash
python -m simplicio_loop.cli run --repo . --task task.md --delivery implemented
```

`resume` is the handoff back into the broader goal. It clears the maintenance-deferred flag back to active mode, invalidates stale operator/evidence receipts, and sets `next_action=mapper_scan_required` so the follow-up attempt re-enters the normal decision/apply/verify path with a writable control plane.

## Deferral rationale

Use backlog-only when all three are true:

- the broader goal should keep its state and audit trail;
- the discovered correction belongs to a frozen or maintenance-owned control plane;
- the safest honest outcome is "captured for later mutation" rather than "applied now".

Do not use backlog-only as a generic skip path. If the control plane is writable and the chosen change is safe, stay in normal converge/operate mode.

## Resume steps

1. Inspect `.simplicio-loop/orchestrator/runs/<run-id>/maintenance-receipt.json` and confirm the correction summary plus resume instructions.
2. Re-open the run with `python -m simplicio_loop.cli resume --repo . <run-id>`.
3. Re-run mapper/operator work from the resumed state (`next_action=mapper_scan_required`) during the writable maintenance window.
4. Finish only after the normal evidence, watcher, and completion gates pass.

## Runnable example

For a deterministic end-to-end smoke check that exercises the exact sequence above without touching production systems, run:

```powershell
python examples/maintenance-deferred/run_example.py
```

The script creates a temporary repo, seeds a minimal active run, captures a backlog-only maintenance correction, resumes the run, and exits non-zero if any contract detail drifts.

Use normal converge/operate mode when the control plane is writable and the selected change is safe to apply. Use backlog-only only when the deferral reason is explicit and the receipt can be handed to a later maintenance run.
