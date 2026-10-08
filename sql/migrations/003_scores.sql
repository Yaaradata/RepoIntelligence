-- Migration 003: append-only assessments, versioned scores, report view.

BEGIN;

-- 5.7 Assessments — APPEND-ONLY. NULLS NOT DISTINCT so a showhn_digest row
-- (event_id NULL) is still skipped on re-run instead of duplicated.
CREATE TABLE IF NOT EXISTS repo_intelligence.github_repo_assessments (
    assessment_id   BIGSERIAL PRIMARY KEY,
    repo_id         BIGINT NOT NULL REFERENCES repo_intelligence.github_repositories(repo_id) ON DELETE CASCADE,
    event_id        BIGINT REFERENCES repo_intelligence.github_repo_events(event_id) ON DELETE CASCADE,
    task_type       TEXT NOT NULL CHECK (task_type IN ('screen','editorial','showhn_digest')),
    result_json     JSONB NOT NULL,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    policy_version  TEXT,
    stage_version   TEXT NOT NULL,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    cost_usd        NUMERIC(10,6),
    run_id          UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE NULLS NOT DISTINCT (repo_id, event_id, task_type, provider, model, prompt_version)
);

CREATE OR REPLACE FUNCTION repo_intelligence.forbid_assessment_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'github_repo_assessments is append-only (% blocked)', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS trg_assessments_append_only ON repo_intelligence.github_repo_assessments;
CREATE TRIGGER trg_assessments_append_only
    BEFORE UPDATE ON repo_intelligence.github_repo_assessments
    FOR EACH ROW EXECUTE FUNCTION repo_intelligence.forbid_assessment_mutation();

-- 5.8 Scores — derived, versioned, recomputable.
CREATE TABLE IF NOT EXISTS repo_intelligence.github_repo_scores (
    repo_id             BIGINT NOT NULL REFERENCES repo_intelligence.github_repositories(repo_id) ON DELETE CASCADE,
    event_id            BIGINT NOT NULL REFERENCES repo_intelligence.github_repo_events(event_id) ON DELETE CASCADE,
    score_version       TEXT NOT NULL,

    usefulness          NUMERIC(4,2),
    evidence_factor     NUMERIC(4,3),
    momentum_pct        NUMERIC(4,3),
    adoption_pct        NUMERIC(4,3),
    showhn_pct          NUMERIC(4,3),
    popularity_pct      NUMERIC(4,3),
    final_score         NUMERIC(4,2),

    components          JSONB NOT NULL,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (repo_id, event_id, score_version)
);

-- 5.12 Report view. Latest editorial assessment per event only: assessments
-- are append-only, so a plain join would emit one row per model/prompt.
DROP VIEW IF EXISTS repo_intelligence.v_candidates;
CREATE VIEW repo_intelligence.v_candidates AS
SELECT
    r.repo_id, r.full_name, r.html_url, r.description,
    r.primary_language, r.licence_key, r.created_at,
    e.event_id, e.event_type, e.lane, e.event_week,
    s.stars, s.forks, s.contributors_count,
    s.downloads_30d, s.latest_release_tag, s.latest_release_at, s.pushed_at,
    sc.usefulness, sc.final_score, sc.components,
    a.result_json AS editorial,
    hn.points AS showhn_points, hn.comment_count AS showhn_comments
FROM repo_intelligence.github_repo_events e
JOIN repo_intelligence.github_repositories r   ON r.repo_id = e.repo_id
LEFT JOIN LATERAL (
    SELECT * FROM repo_intelligence.github_repo_snapshots
    WHERE repo_id = e.repo_id ORDER BY captured_at DESC LIMIT 1
) s ON TRUE
LEFT JOIN repo_intelligence.github_repo_scores sc
       ON sc.event_id = e.event_id AND sc.score_version = 'v001'
LEFT JOIN LATERAL (
    SELECT result_json FROM repo_intelligence.github_repo_assessments
    WHERE event_id = e.event_id AND task_type = 'editorial'
    ORDER BY created_at DESC LIMIT 1
) a ON TRUE
LEFT JOIN LATERAL (
    SELECT * FROM repo_intelligence.github_repo_showhn
    WHERE repo_id = e.repo_id AND match_confidence >= 0.70
    ORDER BY captured_at DESC LIMIT 1
) hn ON TRUE;

COMMIT;
