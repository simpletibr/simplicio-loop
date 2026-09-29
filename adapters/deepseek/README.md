# DeepSeek adapter

DeepSeek is a model provider, not an agent host: there is no DeepSeek executable to install into, so `scripts/install.sh` has no `deepseek` runtime. Install status: **manual**.

## Skill load

DeepSeek's own documentation lists the coding agents it works with: Claude Code, OpenCode and OpenClaw (<https://api-docs.deepseek.com/guides/coding_agents/>). Load the skills through one of them. For Claude Code:

```bash
bash scripts/install.sh claude          # opencode / openclaw for the other two hosts
# then, in the shell that starts the host (never in a committed file):
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_AUTH_TOKEN=<your DeepSeek API key>
# plus the model variables the DeepSeek page lists
```

For everything after that, follow the host's own README: [claude](../claude/README.md), [opencode](../opencode/README.md) or [openclaw](../openclaw/README.md).

## Loop drive

Whatever the host uses: Claude Code has a real `Stop` hook, OpenCode is self-paced and OpenClaw runs the loop on its own scheduler. A self-paced agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`.

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through the host's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. The model that plans is the DeepSeek model behind the host.
