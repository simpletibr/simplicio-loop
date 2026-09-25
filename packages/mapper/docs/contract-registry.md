# Cross-repository contract registry

`simplicio.contract-registry/v1` is the Mapper-owned inventory of public
contracts shared with Loop, Dev CLI, Runtime and Fast. It records ownership,
producers, consumers, writer authority, supported versions, canonical schema
paths, fixture paths and the required change policy.

The registry scanner is read-only. It never imports another repository, opens
another repository's database, invokes an effect, or changes source files.
Unknown identifiers, duplicate incompatible schemas and invalid registry
metadata are reported as failures. A canonical hash of `auto` is deliberately
reported as an unverified warning until a release process records the exact
hash.

From the Mapper checkout:

```text
simplicio-mapper contracts inventory \
  --root mapper=. \
  --root loop=../simplicio-loop \
  --root dev-cli=../simplicio-dev-cli \
  --root runtime=../simplicio-runtime \
  --registry contracts/contract-registry/v1/registry.json --json

simplicio-mapper contracts validate \
  --registry contracts/contract-registry/v1/registry.json --json

simplicio-mapper contracts diff --old old-schema.json --new new-schema.json --json

simplicio-mapper contracts impact simplicio.context-snapshot/v1 \
  --registry contracts/contract-registry/v1/registry.json --json
```

`diff` classifies JSON Schema changes as `breaking`, `additive`,
`compatible`, `ambiguous` or `unchanged`. A breaking change requires a new
version, an ADR, a migration fixture and consumer conformance evidence.
External contracts remain explicitly registered but unverified until their
canonical schema and cross-repository checkout are available to the gate.
