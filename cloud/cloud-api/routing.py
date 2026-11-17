"""
Origin -> destination driving distance/duration, for delivery ETA estimates
and route suggestions (Fuel Provider view). Free, keyless — OSRM's public
demo server, same spirit as geocoding.py's choice of Nominatim over a paid
maps API.

OSRM's demo server (router.project-osrm.org) has no published hard rate
limit, but it's a shared community resource, not a production SLA — treat
it the same way geocoding.py treats Nominatim: self-throttled to roughly
1 request/second, and every call degrades to "no estimate" rather than
failing the caller. If delivery volume ever grows past occasional use,
self-host an OSRM instance (same OSM data, your own server) instead of
leaning on the public one.

Everything here never raises — a failed/ambiguous route lookup just means
no ETA badge on the map and no route-distance shown; nothing else depends
on this succeeding, exactly like weather.py and geocoding.py.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

_HEADERS = {"User-Agent": "TLS-Decoded-Cloud/1.0 (fuel delivery ETA estimates; contact: station admin)"}
_last_request_at = 0.0
_MIN_INTERVAL_SECONDS = 1.0

# A candidate alternative route is only worth surfacing as a "suggestion" if
# it saves at least this fraction of the primary route's duration — small
# differences aren't worth a supplier's attention.
_ALT_SUGGESTION_THRESHOLD = 0.15


def _throttle() -> None:
    global _last_request_at
    wait = _MIN_INTERVAL_SECONDS - (time.time() - _last_request_at)
    if wait > 0:
        time.sleep(wait)


def route(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float,
    alternatives: bool = False,
) -> Optional[dict]:
    """
    Returns {"distance_km": float, "duration_min": float,
    "alternative": {"distance_km", "duration_min"} | None} for the best
    driving route between two points, or None if OSRM can't route it (no
    network, no road data for the area, upstream down).

    "alternative" is only populated when `alternatives=True` was passed AND
    OSRM returned a second route that's meaningfully faster or shorter than
    the primary one — the raw material for a "there may be a better route"
    suggestion. OSRM already picks the best single route by default, so
    this is for the daisy-chain/multi-stop case where a human dispatcher
    might reasonably want a second opinion.
    """
    global _last_request_at
    _throttle()
    try:
        with httpx.Client(timeout=8.0, headers=_HEADERS) as client:
            resp = client.get(
                f"https://router.project-osrm.org/route/v1/driving/"
                f"{origin_lng},{origin_lat};{dest_lng},{dest_lat}",
                params={
                    "overview": "false",
                    "alternatives": "true" if alternatives else "false",
                },
            )
        _last_request_at = time.time()
        if resp.status_code != 200:
            return None
        data = resp.json()
        routes = data.get("routes") or []
        if not routes:
            return None

        primary = routes[0]
        result = {
            "distance_km": round(primary["distance"] / 1000.0, 2),
            "duration_min": round(primary["duration"] / 60.0, 1),
            "alternative": None,
        }

        if alternatives and len(routes) > 1:
            best_alt = min(routes[1:], key=lambda r: r["duration"])
            if best_alt["duration"] < primary["duration"] * (1 - _ALT_SUGGESTION_THRESHOLD):
                result["alternative"] = {
                    "distance_km": round(best_alt["distance"] / 1000.0, 2),
                    "duration_min": round(best_alt["duration"] / 60.0, 1),
                }
        return result
    except Exception:
        return None
