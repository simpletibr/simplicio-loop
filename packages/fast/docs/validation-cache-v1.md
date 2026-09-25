# Content-addressed validation cache v1

`ValidationKey` includes source Merkle identity, lockfiles, toolchain, command,
allowlisted environment, platform, config/fixture fingerprints, generation,
producer schema and freshness class. Its digest is deterministic and excludes
timestamps, absolute paths and secrets. `ValidationCache` stores derived result
facts only; callers decide when policy requires a fresh execution.

`affected()` selects tests from explicit stable-handle mappings under a budget
and reports truncation rather than silently claiming completeness. The cache
does not run commands, replace Dev CLI gates or turn a cache hit into fresh
evidence.

`save()` and `load()` persist the derived entries behind a content digest and
reject malformed or tampered documents. Persistence is a cache transport only;
freshness policy and command execution remain explicit caller responsibilities.
