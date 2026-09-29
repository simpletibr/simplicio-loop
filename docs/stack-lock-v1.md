# `simplicio.stack-lock/v1`

The Loop now has a deterministic stack-lock primitive for issue #1032. Callers
provide observations from installed Mapper and Dev CLI components; the
primitive canonicalizes component order, hashes artifacts when the executable
is a regular file, records capabilities and freezes the route before an effect.

`standalone` is the only route; the `runtime-backed` route was removed in 3.46.0.
`verify_unchanged` rejects artifact,
capability, version, component, run-id, or route drift after freeze.

The installed CLI accepts a JSON observation file and persists the lock
atomically without invoking commands or installing packages:

```text
simplicio-loop stack lock \
  --components components.json \
  --route standalone \
  --run-id run-123 \
  --output .simplicio-loop/orchestrator/stack-lock.json

simplicio-loop stack verify \
  --lock .simplicio-loop/orchestrator/stack-lock.json \
  --components components.json
```

An existing lock is immutable: writing a different hash is blocked. Verification
recomputes the canonical hash and then compares the current artifact, version,
capability and route observations. Contract Registry integration, cross-platform
installed discovery, upgrade/rollback diagnostics and automatic runner wiring
remain residual work for #1032.


## Optional compatibility registry

For a strict, local compatibility check, pass a simplicio.stack-registry/v1
JSON file to stack lock:

~~~text
simplicio-loop stack lock \
  --components components.json \
  --registry stack-registry.json \
  --route standalone \
  --output .simplicio-loop/orchestrator/stack-lock.json
~~~

The registry is evaluated before StackLock.create or any lock write. A
missing component, unsupported version/capability, compatibility mismatch, or
duplicate binary returns BLOCKED with exit code 2 and leaves the output path
untouched. Without --registry, the existing observation-only lock behavior is
preserved. This explicit gate does not replace installed cross-platform,
upgrade/rollback, or cross-repository evidence.
