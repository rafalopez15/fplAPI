---
paths:
  - "src/util/auth.py"
  - "src/util/supabase_admin.py"
  - "src/routers/me.py"
  - "src/routers/notes.py"
  - "src/services/profiles.py"
  - "src/services/user_teams.py"
  - "src/services/notes.py"
  - "src/models/profile.py"
  - "src/models/user_team.py"
  - "src/models/note.py"
  - "src/jobs/manage_test_users.py"
  - "tests/test_auth.py"
  - "tests/test_account_deletion.py"
  - "tests/test_user_teams.py"
  - "tests/test_notes.py"
  - "tests/test_manage_test_users.py"
---

# Accounts

- **Every query filters by the user id from the token.** Account routes take a plain `get_session`, not `DataSession`.
- **Token checks (`CurrentUser`):** signature against Supabase's JWKS with `ES256`/`RS256` only (never the token's own `alg`), plus `exp`, `aud == "authenticated"` and `iss`. Don't turn on `PyJWKClient`'s `cache_keys`: it never expires keys, so a revoked key would keep working.
- **Anonymous sign-ins stay off in Supabase.** They also get `aud: "authenticated"`; if they're ever wanted, reject `is_anonymous: true` first.
- `SUPABASE_URL` unset means account routes return 503; nothing else changes.
- **Anything that writes an account table calls `ensure_profile()` first.** `profiles` has no foreign key to `auth.users` (the test database has no `auth` schema). Account tables reference `profiles` with `ON DELETE CASCADE`.

## Deleting an account

- Delete the rows, call Supabase's Admin API, and only then commit; roll back and 503 if Supabase fails. **This is the one allowed transaction held across an HTTP call.**
- Only a 404 with `error_code: "user_not_found"` counts as already deleted.
- `deleted_accounts` keeps every deleted id forever; `ensure_profile()` refuses them, so a write with a deleted user's still-valid token is 401. Both paths take a per-account advisory lock.
- Log the user id and status on failure, never the key or the body.

## Teams and notes

- **`user_teams`:** `relation` is `mine` or `following`. `PUT` is an upsert; adding checks FPL (one call), switching doesn't. Limits stop scripts only: 1,000 teams (409) and 60 new an hour (429 with `Retry-After`).
- **`teams_tracked`** stores each team's name once. A team without a row comes back `name: null` until the hourly sync fills it. It's the team's name, never the manager's.
- **Notes:** the device makes the id and every write sends the whole note. The newer `updated_at` wins, and the response is always the stored note. Deleting is a write (`deleted_at`), leaving a tombstone; undo is a later `PUT`.
- `GET /me/notes?since=` pages by `(synced_at, id)`, 500 a page, with the last cursor held 5s behind the clock. The cursor is opaque.

## Status codes

| Situation | Status |
|---|---|
| Missing, malformed, expired, forged or HS256 token, or a deleted account writing | 401 `"Not signed in"` with `WWW-Authenticate: Bearer` |
| `SUPABASE_URL` unset or Supabase's keys unreachable | 503 `"Sign-in is unavailable right now"` |
| `DELETE /api/me` fails or `SUPABASE_SECRET_KEY` unset | 503 `"Couldn't delete your account right now"` |
| 1,000 teams already | 409 `"Team limit reached"` |
| 61st new team within an hour | 429 `"Too many teams added, try again later"` |
| Note missing or another user's (never 403) | 404 `"Note not found"` |
| A cursor the API didn't issue | 422 `"Invalid cursor"` |

## Test users (`manage_test_users.py`)

Staging only: it refuses unless `SUPABASE_URL` and `DATABASE_URL` are both staging's, and refuses emails outside `@fplsocial.dev`. Run through `test-users.yml`, never as an endpoint.
