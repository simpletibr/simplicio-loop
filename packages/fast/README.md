<p align="center">
  <img src="assets/simplicio-fast-hero-v3.png" alt="simplicio-fast turns source code into a shared binary semantic memory for fast agent execution" width="100%" />
</p>

<h1 align="center">simplicio-fast</h1>

<p align="center">
  <strong>Semantic project memory and guarded change coordination for AI coding tools.</strong>
</p>

<p align="center">
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-2.0.35-22c55e?style=for-the-badge" alt="Version 2.0.35"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%2B-3776ab?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="https://github.com/simpletibr/simplicio-loop/issues"><img src="https://img.shields.io/github/issues/simpletibr/simplicio-loop?style=for-the-badge" alt="Open issues"></a>
  <img src="https://img.shields.io/badge/core_runtime_dependencies-0-111827?style=for-the-badge" alt="0 core runtime dependencies">
  <img src="https://img.shields.io/badge/integrated_extra_dependencies-2-334155?style=for-the-badge" alt="2 integrated extra dependencies">
</p>

<p align="center">
  <strong>Languages:</strong><br>
  <a href="README.md">English</a> ·
  <a href="READMEs/README.pt-BR.md">Português</a> ·
  <a href="READMEs/README.es-ES.md">Español</a> ·
  <a href="READMEs/README.fr-FR.md">Français</a> ·
  <a href="READMEs/README.de-DE.md">Deutsch</a> ·
  <a href="READMEs/README.it-IT.md">Italiano</a> ·
  <a href="READMEs/README.ja-JP.md">日本語</a> ·
  <a href="READMEs/README.ko-KR.md">한국어</a> ·
  <a href="READMEs/README.zh-CN.md">简体中文</a> ·
  <a href="READMEs/README.ru-RU.md">Русский</a> ·
  <a href="READMEs/README.pl-PL.md">Polski</a> ·
  <a href="READMEs/README.tr-TR.md">Türkçe</a> ·
  <a href="READMEs/README.nl-NL.md">Nederlands</a> ·
  <a href="READMEs/README.hi-IN.md">हिन्दी</a> ·
  <a href="READMEs/README.ar-SA.md">العربية</a>
</p>

---

## What is simplicio-fast?

`simplicio-fast` is the semantic project-memory layer for AI coding workflows. It turns a repository
into a versioned, memory-mapped snapshot, selects small hash-verified context packets, compiles
plans, and produces guarded changeset/rollout receipts. The source files remain authoritative; the
snapshot is a disposable, incrementally refreshed cache.

In one sentence: **Fast helps an agent understand the right code and prove which generation a
proposed change came from, without becoming the LLM, scheduler or policy authority.**

Version 2.x coordinates the boundaries between Mapper, Dev CLI, Loop and Runtime:

| Fast owns | Other Simplicio components own |
|---|---|
| ingestion, binary/mmap memory, bounded context, PlanDAG and hash guards | canonical ContextGraph extraction (Mapper) |
| generation IDs, worktree overlays and rollout receipts | mechanical source mutation (Dev CLI) |
| deterministic JSON contracts and fail-closed fallback | policy/effects/receipts (Runtime) and retries/slots/convergence (Loop) |

Fast is **not** an LLM, an autonomous scheduler, a source-of-truth database, or a replacement for
Runtime authorization. It is the small, inspectable coordination layer between repository files and
those tools.

```text
normal source files
        ↓
semantic extraction + SHA-256
        ↓
versioned .sfast binary snapshot
        ↓ mmap
small context query
        ↓
LLM plan and normal source patch
        ↓
tests + incremental refresh
```

The source repository always remains the source of truth. A `.sfast` file is a disposable derived cache, never a replacement for `.py`, `.ts`, `.rs`, `.cs` or other development files.

## Why it matters

- **Fast repeated orientation** — avoid parsing the full repository for every query.
- **Incremental rebuilds** — unchanged files reuse their semantic records by SHA-256.
- **Low-copy access** — `mmap` lets the OS page only the bytes that are touched.
- **Shared project memory** — future Loop slots can pin one immutable base generation.
- **Smaller LLM context** — send selected symbols and spans instead of repository dumps.
- **Auditable execution** — generation IDs, source hashes and receipts can bind context to patches.

> `simplicio-fast` is designed for broad repository use, but speedups are workload-dependent. The current ~23× result is a measured POC query benchmark, not a universal guarantee. Small repositories and cold one-shot runs may see little or no gain.

<p align="center">
  <img src="assets/simplicio-fast-shared-memory-v3.png" alt="One immutable memory-mapped snapshot shared by isolated worktrees" width="920" />
</p>

<p align="center"><em>One canonical memory image, many isolated consumers and future worktree overlays.</em></p>

## Benchmark

The included benchmark generates 500 Python modules containing 1,500 symbols. It compares reparsing every AST for each query with querying the binary snapshot through `mmap`.

| Operation | Median/total wall time | CPU / incremental behavior |
|---|---:|---:|
| Traditional AST query | 40.35 ms median | 40.36 ms CPU |
| Cold snapshot build | 57.43 ms | 500 parsed |
| `mmap` snapshot query | 1.75 ms median | 1.76 ms CPU |
| Rebuild without changes | 26.65 ms | 0 parsed / 500 reused |
| Rebuild after one file change | 28.05 ms | 1 parsed / 499 reused |

**Measured query result:** approximately **23× faster** and **95.65% less query CPU** on the recorded local environment (Python 3.12.13, peak process RSS 21,268 KiB).

Reproduce it with the same disposable-fixture approach the test suite uses (build
a snapshot, then query it via `simplicio-fast build`/`query`) rather than trusting
the table.

The command records wall time, CPU time, peak RSS (or `null` plus an explicit reason when the host does not expose it), cold build, warm query, no-change rebuild, one-file rebuild and whether the changed symbol became visible. It also measures the shared-base overlay path at 1, 5 and 20 slots with ten repetitions per row. Use identical hardware/configuration when comparing integrations.

Peak RSS is reported in KiB using POSIX `resource.getrusage` or Windows
`GetProcessMemoryInfo` through the standard-library `ctypes` bridge. If the operating system
cannot expose the metric, the command still completes with a partial receipt: `peak_rss_kib` is
`null`, `peak_rss_reason` contains a deterministic reason code, and both `status` and
`metrics_status` are `"partial"` in the `simplicio.fast.benchmark/v1` receipt.

## Install

```bash
git clone https://github.com/simpletibr/simplicio-loop
cd simplicio-loop/packages/fast
python -m pip install -e .
```

The base install is dependency-free and keeps the complete Python fallback.
For the production Mapper/Dev CLI adapters, install the explicit profile:

```bash
python -m pip install -e '.[integrated]'
```

Loop installs Mapper, Dev CLI, and Fast from its pinned submodules, so it does
not need Fast to pull their transitive stacks into every isolated slot.

### Offline installation verification

`simplicio-fast doctor --installation --json` is an offline check: it reports the
installed Python package and the offline resolution path. The command does not
download, build, or remove files.

For a local packaging smoke test on Windows, build both artifacts and install the
wheel into a clean target directory:

```powershell
python -m build
python -m venv .tmp-fast-venv
& .\.tmp-fast-venv\Scripts\python.exe -m pip install --no-deps (Get-ChildItem dist\simplicio_fast-*.whl).FullName
& .\.tmp-fast-venv\Scripts\python.exe -m simplicio_fast.cli doctor --installation --json
```

This is a local Python/wheel check. Cross-OS/architecture wheels, signed
provenance, and upgrade/downgrade rollback still require the clean VM/container
matrix tracked by issue #44.

## CLI and agent contract

```bash
simplicio-fast --help
simplicio-fast build --help
simplicio-fast query --help
simplicio-fast search --help
simplicio-fast context --help
simplicio-fast impact --help
simplicio-fast stats --help
simplicio-fast doctor --help
simplicio-fast capabilities --help
simplicio-fast base --help
simplicio-fast overlay --help
simplicio-fast merge --help
simplicio-fast rollout --help
simplicio-fast serve --help
```

Run `simplicio-fast --help` first when integrating a new tool or LLM. Its command descriptions
state the role of each surface: build/refresh memory, query or bound context, plan a task, validate
or apply a hash-guarded changeset, inspect readiness, coordinate overlays, and emit rollout state.
All machine-facing responses are versioned JSON; consumers must preserve `schema`, generation and
receipt fields and must never read `.sfast` offsets directly.

Build and query the current repository:

```bash
simplicio-fast ingest .
simplicio-fast understand "change UserService"
simplicio-fast plan "change UserService"
simplicio-fast query UserService
```

Run without installing:

```bash
PYTHONPATH=src python -m simplicio_fast.cli build .
PYTHONPATH=src python -m simplicio_fast.cli query UserService
```

`context --json` emits a versioned `provenance` receipt alongside bounded spans. The receipt
contains the normalized repository root, the Git commit (or `null` plus an explicit reason outside
Git), the absolute snapshot path, the SHA-256 digest of the bytes opened by mmap, the stable
`SFAST001:<digest>` generation, span count and effective limits. Loop and Runtime consumers may pin
that generation and verify each span's `source_sha256`; they must request semantic context through
Mapper and must not read `.sfast` offsets directly.

```bash
PYTHONPATH=src python -m simplicio_fast.cli context UserService \
  --root . --snapshot .simplicio-loop/fast/project.sfast --max-results 10 --max-lines 120 \
  --max-bytes 32000 --max-tokens 8000 --json
```

The command fails closed with `simplicio.fast.error/v1` when the snapshot is corrupt or a source
file no longer matches its recorded hash; refresh the derived snapshot before retrying.

## Canonical generations and worktree overlays

Issue #3 adds a versioned coordination layer without making `.sfast` a public
context contract. Build one immutable base generation from the default branch,
then create one delta per worktree:

```bash
simplicio-fast base .
simplicio-fast overlay . --base-generation <base-generation> --worktree-id slot-1
simplicio-fast merge UserService --base-generation <base-generation> \
  --worktree-id slot-1 --overlay-generation <overlay-generation>
```

The manifest binds the generation to the source commit, configuration,
parser capabilities and source SHA-256 values. Overlay records contain only
changed-file symbols and tombstones; merge is read-only and never rewrites the
canonical base. Results carry `base_generation` and `overlay_generation` so a
Mapper/Runtime caller can pin a bounded, auditable context attempt.

For issue-scoped Loop handoffs, use the changed-path contract instead of rebuilding the canonical base:

```bash
simplicio-fast delta . --base-generation <base-generation> --worktree-id issue-230 --changed-path src/service.py
simplicio-fast handoff . --base-generation <base-generation> --worktree-id issue-230 \
  --delta-generation <delta-generation> --parity-snapshot .simplicio-loop/fast/full.sfast
```

The handoff is `simplicio.fast.handoff/v1` and reports cold/warm/incremental timings,
CPU time, mapped bytes, parsed files, cache reuse, canonical snapshot SHA-256, delta SHA-256
and source-tree parity. It rejects a stale base commit, config fingerprint, schema, artifact
digest or source path.

Its receipt is `simplicio.fast.changed-path-delta-benchmark/v2`; v1 readers must reject
or explicitly migrate the previous `raw`/`totals` shape to `categories.<lane>.raw`/`summary`.

Rollback is safe and derived-state-only: discard the delta generation, release its lease, and
keep the immutable canonical base; source files remain authoritative and are never reverted by
Fast's handoff path.
Use `simplicio-fast pin` while an attempt is active and `simplicio-fast gc`
afterward. GC is dry-run by default and never removes a generation protected by
an unexpired lease. `simplicio-fast watch` performs a debounced refresh pass;
watchers should call the same operation after filesystem events rather than
building a full snapshot in every slot.

Supported adapters are Python AST plus deterministic fallback extractors for
TypeScript, Rust and C#. `simplicio-fast capabilities` reports whether a native
parser is available, whether fallback extraction is active, and why a language
is unavailable. Fallback results are bounded semantic hints and should be
verified by the native toolchain before mutation.

## CRUD proof of concept

The repository includes a dependency-free user API to prove the full cycle: create normal source, map it, query it, alter its behavior and refresh only the changed semantic input.

```bash
simplicio-fast serve --port 3000
```

```bash
curl -X POST http://127.0.0.1:3000/users \
  -H 'content-type: application/json' \
  -d '{"name":"Wesley","email":"wesley@example.com"}'

curl http://127.0.0.1:3000/users

curl -X PUT http://127.0.0.1:3000/users/USER_ID \
  -H 'content-type: application/json' \
  -d '{"active":false}'

curl -X DELETE http://127.0.0.1:3000/users/USER_ID
```

## How an LLM or tool should use it

An LLM or tool should not read the `.sfast` binary directly. Ask Fast for a bounded context packet,
make the decision from those spans, and return a versioned changeset for guarded execution.

1. The task reaches Fast through the Agent or Loop.
2. Fast invokes Mapper and stores the canonical graph in mmap.
3. `understand` selects bounded, hash-verified context.
4. `plan` compiles `simplicio.fast.plandag/v2`.
5. The LLM decides and returns `simplicio.fast.changeset/v2`.
6. `delivery --changeset changeset.json` wraps the same guarded executor in a delivery receipt. It is a dry-run by default; `--write --profile loop-standalone` performs the local atomic path, verifies before/after hashes, refreshes the snapshot and makes identical retries idempotent. Full writes fail closed until a verified Runtime authorization is integrated. If the native adapter is unavailable or refuses the v2 contract, Fast reports the refusal and may use its explicit atomic bootstrap fallback; the receipt remains versioned and never labels that path as integrated.
7. Runtime authorizes effects and Loop validates/converges.
8. Fast incrementally refreshes changed files.

### Integrated delivery versus bootstrap

The production delivery path is explicit and Mapper-owned. Produce the Mapper handoff first, then pass it to Fast:

```bash
simplicio-mapper snapshot build --root .
simplicio-mapper fast-handoff . > mapper-handoff.json
simplicio-fast build . --output fast.sfast --mapper-mode integrated --mapper-handoff mapper-handoff.json
simplicio-fast delivery "implement the requested change" --root . --snapshot fast.sfast --mapper-mode integrated --mapper-handoff mapper-handoff.json
```

Integrated delivery fails closed when the handoff is absent, stale, incomplete or incompatible. The Python snapshot extractor is only an explicit development fallback:

```bash
simplicio-fast delivery "diagnose locally" --root . --snapshot fast.sfast --mapper-mode bootstrap
```

Receipts record the producer, mode, Mapper generation and stable handles; bootstrap output is never labeled as integrated production context.

For parser-adapter/v1 consumers, the same validated handoff can be compiled into a
canonical JSON payload. Mapper remains the owner of symbols and stable IDs; Fast only
verifies source hashes and translates the documented facts:

```bash
simplicio-fast parser-payload . --mapper-handoff mapper-handoff.json --output parser-payload.json
```

The command fails closed on missing Mapper IDs, unsupported schemas, stale artifact
digests, missing sources or unknown relation targets.

Version 2.0.35 provides `ingest`, `understand`, `plan`, `apply`, `context`, `doctor`, `refresh`,
`query` and the CRUD proof. Internal mapping/editing remain bootstrap fallbacks when integrations
are absent; `doctor` identifies whether the complete integrated path is ready.
The `build`, `query`, direct-index `search`, bounded `context`, typed `impact`, `stats` and
`doctor` surfaces remain available for the binary format. Mapper remains the canonical public
context producer; consumers should use its versioned handles rather than reading this binary
directly. Full cross-repository integration is tracked in [issue #1](https://github.com/simpletibr/simplicio-loop/issues/1).
The compatibility matrix and the atomic shadow/canary/rollback receipt contract are
tracked under the same epic.

### Verified address catalog (Python reference)

`simplicio_fast.catalog.AddressCatalog` keeps the complete Mapper SHA-256 as the
authoritative identity and derives a short handle scoped to the normalized repository
and generation. `resolve`, `resolve_many`, `verify`, `stat` and binary `save`/`load`
validate payload digests and fail closed for cross-repository, stale-generation,
tombstoned or corrupted handles. The catalog never exposes `.sfast` offsets.
Context-packet handle transport remains an explicit follow-up gate for issue #59.

### Bitemporal overlay reference

`simplicio_fast.temporal.BitemporalOverlay` records append-only semantic versions with
logical source/world sequences and observed/system sequences. `as_of` reconstructs a
generation-scoped view; update, rename and delete create predecessor/successor links or
tombstones instead of erasing prior evidence. The Python reference does not claim
storage compaction, Runtime authorization or cross-repository E2E integration; those are
the remaining gates for issue #60.

### Semantic pager reference

`simplicio_fast.pager.SemanticPager` is the bounded Python reference for a
generation-scoped working set. It enforces byte/page budgets, validates page digests,
deduplicates concurrent loads with single-flight, supports leases, deterministic LRU
eviction, bounded prefetch and selective invalidation. It reports observable cache
metrics. Semantic page-in, RSS/page-fault telemetry, Runtime quotas and 20/100-slot
E2E behavior remain gates for issue #61.

### Delivery ledger reference

`simplicio_fast.ledger.DeliveryLedger` provides the Python boundary reference for
`simplicio.fast.delivery-ledger/v1`: deterministic event IDs, domain-separated chained
hashes, incremental/full verification, idempotent appends, winner fencing, delivery
sealing and secret-redaction checks. It projects JSON only at the boundary and does not
claim to replace the Runtime #3626 HBP/HBI codec, multiprocess persistence or Full/Loop
E2E integration; those remain gates for issue #62.

<p align="center">
  <img src="assets/simplicio-fast-verified-flow-v3.png" alt="Compact context moving through planning, editing, testing and verification gates" width="920" />
</p>

<p align="center"><em>Compact context enters; verified normal source code leaves.</em></p>

## Binary contract 2.0

New snapshots are `SFAST001/v2`, little-endian and immutable after publication. The header points to
an aligned section directory; every section and the complete payload have SHA-256 checksums. The
fixed-size file and symbol records are validated before mmap access, while direct exact/name-prefix,
path and kind indexes resolve records without walking the complete symbol table. Stable symbol IDs
are SHA-256 values derived from repository, relative file, language, qualified symbol and signature.

The `relations` section stores deterministic `import`, `reference`, `call`, `definition` and `test`
edges with origin, destination and confidence. `context` enforces result, line, byte and token budgets
and includes the source SHA-256 for every span. `doctor` reports the pinned generation and section
checksums, and rejects truncation, overlap, unknown versions, bad offsets and tampering without a
process crash.

| Section | Purpose |
|---|---|
| Header/directory | `SFAST001`, schema version, endian marker, generation, aligned sections and whole-file SHA-256 |
| File records | path reference, source size, SHA-256 and stable file ID |
| Symbol records | name/qualified/signature references, file ID, line range, kind and stable ID |
| Direct indexes | exact qualified name, name prefix, path and kind lookup tables |
| Relations | typed imports, references, calls and confidence |
| String table | compact UTF-8 paths, names, qualified names and signatures |

Safety properties:

- read-only memory mapping;
- bounds, magic, version and total-size checks;
- atomic temporary-write and replace;
- deterministic symbol ordering;
- source hashes for incremental reuse;
- safe full rebuild because snapshots are derived.

### Segmented storage and bounded page-in

The Python reference can publish immutable SFAST sections as content-addressed segments:

```bash
simplicio-fast segments publish --directory .simplicio-loop/fast/segments --snapshot .simplicio-loop/fast/project.sfast
simplicio-fast segments validate --directory .simplicio-loop/fast/segments
simplicio-fast segments map --directory .simplicio-loop/fast/segments --name symbols
```

`segments map` validates the selected segment's size and SHA-256, then opens only that segment
through read-only `mmap`; it never exposes offsets from the monolithic snapshot. Publication
swaps the manifest atomically and retains content-addressed segments for unchanged generations.
Python is the sole writer and reader authority; demand-driven semantic indexes and
large-RSS/page-fault benchmarks remain open gates for issues #40, #43 and #61.

### Deterministic query planning

`query-plan` emits `simplicio.fast.query-plan/v1` with the selected exact, prefix, path, kind,
or relation index, candidate record count, bounded byte estimate, generation and reason code:

```bash
simplicio-fast query-plan DeliveryEngine --operation context --max-results 3 --max-bytes 12000
```

The planner uses index statistics and record sizes; it does not claim provider tokens, does not
materialize source spans, and keeps causal prefetch disabled until a bounded neighbor policy is
available. Plan output is explainable and comparable across identical generations.

### Append-only change journal

`simplicio_fast.journal.ChangeJournal` provides the bounded reference contract for incremental
consumers. It stores `simplicio.fast.change-journal/v1` records with canonical create, update,
rename, delete, config and schema events, source generation, optional before/after SHA-256 values,
and a SHA-256 chain. Every append fsyncs the record; reads fail closed on schema, path, chain,
hash or JSON corruption. A final incomplete record can be recovered explicitly with
`journal.recover()`, which truncates only that tail and returns a versioned recovery receipt.

The journal is an evidence log, not a replacement for source files or the published snapshot:
dependency closure, cross-language adapters, proportional parser reuse and end-to-end daemon
integration remain separate gates for issue #77.

### Migration from SFAST001/v1

Readers accept both the frozen v1 table and v2 section snapshots. A v1 snapshot is read-only during
the migration window and has no persisted relation/index sections; queries use its validated legacy
records. Run `simplicio-fast refresh . -o .simplicio-loop/fast/project.sfast` (or `build`) to publish a
v2 snapshot atomically. Never patch a `.sfast` file in place: if `doctor` reports an incompatible,
truncated or checksum-failing file, discard the derived cache and rebuild from source. A failed
refresh leaves the previous complete snapshot untouched.

## Test

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
python scripts/check_release_integrity.py --check --json
```

The wheel carries `simplicio_fast/release_policy.json`, so an installed
consumer can inspect branch, dependency and version-source policy without
access to the source checkout. The root `release-policy.json` is a checked
mirror, and the integrity gate rejects drift between the two.

Version 2.0.35 covers:

- complete user CRUD and later status change;
- normalized-email conflict;
- binary build and symbol query;
- unchanged-file reuse;
- one-file invalidation and new-symbol visibility.
- v2 corruption/truncation rejection, direct indexes, typed impact relations and bounded context;
- frozen SFAST001/v1 read compatibility.

The benchmark defaults to ten repetitions at 1,000, 10,000 and 100,000 symbols and records wall
time, CPU time, peak RSS and page-fault counters where the host exposes them. Use identical source,
query, Python, hardware and cache conditions when comparing baseline and Fast; unavailable counters
are emitted as `null`, never estimated.

## Current scope

Ready in Fast 2.0.16:

- Python 3.11+;
- Python AST classes, functions and async functions;
- versioned binary snapshot;
- read-only `mmap`;
- incremental SHA-256 reuse;
- atomic writes;
- CRUD, tests and benchmark;
- Mapper/Dev CLI readiness checks with explicit fallback receipts;
- canonical base generations, isolated worktree overlays, leases and refresh;
- provenance, apply and rollout receipts for shadow, canary, integrated and rollback states;
- optional Runtime-first semantic scoring with a complete deterministic offline fallback.

External boundaries and follow-ups:

- full Mapper, Dev CLI, Loop and Runtime integration remains an integration concern:
  callers must pass Mapper-owned handles and must not read Fast offsets directly;
- central daemon and native parser bindings remain follow-up work;
- cross-repository promotion remains owned and verified by the corresponding Loop/Runtime projects.

## Ecosystem architecture

| Project | Responsibility |
|---|---|
| `simplicio-fast` | central processor, mmap memory, understanding and PlanDAG |
| `simplicio-mapper` | canonical project extraction and stable IDs |
| `simplicio-dev-cli` | guarded mechanical source edits |
| `simplicio-loop` | orientation, slots, convergence and delivery |
| `simplicio-runtime` | deterministic execution, policy and receipts |
| `simplicio-agent` | decisions, context selection and patch strategy |
| `simplicio-code` | integrated developer experience |



## V3 architecture and execution profiles

Fast is the semantic CPU/cache engine for comprehension and guarded change delivery. It keeps
repository meaning hot across orientation, impact analysis, planning, editing, validation and
retries. The source tree remains authoritative; snapshots are derived state.

- **Full:** Mapper → Fast → Dev CLI, coordinated by Loop and governed by Runtime.
- **Loop standalone:** Loop → Fast, with Mapper and Dev CLI adapters encapsulated; Runtime,
  Agent and Code are optional.
- **Engine:** Python is the only engine. There is no probing, selection between
  implementations, or fallback wording; `select_engine("python")` always succeeds and
  `off` disables the engine entirely.

See [ADR-0001](docs/ADR-0001-fast-v3-ownership.md) and the
[contract matrix](docs/fast-v3-contract-matrix.md). The executable delivery-engine work is
tracked in [issue #46](https://github.com/simpletibr/simplicio-loop/issues/46).

## Star history

[![Star History Chart](https://api.star-history.com/svg?repos=simpletibr/simplicio-loop&type=Date)](https://star-history.com/#simpletibr/simplicio-loop&Date)

> GitHub stars and the chart become externally visible when repository visibility and Star History access permit it.

## Roadmap

See the granular cross-repository plan:

- [Simplicio Loop epic and core issues](https://github.com/simpletibr/simplicio-loop/issues)
- [Mapper integration](https://github.com/simpletibr/simplicio-loop/issues/358) (now `packages/mapper/`)
- [Dev CLI integration](https://github.com/simpletibr/simplicio-loop/issues/341) (now `packages/dev-cli/`)
- [Loop integration](https://github.com/wesleysimplicio/simplicio-loop/issues/746)
- [Runtime integration](https://github.com/wesleysimplicio/simplicio-runtime/issues/3597)

## License and status

Version 2.0.35 is governed by the local release-integrity gate. Review [CHANGELOG.md](CHANGELOG.md),
`AGENTS.md` and open issues before making it mandatory across the entire Simplicio ecosystem.
