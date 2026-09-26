# Completion oracle adapter matrix

The seven named runtime adapters—Cursor, Claude, Codex, VS Code, Antigravity, Simplicio Agent (formerly Hermes), and the legacy `hermes` alias—must use the same completion oracle. `scripts/completion_oracle_matrix.py` executes that shared implementation once per adapter and compares the typed tuple `(ready, verdict, reason_code, tag)`.

A matrix is green only when every adapter has the same tuple. Unknown adapter names fail closed. This catches adapter-specific bypasses such as accepting a legacy `done` flag, ignoring a stale watcher challenge, or dropping a required evidence/flow gate.

Example:

```bash
python scripts/completion_oracle_matrix.py \
  --loop-dir .simplicio-loop/orchestrator/loop \
  --run-dir .simplicio-loop/orchestrator/runs/<run-id> \
  --response-text '<promise>EXACT TEXT</promise>'
```

The JSON result uses schema `simplicio.completion-oracle-matrix/v1` and includes one row per adapter, a `parity` boolean, and the common `signature`. Run it for both blocked fixtures and a complete fixture; a blocked verdict is expected whenever any required gate is absent.
