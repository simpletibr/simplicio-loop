-- Neural memory schema — migration 0003 (expanded kinds + gates)
-- Adds user_profile, mapper-run, mapper-change, chat-note, action-log kinds.
-- Adds action_gate_state and chat_checkpoints tables.
-- Applied automatically by `simplicio memory init` after 0002.

-- ── Recreate memory_items without the restrictive CHECK constraint ────────────
-- SQLite cannot ALTER TABLE to modify a CHECK constraint.
-- This migration recreates the table with an open `kind` column and
-- application-level validation.
PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS memory_items_v3 (
  id             INTEGER PRIMARY KEY,
  stable_id      TEXT    NOT NULL UNIQUE,
  kind           TEXT    NOT NULL,
  source         TEXT    NOT NULL,
  title          TEXT    NOT NULL,
  content        TEXT    NOT NULL,
  artifact_path  TEXT,
  source_hash    TEXT,
  metadata       TEXT,
  provenance     TEXT,
  tags           TEXT    NOT NULL DEFAULT '',
  weight         REAL    NOT NULL DEFAULT 1.0,
  created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO memory_items_v3
  SELECT id,stable_id,kind,source,title,content,artifact_path,
         source_hash,metadata,provenance,tags,weight,created_at,updated_at
  FROM memory_items;

DROP TABLE IF EXISTS memory_items_fts;
DROP TABLE IF EXISTS memory_items;

ALTER TABLE memory_items_v3 RENAME TO memory_items;

-- Recreate FTS5 virtual table
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

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_memory_items_kind        ON memory_items(kind);
CREATE INDEX IF NOT EXISTS idx_memory_items_source_hash ON memory_items(source_hash);
CREATE INDEX IF NOT EXISTS idx_memory_items_updated_at  ON memory_items(updated_at);

PRAGMA foreign_keys=ON;

-- ── Action gate state ─────────────────────────────────────────────────────────
-- Persists the current gate mode (ask/auto/safe) and allowlist/blocklist.
CREATE TABLE IF NOT EXISTS action_gate_state (
  id          INTEGER PRIMARY KEY,
  repo        TEXT    NOT NULL,
  mode        TEXT    NOT NULL DEFAULT 'ask' CHECK(mode IN ('ask','auto','safe')),
  allowlist   TEXT    NOT NULL DEFAULT '',   -- comma-separated action kinds
  blocklist   TEXT    NOT NULL DEFAULT '',   -- comma-separated action kinds
  updated_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(repo)
);

-- ── Chat checkpoints ──────────────────────────────────────────────────────────
-- Each row is a reversible snapshot (git stash ref + metadata).
CREATE TABLE IF NOT EXISTS chat_checkpoints (
  id           INTEGER PRIMARY KEY,
  checkpoint_id TEXT   NOT NULL UNIQUE,
  repo         TEXT    NOT NULL,
  description  TEXT    NOT NULL DEFAULT '',
  stash_ref    TEXT    NOT NULL DEFAULT '',
  git_head     TEXT    NOT NULL DEFAULT '',
  files_changed TEXT   NOT NULL DEFAULT '',
  restored     INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_checkpoints_repo
  ON chat_checkpoints(repo, created_at);

-- ── Action trajectory ─────────────────────────────────────────────────────────
-- Append-only log of every action taken during a chat session.
CREATE TABLE IF NOT EXISTS action_trajectory (
  id           INTEGER PRIMARY KEY,
  session_id   TEXT    NOT NULL,
  repo         TEXT    NOT NULL,
  action_kind  TEXT    NOT NULL,
  description  TEXT    NOT NULL,
  args_json    TEXT    NOT NULL DEFAULT '{}',
  result_json  TEXT    NOT NULL DEFAULT '{}',
  checkpoint_id TEXT,
  created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_action_trajectory_session
  ON action_trajectory(session_id, created_at);

-- ── Memory items archived (soft-delete for forget) ────────────────────────────
CREATE TABLE IF NOT EXISTS memory_items_archived (
  id             INTEGER PRIMARY KEY,
  original_id    INTEGER NOT NULL,
  stable_id      TEXT    NOT NULL,
  kind           TEXT    NOT NULL,
  source         TEXT    NOT NULL,
  title          TEXT    NOT NULL,
  content        TEXT    NOT NULL,
  source_hash    TEXT,
  tags           TEXT    NOT NULL DEFAULT '',
  archived_by    TEXT    NOT NULL DEFAULT 'memory-forget',
  archived_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_archived_stable
  ON memory_items_archived(stable_id);

INSERT OR IGNORE INTO schema_migrations(id) VALUES('0003_expanded_kinds_and_gates');
