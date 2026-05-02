# Changelog

## 1.2.2 - 2026-05-03

- Fix: sort earthquake list by most recent first
- Feat: tighten earthquake filter to M3.0+, 500 km radius, last 5 days
- Perf: async HTTP layer with httpx, parallel health checks and AMeDAS prefetch
- Perf: increase weather/wind/earthquake cache TTL to 30 minutes
- Chore: remove author attribution from LICENSE
- Fix: update default coordinates to Tokyo Hino-shi in app.py
- Docs: add CHANGELOG and link it from README
- Docs: update default location references to Tokyo Hino-shi
- Fix: sync frontend DEFAULT_LOCATION with app.py defaults
- Docs: update screenshots with earthquake panel
- Docker: use /wgapp as clone target instead of /app
- Docker: fix restart by cloning to /app, drop unused quote_cache volume
- Docker: rm -rf /wgapp before clone to fix restart collision
- Docker: clone into /wgapp to match UV_PROJECT_ENVIRONMENT path
- Feat: add seismic activity panel (USGS M2.5+ earthquakes)
- Docs: fix ports example in README (8080 → 5099)
- Docker: always pull latest base image
- Iss: increase cache TTL to 15s, timeout to 10s, poll interval to 15s
- Docs: add Docker/Portainer deployment section to README
- Docker: clone and run from GitHub at startup
- Update screenshots
- Fork: remove countdown timer, fix wind map

All notable changes to this fork are documented here.

## [Unreleased]

## [1.2.1] — 2026-02-26

### Changed
- **Earthquake list order** — results are now sorted by most recent first (newest at the top) instead of by distance. CLOSEST stat now computes the minimum distance across all results rather than reading from the first entry.

## [1.2.0] — 2026-02-26

### Changed
- **Earthquake filter** — switched from the USGS M2.5+ weekly GeoJSON feed to the USGS FDSNWS query API; filter is now M3.0+, within 500 km of the configured weather location, over the last 5 days. A bounding box derived from the location is sent to the API to minimise payload size; exact haversine distance filtering is applied server-side. Results are sorted by distance (closest first).
- Cache key for `/api/earthquakes` is now per-location (`lat,lng`) as before; `radius_km` in the response reflects the new 500 km limit.

## [1.1.0] — 2026-02-23

### Changed
- **Async HTTP layer** — replaced `requests` with `httpx[http2]`; all Flask routes are now `async def` via `flask[async]` (asgiref). Concurrent browser requests no longer queue behind blocking outbound HTTP calls.
- **Parallel health checks** — `/api/health` now probes all five upstream endpoints simultaneously via `asyncio.gather()` instead of sequentially; worst-case latency drops from ~sum of all timeouts to the single slowest response.
- **Parallel AMeDAS prefetch** — station table and `latest_time.txt` are fetched concurrently on cache miss; second fetch (`map/{time}.json`) follows as before.

## [1.0.0] — 2026-02-22

Initial release of the 7ang0n1n3 fork, based on [elkentaro/weatherglass](https://github.com/elkentaro/weatherglass).

### Added
- **Seismic activity panel** — USGS M2.5+ weekly earthquake feed, no API key required
- **Wind & currents map** — Leaflet map with live particle animation via `leaflet-velocity@2.1.4`, replacing the previous `earth.nullschool.net` iframe
  - `/api/windgrid` endpoint: fetches u/v components from Open-Meteo batch API
  - Grid adapts dynamically to visible map bounds (north/south/east/west params)
  - Hard cap at 900 grid points; spacing scales with viewport
  - Country/coastline outlines visible alongside wind data
- **Thread-safe caches** — `threading.Lock()` guards on all shared caches (`_iss_cache_lock`, `_amedas_table_cache_lock`, `_windgrid_cache_lock`)
- **Docker/Portainer deployment** — `docker-compose.yml` clones from GitHub at startup; documented in README

### Changed
- ISS tracker: cache TTL 3 s → 15 s, HTTP timeout 5 s → 10 s, frontend poll interval 5 s → 15 s
- Default location set to Tokyo Hino-shi (lat/lng aligned between `app.py` and frontend)
- Docker: clone target changed from `/app` to `/wgapp` to avoid conflicts with the `UV_PROJECT_ENVIRONMENT` path; `rm -rf` before clone prevents restart collisions
- Docker: always pull latest base image (`pull_policy: always`)

### Removed
- Countdown timer panel, modal, associated CSS and JavaScript
- DEF CON / bunny theming (`static/bunny.png`)
- `requirements.txt` (replaced by `pyproject.toml` + `uv.lock`)
- Unused `quote_cache` Docker volume
