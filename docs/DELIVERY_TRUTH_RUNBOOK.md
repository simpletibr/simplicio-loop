# Delivery-truth verification runbook (#290 Fase 8)

Operator guidance for when the delivery-truth pipeline (`simplicio_loop/source_state.py`,
`simplicio_loop/external_verifiers.py`, `simplicio_loop/merge_executor.py`,
`simplicio_loop/github_lifecycle.py`, `simplicio_loop/delivery.py`) reports `FAIL` or
`UNVERIFIED` instead of a clean `PASS`. The pipeline is fail-closed by design (see
`docs/delivery-target-receipts.md` and `docs/verified-agent-delivery.md`): a stuck or
unverified gate is expected, correct behavior under real-world provider flakiness, permission
gaps, or genuine negative facts — **never** treat a stuck gate as a bug to route around with a
manual override, and never hand-edit a receipt file to make a gate pass.

## How to triage

1. Run `python3 scripts/loop_progress.py status --json` (or the CLI surface wired for the
   run) to see the current target, the last evidence-set hash, and which gate is blocking.
2. Find the `reason_code` on the blocking gate. The table below groups the stable reason codes
   this pipeline emits (see `simplicio_loop/external_verifiers.py`,
   `simplicio_loop/source_state.py`, `simplicio_loop/github_lifecycle.py`,
   `simplicio_loop/merge_executor.py`, `simplicio_loop/delivery.py`) by root cause and gives the
   concrete recovery action.
3. Recovery is always **re-query, never assume**: fix the underlying condition (permission,
   network, stale ref) and let the pipeline observe the provider again. Do not fabricate a
   passing receipt.

## Reason-code catalog and recovery actions

### GitHub unavailable / rate limited / transient network fault

| reason_code | Meaning | Recovery |
|---|---|---|
| `default_branch_query_failed`, `compare_query_failed`, `review_threads_query_failed`, `deployment_release_query_failed`, `release_download_failed` | The live GitHub call itself failed (network, 5xx, rate limit, timeout). | Re-run the same command. `simplicio_loop.external_verifiers.retry_transient` already retries transient codes with backoff — if it is still failing after the configured attempts, check `gh api rate_limit` and GitHub's status page, then retry once the condition clears. Never treat a transient failure as a negative verdict. |
| `pagination_incomplete` | A paginated GraphQL query (e.g. review threads) never reached `hasNextPage=false`. | Re-run the query; if it recurs, check for an expired token or reduced GraphQL rate-limit budget (`gh api graphql` cost). |

### Insufficient permission / scope

| reason_code | Meaning | Recovery |
|---|---|---|
| Any `*_query_failed` code whose underlying `gh`/API error is `403`/`insufficient scope` | The credential used lacks the scope needed to read reviews, checks, releases, or deployments. | Rotate to a token/App installation with the required scope (see `docs/SECURITY_CREDENTIALS.md` if present, or the queue's credential-issuance policy from #289). Do not weaken the gate to tolerate missing scope — fix the credential. |

### Stale / identity-mismatched evidence

| reason_code | Meaning | Recovery |
|---|---|---|
| `source_fingerprint_mismatch`, `delivery_target_mismatch`, `deployment_commit_mismatch`, `delivery_state_invalid` | A receipt refers to a different SHA/tree/target than the one currently in play (e.g. a new push landed after the receipt was produced). | This is a correct rejection, not a bug. Re-run the full verification chain against the *current* head/tag; do not reuse the stale receipt. |
| `merge_reachability_unverified`, `deployment_reachability_unverified` | The commit could not be proven reachable from the real default branch at query time. | Confirm the default branch is what you expect (`gh repo view --json defaultBranchRef`); if the branch legitimately advanced mid-query, re-run — the verifier already retries once for a moving target, but a second real divergence (force-push, rebase) requires re-establishing the expected SHA before re-querying. |
| `quality_matrix_commit_unbound`, `quality_matrix_commit_mismatch`, `merge_queue_commit_mismatch` | (#290) `merge-ready`+ requires the `#283` quality-matrix receipt and the delivery/`#288` evidence to point at the *same* commit (`oracle.py::_commit_binding_gate`) — a green receipt for the wrong SHA must not satisfy the gate. `_unbound` means the quality-matrix receipt never declared `work_item.head_sha` at all. | Re-run `scripts/quality_matrix.py build\|populate --work-item-head-sha <current head sha>` against the actual commit under test, then re-evaluate. Never hand-edit the sha to make the gate pass. |

### Genuine negative facts (do not retry blindly — inspect first)

| reason_code | Meaning | Recovery |
|---|---|---|
| `approvals_missing`, `issue_state_mismatch` | The required review/issue state genuinely is not what the target needs (e.g. no valid approval after the last push, or the issue is not in the expected state). | Get the actual approval / fix the actual issue state on the provider. There is nothing to "recover" mechanically — this is real project state. |
| `checksum_mismatch`, `checksum_manifest_absent`, `release_checksum_missing` | Downloaded release bytes do not match the published manifest, or no manifest exists. | Investigate whether the release process is broken (missing checksum step) or the asset was tampered with/corrupted in transit. Re-publish the release artifact with a correct manifest; never bypass the checksum check. |
| `release_signature_missing`, `sbom_asset_absent`, `release_sbom_missing` | No attestation/signature or SBOM asset was found on the release. | See the frozen policy decision in `docs/adr/0003-attestation-and-sbom-policy.md` — this repo's release process is expected to attach a `sbom_generate.py`-produced SBOM and a `provenance_generate.py`-produced local provenance statement. If either is missing, the release step that should attach them did not run; fix the release process, do not waive the gate. |
| `install_smoke_failed`, `install_failed`, `import_smoke_failed`, `venv_create_failed`, `install_smoke_error` | The downloaded artifact genuinely could not be installed/imported into a clean environment. | This usually means a real packaging defect (missing entry point, broken dependency pin, wrong Python floor). Fix the package; re-run the smoke against a fresh release, never mark it passed by hand. |
| `deployment_smoke_failed`, `deployment_artifact_unverified`, `deployment_environment_missing` | The deployment target's install-from-verified-bytes check failed, or no environment was named. | Confirm `environment` was passed and that the same release verified above is what the deployment step installed. See the scope note in `docs/adr/0003-attestation-and-sbom-policy.md` regarding what "deployed" means for this repo (an installable package, not a running service with health/canary semantics). |
| `deployment_unqueried`, `install_smoke_unqueried` | The pipeline never asked for this gate at all (by default, out of caution, it does not run byte-level/deployment verification unless the target state or an explicit flag requests it). | This is not a failure — it means nobody requested the `deployed`/`released` target yet. Pass `target_state=` or the explicit `verify_*=True` flag (see `_should_verify_deployment` / `_should_verify_release_artifacts` in `simplicio_loop/source_state.py`) if you actually need that proof. |
| `commit_sha_missing`, `default_branch_mismatch`, `transition_invalid`, `delivery_schema_invalid`, `delivery_source_incomplete` | A structural/identity precondition for the transition is not met (missing SHA, mismatched branch, invalid schema). | Inspect the receipt/observation that failed validation; this is `simplicio_loop/delivery.py`'s fail-closed schema/identity check working as intended. Re-run the upstream step that should have populated the missing field. |

### Crash / interruption mid-transition

Symptom: a run was interrupted (process killed, host restarted, network cut) while a merge,
release, deploy, or issue-close effect was in flight. `tests/test_delivery_concurrency_fault_injection.py`
proves this class of failure end-to-end (see `test_crash_between_intent_and_effect_recovers_without_duplicating_the_effect`,
`test_crash_during_merge_command_network_call_produces_no_false_positive_receipt`, and
`test_crash_during_deployment_verifier_network_call_produces_no_false_positive_payload`).

Recovery is always the same shape:

1. Do **not** assume the interrupted effect succeeded or failed — the client's own exit code
   proves nothing about what GitHub actually did with an in-flight request.
2. Re-claim the work item (a new `AttemptCoordinator.claim()` picks up the expired lease with a
   higher fencing token; the dead attempt's idempotency key is never replayed).
3. Re-query the provider fresh (`MergeExecutor.reconcile()`, a fresh `github_delivery_payload()`
   call, or the relevant verifier) to determine the actual remote state.
4. If the effect already landed remotely (e.g. GitHub processed the merge before the client
   died), the fresh re-query observes `merged=True` and the run proceeds without re-running the
   effect. If it did not land, the fresh re-query observes the pre-effect state and the run
   retries the effect under the new attempt's idempotency key.
5. Every prior attempt's events remain in its own append-only `events.jsonl` under
   `.simplicio-loop/orchestrator/runs/<run_id>/<work_item_id>/<attempt_id>/` — inspect them to reconstruct
   exactly where the crash happened, but never mutate them.

### Regression after a terminal state

Symptom: a run previously reached `merge-ready`/`merged`/`released`/`deployed`, and a later
observation shows the underlying provider state moved backward (new review thread opened, a
release/tag was deleted, a deployment was rolled back).

Recovery: this is by design (see the "No monotonic fantasy" invariant in issue #290) — the
projection must regress, completion must be invalidated, and the run must reopen with the
precise reason code from the table above. Do not force the run back to `COMPLETE`; address the
regression at its source (resolve the new thread, re-publish the release, redeploy) and let the
pipeline observe the fix live.

## Status surface: where each field of a blocked gate actually lives

Issue #290 asks that "CLI/status" show origin, trust level, age, identity, gates, and reason for
every `FAIL`/`UNVERIFIED`, without exposing secrets. There is no single new dashboard command for
this; the fields are all present today, split across the existing JSON surfaces rather than
merged into one view:

- **origin / identity**: `delivery-receipt.json`'s `source_kind`, `source_payload.source_query`
  (`provider`, `repo`, `pr`/`tag`, `mode: "live"|"fixture"`), and `source_fingerprint`.
- **trust level**: `source_query.mode` (`"live"` vs `"fixture"`) at the top of every payload, plus
  the explicit `trust_level: "test-fixture"` marker on the reviews-fixture override
  (`source_state.py`) — no other trust level is ever forged as `"provider-live"`, since a real
  query has no need to self-attest what it already proves by having actually run.
- **age**: `source_checked_at` (receipt) and each verifier's `expires_at`/TTL class
  (`freshness.py`).
- **gates / reason**: every gate in `delivery-receipt.json["gates"]`,
  `quality-matrix.json`'s `evaluate_quality_matrix` output, and `completion-receipt.json["gates"]`
  carries `{name, status, reason_code, detail}` uniformly.
- **secrets**: never present in any of the above — `github_lifecycle.py::_redact` sanitizes before
  anything is persisted or printed.

`python3 scripts/loop_progress.py status --json`, `simplicio_loop/cli.py sync-source`, and
`scripts/completion_oracle.py` each print one or more of these JSON documents directly; an
operator or script composing all three gets the full picture the AC asks for. Building one
additional command that merely re-prints the union of these existing fields was judged not worth
the added surface for this round — flagged here rather than silently dropped.

## Where to look for more detail

- `docs/delivery-target-receipts.md` — receipt schema and target → gate → receipt mapping.
- `docs/verified-agent-delivery.md` — end-to-end verified-delivery narrative.
- `docs/adr/0003-attestation-and-sbom-policy.md` — frozen attestation/SBOM policy decision.
- `docs/INDEPENDENT_WATCHER.md` — independent re-verification of implementer claims.
- `tests/test_delivery_concurrency_fault_injection.py` — the concurrency/crash/fault-injection
  matrix referenced above, runnable locally with `python -m pytest
  tests/test_delivery_concurrency_fault_injection.py -v`.
