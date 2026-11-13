---
paths:
  - "src/db/**"
  - "migrations/**"
  - "alembic.ini"
  - "src/util/database.py"
  - "src/util/config.py"
  - "tests/test_db.py"
  - "tests/test_database.py"
---

# Database

- **Poolers:** the API on Vercel uses Supabase's transaction pooler (port 6543); the workflows and a local `.env` use the session pooler (5432), which has only 15 client slots (why: FPL-39). Vercel's `DATABASE_URL` and the GitHub secrets are separate, so no code picks a URL.

  | Where | Database | Pooler |
  |---|---|---|
  | Vercel Production `DATABASE_URL` | production | transaction (6543) |
  | Vercel Preview `DATABASE_URL` | staging | transaction (6543) |
  | GitHub `production` environment secret `DATABASE_URL` | production | session (5432) |
  | GitHub secret `STAGING_DATABASE_URL` | staging | session (5432) |
  | Local `.env` | production | session (5432) |

- URLs use `postgresql+psycopg://` and `?sslmode=require`. The direct connection is IPv6-only and unused.
- The engine sets `prepare_threshold=None`: the transaction pooler can't keep prepared statements.
- Keep the pool small (`DATABASE_POOL_SIZE` 3, `DATABASE_MAX_OVERFLOW` 2): every Vercel instance has its own.
- `migrations/env.py` reads the URL from `config.py`, never `alembic.ini`, and escapes `%`. It keeps a URL already set, as the tests do.

## Schema

- FPL tables: ids are FPL's (`autoincrement=False`), column names are FPL's field names, decimals are `numeric`, timestamps `timestamptz`. Rows are upserted, never deleted. Player ids like `events.most_selected` deliberately have no foreign key, so a missing player can't fail a sync.
- `fixtures.started` is true from kickoff; FPL sets `finished` a day or more after the match. "Still to be played" means `started = false`.
- `player_fixture_history` isn't filled yet.

## Migrations

- **Every migration that creates a table adds `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`.** Autogenerate doesn't, and `tests/test_db.py` fails without it.
- New migration: change `src/db/models.py`, then autogenerate against the test database, never Supabase: `DATABASE_URL=$TEST_DATABASE_URL alembic revision --autogenerate -m "..."`. Review it, add RLS, run the tests.
- **Never run `alembic upgrade head` against Supabase.** `migrate.yml` applies it: staging on the PR, production on merge (or before the next hourly sync if that run is lost).
- Keep schema changes backward compatible: new code can briefly run on the old schema (FPL-125).

## `/healthcheck`

Always 200: `{"status": "ok", "database": "ok" | "unavailable", "last_sync", "last_points_sync"}`. `last_sync` is the last bootstrap sync (hourly); `last_points_sync` moves about weekly. A `last_points_sync` over about 10 days old in season means the points sync is failing.
