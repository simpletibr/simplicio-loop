# Harnesses: which hosts `simplicio-loop` can call in hybrid mode

`simplicio-loop "<task>"` runs the whole turbo flow behind one command (Mapper survey, fan-out, `simplicio-dev-cli` apply, `--verify`, one repair)
and answers every model call the engine needs through the invoking host's own headless CLI: the same model, account and
configuration, no key of its own, and nothing written to the host's config. Which host is calling, and how to call it, is data: the
`detect` and `llm` fields of each entry of [`simplicio_loop/_catalog/harnesses.json`](../simplicio_loop/_catalog/harnesses.json)
(schema `simplicio.harnesses/v1`). The engine reads that file; there is no second list. See [CLI_COMMANDS.md](CLI_COMMANDS.md#hybrid-mode) for the
fallback causes and the environment.

35 hosts: 7 verified, 13 documented, 15 host-mode.

| status | meaning |
|---|---|
| verified | Run locally on the date shown: its flags were checked with `--help` and one live tool-less call ("Reply with OK") was parsed by the parser named in the entry. |
| documented | The command comes from the host's own documentation (linked). Where the CLI is installed here its flags were checked with `--help`, but no live call was possible (not signed in here) or made. Best effort: a failure is a typed cause and the fallback below applies. |
| host-mode | No headless one-shot model call is known (or it would edit files), so the invocation prints the two-command plan request. |

## Hosts

| id | status | auto-selected | headless command | detection | network, tools, cost | evidence |
|---|---|---|---|---|---|---|
| `claude-code` | verified | yes | `claude -p --output-format json --safe-mode --system-prompt '{system}' --tools '' --no-session-persistence` (prompt on stdin) | env `CLAUDECODE=1`, `CLAUDE_CODE_ENTRYPOINT`; process `claude` (observed) | network: allowed; tools: disabled; fixed prompt about 440 tokens | run 2026-09-29 (claude 2.1.284) |
| `codex` | documented | yes | `codex exec --json --ephemeral --sandbox read-only --skip-git-repo-check -` (prompt on stdin; planner rule prepended to the prompt) | env `CODEX_THREAD_ID`, `CODEX_SESSION_ID`, `CODEX_SANDBOX`; process `codex` | network: blocked-when-sandboxed; no network when `CODEX_SANDBOX_NETWORK_DISABLED=1` is set; tools: read-only | [docs](https://developers.openai.com/codex/noninteractive), flags checked 2026-09-29 (codex-cli 0.155.1) |
| `grok` | documented | no | `grok -p '{prompt}' --output-format json --system-prompt-override '{system}' --max-turns 1 --no-subagents --disable-web-search` (prompt as an argument) | process `grok` | network: allowed; tools: limited-by-max-turns | [docs](https://x.ai/cli), flags checked 2026-09-29 (grok 1.0.41) |
| `cursor` | documented | yes | `cursor-agent -p --mode ask '{prompt}'` (prompt as an argument; planner rule prepended to the prompt) | process `cursor-agent` | network: allowed; tools: read-only | [docs](https://cursor.com/docs/cli/headless) |
| `github-copilot` | documented | no | `copilot -p '{prompt}' --silent --no-ask-user --no-custom-instructions` (prompt as an argument; planner rule prepended to the prompt) | process `copilot` | network: allowed; tools: approval-denied | [docs](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference) |
| `opencode` | verified | yes | `opencode run --pure --agent simplicio-planner --format json --title simplicio-turbo` (prompt on stdin; planner agent merged into the host config) | env `OPENCODE=1`, `OPENCODE_PID`; process `opencode` (observed) | network: allowed; tools: disabled; fixed prompt about 220 tokens | run 2026-09-29 (opencode 1.18.32) |
| `mimo-code` | host-mode | - | none: the two-command host mode | none (not detected: host mode) | No headless one-shot model call was checked for MiMo Code. |  |
| `amp` | host-mode | - | none: the two-command host mode | process `amp` | Amp has an execute mode (`amp -x`), but its documentation pages are client-rendered and were not read; left in host mode. | https://ampcode.com/manual |
| `openclaude` | host-mode | - | none: the two-command host mode | process `openclaude` | OpenClaude is a Claude Code fork with a --print run, but its flags were not checked; left in host mode. | https://github.com/Gitlawb/openclaude |
| `antigravity` | verified | no | `agy --print '{prompt}' --output-format json --disable-slash-commands --print-timeout 120s` (prompt as an argument; planner rule prepended to the prompt) | process `agy` | network: allowed; tools: cannot-be-disabled; fixed prompt about 26,800 tokens | run 2026-09-29 (agy 1.2.9) |
| `pi` | verified | yes | `pi -p --mode json --no-tools --no-session --no-context-files --no-extensions --no-skills --no-prompt-templates --system-prompt '{system}'` (prompt on stdin) | process `pi` | network: allowed; tools: disabled; fixed prompt about 80 tokens | run 2026-09-29 (pi 0.85.1) |
| `oh-my-pi` | verified | yes | `omp -p --mode json --no-tools --no-session --no-extensions --no-skills --no-rules --no-lsp --no-title --system-prompt '{system}'` (prompt on stdin) | process `omp` | network: allowed; tools: disabled; fixed prompt about 280 tokens | run 2026-09-29 (omp 18.2.4) |
| `hermes` | verified | no | `hermes -z '{prompt}' --ignore-rules` (prompt as an argument; planner rule prepended to the prompt) | process `hermes` | network: allowed; tools: cannot-be-disabled; fixed prompt about 12,900 tokens | run 2026-09-29 (hermes 0.21.4) |
| `devin` | host-mode | - | none: the two-command host mode | process `devin` | No headless one-shot model call is documented for Devin. |  |
| `goose` | documented | no | `goose run --no-session -i -` (prompt on stdin; planner rule prepended to the prompt) | process `goose` | network: allowed; tools: unverified | [docs](https://goose-docs.ai/docs/guides/running-tasks) |
| `auggie` | documented | no | `auggie --print --quiet '{prompt}'` (prompt as an argument; planner rule prepended to the prompt) | process `auggie` | network: allowed; tools: unverified | [docs](https://docs.augmentcode.com/cli/reference) |
| `autohand` | host-mode | - | none: the two-command host mode | process `autohand` | No headless one-shot model call was checked for Autohand Code. |  |
| `charm` | host-mode | - | none: the two-command host mode | process `crush` | No non-interactive run command appears in the Crush README; left in host mode. | https://github.com/charmbracelet/crush |
| `cline` | host-mode | - | none: the two-command host mode | process `cline` | Cline CLI has a headless --json mode, but its output schema and approval behaviour were not checked; left in host mode. | https://docs.cline.bot/cline-cli/overview |
| `codebuff` | host-mode | - | none: the two-command host mode | process `codebuff` | Codebuff is driven through its SDK, not a one-shot CLI call. |  |
| `command-code` | host-mode | - | none: the two-command host mode | none (not detected: host mode) | No headless one-shot model call was checked for Command Code. |  |
| `continue` | documented | no | `cn -p '{prompt}' --silent` (prompt as an argument; planner rule prepended to the prompt) | process `cn` | network: allowed; tools: approval-denied | [docs](https://docs.continue.dev/cli/headless-mode) |
| `droid` | documented | yes | `droid exec --output-format json` (prompt on stdin; planner rule prepended to the prompt) | process `droid` | network: allowed; tools: read-only | [docs](https://docs.factory.ai/cli/droid-exec/overview) |
| `kilocode` | host-mode | - | none: the two-command host mode | process `kilo` | `kilo run` exists (an OpenCode fork) but only its --auto autonomous mode is documented, which approves every tool; left in host mode. | https://kilo.ai/docs/cli |
| `kimi` | documented | no | `kimi --quiet -p '{prompt}'` (prompt as an argument; planner rule prepended to the prompt) | process `kimi` | network: allowed; tools: auto-approved | [docs](https://moonshotai.github.io/kimi-cli/en/customization/print-mode.md), flags checked 2026-09-29 (kimi 1.47.0) |
| `kiro` | documented | yes | `kiro-cli chat --no-interactive --trust-tools=read,grep` (prompt on stdin; planner rule prepended to the prompt) | process `kiro-cli` | network: allowed; tools: read-only | [docs](https://kiro.dev/docs/cli/headless/) |
| `mistral-vibe` | documented | no | `vibe --prompt '{prompt}'` (prompt as an argument; planner rule prepended to the prompt) | process `vibe` | network: allowed; tools: edits-auto-approved | [docs](https://github.com/mistralai/mistral-vibe#programmatic-mode) |
| `qwen-code` | documented | yes | `qwen -p '{prompt}' --system-prompt '{system}' --output-format json --exclude-tools shell,write,edit` (prompt as an argument) | process `qwen` | network: allowed; tools: read-only | [docs](https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/headless.md) |
| `rovo-dev` | host-mode | - | none: the two-command host mode | process `acli` | No headless one-shot model call was checked for Rovo Dev. |  |
| `gemini` | documented | no | `gemini -p '{prompt}' --output-format json` (prompt as an argument; planner rule prepended to the prompt) | env `GEMINI_CLI=1`; process `gemini` | network: allowed; tools: approval-denied | [docs](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/headless.md) |
| `vscode` | host-mode | - | none: the two-command host mode | none (not detected: host mode) | An editor, not a CLI: there is no one-shot model call to make. |  |
| `orca-dev` | host-mode | - | none: the two-command host mode | process `orca` | Orca is an agent orchestrator: `orca --help` (1.4.204, checked here) lists worktree, terminal and orchestration commands and no one-shot model call. |  |
| `aider` | host-mode | - | none: the two-command host mode | process `aider` | aider --message applies the model's reply as edits to the files, so it is not a plain planning call. | https://aider.chat/docs/scripting.html |
| `deepseek` | host-mode | - | none: the two-command host mode | none (not detected: host mode) | A model family, not a host executable: nothing to detect and no headless CLI to call. |  |
| `openclaw` | verified | yes | `openclaw infer model run --local --json --prompt '{prompt}'` (prompt as an argument; planner rule prepended to the prompt) | process `openclaw` | network: allowed; tools: disabled | run 2026-09-29 (openclaw 2026.6.1) |

## Why only some hosts are auto-selected

The engine sends the text of repository files to the host CLI, and that text is untrusted. A headless run that keeps its tools and approves
them itself would let a prompt injection in a file run commands with your authority, where the interactive host would have asked. So a host is
chosen on its own only when its command demonstrably has no tools or a read-only mode (`auto-selected: yes`: `--tools ""`, a deny-all agent,
`--no-tools`, `--sandbox read-only`, `--mode ask`, `--trust-tools=read,grep`, `--exclude-tools shell,write,edit`, or an `exec` that is read-only by
default). The others (`auto-selected: no`) print the host-mode request with `reason: "hybrid_unavailable: opt_in"` until you name them with
`SIMPLICIO_TURBO_LLM=<id>`, which you should do only in a repository you trust. A catalog test fails for a new auto-selected entry that has no
tools-off marker.

## Fixed cost you should know

A host CLI sends its own system prompt and tool list with every call, which the planner cannot shrink. Measured on "Reply with OK":

- `opencode`: about 220 tokens over the ~750 of a direct provider call (the planner agent has no tools).
- `claude-code`: about 440 tokens (`--safe-mode`, no tools).
- `hermes`: about **12,900** tokens per call and no flag to shrink it.
- `antigravity` (`agy`): about **26,800** tokens and 11.6 s for one word.

`SIMPLICIO_TURBO_LLM=host` forces the two-command host mode when that cost is not worth it.

## Permissions

The host prompts once for the `simplicio-loop` command, like for any shell command. An allow rule is optional and broad: in OpenCode a
`permission.bash` rule `"simplicio-loop *": "allow"` in `opencode.json`, in Claude Code `Bash(simplicio-loop:*)` in the allow list. Because
`--verify` runs any shell command and the engine starts the host's own CLI, such a rule approves arbitrary commands and a nested model call, not
just this tool. Add it only in repositories you trust. This is advice for you: the skill never asks the model to widen permissions.

The engine's own time budget is `SIMPLICIO_TURBO_BUDGET_S` (default 100 s), under the 120 s that the Claude Code and OpenCode bash tools allow by default.

## Forcing or turning off a host

- `SIMPLICIO_TURBO_LLM=<id or alias>` calls that host even without its markers (a headless script, for example) and skips the network probe.
- `SIMPLICIO_TURBO_LLM=host` never calls a host CLI; `provider` is the OpenRouter provider client (needs `OPENROUTER_API_KEY`); `auto` (default) detects.
- When the host cannot be used the same invocation prints the host-mode request with `reason: "hybrid_unavailable: <cause>"`; the causes are listed in [CLI_COMMANDS.md](CLI_COMMANDS.md#hybrid-mode).
