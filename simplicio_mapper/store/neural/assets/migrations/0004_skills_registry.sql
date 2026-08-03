-- Neural memory schema — migration 0004 (skills registry + load audit)
-- Applied automatically by `simplicio memory init` / ensure_memory_store after 0003.
-- Purpose: make "all skills always loaded" auditable — a registry of every skill
-- seeded into memory plus an append-only load-event log. Pure additive, idempotent.

-- Registry of every skill known to the project (code/video/content/orchestration).
-- Rows are upserted by the skill ingestor / memory init; the memory_items rows
-- (kind=project_skill) remain the retrievable content, this table is the index.
CREATE TABLE IF NOT EXISTS skills_registry (
  skill_name     TEXT    NOT NULL PRIMARY KEY,     -- canonical skill name
  stable_id      TEXT    NOT NULL UNIQUE,          -- skill:{repo}:{name} (memory_items key)
  domain         TEXT    NOT NULL DEFAULT 'coding',-- coding|video|content|orchestration
  load_strategy  TEXT    NOT NULL DEFAULT 'on_demand'
                   CHECK(load_strategy IN ('eager','lazy','on_demand','preload')),
  artifact_path  TEXT,                             -- relative path to SKILL.md
  enabled        INTEGER NOT NULL DEFAULT 1,
  metadata       TEXT,                             -- JSON, extensible
  created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_skills_registry_domain ON skills_registry(domain);

-- Append-only audit of skill load/seed events (when a skill entered memory).
CREATE TABLE IF NOT EXISTS skill_load_events (
  id             INTEGER PRIMARY KEY,
  skill_name     TEXT    NOT NULL,
  event          TEXT    NOT NULL DEFAULT 'seeded',-- seeded|loaded|skipped|error
  detail         TEXT,
  created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_skill_load_events_name ON skill_load_events(skill_name);

INSERT OR IGNORE INTO schema_migrations(id) VALUES ('0004_skills_registry');
