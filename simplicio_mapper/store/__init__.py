"""Public MapperStore/v1 Python foundation.

This package owns connection policy and lifecycle only. Domain schemas belong to
later MapperStore issues; importing it performs no filesystem or SQLite work.
"""

from .connection import (
    StoreConnection,
    StoreError,
    StoreIntegrityError,
    StoreMissingError,
    WriterIdentity,
)
from .locks import StoreFileLock, StoreLockError
from .paths import StoreLocation, StorePathError, assert_within_root, resolve_store_location
from .profiles import StoreMode, StoreProfile
from .registry import (
    DEFAULT_MANIFEST,
    MIGRATION_EVENT_SCHEMA,
    SCHEMA_REGISTRY,
    AmbiguousMigrationError,
    IncompatibleWriterError,
    MigrationEngine,
    MigrationFault,
    MigrationPreflightError,
    MigrationSpec,
    RegistryChecksumError,
    RegistryError,
    canonical_json,
    default_migrations,
    negotiate,
    registry_fixture,
    sha256_json,
)
from .semantic import SEMANTIC_API_SCHEMA, SEMANTIC_SCHEMA, SemanticStore, SemanticStoreError
from .status import inspect_store
from .transactions import (
    FenceValidator,
    FenceViolationError,
    TransactionError,
    is_busy_error,
    run_with_retry,
    transaction,
)

__all__ = [
    "FenceValidator",
    "FenceViolationError",
    "StoreConnection",
    "StoreError",
    "StoreFileLock",
    "StoreIntegrityError",
    "StoreLocation",
    "StoreLockError",
    "StoreMissingError",
    "StoreMode",
    "StorePathError",
    "StoreProfile",
    "AmbiguousMigrationError",
    "DEFAULT_MANIFEST",
    "IncompatibleWriterError",
    "MIGRATION_EVENT_SCHEMA",
    "MigrationEngine",
    "MigrationFault",
    "MigrationPreflightError",
    "MigrationSpec",
    "RegistryChecksumError",
    "RegistryError",
    "SCHEMA_REGISTRY",
    "SEMANTIC_API_SCHEMA",
    "SEMANTIC_SCHEMA",
    "SemanticStore",
    "SemanticStoreError",
    "TransactionError",
    "WriterIdentity",
    "assert_within_root",
    "canonical_json",
    "default_migrations",
    "inspect_store",
    "is_busy_error",
    "negotiate",
    "registry_fixture",
    "resolve_store_location",
    "run_with_retry",
    "sha256_json",
    "transaction",
]
