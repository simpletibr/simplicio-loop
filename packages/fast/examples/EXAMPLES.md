# Simplicio Fast examples

## Build bounded context

```powershell
$env:PYTHONPATH = "src"
python -m simplicio_fast.cli build . -o .simplicio/fast/project.sfast
python -m simplicio_fast.cli context ProjectProcessor --root . `
  -s .simplicio/fast/project.sfast --max-results 2 --max-bytes 4000
```

The JSON response contains a versioned provenance receipt, source commit,
snapshot generation, digest and effective limits.

## Record a canary and rollback

```powershell
simplicio-fast rollout canary --generation SFAST001:42
simplicio-fast rollout rollback --reason "canary acceptance failed"
```

Use the receipt as the handoff to Loop/Runtime. Do not edit `.sfast` files or
use their internal offsets as an external contract.
