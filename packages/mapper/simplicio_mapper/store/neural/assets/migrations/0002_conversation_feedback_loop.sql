-- Neural memory schema — migration 0002 (conversation feedback loop)
-- Applied automatically by `simplicio memory init` after 0001.
-- Adds structured conversation chunking, provenance linking, and
-- decision/action_item extraction tables (issue #169).

-- ── Structured conversation chunks ──────────────────────────────────────────
-- One row per Q&A turn with quality metadata, language detection, and summary.
CREATE TABLE IF NOT EXISTS conversation_chunks (
  id                 INTEGER PRIMARY KEY,
  session_id         TEXT NOT NULL,
  chunk_index        INTEGER NOT NULL DEFAULT 0,
  question           TEXT NOT NULL,
  answer             TEXT NOT NULL,
  language           TEXT NOT NULL DEFAULT 'en',
  context_items_used INTEGER NOT NULL DEFAULT 0,
  quality_score      REAL NOT NULL DEFAULT 0.5,
  summary            TEXT,
  created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(session_id, chunk_index)
);

-- ── Provenance links ─────────────────────────────────────────────────────────
-- Links each conversation chunk to the memory_items it used as context.
-- memory_item_stable_id references memory_items.stable_id (not a FK to avoid
-- cross-migration coupling; enforced by application logic).
CREATE TABLE IF NOT EXISTS conversation_links (
  id                    INTEGER PRIMARY KEY,
  session_id            TEXT NOT NULL,
  chunk_index           INTEGER NOT NULL DEFAULT 0,
  memory_item_stable_id TEXT NOT NULL,
  relevance_rank        INTEGER NOT NULL DEFAULT 0,
  created_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ── Extracted decisions and action items ─────────────────────────────────────
-- Lines prefixed with Decision: / Action: / Insight: in agent answers
-- are extracted here. Decisions with promoted_to_memory=1 also appear
-- in memory_items(kind='decision').
CREATE TABLE IF NOT EXISTS conversation_extracts (
  id                 INTEGER PRIMARY KEY,
  session_id         TEXT NOT NULL,
  extract_kind       TEXT NOT NULL CHECK(extract_kind IN ('decision','action_item','insight')),
  content            TEXT NOT NULL,
  promoted_to_memory INTEGER NOT NULL DEFAULT 0,
  created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conv_chunks_session   ON conversation_chunks(session_id);
CREATE INDEX IF NOT EXISTS idx_conv_links_session    ON conversation_links(session_id);
CREATE INDEX IF NOT EXISTS idx_conv_extracts_session ON conversation_extracts(session_id);
CREATE INDEX IF NOT EXISTS idx_conv_extracts_kind    ON conversation_extracts(extract_kind);

-- ── Record this migration as applied ─────────────────────────────────────────
INSERT OR IGNORE INTO schema_migrations(id) VALUES('0002_conversation_feedback_loop');
