"""
Address -> lat/lng, for the station map pin (Admin -> Stations). Free,
keyless — OpenStreetMap's Nominatim, same spirit as weather.py's choice of
free/keyless upstreams for this project.

Nominatim's usage policy (https://operations.osmfoundation.org/policies/nominatim/)
requires a descriptive User-Agent and caps public-instance usage at ~1
request/second — fine for "an admin geocodes a station address occasionally
when provisioning it," not fine for bulk/automated geocoding. If station
volume ever grows past occasional manual use, self-host a Nominatim instance
rather than hammering the public one.

Like weather.py, this never raises — a failed/ambiguous geocode just means
the admin sets lat/lng by hand (or drags the pin) instead; nothing else
depends on this succeeding.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

_HEADERS = {"User-Agent": "TLS-Decoded-Cloud/1.0 (fuel station map pins; contact: station admin)"}
_last_request_at = 0.0
_MIN_INTERVAL_SECONDS = 1.0  # Nominatim's usage policy


def geocode_address(address: str) -> Optional[dict]:
    """Returns {"lat": float, "lng": float, "display_name": str} for the
    best match, or None if it can't be geocoded (bad address, no network,
    upstream down, or a 429 from exceeding the rate limit)."""
    global _last_request_at
    address = (address or "").strip()
    if not address:
        return None

    wait = _MIN_INTERVAL_SECONDS - (time.time() - _last_request_at)
    if wait > 0:
        time.sleep(wait)

    try:
        with httpx.Client(timeout=8.0, headers=_HEADERS) as client:
            resp = client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": address, "format": "json", "limit": 1},
            )
        _last_request_at = time.time()
        if resp.status_code != 200:
            return None
        results = resp.json()
        if not results:
            return None
        r = results[0]
        return {"lat": float(r["lat"]), "lng": float(r["lon"]), "display_name": r.get("display_name", address)}
    except Exception:
        return None
