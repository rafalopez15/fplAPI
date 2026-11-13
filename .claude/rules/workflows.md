---
paths:
  - ".github/**"
  - ".gitleaks.toml"
  - ".gitleaksignore"
  - "vercel.json"
  - "Dockerfile"
  - ".dockerignore"
  - ".python-version"
---

# Workflows and hosting

## Secrets

- **Production jobs run only from `main`** (`if: github.ref == 'refs/heads/main'`) and use `environment: {name: production, deployment: false}`; that environment allows `main` only, so a branch's edited workflow can't read its secrets.
- `STAGING_DATABASE_URL` is a repository secret, since staging jobs run on PRs. `staging-admin` (main only) holds the staging Supabase key and test-user password.
- **Put secrets on the step that uses them, never the job's `env`**, so `pip install` never sees them.
- **A called workflow gets no secrets the caller doesn't pass**, environment secrets included; a missing one is an empty string, not an error. Pass them by name, and declare them `required` under `workflow_call.secrets`.
- Dependabot's runs get no secrets and a read-only token, so jobs that need them skip `dependabot[bot]`.

## Database workflows

- Every database job has a `production` (group `database`) and a `staging` (group `staging-database`) version, so a sync never runs mid-migration.
- The hourly sync calls `migrate.yml` first (`from_sync: true`); its production sync `needs` it, so a failed migration skips the sync. The calling job sets no `concurrency`: the same group in both would deadlock. In a called workflow `github.event_name` and `github.ref` are the caller's, which is why `from_sync` exists.
- `pg_cron` in Supabase starts the sync at :17 because GitHub skips most scheduled runs; the workflow's own `schedule` is only a backup. The trigger's SQL is in the README, not a migration.
- Scheduled and `repository_dispatch` workflows run from `main`'s copy only, so changes to them take effect after merge.

## Checks and alerts

- `ci.yml`: Pylint, Format, Tests (95% coverage, Postgres 17 service) and one PR comment found by the `<!-- ci-report -->` marker. Only that job has `pull-requests: write`.
- `smoke-test.yml` runs on Vercel's `vercel.deployment.success` dispatch and posts a **Smoke test** status. It needs `repository_dispatch` events on in Vercel's Git settings, and fails with 401 if Vercel Authentication is turned on for previews.
- `stale-sync-alert.yml` keeps one "Production sync is stale" issue open while `last_sync` is over 3 hours old. The run passes either way. It's a backstop, not a pager: GitHub skips most scheduled runs. Test by hand with `max_age_hours: 0.1`, again to see a comment, then with the default to close it.
- Find an issue by exact title from `gh issue list` without `--search`: the search index can miss a new issue.

## Actions and gitleaks

- **Pin actions by full commit hash** with the release as a comment (`@<hash> # v5.1.0`), never a tag. Dependabot updates them.
- `gitleaks.yml` scans full history. Its binary is pinned by `GITLEAKS_VERSION` and `GITLEAKS_SHA256`, bumped together by hand.
- **On a finding, rotate the secret first**: the repo is public. On a PR branch, rewrite the branch to drop the commit. Once on `main`, add the fingerprint (`<commit>:<file>:<rule>:<line>`, from the job log) to `.gitleaksignore` after rotating.
- A false positive gets the narrowest allowlist in `.gitleaks.toml` (path plus value regex) or its fingerprint. Never turn a rule off. Keep test URL passwords short (`fpl`, `pw`).

## Hosting

- Vercel Hobby, region `cle1` (`vercel.json`), Python from `.python-version`; keep it in step with CI's. No Vercel-specific code.
- Previews are public on purpose, so the iOS app can test against them.
- The `Dockerfile` is for local runs only. `.dockerignore` patterns use `**/` so they match in subfolders.
