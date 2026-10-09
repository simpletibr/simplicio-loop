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

## 3.1. Login, update, install and doctor

```bash
simplicio-loop login            # sign in; the login is shared with the Simplicio Runtime
simplicio-loop auth status      # who is logged in (it never prints a token)
simplicio-loop logout --yes     # delete the login file (the Runtime reads it too)
simplicio-loop update --dry-run # show what the update would do; change nothing
simplicio-loop update           # install the latest release
simplicio-loop doctor           # login, update, distribution, Runtime, PATH operators, disk
```

Every flag and every exit code is in [`docs/CLI_COMMANDS.md`](docs/CLI_COMMANDS.md).

Simplicio Loop and the Simplicio Runtime use one login. Both programs read and write the file
`~/.simplicio/login.json`. If both are installed, you sign in one time.
`simplicio-loop login` runs the Runtime sign-in and then reads the file.
Without the Runtime, a standalone sign-in is UNVERIFIED. The command then prints how to install the Runtime.
Before a token refresh, Loop takes a lock on `login.lock` next to the file and reads the file again.
This prevents two programs from refreshing the same rotating token.
Loop refuses a login file that group or others can read, a symlink, and a folder that group or others can write.
If another program creates `~/.simplicio` with mode 0775 (for example under `umask 002`), Loop refuses it and prints the exact command, for example `chmod 700 /home/you/.simplicio`.

`simplicio-loop update` acts by how you installed Loop. A pip install receives the release wheel.
A git checkout must use `git pull` and `bash scripts/dev_install.sh`.
A binary downloads the release file for your system and `SHA256SUMS`, compares the SHA256 before it changes anything,
and keeps the old file as `<name>.bak`. The release file is named
`simplicio-loop-v<version>-<os>-<arch>` (`.exe` on Windows). `simplicio-loop doctor` shows how you installed Loop.

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
