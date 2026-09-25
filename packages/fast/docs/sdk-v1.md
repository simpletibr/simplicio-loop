# Embeddable SDK v1

`ProjectionSDK` provides a small in-process Python facade for publish, scoped
delta compilation, query, snapshot, save/open, context compilation and
capability inspection. It delegates validation to the typed projection/store
contracts and preserves explicit repository/generation boundaries.

The SDK is provider-neutral and read-only with respect to source authority. It
does not require a global daemon or MCP server, does not expose mmap pointers,
and does not authorize effects. Rust crate parity, resident session transport,
async-safe adapters, installed cross-platform artifacts and release receipts
remain open gates for #348.

`ProjectionSDK` supports explicit `close()` lifecycle management plus synchronous
and asynchronous context-manager forms. Closing is idempotent; all operations,
including async adapters, fail with the stable `sdk_closed` reason code after
close, preventing use of a released facade.

`query_async()` and `context_async()` run the same bounded local operations in
a worker thread and return deterministic results matching the synchronous API,
without shared mutable async state or a daemon requirement.

`ProjectionSDK.capabilities()` exposes a machine-readable `support_matrix`.
The Python surface is currently `supported`; Rust, resident session and CLI
surfaces are explicitly `partial` until their conformance, installed-artifact
and cross-platform receipts are available. A partial row is not a parity claim.

The same capabilities response includes `simplicio.fast.sdk-compatibility/v1`.
An exact version is accepted, and a reader upgrade may consume an older minor
within the same major. A reader downgrade rejects a newer artifact minor until
an explicit migration exists; every major mismatch, including a future major,
rejects with a stable reason code. Rollback is limited to a previously
validated contract version, so version skew cannot silently become authority.
