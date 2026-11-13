---
paths:
  - "src/jobs/sync_bootstrap.py"
  - "src/services/teams.py"
  - "tests/test_sync_bootstrap.py"
---

# Hourly sync

- `sync_bootstrap.py` upserts bootstrap-static and `/fixtures/` in one transaction, recording each run in `sync_runs`. On failure the previous data stays.
- Then, even if that failed, in order:
  1. `sync_event_points()` stores points for each `data_checked` gameweek not stored yet, one transaction per gameweek, stopping at the first failure.
  2. `sync_team_names()` fetches names for up to 100 account teams `teams_tracked` doesn't have. A team FPL doesn't have is stored with a null name, so it isn't asked for again.
  3. `purge_snapshots()` deletes snapshots older than 30 days.
- Nothing is fetched at startup or per request.

## Kit colors

`KIT_COLORS` in `src/services/teams.py` is keyed by FPL's team `code` (stable across seasons, unlike `id`). **Each summer, add the promoted clubs and drop the relegated ones.** Nothing flags a missing club: the test only checks there are 20 entries, so CI stays green while new clubs get `null` colors.
