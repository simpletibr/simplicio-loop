# Simplicio capture engine

A native, **stdlib-only**, transparent token-capture proxy and deterministic
compression engine — no third-party dependencies, no network beyond the upstream you
point it at.

The engine sits **in the HTTP path** as an OpenAI/Anthropic-compatible proxy. It
measures prompt tokens, applies safe deterministic compression to message content,
forwards the request to the real provider **without changing the model**, streams
the response straight back, and records savings to `~/.simplicio/proxy_savings.json`.
It is **fail-open**: if anything goes wrong parsing or compressing a request, the
original bytes are forwarded unchanged.

## Quick start

```bash
# 1. start the proxy (default port 8788)
python3 engine/simplicio_engine.py proxy --port 8788 --upstream https://api.openai.com
# …or via the unified launcher:
bin/simplicio-cli proxy --port 8788 --upstream https://api.openai.com

# 2. point a client at it (the proxy forwards the client's own API key)
export OPENAI_BASE_URL="http://127.0.0.1:8788/v1"
export OPENAI_API_BASE="http://127.0.0.1:8788/v1"
# for Anthropic-format clients:
export ANTHROPIC_BASE_URL="http://127.0.0.1:8788"

# 3. view savings
python3 engine/simplicio_report.py            # text report
python3 engine/simplicio_engine.py doctor     # one-line status
```

The `simplicio-cli wrap` command does step 2 for you — it injects those env vars and
execs the client (see the commands table).

## Two entry points

| Launcher | Reaches | Notes |
|---|---|---|
| `bin/simplicio-cli` → `simplicio_cli.py` | `proxy`, `doctor`, `memory`, `mcp`, `init`, `wrap`, `report`, `verify`, `audit`, `capture`, `evals`, `compress`, `version`, `help` | unified CLI; `compress` reads stdin |
| `python3 engine/simplicio_engine.py` | same set (minus the inline `compress`/`version`/`help`) | full subcommand set; hands off to sibling modules |

All engine subcommands are routed by `bin/simplicio-cli` (the dispatcher forwards anything in
`ENGINE_CMDS` to the engine via process replacement).

## Commands

| Command | What it does | Example |
|---|---|---|
| `proxy` | Run the transparent capture proxy in the HTTP path. | `simplicio_engine.py proxy --port 8788 --upstream https://api.openai.com` |
| `doctor` | Show proxy reachability + lifetime savings in one line. | `simplicio_engine.py doctor --port 8788` |
| `memory` | `stats` → engine history count; `remember`/`recall`/`forget`/`list` → CCR key-value store. | `simplicio_engine.py memory remember key "value"` |
| `mcp` | Run the native stdio MCP server (`simplicio_compress` / `simplicio_retrieve` / `simplicio_stats` tools). | `simplicio_engine.py mcp` |
| `init` | Register the Simplicio MCP server into a client config. **Dry-run by default**; `--apply` writes. | `simplicio_engine.py init claude --apply` |
| `wrap` | Launch a client with its LLM traffic routed through the local proxy (injects base-URL env, execs the binary). | `simplicio_engine.py wrap codex --require-proxy -- chat` |
| `report` | Savings report from the ledger: lifetime + session + per-model/provider breakdown. | `simplicio_report.py --since 120 --top 5` |
| `verify` | Self-check the whole token-economy stack (8 checks → PASS/WARN/FAIL table). | `simplicio-cli verify --json` |
| `audit` | Scan files/dirs and rank how many tokens compression would save. | `simplicio-cli audit ./logs --top 10` |
| `capture` | Dry-run: show what a request payload would compress/save, without sending it. | `simplicio-cli capture --file body.json` |
| `evals` | Compression eval + regression gate (corpus → %saved, asserts no corruption). | `simplicio-cli evals --json` |
| `compress` | Read stdin, print deterministically compressed text to stdout. | `cat noisy.log \| simplicio-cli compress` |

Module-level helpers that back these commands:

| Module | Role |
|---|---|
| `simplicio_cli.py` | Unified `simplicio` dispatcher (process-replacement to the engine). |
| `simplicio_engine.py` | Proxy + savings store + subcommand dispatcher. |
| `simplicio_compress.py` | Base deterministic compression (8 algos, `ALGOS`). |
| `simplicio_compress_extra.py` | Extra deterministic passes (4 algos, `EXTRA_ALGOS`). |
| `simplicio_memory.py` | CCR (compress-cache-retrieve) key-value store. |
| `simplicio_tools_server.py` | Native JSON-RPC 2.0 stdio MCP server. |
| `simplicio_init.py` | Client-config writer (codex/claude/copilot/openclaw). |
| `simplicio_wrap.py` | Capture-routing launcher for a client. |
| `simplicio_report.py` | Savings report (per model/provider, `--since`/`--top`/`--json`). |
| `simplicio_verify.py` | One-command stack self-check (proxy/monitor/savings/engine/compress/memory/mcp/operator). |
| `simplicio_tokens.py` | Calibrated stdlib token estimator (used by the proxy + capture). |
| `simplicio_audit.py` | `audit` — per-file compression-savings opportunity. |
| `simplicio_capture.py` | `capture` — dry-run request compression analyzer (never sends). |
| `simplicio_evals.py` | `evals` — compression eval + regression gate. |
| `simplicio_report.py` | Savings reporting over the ledger. |
| `simplicio_verify.py` | Stack self-check. |
| `simplicio_tokens.py` | Stdlib BPE-ish token estimator (`count_tokens`, `count_payload`). |

## How capture works

```
client ──HTTP──▶ simplicio-cli proxy ──HTTP──▶ real provider ──▶ proxy ──stream──▶ client
                      │
                      └── records → ~/.simplicio/proxy_savings.json (schema v3)
```

- **In the HTTP path.** The proxy parses the request body, measures input tokens
  (`~4 chars/token`), compresses `system` + `messages` content, and forwards.
- **Per-provider routing, no model swap.** It reads the request's `model` and routes
  to that family's real host (gpt/o1/o3/o4 → OpenAI, claude → Anthropic, deepseek,
  grok → x.ai, mistral/mixtral, gemini → Google). Unknown models fall back to
  `--upstream`. The model is never changed; each client forwards its own API key, so
  auth stays per-provider. Disable routing with `--no-route`.
- **Only rewrites when it saves.** The compressed body is sent only if it is strictly
  smaller; otherwise the original bytes go through unchanged.
- **Fail-open.** Any parse/compress error → original body forwarded. An upstream
  failure returns a `502` JSON error instead of crashing the proxy.
- **Savings store (schema v3).** Atomic, thread-safe writes to
  `proxy_savings.json` with `lifetime`, `display_session` (resets after 60 min idle),
  and a capped `history` (5000 entries). Costs are **estimated** from a rough
  `$/1M input tokens` table per family, not billed amounts.
- **Health/stats endpoints.** `GET /health` → `{"engine":"simplicio",...}`;
  `GET /stats` → lifetime totals. `--no-optimize` runs pure passthrough.

## Compression

Meaning-preserving, **idempotent**, shrink-only (each algo is applied only if it
strictly reduces length; otherwise the text is returned byte-for-byte unchanged).
Operates at the whitespace / blank-line / dedup / JSON-minify level — intra-line
spacing inside code lines is never touched.

**Base algorithms** (`simplicio_compress.ALGOS`):

| Algo | Effect |
|---|---|
| `strip_ansi` | Remove ANSI terminal escape sequences (CSI/SGR, OSC). |
| `trailing_ws` | Strip trailing whitespace per line (preserves EOL style). |
| `rule_runs` | Collapse runs of 10+ identical rule chars (`=-_*#.~`) to 8. |
| `hex_dump_fold` | Fold 32+ consecutive hex byte-pairs to `[N bytes hex elided]`. |
| `fenced_log_fold` | Collapse 5+ lines sharing a timestamp/`[tag]` prefix to one + marker. |
| `dedup_lines` | Collapse runs of identical consecutive non-empty lines to one + marker. |
| `collapse_blanks` | 3+ consecutive blank lines → 2. |
| `minify_json` | If the whole text is a standalone JSON object/array, minify it. |

**Extra algorithms** (`simplicio_compress_extra.EXTRA_ALGOS`):

| Algo | Effect |
|---|---|
| `markdown_table_ws` | Trim padding spaces adjacent to `|` in markdown table rows (cell text untouched). |
| `repeated_block_fold` | Collapse an identical 3+-line block repeated consecutively to one copy + marker. |
| `long_token_elide` | Replace a single unbroken token >200 chars (base64/data-URI/minified JS) with a marker. |
| `numbered_noise_fold` | Fold 8+ lines identical except for an incrementing number/timestamp. |

The proxy uses the base + extra modules when present, falling back to a small inline
pipeline otherwise.

**Honest scope.** This is **deterministic compression only**. It does **not** do any
ONNX/semantic compression or any RAG. It removes machine-shaped noise
(whitespace, dedup, ANSI, hex dumps, log spam, oversized blobs) — it does not rewrite
or summarize meaning.

> The `memory remember/recall` store (`simplicio_memory.py`) is separate: it uses
> lossless zlib+base64 compression for a byte-exact round-trip, tracking
> `bytes_saved` per entry.

## Data files

All under `~/.simplicio` by default; override the root with the **`SIMPLICIO_HOME`**
env var.

| Path | Contents |
|---|---|
| `~/.simplicio/proxy_savings.json` | Savings ledger (schema v3): `lifetime`, `display_session`, `history`. |
| `~/.simplicio/memory.json` | CCR key-value store (zlib+base64 values + per-entry savings). |
| `~/.simplicio/logs/proxy.log` | Proxy `START` / `PERF` / `UPSTREAM_ERROR` log lines. |

Relevant env vars: `SIMPLICIO_HOME`, `SIMPLICIO_PROXY_PORT` (default `8788`),
`SIMPLICIO_UPSTREAM`, `SIMPLICIO_MONITOR_PORT` (default `9090`, used by `verify`),
`SIMPLICIO_WRAP_BIN` (override the client binary `wrap` execs).
