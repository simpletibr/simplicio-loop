# Issue #302 validation evidence

The Dev CLI now separates a non-authorizing `ChangeProposal` from a
short-lived `EffectAuthorization` issued by a coordinator. The Runtime sink
rebuilds the proposal from the effect and dispatch context and rejects the
submission before persistence or transport when authorization is missing,
expired, tampered, bound to another effect, or issued by an LLM/model. Write,
delete, commit and gated effects require a human-gate receipt reference.

Validation from the repository root:

```text
python3 -m pytest -q tests/python/test_effect_authorization.py tests/python/test_runtime_effect_sink.py tests/python/test_atomic_execution.py tests/python/test_pipeline_integrated_mode.py
81 passed in 3.12s
python3 -m compileall -q simplicio tests/python/test_effect_authorization.py
git diff --check
```

The public pipeline accepts `authorization=` and carries it into the typed
dispatch context. No GitHub Actions workflow or external CI result is used.
The installed Loop/Runtime cross-repository receipt matrix remains a separate
deployment verification because this repository does not own those deployed
processes.
