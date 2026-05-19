-- =============================================================
-- QAptain — Supabase module memory setup
-- Run this once in your Supabase SQL Editor (Dashboard → SQL).
-- Replaces the ChromaDB semantic memory with PostgreSQL FTS.
-- =============================================================

-- 1. Table for module memory documents
CREATE TABLE IF NOT EXISTS module_memories (
  id         UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  workspace_id TEXT      NOT NULL,
  module_id    TEXT      NOT NULL UNIQUE,
  content      TEXT      NOT NULL,
  metadata     JSONB     DEFAULT '{}',
  fts          tsvector  GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
  created_at   TIMESTAMPTZ DEFAULT now()
);

-- 2. Indexes
CREATE INDEX IF NOT EXISTS idx_module_memories_fts
  ON module_memories USING GIN (fts);

CREATE INDEX IF NOT EXISTS idx_module_memories_workspace
  ON module_memories (workspace_id);

-- 3. Full-text search RPC function (called from supabase-memory.ts)
CREATE OR REPLACE FUNCTION match_module_memories(
  p_workspace_id TEXT,
  p_query        TEXT,
  p_limit        INT DEFAULT 6
)
RETURNS TABLE (
  id           UUID,
  workspace_id TEXT,
  module_id    TEXT,
  content      TEXT,
  metadata     JSONB,
  rank         REAL
)
LANGUAGE sql STABLE
AS $$
  SELECT
    m.id,
    m.workspace_id,
    m.module_id,
    m.content,
    m.metadata,
    ts_rank(m.fts, plainto_tsquery('english', p_query)) AS rank
  FROM module_memories m
  WHERE m.workspace_id = p_workspace_id
    AND (
      m.fts @@ plainto_tsquery('english', p_query)
      OR m.content ILIKE '%' || p_query || '%'
    )
  ORDER BY rank DESC
  LIMIT p_limit;
$$;

-- 4. Disable RLS so the publishable key can read/write without policies.
--    If you switch to using SUPABASE_SERVICE_ROLE_KEY, you can enable RLS
--    and add policies instead.
ALTER TABLE module_memories ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all for service role" ON module_memories
  FOR ALL USING (true) WITH CHECK (true);
