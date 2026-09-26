"""Stable MapperStore contract identifiers and ownership declarations.

The individual domain stores use these values as metadata markers.  Keeping
the identifiers in a dependency-free module prevents the canonical facade from
having to import a domain implementation merely to validate a store.
"""

from __future__ import annotations

MAPPER_STORE_SCHEMA = "simplicio.mapper-store/v1"
MAPPER_STORE_API_SCHEMA = "simplicio.mapper-store-api/v1"
MAPPER_STORE_CAPABILITY_SCHEMA = "simplicio.mapper-store-capability/v1"
MAPPER_STORE_CONFORMANCE_SCHEMA = "simplicio.mapper-store-conformance/v2"
MAPPER_STORE_RECORD_SCHEMA = "simplicio.mapper-store-record/v1"
MAPPER_STORE_ABSORB_SCHEMA = "simplicio.mapper-store.legacy-absorb/v1"

MAPPER_STORE_WRITER = "mapper-store"
MAPPER_STORE_READERS = ("runtime", "loop", "mcp")

MEMORY_STORE_VERSION = 1
SEMANTIC_STORE_VERSION = 1
OPERATIONS_STORE_VERSION = 1

__all__ = [
    "MAPPER_STORE_ABSORB_SCHEMA",
    "MAPPER_STORE_API_SCHEMA",
    "MAPPER_STORE_CAPABILITY_SCHEMA",
    "MAPPER_STORE_CONFORMANCE_SCHEMA",
    "MAPPER_STORE_READERS",
    "MAPPER_STORE_RECORD_SCHEMA",
    "MAPPER_STORE_SCHEMA",
    "MAPPER_STORE_WRITER",
    "MEMORY_STORE_VERSION",
    "OPERATIONS_STORE_VERSION",
    "SEMANTIC_STORE_VERSION",
]
