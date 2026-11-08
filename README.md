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
# Supabase's schema comes from the Migrate database workflow (see Migrations), not from here.
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
| `SUPABASE_URL` | No | The Supabase project whose sign-in tokens `/api/me` accepts, e.g. `https://<ref>.supabase.co`. Without it, account routes return 503 (see Sign-in) |
| `SUPABASE_SECRET_KEY` | No | The same project's secret key, for deleting accounts (`DELETE /api/me`). Without it, deleting returns 503. Never commit or log it |
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
4. Add the GitHub secret (see Scheduled jobs below) and run **Migrate database** from the Actions tab: it creates the schema. Then start the app and open `/healthcheck`. It should return `{"status": "ok", "database": "ok"}`.

Keep in mind:
- Never commit `DATABASE_URL` or paste it anywhere public: it contains the password.
- Free projects pause after a week without activity. Restore the project from the Supabase dashboard if that happens.
- If you reset the database password in Supabase, update `DATABASE_URL` in `.env`, in Vercel and in the GitHub secret.

## 🔀 Migrations (Alembic)
Schema changes are versioned migrations in `migrations/versions/`. Alembic reads the connection string from `DATABASE_URL`, so **commands run against whichever database `.env` points at**. Run them against the local test database (`DATABASE_URL=$TEST_DATABASE_URL alembic ...`). Supabase is migrated only by the **Migrate database** workflow: staging on the PR, production on merge, with the hourly sync held off while it runs. Don't run `alembic upgrade head` against Supabase yourself.

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
3. Run the tests: they migrate the test database from scratch, so a broken migration fails them.
4. Commit the migration file with the code that uses it, and open a PR. **Migrate database** applies it to staging for the PR's preview; check the result in staging's table editor. It reaches production when the PR merges.

Don't edit a migration that has already been applied: add a new one instead.

## ⏱️ Scheduled jobs (GitHub Actions)
`src/jobs/sync_bootstrap.py` copies FPL's `bootstrap-static` (teams, positions, players and gameweeks) and the season's fixtures into the database, then each finished gameweek's points per player (once per gameweek, after FPL confirms its bonus points; the first run backfills the season so far). GitHub Actions runs it every hour, started by Supabase (see [Hourly trigger](#hourly-trigger-supabase-pg_cron)), and each run is recorded in the `sync_runs` table. A failed run leaves the previous data in place.

When a change to `migrations/`, `src/db/` or `alembic.ini` reaches `main`, the **Migrate database** workflow applies it to Supabase with `alembic upgrade head`.

Both workflows have a job for production and one for [staging](#staging-database-for-previews). They need each database's session pooler connection string as a repository secret (**Settings → Secrets and variables → Actions → New repository secret**):

| Secret | Value |
|---|---|
| `DATABASE_URL` | Production's session pooler URL, the same as `DATABASE_URL` in your `.env` |
| `STAGING_DATABASE_URL` | Staging's session pooler URL |

Both can also be started by hand from the **Actions** tab (**Run workflow**). Started from `main`, they run against production and staging; started from any other branch, against staging only. To run the sync locally against the database in your `.env`:

```bash
python -m src.jobs.sync_bootstrap
```

### Staging database (for previews)
Vercel preview deployments use a second Supabase project, `fpl-api-staging`, so unmerged code never reads or writes production data. It's set up like production (free plan, us-east-2, Data API off, RLS from the migrations) and holds only test data, so it's safe to reset.

- **Migrations:** a pull request that touches `migrations/`, `src/db/` or `alembic.ini` runs **Migrate database** against staging, then syncs staging with the PR's code, so its preview has the new schema and data. Production migrates only when the PR merges.
- **Data:** the hourly sync also syncs staging (started by the same pg_cron trigger as production), which keeps the free project from pausing after a week without activity.
- **Vercel:** `DATABASE_URL` for **Preview** is staging's transaction pooler URL, and `SUPABASE_URL` for **Preview** is staging's project URL. Production keeps production's.
- **Sign-in:** previews only accept tokens from staging's Supabase Auth, so an iOS Debug build pointed at a preview signs in against staging (see Sign-in).

To set it up:
1. In Supabase, create a project named `fpl-api-staging` in the same region as production. Turn off the Data API (**Project Settings → Data API**).
2. Under **Connect**, copy both pooler URIs and change them as in the Database section (`postgresql+psycopg://`, `?sslmode=require`):
   - **Session pooler** (`:5432`) → GitHub secret `STAGING_DATABASE_URL`.
   - **Transaction pooler** (`:6543`) → Vercel `DATABASE_URL`, **Preview** environment only, marked **Sensitive**.
3. Run **Migrate database** from the Actions tab on any branch: it creates the schema and runs the first sync on staging.

**If staging gets ahead of `main`**, e.g. after a migration PR is closed without merging, the next migration PR fails with "Can't locate revision". Undo the abandoned migration by running `alembic downgrade <main's head revision>` with `DATABASE_URL` set to staging's session pooler URL, from the abandoned branch (which still has the migration file). Or recreate the staging project and repeat the setup. Two open PRs with migrations conflict on staging the same way; merge or rebase one first.

### Sign-in (Supabase Auth)
Account routes (`/api/me...`) need a Supabase access token in `Authorization: Bearer <token>`. The API checks it against the project's public keys at `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`, which must be asymmetric (ES256 or RSA): **Project Settings → JWT Keys**. FPL routes never look at the token. Design and decisions: the FPL-11 design doc in Linear.

Sign-in is a 6-digit code by email, set up on staging only for now (FPL-47). Production's setup, Sign in with Apple and email from our own domain come with FPL-55, before TestFlight.

Staging's setup:
- **Authentication → Sign In / Providers → Email:** on, Confirm email on, OTP length 6, OTP expiry 600 seconds.
- **Authentication → Emails → SMTP Settings:** custom SMTP through Resend's test sender, because Supabase only lets you edit templates with custom SMTP. Sender `onboarding@resend.dev`, host `smtp.resend.com`, port `465`, username `resend`, password a Resend API key with sending access. The test sender only delivers to the address the Resend account was created with, and Gmail files it as spam until marked otherwise. The sender address must be `onboarding@resend.dev`: any other domain fails with `550 ... domain is not verified`.
- **Authentication → Emails → Templates:** **Confirm signup** (sent on a first sign-in) and **Magic Link** (later ones) send `{{ .Token }}` instead of the link.

To check sign-in works without the app, request a code, then exchange it for a session. The publishable key is under **Project Settings → API Keys**; run these in your own terminal, not anywhere they're logged:
```bash
curl -i https://<ref>.supabase.co/auth/v1/otp -H "apikey: $KEY" -H "Content-Type: application/json" \
  -d '{"email": "<address>", "create_user": true}'
curl -s https://<ref>.supabase.co/auth/v1/verify -H "apikey: $KEY" -H "Content-Type: application/json" \
  -d '{"type": "email", "email": "<address>", "token": "<code>"}'
```
The second returns a JSON session; its `access_token` works as the Bearer token for `/api/me` on a preview.

**Deleting accounts** (`DELETE /api/me`) uses Supabase's Admin API, which needs the project's secret key: **Project Settings → API Keys → Secret keys**, a key named `fpl_account_deletion`. It goes in Vercel as `SUPABASE_SECRET_KEY`, marked **Sensitive**, staging's for **Preview**. It bypasses all of Supabase's security, so never paste it anywhere else; if it leaks, revoke it there and create a new one.

### Hourly trigger (Supabase pg_cron)
GitHub runs scheduled workflows on a best-effort basis: on 2 November 2026 it ran 2 of about 27 hourly syncs. So Supabase starts the sync instead. Every hour at :17 UTC, a `pg_cron` job in the database uses `pg_net` to call GitHub's [workflow dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event), the same thing the **Run workflow** button does. These runs show in Actions as `workflow_dispatch`, started by the token's owner.

The workflow's own `schedule` stays as a backup. If both fire, the `database` concurrency group queues the second run, and the sync skips rows that haven't changed.

None of this is in the repo or in a migration. Migrations also run against the test databases, which don't have `pg_cron`, `pg_net` or Vault. To set it up (or recreate it):

1. **Create a GitHub token.** In GitHub, go to **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**. Set the resource owner to your account, repository access to **Only select repositories** → this repository, and **Actions: Read and write** as the only permission, with an expiry date. "Public repositories" access is read-only, and GitHub answers it with 403 "Resource not accessible by personal access token".
2. **Enable the extensions.** In Supabase, go to **Database → Extensions** and enable `pg_cron` and `pg_net`.
3. **Store the token in Vault.** In Supabase's **SQL Editor**, run this with the token in place of `<token>`. This is the only place the token goes; don't save the query.
   ```sql
   select vault.create_secret('<token>', 'github_dispatch_token', 'Starts sync-bootstrap.yml in GitHub Actions');
   ```
4. **Schedule the job.** The SQL reads the token from Vault each time it runs:
   ```sql
   select cron.schedule('sync-bootstrap', '17 * * * *', $$
     select net.http_post(
       url := 'https://api.github.com/repos/rafalopez15/fplAPI/actions/workflows/sync-bootstrap.yml/dispatches',
       headers := jsonb_build_object(
         'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets
                                        where name = 'github_dispatch_token'),
         'Accept', 'application/vnd.github+json',
         'X-GitHub-Api-Version', '2022-11-28',
         'User-Agent', 'fplAPI-sync-trigger'),
       body := '{"ref": "main"}'::jsonb
     )
   $$);
   ```

**Token expiry:** 1 February 2027. Rotate it before then: create a new token as in step 1, then run
```sql
select vault.update_secret(
  (select id from vault.secrets where name = 'github_dispatch_token'), '<new token>');
```
and update the date above.

**Checking it.** In the SQL Editor:
```sql
-- Did the cron job run? Look for status 'succeeded'.
select start_time, status, return_message from cron.job_run_details
order by start_time desc limit 5;

-- What did GitHub answer? 204 means the run was started; 401 means the token is wrong or expired;
-- 403 means it lacks Actions write access to this repository.
-- pg_net keeps responses for about 6 hours.
select created, status_code, content from net._http_response
order by created desc limit 5;
```
`last_sync` in `/healthcheck` should never be much more than an hour old. `last_points_sync` moves only when a gameweek's bonus points are confirmed, so about once a week. To stop the trigger, run `select cron.unschedule('sync-bootstrap');`.

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
| `DATABASE_URL` | Production: production's **transaction pooler** URL. Preview: [staging's](#staging-database-for-previews). Mark both **Sensitive**. |
| `SUPABASE_URL` | Optional. Preview: staging's project URL (`https://<ref>.supabase.co`). Production: production's, once its sign-in is set up (FPL-55). Not secret. |
| `SUPABASE_SECRET_KEY` | Optional, for account deletion. Preview: staging's secret key. Production: production's, with FPL-55. Mark it **Sensitive**. |

Get it from **Connect → Transaction pooler** in Supabase and change it as in the Database section: `postgresql+psycopg://` at the start, `?sslmode=require` at the end. It ends in `:6543/postgres?sslmode=require`.

Vercel uses the transaction pooler, not the session pooler in `.env`. The session pooler gives each open connection one of only 15 slots, and every warm Vercel instance keeps a few connections open, so they can fill every slot and lock the hourly sync out. The transaction pooler shares connections between requests. The GitHub workflows and local runs stay on the session pooler.

`DATABASE_URL` is the only required setting; the others have defaults. After a deploy, `https://<project>.vercel.app/healthcheck` should return `"database": "ok"` with a recent `last_sync`. The **Smoke test** workflow checks this automatically after every deployment and reports it on the commit; to run the same check yourself:

```bash
.github/scripts/smoke_test.sh https://fpl-api-six.vercel.app
```

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
black .                          # format the code (Black's defaults: 88 characters)
black --check .                  # what CI checks: fails if any file would change
```
The one-time Black reformat is listed in `.git-blame-ignore-revs`, so `git blame` skips it and shows who actually wrote each line. GitHub's blame view does this automatically; locally, run this once in your clone:
```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```
Apart from the test database, the tests need no network access, and they use dummy values for the other settings. CI runs all three on every pull request and on pushes to `main`, with its own Postgres container, and posts the results as a comment on the PR. The comment is updated on each push.
