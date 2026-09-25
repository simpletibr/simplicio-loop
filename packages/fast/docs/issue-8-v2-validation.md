# Issue #8 V2 validation

Fast is the single coordinator boundary. `integrations.py` owns Mapper and Dev
CLI discovery and invocation; callers consume Fast schemas and never invoke
those tools directly.

## Compatibility matrix

| Component | Minimum contract | Readiness rule |
| --- | --- | --- |
| `simplicio-mapper` | `>=0.24.2` | package metadata, executable and version all present |
| `simplicio-cli` | `>=0.16.3` | package metadata, executable and version all present |
| Fast | `2.0.0` | snapshot integrity plus both rows above |

`simplicio-fast doctor` emits `integrated_ready: true` only when every row is
compatible. Missing or incompatible integrations fail closed and leave the
explicit bootstrap fallback available in the ingest/apply receipt.

## Shadow, canary and rollback

`src/simplicio_fast/rollout.py` provides the small coordination contract used
by Loop/Runtime adapters:

```text
shadow -> canary -> integrated
                 \-> rollback
fallback --------> rollback
```

`simplicio-fast rollout shadow|canary|integrated|fallback|rollback` writes an
atomic `simplicio.fast.rollout-receipt/v1`. Every receipt records the mode,
generation, previous mode and reason. Rollback is explicit and produces a
`rolled-back` status; it never masquerades as an integrated success.

## Reproducible gates

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests benchmarks
PYTHONPATH=src python -m simplicio_fast.cli --help
PYTHONPATH=src python -m simplicio_fast.cli rollout shadow --generation SFAST001:1
python benchmarks/run.py
```

Benchmark values are environment observations only. The raw receipt must
record repetitions, wall time, CPU time, peak RSS and incremental visibility;
unavailable measurements remain `null` with a reason.
