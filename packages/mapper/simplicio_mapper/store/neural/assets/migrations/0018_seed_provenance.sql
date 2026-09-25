-- Neural memory schema — migration 0018 (seed provenance)
-- Records deterministic seed inputs and the rows materialized by each apply.
-- The table is intentionally neutral: personal preferences must not be seeded
-- here; those belong to an explicit opt-in profile scope.

CREATE TABLE IF NOT EXISTS memory_seed_runs (
  seed_hash    TEXT PRIMARY KEY,
  expected_rows INTEGER NOT NULL,
  applied_rows  INTEGER NOT NULL,
  applied_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_seed_runs_applied_at
  ON memory_seed_runs(applied_at);
