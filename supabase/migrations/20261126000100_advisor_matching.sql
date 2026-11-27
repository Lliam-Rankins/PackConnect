-- Advisor matching: weighted full-text vector + per-field profile embeddings.
--
-- pgvector lives in the "extensions" schema (Supabase convention), which is NOT on
-- the connection search_path ("<test schema>, public" in backend/database.py), so
-- always schema-qualify. Query idiom:
--     embedding::extensions.vector            -- cast a '[0.1,0.2,...]' literal
--     %s::extensions.vector
--     1 - (pe.embedding OPERATOR(extensions.<=>) %s::extensions.vector)   -- cosine similarity
-- A field is embedded phrase by phrase: one row per (student, field, chunk); score a field by its best chunk.
-- Column type: extensions.vector(384).
BEGIN;
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

ALTER TABLE public.students ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(advice_topics, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(skills, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(interests, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(bio, '')), 'D')
    ) STORED;
CREATE INDEX IF NOT EXISTS students_search_vector ON public.students USING gin (search_vector);

-- embedding is NULL while pending or failed (a failed field keeps a single chunk-0 row); a field is stale when
-- any chunk's source_hash differs from the current text. All chunks of a field share the field's source_hash.
CREATE TABLE IF NOT EXISTS public.profile_embeddings (
    student_id bigint NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
    field text NOT NULL CHECK (field IN ('advice_topics', 'skills', 'interests', 'bio')),
    chunk smallint NOT NULL DEFAULT 0,  -- 0-based phrase index within the field
    embedding extensions.vector(384),
    model text NOT NULL,
    source_hash text NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    last_error_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, field, chunk)
);
ALTER TABLE public.profile_embeddings ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.profile_embeddings FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.profile_embeddings TO service_role;
NOTIFY pgrst, 'reload schema';
COMMIT;
