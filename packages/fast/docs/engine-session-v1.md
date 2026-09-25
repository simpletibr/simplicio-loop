# Resident engine session v1

The Rust reader exposes a resident, read-only session through newline-delimited
JSON on stdin/stdout. One process can serve `stats`, `query`, and `context`
requests after the verified handshake; the one-shot commands remain diagnostic
compatibility surfaces.

## Handshake

The first response is `simplicio.fast.engine-session/v1` and includes the ABI,
engine version, supported schemas/capabilities, binary SHA-256, source commit,
conformance digest, platform, nonce, and `transport: stdio-lines`. The Python
client rejects missing or mismatched identity fields before sending requests.

## Request bounds and generation pinning

Each request is one canonical JSON line no larger than 1 MiB. Query and context
operations remain bounded by their explicit result, byte, line, and token
limits. A request may include `payload.generation`, equal to the immutable
`SFAST001:<digest>` generation returned by snapshot stats. If it does not match
the mapped snapshot, the session returns `{\"ok\":false,\"reason\":\"generation_mismatch\"}`
and performs no read. This prevents a caller from silently consuming a stale
generation while the source-side owner swaps snapshots.

The session owns no source mutation, scheduling, policy, or effect authority.
Closing stdin terminates the process; clients must treat crash/restart as a
new handshake and revalidate the binary and conformance identity.
