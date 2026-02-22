# Changelog

All notable changes to this fork are documented here.

## [Unreleased]

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
