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
    "TransactionError",
    "WriterIdentity",
    "assert_within_root",
    "inspect_store",
    "is_busy_error",
    "resolve_store_location",
    "run_with_retry",
    "transaction",
]
