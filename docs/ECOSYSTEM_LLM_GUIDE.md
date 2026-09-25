# Simplicio Ecosystem — LLM orientation guide (canonical)

**Audience:** Claude, Codex, Cursor, VS Code, Gemini, Grok, Kiro, OpenCode, Orca (opt-in), Hermes, OpenClaw, Aider, Antigravity, and any coding agent.

**Read this first** every session when working on Simplicio product delivery. The single agent-instruction file (`AGENTS.md`, plus adapter READMEs) points here for the full map.

---

## 1. What each project is

| Project | Role (one line) | Install surface | Works alone? |
|---------|-----------------|-----------------|--------------|
| **simplicio-runtime** | Execution kernel: gates, leases, effects, MCP, **owns the loop subsystem**, **owns execution metrics report**, decides when to activate loop | binary `simplicio` | N/A (is the kernel) |
| **simplicio-loop** | Protocol + host hooks + Prism/journal/anchor for convergence under Runtime authority | `pip install simplicio-loop` + skills/hooks | Operators yes; full loop prefers Runtime |
| **simplicio-mapper** | Read-only repo observer / map / handoff | `simplicio-mapper` CLI | **Yes** |
| **simplicio-dev-cli** | Focused plan compiler + deterministic edits | `simplicio-dev-cli` / `simplicio-py` | **Yes** |
| **simplicio-fast** | Snapshots / mmap / PlanDAG / understand·plan·apply hot path | `simplicio-fast` CLI | **Yes** (when installed) |
| **simplicio-agent** | Optional coordinator / desktop / gateways / product apps | package + Desktop Electron | Coordinator only; not mandatory gateway |

**Law (ADR-2026-08-04 + 04b):**

1. **Loop complete lives inside Runtime.** Runtime decides `use_loop` (`simplicio loop decide`).
2. **mapper + dev-cli + fast work alone** without Runtime (survey / plan / edit / Fast).
3. Hosts do **not** start loop as a peer path that bypasses Runtime when Runtime is available.
4. **No mass rebrand scripts** (`rebrand_to_simplicio.py` removed — inventory/guard only).

**Law (ADR-2026-08-05):**

- Every loop/runtime run emits **`simplicio.execution-report/v1`**: per task/issue + consolidated metrics (speed, latency, CPU/RAM when MEASURED, tokens in/out). **Never invent numbers.**

---

## 2. Mental model

```text
  Host LLM (Claude / Cursor / Codex / …)
       │ thinks, plans, selects tools
       ▼
  simplicio-runtime  ◄── owns gates, loop decide, execution-report, MCP
       │ activates loop when use_loop=true
       ▼
  simplicio-loop protocol (journal / anchor / prism / hooks)
       │ uses operators
       ├── simplicio-mapper   (standalone OK)
       ├── simplicio-dev-cli  (standalone OK)
       └── simplicio-fast     (standalone OK)
```

---

## 3. Step-by-step — first-time install (Windows)

### 3.1 Runtime binary (required for product path)

```powershell
# From source (this repo)
cargo build --release
# Install to a PATH location (user-local example)
$bin = "$env:LOCALAPPDATA\Simplicio\bin"
New-Item -ItemType Directory -Force -Path $bin | Out-Null
Copy-Item target\release\simplicio.exe $bin\simplicio.exe -Force
# Add to user PATH if missing
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$bin*") {
  [Environment]::SetEnvironmentVariable("Path", "$userPath;$bin", "User")
  $env:Path = "$env:Path;$bin"
}
simplicio --version
```

Or use a published release asset `simplicio-windows-x86_64.exe` renamed to `simplicio.exe`.

### 3.2 Operators + loop package

```powershell
pip install -U simplicio-loop simplicio-mapper simplicio-dev-cli
# Fast when available:
pip install -U simplicio-fast
```

### 3.3 MCP + host rules (when Runtime is present)

```powershell
simplicio mcp register
python -m simplicio_loop.scripts.host_rule_sync --global --json  # if scripts exposed
# or from loop checkout:
python scripts/host_rule_sync.py --global --json
python scripts/mcp_force_sync.py --global --json
```

Restart the IDE/agent so MCP tools appear (`simplicio_map`, `gate`, `edit`, `run`, …).

### 3.4 Prove 100% operational (smoke)

```powershell
simplicio --version
simplicio loop policy --json
simplicio loop decide --task "status smoke" --json --repo .
simplicio execution-report show --json --repo .
simplicio contracts smoke --json
simplicio-loop preflight --strict --json
simplicio-mapper --help
simplicio-dev-cli --help
```

Expected:

- `loop policy` → `owner: simplicio-runtime`, `host_may_start_loop_directly: false`
- `execution-report` present after decide (or after `execution-report start`)
- preflight green or explicit degraded labels (never silent fake OK)

---

## 4. Step-by-step — every non-trivial task

1. **Orient:** `simplicio runtime map --repo . --for-llm markdown` then `simplicio memory "<task>"` (or MCP equivalents).
2. **Decide loop:** `simplicio loop decide --task "<task>" --json --repo .`
3. **Report shell:** opened automatically by decide; or `simplicio execution-report start --json`.
4. **Survey:** `simplicio-mapper` (scan/inspect/handoff) — not ad-hoc full-tree LLM walks.
5. **Hot path:** `simplicio-fast` when operational.
6. **Mutate under STRICT:** `simplicio-dev-cli` / Fast apply / Runtime `edit` — not host Write as primary.
7. **Record metrics per task/issue:**
   ```text
   simplicio execution-report record-task --task-id t1 --issue 42 --title "…" --outcome COMPLETE --wall-ms N --tokens-in N --tokens-out N --operator mapper --operator dev-cli --json
   ```
8. **Validate:** `simplicio validate "<task>" --repo . --json` + project tests.
9. **Finish report:** `simplicio execution-report finish --status COMPLETE --json`
10. **Evidence-gated exit:** MEASURED only with receipts; no theater closes.

---

## 5. Commands cheat sheet

| Intent | Command |
|--------|---------|
| Loop ownership law | `simplicio loop policy --json` |
| Activate? | `simplicio loop decide --task "…" --json` |
| Last loop decision | `simplicio loop status --json` |
| Start metrics report | `simplicio execution-report start --json` |
| Per-task metrics | `simplicio execution-report record-task …` |
| Consolidated | `simplicio execution-report consolidate --json` |
| Loop e2e receipt | `simplicio loop-execution --json` |
| Anchor live read | `simplicio loop-contract --live --json` |
| Spine | `simplicio run "…" --repo . --json` |
| MCP | `simplicio serve --mcp --stdio` / `simplicio mcp register` |

Operator-standalone report (no Runtime binary):

```text
python -m simplicio_loop.execution_report start --json
python -m simplicio_loop.execution_report record-task --task-id t1 --title "…" --json
```

---

## 6. Host notes (all hosts)

| Host | How loop ticks | Hand-edit |
|------|----------------|-----------|
| Claude Code | Stop + PreToolUse hooks | `action_gate` under STRICT |
| Cursor | stop + afterAgentResponse | hooks + rules |
| Codex / Grok / VS Code / Kiro / Hermes / OpenCode | self-paced | STRICT env + this guide |
| Orca | **opt-in only** (`CLIENT_INTEGRATIONS`) | same |
| Gemini / Aider / Antigravity | self-paced / conventions file | STRICT |

Self-paced: re-read `.simplicio/orchestrator/loop/scratchpad.md` each turn; honor Runtime decision receipt.

---

## 7. Related ADRs

- Runtime: `docs/ADR-2026-08-04-RUNTIME-OWNED-LOOP.md`
- Runtime: `docs/ADR-2026-08-04b-LOOP-INSIDE-RUNTIME-OPERATORS-STANDALONE.md`
- Runtime: `docs/ADR-2026-08-05-EXECUTION-METRICS-REPORT-STANDARD.md`
- Loop: `docs/adr/0009-loop-inside-runtime-operators-standalone.md`
- Loop: `docs/adr/0010-execution-metrics-report-standard.md`

---

## 8. Honesty

- Facts are `MEASURED|` only with receipts; else `UNVERIFIED|`.
- Missing Runtime → report degraded; do not invent `open=0` or full product completion.
- Tokens/CPU/RAM: never fabricate; use `null` + `unavailable_reasons`.
