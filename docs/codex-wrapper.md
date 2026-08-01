# Codex wrapper

`simplicio-codex-wrapper` is an explicit, reversible forwarding shim. It does
not add or remove Codex sandbox, approval-policy, or mutation flags, and it
sets `SIMPLICIO_HOOK_GUARD=1` to prevent recursive hook invocation.

Install at an explicit path:

```text
simplicio-codex-wrapper --install PATH
```

The installer refuses to overwrite a non-Simplicio file. Remove only a shim
created by the installer:

```text
simplicio-codex-wrapper --uninstall PATH
```

The wrapper does not auto-approve mutations or claim Runtime execution. A
Runtime/Loop coordinator remains responsible for authorization and scheduling.
