# fplAPI

FastAPI service that wraps the official Fantasy Premier League (FPL) API and exposes a cleaner REST interface. Its main consumer will be an iOS app.

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

## Commands

```bash
source env/bin/activate              # venv lives in env/ (not .env, which is config)
pip install -r requirements-dev.txt  # app, test and lint dependencies
cp .env.example .env                 # first-time setup
fastapi dev main.py                  # run locally with reload
python -m pytest                     # tests + coverage report (fails under 95%)
pylint $(git ls-files '*.py')        # lint, same as CI (config in .pylintrc)
alembic upgrade head                 # apply database migrations (uses DATABASE_URL)
alembic revision -m "describe change" # new migration in migrations/versions/
colima start && docker start fplapi-test-db  # local test database (setup in README)
```

## Architecture

```
main.py                  App setup: lifespan (initial data fetch), exception handlers, /healthcheck
alembic.ini              Alembic settings; the database URL is set in migrations/env.py
migrations/              Alembic environment and versions/ (one file per migration)
src/
  routers/               HTTP layer: one APIRouter per resource, mounted under /api
    __init__.py          Combines the resource routers into a single `routers`
    elements.py          /elements, /elements/{id}, /elements/position/{element_type}
    events.py            /events, /events/{id}, /events/current-event/
    teams.py             /teams, /teams/{team_name}
  services/              Business logic: filters and lookups over the cached FPL data
  models/                Pydantic response models (ElementResponse, EventResponse)
  db/
    models.py            SQLAlchemy ORM tables; Alembic autogenerates migrations from them
  util/
    config.py            Reads .env (python-dotenv) into module-level constants
    database.py          SQLAlchemy engine and is_database_reachable()
    fpl_service.py       FplService singleton: fetches and caches FPL data
tests/                   pytest suite, one file per layer (test_db.py: schema and migrations)
```

**Request flow:** router → service → `FplService().get_data(key)` → cached data from FPL's `bootstrap-static` endpoint.

- **Routers** handle HTTP concerns only: path parameters, status codes, `HTTPException`. They call services and never touch `FplService` directly.
- **Services** are plain functions. They read collections through `FplService().get_data(...)` and return raw dicts, Pydantic models, or `None`/`[]` when nothing matches.
- **`FplService`** is a process-wide singleton. `get_fpl_api_data()` fetches all of bootstrap-static once and stores it in `fpl_data`. Every read is served from that cache.
- **Data refresh:** the lifespan hook fetches once at startup, and `/events/current-event/` refreshes before answering. No other endpoint triggers a fetch.

## Design decisions

### Configuration
- All URLs and tunables live in `.env`, are read in `src/util/config.py`, and are imported as constants. Never hardcode URLs.
- Required variables (`FPL_BASE_URL`, `FPL_BOOTSTRAP_STATIC_PATH`) go through `_get_env()`, which raises at import time if one is missing so the app fails fast. Optional ones, like `FPL_REQUEST_TIMEOUT` (default 10s), use `os.getenv` with a default.
- Endpoint URLs are built as base URL + path. To add an endpoint, add an `FPL_..._PATH` variable to `.env` and `.env.example`, then a constant in `config.py`.
- `.env` is gitignored; `.env.example` is committed and must stay in sync with it.

### Database
- Postgres on Supabase, accessed with SQLAlchemy (sync engine, psycopg 3 driver) and migrated with Alembic.
- `DATABASE_URL` (required) is the Supabase **session pooler** URI with the scheme changed to `postgresql+psycopg://` and `?sslmode=require` added. The session pooler works over IPv4 and supports prepared statements; the direct connection is IPv6-only. `DATABASE_CONNECT_TIMEOUT` (default 5s) is optional.
- Never print or log `DATABASE_URL`: it contains the password.
- `migrations/env.py` reads the URL from `config.py`, never from `alembic.ini`, and escapes `%` for configparser. If a URL is already set (as the tests do), it keeps that one.
- **Schema** (design in the FPL-7 spike's "Spike outcome" comment in Linear): `teams`, `element_types`, `elements`, `events`, `player_fixture_history` (one row per player per fixture, from `/element-summary/{id}/`) and `sync_runs`.
  - Column names are FPL's field names, so rows map 1:1 onto the Pydantic models. `elements` columns match `ElementResponse`, including which are `NOT NULL`.
  - Ids are FPL's, never generated (`autoincrement=False`). Decimals are `numeric`, timestamps are `timestamptz`.
  - Rows are upserted, never deleted. `events.most_selected` and the other player ids deliberately have no foreign key, so a missing player can't fail a sync.
- **Row-level security:** Supabase's Data API is off, and every table has RLS enabled with no policies, as a second layer. Autogenerate doesn't handle RLS, so every migration that creates a table must add `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`. `tests/test_db.py` fails if a table lacks it.
- **New migration:** change `src/db/models.py`, then autogenerate against the test database, not Supabase: `DATABASE_URL=$TEST_DATABASE_URL alembic revision --autogenerate -m "..."`. Review the file, add RLS for new tables, wrap lines over 100 characters, run the tests, then `alembic upgrade head` against Supabase.
- SQLAlchemy calls are blocking, so run them in `asyncio.to_thread` from async code, like FPL fetches.
- `/healthcheck` returns `{"status": "ok", "database": "ok" | "unavailable"}`, always with 200, so a database outage doesn't make a host restart the app.

### Fetching
- `requests` is blocking, so it runs in `asyncio.to_thread` with a timeout to keep the event loop free.
- `raise_for_status()` turns error responses into exceptions, and every `requests.exceptions.RequestException` is caught and logged. A failed fetch never raises and never crashes the app; any cached data is kept.

### Error responses
Use these status codes consistently:

| Situation | Status |
|---|---|
| FPL data never loaded (`FplDataUnavailableError`) | **503** `"FPL data is currently unavailable"`, raised by the global handler in `main.py` |
| Single-item lookup or filter finds nothing | **404** with a resource-specific detail, e.g. `"Team not found"` |
| Collection endpoint with no items | **200** with `[]` |
| Invalid path parameter type | **422** (FastAPI default) |

### Logging
- Use `logging.getLogger(__name__)` with `%s` placeholders, e.g. `logger.info("msg: %s", value)`. Never pass extra arguments without a placeholder: pytest's log capture raises on that.

## Testing

- pytest with pytest-cov. `pytest.ini` enforces **≥95% coverage** on `src` and `main`, currently at 100%.
- `tests/conftest.py`:
  - Sets the required env vars before importing `src`, so tests don't need a `.env` file (e.g. in CI).
  - `loaded_service` preloads the `FplService` singleton with sample data built by `make_element()` and `make_event()`, and resets it afterwards.
  - The autouse fixture `block_network` makes any real `requests.get` call fail the test. Mock it with `monkeypatch` when a test needs a response.
  - The autouse fixture `block_database` does the same for `database.engine.connect`. Patch `database.is_database_reachable` (or `engine.connect`) when a test hits `/healthcheck`.
  - Database tests use a real Postgres from `TEST_DATABASE_URL` (in `.env` locally, a service container in CI). `db_engine` migrates it from scratch once per run, and `db_session` rolls back each test's changes, even after `commit()`. The fixture refuses a Supabase URL. Without `TEST_DATABASE_URL`, the database tests fail with setup instructions.
- Async code is tested with `asyncio.run(...)`, so pytest-asyncio isn't needed. Routes are tested with `fastapi.testclient.TestClient`. Use it as a context manager only when the lifespan (startup fetch) should run.
- `config.py` import-time behavior is tested by running it as a fresh module (`load_fresh_config`), so the real module stays untouched.
- Every new code path needs tests, including its error paths.

## Environment

- Python **3.10+**. 3.9 is end-of-life, and GitHub's Ubuntu 26.04 runners don't provide it.
- CI runs two workflows on every push, both on Python 3.13: `.github/workflows/pylint.yml` lints, and `.github/workflows/tests.yml` runs pytest with the 95% coverage gate against a Postgres 17 service container. Each writes a summary table to the run page: test pass rate and failures via `.github/scripts/summarize_tests.py`, and pylint score and issues via `.github/scripts/summarize_pylint.py`.
- `.pylintrc` turns off docstring checks and `too-few-public-methods`, and ignores `alembic.context` and `alembic.op` for member checks because they're populated at runtime. Migration files disable `invalid-name` on their first line, because Alembic requires names like `revision` and file names start with the revision id (the template in `migrations/script.py.mako` adds it). Test files disable `redefined-outer-name` (pytest fixtures) at the top of the file. Fix any other warnings rather than silencing them.
- Runtime dependencies are pinned in `requirements.txt`; test and lint tools in `requirements-dev.txt`, which includes it.

## Known gaps

- If the startup fetch fails, only `/events/current-event/` retries. Other endpoints keep returning 503 until it's called or the app restarts.
