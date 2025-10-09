-- QAptain Database Schema (v2 - Robust & Idempotent)
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

-- 1. test_sessions Table
CREATE TABLE IF NOT EXISTS test_sessions (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS user_id uuid;
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
ALTER TABLE saved_scenarios ADD COLUMN IF NOT EXISTS user_id uuid;
ALTER TABLE saved_scenarios ADD COLUMN IF NOT EXISTS url TEXT;
ALTER TABLE saved_scenarios ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE saved_scenarios ADD COLUMN IF NOT EXISTS user_story TEXT;
ALTER TABLE saved_scenarios ADD COLUMN IF NOT EXISTS steps TEXT[];

-- Add Indexes for performance
CREATE INDEX IF NOT EXISTS idx_test_sessions_user_id ON test_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_test_scenarios_session_id ON test_scenarios(session_id);
CREATE INDEX IF NOT EXISTS idx_test_steps_scenario_id ON test_steps(scenario_id);
CREATE INDEX IF NOT EXISTS idx_test_logs_session_id ON test_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_saved_scenarios_url ON saved_scenarios(url);
CREATE INDEX IF NOT EXISTS idx_saved_scenarios_user_id ON saved_scenarios(user_id);

-- Comments to explain the schema
COMMENT ON TABLE test_sessions IS 'Stores high-level information about each test run.';
COMMENT ON TABLE test_scenarios IS 'Stores the individual scenarios that are part of a test session.';
COMMENT ON TABLE test_steps IS 'Stores the granular steps within each test scenario (currently not in use but good for future expansion).';
COMMENT ON TABLE test_logs IS 'Aggregates all logs (info, errors, screenshots) for a given test session.';
COMMENT ON TABLE test_reports IS 'Stores the final AI-generated analysis for a completed test session.';
COMMENT ON TABLE scenario_reports IS 'Stores AI-generated analysis for each individual scenario.';
COMMENT ON TABLE saved_scenarios IS 'Stores reusable test scenarios created by users.';