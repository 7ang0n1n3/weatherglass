#!/usr/bin/env python3
"""
WeatherGlass — Standalone weather dashboard
Standalone weather dashboard with configurable location.
"""

import logging
import math
import time
import threading
import requests
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("weatherglass")

# ─── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_LAT = 35.6790
DEFAULT_LNG = 139.3935
DEFAULT_LABEL = "Tokyo Hino-shi, Japan"
DEFAULT_TZ = "Asia/Tokyo"

# ─── Caches ──────────────────────────────────────────────────────────────────

_weather_cache = {}  # keyed by "lat,lng" → {"data", "ts"}
_weather_cache_lock = threading.Lock()
WEATHER_CACHE_TTL = 1800  # 30 minutes

_windgrid_cache = {}  # keyed by "lat,lng" → {"data", "ts"}
_windgrid_cache_lock = threading.Lock()
WINDGRID_CACHE_TTL = 1800  # 30 minutes

_iss_cache = {"data": None, "ts": 0}
_iss_cache_lock = threading.Lock()
ISS_CACHE_TTL = 15

# ─── AMeDAS (JMA Japan-only station observations) ───────────────────────────

_amedas_cache = {"data": None, "ts": 0, "station": None, "lat": None, "lng": None}
_amedas_cache_lock = threading.Lock()
AMEDAS_CACHE_TTL = 300

_amedas_table_cache = {"data": None, "ts": 0}
_amedas_table_cache_lock = threading.Lock()

_eq_cache = {}  # keyed by "lat,lng" -> {"data", "ts"}
_eq_cache_lock = threading.Lock()
EQ_CACHE_TTL = 1800  # 30 minutes

JMA_AMEDAS_BASE = "https://www.jma.go.jp/bosai/amedas/data"
JMA_AMEDAS_TABLE = "https://www.jma.go.jp/bosai/amedas/const/amedastable.json"
JMA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Accept": "application/json,*/*",
}


def _get_amedas_table():
    now = time.time()
    with _amedas_table_cache_lock:
        if _amedas_table_cache["data"] and (now - _amedas_table_cache["ts"]) < 86400:
            return _amedas_table_cache["data"]
    try:
        r = requests.get(JMA_AMEDAS_TABLE, headers=JMA_HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        with _amedas_table_cache_lock:
            _amedas_table_cache["data"] = data
            _amedas_table_cache["ts"] = now
        return data
    except Exception as e:
        log.warning(f"AMeDAS table fetch failed: {e}")
        with _amedas_table_cache_lock:
            return _amedas_table_cache["data"]


def _find_nearest_station(lat, lon, table, obs_data=None):
    best_id, best_dist = None, float("inf")
    for sid, info in table.items():
        if obs_data:
            sobs = obs_data.get(sid)
            if not sobs or "temp" not in sobs:
                continue
            if isinstance(sobs["temp"], list) and len(sobs["temp"]) >= 2 and sobs["temp"][1] != 0:
                continue
        slat = info["lat"][0] + info["lat"][1] / 60.0
        slon = info["lon"][0] + info["lon"][1] / 60.0
        d = math.sqrt((slat - lat) ** 2 + (slon - lon) ** 2)
        if d < best_dist:
            best_dist = d
            best_id = sid
    return best_id, best_dist


def _is_japan(lat, lng):
    """Check if coordinates are roughly within Japan's bounding box."""
    return 24.0 <= lat <= 46.0 and 122.0 <= lng <= 154.0


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("weather.html")


@app.route("/api/weather")
def api_weather():
    """Return cached Open-Meteo forecast. Accepts ?lat=...&lng=... query params."""
    lat = request.args.get("lat", DEFAULT_LAT, type=float)
    lng = request.args.get("lng", DEFAULT_LNG, type=float)
    tz = request.args.get("tz", "auto")

    cache_key = f"{lat:.4f},{lng:.4f}"
    now = time.time()

    with _weather_cache_lock:
        cached = _weather_cache.get(cache_key)
        if cached and (now - cached["ts"]) < WEATHER_CACHE_TTL:
            return jsonify({
                "weather": cached["data"],
                "cached": True,
                "age": int(now - cached["ts"]),
            })

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lng}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        "weather_code,wind_speed_10m,wind_direction_10m,precipitation"
        "&hourly=temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,"
        "weather_code,wind_speed_10m"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,precipitation_probability_max,wind_speed_10m_max,"
        "sunrise,sunset"
        f"&timezone={tz}&forecast_days=4"
    )

    try:
        log.info(f"Weather fetch: lat={lat} lng={lng} tz={tz}")
        log.info(f"Weather URL: {url}")
        r = requests.get(url, timeout=15)
        log.info(f"Weather response: status={r.status_code} size={len(r.content)}")
        if not r.ok:
            log.error(f"Weather API error response: {r.text[:500]}")
        r.raise_for_status()
        data = r.json()
        # Check if Open-Meteo returned an error in JSON
        if "error" in data and "reason" in data:
            log.error(f"Open-Meteo error: {data}")
            return jsonify({"error": data.get("reason", "Unknown API error")}), 502
        log.info(f"Weather OK: keys={list(data.keys())}")
        with _weather_cache_lock:
            _weather_cache[cache_key] = {"data": data, "ts": now}
        return jsonify({"weather": data, "cached": False, "age": 0})
    except Exception as e:
        with _weather_cache_lock:
            cached = _weather_cache.get(cache_key)
            if cached:
                return jsonify({
                    "weather": cached["data"],
                    "cached": True,
                    "age": int(now - cached["ts"]),
                    "error": str(e),
                })
        return jsonify({"error": str(e)}), 502


@app.route("/api/amedas")
def api_amedas():
    """Return live AMeDAS observation for nearest station. Japan only."""
    lat = request.args.get("lat", DEFAULT_LAT, type=float)
    lng = request.args.get("lng", DEFAULT_LNG, type=float)

    if not _is_japan(lat, lng):
        return jsonify({"error": "AMeDAS only available in Japan", "unavailable": True}), 200

    now = time.time()
    with _amedas_cache_lock:
        if (_amedas_cache["data"]
                and (now - _amedas_cache["ts"]) < AMEDAS_CACHE_TTL
                and _amedas_cache["lat"] == round(lat, 4)
                and _amedas_cache["lng"] == round(lng, 4)):
            return jsonify({
                "observation": _amedas_cache["data"],
                "station": _amedas_cache["station"],
                "cached": True,
                "age": int(now - _amedas_cache["ts"]),
            })

    try:
        table = _get_amedas_table()
        if not table:
            return jsonify({"error": "Could not fetch station table"}), 502

        r = requests.get(f"{JMA_AMEDAS_BASE}/latest_time.txt", headers=JMA_HEADERS, timeout=5)
        r.raise_for_status()
        latest_str = r.text.strip()
        time_key = latest_str[:19].replace("-", "").replace("T", "").replace(":", "")

        map_url = f"{JMA_AMEDAS_BASE}/map/{time_key}.json"
        r = requests.get(map_url, headers=JMA_HEADERS, timeout=10)
        r.raise_for_status()
        map_data = r.json()

        if not map_data:
            return jsonify({"error": "Empty map data"}), 502

        station_id, station_dist = _find_nearest_station(lat, lng, table, map_data)
        if not station_id or station_id not in map_data:
            return jsonify({"error": "No nearby station with temperature data"}), 502

        # If nearest station is too far (>0.5 degrees ≈ 50km), skip
        if station_dist > 0.5:
            return jsonify({"error": "No nearby AMeDAS station", "unavailable": True}), 200

        station_info = table[station_id]
        station_meta = {
            "id": station_id,
            "name_jp": station_info.get("kjName", ""),
            "name_en": station_info.get("enName", ""),
            "lat": station_info["lat"][0] + station_info["lat"][1] / 60.0,
            "lon": station_info["lon"][0] + station_info["lon"][1] / 60.0,
            "alt": station_info.get("alt", 0),
        }

        obs = map_data[station_id]

        def val(key):
            v = obs.get(key)
            if v is None:
                return None
            if isinstance(v, list) and len(v) >= 2:
                return v[0] if v[1] == 0 else None
            return v

        observation = {
            "time": latest_str,
            "temp": val("temp"),
            "humidity": val("humidity"),
            "wind_speed": val("wind"),
            "wind_direction": val("windDirection"),
            "precipitation_1h": val("precipitation1h"),
            "precipitation_10m": val("precipitation10m"),
            "pressure": val("normalPressure"),
            "sun_1h": val("sun1h"),
            "snow": val("snow"),
        }

        with _amedas_cache_lock:
            _amedas_cache["data"] = observation
            _amedas_cache["station"] = station_meta
            _amedas_cache["ts"] = now
            _amedas_cache["lat"] = round(lat, 4)
            _amedas_cache["lng"] = round(lng, 4)

        return jsonify({
            "observation": observation,
            "station": station_meta,
            "cached": False,
            "age": 0,
        })

    except Exception as e:
        log.error(f"AMeDAS fetch error: {e}")
        with _amedas_cache_lock:
            if _amedas_cache["data"]:
                return jsonify({
                    "observation": _amedas_cache["data"],
                    "station": _amedas_cache["station"],
                    "cached": True,
                    "age": int(now - _amedas_cache["ts"]),
                    "error": str(e),
                })
        return jsonify({"error": str(e)}), 502


@app.route("/api/iss")
def api_iss():
    """Return current ISS position."""
    now = time.time()
    with _iss_cache_lock:
        if _iss_cache["data"] and (now - _iss_cache["ts"]) < ISS_CACHE_TTL:
            return jsonify(_iss_cache["data"])
    try:
        r = requests.get("https://api.wheretheiss.at/v1/satellites/25544", timeout=10)
        r.raise_for_status()
        data = r.json()
        with _iss_cache_lock:
            _iss_cache["data"] = data
            _iss_cache["ts"] = now
        return jsonify(data)
    except Exception as e:
        log.warning(f"ISS fetch failed: {e}")
        with _iss_cache_lock:
            if _iss_cache["data"]:
                return jsonify(_iss_cache["data"])
        return jsonify({"error": str(e)}), 502


@app.route("/api/earthquakes")
def api_earthquakes():
    """Return recent M2.5+ earthquakes within 1500 km of a location (USGS)."""
    lat = request.args.get("lat", DEFAULT_LAT, type=float)
    lng = request.args.get("lng", DEFAULT_LNG, type=float)
    cache_key = f"{lat:.2f},{lng:.2f}"
    now = time.time()

    with _eq_cache_lock:
        cached = _eq_cache.get(cache_key)
        if cached and (now - cached["ts"]) < EQ_CACHE_TTL:
            return jsonify({**cached["data"], "cached": True, "age": int(now - cached["ts"])})

    try:
        r = requests.get(
            "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson",
            timeout=15,
        )
        r.raise_for_status()
        features = r.json().get("features", [])

        results = []
        for f in features:
            props = f.get("properties", {})
            coords = f.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            eq_lng, eq_lat = coords[0], coords[1]
            depth = coords[2] if len(coords) > 2 else 0
            dist_km = _haversine_km(lat, lng, eq_lat, eq_lng)
            if dist_km > 1500:
                continue
            time_ms = props.get("time", 0) or 0
            age_s = int((now * 1000 - time_ms) / 1000)
            if age_s < 60:
                time_ago = f"{age_s}s ago"
            elif age_s < 3600:
                time_ago = f"{age_s // 60}m ago"
            elif age_s < 86400:
                time_ago = f"{age_s // 3600}h ago"
            else:
                time_ago = f"{age_s // 86400}d ago"
            results.append({
                "mag": props.get("mag"),
                "place": props.get("place", "Unknown"),
                "dist_km": round(dist_km),
                "depth_km": round(depth, 1),
                "time_ago": time_ago,
            })

        results.sort(key=lambda x: x["dist_km"])
        results = results[:15]
        payload = {
            "earthquakes": results,
            "total": len(results),
            "radius_km": 1500,
            "cached": False,
            "age": 0,
        }
        with _eq_cache_lock:
            _eq_cache[cache_key] = {"data": payload, "ts": now}
        return jsonify(payload)

    except Exception as e:
        log.warning(f"USGS fetch failed: {e}")
        with _eq_cache_lock:
            cached = _eq_cache.get(cache_key)
            if cached:
                return jsonify({**cached["data"], "cached": True, "age": int(now - cached["ts"]), "error": str(e)})
        return jsonify({"error": str(e)}), 502


@app.route("/api/health")
def api_health():
    """Quick connectivity check — tests outbound HTTP to Open-Meteo."""
    results = {}
    for name, url in [
        ("open-meteo", "https://api.open-meteo.com/v1/forecast?latitude=35.56&longitude=139.69&current=temperature_2m&forecast_days=1"),
        ("rainviewer", "https://api.rainviewer.com/public/weather-maps.json"),
        ("iss", "https://api.wheretheiss.at/v1/satellites/25544"),
        ("jma-amedas", "https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"),
        ("usgs-earthquakes", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson"),
    ]:
        try:
            t0 = time.time()
            r = requests.get(url, timeout=8)
            elapsed = round((time.time() - t0) * 1000)
            results[name] = {
                "status": r.status_code,
                "ok": r.ok,
                "ms": elapsed,
                "bytes": len(r.content),
            }
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)}
    log.info(f"Health check: {results}")
    return jsonify(results)


@app.route("/api/timezone")
def api_timezone():
    """Reverse-geocode timezone from coordinates using Open-Meteo."""
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    if lat is None or lng is None:
        return jsonify({"error": "lat and lng required"}), 400
    try:
        r = requests.get(
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}"
            "&current=temperature_2m&timezone=auto&forecast_days=1",
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        return jsonify({
            "timezone": data.get("timezone", "auto"),
            "timezone_abbreviation": data.get("timezone_abbreviation", ""),
            "utc_offset_seconds": data.get("utc_offset_seconds", 0),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/windgrid")
def api_windgrid():
    """Return a wind vector grid for leaflet-velocity covering the visible map bounds."""
    lat = request.args.get("lat", DEFAULT_LAT, type=float)
    lng = request.args.get("lng", DEFAULT_LNG, type=float)

    # Visible map bounds passed from the frontend (with padding already included)
    bn = request.args.get("n", type=float)
    bs = request.args.get("s", type=float)
    be = request.args.get("e", type=float)
    bw = request.args.get("w", type=float)

    if all(v is not None for v in [bn, bs, be, bw]):
        # Add 15% padding so edge particles don't vanish abruptly
        pad_lat = (bn - bs) * 0.15
        pad_lng = (be - bw) * 0.15
        la1 = min(85.0, bn + pad_lat)
        la2 = max(-85.0, bs - pad_lat)
        lo1 = bw - pad_lng
        lo2 = be + pad_lng
        cache_key = f"{bn:.1f},{bs:.1f},{be:.1f},{bw:.1f}"
    else:
        # Fallback: fixed ±20° box centred on the location
        la1, la2 = lat + 20, lat - 20
        lo1, lo2 = lng - 20, lng + 20
        cache_key = f"{lat:.2f},{lng:.2f}"

    now = time.time()
    with _windgrid_cache_lock:
        cached = _windgrid_cache.get(cache_key)
        if cached and (now - cached["ts"]) < WINDGRID_CACHE_TTL:
            return jsonify(cached["data"])

    # Aim for ~20 columns and rows; keep spacing between 1.0 and 3.0 degrees
    span_lat = la1 - la2
    span_lng = lo2 - lo1
    dlat = max(1.0, min(3.0, span_lat / 20))
    dlng = max(1.0, min(3.0, span_lng / 20))
    NY = round(span_lat / dlat) + 1
    NX = round(span_lng / dlng) + 1
    # Hard cap: Open-Meteo batch limit is 1000 locations
    while NX * NY > 900:
        dlat *= 1.1
        dlng *= 1.1
        NY = round(span_lat / dlat) + 1
        NX = round(span_lng / dlng) + 1

    all_lats, all_lngs = [], []
    for i in range(NY):
        for j in range(NX):
            all_lats.append(la1 - i * dlat)
            all_lngs.append(lo1 + j * dlng)

    lats_str = ",".join(f"{v:.2f}" for v in all_lats)
    lngs_str = ",".join(f"{v:.2f}" for v in all_lngs)
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lats_str}&longitude={lngs_str}"
        "&current=wind_speed_10m,wind_direction_10m&forecast_days=1&timezone=UTC"
    )

    try:
        log.info(f"Wind grid fetch: {NX}x{NY} ({NX*NY} pts) span={span_lat:.1f}°lat×{span_lng:.1f}°lng d={dlat:.1f}°")
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        points = r.json()
        if not isinstance(points, list):
            points = [points]

        u_data, v_data = [], []
        for pt in points:
            c = pt.get("current", {})
            speed = (c.get("wind_speed_10m") or 0) / 3.6
            direction = c.get("wind_direction_10m") or 0
            u_data.append(round(-speed * math.sin(math.radians(direction)), 2))
            v_data.append(round(-speed * math.cos(math.radians(direction)), 2))

        actual_la2 = la1 - (NY - 1) * dlat
        actual_lo2 = lo1 + (NX - 1) * dlng
        header_base = {
            "parameterUnit": "m.s-1",
            "parameterCategory": 2,
            "dx": dlng, "dy": dlat,
            "la1": la1, "lo1": lo1,
            "la2": actual_la2, "lo2": actual_lo2,
            "nx": NX, "ny": NY,
        }
        result = [
            {**{"header": {**header_base, "parameterNumber": 2, "parameterNumberName": "eastward_wind"}}, "data": u_data},
            {**{"header": {**header_base, "parameterNumber": 3, "parameterNumberName": "northward_wind"}}, "data": v_data},
        ]

        with _windgrid_cache_lock:
            _windgrid_cache[cache_key] = {"data": result, "ts": now}
        return jsonify(result)

    except Exception as e:
        log.error(f"Wind grid fetch error: {e}")
        with _windgrid_cache_lock:
            cached = _windgrid_cache.get(cache_key)
            if cached:
                return jsonify(cached["data"])
        return jsonify({"error": str(e)}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5099, debug=False)
