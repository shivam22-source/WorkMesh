-- ============================================================================
-- V001__canonical_schema.sql
-- Employee Knowledge RAG Canonical PostgreSQL Schema (Phase 1)
-- ============================================================================

-- Ensure pgvector extension is available
CREATE EXTENSION IF NOT EXISTS vector;

-- ----------------------------------------------------------------------------
-- 1. Identity & Access Control: Users, Groups, and Memberships
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(64) NOT NULL DEFAULT 'ENGINEER',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS groups (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_group_membership (
    user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id VARCHAR(64) NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_ugm_user_id ON user_group_membership(user_id);
CREATE INDEX IF NOT EXISTS idx_ugm_group_id ON user_group_membership(group_id);

-- ----------------------------------------------------------------------------
-- 2. Raw Source Ingestion: Source Records
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS source_records (
    id VARCHAR(128) PRIMARY KEY,
    source_type VARCHAR(32) NOT NULL,
    source_id VARCHAR(255) NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT,
    author_id VARCHAR(255),
    raw_content TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_source_type_source_id UNIQUE (source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_source_records_type ON source_records(source_type);

-- ----------------------------------------------------------------------------
-- 3. Canonical Knowledge Model: Documents and Chunks
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS documents (
    id VARCHAR(128) PRIMARY KEY,
    source_record_id VARCHAR(128) NOT NULL REFERENCES source_records(id) ON DELETE CASCADE,
    source_type VARCHAR(32) NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    author VARCHAR(255),
    url TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_source_record ON documents(source_record_id);
CREATE INDEX IF NOT EXISTS idx_documents_source_type ON documents(source_type);

CREATE TABLE IF NOT EXISTS chunks (
    id VARCHAR(128) PRIMARY KEY,
    document_id VARCHAR(128) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    token_count INT,
    embedding vector(1536),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_document_chunk_index UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING GIN(tsv);

-- ----------------------------------------------------------------------------
-- 4. Access Control List (ACL) References
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS acl_references (
    id BIGSERIAL PRIMARY KEY,
    resource_type VARCHAR(32) NOT NULL,
    resource_id VARCHAR(128) NOT NULL,
    principal_type VARCHAR(32) NOT NULL,
    principal_id VARCHAR(64) NOT NULL,
    permission VARCHAR(32) NOT NULL DEFAULT 'READ',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_acl_resource_principal UNIQUE (resource_type, resource_id, principal_type, principal_id, permission)
);

CREATE INDEX IF NOT EXISTS idx_acl_resource ON acl_references(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_acl_principal ON acl_references(principal_type, principal_id);

-- ----------------------------------------------------------------------------
-- 5. Synchronization State
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sync_state (
    source_type VARCHAR(32) PRIMARY KEY,
    cursor_value TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'IDLE',
    last_sync_started_at TIMESTAMPTZ,
    last_sync_completed_at TIMESTAMPTZ,
    records_synced_last_run INT NOT NULL DEFAULT 0,
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 6. Audit Trail
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    action VARCHAR(64) NOT NULL,
    resource VARCHAR(255),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address VARCHAR(45),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_events(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action);

-- ----------------------------------------------------------------------------
-- 7. Knowledge Graph / Relationship Layer (AD-03)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS entities (
    id VARCHAR(128) PRIMARY KEY,
    entity_type VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    source_record_id VARCHAR(128) REFERENCES source_records(id) ON DELETE SET NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

CREATE TABLE IF NOT EXISTS relationships (
    id BIGSERIAL PRIMARY KEY,
    source_entity_id VARCHAR(128) NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id VARCHAR(128) NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relationship_type VARCHAR(64) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_entity_relationship UNIQUE (source_entity_id, target_entity_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(relationship_type);

-- ----------------------------------------------------------------------------
-- 8. Seed Default Local Dev Data
-- ----------------------------------------------------------------------------

INSERT INTO users (id, email, full_name, role)
VALUES 
    ('employee_42', 'employee_42@company.internal', 'Alex Engineer', 'ENGINEER'),
    ('employee_admin', 'admin@company.internal', 'Sam Admin', 'ADMIN')
ON CONFLICT (id) DO NOTHING;

INSERT INTO groups (id, name, description)
VALUES 
    ('group_engineering', 'Engineering Team', 'All engineering personnel'),
    ('group_backend', 'Backend Core', 'Backend core service maintainers'),
    ('group_finance', 'Finance & Accounting', 'Restricted finance documents')
ON CONFLICT (id) DO NOTHING;

INSERT INTO user_group_membership (user_id, group_id)
VALUES 
    ('employee_42', 'group_engineering'),
    ('employee_42', 'group_backend'),
    ('employee_admin', 'group_engineering')
ON CONFLICT (user_id, group_id) DO NOTHING;

INSERT INTO sync_state (source_type, status, records_synced_last_run)
VALUES 
    ('GITHUB', 'IDLE', 0),
    ('SLACK', 'IDLE', 0),
    ('EMAIL', 'IDLE', 0)
ON CONFLICT (source_type) DO NOTHING;
