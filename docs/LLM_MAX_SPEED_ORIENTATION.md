# LLM max-speed orientation (canonical — simplicio-loop)

**Audience:** every host LLM (Claude, Codex, Cursor, Grok, VS Code, Gemini, Hermes, …).  
**Status:** normative operator law for autonomous delivery.  
**Paired:** `simplicio-runtime/docs/LLM_MAX_SPEED_ORIENTATION.md` (Runtime half).  
**Loaded every re-feed:** `plugin/skills/simplicio-loop/SKILL.md` block  
`<!-- SIMPLICIO-LLM-ORIENTATION -->` (extracted by `hooks/loop_stop.py`).

---

## One-line law

> **Act > narrate. Mapper + Fast + dev-cli on the hot path. Runtime owns loop activation. Prism waves with lease isolation. Smallest gate that proves the AC. MEASURED only.**

**Worker preflight:** read `AGENTS.md`, then every relevant local skill before operating. Use the single read-only binary/artifact set built from the canonical default branch. Never rebuild binaries or regenerate canonical Mapper/Fast artifacts in a worker; worktrees isolate source edits and receipts only. Receipts must carry repo/revision, binary digest/version, Mapper generation, and artifact digest. Missing, stale, or mismatched central artifacts are fail-closed and trigger central rebuild only.


---

## Speed contract (always)

| Rule | Do | Don't |
|------|----|--------|
| Control plane | `simplicio loop decide --json` first; honor `loop-decision.json` | Start `/simplicio-loop` bypassing Runtime when Runtime is up |
| Tokens | mapper handoff / Runtime MCP / Fast snapshot | Full-tree LLM Read/Grep walks |
| Mutate | `simplicio-dev-cli` / `simplicio edit --plan` under STRICT | Host Write/Edit as primary path |
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
# or: source ~/.simplicio/economy-parallel-env.sh
```

Core flags (CPU-bounded; never invent higher than `economy status` recommended):

| Env | Intent |
|-----|--------|
| `SIMPLICIO_LOOP=1` + `STRICT=1` | enforceable operator floor |
| `SIMPLICIO_LOOP_REQUIRE_RUNTIME=auto` | Runtime preferred, not hard-required |
| `SIMPLICIO_EXECUTION_PROFILE=auto` | `runtime-backed` when Runtime up |
| `SIMPLICIO_FAST_MODE=required` | Fast native when operational |
| `SIMPLICIO_LOOP_AUTO_FAN_OUT=1` | parallel worktrees on batch |
| `SIMPLICIO_PRISM_SLOTS` | machine-sized (`recommend_prism_slots`) |
| `SIMPLICIO_PRISM_BATCH_SIZE` | issues per wave (default/min 10; explicit larger OK; logical unbounded) |
| `SIMPLICIO_LOOP_OPERATOR_WORKERS` | ≈ logical CPU count |
| `SIMPLICIO_ASYNC_IO_MAX_CONCURRENCY` | Python asyncio I/O fabric |
| `SIMPLICIO_MCP_FORCE=1` | MCP-first **when** Runtime present |

Opt out: `SIMPLICIO_ECONOMY_PARALLEL=0`.

---

## Parallelism layers (do not confuse)

| Layer | Owner | Role |
|-------|--------|------|
| Runtime Tokio fabric | `simplicio-runtime` | agents, gate, evidence, backpressure |
| Prism slots | loop + `arm_drain_prism` | admission, lease, wave barrier |
| Batch size | `SIMPLICIO_PRISM_BATCH_SIZE` | items per wave (e.g. 30) |
| Operator workers | loop | mapper/fast/dev-cli fan-out |
| Asyncio | loop supervisor | I/O concurrency |
| Writes | governor | **serialized** by path (correct, not slow-by-bug) |

**Logical agents ≠ physical workers.** Requesting 64 logical agents is fine; the governor admits what CPU/RAM allow. Physical Prism width uses machine auto (`--slots 0`); do not thrash the box.

Prism routing (Loop): **1–3 tasks → direct parallelism**; **>3 → Prism**. Default/min batch 10 when quantity omitted; explicit larger batch OK. Wave barrier `reconcile-before-next`.

---

## Hot path (order fixed)

1. `simplicio loop decide --task "…" --repo . --json`
2. `simplicio-loop economy apply --json` (if not aligned)
3. `simplicio-loop preflight --strict --json`
4. `simplicio-mapper scan/inspect/handoff` (not ad-hoc tree walks)
5. `simplicio-fast understand|plan|apply` when operational
6. Mutate: `simplicio-dev-cli task` / Runtime `edit --plan`
7. Smallest gate proving AC
8. Drain waves: `python3 scripts/arm_drain_prism.py --repo . --slots 0 --batch-size N --json`
9. Claim → implement → PR `Closes #N` → merge → **reconcile** → next wave
10. `simplicio.execution-report/v1` (never invent metrics)

---

## Drain waves (max throughput)

```bash
python3 scripts/arm_drain_prism.py --repo . --slots 0 --batch-size 30 --max-iterations 200 --json
```

Per wave:

1. Live re-query open issues (never invent `open=0`).
2. Admit ≤ `batch-size` **independent** issues (prefer non-overlapping paths).
3. Lease + isolated worktree per issue.
4. Hot path (mapper → Fast → dev-cli) per issue.
5. **Reconcile** leases/results before the next wave.
6. Wave receipt: `attempted / merged / blocked / open_left`.

Per-issue worker micro-prompt:

```text
Issue #N only. Runtime+STRICT. Mapper→Fast→dev-cli.
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
`.simplicio/orchestrator/loop/scratchpad.md` each turn and obey this doc + host-rules  
`packaging/host-rules/simplicio-loop-operator-flow.md`.

Pasteable **FAST CLOSE** header for a session:

```text
[RUNTIME-OWNED · PRISM · FAST CLOSE]
economy apply + preflight --strict
loop decide first; honor use_loop
Mapper→Fast→dev-cli; no hand-edit
Prism --slots 0 --batch-size <N>; reconcile each wave
REVIEW=0 metadata; FULL_CI=0 unless AC requires
End: DONE | NEXT | BLOCKED
```

---

## Related

- ADR 0009 — loop inside Runtime; operators standalone  
- ADR 0010 — execution-report metrics  
- `docs/PRISM_EXECUTION.md`, `docs/fast-fanout.md`  
- `simplicio_loop/economy_profile.py`  
- Host rule sync: `python3 scripts/host_rule_sync.py --global`
