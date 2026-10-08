# RepoIntelligence V1

GitHub repository intelligence for TheNeural newsletter. Phase 1 (collection) is
built: discovery lanes A/D/E, identity keyed on `repo_id`, weekly snapshots,
releases, README facts, package mapping with downloads, and Show HN matching.
Everything in Phase 1 is free; there are no LLM calls yet.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env     # DATABASE_URL, GITHUB_TOKEN (fine-grained, read-only public repos)
```

Migrations live in `sql/migrations/` and are applied by a human, in order:

```bash
psql "$DATABASE_URL" -f sql/migrations/001_schema.sql
psql "$DATABASE_URL" -f sql/migrations/002_events.sql
psql "$DATABASE_URL" -f sql/migrations/003_scores.sql
.venv/bin/python scripts/check_schema.py      # run this before diagnosing anything
```

## Running

```bash
.venv/bin/python scripts/run_pipeline.py --dry-run          # prints scope and search queries only
.venv/bin/python scripts/run_pipeline.py                    # discovery → identity → snapshot(new) → packages → showhn
.venv/bin/python scripts/run_stage.py --stage snapshot --scope watchlist   # fixed weekday only
.venv/bin/python scripts/run_stage.py --stage showhn_refresh
```

Every stage prints its resolved scope before it does any work. A watchlist
snapshot refuses to run on any day but `snapshot.fixed_weekday`
(`config/settings.yaml`, 6 = Sunday) unless `--force-weekday` is passed.

Cron wrappers are in `scripts/cron/` (not installed):

| UTC | Script |
|---|---|
| 19:00 daily | `discovery.sh` |
| every 6h | `showhn.sh` |
| 20:00 Sunday | `snapshot.sh` |

## Tests

```bash
.venv/bin/python -m pytest -q tests/unit
```

No test touches the network or the database.
