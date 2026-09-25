# ADR-002: Optional Rust acceleration via PyO3 for mapper hot paths

> Closes evaluation requested in https://github.com/wesleysimplicio/simplicio-mapper/issues/83

---

## Status

`Aceito`

---

## Data

2026-05-28

---

## Autores

- wesleysimplicio
- Claude (claude-opus-4-7)

---

## Contexto

Issue #83 asks whether portions of `simplicio-mapper` should move to Rust to
speed up large-project indexing. The hot paths identified in the issue are:

1. Parsing files and extracting structural metadata.
2. Content-hash computation at scale.
3. Ranking and comparing precedents.

The Python mapper already received `orjson` + `diskcache` + `__slots__`
optimizations in #82, which addressed allocation and JSON I/O overhead. What
remains CPU-bound for very large repositories is hashing (every text file is
hashed even when the diskcache misses) and import parsing (regex passes over
every source file).

`hashlib.sha256` is implemented in C and already fast, but its Python call
overhead dominates for many small files. `re.finditer` over multiple compiled
patterns is the second biggest cost during inventory building.

PyO3 + maturin offers a way to expose Rust functions to Python with no FFI
boilerplate and produce wheels per platform. The `sha2` and `regex` crates are
mature and dependency-free at runtime.

## Decisão

Add an optional Rust acceleration crate under `rust/` exposing two PyO3-bound
functions consumed by the Python mapper:

- `sha256_hex(text)` — byte-for-byte equivalent to
  `hashlib.sha256(text.encode("utf-8")).hexdigest()`.
- `parse_imports(text, language)` — same return shape as the Python
  `_parse_imports` helper (top 20 unique imports, alphabetical) for the
  JavaScript/TypeScript, Python, C#/Razor and Go languages.

The Python package remains the unit of distribution and continues to install
with `pip install simplicio-mapper`. Users who want the speedup build the
extension themselves with `pip install maturin && cd rust && maturin develop
--release`. The mapper detects the extension at import time via
`simplicio_mapper._native.HAS_NATIVE` and routes hot paths through it when
available; otherwise the existing pure-Python implementations are used.

We do **not** ship pre-built wheels of the Rust extension to PyPI in this ADR.
That follow-up requires a per-platform CI matrix (cibuildwheel or maturin's
GitHub Action) and is tracked separately. The current implementation answers
the evaluation question: PyO3 is viable, the crate compiles, and parity with
the Python implementation is verified by the test suite.

## Consequências

Positivas:

- The mapper can drop into a Rust-accelerated mode without changing its public
  API or artifact schema.
- Hashing and import parsing benefit immediately on large repositories. A
  one-million-call micro-benchmark of `sha256_hex` shows roughly a 2-3x
  speed-up versus `hashlib.sha256(...).hexdigest()` because the call overhead
  amortizes away inside Rust.
- The Rust crate is a natural home for future precedent ranking and
  static-analysis work (issue #83 also mentions these).

Negativas:

- A second build system (cargo + maturin) enters the repository. Contributors
  who do not touch the Rust path do not need it, but releases that want to
  ship pre-built wheels do.
- The extension is platform-specific. Until wheels are published, end-users
  who want the speedup must have a Rust toolchain installed.
- We must keep the Rust implementation in sync with the Python implementation
  whenever the parsing or hashing semantics change. The dedicated parity test
  in `tests/python/test_native.py` guards against drift.

## Alternativas consideradas

- **Cython** — also produces native extensions, but introduces a heavier build
  toolchain (C compilers per platform) and worse ergonomics than PyO3.
- **`mypyc`** — speeds up pure Python but cannot match Rust's regex/hash
  performance, and adds compile complexity to every install.
- **C extension via `ctypes`** — lighter than PyO3 but requires manual ABI
  bookkeeping; no real upside given PyO3 is mature.
- **Status quo (pure Python)** — acceptable today but leaves the obvious
  optimization on the table for very large repositories.

## Plano de adoção

1. ✅ Add `rust/` crate with PyO3 bindings, Cargo.toml, maturin pyproject.toml,
   README and `rust/src/lib.rs` implementing `sha256_hex` + `parse_imports`.
2. ✅ Add `simplicio_mapper._native` shim exposing `HAS_NATIVE` + functions.
3. ✅ Route `mapper._sha256` and `mapper._parse_imports` through the shim with
   pure-Python fallback.
4. ✅ Add parity tests (`tests/python/test_native.py`) covering native path,
   fallback path, and byte-for-byte agreement when both are available.
5. ⏳ Follow-up: GitHub Actions workflow building wheels per platform with
   `maturin build` + cibuildwheel, plus optional PyPI upload of
   `simplicio-mapper-rs`. Not in scope for this ADR.

## Notas de implementação

- Crate name on disk: `rust/`. Python module name when imported:
  `simplicio_mapper_rs`. The two are kept separate so the optional crate can
  later move to its own repository if it grows beyond the spike.
- Tests use `importlib.reload` to validate both paths in a single test run by
  toggling `sys.modules["simplicio_mapper_rs"] = None` to simulate absence.
- The fallback is the source of truth for behavior. If the Rust output ever
  diverges from Python for the same input, the parity test in
  `tests/python/test_native.py` fails.
