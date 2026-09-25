# Mapper-to-Canvas compatibility fixtures v1

This contract is an offline, producer/consumer check. Each fixture is a small
repository source tree. The harness copies it to a temporary clone, invokes the
real mapper CLI, validates the versioned visualization bundle, and imports that
same JSON with a minimal Canvas consumer that reads `nodes` and `edges` directly.

The committed goldens are normalized only for timestamps and clone-local Git
metadata. They are not hand-authored payloads. Run:

```bash
python scripts/mapper_canvas_compat.py check
python scripts/mapper_canvas_compat.py update --reason "explain the semantic change"
```

`check` covers layered web, monorepo, CLI, event-driven, polyglot, and
intentionally incomplete/unresolved projects. It also checks schema IDs,
stable IDs, source evidence, redaction, deterministic output, flow and graph
integrity, compatibility matrix, and performance guardrails. Updating a golden
requires an explicit reason and must be reviewed as a semantic contract change.

The harness is offline: it has no network, Canvas service, browser, or external
consumer dependency. The consumer simulation is deliberately zero-transform so
the committed bundle is the interchange artifact.
