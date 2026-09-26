# Progressive validation

`simplicio_loop.progressive_validation` implements the issue #815 validation
contract without invoking an LLM or provider.

The controller consumes an impact level and ordered verification commands. It
runs the smallest sufficient prefix of `parse`, `format`, `targeted`, `impact`,
`module`, and `full`. Medium/high/critical risk, delivery, and a prior failure
promote the required ceiling. Critical and delivery policies require `full`.
Any failing lane stops execution, so a failing targeted test can never be
hidden by a later broad suite.

Cache entries are disposable and fail closed. Their key binds the full SHA-256
of source, toolchain, configuration, level, and argv. A same-command entry with
different input hashes is reported as a stale rejection and executed again.
Tampered entries are also rejected.

Each receipt records:

- exact argv, exit status, duration, stdout hash, and stderr hash per lane;
- Python, implementation, and platform versions;
- source, tool, and configuration hashes;
- cache hits and stale rejections;
- separate incremental and final-suite durations;
- `null` plus a reason when the final suite was not required or reached.

## CLI

```bash
python3 scripts/progressive_validation.py \
  --plan verification-plan.json \
  --cache .simplicio-loop/validation-cache.json \
  --receipt .simplicio-loop/validation-receipt.json
```

The plan is a JSON object with complete `source_hash`, `tool_hash`, and
`config_hash` values, `impact_level`, `risk`, `delivery`, `prior_failure`, and
`commands`, where each command contains `level` and an argv array.

## Rollback

Remove the controller, CLI, and its cache. No source mutation or remote effect
is performed by the cache itself. Cached evidence is advisory and may always be
deleted; a cache miss reruns validation.
