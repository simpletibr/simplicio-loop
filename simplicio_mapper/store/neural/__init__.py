"""Neural memory bank owned by MapperStore (central data hub).

Assets (seeds, migrations, schema) were absorbed from simplicio-runtime so
Mapper is the SoT for offline neural SQLite. Runtime/CLI clients should point
at the Mapper data root (SIMPLICIO_DATA_DIR) rather than a private Runtime DB.
"""

from .bank import (
    NEURAL_API_SCHEMA,
    NEURAL_DB_NAME,
    NeuralBankError,
    absorb_runtime_neural,
    apply_migrations,
    bootstrap_neural,
    neural_database_path,
    neural_status,
    seed_neural,
)

__all__ = [
    "NEURAL_API_SCHEMA",
    "NEURAL_DB_NAME",
    "NeuralBankError",
    "absorb_runtime_neural",
    "apply_migrations",
    "bootstrap_neural",
    "neural_database_path",
    "neural_status",
    "seed_neural",
]
