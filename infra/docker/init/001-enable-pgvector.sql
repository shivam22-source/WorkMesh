-- Runs once, on first initialisation of an empty Postgres data volume.
-- Phase 0 only enables the vector extension. The application schema
-- (users, documents, chunks, acl refs, sync state, audit) is Phase 1
-- and lives in infra/migrations as versioned Flyway migrations.

CREATE EXTENSION IF NOT EXISTS vector;
