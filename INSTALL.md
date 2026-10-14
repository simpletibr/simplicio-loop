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

Global scope: `install --global` also refreshes the `simplicio-*` skills of every host that already has the loop skill
(11 hosts, for example `~/.codex/skills/simplicio-*` and `~/.grok/skills/simplicio-*`) and the Loop-owned global rule files
a host already has. It creates none of them on a clean HOME. Those files are outside the ownership receipt, so they stay after
`install --uninstall`. Remove them by hand if you want them gone.

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
simplicio-loop doctor           # login, update, distribution, Runtime, PATH operators, disk, setup
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

## 3.2. Setup (after install)

`simplicio-loop install` ends with `simplicio-loop setup`. You can run it again at any time. The second run says `unchanged`.

```bash
simplicio-loop setup            # look at the machine, find your agent CLIs, find your GitHub login
simplicio-loop setup --check    # change nothing. Exit 0: nothing pending. Exit 10: something is pending
simplicio-loop setup --dry-run  # show what setup would install
simplicio-loop setup --yes      # also install git and bwrap with your system package manager
```

| Step | What setup does |
| --- | --- |
| Tools | Looks for Python 3.11 or newer, pip, venv, git, gh, bwrap (Linux) and uv. |
| Install | Downloads `gh` and `uv` from their official releases to `~/.local/bin`. It compares the SHA256 first and never replaces a file. Python comes from `uv python install`. |
| PATH | Shows each PATH entry that is relative, writable by others, or owned by a user other than root or you. It also shows an entry under a folder that anyone can rewrite, and `~/.local/bin`. Setup does not search these entries. It runs nothing from them, not even `gh` or `git` for the GitHub login. The one exception is a `gh` or `uv` file that setup installed. Setup records its SHA256 in `setup.json` and runs only that exact file while the SHA256 matches. An agent CLI that sits only in such an entry shows as ignored. Example: `claude` in `~/.local/bin`, where the native Claude Code installer puts it. Setup prints the file and a command that moves it to a safe folder. |
| System packages | Installs git and bwrap only with `--yes`, and only as root or when `sudo -n` works. Otherwise it prints the exact command. |
| Agent CLIs | Looks for `claude`, `codex`, `grok`, `kimi`, `opencode`, `agy`, `copilot` and the other hosts of the Runtime. It shows version, login and watcher support, and it picks a default host. |
| GitHub | Uses `GH_TOKEN`, then your logged-in `gh`, then the git credential helper, then a stored token. If none works, it asks for a token with hidden input. `--github-token-stdin` reads the token from a pipe. The token goes only to `api.github.com`. |
| Summary | Writes `~/.simplicio-loop/setup.json` (mode 600, no token). `doctor` and the 24/7 watcher read it. |

Without a terminal, setup never waits for input. It prints what to run. Windows and macOS: UNVERIFIED.

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
