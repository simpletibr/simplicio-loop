# OpenCode adapter

OpenCode is a terminal-native agent that reads `AGENTS.md`, supports MCP servers, and has its
own config (`opencode.json`). No stop-hook → self-paced loop.

## Install

```bash
bash scripts/install.sh opencode
```

The installer copies the 7 skills into OpenCode's default-scanned skill locations (a repo-local
`.claude/skills/` the installer writes into `--target`, plus OpenCode's own global
`~/.config/opencode/skills/`) and registers the MCP server in `opencode.json` when a `simplicio`
binary is found on `PATH` (best-effort; the loop never requires it — see "Native bind" below).

## Use

```
opencode run "/simplicio-loop finish all the open issues"
```

## The actual flow: Mapper survey, Dev CLI apply — no Runtime, no MCP required

`simplicio-loop` does not survey or edit with the LLM directly, and does not require Runtime/MCP
to run at all. Every flow starts with a Mapper survey, then the host LLM decides the exact
find/replace edits and hands them to Dev CLI to apply and verify:

```bash
mkdir -p .simplicio-loop
simplicio-loop orient --brief --repo . --task "<task 1>" [--task "<task 2>" ...] --json \
  > .simplicio-loop/brief.json
# write .simplicio-loop/ops.json from the brief's apply.ops_format, then:
simplicio-loop apply .simplicio-loop/ops.json --repo . --json
# PASS: done. BLOCKED/FAIL: fix the named find/check, re-run apply.
```

`apply`/`prepare` refuse to run without that Mapper survey
(`mapper_provenance_missing`, nothing written) — the two REQUIRED operators are
`simplicio-mapper` (survey) and `simplicio-dev-cli` (apply + verify), both installed transitively
via the `simplicio-cli` package. `simplicio-loop` BLOCKS if either binary is absent. See
`.claude/skills/simplicio-loop/SKILL.md` for the full protocol.

## Loop drive — self-paced

Drive ticks headlessly on a schedule:

```bash
*/2 * * * *  cd /repo && opencode run "/simplicio-loop continue the open queue"
```

`simplicio-loop` advances its own state and exits on the evidence-gated promise, the cap, or an
explicit STOP.

## Token economy

`orient_clamp.py` works as-is. Reference it in `AGENTS.md` so heavy commands are clamped.

## Native bind — MCP (optional, never required)

There is no Runtime/MCP backend requirement in this stack: `simplicio-loop` runs standalone on
its two required operators (`simplicio-mapper`, `simplicio-dev-cli`). The `simplicio-runtime`
native bind (the `simplicio` CLI / MCP server, package `simplicio-runtime`) is an OPTIONAL
acceleration on OpenCode, exactly as on every other adapter — when it is installed and reachable
it supplies native integrations; when it is unavailable the loop records that those integrations
were skipped and continues normally with its required Mapper/Dev CLI operators. Add this to
`opencode.json` only if you have installed `simplicio-runtime` and want the native bind:

```json
{ "mcp": { "simplicio": { "type": "local", "command": ["simplicio", "serve", "--mcp", "--stdio"] } } }
```

## MCP config

- **Config file:** `opencode.json` (or `opencode.jsonc`) at the repo root, under the **`mcp`**
  key — OpenCode's schema uses `type: "local"` + a `command` array, not `command`/`args` split
  like most other hosts.
- **Snippet:**

```json
{
  "mcp": {
    "simplicio": {
      "type": "local",
      "command": ["simplicio", "serve", "--mcp", "--stdio"],
      "environment": {}
    }
  }
}
```

  (OpenCode inherits the working directory it was launched from; run `opencode` from the target
  repo, or set `environment`/`cwd` per your OpenCode version's config reference.)
- **Verify:** `opencode mcp list` if your version ships that subcommand, or inspect
  `opencode.json` directly. Tier: **best-effort** — OpenCode is Tier 2 (provider-agnostic MCP
  support is documented upstream but not mechanically gated here).

## Skills: where OpenCode looks

OpenCode scans a repo's `.claude/skills/` by default (in addition to its own native
`.opencode/skills/`), confirmed by inspecting the installed `opencode` binary
(`OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` is the documented opt-out, meaning the scan is on by
default). `scripts/install.sh opencode` writes the skills into `.claude/skills/` in the install
target and into OpenCode's own global `~/.config/opencode/skills/`; either location alone is
enough for OpenCode to discover `simplicio-loop` and invoke it via `/simplicio-loop`.

## Progresso do run

Self-paced (N2): the tick echoes the turn-header. Universal fallback (N3, works with any config):
`watch -n5 cat .simplicio-loop/orchestrator/loop/PROGRESS.md`.
