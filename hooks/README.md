# Hooks — simplicio-tasks super-plugin

Cross-platform (pure **Python 3**, so identical on Windows / macOS / Linux). Most are
**fail-open**: a hook that errors or is unsure always lets the agent stop and the command
run unchanged — it can never trap you in a loop or break a command. The real guards are the
`max_iterations` cap, explicit STOP, and evidence gates, not hook cleverness. The **exception is
`action_gate.py`, which is fail-CLOSED**: a matched irreversible op or a secret in the staged
diff is denied (exit 2) even if that means stopping a push — a safety check that can't pass is
not a pass. It still lets every benign command through, so it never bricks normal work.

| File | Role | Event |
|---|---|---|
| `loop_stop.py` | simplicio-loop: re-feed the goal or exit (evidence-gated promise + cap + STOP) | `stop` / Claude `Stop` |
| `loop_capture.py` | simplicio-loop: raise the `done` flag when an evidence-backed `<promise>` is seen | Cursor `afterAgentResponse` |
| `action_gate.py` | safety: **fail-closed** — block irreversible ops + secret-laden commits/pushes BEFORE they run; `pre-push` also requires a green local gate: `SIMPLICIO_PREPUSH_GATE`, else `scripts/check.py --core-gate` when the project ships it, else it blocks (#291, #1410) | `PreToolUse` (Bash) / git pre-push / pre-commit |
| `user_prompt_submit.py` | host adapter: pass the prompt through the packaged Claude adapter; if the adapter cannot be imported it degrades explicitly (warning on stderr, exit 0, no traceback) | Claude `UserPromptSubmit` |
| `orient_clamp.py` | simplicio-orient: **wrapper** — run a command, return reduced output + tee-on-failure | called directly, any runtime |
| `orient_rewrite.py` | simplicio-orient: auto-route heavy read-only commands through the clamp (opt-in) | `PreToolUse` |
| `_dashboard_emit.py` | telemetry: fail-open bridge the three hooks above use to append `simplicio.dashboard-event/v1` events to the active run (#1398); not a hook itself | imported by `loop_stop.py`, `action_gate.py`, `user_prompt_submit.py` |
| `pre-commit.py` | packaging, simplicio-loop source repo only: auto-sync its mirrors when a watched path is staged (#98); does nothing in a project that lacks the sync scripts | git pre-commit |

## Mirror auto-sync (`pre-commit.py`, #98)

Only the simplicio-loop source repository keeps mirrored copies that need regenerating. In any other
project `pre-commit.py` finds no sync scripts and lets the commit proceed (fail-open); you can leave
it unwired.

## The safety gate (`action_gate.py`)

Enforces `simplicio-tasks` Step 5 mechanically instead of trusting the model to remember it.
Wire it as a Claude `PreToolUse` Bash hook (the installer does this) AND a git pre-push hook
(the installer does this too, project-local only):

```bash
# git pre-push: secret-scan the REAL push range (HEAD vs. upstream, not the staged diff) AND
# run the project's local gate. Name it with SIMPLICIO_PREPUSH_GATE (any shell command, run from
# the project root). A project that ships scripts/check.py uses `scripts/check.py --core-gate`
# when the variable is unset. With neither, the push is BLOCKED and says why (#1410): a gate
# that was skipped is not a pass.
export SIMPLICIO_PREPUSH_GATE='pytest -q'
printf '#!/bin/sh\npython3 hooks/action_gate.py pre-push\n' > .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

It blocks (exit 2): force-push / history rewrite (`filter-branch`), remote-ref deletion,
mass-delete (`rm -rf /`), destructive DDL (`DROP DATABASE`), infra teardown (`terraform destroy`),
any commit/push whose diff contains a secret (AWS/GitHub/Slack/OpenAI keys, private keys,
hardcoded credentials — placeholder-aware), and — for `pre-push` specifically — a failing or
missing local gate. When the frozen task anchor carries a delivery contract but the
`simplicio_loop` package is not importable, the contract cannot be enforced: `action_gate.py`
blocks the commit/push and `loop_stop.py` refuses to end the turn, instead of silently passing.
There is no bypass flag: fix the gate, don't skip it. `python3 hooks/action_gate.py
selftest` proves the ruleset. `action_gate.py check --staged` (the pre-commit-flavored,
secret-scan-only mode) remains available for a lighter pre-commit wiring.

One shape is read as data: the JSON plan a host pipes to `simplicio-loop turbo --repo R --apply - <<'PLAN'`. The
gate reads the whole Bash command, so without this a plan that merely contains a destructive statement (a
migration, a runbook) would be blocked for what it says. `strip_plan_heredoc` drops that heredoc body before
classifying, and only when the first line is one plain `simplicio-loop turbo ... --apply -` command (no unquoted
operator, so no other command can read the heredoc), the delimiter is quoted (the shell expands nothing in the
body), it is the last line and no earlier line equals it. Any other command, and every other reader of a heredoc,
is classified in full.

## The always-works one (no wiring needed)

`orient_clamp.py` is a plain wrapper — use it anywhere, any runtime, no hooks:

```bash
python3 hooks/orient_clamp.py -- go test ./...          # reduced output, tee log on failure
python3 hooks/orient_clamp.py --json -- git diff      # machine summary
```

Config (optional) `.simplicio-loop/orchestrator/orient.toml`:

```toml
[tee]   mode = "failures"   # failures | always | never
[hooks] exclude_commands = ["curl", "wget", "playwright", "ssh", "vim", "less"]
```

## Wiring per runtime

### Cursor
`hooks/hooks.json` is already in Cursor's format — the plugin loads it automatically. It wires
the loop (`afterAgentResponse` + `stop`) and the learn trigger.

### Claude Code
Claude uses `settings.json` (project `.claude/settings.json` or user `~/.claude/settings.json`).
Add (paths relative to the repo root, or absolute):

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [
        { "type": "command", "command": "python3 ./hooks/loop_stop.py" }
      ] }
    ],
    "PreToolUse": [
      { "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "python3 ./hooks/action_gate.py" },
          { "type": "command", "command": "python3 ./hooks/orient_rewrite.py" }
        ] }
    ],
    "UserPromptSubmit": [
      { "hooks": [
        { "type": "command", "command": "python3 ./hooks/user_prompt_submit.py" }
      ] }
    ]
  }
}
```

`orient_rewrite` is opt-in (the `PreToolUse` block). Omit it to keep clamping manual via
`orient_clamp.py`. Claude has no `afterAgentResponse`; `loop_stop.py` folds capture in by
reading the transcript, so `loop_capture.py` isn't needed there.

### Other runtimes (Codex, Gemini, Aider, OpenCode, Kiro, Antigravity, Simplicio Agent, OpenClaw)
Most don't expose a stop hook. Use the **no-hook fallback**: the `simplicio-loop` skill
self-paces via the host scheduler (`/loop`, OS cron, or the runtime's task scheduler), and
`orient_clamp.py` is invoked directly. The per-runtime entries live in the simplicio-loop source repository.

## Safety

- Fail-open for errors in the hooks themselves: stop allowed / command unchanged. The exceptions
  are the fail-closed `action_gate.py` and an unenforceable delivery contract (see above).
- `orient_rewrite.py` never rewrites writes, excluded, or compound commands (`&& | ; > $()`).
- The loop never exits on a self-reported "done" — only on an evidence-backed `<promise>`,
  the `max_iterations` cap, spindle handoff, or an explicit `.simplicio-loop/orchestrator/STOP`.
- Treat `.simplicio-loop/orchestrator/orient.toml` as untrusted perception-shaping config: review + hash-pin
  before trusting it (see `simplicio-orient`).
