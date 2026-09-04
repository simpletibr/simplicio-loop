# CLI command reference

`simplicio-cli`, `simplicio-py`, and `simplicio-dev-cli` expose the same command
surface. Every command and subcommand accepts `--help`; use the most specific
form available, for example `simplicio-py memory recall --help`.

## Top-level commands

| Command | Purpose |
|---|---|
| `index` | Build or refresh the repository context cache. |
| `task` | Execute a governed task-to-code edit and verification flow. |
| `proposal` | Compile a non-mutating Runtime change proposal. |
| `run` | Run a task, feature, sprint, or scratch goal. |
| `bench` | Compare real execution with and without the CLI assistance. |
| `cache` | Inspect or clear completion cache (`stats`, `clear`). |
| `smoke` | Check the deterministic-only adapter without contacting an LLM. |
| `init` | Install the Simplicio skill and Claude hook. |
| `detect` | Classify whether text describes a code-edit task. |
| `status` | Show the current local run state. |
| `claims` | Check, tag, or report evidence-backed claims (`check`, `tag`, `report`). |
| `inspect` | Inspect a target with Mapper-backed context. |
| `intake` | Convert raw task text into a provider-free TaskSpec contract. |
| `doctor` | Check dependency freshness and deterministic readiness. |
| `fast` | Inspect optional Fast capabilities (`capabilities`, `doctor`). |
| `versions` | Report installed, declared, and tested ecosystem versions. |
| `release-train` | Verify Mapper release events and N/N-1 evidence (`verify`, `doctor`). |
| `env-export` | Print safe exports from a dotenv file without sourcing it. |
| `mechanical-edit` | Dry-run or apply a mechanical edit plan. |
| `changeset` | Decode and apply a Fast changeset through the edit boundary. |
| `edit` | Apply a governed edit through Runtime or the local fallback. |
| `reconcile` | Reconcile a pending Runtime effect from an evidence file. |
| `file` | Read bounded file contents (`read`). |
| `test` | Run a test command and report its result (`run`). |
| `token` | Run token-efficient execution primitives (log, diff, retry, routing, cache). |
| `score-skill` | Score a skill or law document against deterministic scenarios. |
| `runtime` | Inspect Runtime identity, capabilities, and readiness. |
| `prototype` | Plan, scaffold, validate, diff, promote, or reject a prototype. |
| `memory` | Store, search, validate, back up, and hand off cross-vendor memory. |

The compatibility commands `gate`, `nest`, `scratch`, and `skill new` are
dispatched by their own modules and also expose `--help`.

## Agent-facing operating sequence

1. Run `simplicio-mapper --help`, then `simplicio-mapper scan`/`inspect`/`handoff`.
2. Run `simplicio-dev-cli task --help` and choose the narrowest governed command.
3. Use `simplicio-fast --help` only when the Fast extra is installed and the route is available.
4. Verify with `simplicio-dev-cli test run --help` and the repository's real test command.

The dependency train for this release is Mapper `0.26.27`, Dev CLI `0.18.11`,
and Fast `2.0.22` (Fast is available on Python 3.11+). Keep this file linked
from agent instruction files whenever the command surface changes.
