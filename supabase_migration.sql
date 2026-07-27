-- ====================================================================
-- MIGRATION: Supabase Schema — documents + jobs only
-- All richer artifacts (requirements, test_cases, scenarios,
-- traceability, coverage) are stored in MongoDB.
-- ====================================================================

-- 1. DROP ALL EXISTING TABLES (clean slate)
DROP TABLE IF EXISTS coverage_summaries  CASCADE;
DROP TABLE IF EXISTS traceability        CASCADE;
DROP TABLE IF EXISTS acceptance_criteria CASCADE;
DROP TABLE IF EXISTS scenarios           CASCADE;
DROP TABLE IF EXISTS test_cases          CASCADE;
DROP TABLE IF EXISTS requirements        CASCADE;
DROP TABLE IF EXISTS analysis_jobs       CASCADE;
DROP TABLE IF EXISTS jobs                CASCADE;
DROP TABLE IF EXISTS documents           CASCADE;

-- 2. UPDATED_AT TRIGGER FUNCTION
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3. CREATE TABLES

-- documents
--   Stores only the uploaded file's metadata + storage reference.
--   No parsed_status, no uploaded_by.
CREATE TABLE documents (
  id              uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id          text    UNIQUE NOT NULL,
  filename        text    NOT NULL,
  file_type       text,
  file_size_bytes int,
  storage_path    text    NOT NULL,
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);

CREATE TRIGGER set_updated_at_documents
BEFORE UPDATE ON documents
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- jobs
--   Tracks the lifecycle of one analysis run for a document.
CREATE TABLE jobs (
  id            text    PRIMARY KEY,
  document_id   uuid    REFERENCES documents(id) ON DELETE CASCADE,
  status        text    DEFAULT 'processing',
  error_message text,
  created_at    timestamptz DEFAULT now(),
  updated_at    timestamptz DEFAULT now(),
  completed_at  timestamptz
);

CREATE TRIGGER set_updated_at_jobs
BEFORE UPDATE ON jobs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
