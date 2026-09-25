# Codex → Runtime integration

The integration has two guarded entry points:

- a PATH shim for one-shot `codex exec "..."` calls;
- a `UserPromptSubmit` hook for interactive Codex sessions.

For a developer task, both invoke `simplicio run <prompt> --repo <cwd>
--evidence --json`. A successful Runtime route returns a blocking hook result
only after a valid JSON evidence receipt is present, so Codex is not started a
second time. A Runtime failure, invalid receipt, or classifier error is
fail-closed and is never converted into a successful Codex run.

Codex policy inputs are passed unchanged as Runtime metadata (`--sandbox`,
`--ask-for-approval`, and the explicit bypass flag). The integration rejects
the explicit bypass flag, never adds an approval or sandbox bypass, and always
sets `SIMPLICIO_HOOK_GUARD=1` for nested provider calls.

Install the wrapper and the marked Codex hook together. The wrapper directory
must precede the real Codex binary in `PATH`; the installer does not rewrite a
shell profile or overwrite an existing foreign executable:

```text
simplicio-codex-wrapper --install-codex ~/.codex --wrapper-path ~/.local/bin/codex
```

The installer preserves foreign hooks and writes a `.simplicio.bak` copy when
it changes an existing `hooks.json`. Remove only the marked integration:

```text
simplicio-codex-wrapper --uninstall-codex ~/.codex --wrapper-path ~/.local/bin/codex
```

The legacy explicit operations remain available:

```text
simplicio-codex-wrapper --install PATH
simplicio-codex-wrapper --uninstall PATH
```

The wrapper refuses to overwrite or remove non-Simplicio files. Runtime,
approval, receipt, and rollback decisions remain owned by the Runtime/Loop
coordinator.
