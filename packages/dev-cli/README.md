# simplicio-cli (`simplicio-dev-cli`)

Deterministic task-to-code contract and verification CLI. It never executes or
provisions an LLM: the agent decides the change, and this CLI applies and
verifies it.

## Commands

- `simplicio-dev-cli edit --root <repo> --plan <edit-plan.json> --apply --json`:
  applies a `{"operations": [{"path", "find", "replace"}]}` plan (each `find`
  must match exactly once), then runs a bounded, scoped verification and prints
  one JSON receipt with `mutation_receipt.verification.status`.
- `simplicio-dev-cli test` runs the project's verifier.
- `simplicio-dev-cli capabilities` lists what this install supports.

Part of the `simplicio-loop` monorepo (`packages/dev-cli`). Install for
development with `bash scripts/dev_install.sh` from the repository root.

## What the model sees

The model writes the edit plan and reads back one JSON receipt: files changed,
the plan digest, and the verification result with a short stdout/stderr tail.
It never sees the CLI's internal compile or diff stages.

### Token effect

A change is paid once as the plan, a few find/replace pairs, instead of whole
rewritten files. The receipt keeps only a bounded output tail.

### KV cache effect

The receipt is printed with sorted keys and holds no model-visible prompt text.
Appending it at the end of the conversation leaves the earlier cached prefix
untouched.
