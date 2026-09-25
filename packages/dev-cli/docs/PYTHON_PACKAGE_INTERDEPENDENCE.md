# Python Package Interdependence

<!-- GENERATED FILE — do not hand-edit (#101). Regenerate with:
       python3 scripts/gen_package_interdependence.py
     Check it hasn't drifted from pyproject.toml with:
       python3 scripts/gen_package_interdependence.py --check
-->

Source of truth: this repo's `pyproject.toml` (`simplicio-cli` v0.18.16).

## Current Graph

```text
simplicio-mapper >=0.26.31,<0.27
  ^
  |
simplicio-cli 0.18.16
  ^
  |
simplicio-sprint (downstream, depends on this package)
```

## Real dependency floors (read from pyproject.toml)

### Base (always installed — `pip install simplicio-cli`)

- `numpy>=2.1.0`
- `simplicio-mapper>=0.26.31,<0.27`
- `httpx>=0.28.1`
- `orjson>=3.11.9`
- `diskcache>=5.6.3`
- `libcst>=1.8.6`
- `tiktoken>=0.12.0,<1`

### Optional extras (#99 — heavy ML/provider deps are opt-in)

- **`simplicio-cli[ml]`**: `sentence-transformers>=5.6.0`
- **`simplicio-cli[bench]`**: `fpdf2>=2.8.7`
- **`simplicio-cli[fast]`**: `simplicio-fast>=2.0.28,<3; python_version >= '3.11'`
- **`simplicio-cli[performance]`**: `uvloop>=0.21.0; sys_platform != 'win32'`
- **`simplicio-cli[all]`**: `simplicio-cli[ml]`, `simplicio-cli[bench]`, `simplicio-cli[performance]`
- **`simplicio-cli[test]`**: `pytest>=8`, `pytest-cov>=7`, `hypothesis>=6.100`, `tomli>=2.0.1; python_version < '3.11'`
- **`simplicio-cli[dev]`**: `simplicio-cli[test]`, `ruff>=0.15.8`, `mypy>=1.19.1`

## Rules

- `simplicio-prompt` is forbidden on the hot path (not a base dependency).
- `simplicio-mapper` stays independent from the executor and sprint packages.
- `simplicio-cli` may depend on `simplicio-mapper` (base), plus the optional extras above.
- `simplicio-sprint` may depend on `simplicio-cli` and `simplicio-mapper`.
- No package may depend on `simplicio-sprint`; this keeps the orchestration
  layer at the edge and prevents cycles.

## Where simplicio-cli fits (mapper / loop)

```text
simplicio-mapper   -- repo context (project-map.json, precedent-index.json)
       |
       v
simplicio-cli      -- THIS PACKAGE: edit --plan + test
       |               (no LLM; no Runtime; no simplicio-prompt)
       v
simplicio-loop     -- coordinator: lease, journal, watcher
```

simplicio-cli is the mutator/verifier. It does not orchestrate multi-step
work. Runtime is not part of this stack.

## Local LLM Standard

- Default local model for this package: `openbmb/minicpm5:latest`, via
  `llama.cpp` / `llama-cpp-python` (the `local` extra —
  `pip install 'simplicio-cli[local]'`).
- This is independent of any other Simplicio repo's local-model default;
  each repo pins its own via its own code (here: `simplicio/providers.py`'s
  `LOCAL_DEFAULT_MODEL`), which is what this doc reads to stay accurate.
- Ollama is not part of the local default path; it remains an explicit
  OpenAI-compatible provider option only when configured by the user
  (`SIMPLICIO_MODEL` / `SIMPLICIO_BASE_URL`).

