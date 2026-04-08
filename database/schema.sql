-- ============================================================
-- Multi-Agent System: AlloyDB Schema
-- Extensions: pgvector + google_ml_integration (AlloyDB AI)
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS google_ml_integration CASCADE;
CREATE EXTENSION IF NOT EXISTS vector;

-- ────────────────────────────────────────────────────────────
-- TASKS
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    task_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       TEXT NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','in_progress','done','cancelled')),
    priority      TEXT NOT NULL DEFAULT 'medium'
                    CHECK (priority IN ('low','medium','high','critical')),
    due_date      TIMESTAMP,
    tags          TEXT[],
    metadata      JSONB DEFAULT '{}',
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_id  ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);

-- ────────────────────────────────────────────────────────────
-- EVENTS / CALENDAR
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    event_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       TEXT NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT,
    start_time    TIMESTAMP NOT NULL,
    end_time      TIMESTAMP NOT NULL,
    location      TEXT,
    attendees     TEXT[],
    linked_task_id UUID REFERENCES tasks(task_id) ON DELETE SET NULL,
    metadata      JSONB DEFAULT '{}',
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_user_id    ON events(user_id);
CREATE INDEX IF NOT EXISTS idx_events_start_time ON events(start_time);

-- ────────────────────────────────────────────────────────────
-- NOTES / KNOWLEDGE BASE  (AlloyDB AI embeddings)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notes (
    note_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       TEXT NOT NULL,
    title         TEXT NOT NULL,
    content       TEXT NOT NULL,
    tags          TEXT[],
    -- 768-dim: MUST match text-embedding-005
    content_vector VECTOR(768),
    metadata      JSONB DEFAULT '{}',
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

-- ScaNN vector index (AlloyDB AI — higher recall than HNSW)
CREATE INDEX IF NOT EXISTS idx_notes_vector
    ON notes USING scann (content_vector cosine);

CREATE INDEX IF NOT EXISTS idx_notes_user_id ON notes(user_id);

-- Grant embedding function to postgres user
GRANT EXECUTE ON FUNCTION embedding TO postgres;

-- ────────────────────────────────────────────────────────────
-- INTERACTION HISTORY  (short + long-term memory)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS interactions (
    interaction_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      TEXT NOT NULL,           -- short-term: groups a session
    user_id         TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content         TEXT NOT NULL,
    tool_calls      JSONB DEFAULT '[]',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interactions_session ON interactions(session_id);
CREATE INDEX IF NOT EXISTS idx_interactions_user    ON interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_interactions_created ON interactions(created_at DESC);

-- ────────────────────────────────────────────────────────────
-- WORKFLOWS  (execution audit log)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflows (
    workflow_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       TEXT NOT NULL,
    name          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','completed','failed','retrying')),
    steps         JSONB DEFAULT '[]',        -- [{name, status, result, error}]
    result        JSONB,
    error         TEXT,
    started_at    TIMESTAMP DEFAULT NOW(),
    finished_at   TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_workflows_user_id ON workflows(user_id);
CREATE INDEX IF NOT EXISTS idx_workflows_status  ON workflows(status);

-- ────────────────────────────────────────────────────────────
-- Register Gemini 2.5 Flash model for in-database AI calls
-- (run AFTER AlloyDB IAM binding is applied)
-- ────────────────────────────────────────────────────────────
/*
CALL google_ml.create_model(
    model_id => 'gemini-2.5-flash',
    model_request_url => 'https://aiplatform.googleapis.com/v1/projects/<PROJECT_ID>/locations/global/publishers/google/models/gemini-2.5-flash:generateContent',
    model_qualified_name => 'gemini-2.5-flash',
    model_provider => 'google',
    model_type => 'llm',
    model_auth_type => 'alloydb_service_agent_iam'
);
*/
