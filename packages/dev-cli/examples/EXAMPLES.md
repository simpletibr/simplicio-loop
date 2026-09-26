# Simplicio Examples

These examples describe the supported local and Runtime-backed boundaries.

## Standalone changeset

```powershell
python -m simplicio.cli changeset --help
python scripts/issue_422_e2e.py --root . --repeats 10
```

The standalone lane uses the Dev CLI transaction executor and does not require
Runtime. A successful result must include a verified receipt; a failed or
ambiguous effect remains fail-closed.

## Memory and handoff

```powershell
python -m simplicio.cli memory init --dir .\.simplicio-loop\memory --json
python -m simplicio.cli memory store "release process" "Ship through a reviewed PR." --dir .\.simplicio-loop\memory --json
python -m simplicio.cli memory handoff "reviewed PR" --dir .\.simplicio-loop\memory --json
```

Markdown notes remain exportable source material. The derived index is
rebuildable and its search mode is reported honestly.

## Runtime-backed evidence

Set `SIMPLICIO_RUNTIME_EFFECT_URL` and `SIMPLICIO_RUNTIME_E2E_ROOT` only when a
compatible Runtime effect service owns the same isolated repository root. Run
the evidence harness again and retain the raw report. If the endpoint or
capability is absent, the Runtime row stays `AVAILABLE_NOT_E2E`/`UNVERIFIED`.
