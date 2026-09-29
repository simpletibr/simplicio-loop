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

## The actual flow: `simplicio-loop turbo` — no Runtime, no MCP, no API key required

`simplicio-loop` does not survey or edit with the host LLM, and does not require Runtime/MCP to run
at all. Invoking the skill runs ONE command, `simplicio-loop "<task>" --verify "<tests>"`: Mapper surveys the repo
once, the engine calls OpenCode itself for the plan (`opencode run --pure --agent simplicio-planner`, prompt on stdin;
your own provider, credentials and default model, with one planner agent that has no tools merged in through
`OPENCODE_CONFIG`, nothing written to your OpenCode config), Dev CLI applies and verifies it, and the command prints
the result (`mode: "hybrid"`, `llm: "opencode"`). Only when it cannot (no network, an auth or HTTP error, a timeout,
`opencode` missing) does it print a `needs_plan` request (`reason: "hybrid_unavailable: <cause>"`), and the host model
runs the printed `apply` command once with its find/replace plan as the heredoc body:

```bash
simplicio-loop "<task>" --verify "<tests>"      # the whole flow; needs_plan (tasks, map, files, format, rules, apply) only on a fallback
simplicio-loop turbo --repo . --apply - --verify "<tests>" <<'PLAN'
{"operations":[{"path":"<file>","find":"<text copied from files, once>","replace":"<new text>"}]}
PLAN
# status ok + verify.passed: done. failed: fix the plan once from the reason and excerpt, run it again.
```

OpenCode prompts once for the `simplicio-loop` command like for any bash command. An allow rule is optional and broad; see
[docs/HARNESSES.md](../../docs/HARNESSES.md#permissions) before adding one.

No exploring, no listing or reading files, no running the tests yourself (`--verify` does): every extra tool
call re-sends the whole conversation.

The two REQUIRED operators are `simplicio-mapper` (survey) and `simplicio-dev-cli` (apply +
verify), both built into the `simplicio-loop` wheel. `simplicio-loop` BLOCKS if either binary is
absent. See `.claude/skills/simplicio-loop/SKILL.md` for the full protocol.

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
