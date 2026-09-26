<!-- simplicio-contract:begin -->
contract: operator-run/v1
schema: simplicio.contract-doc/v1
purpose: A versioned, **testable** definition of the mandatory operator bridge — the only path through which `simplicio-loop` is allowed to make a production mutation.
rules: The JSON schema next to this file is authoritative; mutable data lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# `simplicio.operator-run/v1`

A versioned, **testable** definition of the mandatory operator bridge — the only path through
which `simplicio-loop` is allowed to make a production mutation. It closes issue #135: the loop
previously only checked `which simplicio-dev-cli`; execution `simplicio-dev-cli task` lived mostly
in the docs and the E2E labeled the EDIT hop `simulated`. This contract makes real execution
**enforced by a receipt**, not by prose.

`scripts/check_operator_run_contract.py` validates every fixture under `fixtures/` against the
**REAL** producers (`simplicio_loop/runner.py`'s `execute_operator` boundary) and asserts the
#135 acceptance criteria directly — it never fakes a pass.

Run `python3 scripts/check_operator_run_contract.py` to validate. It exits non-zero with a
specific failure message on any drift.

## Stability

`v1` is additive-only once published: existing fixtures, `schema.json` required fields, and
`expected.json` keys will not change meaning or be removed in `v1`. A breaking change ships as
`v2` in a sibling directory.

## The bridge in one paragraph

`arm_run` freezes the task-contract, the mapper hands off an `authorized_targets` pack, the
planner freezes a `plan` (steps + candidate_targets + hashes). `execute_operator` then:

1. validates the operator **identity + capability + min-version** (not just `which`);
2. captures a **checkpoint** of the authorized targets *before* any mutation;
3. invokes `simplicio-dev-cli task ... --target <plan target> --bound-paths <plan target>`;
4. redacts + persists stdout/stderr/exit-code;
5. on `returncode != 0` performs an **automatic rollback** to the checkpoint;
6. emits an **immutable operator receipt** (`operator-receipt.json`, schema
   `simplicio.operator-receipt/v0`);
7. the run cannot be concluded while `git diff` names a file with no matching receipt.

Manual edits made outside the bridge are detected (diff without receipt) and **block** conclusion.
A dev-cli failure never unlocks silent manual LLM editing.

## Acceptance criteria covered by this contract

| #135 AC | Enforced by |
|---|---|
| Cada diff de produção coberto por operator receipt | `conclude_run` diff-coverage gate (`_operator_run_diff_coverage`) |
| Runner bloqueia conclusão se `git diff` sem receipt | `_operator_run_diff_coverage` raises on `uncovered_paths` |
| Dev-cli validado por identity/capability/min-version | `_preflight_operator` + `_devcli_min_version` |
| Alteração AC-scoped e aponta para targets do plano | `authorized_targets`/`target` bound to `plan.candidate_targets` |
| Expansão de target volta ao planner/impact gate | target outside `authorized_targets` → `RuntimeError` |
| Até 3 retries preservam fingerprints e mudam estratégia | `dispatch_operator_batch` `retry_budget=3`, `failure_fingerprint` |
| Checkpoint antes da 1ª mutação + rollback automático | `_capture_operator_checkpoint` before subprocess; `_restore_operator_checkpoint` |
| Comando dev-cli + stdout/stderr redigidos + exit code persistidos | receipt `argv`/`stdout`/`stderr`/`returncode` |
| Falha do dev-cli nunca libera edição manual silenciosa | fail-closed `blocked` state; no edit fallback path |
| Operações mecânicas não chamam modelo remoto | `provider_config` empty when `--local`/mechanical |
| `no_change` só com prova de estado já satisfatório | `_no_change_proof` required when `status == no_change` |
| Um run PLANES mostra mapper → plan → dev-cli receipts → diff → tests | `build_evidence_receipt` chain + fixture `planes-e2e` |
| CLI direta e MCP produzem o mesmo schema | both call `execute_operator`; receipts share `OPERATOR_RECEIPT_SCHEMA` |

## Fixtures

| Fixture | What it proves |
|---|---|
| `diff-coverage-gate` | a production diff without a receipt blocks conclusion |
| `no-change-proof` | `no_change` is rejected unless `no_change_proof` is present and the AC is already satisfied |
| `devcli-min-version` | below-min-version / wrong-homonym dev-cli is blocked at preflight |
| `target-expansion` | a target outside `authorized_targets` routes back to planner/impact gate (raises) |
| `retry-preserves-fingerprint` | retries keep the failure fingerprint and change strategy, bounded at 3 |
| `rollback-on-validation-fail` | checkpoint restore fires on non-zero exit |
| `cli-and-mcp-same-schema` | the `execute_operator` receipt shape is identical for CLI and MCP entrypoints |

See each fixture's `expected.json` for the exact assertions the validator runs against the real
`runner` module.
