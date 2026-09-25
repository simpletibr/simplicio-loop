#!/usr/bin/env bash
# simplicio-userpromptsubmit — fires on every Claude Code UserPromptSubmit event.
#
# Reads the user prompt from CLAUDE_USER_PROMPT and pipes it to `simplicio-py
# detect`. If the heuristic decides it is a code-edit task, a PROMPT_HINT is
# printed to stderr nudging the agent to invoke the simplicio-cli skill. Always
# exits 0 — never blocks.
#
# Installed by `simplicio-py init`. Safe to delete to disable.
set -u

# Recursion guard: when simplicio-py shells out to `claude -p` / `codex exec`
# (provider mode `claude-cli/<model>` or `codex-cli/<model>`), it injects
# SIMPLICIO_HOOK_GUARD=1 into the subprocess so this hook does not re-fire
# inside the inner CLI session and recurse indefinitely.
if [ -n "${SIMPLICIO_HOOK_GUARD:-}" ]; then
  exit 0
fi

prompt="${CLAUDE_USER_PROMPT:-}"
if [ -z "$prompt" ]; then
  exit 0
fi

if ! command -v simplicio-py >/dev/null 2>&1; then
  exit 0
fi

printf '%s' "$prompt" | simplicio-py detect 2>&1 1>/dev/null || true
exit 0
