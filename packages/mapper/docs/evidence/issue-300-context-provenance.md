# simplicio-dev-cli #300 — Mapper provenance evidence

## Scope

`handoff --execution-context` now creates one canonical `ContextSnapshot`,
binds the bounded `ContextPack` to its exact canonical SHA-256 digest, and
reuses that same snapshot while assembling `simplicio.execution-context/v1`.
The full snapshot is a sibling control-plane artifact; it is not embedded in
the LLM projection.

The additive `ContextPack.source_snapshot` object contains:

- `snapshot_id`;
- `revision`;
- canonical `source_digest`;
- `root_hash`.

Generic library callers that do not supply a canonical snapshot continue to
produce a standalone pack without claiming provenance. Integrated Dev CLI
intake therefore remains fail-closed for those packs.

## Verification

Focused unit, integration, and system tests:

```text
python -m unittest \
  tests.python.test_context_pack \
  tests.python.test_task_aware_handoff \
  tests.python.test_execution_context \
  tests.python.test_cli

Ran 117 tests in 6.478s
OK
```

Touched-module coverage:

```text
simplicio_mapper/cli/_status_engine.py    78%
simplicio_mapper/context_pack.py          93%
simplicio_mapper/execution_context.py     95%
TOTAL                                     89%
```

The installed-package interoperability check built
`simplicio_mapper-0.24.2-py3-none-any.whl`, installed it beside the Dev CLI
checkout, passed the emitted snapshot and pack through
`load_mapper_context`, `load_mapper_context_pack`, and
`bind_mapper_context`, and produced a `sha256:` context handle without an
adapter or fabricated provenance.

The execution-context benchmark regression suite also passed:

```text
python -m unittest tests.python.test_execution_context_benchmark

Ran 2 tests in 0.865s
OK
```

## Security and failure behavior

- Canonical hashing uses the existing fail-closed context contract serializer.
- No snapshot content is copied into `ContextPack`.
- The system test verifies all four provenance fields against the emitted
  sibling snapshot.
- Dev CLI rejects absent or mismatched provenance before effect dispatch.
- A diff secret scan found no token, private-key, or credential pattern.

## Remaining external gate

This PR closes the Mapper producer gap recorded by Dev CLI issue #300. A real
installed Loop invocation and a reachable Runtime EffectTransaction endpoint
are still required before the parent issue can claim the complete
Loop → LLM projection → Dev CLI → Runtime receipt E2E. This evidence does not
substitute the local offline Runtime transport for that external gate.
