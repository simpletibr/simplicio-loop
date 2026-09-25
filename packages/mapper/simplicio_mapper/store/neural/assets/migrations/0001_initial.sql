-- Neural memory schema — migration 0001 (initial)
-- Applied automatically by `simplicio memory init`.
-- Source of truth for the SQLite schema; embedded in the binary via include_str!.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ── Schema version tracking ─────────────────────────────────────────────────
-- Stores applied migration IDs so future migrations can be applied
-- incrementally without re-running past ones.

CREATE TABLE IF NOT EXISTS schema_migrations (
  id TEXT PRIMARY KEY,            -- e.g. "0001_initial"
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ── memory_items ─────────────────────────────────────────────────────────────
-- Central store for all memory chunks: code, commits, skills, decisions,
-- issues, and conversation turns.
--
-- item_type values (stored in `kind` column):
--   code         — source file / symbol extracted from project-map.json
--   commit       — git commit metadata and message
--   skill        — SKILL.md definition from the skills/ directory
--   decision     — architecture / ADR document from docs/
--   issue        — GitHub issue body and metadata
--   conversation — persisted agent chat turn (also in neural_sessions)
--
-- provenance (JSON): de onde o item veio; estrutura livre mas recomendada:
--   { "source": "git" | "fs" | "github" | "chat",
--     "ref":    <commit sha | file path | issue url | session_id>,
--     "ingest_run": <unix timestamp> }
--
-- metadata (JSON): atributos extras por tipo; estrutura livre.

CREATE TABLE IF NOT EXISTS memory_items (
  id             INTEGER PRIMARY KEY,
  stable_id      TEXT    NOT NULL UNIQUE,         -- deterministic dedup key
  kind           TEXT    NOT NULL                  -- see item_type values above
                   CHECK(kind IN (
                     'code','commit','skill','decision','issue','conversation',
                     'run','evidence','note','chat-note','user_profile',
                     'user-profile','trajectory','semantic','episodic',
                     'pattern','fact'
                   )),
  source         TEXT    NOT NULL,                 -- human-readable origin label
  title          TEXT    NOT NULL,
  content        TEXT    NOT NULL,
  artifact_path  TEXT,                             -- fs path for file-backed items
  source_hash    TEXT,                             -- sha256 of original bytes
  metadata       TEXT,                             -- JSON — extensible per kind
  provenance     TEXT,                             -- JSON — see header comment
  tags           TEXT    NOT NULL DEFAULT '',
  weight         REAL    NOT NULL DEFAULT 1.0,     -- retrieval priority boost
  created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ── FTS5 full-text index ──────────────────────────────────────────────────────
CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts
USING fts5(title, content, source, tags,
           content='memory_items', content_rowid='id');

CREATE TRIGGER IF NOT EXISTS memory_items_ai AFTER INSERT ON memory_items BEGIN
  INSERT INTO memory_items_fts(rowid, title, content, source, tags)
  VALUES (new.id, new.title, new.content, new.source, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS memory_items_ad AFTER DELETE ON memory_items BEGIN
  INSERT INTO memory_items_fts(memory_items_fts, rowid, title, content, source, tags)
  VALUES ('delete', old.id, old.title, old.content, old.source, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS memory_items_au AFTER UPDATE ON memory_items BEGIN
  INSERT INTO memory_items_fts(memory_items_fts, rowid, title, content, source, tags)
  VALUES ('delete', old.id, old.title, old.content, old.source, old.tags);
  INSERT INTO memory_items_fts(rowid, title, content, source, tags)
  VALUES (new.id, new.title, new.content, new.source, new.tags);
END;

-- ── memory_vectors ────────────────────────────────────────────────────────────
-- Embedding storage. One row per (item, chunk, model) triple.
-- embedding BLOB: raw float32 vector, little-endian, length = dimensions × 4.
-- When sqlite-vec is available, a vec0 virtual table is created on top of this
-- via `simplicio memory enable-vec` (see LOCAL_MEMORY.md).

CREATE TABLE IF NOT EXISTS memory_vectors (
  item_id         INTEGER NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
  chunk_id        TEXT    NOT NULL,                -- sub-item chunk identifier
  embedding_model TEXT    NOT NULL,                -- e.g. "all-MiniLM-L6-v2"
  dimensions      INTEGER NOT NULL,
  embedding       BLOB,                            -- float32 LE array
  backend         TEXT    NOT NULL DEFAULT 'sqlite-vec',
  created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (item_id, chunk_id, embedding_model)
);

-- ── memory_relationships ──────────────────────────────────────────────────────
-- Typed directed edges between memory items.
--
-- relation_type values (open vocabulary; recommended values):
--   generated_by   — item was produced by another (e.g. skill → commit)
--   references     — item mentions / links to another
--   caused_change  — commit / decision caused a code change
--   implements     — code item implements a decision or issue
--   supersedes     — newer item replaces an older one
--   related_to     — generic weak association

CREATE TABLE IF NOT EXISTS memory_relationships (
  id           INTEGER PRIMARY KEY,
  from_item_id INTEGER NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
  to_item_id   INTEGER NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
  relation_type TEXT   NOT NULL,
  metadata     TEXT,                               -- JSON — extra edge attributes
  created_at   TEXT   NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(from_item_id, to_item_id, relation_type)  -- no duplicate edges
);

-- ── memory_queries ────────────────────────────────────────────────────────────
-- Audit log for retrieval calls — used for latency monitoring and
-- query-driven memory weight tuning.

CREATE TABLE IF NOT EXISTS memory_queries (
  id           INTEGER PRIMARY KEY,
  query        TEXT    NOT NULL,
  backend      TEXT    NOT NULL,
  result_count INTEGER NOT NULL DEFAULT 0,
  latency_ms   INTEGER,
  created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ── neural_sessions ───────────────────────────────────────────────────────────
-- Persisted conversation turns for cross-session recall.

CREATE TABLE IF NOT EXISTS neural_sessions (
  id                  INTEGER PRIMARY KEY,
  session_id          TEXT NOT NULL,
  role                TEXT NOT NULL CHECK(role IN ('user','assistant')),
  content             TEXT NOT NULL,
  context_items_used  INTEGER NOT NULL DEFAULT 0,
  created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_memory_items_kind
  ON memory_items(kind);

CREATE INDEX IF NOT EXISTS idx_memory_items_source_hash
  ON memory_items(source_hash);

CREATE INDEX IF NOT EXISTS idx_memory_items_updated_at
  ON memory_items(updated_at);

CREATE INDEX IF NOT EXISTS idx_memory_vectors_model
  ON memory_vectors(embedding_model);

CREATE INDEX IF NOT EXISTS idx_memory_relationships_from
  ON memory_relationships(from_item_id);

CREATE INDEX IF NOT EXISTS idx_memory_relationships_to
  ON memory_relationships(to_item_id);

CREATE INDEX IF NOT EXISTS idx_memory_relationships_type
  ON memory_relationships(relation_type);

CREATE INDEX IF NOT EXISTS idx_neural_sessions_session
  ON neural_sessions(session_id, created_at);

-- ── sqlite-vec phase (optional) ───────────────────────────────────────────────
-- Load the sqlite-vec extension via SIMPLICIO_SQLITE_VEC_PATH / SQLITE_VEC_PATH
-- and run `simplicio memory enable-vec` to create the vec0 virtual table on top
-- of memory_vectors.embedding. See docs/LOCAL_MEMORY.md for details.

-- ── Upgrade path for pre-migration DBs ────────────────────────────────────────
-- These ALTER TABLE statements are no-ops on a fresh DB (columns exist from
-- CREATE TABLE above). On a DB created before this migration system, they add
-- the new columns. `IF NOT EXISTS` (SQLite 3.35+, 2021) makes this a true
-- no-op instead of relying on the sqlite3 CLI's continue-past-errors
-- behavior — that assumption doesn't hold for every sqlite3 build (observed
-- on Windows: `.read` exits 1 on "duplicate column name", which `simplicio
-- memory init` then surfaces as a command failure even though the schema
-- ends up correct either way).
ALTER TABLE memory_items ADD COLUMN metadata   TEXT;
ALTER TABLE memory_items ADD COLUMN provenance TEXT;

-- ── Record this migration as applied ──────────────────────────────────────────
INSERT OR IGNORE INTO schema_migrations(id) VALUES('0001_initial');
