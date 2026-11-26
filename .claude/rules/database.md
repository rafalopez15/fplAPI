---
paths:
  - "src/db/**"
  - "migrations/**"
  - "alembic.ini"
  - "src/util/database.py"
  - "src/util/config.py"
  - "tests/test_db.py"
  - "tests/test_database.py"
  - "tests/test_api_role.py"
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
- **The deployed API connects as `fplapi_app`, not the owner** (why: FPL-44). A migration that adds a table the API uses grants it only the commands the code runs and adds a policy `FOR ALL TO fplapi_app USING (true) WITH CHECK (true)`: RLS is on, so without one the role sees no rows. List the table in `PRIVILEGES` in `tests/test_api_role.py` (an empty set if the API doesn't use it). Workflows and jobs stay `postgres`.
  - **A table the API inserts into with a generated id:** add a test that inserts as the role. An `Identity()` column needs only `INSERT` if the insert doesn't ask for the id back (`insert(...).inline()`): SQLAlchemy's default adds `RETURNING id`, which also needs `SELECT`; a `serial` column or separate sequence also needs `GRANT USAGE` on the sequence.
- New migration: change `src/db/models.py`, then autogenerate against the test database, never Supabase: `DATABASE_URL=$TEST_DATABASE_URL alembic revision --autogenerate -m "..."`. Review it, add RLS, run the tests.
- **Never run `alembic upgrade head` against Supabase.** `migrate.yml` applies it: staging on the PR, production on merge (or before the next hourly sync if that run is lost).

### Expand, use, contract

Vercel can deploy `main` before `migrate.yml` migrates production, and if that run is lost the gap lasts until the next hourly sync. Code that needs schema production doesn't have yet fails there. So a schema change ships in steps, each safe with the code before and after it (why: FPL-125):

1. **Expand:** a PR whose migration only adds (a table, a nullable column, an index). Merge it alone and wait until production's `alembic_version` has it. A new column on a table the code already reads goes in the model as `mapped_column(deferred=True)`: `select(Model)` would query it before it exists, and leaving it out of the model fails `test_migrations_match_models`. Example: `team_gameweeks.points` was added deferred, with a test that `select(TeamGameweek)` leaves it out.
2. **Use:** a later PR with the code that reads and writes it, which drops `deferred`. Example: league activity returning `points`.
3. **Contract:** removing a column takes two PRs: one stops using it and defers it, a later one drops it from the model and the database. A rename is an expand, a use and a contract. Example (hypothetical): dropping `team_gameweeks.captain_changed` would first stop reading it and defer it, then drop it.

A new table can ship with the code that uses it when that code tolerates the table being missing, as the snapshots do (a failed save or load is logged, not raised). Say so in the PR.

## `/healthcheck`

Always 200: `{"status": "ok", "database": "ok" | "unavailable", "last_sync", "last_points_sync"}`. `last_sync` is the last bootstrap sync (hourly); `last_points_sync` moves about weekly. A `last_points_sync` over about 10 days old in season means the points sync is failing.
