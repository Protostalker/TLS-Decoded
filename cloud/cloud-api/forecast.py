"""
Fuel depletion forecast for the cloud T1 station view (cloud only; the
local station dashboard does not have this).

Pure functions, no DB access, so the math can be tested on its own. The
endpoint that feeds it lives in routers/stations.py (GET
/api/stations/{id}/forecast).

How the prediction works:

1. Build an hour-of-day consumption profile from the last PROFILE_DAYS of
   readings, in the STATION's local timezone. Every pair of consecutive
   readings contributes its gallons and its elapsed time to the hour(s) of
   day it covers, split proportionally when it crosses an hour boundary.
   - Intervals longer than MAX_GAP_HOURS are skipped (station offline,
     poller down): we don't know when that fuel was sold.
   - Intervals where the volume ROSE by more than DELIVERY_JUMP_GAL are
     skipped (a delivery happened; the sales hidden under it are unknown).
   - Small rises (temperature / probe jitter) are kept as a small negative
     contribution so they cancel the matching jitter dips instead of
     inflating consumption.
   - Idle intervals (no volume change) DO count as hours, so a station
     that is quiet overnight gets a flat overnight line.
2. rate[h] = gallons / hours observed for that hour of day. An hour with
   less than MIN_HOURS_PER_BUCKET of observation falls back to the overall
   average rate. With less than MIN_TOTAL_HOURS of usable data there is no
   forecast at all.
3. Starting from the tank's latest reading, walk forward hour by hour
   subtracting rate[hour of day]. Clamped at 0. Assumes no delivery.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

# range key -> (past_hours, future_hours, step_hours). The window is the
# TOTAL width: e.g. "24h" = 16h actual + 8h predicted.
FORECAST_RANGES: dict[str, tuple[int, int, int]] = {
    "24h": (16, 8, 1),
    "48h": (36, 12, 1),
    "72h": (54, 18, 1),
    "5d": (96, 24, 2),
    "7d": (132, 36, 3),
}

PROFILE_DAYS = 28
MAX_GAP_HOURS = 3.0
DELIVERY_JUMP_GAL = 25.0
MIN_HOURS_PER_BUCKET = 2.0
MIN_TOTAL_HOURS = 24.0
# How far past the window we keep walking to find "hits reorder" / "runs
# empty" times for the summary chips.
PROJECTION_HORIZON_HOURS = 60 * 24

Reading = tuple[datetime, float]  # (polled_at UTC-aware, volume_gallons)


def _hour_floor(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def _segments(t0: datetime, t1: datetime) -> Iterable[tuple[datetime, float]]:
    """Split [t0, t1) at hour boundaries. Yields (segment_start, hours).
    Boundaries are taken in UTC, which coincide with local hour boundaries
    for every whole-hour UTC offset (all US zones)."""
    t = t0
    while t < t1:
        boundary = _hour_floor(t) + timedelta(hours=1)
        end = min(t1, boundary)
        yield t, (end - t).total_seconds() / 3600.0
        t = end


def build_hourly_profile(rows: Sequence[Reading], tz: ZoneInfo) -> Optional[dict]:
    """rows must be sorted by time ascending. Returns
    {"rates": [24 floats gal/hr], "source": "hour_of_day"|"flat",
     "observed_hours": float, "avg_rate": float} or None if too little data."""
    gal = [0.0] * 24
    hrs = [0.0] * 24
    for (pt, pv), (ct, cv) in zip(rows, rows[1:]):
        total = (ct - pt).total_seconds() / 3600.0
        if total <= 0 or total > MAX_GAP_HOURS:
            continue
        delta = pv - cv  # positive = fuel sold
        if delta < -DELIVERY_JUMP_GAL:
            continue
        for seg_start, seg_hours in _segments(pt, ct):
            h = seg_start.astimezone(tz).hour
            gal[h] += delta * (seg_hours / total)
            hrs[h] += seg_hours

    observed = sum(hrs)
    if observed < MIN_TOTAL_HOURS:
        return None
    avg = max(0.0, sum(gal) / observed)
    rates = []
    thin = 0
    for h in range(24):
        if hrs[h] >= MIN_HOURS_PER_BUCKET:
            rates.append(max(0.0, gal[h] / hrs[h]))
        else:
            rates.append(avg)
            thin += 1
    return {
        "rates": rates,
        "source": "flat" if thin == 24 else "hour_of_day",
        "observed_hours": round(observed, 1),
        "avg_rate": avg,
    }


def project_volume(t0: datetime, v0: float, t1: datetime, rates: Sequence[float], tz: ZoneInfo) -> float:
    """Volume at t1 starting from v0 at t0, using the hour-of-day rates."""
    v = v0
    for seg_start, seg_hours in _segments(t0, t1):
        v -= rates[seg_start.astimezone(tz).hour] * seg_hours
        if v <= 0:
            return 0.0
    return v


def time_until_level(t0: datetime, v0: float, level: float, rates: Sequence[float], tz: ZoneInfo,
                     horizon_hours: float = PROJECTION_HORIZON_HOURS) -> Optional[datetime]:
    """First time the projected volume drops to `level`, or None if it does
    not within the horizon (or the tank is already at/below it)."""
    if v0 <= level:
        return None
    v = v0
    end = t0 + timedelta(hours=horizon_hours)
    for seg_start, seg_hours in _segments(t0, end):
        r = rates[seg_start.astimezone(tz).hour]
        drop = r * seg_hours
        if r > 0 and v - drop <= level:
            return seg_start + timedelta(hours=(v - level) / r)
        v -= drop
    return None


def window_grid(now: datetime, range_key: str, tz: ZoneInfo) -> tuple[datetime, list[datetime]]:
    """Anchor = now floored to the step, aligned to LOCAL clock hours so the
    2h/3h steps land on readable labels (00:00, 03:00, ...). Returns
    (anchor, grid) where grid spans anchor-past .. anchor+future."""
    past, future, step = FORECAST_RANGES[range_key]
    local = now.astimezone(tz)
    local_floor = local.replace(minute=0, second=0, microsecond=0)
    local_floor -= timedelta(hours=local_floor.hour % step)
    anchor = local_floor.astimezone(timezone.utc)
    start = anchor - timedelta(hours=past)
    n = (past + future) // step
    return anchor, [start + timedelta(hours=i * step) for i in range(n + 1)]


def tank_series(rows: Sequence[Reading], grid: Sequence[datetime], profile: Optional[dict],
                tz: ZoneInfo, step_hours: int, reorder_threshold: Optional[float]) -> dict:
    """Per-tank values on the shared grid. A grid point at or before the
    latest reading is ACTUAL (latest reading at or before that time, if one
    exists within the tolerance; else None = gap). A grid point after the
    latest reading is PREDICTED from that latest reading."""
    out = {
        "values": [None] * len(grid),
        "predicted": [False] * len(grid),
        "last_reading_at": None,
        "last_volume_gallons": None,
        "projected_reorder_at": None,
        "projected_empty_at": None,
    }
    if not rows:
        return out

    times = [r[0] for r in rows]
    last_t, last_v = rows[-1]
    out["last_reading_at"] = last_t.isoformat()
    out["last_volume_gallons"] = round(last_v, 1)
    tolerance = timedelta(hours=max(step_hours, 2))

    for i, t in enumerate(grid):
        if t <= last_t:
            idx = bisect_right(times, t) - 1
            if idx >= 0 and t - times[idx] <= tolerance:
                out["values"][i] = round(rows[idx][1], 1)
        elif profile is not None:
            out["values"][i] = round(project_volume(last_t, last_v, t, profile["rates"], tz), 1)
            out["predicted"][i] = True

    if profile is not None:
        if reorder_threshold:
            r = time_until_level(last_t, last_v, reorder_threshold, profile["rates"], tz)
            out["projected_reorder_at"] = r.isoformat() if r else None
        e = time_until_level(last_t, last_v, 0.0, profile["rates"], tz)
        out["projected_empty_at"] = e.isoformat() if e else None
    return out
