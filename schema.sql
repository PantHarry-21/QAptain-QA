-- QAptain Database Schema (v3 - Corrected for NextAuth)
-- This script safely creates tables and adds missing columns to existing tables.

-- Enable UUID generation functionality
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Custom Types for status fields
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'test_status') THEN
        CREATE TYPE test_status AS ENUM ('pending', 'running', 'completed', 'failed');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'scenario_status') THEN
        CREATE TYPE scenario_status AS ENUM ('pending', 'running', 'passed', 'failed');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'log_level') THEN
        CREATE TYPE log_level AS ENUM ('info', 'success', 'error', 'warning');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'risk_level') THEN
        CREATE TYPE risk_level AS ENUM ('low', 'medium', 'high');
    END IF;
END$$;

--
-- Application-specific tables
--

-- 1. test_sessions Table
CREATE TABLE IF NOT EXISTS test_sessions (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS user_id TEXT; -- Corrected for users.id FK
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS url TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS status test_status DEFAULT 'pending';
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS total_scenarios INTEGER;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS passed_scenarios INTEGER;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS failed_scenarios INTEGER;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS total_steps INTEGER;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS passed_steps INTEGER;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS failed_steps INTEGER;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS duration BIGINT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS page_analysis JSONB;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS ai_analysis JSONB;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS selected_scenario_ids JSONB;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS video_url TEXT;

-- 2. test_scenarios Table
CREATE TABLE IF NOT EXISTS test_scenarios (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE test_scenarios ADD COLUMN IF NOT EXISTS session_id uuid REFERENCES test_sessions(id) ON DELETE CASCADE;
ALTER TABLE test_scenarios ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE test_scenarios ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE test_scenarios ADD COLUMN IF NOT EXISTS steps TEXT[];
ALTER TABLE test_scenarios ADD COLUMN IF NOT EXISTS status scenario_status DEFAULT 'pending';
ALTER TABLE test_scenarios ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE test_scenarios ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE test_scenarios ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE test_scenarios ADD COLUMN IF NOT EXISTS duration BIGINT;
ALTER TABLE test_scenarios ADD COLUMN IF NOT EXISTS error_message TEXT;

-- 3. test_steps Table
CREATE TABLE IF NOT EXISTS test_steps (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE test_steps ADD COLUMN IF NOT EXISTS scenario_id uuid REFERENCES test_scenarios(id) ON DELETE CASCADE;
ALTER TABLE test_steps ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE test_steps ADD COLUMN IF NOT EXISTS "order" INTEGER;
ALTER TABLE test_steps ADD COLUMN IF NOT EXISTS status scenario_status DEFAULT 'pending';
ALTER TABLE test_steps ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE test_steps ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE test_steps ADD COLUMN IF NOT EXISTS duration BIGINT;
ALTER TABLE test_steps ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE test_steps ADD COLUMN IF NOT EXISTS screenshot_url TEXT;
ALTER TABLE test_steps ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- 4. test_logs Table
CREATE TABLE IF NOT EXISTS test_logs (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE test_logs ADD COLUMN IF NOT EXISTS session_id uuid REFERENCES test_sessions(id) ON DELETE CASCADE;
ALTER TABLE test_logs ADD COLUMN IF NOT EXISTS scenario_id uuid;
ALTER TABLE test_logs ADD COLUMN IF NOT EXISTS step_id uuid;
ALTER TABLE test_logs ADD COLUMN IF NOT EXISTS level log_level;
ALTER TABLE test_logs ADD COLUMN IF NOT EXISTS message TEXT;
ALTER TABLE test_logs ADD COLUMN IF NOT EXISTS "timestamp" TIMESTAMPTZ DEFAULT now();
ALTER TABLE test_logs ADD COLUMN IF NOT EXISTS metadata JSONB;

-- 5. test_reports Table
CREATE TABLE IF NOT EXISTS test_reports (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE test_reports ADD COLUMN IF NOT EXISTS session_id uuid UNIQUE REFERENCES test_sessions(id) ON DELETE CASCADE;
ALTER TABLE test_reports ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE test_reports ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE test_reports ADD COLUMN IF NOT EXISTS key_findings TEXT[];
ALTER TABLE test_reports ADD COLUMN IF NOT EXISTS recommendations TEXT[];
ALTER TABLE test_reports ADD COLUMN IF NOT EXISTS risk_level risk_level;
ALTER TABLE test_reports ADD COLUMN IF NOT EXISTS risk_assessment_issues TEXT[];
ALTER TABLE test_reports ADD COLUMN IF NOT EXISTS performance_metrics JSONB;
ALTER TABLE test_reports ADD COLUMN IF NOT EXISTS quality_score INTEGER;
ALTER TABLE test_reports ADD COLUMN IF NOT EXISTS pdf_url TEXT;
ALTER TABLE test_reports ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- 6. scenario_reports Table
CREATE TABLE IF NOT EXISTS scenario_reports (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE scenario_reports ADD COLUMN IF NOT EXISTS session_id uuid REFERENCES test_sessions(id) ON DELETE CASCADE;
ALTER TABLE scenario_reports ADD COLUMN IF NOT EXISTS scenario_id uuid UNIQUE REFERENCES test_scenarios(id) ON DELETE CASCADE;
ALTER TABLE scenario_reports ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE scenario_reports ADD COLUMN IF NOT EXISTS issues TEXT[];
ALTER TABLE scenario_reports ADD COLUMN IF NOT EXISTS recommendations TEXT[];

-- 7. saved_scenarios Table
CREATE TABLE IF NOT EXISTS saved_scenarios (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE saved_scenarios ADD COLUMN IF NOT EXISTS user_id TEXT; -- Corrected for users.id FK
ALTER TABLE saved_scenarios ADD COLUMN IF NOT EXISTS url TEXT;
ALTER TABLE saved_scenarios ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE saved_scenarios ADD COLUMN IF NOT EXISTS user_story TEXT;
ALTER TABLE saved_scenarios ADD COLUMN IF NOT EXISTS steps TEXT[];

--
-- NEXTAUTH.JS CORRECTED SCHEMA
--

-- 8. users Table
CREATE TABLE IF NOT EXISTS users (
    id TEXT NOT NULL PRIMARY KEY,
    first_name TEXT,
    last_name TEXT,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    email_verified TIMESTAMPTZ,
    activation_token TEXT,
    image TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 9. accounts Table
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT NOT NULL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  provider TEXT NOT NULL,
  provider_account_id TEXT NOT NULL,
  refresh_token TEXT,
  access_token TEXT,
  expires_at BIGINT,
  token_type TEXT,
  scope TEXT,
  id_token TEXT,
  session_state TEXT,
  UNIQUE (provider, provider_account_id)
);

-- 10. sessions Table
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT NOT NULL PRIMARY KEY,
  session_token TEXT NOT NULL UNIQUE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires TIMESTAMPTZ NOT NULL
);

-- 11. verification_tokens Table
CREATE TABLE IF NOT EXISTS verification_tokens (
  identifier TEXT NOT NULL,
  token TEXT NOT NULL,
  expires TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (identifier, token)
);

--
-- INDEXES
--
CREATE INDEX IF NOT EXISTS idx_test_sessions_user_id ON test_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_test_scenarios_session_id ON test_scenarios(session_id);
CREATE INDEX IF NOT EXISTS idx_test_steps_scenario_id ON test_steps(scenario_id);
CREATE INDEX IF NOT EXISTS idx_test_logs_session_id ON test_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_saved_scenarios_url ON saved_scenarios(url);
CREATE INDEX IF NOT EXISTS idx_saved_scenarios_user_id ON saved_scenarios(user_id);