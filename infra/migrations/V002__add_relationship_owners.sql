-- ----------------------------------------------------------------------------
-- V002: Add relationship_owners table for multi-owner relationship provenance (AD-03 / Phase 5)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS relationship_owners (
    relationship_id BIGINT NOT NULL REFERENCES relationships(id) ON DELETE CASCADE,
    source_record_id VARCHAR(128) NOT NULL REFERENCES source_records(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (relationship_id, source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_rel_owners_source_record ON relationship_owners(source_record_id);
CREATE INDEX IF NOT EXISTS idx_rel_owners_relationship_id ON relationship_owners(relationship_id);

-- ----------------------------------------------------------------------------
-- Backfill Verified Relationship Ownership from Phase 4 Stored Evidence
-- ----------------------------------------------------------------------------

-- 1. TICKET -> PR: Verified via PR title, raw_content, or metadata->'ticket_ids'
INSERT INTO relationship_owners (relationship_id, source_record_id)
SELECT r.id, t.source_record_id
FROM relationships r
JOIN entities s ON r.source_entity_id = s.id AND s.entity_type = 'TICKET'
JOIN entities t ON r.target_entity_id = t.id AND t.entity_type = 'PULL_REQUEST'
JOIN source_records sr ON t.source_record_id = sr.id AND sr.source_type = 'GITHUB'
WHERE r.relationship_type = 'implemented_by'
  AND t.source_record_id IS NOT NULL
  AND (
      (sr.metadata ? 'ticket_ids' AND jsonb_typeof(sr.metadata->'ticket_ids') = 'array' AND sr.metadata->'ticket_ids' @> to_jsonb(s.name))
      OR (sr.raw_content ~* ('\m' || s.name || '\M') OR sr.title ~* ('\m' || s.name || '\M'))
  )
ON CONFLICT DO NOTHING;

-- 2. TICKET -> SLACK_THREAD: Verified via Slack raw_content or metadata->'ticket_ids'
INSERT INTO relationship_owners (relationship_id, source_record_id)
SELECT r.id, t.source_record_id
FROM relationships r
JOIN entities s ON r.source_entity_id = s.id AND s.entity_type = 'TICKET'
JOIN entities t ON r.target_entity_id = t.id AND t.entity_type = 'SLACK_THREAD'
JOIN source_records sr ON t.source_record_id = sr.id AND sr.source_type = 'SLACK'
WHERE r.relationship_type = 'discussed_in'
  AND t.source_record_id IS NOT NULL
  AND (
      (sr.metadata ? 'ticket_ids' AND jsonb_typeof(sr.metadata->'ticket_ids') = 'array' AND sr.metadata->'ticket_ids' @> to_jsonb(s.name))
      OR (sr.raw_content ~* ('\m' || s.name || '\M') OR sr.title ~* ('\m' || s.name || '\M'))
  )
ON CONFLICT DO NOTHING;

-- 3. COMMIT -> EMPLOYEE: Verified via commit author_id or metadata->'author'->>'login'
INSERT INTO relationship_owners (relationship_id, source_record_id)
SELECT r.id, s.source_record_id
FROM relationships r
JOIN entities s ON r.source_entity_id = s.id AND s.entity_type = 'COMMIT'
JOIN entities t ON r.target_entity_id = t.id AND t.entity_type = 'EMPLOYEE'
JOIN source_records sr ON s.source_record_id = sr.id AND sr.source_type = 'GITHUB'
WHERE r.relationship_type = 'authored_by'
  AND s.source_record_id IS NOT NULL
  AND (
      sr.author_id = t.metadata->>'login'
      OR sr.metadata->'author'->>'login' = t.metadata->>'login'
  )
ON CONFLICT DO NOTHING;

-- 4. PR -> COMMIT (Path 4a: Verified via PR metadata->'commits' array with safe CASE)
INSERT INTO relationship_owners (relationship_id, source_record_id)
SELECT r.id, s_sr.id
FROM relationships r
JOIN entities s ON r.source_entity_id = s.id AND s.entity_type = 'PULL_REQUEST'
JOIN entities t ON r.target_entity_id = t.id AND t.entity_type = 'COMMIT'
JOIN source_records s_sr ON s.source_record_id = s_sr.id AND s_sr.source_type = 'GITHUB'
WHERE r.relationship_type = 'contains'
  AND s_sr.metadata IS NOT NULL
  AND s_sr.metadata ? 'commits'
  AND EXISTS (
      SELECT 1 
      FROM jsonb_array_elements(
          CASE 
              WHEN jsonb_typeof(s_sr.metadata->'commits') = 'array' 
              THEN s_sr.metadata->'commits' 
              ELSE '[]'::jsonb 
          END
      ) c
      WHERE (
          (jsonb_typeof(c) = 'object' AND c->>'sha' IS NOT NULL AND c->>'sha' = t.metadata->>'sha')
          OR (jsonb_typeof(c) = 'string' AND c#>>'{}' = t.metadata->>'sha')
      )
  )
ON CONFLICT DO NOTHING;

-- 5. PR -> COMMIT (Path 4b: Verified via commit message referencing PR with token boundary \m)
INSERT INTO relationship_owners (relationship_id, source_record_id)
SELECT r.id, t_sr.id
FROM relationships r
JOIN entities s ON r.source_entity_id = s.id AND s.entity_type = 'PULL_REQUEST'
JOIN entities t ON r.target_entity_id = t.id AND t.entity_type = 'COMMIT'
JOIN source_records t_sr ON t.source_record_id = t_sr.id AND t_sr.source_type = 'GITHUB'
WHERE r.relationship_type = 'contains'
  AND t_sr.raw_content IS NOT NULL
  AND s.metadata->>'number' IS NOT NULL
  AND s.metadata->>'number' ~ '^\d+$'
  AND s.metadata->>'repository' IS NOT NULL
  AND t.metadata->>'repository' IS NOT NULL
  AND s.metadata->>'repository' = t.metadata->>'repository'
  AND t_sr.raw_content ~* ('\m(?:PR\s*#?|pull/)' || (s.metadata->>'number') || '\M')
ON CONFLICT DO NOTHING;
