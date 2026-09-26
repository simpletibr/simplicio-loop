# Public Simplicio I/O contract — `simplicio.io/v1`

This is the only public envelope shared by Mapper, Fast, Dev CLI and Loop.
Internal schemas remain implementation details of their owning component.

| Operation | Owner | Responsibility |
|---|---|---|
| `understand` | Mapper | survey the repository and produce canonical context |
| `search` | Fast | retrieve/rank context without editing files |
| `change` | Dev CLI | apply deterministic changes and report evidence |
| `verify` | Dev CLI | run bounded validation and report evidence |
| `run` | Loop | coordinate the operations, retries and convergence |

Every message has the same outer shape: `schema`, `operation`, `request_id`,
`repository`, `payload`, `evidence` and `error`. The payload is owned by the
operation owner; consumers must not depend on internal offsets, filenames or
private receipt formats.

Breaking changes create `simplicio.io/v2`. Legacy cross-repository envelopes
are not adapted indefinitely: producers and consumers migrate together in the
same release train.

