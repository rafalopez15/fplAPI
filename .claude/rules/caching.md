---
paths:
  - "src/middleware/**"
  - "main.py"
  - "tests/test_middleware.py"
---

# Caching

Vercel's CDN does the caching; there are no in-memory caches, since Vercel instances don't share memory.

- **Synced routes:** `cache_synced_data` sets `SYNCED_CACHE` (`s-maxage=300, stale-while-revalidate=3600`) on a `GET` under `/api/` that answers 200 with no `Cache-Control` of its own. A new synced route is covered automatically.
- **Left alone:** live routes and stale snapshots (they set their own), `/api/me` (`never_cache_accounts` makes it `private, no-store`), errors (a cached 503 would outlive the outage) and `/healthcheck`.
- **`GET` only,** so CORS preflight `OPTIONS` 200s aren't cached.
- **Live routes** on success: `s-maxage=60` (manager, transfers, picks, live points, live fixtures) or 300 (history, league standings), with `stale-while-revalidate`. Errors send `no-store`; a stale snapshot sends `s-maxage=30`.
- **Cached responses must carry `Vary: Origin`** once CORS exists (FPL-69), or the CDN can serve a browser a copy cached without its CORS headers.
- **Checking it:** the CDN consumes `s-maxage` and sends clients `public, max-age=0, must-revalidate`, so check for `x-vercel-cache: HIT` on a repeat request, not the header.
