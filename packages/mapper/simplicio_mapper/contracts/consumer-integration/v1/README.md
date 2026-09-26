# Consumer integration contract v1

This contract defines the external, installed-wheel boundary for consumers that
depend on `simplicio-mapper` retrieval/context outputs without importing the
repo checkout.

- `simplicio.consumer-dev-cli-receipt/v1` captures a Dev CLI-shaped consumer
  reading the published retrieval index/selection schemas and honoring
  sufficiency and broader-context flags.
- `simplicio.consumer-loop-receipt/v1` captures a Simplicio Loop-shaped
  consumer reading the published context snapshot/graph schemas and honoring
  omission and broader-context flags.

These receipts are intentionally narrow: they prove an installed wheel can
produce consumable outputs from real artifacts, but they do not authorize any
mutation or in-tree imports.
