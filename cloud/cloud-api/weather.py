"""
Weather lookups for stations that have a zip code on file — surfaces
forecast-driven maintenance heads-ups on T1 (full panel) and T2 (condensed
chip), e.g. "rain forecast: check tank vent cap covers."

Two free, keyless upstreams, both US-only:
  - Zippopotam.us   — zip -> lat/lon/city/state
  - api.weather.gov — lat/lon -> multi-period forecast (National Weather
    Service; requires a User-Agent header, no API key)

A station without a zip code, or an upstream hiccup, simply means no
weather data — this never raises, callers get None and just omit the
panel. Results are cached in-process per zip for CACHE_TTL_SECONDS so
repeated dashboard polls (T1 auto-refreshes every 60s) don't hammer either
upstream API, and so a slow/down upstream doesn't slow down the dashboard.
"""
import time
from typing import Optional

import httpx

CACHE_TTL_SECONDS = 30 * 60
_cache: dict[str, tuple[float, Optional[dict]]] = {}

RAIN_WORDS = ("rain", "showers", "thunderstorm", "drizzle")
SNOW_WORDS = ("snow", "sleet", "flurries", "wintry", "ice")
WIND_THRESHOLD_MPH = 25
FREEZE_F = 32
HEAT_F = 95

_HEADERS = {"User-Agent": "TLS-Decoded/1.0 (fuel tank monitor; contact: station admin)"}


def _cache_get(key: str) -> Optional[dict]:
    hit = _cache.get(key)
    if not hit:
        return None
    ts, data = hit
    if time.time() - ts > CACHE_TTL_SECONDS:
        return None
    return data


def _cache_set(key: str, data: Optional[dict]) -> None:
    _cache[key] = (time.time(), data)


def _geocode_zip(zip_code: str) -> Optional[dict]:
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(f"https://api.zippopotam.us/us/{zip_code}")
        if resp.status_code != 200:
            return None
        data = resp.json()
        place = data["places"][0]
        return {
            "lat": float(place["latitude"]), "lon": float(place["longitude"]),
            "city": place["place name"], "state": place["state abbreviation"],
        }
    except Exception:
        return None


def _fetch_nws_periods(lat: float, lon: float) -> Optional[list[dict]]:
    try:
        with httpx.Client(timeout=8.0, headers=_HEADERS) as client:
            points = client.get(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
            if points.status_code != 200:
                return None
            forecast_url = points.json()["properties"]["forecast"]
            fc = client.get(forecast_url)
            if fc.status_code != 200:
                return None
            return fc.json()["properties"]["periods"]
    except Exception:
        return None


def _wind_mph(wind_speed: str) -> int:
    """NWS gives wind as a free-text string like '10 mph' or '15 to 20 mph' —
    take the first (or only) number, worst case 0 if unparsable."""
    try:
        return int(''.join(c for c in wind_speed.split()[0] if c.isdigit()))
    except (ValueError, IndexError):
        return 0


def _recommendations(periods: list[dict]) -> list[dict]:
    """One entry per upcoming period (next ~2 days) that warrants a
    heads-up, each naming the period, the trigger, and a plain-language
    action a technician can act on."""
    out = []
    for p in periods[:4]:
        name = p.get("name", "")
        forecast = (p.get("detailedForecast") or p.get("shortForecast") or "").lower()
        temp = p.get("temperature")
        unit = p.get("temperatureUnit")
        wind_mph = _wind_mph(p.get("windSpeed") or "")

        if any(w in forecast for w in RAIN_WORDS):
            out.append({
                "period": name, "type": "rain",
                "message": "Rain forecast — check tank vent cap covers / rubber seals are seated to reduce water intrusion.",
            })
        if any(w in forecast for w in SNOW_WORDS):
            out.append({
                "period": name, "type": "snow",
                "message": "Snow/ice forecast — clear access to fill ports before delivery trucks arrive.",
            })
        if temp is not None and unit == "F" and temp <= FREEZE_F:
            out.append({
                "period": name, "type": "freeze",
                "message": f"Freezing temps forecast ({temp}°F) — check for line/condensation freezing, verify heat tape if equipped.",
            })
        if temp is not None and unit == "F" and temp >= HEAT_F:
            out.append({
                "period": name, "type": "heat",
                "message": f"High heat forecast ({temp}°F) — monitor vapor pressure / excessive vapor loss.",
            })
        if wind_mph >= WIND_THRESHOLD_MPH:
            out.append({
                "period": name, "type": "wind",
                "message": f"High winds forecast (~{wind_mph} mph) — secure loose covers and signage.",
            })
    return out


def get_station_weather(zip_code: str) -> Optional[dict]:
    """Returns {location, current, forecast[], recommendations[]}, or None if
    the zip can't be geocoded or NWS has no data for it (non-US zip, bad
    zip, upstream down, etc.) — cached per zip for CACHE_TTL_SECONDS."""
    if not zip_code:
        return None
    zip_code = zip_code.strip()
    cache_key = f"weather:{zip_code}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    geo = _geocode_zip(zip_code)
    if not geo:
        _cache_set(cache_key, None)
        return None
    periods = _fetch_nws_periods(geo["lat"], geo["lon"])
    if not periods:
        _cache_set(cache_key, None)
        return None

    current = periods[0]
    result = {
        "location": f"{geo['city']}, {geo['state']}",
        "current": {
            "period": current.get("name"),
            "temperature": current.get("temperature"),
            "temperature_unit": current.get("temperatureUnit"),
            "short_forecast": current.get("shortForecast"),
            "wind_speed": current.get("windSpeed"),
            "wind_direction": current.get("windDirection"),
            "precipitation_chance": (current.get("probabilityOfPrecipitation") or {}).get("value"),
        },
        "forecast": [
            {
                "period": p.get("name"), "temperature": p.get("temperature"),
                "temperature_unit": p.get("temperatureUnit"), "short_forecast": p.get("shortForecast"),
                "is_daytime": p.get("isDaytime"),
            }
            for p in periods[:6]
        ],
        "recommendations": _recommendations(periods),
    }
    _cache_set(cache_key, result)
    return result
