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
| `FPL_BASE_URL` | Yes | Base URL of the official FPL API |
| `FPL_BOOTSTRAP_STATIC_PATH` | Yes | Path of FPL's `bootstrap-static` endpoint |
| `FPL_REQUEST_TIMEOUT` | No | Seconds before an FPL request times out (default 10) |
| `DATABASE_URL` | Yes | Supabase connection string (see below) |
| `DATABASE_CONNECT_TIMEOUT` | No | Seconds before a database connection attempt times out (default 5) |

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
- If you reset the database password in Supabase, update `DATABASE_URL` in `.env`.

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

## ▶️ Running locally
```bash
fastapi dev main.py
```
The API runs at `http://127.0.0.1:8000`, with interactive docs at `/docs`. Endpoints are under `/api`, e.g. `/api/elements`. The server reloads when code changes.

## ✅ Tests and linting
```bash
python -m pytest                 # tests with a coverage report; fails under 95%
pylint $(git ls-files '*.py')    # lint with the settings in .pylintrc
```
The tests don't need a `.env` file, network access or a database. CI runs both on every push.
