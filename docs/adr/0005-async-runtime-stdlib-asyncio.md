# ADR-0005 — Async runtime: stdlib `asyncio`, not AnyIO

- **Status:** accepted
- **Date:** 2026-07-19
- **Relates to:** issue #495 (async Python core epic), issue #508 (bounded queues /
  backpressure / event-driven polling), PR #583 (`AsyncBoundedQueue` wired into the remote
  worker's `serve-async`; that worker was removed in 3.46.0, see the amendment below).

## Context

Multiple verification passes on #508 flagged the same real, unresolved gap: the codebase had
already effectively chosen stdlib `asyncio` over an AnyIO-based abstraction layer for every
async module it ships (`async_bounded_queue.py`, `async_io_supervisor.py`, `event_loop.py`,
`map_service_single_flight.py`, `process_supervisor.py`; the original list also named the removed
`hub_daemon.py`, `loop_runtime.py`, `remote_queue.py` transport and `remote_worker_cli.py`) —
but that choice had never been written down anywhere as a closed decision. `anyio` does not appear in the dependency
manifests or in any module's imports.

AnyIO would have bought trio/curio interoperability and a slightly friendlier structured-
concurrency API surface, at the cost of an extra runtime dependency and a translation layer over
primitives (`asyncio.Queue`, `asyncio.Event`, `asyncio.wait_for`, `asyncio.create_subprocess_exec`)
that this project already uses directly and extensively.

## Decision

Keep stdlib `asyncio` as the sole async runtime for `simplicio-loop`.

This async decision does not grant workers build authority. Loop/Prism `asyncio` scheduling, leases, and I/O consume the centrally built, read-only binary/artifact set from the canonical default branch. Runtime/Tokio remains the authority for gates, effects, receipts, and reconciliation. Workers never rebuild binaries or regenerate canonical Mapper/Fast artifacts; worktrees isolate source edits and receipts only. Receipts record repository/revision, binary digest/version, Mapper generation, and artifact digest. Missing, stale, incompatible, or mismatched central artifacts fail closed and route to central rebuild only.

Do not add `anyio` as a
dependency. This is a ratification of the status quo, not a migration:

- `AsyncBoundedQueue` (`async_bounded_queue.py`) is built directly on `asyncio.Condition`/
  `asyncio.Event`, not an AnyIO memory-object-stream.
- The former remote worker's `serve-async` (#583, removed in 3.46.0) composed three plain
  `asyncio.create_task()` workers connected by two `AsyncBoundedQueue` instances — no AnyIO task
  group.
- `process_supervisor.py` uses `asyncio.create_subprocess_exec` and `asyncio.wait_for` for
  kill-tree/timeout handling.

## Rationale

- **No trio requirement.** Nothing in this codebase runs under trio or needs portability across
  event-loop implementations; the only consumers are CPython's default asyncio loop across
  Linux/macOS/Windows.
- **One fewer dependency.** `simplicio-loop` already keeps its dependency footprint deliberately
  thin (see ADR-0001); adding AnyIO for an abstraction this project would use in only one way is
  net-negative.
- **Team familiarity and existing test surface.** The `test_async_bounded_queue*.py` suites (and,
  when this was written, the remote-worker suites) already assert
  against `asyncio` primitives directly (`asyncio.CancelledError`, `asyncio.Event`, task
  cancellation semantics). Introducing AnyIO now would mean rewriting working, well-covered tests
  for no behavioral gain.

## Consequences

- Any future async module in this repo should use `asyncio` directly, matching the existing
  modules, rather than introducing a second async abstraction layer.
- If a concrete need for trio interoperability or structured task-group semantics AnyIO provides
  ever arises, it should be raised as its own ADR superseding this one — not mixed in ad hoc.
- This ADR does not, by itself, address the other real gaps named alongside it on #508: the
  repo-wide sweep of remaining synchronous blocking call sites (`cli.py`,
  `github_lifecycle.py`; `hub_daemon.py` and `secure_transport.py` were removed in 3.46.0) and cross-platform (Windows/macOS) verification of
  the async/kill-tree paths. Those remain open, tracked on #508/#509, and are unaffected by this
  decision either way since they do not currently use AnyIO.

## Amendment 2026-09-29

Issue #1379 (loop 3.46.0) removed the Hub daemon, the remote queue transport and remote
workers, `loop_runtime.py` and the Runtime/MCP integration. The decision above (stdlib
`asyncio`, no AnyIO) is unchanged and applies to the async modules that remain; the
Runtime/Tokio authority paragraph in the Decision section describes the removed integration.
