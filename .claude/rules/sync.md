---
paths:
  - "src/jobs/sync_bootstrap.py"
  - "src/services/teams.py"
  - "tests/test_sync_bootstrap.py"
  - "src/jobs/gameweek_pass.py"
  - "src/services/team_gameweeks.py"
  - "tests/test_gameweek_pass.py"
---

# Hourly sync

- `sync_bootstrap.py` upserts bootstrap-static and `/fixtures/` in one transaction, recording each run in `sync_runs`. On failure the previous data stays.
- Then, even if that failed, in order:
  1. `sync_event_points()` stores points for each `data_checked` gameweek not stored yet, one transaction per gameweek, stopping at the first failure.
  2. `sync_team_names()` fetches names for up to 100 account teams `teams_tracked` doesn't have. A team FPL doesn't have is stored with a null name, so it isn't asked for again.
  3. `purge_snapshots()` deletes snapshots older than 30 days.
- Nothing is fetched at startup or per request.

## Gameweek pass

`gameweek_pass.py` runs as its own job after the sync, even if the sync failed, never after a failed migration.

- **Own concurrency groups** (`gameweek-pass`, `staging-gameweek-pass`) and a 55-minute timeout. Never put it in `database` / `staging-database`: a 40-minute job there holds migrations up, and GitHub cancels a migration run left waiting (why: FPL-139).
- Order: purge leagues idle 14 days, refresh each tracked league's teams, then each team behind the latest passed deadline: `/transfers/` once, `picks` per missing gameweek.
- **A row per team per gameweek,** even a quiet one. A picks 404 means the team hadn't started, except for the latest gameweek, which waits for the next run.
- **Commit per team,** saving progress in a `finally`, so the time limit or FPL's first 503 stops it without losing work. `teams_tracked.last_event` is where the next run carries on.
- New FPL calls go through `Pacer.wait()`. Tests patch `job.time` with a fake clock.

## Kit colors

`KIT_COLORS` in `src/services/teams.py` is keyed by FPL's team `code` (stable across seasons, unlike `id`). **Each summer, add the promoted clubs and drop the relegated ones.** Nothing flags a missing club: the test only checks there are 20 entries, so CI stays green while new clubs get `null` colors.
