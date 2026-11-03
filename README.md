# fplAPI

A Python API wrapper for the Fantasy Premier League (FPL) platform, built to simplify data retrieval, analysis, and integration with FPL data.

## 🚀 Project Overview  
fplAPI provides a convenient and Pythonic interface to access FPL data from the official FPL endpoints. It abstracts away raw HTTP requests and provides structured data (players, teams, gameweeks, fixtures, etc.) in easy-to-use formats — enabling analysts, developers and FPL enthusiasts to integrate FPL data into their workflows with minimal effort. The main purpose for my use case is to develop an iOS application that utilizes this API service. The purpose of the iOS app is to create a more fluid experience for FPL players compared to the current official FPL app.

## 📦 Features  
- Fetch and parse player, team and fixture data from the official FPL API  
- Structured Python models (data classes/pydantic) for consistent access to data fields  
- Caching and rate-limit handling (if applicable)  
- Example scripts for data extraction, analysis and integration  
- Easy to extend: integrate into dashboards, automated pipelines, or data science workflows  

## 🧰 Tech Stack  
- **Python 3.10+**  
- HTTP client: `requests` (or `httpx`)  
- Database: PostgreSQL on Supabase, via SQLAlchemy and `psycopg`, with Alembic migrations  
- Data modeling: `dataclasses` or `pydantic`  
- (Optional) Caching layer: `functools.lru_cache` or `cachetools`  
- (Optional) Data analysis scripts: `pandas`, `numpy`

## ⚙️ Setup
You need Python 3.10+ and a Supabase project (see Database below).

```bash
git clone https://github.com/rafalopez15/fplAPI.git
cd fplAPI
python3 -m venv env            # the venv lives in env/; .env is the config file
source env/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env           # then fill in DATABASE_URL
alembic upgrade head           # create or update the database schema
```

`.env` is gitignored. These are its settings:

| Variable | Required | Description |
|---|---|---|
| `FPL_BASE_URL` | No | Base URL of FPL's API (default `https://fantasy.premierleague.com/api`). Only set it to point at a local mock |
| `FPL_PROXY_TIMEOUT` | No | Seconds before a live call to FPL from the manager endpoints times out (default 5) |
| `FPL_REQUEST_TIMEOUT` | No | Seconds before an FPL request times out (default 10) |
| `DATABASE_URL` | Yes | Supabase connection string (see below) |
| `DATABASE_CONNECT_TIMEOUT` | No | Seconds before a database connection attempt times out (default 5) |
| `DATABASE_POOL_SIZE` | No | Database connections each process keeps open (default 3) |
| `DATABASE_MAX_OVERFLOW` | No | Extra connections allowed under load (default 2) |
| `TEST_DATABASE_URL` | For tests | Local Postgres used by the test suite (see Tests and linting) |

The app won't start if a required variable is missing.

## 🗄️ Database (Supabase)
The API uses a PostgreSQL database hosted on Supabase's free plan.

1. Create a project at [supabase.com](https://supabase.com). Save the database password somewhere safe, because Supabase only shows it once.
2. Click **Connect** at the top of the project and copy the **Session pooler** connection string. It works over IPv4; the direct connection needs IPv6.
3. Make two changes to it and set it as `DATABASE_URL` in `.env`:
   - change the start from `postgresql://` to `postgresql+psycopg://`, so SQLAlchemy uses the psycopg 3 driver
   - add `?sslmode=require` to the end

   ```
   DATABASE_URL=postgresql+psycopg://postgres.<project-ref>:<password>@<pooler-host>.pooler.supabase.com:5432/postgres?sslmode=require
   ```
   If the password contains `@`, `:`, `/`, `?`, `#` or `%`, URL-encode those characters (e.g. `@` becomes `%40`).
4. Run `alembic upgrade head`, then start the app and open `/healthcheck`. It should return `{"status": "ok", "database": "ok"}`.

Keep in mind:
- Never commit `DATABASE_URL` or paste it anywhere public: it contains the password.
- Free projects pause after a week without activity. Restore the project from the Supabase dashboard if that happens.
- If you reset the database password in Supabase, update `DATABASE_URL` in `.env`, in Vercel and in the GitHub secret.

## 🔀 Migrations (Alembic)
Schema changes are versioned migrations in `migrations/versions/`. Alembic reads the connection string from `DATABASE_URL`, so **commands run against whichever database `.env` points at**.

```bash
alembic upgrade head                        # apply all pending migrations
alembic current                             # show the revision the database is at
alembic history                             # list all migrations
alembic revision -m "add players table"     # create a new, empty migration
alembic downgrade -1                        # undo the most recent migration
```

To change the schema:
1. Run `alembic revision -m "describe the change"`.
2. Fill in `upgrade()` and `downgrade()` in the new file, using `op.create_table`, `op.add_column` and so on.
3. Run `alembic upgrade head`, then check the result in the Supabase table editor.
4. Commit the migration file with the code that uses it.

Don't edit a migration that has already been applied: add a new one instead.

## ⏱️ Scheduled jobs (GitHub Actions)
`src/jobs/sync_bootstrap.py` copies FPL's `bootstrap-static` (teams, positions, players and gameweeks) and the season's fixtures into the database. GitHub Actions runs it every hour, and each run is recorded in the `sync_runs` table. A failed run leaves the previous data in place.

When a change to `migrations/`, `src/db/` or `alembic.ini` reaches `main`, the **Migrate database** workflow applies it to Supabase with `alembic upgrade head`.

Both workflows need the Supabase connection string as a repository secret:
1. On GitHub, go to **Settings → Secrets and variables → Actions → New repository secret**.
2. Name it `DATABASE_URL`, with the same value as `DATABASE_URL` in your `.env`.

Both can also be started by hand from the **Actions** tab (**Run workflow**). To run the sync locally against the database in your `.env`:

```bash
python -m src.jobs.sync_bootstrap
```

## ▶️ Running locally
```bash
fastapi dev main.py
```
The API runs at `http://127.0.0.1:8000`, with interactive docs at `/docs`. Endpoints are under `/api`, e.g. `/api/elements`. The server reloads when code changes.

The API serves FPL data from the database in `DATABASE_URL` and never calls FPL itself. Until the first sync succeeds, data endpoints return 503. To sync straight away instead of waiting for the hourly job, run `python -m src.jobs.sync_bootstrap`. `/healthcheck` shows when data was last synced (`last_sync`).

## 🐳 Running in Docker
The `Dockerfile` builds an image with only the API and its runtime dependencies. Production runs on Vercel and doesn't use it; it's for running the API locally the way a container host would.

```bash
docker build -t fplapi:local .
docker run --rm -p 8000:8000 --env-file .env fplapi:local
```

This serves the API at `http://127.0.0.1:8000`, reading the database in your `.env`, which is Supabase. To use the local test database instead, override `DATABASE_URL`. From inside a container, your Mac is `host.docker.internal`:

```bash
docker run --rm -p 8000:8000 --env-file .env \
  -e DATABASE_URL=postgresql+psycopg://fpl:fpl@host.docker.internal:5433/fpl_test fplapi:local
```

The test database is emptied by every test run, so sync it first: `DATABASE_URL=<test database URL> python -m src.jobs.sync_bootstrap`.

## 🚀 Deployment (Vercel)
The API is deployed to [Vercel](https://vercel.com) on the free Hobby plan, which is for personal, non-commercial use. Vercel detects FastAPI and serves the `app` in `main.py` as one function. Pushes to `main` deploy to production; every PR gets a preview URL.

The repo pins two things:
- `vercel.json` runs the function in `cle1` (Cleveland, AWS us-east-2), the same region as the Supabase database.
- `.python-version` pins Python 3.13, the same as CI and the Docker image. Vercel defaults to 3.12.

In the Vercel project, under **Settings → Environment Variables**, set:

| Variable | Value |
|---|---|
| `DATABASE_URL` | The **transaction pooler** URL, set for Production and Preview. Mark it **Sensitive**. |

Get it from **Connect → Transaction pooler** in Supabase and change it as in the Database section: `postgresql+psycopg://` at the start, `?sslmode=require` at the end. It ends in `:6543/postgres?sslmode=require`.

Vercel uses the transaction pooler, not the session pooler in `.env`. The session pooler gives each open connection one of only 15 slots, and every warm Vercel instance keeps a few connections open, so they can fill every slot and lock the hourly sync out. The transaction pooler shares connections between requests. The GitHub workflows and local runs stay on the session pooler.

That's the only required setting; the others have defaults. After a deploy, `https://<project>.vercel.app/healthcheck` should return `"database": "ok"` with a recent `last_sync`.

The first request after a few idle minutes takes a second or two while Vercel starts an instance. Migrations and the hourly sync still run from GitHub Actions, not Vercel.

## ✅ Tests and linting
The database tests run against a local Postgres in Docker, never Supabase. On macOS, [Colima](https://github.com/abiosoft/colima) is a lightweight way to run Docker:

```bash
brew install colima docker       # one-time install
colima start                     # start Docker (after each reboot)

# one-time: create the test database container on port 5433
docker run -d --name fplapi-test-db -e POSTGRES_USER=fpl -e POSTGRES_PASSWORD=fpl \
  -e POSTGRES_DB=fpl_test -p 5433:5432 postgres:17
docker start fplapi-test-db      # later sessions: start the existing container
```

Set `TEST_DATABASE_URL` in `.env` (the value from `.env.example` matches the container above). The tests migrate this database from scratch on every run and roll back each test's changes. They refuse to run against a Supabase URL.

```bash
python -m pytest                 # tests with a coverage report; fails under 95%
pylint $(git ls-files '*.py')    # lint with the settings in .pylintrc
```
Apart from the test database, the tests need no network access, and they use dummy values for the other settings. CI runs both on every pull request and on pushes to `main`, with its own Postgres container, and posts the results as a comment on the PR. The comment is updated on each push.
