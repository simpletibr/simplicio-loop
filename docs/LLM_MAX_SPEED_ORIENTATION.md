# LLM max-speed orientation (canonical — simplicio-loop)

**Audience:** every host LLM (Claude, Codex, Cursor, Grok, VS Code, Gemini, Hermes, …).
**Status:** normative operator law for autonomous delivery.
**Loaded every re-feed:** `plugin/skills/simplicio-loop/SKILL.md` block
`<!-- SIMPLICIO-LLM-ORIENTATION -->` (extracted by `hooks/loop_stop.py`).

---

## One-line law

> **Act > narrate. There is no Runtime/MCP backend in this stack — Mapper +
> simplicio-dev-cli on the hot path, direct under `/simplicio-loop`. Smallest gate that
> proves the AC. MEASURED only.**

**Worker preflight:** read `AGENTS.md`, then every relevant local skill before operating. Use the single read-only binary/artifact set built from the canonical default branch. Never rebuild binaries or regenerate canonical Mapper artifacts in a worker; worktrees isolate source edits and receipts only. Receipts must carry repo/revision, binary digest/version, Mapper generation, and artifact digest. Missing, stale, or mismatched central artifacts are fail-closed and trigger central rebuild only.

---

## Speed contract (always)

| Rule | Do | Don't |
|------|----|--------|
| Control plane | `/simplicio-loop` starts the loop directly | Wait on a Runtime/MCP activation decision — none exists |
| Tokens | mapper handoff | Full-tree LLM Read/Grep walks |
| Mutate | `simplicio-loop "<task>"`, then its printed `apply` once with your plan as the heredoc body (Mapper survey, your plan, dev-cli apply): exactly two commands | Host Write/Edit on source files, exploring, running the tests yourself |
| Parallel | 1–3 tasks direct; >3 Prism + worktrees + leases + reducer | 64 processes on one dirty tree |
| Gates | focused test / doctor / `git diff --check` | Full-repo fmt/test for residual noise |
| Review | 0–1 self-check on small diffs | 3-reviewer panels per metadata PR |
| Claims | `MEASURED\|` / `UNVERIFIED\|` | Invent open=0, timings, savings |
| Exit | real AC + PR/`Closes #N` when required | Theater stubs / false promise |

**Cadence every message:** end with exactly one of
`DONE | NEXT(<one step>) | BLOCKED(<code>)`.

---

## Economy-parallel env (apply once per session)

```bash
simplicio-loop economy apply --json
# or: source ~/.simplicio-loop/economy-parallel-env.sh
```

Core flags (CPU-bounded; never invent higher than `economy status` recommended):

| Env | Intent |
|-----|--------|
| `SIMPLICIO_LOOP=1` + `STRICT=1` | enforceable operator floor |
| `SIMPLICIO_EXECUTION_PROFILE=standalone` | the only execution profile — no Runtime/MCP backend |
| `SIMPLICIO_LOOP_AUTO_FAN_OUT=1` | parallel worktrees on batch |
| `SIMPLICIO_PRISM_SLOTS` | machine-sized (`recommend_prism_slots`) |
| `SIMPLICIO_PRISM_BATCH_SIZE` | issues per wave (default/min 10; explicit larger OK; logical unbounded) |
| `SIMPLICIO_LOOP_OPERATOR_WORKERS` | ≈ logical CPU count |
| `SIMPLICIO_ASYNC_IO_MAX_CONCURRENCY` | Python asyncio I/O fabric |

Opt out: `SIMPLICIO_ECONOMY_PARALLEL=0`.

---

## Parallelism layers (do not confuse)

| Layer | Owner | Role |
|-------|--------|------|
| Prism slots | loop + `arm_drain_prism` | admission, lease, wave barrier |
| Batch size | `SIMPLICIO_PRISM_BATCH_SIZE` | items per wave (e.g. 30) |
| Operator workers | loop | mapper/dev-cli fan-out |
| Asyncio | loop supervisor | I/O concurrency |
| Writes | governor | **serialized** by path (correct, not slow-by-bug) |

**Logical agents ≠ physical workers.** Requesting 64 logical agents is fine; the governor admits what CPU/RAM allow. Physical Prism width uses machine auto (`--slots 0`); do not thrash the box.

Prism routing (Loop): **1–3 tasks → direct parallelism**; **>3 → Prism**. Default/min batch 10 when quantity omitted; explicit larger batch OK. Wave barrier `reconcile-before-next`.

---

## Hot path (order fixed)

1. `simplicio-loop economy apply --json` (if not aligned)
2. `simplicio-loop preflight --strict --json`
3. `simplicio-loop "<task>" [--verify "<tests>"]`, short for
   `simplicio-loop turbo --repo . --task "<task>" [--task "<task 2>" ...] --verify "<tests>"`.
   Mapper reads the repo once and the command prints a `needs_plan` request (task, map slice, the current
   text of the files it names, the plan format, the exact `apply` command). No provider and no API key.
   Name every file to change in the task text. Do not run `simplicio-mapper scan`/`inspect`/`handoff`
   yourself.
4. You are the model: run the request's `apply` command once, your JSON plan as its heredoc body
   (`simplicio-loop turbo --repo . --apply - --verify "<tests>" <<'PLAN'`, then
   `{"operations":[{"path","find","replace"}]}` with each `find` copied from the printed text and unique in
   the file, then `PLAN`); `simplicio-dev-cli` applies it and runs `--verify`. That is all: exactly two
   commands. Never hand-edit source, explore, list or read files, or run the tests yourself. Read its JSON
   (`status`, `applied`, `failed`, `verify`). Done = `status: "ok"` and `verify.passed: true`. On `failed`,
   fix the plan once from the reported reason and excerpt and run the same `apply` command again.
5. Smallest gate proving AC.
6. Drain waves: `python3 scripts/arm_drain_prism.py --repo . --slots 0 --batch-size N --json`
7. Claim → implement → PR `Closes #N` → merge → **reconcile** → next wave
8. `simplicio.execution-report/v1` (never invent metrics)

---

## Drain waves (max throughput)

```bash
python3 scripts/arm_drain_prism.py --repo . --slots 0 --batch-size 30 --max-iterations 200 --json
```

Per wave:

1. Live re-query open issues (never invent `open=0`).
2. Admit ≤ `batch-size` **independent** issues (prefer non-overlapping paths).
3. Lease + isolated worktree per issue.
4. Hot path per issue: the two `simplicio-loop turbo` commands (see above).
5. **Reconcile** leases/results before the next wave.
6. Wave receipt: `attempted / merged / blocked / open_left`.

Per-issue worker micro-prompt:

```text
Issue #N only. STRICT. `simplicio-loop turbo` (request, then apply with your plan as the heredoc).
Lease + worktree only. No hand-edit. Smallest gate for AC.
Done = evidence (+ PR Closes #N when required). BLOCKED = one reason code.
```

---

## Forbidden thrash (measured failure modes)

- Full-repo `cargo fmt` / `cargo test --all-targets` for unrelated residual
- Three adversarial reviewers on a 6-file version bump
- Reinstall operators every turn (TTL pin only)
- Issue-audit waves while mid-delivery of one ship
- Polling subagents for minutes without a decision
- Spawning N full host agents on the same dirty tree

---

## Codex / self-paced hosts

Self-paced hosts (Codex, Grok, VS Code, …) re-read
`.simplicio-loop/orchestrator/loop/scratchpad.md` each turn and obey this doc + host-rules
`packaging/host-rules/simplicio-loop-operator-flow.md`.

Pasteable **FAST CLOSE** header for a session:

```text
[STANDALONE · PRISM · FAST CLOSE]
economy apply + preflight --strict
simplicio-loop "…" --verify "<tests>", then its apply once with the plan as the heredoc (no API key)
Mapper→dev-cli through turbo; no hand-edit of source
Prism --slots 0 --batch-size <N>; reconcile each wave
REVIEW=0 metadata; FULL_CI=0 unless AC requires
End: DONE | NEXT | BLOCKED
```

---

## Related

- ADR 0009 — loop plus operators standalone
- ADR 0010 — execution-report metrics
- `docs/PRISM_EXECUTION.md`
- `simplicio_loop/economy_profile.py`
- Host rule sync: `python3 scripts/host_rule_sync.py --global`
