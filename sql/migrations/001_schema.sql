-- Migration 001: identity, snapshots, releases, Show HN, quality facts,
-- editorial state, run tracking, golden labels, discovery candidates.
-- Idempotent. Agents write migrations; humans apply DDL.

BEGIN;

CREATE SCHEMA IF NOT EXISTS repo_intelligence;

-- 5.1 Identity — keyed on GitHub numeric id, never owner/name.
CREATE TABLE IF NOT EXISTS repo_intelligence.github_repositories (
    repo_id             BIGINT PRIMARY KEY,
    owner               TEXT NOT NULL,
    name                TEXT NOT NULL,
    full_name           TEXT NOT NULL,
    description         TEXT,
    homepage            TEXT,
    html_url            TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_snapshot_at    TIMESTAMPTZ,
    primary_language    TEXT,
    licence_key         TEXT,
    is_fork             BOOLEAN NOT NULL DEFAULT FALSE,
    is_archived         BOOLEAN NOT NULL DEFAULT FALSE,
    package_ecosystem   TEXT CHECK (package_ecosystem IN ('npm','pypi','crates','docker')),
    package_name        TEXT,
    package_match_strategy TEXT,                 -- manifest|homepage|name_verified
    previous_full_names TEXT[],
    created_row_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_repos_full_name ON repo_intelligence.github_repositories(full_name);
CREATE INDEX IF NOT EXISTS ix_repos_created   ON repo_intelligence.github_repositories(created_at);

-- Stage 0 output: run-scoped candidate list. repo_id is NULL until identity
-- resolves seeds / Show HN entries that arrive as owner/name.
CREATE TABLE IF NOT EXISTS repo_intelligence.github_discovery_candidates (
    candidate_id    BIGSERIAL PRIMARY KEY,
    run_id          UUID NOT NULL,
    lane            TEXT NOT NULL CHECK (lane IN ('new','accelerating','established','popular','seed')),
    source          TEXT NOT NULL,               -- search:<group>|snapshots|seeds.yaml|showhn_front
    full_name_hint  TEXT,
    repo_id         BIGINT,
    discovered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    evidence        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_candidates_run ON repo_intelligence.github_discovery_candidates(run_id);
CREATE INDEX IF NOT EXISTS ix_candidates_repo ON repo_intelligence.github_discovery_candidates(repo_id);

-- 5.2 Snapshots — one row per repo per day; re-running a day updates.
CREATE TABLE IF NOT EXISTS repo_intelligence.github_repo_snapshots (
    snapshot_id         BIGSERIAL PRIMARY KEY,
    repo_id             BIGINT NOT NULL REFERENCES repo_intelligence.github_repositories(repo_id) ON DELETE CASCADE,
    captured_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    captured_date       DATE GENERATED ALWAYS AS ((captured_at AT TIME ZONE 'UTC')::date) STORED,

    stars               INTEGER NOT NULL,
    forks               INTEGER NOT NULL,
    subscribers         INTEGER,                 -- subscribers_count (real watchers)
    open_issues         INTEGER,                 -- open_issues_count minus open PRs
    open_prs            INTEGER,
    contributors_count  INTEGER,                 -- API caps at 500
    contributor_orgs    INTEGER,

    commits_7d          INTEGER,
    commits_30d         INTEGER,
    pushed_at           TIMESTAMPTZ,

    latest_release_tag  TEXT,
    latest_release_at   TIMESTAMPTZ,
    release_count       INTEGER,

    downloads_7d        BIGINT,
    downloads_30d       BIGINT,

    description         TEXT,                    -- for CAPABILITY_CHANGE detection
    topics              TEXT[],
    languages           JSONB,

    UNIQUE (repo_id, captured_date)
);
CREATE INDEX IF NOT EXISTS ix_snap_repo_date ON repo_intelligence.github_repo_snapshots(repo_id, captured_date DESC);

-- 5.3 Releases
CREATE TABLE IF NOT EXISTS repo_intelligence.github_repo_releases (
    repo_id         BIGINT NOT NULL REFERENCES repo_intelligence.github_repositories(repo_id) ON DELETE CASCADE,
    tag             TEXT NOT NULL,
    published_at    TIMESTAMPTZ NOT NULL,
    is_prerelease   BOOLEAN NOT NULL DEFAULT FALSE,
    semver_major    INTEGER,
    semver_minor    INTEGER,
    semver_patch    INTEGER,
    name            TEXT,
    body_excerpt    TEXT,
    PRIMARY KEY (repo_id, tag)
);
CREATE INDEX IF NOT EXISTS ix_releases_published ON repo_intelligence.github_repo_releases(published_at DESC);

-- 5.4 Show HN
CREATE TABLE IF NOT EXISTS repo_intelligence.github_repo_showhn (
    repo_id             BIGINT NOT NULL REFERENCES repo_intelligence.github_repositories(repo_id) ON DELETE CASCADE,
    hn_story_id         BIGINT NOT NULL,
    captured_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    title               TEXT,
    story_url           TEXT,
    posted_at           TIMESTAMPTZ,
    author              TEXT,

    match_strategy      TEXT NOT NULL CHECK (match_strategy IN ('url_exact','homepage','title_text')),
    match_confidence    NUMERIC(3,2) NOT NULL,

    points              INTEGER,
    comment_count       INTEGER,
    points_6h           INTEGER,
    points_24h          INTEGER,
    points_48h          INTEGER,
    comments_24h        INTEGER,
    comments_48h        INTEGER,

    comment_digest      JSONB,

    PRIMARY KEY (repo_id, hn_story_id, captured_at)
);
CREATE INDEX IF NOT EXISTS ix_showhn_posted ON repo_intelligence.github_repo_showhn(posted_at DESC);

-- 5.6 Quality facts — file inspection only.
CREATE TABLE IF NOT EXISTS repo_intelligence.github_repo_quality_facts (
    repo_id             BIGINT PRIMARY KEY REFERENCES repo_intelligence.github_repositories(repo_id) ON DELETE CASCADE,
    checked_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    has_readme          BOOLEAN,
    readme_length       INTEGER,
    has_install_section BOOLEAN,
    has_usage_example   BOOLEAN,
    code_block_count    INTEGER,
    badge_count         INTEGER,
    has_tests           BOOLEAN,
    has_ci              BOOLEAN,
    has_docs_dir        BOOLEAN,
    has_examples_dir    BOOLEAN,
    has_contributing    BOOLEAN,
    has_changelog       BOOLEAN,
    readme_excerpt      TEXT
);

-- 5.9 Editorial state. watchlist_status is pipeline state; the featured /
-- suppressed columns are editorial decisions. They never share a column.
CREATE TABLE IF NOT EXISTS repo_intelligence.github_repo_editorial_state (
    repo_id                 BIGINT PRIMARY KEY REFERENCES repo_intelligence.github_repositories(repo_id) ON DELETE CASCADE,
    last_featured_at        TIMESTAMPTZ,
    last_featured_reason    TEXT,
    last_featured_event_id  BIGINT,
    features_count          INTEGER NOT NULL DEFAULT 0,
    cooldown_until          TIMESTAMPTZ,
    suppressed              BOOLEAN NOT NULL DEFAULT FALSE,
    suppressed_reason       TEXT,
    watchlist_status        TEXT NOT NULL DEFAULT 'active'
                            CHECK (watchlist_status IN ('active','watch','dormant','excluded')),
    watchlist_reason        TEXT,
    watchlist_checked_at    TIMESTAMPTZ
);

-- 5.10 Run tracking
CREATE TABLE IF NOT EXISTS repo_intelligence.pipeline_runs (
    run_id          UUID PRIMARY KEY,
    pipeline_name   TEXT NOT NULL,
    trigger_type    TEXT,
    code_commit_sha TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    status          TEXT NOT NULL CHECK (status IN ('running','succeeded','failed','stopped')),
    items_input     INTEGER,
    items_succeeded INTEGER,
    items_failed    INTEGER,
    total_cost_usd  NUMERIC(10,6),
    metadata        JSONB
);

CREATE TABLE IF NOT EXISTS repo_intelligence.stage_runs (
    stage_run_id    BIGSERIAL PRIMARY KEY,
    run_id          UUID NOT NULL REFERENCES repo_intelligence.pipeline_runs(run_id) ON DELETE CASCADE,
    stage_name      TEXT NOT NULL,
    stage_version   TEXT,
    prompt_version  TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    items_input     INTEGER,
    items_success   INTEGER,
    items_failed    INTEGER,
    items_skipped   INTEGER,
    cost_usd        NUMERIC(10,6),
    status          TEXT,
    error_summary   TEXT
);

CREATE TABLE IF NOT EXISTS repo_intelligence.llm_requests (
    request_id      BIGSERIAL PRIMARY KEY,
    run_id          UUID,
    stage_name      TEXT,
    provider        TEXT,
    model           TEXT,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    estimated_cost  NUMERIC(10,6),
    actual_cost     NUMERIC(10,6),
    latency_ms      INTEGER,
    http_status     INTEGER,
    retry_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5.11 Golden set
CREATE TABLE IF NOT EXISTS repo_intelligence.golden_labels (
    repo_id         BIGINT NOT NULL,
    golden_set      TEXT NOT NULL,
    labeller        TEXT NOT NULL,
    verdict         TEXT NOT NULL CHECK (verdict IN ('newsletter_worthy','maybe','reject')),
    usefulness      NUMERIC(4,1),
    novelty         NUMERIC(4,1),
    evidence        NUMERIC(4,1),
    maturity        NUMERIC(4,1),
    actionability   NUMERIC(4,1),
    reason          TEXT,
    labelled_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (repo_id, golden_set, labeller)
);

COMMIT;
