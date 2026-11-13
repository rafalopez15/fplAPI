---
paths:
  - "tests/**"
  - "pytest.ini"
---

# Tests

- `conftest.py` sets the required env vars before importing `src`, so no `.env` is needed.
- **Network and database are blocked by default** (autouse `block_network`, `block_database`). Mock FPL with `monkeypatch`; the `supabase` fixture in `test_account_deletion.py` mocks the Admin API. Patch `database.is_database_reachable` for `/healthcheck`.
- `seeded_session`: 2 teams, 4 positions, 3 players (Saka, Haaland, Palmer), gameweeks 8–10 and a successful sync. Change data by editing its rows. `client` is a `TestClient` on it.
- FPL-shaped builders (`make_team()`, `make_element()`, `make_event()`, `future_event()`) are shared.
- **Sign-in is off** (`SUPABASE_URL` empty). For account routes use `signed_in()` (or `signed_in(other_id)`), which needs the `jwks` fixture. Tests never call Supabase.
- Database tests need `TEST_DATABASE_URL`; `db_engine` migrates it once a run and `db_session` rolls back each test, even after `commit()`. It refuses a Supabase URL.
- Async code: `asyncio.run(...)`, no pytest-asyncio. `config.py`'s import-time behaviour: `load_fresh_config`.
- Test files disable `redefined-outer-name` at the top for fixtures.
