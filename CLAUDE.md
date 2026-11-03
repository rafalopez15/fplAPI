# fplAPI

FastAPI service that serves Fantasy Premier League (FPL) data through a cleaner REST interface, from a Postgres copy of the official FPL API that an hourly job keeps current. Its main consumer will be an iOS app.

## Working guidelines

Adapted from [andrej-karpathy-skills/CLAUDE.md](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md). They favor caution over speed; use judgment on trivial tasks.

1. **Think before coding.** State assumptions. If a request can be read more than one way, lay out the options instead of picking one silently. Ask when something is unclear, and raise tradeoffs early.
2. **Simplicity first.** Write the smallest change that solves the stated problem. No speculative features, extra abstractions, or configuration nobody asked for.
3. **Surgical changes.** Touch only what the task requires. Leave unrelated code, comments and formatting alone. Clean up only what your own change orphaned; point out other problems instead of fixing them unasked.
4. **Goal-driven execution.** Turn each task into something you can verify, such as a test that fails before the fix and passes after. For multi-step work, give a short plan with a check for each step.

## Git conventions

- **No AI attribution.** Never add `Co-Authored-By: Claude`, "Generated with Claude Code", or any other Claude/AI attribution to commit messages or PR descriptions.
- Group changes into logical commits, each leaving the app working: for example config, fixes, tests and tooling as separate commits.
- Commit messages: a short imperative subject line, then a body explaining what changed and why.
- Commit or push only when asked.
- **Branches:** one short-lived branch per Linear story, created from an up-to-date `main` and named with the issue id (e.g. `fpl-8-sync-bootstrap`) so Linear links it. There's no `dev` branch. Once a branch's PR is merged, don't commit to it again: start the next story on a new branch.
- **Merging:** PRs merge into `main` with a merge commit, not squash or rebase, so the logical commits above survive on `main`.

## Commands

```bash
source env/bin/activate              # venv lives in env/ (not .env, which is config)
pip install -r requirements-dev.txt  # app, test and lint dependencies
cp .env.example .env                 # first-time setup
fastapi dev main.py                  # run locally with reload
python -m src.jobs.sync_bootstrap    # sync bootstrap-static into the database in DATABASE_URL
docker build -t fplapi:local . && docker run --rm -p 8000:8000 --env-file .env fplapi:local
python -m pytest                     # tests + coverage report (fails under 95%)
pylint $(git ls-files '*.py')        # lint, same as CI (config in .pylintrc)
alembic upgrade head                 # apply database migrations (uses DATABASE_URL)
alembic revision -m "describe change" # new migration in migrations/versions/
colima start && docker start fplapi-test-db  # local test database (setup in README)
```

## Architecture

```
main.py                  App setup: exception handlers (503s), /healthcheck
alembic.ini              Alembic settings; the database URL is set in migrations/env.py
migrations/              Alembic environment and versions/ (one file per migration)
src/
  routers/               HTTP layer: one APIRouter per resource, mounted under /api
    __init__.py          Combines the resource routers into a single `routers`
    elements.py          /elements, /elements/{id}, /elements/position/{element_type}
    events.py            /events, /events/{id}, /events/current-event/, /events/{id}/live (live from FPL)
    teams.py             /teams, /teams/{team_name}
    fixtures.py          /fixtures (optional ?finished= and ?started= filters)
    managers.py          /managers/{id}, /managers/{id}/transfers, /managers/{id}/history,
                         /managers/{id}/picks?event= (live from FPL)
  services/              Business logic: queries that return Pydantic models
  models/                Pydantic response models (ElementResponse, EventResponse, TeamResponse)
  db/
    models.py            SQLAlchemy ORM tables; Alembic autogenerates migrations from them
  jobs/
    sync_bootstrap.py    Hourly job: upserts bootstrap-static into Postgres, records sync_runs
  util/
    config.py            Reads .env (python-dotenv) into module-level constants
    database.py          Engine, session dependencies (DataSession), sync state, health checks
    fpl_client.py        All FPL calls: the sync job's fetches and the live ones (manager*, event_live)
tests/                   pytest suite, one file per layer (test_db.py: schema and migrations)
vercel.json              Vercel settings: function region (cle1)
.python-version          Python version for Vercel (3.13)
Dockerfile               Image for running the API locally (Vercel doesn't use it)
```

**Request flow:** router → service → SQLAlchemy query on Postgres → Pydantic response model.

The exceptions are `/managers/...` and `/events/{id}/live`, which call FPL live through `fpl_client` (router → service → `fetch_*()` → FPL). Manager data is per user and can't be synced ahead of time, and live points change by the minute during matches. Vercel's CDN caches their successful responses (see Fetching), and they don't touch the database, so they work even when the sync is behind.

- **Routers** handle HTTP concerns only: path parameters, status codes, `HTTPException`. Endpoints are plain `def`, so FastAPI runs them in its thread pool and the blocking database calls don't stall the event loop. Each takes a `session: DataSession` and passes it to a service.
- **`DataSession`** (`src/util/database.py`) is the request's session from `get_session`, after `get_data_session` checks that a bootstrap sync has succeeded. Tests override `get_session`.
- **Services** are plain functions that take the session first. They query with the ORM models and return Pydantic models (built with `model_validate(row)`), or `None`/`[]` when nothing matches. Lists are in FPL id order.
- **Response models** use `from_attributes=True`. `EventResponse` rebuilds FPL's `top_element_info` object from the `top_element` and `top_element_points` columns.
- **Data refresh:** `src/jobs/sync_bootstrap.py` upserts bootstrap-static and FPL's `/fixtures/` into Postgres every hour (GitHub Actions), in one transaction. Nothing is fetched at startup or per request. `/healthcheck` reports the last successful sync as `last_sync`.

## Design decisions

### Configuration
- **Secrets and per-environment settings live in `.env`**, are read in `src/util/config.py`, and are imported as constants. Values that are the same everywhere don't belong there.
- `DATABASE_URL` is the only required setting. It goes through `_get_env()`, which strips surrounding whitespace and raises at import time if it's missing or empty, so the app fails fast. Optional ones, like `FPL_REQUEST_TIMEOUT` (default 10s), use `os.getenv` with a default. A new setting should be optional with a default: the deployed API imports `config.py` too, and a new required setting would stop it from starting until it was added in Vercel.
- **FPL's API paths are constants in `src/util/fpl_client.py`** (`BOOTSTRAP_STATIC_URL`, `FIXTURES_URL`, `ENTRY_URL`), built from `FPL_BASE_URL`. That one is optional, defaulting to `https://fantasy.premierleague.com/api`, so it can point at a local mock. To call a new FPL endpoint, add a constant there, not a setting.
- `.env` is gitignored; `.env.example` is committed and must stay in sync with it.

### Database
- Postgres on Supabase, accessed with SQLAlchemy (sync engine, psycopg 3 driver) and migrated with Alembic.
- `DATABASE_URL` (required) is a Supabase pooler URI with the scheme changed to `postgresql+psycopg://` and `?sslmode=require` added. Both poolers work over IPv4; the direct connection is IPv6-only. `DATABASE_CONNECT_TIMEOUT` (default 5s) is optional.
  - **The API on Vercel uses the transaction pooler (port 6543).** The session pooler (port 5432) gives each open client connection one of only 15 slots, and every warm Vercel instance, previews included, keeps its own pool open. On 3 November 2026 they took all 15 and the hourly sync couldn't connect. The transaction pooler shares server connections between transactions, so idle pools don't hold slots.
  - **The GitHub workflows (sync and migrate) and a local `.env` use the session pooler (port 5432),** through the `DATABASE_URL` repository secret. Vercel's variable and that secret are separate, so no code picks a URL.
  - The transaction pooler can't keep prepared statements between transactions, so the engine sets `prepare_threshold=None` (psycopg prepares statements automatically otherwise). It works on both poolers.
- **Connection pool:** `DATABASE_POOL_SIZE` (default 3) and `DATABASE_MAX_OVERFLOW` (default 2). Keep them small: every Vercel instance has its own pool, and Supabase's free plan allows only a few server connections in total. Anything that connects through the session pooler holds one of its 15 slots for as long as the connection is open.
- Never print or log `DATABASE_URL`: it contains the password.
- `migrations/env.py` reads the URL from `config.py`, never from `alembic.ini`, and escapes `%` for configparser. If a URL is already set (as the tests do), it keeps that one.
- **Schema** (design in the FPL-7 spike's "Spike outcome" comment in Linear): `teams`, `element_types`, `elements`, `events`, `fixtures` (every match of the season, from `/fixtures/`), `player_fixture_history` (one row per player per fixture, from `/element-summary/{id}/`) and `sync_runs`.
  - `fixtures.started` is true from kickoff. FPL only sets `finished` once the gameweek's bonus points are confirmed, a day or more after the match, so "still to be played" means `started = false`.
  - Column names are FPL's field names, so rows map 1:1 onto the Pydantic models. `elements` columns match `ElementResponse`, including which are `NOT NULL`.
  - Ids are FPL's, never generated (`autoincrement=False`). Decimals are `numeric`, timestamps are `timestamptz`.
  - Rows are upserted, never deleted. `events.most_selected` and the other player ids deliberately have no foreign key, so a missing player can't fail a sync.
- **Row-level security:** Supabase's Data API is off, and every table has RLS enabled with no policies, as a second layer. Autogenerate doesn't handle RLS, so every migration that creates a table must add `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`. `tests/test_db.py` fails if a table lacks it.
- **New migration:** change `src/db/models.py`, then autogenerate against the test database, not Supabase: `DATABASE_URL=$TEST_DATABASE_URL alembic revision --autogenerate -m "..."`. Review the file, add RLS for new tables, wrap lines over 100 characters, run the tests, then `alembic upgrade head` against Supabase.
- SQLAlchemy calls are blocking: use plain `def` endpoints (FastAPI's thread pool), or `asyncio.to_thread` from async code, as `/healthcheck` does.
- `/healthcheck` returns `{"status": "ok", "database": "ok" | "unavailable", "last_sync": <ISO timestamp> | null}`, always with 200, so a database outage doesn't make a host restart the app.

### Fetching
- All FPL calls go through `src/util/fpl_client.py`, with a timeout and a descriptive `User-Agent` (`HEADERS`).
- **Sync job:** `fetch_bootstrap_static()` and `fetch_fixtures()` use `FPL_REQUEST_TIMEOUT` (default 10s) and raise `requests` errors on network errors, error statuses (`raise_for_status()`) and invalid JSON. The job catches them, records the failed run, and leaves the previous data in place.
- **Live endpoints:** `fetch_manager()`, `fetch_manager_transfers()`, `fetch_manager_history()`, `fetch_manager_picks()` and `fetch_event_live()` go through `_get_live_json()` and use the shorter `FPL_PROXY_TIMEOUT` (default 5s), because someone is waiting. They raise `FplNotFoundError` for FPL's 404 and `FplUnavailableError` for everything else, including timeouts, 429/5xx and FPL's HTML "the game is being updated" page.
- **Picks:** FPL only publishes a squad once the gameweek's deadline has passed. Without `?event=`, `/picks` first calls `fetch_manager()` for the manager's `current_event` (two FPL calls), and returns 404 if there's none yet. FPL's 404 for a gameweek with no picks (before the manager joined, or not yet played) is also "Manager not found".
- **Live points:** `/events/{id}/live` flattens FPL's `event/{gw}/live/` (about 475KB, ~30 stats and a breakdown per player) to `id`, `total_points` and `minutes` per player (about 27KB). FPL returns an empty list for a gameweek that hasn't started (200 `[]`) and 404 outside 1–38 (`"Event not found"`).
- **Caching:** the live routes set `Cache-Control: s-maxage=..., stale-while-revalidate=...` on successful responses, so Vercel's CDN serves repeats without calling FPL: 60s for the manager, transfers, picks and live points, 300s for history. Errors send `no-store`. An in-memory cache would be useless on Vercel, whose instances don't share memory and scale to zero.

### Error responses
Use these status codes consistently:

| Situation | Status |
|---|---|
| No bootstrap sync has succeeded yet (`FplDataUnavailableError`), or the database is unreachable (`OperationalError`) | **503** `"FPL data is currently unavailable"`, from the handlers in `main.py` |
| A live call to FPL fails (`FplUnavailableError`) | **503** `"FPL is unavailable right now"`, with `Cache-Control: no-store` |
| Single-item lookup or filter finds nothing | **404** with a resource-specific detail, e.g. `"Team not found"`. Unknown FPL managers: `"Manager not found"`, and gameweeks FPL doesn't have on `/live`: `"Event not found"`, both with `no-store` |
| Collection endpoint with no items | **200** with `[]` |
| Invalid path parameter type | **422** (FastAPI default) |

### Logging
- Use `logging.getLogger(__name__)` with `%s` placeholders, e.g. `logger.info("msg: %s", value)`. Never pass extra arguments without a placeholder: pytest's log capture raises on that.

### Hosting
- Production runs on **Vercel** (Hobby plan: personal, non-commercial use only), decided in the FPL-25 spike. Vercel's zero-config FastAPI support serves the `app` in `main.py`; there's no Vercel-specific code.
- `vercel.json` pins the region to `cle1` (Cleveland, AWS us-east-2, next to Supabase), and `.python-version` pins Python 3.13. Keep that file in step with CI's Python.
- Vercel's only required environment variable is `DATABASE_URL` (marked Sensitive), the **transaction pooler** URI (port 6543) for both Production and Preview (see Database). Pushes to `main` deploy to production; PRs get preview URLs.
- Instances scale to zero, so the first request after idle has a cold start of a second or two. An always-warm instance needs Vercel Pro.
- The `Dockerfile` (`python:3.13-slim`, runtime dependencies only, non-root) is for local runs and a future move to a container host such as Cloud Run, the fallback if the app goes commercial. Vercel doesn't use it. `.dockerignore` keeps `.env`, `env/`, tests and migrations out of the image; use `**/` patterns so they match in subfolders.

## Testing

- pytest with pytest-cov. `pytest.ini` enforces **≥95% coverage** on `src` and `main`, currently at 100%.
- `tests/conftest.py`:
  - Sets the required env vars before importing `src`, so tests don't need a `.env` file (e.g. in CI).
  - FPL-shaped builders (`make_team()`, `make_element()`, `make_event()`, `future_event()`, `ELEMENT_TYPES`) are shared by the API and sync tests.
  - `seeded_session` loads a small dataset into the test database through the sync job's `to_row()`: 2 teams, 4 positions, 3 players (Saka, Haaland, Palmer), gameweeks 8 to 10 and a successful sync run. `client` is a `TestClient` whose requests use that session. Change data in a test by editing rows in `seeded_session`.
  - The autouse fixture `block_network` makes any real `requests.get` call fail the test. Mock it with `monkeypatch` when a test needs a response.
  - The autouse fixture `block_database` does the same for `database.engine.connect`. Patch `database.is_database_reachable` (or `engine.connect`) when a test hits `/healthcheck`.
  - Database tests use a real Postgres from `TEST_DATABASE_URL` (in `.env` locally, a service container in CI). `db_engine` migrates it from scratch once per run, and `db_session` rolls back each test's changes, even after `commit()`. The fixture refuses a Supabase URL. Without `TEST_DATABASE_URL`, the database tests fail with setup instructions.
- Routes are tested with `fastapi.testclient.TestClient` (the `client` fixture). Async code is tested with `asyncio.run(...)`, so pytest-asyncio isn't needed.
- `config.py` import-time behavior is tested by running it as a fresh module (`load_fresh_config`), so the real module stays untouched.
- Every new code path needs tests, including its error paths.

## Environment

- Python **3.10+**. 3.9 is end-of-life, and GitHub's Ubuntu 26.04 runners don't provide it.
- `.github/workflows/ci.yml` runs on pull requests and on pushes to `main` (other branch pushes don't run CI until a PR is opened), on Python 3.13. A newer push to the same PR cancels the run in progress. Three jobs:
  - **Pylint** lints, and **Tests** runs pytest with the 95% coverage gate against a Postgres 17 service container. They show as separate checks.
  - Each writes a summary table to the run page and to a Markdown file uploaded as an artifact: test pass rate and failures via `.github/scripts/summarize_tests.py`, pylint score and issues via `.github/scripts/summarize_pylint.py`. Both write through `summary_output.write_markdown()`.
  - **PR comment** (pull requests only, after both jobs, even if they fail) posts one comment with both summaries and edits it on later pushes. It finds the comment by the hidden `<!-- ci-report -->` marker, and is the only job with `pull-requests: write`.
- Two more workflows use the Supabase database through the `DATABASE_URL` repository secret, and share the `database` concurrency group so they never overlap:
  - `sync-bootstrap.yml` runs the bootstrap sync hourly and on manual dispatch. GitHub's own scheduler skips most hourly runs, so a `pg_cron` job in Supabase starts the workflow at :17 every hour through GitHub's workflow dispatch API, with a fine-grained token kept in Supabase Vault. The workflow's `schedule` (cron `17 * * * *`) stays as a backup. The trigger lives only in Supabase, not in a migration (the test databases lack `pg_cron`, `pg_net` and Vault); the README's "Hourly trigger" section has the SQL and the token's expiry date.
  - `migrate.yml` runs `alembic upgrade head` on pushes to `main` that touch `migrations/`, `src/db/` or `alembic.ini`, and on manual dispatch. Migrations reach Supabase this way, not from a laptop.
  - Both need only the `DATABASE_URL` secret; every other setting has a default. Scheduled workflows only run from `main`.
- `.pylintrc` turns off docstring checks and `too-few-public-methods`, and ignores `alembic.context` and `alembic.op` for member checks because they're populated at runtime. Migration files disable `invalid-name` on their first line, because Alembic requires names like `revision` and file names start with the revision id (the template in `migrations/script.py.mako` adds it). Test files disable `redefined-outer-name` (pytest fixtures) at the top of the file. Fix any other warnings rather than silencing them.
- Runtime dependencies are pinned in `requirements.txt`; test and lint tools in `requirements-dev.txt`, which includes it.
