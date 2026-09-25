# SDK diagnostic capabilities

`simplicio-fast capabilities` emits the existing
`simplicio.fast.capabilities/v1` response and now includes a nested
`simplicio.fast.sdk-capabilities/v1` object. The object mirrors the public
Python SDK operations and support matrix, and embeds the compatibility,
source-adapter and context-security manifests.

The CLI is diagnostic only: it does not open a resident session, mutate source
files, create an MCP authority or promote a partial Rust/session capability to
parity. Python remains the supported surface while the other rows retain their
explicit partial reason codes.
