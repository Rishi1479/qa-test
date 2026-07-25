-- ====================================================================
-- MIGRATION: Supabase Schema Upgrade
-- ====================================================================

-- 1. DROP EXISTING TABLES (Safely removing deprecated structure)
-- Note: CASCADE is used to ensure dependent tables/foreign keys are also dropped.
DROP TABLE IF EXISTS coverage_summaries CASCADE;
DROP TABLE IF EXISTS traceability CASCADE;
DROP TABLE IF EXISTS acceptance_criteria CASCADE;
DROP TABLE IF EXISTS scenarios CASCADE;
DROP TABLE IF EXISTS test_cases CASCADE;
DROP TABLE IF EXISTS requirements CASCADE;
DROP TABLE IF EXISTS analysis_jobs CASCADE;
DROP TABLE IF EXISTS jobs CASCADE;
DROP TABLE IF EXISTS documents CASCADE;

-- 2. CREATE `updated_at` TRIGGER FUNCTION
CREATE OR REPLACE FUNCTION set_updated_at() 
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3. CREATE NEW TABLES

-- documents
CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id text UNIQUE NOT NULL,
  filename text NOT NULL,
  file_type text,
  file_size_bytes int,
  storage_path text NOT NULL,
  uploaded_by uuid, -- (Nullable, references auth.users or profiles if available)
  parsed_status text DEFAULT 'pending',
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

-- trigger for documents
CREATE TRIGGER set_updated_at_documents
BEFORE UPDATE ON documents
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- jobs
CREATE TABLE jobs (
  id text PRIMARY KEY,
  document_id uuid REFERENCES documents(id) ON DELETE CASCADE,
  status text DEFAULT 'processing',
  error_message text,
  langsmith_trace_id text,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now(),
  completed_at timestamptz
);

-- trigger for jobs
CREATE TRIGGER set_updated_at_jobs
BEFORE UPDATE ON jobs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- requirements
CREATE TABLE requirements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id text REFERENCES jobs(id) ON DELETE CASCADE,
  req_code text,
  title text,
  raw_text text,
  requirement_type text,
  priority text,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

-- trigger for requirements
CREATE TRIGGER set_updated_at_requirements
BEFORE UPDATE ON requirements
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- test_cases
CREATE TABLE test_cases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  requirement_id uuid REFERENCES requirements(id) ON DELETE CASCADE,
  type text,
  title text,
  preconditions text,
  postconditions text,
  steps jsonb,
  expected_result text,
  test_data jsonb,
  llm_raw_response jsonb,
  langsmith_run_id text,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now(),
  completed_at timestamptz
);

-- trigger for test_cases
CREATE TRIGGER set_updated_at_test_cases
BEFORE UPDATE ON test_cases
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
