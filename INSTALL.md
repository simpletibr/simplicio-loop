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

`<runtime>` ∈ `claude codex vscode cursor antigravity kiro opencode gemini aider simplicio_agent
openclaw orca` (`hermes` still accepted as a legacy alias for `simplicio_agent`). Omit it to
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

- A strong LLM agent runtime (any of the 12 above).
- `python3` on PATH. `git` and, for GitHub sources, an authenticated `gh`.
- That's it. Every extension point has an LLM fallback, so no native runtime is required —
  though `simplicio-runtime`, if present, makes the skill faster and cheaper.
