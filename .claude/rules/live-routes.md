---
paths:
  - "src/util/fpl_client.py"
  - "src/routers/live.py"
  - "src/routers/managers.py"
  - "src/routers/leagues.py"
  - "src/routers/events.py"
  - "src/services/managers.py"
  - "src/services/leagues.py"
  - "src/services/events.py"
  - "src/services/snapshots.py"
  - "src/services/transfer_points.py"
  - "src/services/fpl_rows.py"
  - "src/models/manager.py"
  - "src/models/league.py"
  - "tests/test_snapshots.py"
  - "tests/test_managers.py"
  - "tests/test_leagues.py"
  - "tests/test_event_*.py"
  - "tests/test_transfer_points.py"
  - "tests/test_fpl_client.py"
---

# Live routes

`/managers/...`, `/leagues/{id}`, `/events/{id}/live` and `/events/{id}/fixtures` call FPL per request; nothing else does.

## Calling FPL

- All FPL calls go through `fpl_client.py`, with a timeout and `HEADERS`. Live fetches use `_get_live_json()` and `FPL_PROXY_TIMEOUT` (5s), raising `FplNotFoundError` for FPL's 404 and `FplUnavailableError` for everything else, FPL's HTML "game is being updated" page included.
- **End the read transaction before calling FPL** in a request that queried first, so a slow FPL doesn't hold a pooler connection.
- A row FPL sends that we can't read is skipped and logged (`fpl_rows.readable()`), never a 500.

## Snapshots

- Every live route goes through `Live.call(key, route, fetch)` with a `LiveRoute(model, cache, keep=...)`. It saves each good answer to `fpl_snapshots`; on `FplUnavailableError` it serves the saved copy as 200 with `X-Data-Stale-As-Of` and `s-maxage=30`, else 503.
- **Save the response model's output, never FPL's raw JSON**, so real names can't reach the table (`tests/test_snapshots.py` checks every route).
- 404s are never served from a snapshot. Saving and loading never fail a request.
- A snapshot is validated against the current model when loaded. Adding a required field to a live model makes every old snapshot unusable (503 while FPL is down) until it's refreshed, so make new fields optional.
- `keep` limits what public routes can write: league standings page 1 only and not empty; no `[]` live points or fixtures; no picks before the first deadline.
- A stale `/picks` without `?event=` is the last squad saved, so clients must read the gameweek from `entry_history.event`.

## Route behaviour

- **Leagues on `/managers/{id}`:** classic leagues from the same `entry/{id}/` call, invitational first then smallest. Head-to-head or unreadable leagues are left out.
- **League standings:** never `player_name`. Teams that just joined are only in FPL's `new_entries` until the next gameweek update, so the response returns them as `new_entries` (first page of 50). A page past the end is 200 with no standings. FPL's 404 for a head-to-head league is `"League not found"`.
- **Picks:** without `?event=`, one extra call to `fetch_manager()` for `current_event`; 404 before the first deadline.
- **Live points:** flattened to `id`, `total_points`, `minutes` per player. 200 `[]` before the gameweek starts.
- **Live fixtures:** FPL answers 200 `[]` both for a gameweek it doesn't have and for one with every match postponed, so on `[]` the route checks `events`: stored is 200 `[]`, otherwise 404 `"Event not found"`. Clients treat `finished_provisional` as full time; `finished` lags a day.
- **Net points per transfer** (`transfer_points.py`): Wildcard and Free Hit weeks list every swap tried, so each gameweek is reduced to its real changes and the rest are `is_churn`. Points are null for churn, before the gameweek is stored, and when the database can't be read.
- A web client needs `X-Data-Stale-As-Of` in CORS's `Access-Control-Expose-Headers` (FPL-69).
