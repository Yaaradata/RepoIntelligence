-- Migration 002: events — the selection unit is (repo, event).

BEGIN;

CREATE TABLE IF NOT EXISTS repo_intelligence.github_repo_events (
    event_id        BIGSERIAL PRIMARY KEY,
    repo_id         BIGINT NOT NULL REFERENCES repo_intelligence.github_repositories(repo_id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL CHECK (event_type IN (
                        'FIRST_SEEN','MAJOR_RELEASE','MINOR_RELEASE',
                        'MOMENTUM_SPIKE','CAPABILITY_CHANGE',
                        'SHOWHN_SURGE','ADOPTION_MILESTONE','SECURITY_ADVISORY')),
    lane            TEXT NOT NULL CHECK (lane IN ('new','accelerating','established','popular','seed')),
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_week      DATE NOT NULL CHECK (EXTRACT(ISODOW FROM event_week) = 1),
    evidence        JSONB NOT NULL,
    UNIQUE (repo_id, event_type, event_week)
);
CREATE INDEX IF NOT EXISTS ix_events_week ON repo_intelligence.github_repo_events(event_week DESC, lane);

COMMIT;
