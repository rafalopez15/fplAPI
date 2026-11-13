# fplAPI

FastAPI service serving Fantasy Premier League (FPL) data under `/api`, from a Postgres copy of FPL's API that an hourly job keeps current. The FPL Social iOS app is its main client.

Rules for one area load from `.claude/rules/` when you open its files: `database.md`, `live-routes.md`, `caching.md`, `accounts.md`, `sync.md`, `testing.md`, `workflows.md`. How-tos for people are in `README.md`; decisions and their history are in Linear (team FPL Social, Architecture doc).

## Working guidelines

- State assumptions, and when a request can be read more than one way, lay out the options instead of picking one silently.
- Write the smallest change that solves the problem. No speculative features or configuration nobody asked for.
- Touch only what the task needs; point out other problems instead of fixing them unasked.
- Make each task verifiable, e.g. a test that fails before the fix and passes after.

## Commands

```bash
source env/bin/activate              # venv lives in env/ (not .env, which is config)
pip install -r requirements-dev.txt  # app, test and lint dependencies
fastapi dev main.py                  # run locally with reload
python -m pytest                     # tests + coverage (fails under 95%)
python -m pytest tests/test_event_fixtures.py -k orders   # one file or test
pylint $(git ls-files '*.py')        # lint, as CI does
black .                              # format before committing; CI checks it
python -m src.jobs.sync_bootstrap    # sync FPL into the database in DATABASE_URL
colima start && docker start fplapi-test-db  # local test database (README)
```

## Git and PRs

- Commit or push only when asked.
- One short-lived branch per Linear story from an up-to-date `main`, named with the issue id (`fpl-8-sync-bootstrap`). Never commit to a branch whose PR has merged.
- Logical commits, each leaving the app working. Short imperative subject, then a body with what and why.
- PRs merge with a merge commit, never squash or rebase (`.git-blame-ignore-revs` depends on the hashes).
- PR title `FPL-<n>: <what it does>`. Description: `Closes FPL-<n>.` or `Part of FPL-<n>.`, one or two sentences, `## Changes`, `## Testing` (say what wasn't checked). Plain sentences, no emoji or hype.

## Code

- **Layers:** router (HTTP only) → service (plain functions, session first, return Pydantic models via `model_validate`) → SQLAlchemy or `fpl_client`. Lists in FPL id order; `None`/`[]` when nothing matches.
- **Endpoints are plain `def`**, never `async def`: SQLAlchemy calls block. From async code use `asyncio.to_thread`.
- **Id path parameters** use the types in `src/routers/params.py`, never a bare `int`, so an id Postgres can't store is a 422, not a 500.
- **Database routes** take `session: DataSession` (503 until a sync has succeeded). Live and account routes take a plain `get_session`.
- **Synced `GET` routes are CDN-cached by default** (`cache_synced_data`). A route that must stay fresh sets its own `Cache-Control`.
- **Settings:** secrets and per-environment values live in `.env`, read in `src/util/config.py`. A new setting must be optional with a default, or the deployed API won't start until it's set in Vercel. Keep `.env.example` in step. FPL URLs are constants in `fpl_client.py`, not settings.
- **Never log or print `DATABASE_URL`** or any secret.
- **Logging:** `logging.getLogger(__name__)` with `%s` placeholders; extra arguments without a placeholder make pytest's log capture raise.
- **Don't add a `pyproject.toml`:** Vercel would install from it instead of `requirements.txt` and production breaks (why: FPL-86). Black runs with its defaults for the same reason.
- **Formatting:** Black, line length 88. Black doesn't split long strings, comments or docstrings: rewrap them by hand. Fix Pylint warnings rather than silencing them.
- **Comments:** short. Say why, not what; no ticket numbers or history.
- Every new code path needs tests, error paths included. Coverage gate is 95% with branches; it's at 100%.

## Product rules

- **Managers' real names never leave the API** (why: FPL-11, FPL-45). Response models leave them out; any new route built from FPL manager data needs the same test as `test_real_names_never_leave_the_api`.
- **Accounts are optional.** FPL routes never read `Authorization`, and viewing any team never needs an account.
- **A team's leagues on `/managers/{id}` are public by decision**, because FPL exposes the same list. Revisit only if FPL accounts get linked to app accounts.
- **`/api/me` responses are never cached** (`private, no-store` from `never_cache_accounts` in `src/middleware/cache.py`), so the CDN can't serve one user's data to another.

## Status codes

- 503 `"FPL data is currently unavailable"` before the first sync or with the database down (handlers in `main.py`).
- Live route with FPL down: 200 with the saved copy and `X-Data-Stale-As-Of`, else 503 `"FPL is unavailable right now"`.
- 404 with a resource-specific detail (`"Team not found"`, `"Event not found"`, `"League not found"`, `"Manager not found"`) and `no-store`. A collection with nothing in it is 200 `[]`.
- 401 `"Not signed in"` with `WWW-Authenticate: Bearer` for a missing or bad token. The rest of the account codes are in `accounts.md`.
