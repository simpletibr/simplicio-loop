# Rust hot-path validation — simplicio-core + qwen2.5-coder:3b (local Ollama)

Date: **2026-05-29**
Subject: Rust update `simplicio-core` (PyO3 crate, `build_6layer_prompt`, commit `ea3655b`, closes #17/#18)
Model: `qwen2.5-coder:3b` (Ollama, OpenAI-compatible endpoint `http://localhost:11434/v1`)
Toolchain: `rustc 1.95.0` · `cargo 1.95.0` · `pyo3 0.28.3` · `bumpalo 3.20.3` · `maturin 1.13.3`

The Rust crate re-implements the prompt substitution + comment-strip step of
`simplicio.prompt.build_prompt`. Python stays the source of truth and the
fallback; Rust only takes over when `simplicio_core` is importable. This report
validates the update on four axes: **build → correctness → speed → live model**.

> Update 2026-05-29: PyO3 bumped `0.22` → `0.28`; the crate now builds **natively
> on CPython 3.14.5** (was blocked at 3.13). All figures below are from the native
> 3.14 build.

---

## Headline

- **Build:** OK — `simplicio_core` cp314 release wheel built natively on CPython 3.14.5 in 9.49 s, installed, `_rs_build` live on the hot path. Zero source changes (PyO3 0.22→0.28 API forward-compatible).
- **Correctness:** 5/5 parity tests green + byte-identical to Python on a realistic 2294-char prompt.
- **Speed:** **8.47x faster** than the Python reference (2.710 µs vs 22.965 µs per call). Beats the "~5x" claim in `prompt.py`.
- **Live model:** rust-assembled 6-layer prompt drives `qwen2.5-coder:3b` to **5/6 (83%)** real-pytest pass — same as the contract baseline.

---

## 1. Build status

```
maturin develop --release  (CPython 3.14.5, uv-managed)
Updating pyo3 v0.22.6 -> v0.28.3
Compiling pyo3 v0.28.3 / bumpalo v3.20.3 / simplicio-core v0.1.0
Finished `release` profile [optimized] in 9.49s
Built wheel: simplicio_core-0.1.0-cp314-cp314-macosx_11_0_arm64.whl
Installed simplicio-core-0.1.0
```

Hot-path activation confirmed (Python 3.14.5):

```
>>> from simplicio.prompt import _rs_build
_rs_build = <built-in function build_6layer_prompt>
>>> simplicio_core.hello("rust")
'hello, rust!'
```

## 2. Correctness — parity suite

`tests/python/test_rust_prompt.py` — Rust output asserted byte-identical to the
Python `_assemble_python` reference.

| Test | Result |
|---|---|
| `test_hello_smoke` | PASS |
| `test_substitution_parity_basic` (real template) | PASS |
| `test_substitution_parity_utf8_em_dash` (multibyte safe) | PASS |
| `test_substitution_unknown_placeholder_passthrough` | PASS |
| `test_comment_strip_multiline` | PASS |

**5 passed in 0.04s** (CPython 3.14.5). Parity also held on the realistic
2294-char prompt used in the microbench (`rs == py`).

## 3. Performance — Rust vs Python

Real 6-layer template (1540 chars) + realistic pre-built blocks, 200 000 iterations, CPython 3.14.5:

| Impl | µs/call | ops/s | Speedup |
|---|---|---|---|
| Python `_assemble_python` | 22.965 | 43 545 | 1.00x |
| Rust `build_6layer_prompt` | 2.710 | 368 990 | **8.47x** |

Output: 2294-char assembled prompt, parity OK.

## 4. Live model — qwen2.5-coder:3b (real pytest)

### 4a. Contract effect (`bench/run_exec.py`, inlined contract)

| Model | Without | With | Delta |
|---|---|---|---|
| `qwen2.5-coder:3b` | 4/6 (66%) | 5/6 (83%) | **+17 pts** |

`validate_password` flips fail→pass with the contract. `merge_intervals` fails
both sides (genuine 3B reasoning limit, not a prompt issue).

### 4b. Rust-assembled prompt → qwen → hidden pytest (CPython 3.14.5)

Prompt built by `simplicio_core.build_6layer_prompt` (substitution + comment-strip
on the Rust hot path), then sent to the local model and scored:

| Task | Result | Latency |
|---|---|---|
| can_delete | PASS | 6255 ms |
| email_editable | PASS | 1262 ms |
| slugify | PASS | 5213 ms |
| apply_discount | PASS | 5772 ms |
| merge_intervals | fail | 6230 ms |
| validate_password | PASS | 4290 ms |

**5/6 (83%)** — matches the contract baseline. The Rust-built prompt yields the
same model behaviour as Python, confirming end-to-end parity under a live LLM.

---

## Resolved — Python 3.14

Previously PyO3 `0.22` capped at CPython 3.13, so the crate would not build against
the 3.14 default interpreter (PyO3 hard-errors on a newer interpreter for non-abi3
builds). **Fixed** by bumping `pyo3` to `0.28` (`Cargo.toml`) — a manual major bump
per `.specs/workflow/DEPENDENCY_POLICY.md`. No `lib.rs` changes were needed; the
`#[pyfunction]` / `Bound<'_, PyModule>` API is forward-compatible. Validated above
on the native CPython 3.14.5 build.

> Optional follow-up (not done here): adding the `abi3-py39` feature would emit a
> single forward-compatible `cp39-abi3` wheel that runs on any CPython ≥ 3.9
> without a per-version rebuild. That is a wheel-distribution decision, left for a
> separate change.

## Reproduce

```bash
# build natively on Python 3.14 (pyo3 0.28)
python3.14 -m venv /tmp/scv314 && /tmp/scv314/bin/pip install maturin numpy pytest
cd rust/simplicio-core && VIRTUAL_ENV=/tmp/scv314 /tmp/scv314/bin/maturin develop --release

# correctness
PYTHONPATH=. /tmp/scv314/bin/python -m pytest tests/python/test_rust_prompt.py -v

# live model (Ollama serving qwen2.5-coder:3b)
BENCH_BASE_URL=http://localhost:11434/v1 BENCH_API_KEY=ollama \
  BENCH_MODELS=qwen2.5-coder:3b PYTHONPATH=. /tmp/scv314/bin/python bench/run_exec.py
```
