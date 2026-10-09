# Install — simplicio-loop

simplicio-loop is a **super-plugin** made of skills (markdown) + cross-platform Python hooks.
There is nothing to compile. One installer copies the 7 skills into your runtime, wires the
loop where supported, and prints the optional native-bind line.

## 1. Get it

```bash
git clone https://github.com/wesleysimplicio/simplicio-loop
cd simplicio-loop
```

## 2. Install for your runtime

```bash
# macOS / Linux
bash scripts/install.sh <runtime> [--global] [--target DIR]
# Windows / pwsh
pwsh scripts/install.ps1 <runtime> [-Global] [-Target DIR]
```

`<runtime>` is the `install.runtime` of a `wired` host in
[`simplicio_loop/_catalog/harnesses.json`](simplicio_loop/_catalog/harnesses.json): `claude codex cursor
vscode grok antigravity kiro opencode gemini aider simplicio_agent openclaw orca github-copilot mimo-code
amp openclaude pi oh-my-pi devin goose auggie autohand charm cline codebuff command-code continue droid
kilocode kimi mistral-vibe qwen rovo-dev` (`hermes` still accepted as a legacy alias for
`simplicio_agent`; DeepSeek is a model provider, see `adapters/deepseek/README.md`). Omit it to
auto-detect from the current directory. `--target DIR` installs into
another project; `--global` installs to the runtime's user-wide location.

The only requirement is **python3** on PATH (the skills, hooks, and installer are all
cross-platform Python). For GitHub sources you also want `git` + an authenticated `gh`.

What the installer does (all reversible — copies + a config edit):
- copies `.claude/skills/simplicio-*` (7 skills) into the runtime's skills location,
- copies `hooks/` so hook paths resolve,
- wires the loop (`Stop`/`stop` hook) where the runtime supports it; else the loop self-paces,
- ensures the runtime's entry file (`AGENTS.md` / `GEMINI.md` / `.github/copilot-instructions.md`
  / `.kiro/steering/…` / `CONVENTIONS.md`) references the protocol — idempotently,
- prints `simplicio-cli mcp register --client <runtime>` for optional native binding.

See [`adapters/MATRIX.md`](adapters/MATRIX.md) and `adapters/<runtime>/README.md` for details.
For the exact per-OS mutation inventory (what mutates on disk, PATH, or a service, and which
effects require an explicit flag), see [`docs/INSTALL_MUTATIONS.md`](docs/INSTALL_MUTATIONS.md).

## 3. Run it

```
/simplicio-loop finish all the open issues
```

(or `codex exec`, `gemini -p`, `aider --message`, etc. — see your runtime's adapter.)

## 3.1. Login, update, and check the install

Sign in to share your login with the optional Simplicio Runtime:

```bash
simplicio-loop login            # Google sign-in; shares the login with simplicio-runtime
simplicio-loop auth status      # check who is logged in
simplicio-loop logout           # sign out (requires --yes)
simplicio-loop doctor           # inspect stack and integration status
simplicio-loop update           # install the latest release (--check: report only)
```

For pip installs, `update` downloads the latest GitHub release and runs the install step.
For source (git) checkouts, use `git pull` then `bash scripts/dev_install.sh`.

## 4. Token economy (no wiring needed)

```bash
python3 hooks/orient_clamp.py -- go test ./...     # reduced output, tee log on failure
```

## 5. (Optional) Before an unattended 24/7 run

Confirm source auth is persistent, keep the irreversible-op human gate + secret-scan on, and make
sure the operator has a reachable STOP/cancel path (`.simplicio-loop/orchestrator/STOP` or the runtime's native
cancel command). The loop stops on its `max_iterations` cap, an evidence-gated `<promise>`,
spindle handoff, or explicit STOP.

## Requirements

- A strong LLM agent runtime (any host in `adapters/MATRIX.md`).
- `python3` on PATH. `git` and, for GitHub sources, an authenticated `gh`.
- That's it. Every extension point has an LLM fallback, so no native runtime is required.
