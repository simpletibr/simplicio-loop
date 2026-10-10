# Author flow

The author flow is a second executor. Use it for tasks that a JSON plan cannot do, for example a fix to simplicio-loop itself.

The plan flow (`host_mode.run_exec`) asks the model for a plan. Dev CLI applies the plan. The author flow is different. It opens the `claude` CLI with tools. The CLI edits files in a worktree. The loop runs verify on the work and sends each failure back to the same CLI session.

```mermaid
flowchart LR
    A[Author round: claude edits worktree] --> B{Diff empty?}
    B -- yes --> F[Correction in same session]
    B -- no --> C{Protected path changed?}
    C -- yes --> F
    C -- no --> D{Verify passes?}
    D -- no --> F
    D -- yes --> E[Result: ok]
    F --> A
```

## Run it

```bash
git worktree add ../fix-x -b fix-x
simplicio-loop author --repo ../fix-x --task-file task.md --verify "python3 -m pytest tests/test_x.py -q" --rounds 3
```

Use an isolated worktree. The CLI edits files in `--repo`.

The command prints one JSON object: `status`, `rounds`, `session_id`, `changed`, `failures`, `usage`, `reason_code`.

| Exit code | Meaning |
|---|---|
| 0 | `ok` |
| 3 | `failed` |
| 69 | `unsupported` family |
| 2 | usage error |

## Rules for each round

1. Round 1 starts the session with `--session-id`. Each correction uses `--resume` with the same id.
2. Before round 1, the loop takes a snapshot of the worktree files: path, mode and SHA-256 of the content. After each round it takes another snapshot. `changed` is the difference. The loop never asks git. No change fails the round (`empty_diff`).
3. A changed path in `plan_paths.PROTECTED_PATHS` fails the round (`protected_path`). The loop does not run verify on that tree.
4. The loop runs the `--verify` command. A failure fails the round (`verify_failed`). Without `--verify` the reason code is `ok_unverified`.
5. The verify command runs code of the author. After it, the loop takes another snapshot. A protected path that verify wrote fails the round (`protected_path`), even when verify passed.
6. The `changed` field of the result is the first snapshot against the last one. The last one comes after verify, or after a CLI error.
7. These stop the run at once:
   - a CLI error (`cli_error`)
   - an output that is not a JSON object (`bad_envelope`)
   - a CLI that does not start (`cli_unavailable`, `argv_too_long`)
   - a timeout (`timeout`)

   A missing login stops it before the first round (`claude_login_missing`). `--rounds` must be from 1 to 10, in the command and in `run_author`.

## Snapshot limits

- A file over 64 MiB is not hashed. The snapshot records its mode, size, mtime and inode. The author can make a sparse file of any size, and a hash would read all of it. No protected path is that big. A rewrite of a big file with the same size, mtime and inode is not seen.
- The snapshot has a time budget of 120 s. When it runs out, the run stops with `snapshot_timeout`.
- The snapshot includes `__pycache__` and `.pytest_cache`. These entries are not changes, with one exception: a cache file beside a protected module is a protected change (`protected_path`). Python runs an unchecked `.pyc` without reading its `.py` file. The CLI and verify run with `PYTHONDONTWRITEBYTECODE=1`, so they do not make cache files of their own.

## Security model

What the author sees and writes:

- The worktree is the only place it writes. The sandbox (bwrap) makes the rest of the file system read-only. If there is no bwrap, the run stops with `sandbox_unavailable`.
- The CLI gets a private HOME in `~/.cache/simplicio-loop-author/<run>`. It holds only a copy of `~/.claude/.credentials.json` (mode 0600) and an `.owner` file with the pid of the run. The loop deletes it when the run ends, also after an error, a timeout, SIGINT, SIGTERM or SIGHUP. After SIGKILL the next run deletes each private HOME whose pid is gone. The folder `~/.cache/simplicio-loop-author` stays, because another run can use it.
- The real HOME is an empty tmpfs for the CLI and for verify. The CLI cannot see `~/.ssh`, `~/.config/gh` or the settings of your own Claude sessions.
- The verify command does not see the private HOME. The private HOME is not in the worktree, because the sandbox binds the whole worktree for verify.
- `--setting-sources user` reads the private HOME only, never `.claude/settings.json` of the worktree. Before each round the loop deletes settings, hooks, agents, skills and plugins from the private HOME.
- The child environment has no `GH_TOKEN`, no `GITHUB_TOKEN` and no `ANTHROPIC_API_KEY`. The login is the credentials file. An API key is not a login for this flow yet. This is a known limit.
- The tool list cannot change. It has no `git add` and no `git commit`: in the sandbox a commit never ends. Web tools, slash commands and MCP servers are off.
- Text that goes back to the CLI hides secrets and has a fixed size.
- The snapshot covers `.git/config`, `.git/hooks` and a `.git` file. A hook, a config line or a repointed `.git` file fails the round. Other `.git` files change on every `git add` and `git commit`, so the snapshot skips them.

Risks that stay, and that we accept:

- The sandbox keeps the network open. The author code can send data out.
- During a round, the private HOME holds a copy of the Claude login. The CLI needs it. The login is visible, the network is open and `python -m pytest` runs code of the author. Together, these let the author send the login out during a round. We accept this risk. The mitigation is that the repository and the task come from an owner or a member.
- The task text comes from an issue of an owner or a member. The loop does not prove that the text is safe.
- The CLI reads the `CLAUDE.md` of the project. A hostile repository can inject a prompt this way. `claude --safe-mode` exists. It turns off `CLAUDE.md`, hooks, skills and plugins. We evaluated it as an alternative and we do not use it.
- With `--allow-unsandboxed`, none of the file system limits apply. Use it for manual tests only.

## Usage numbers

`usage` holds the token counters that the CLI reports (`input_tokens`, `output_tokens`, `cache_read_tokens`), added over the rounds, and `measured_rounds`. If the CLI reports none, `usage` is `null`. The loop never estimates them.

The flow works with `claude` only. Other families return `unsupported`.
