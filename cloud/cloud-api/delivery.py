"""
Shared delivery-timer math — elapsed-time-vs-estimate progress for an
active FuelOrder that has a dispatched_at + eta_minutes (see
routers/supplier.py for how those get set, models.py's FuelOrder for the
fields). Used by both the supplier dashboard (routers/supplier.py) and the
station map (routers/stations.py) so the two surfaces never disagree about
how "2/3 of the way there" gets computed.

No GPS — this is explicitly an estimate: elapsed / eta. Progress is capped
a bit past 100% (1.15) rather than clamped exactly at 1.0, so a running-late
delivery still reads as "almost there" instead of looking identical to one
that arrived on time — see `running_late` below for the explicit flag UIs
should use instead of inferring it from the fraction.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def delivery_progress(order) -> Optional[dict]:
    """
    `order` is a FuelOrder row (or anything with the same dispatched_at/
    eta_minutes/origin_label/route_distance_km attributes). Returns None if
    this order never got a route estimate (no pickup address given, or
    geocoding/routing failed at order time) — callers fall back to just the
    free-text eta_note in that case, same as before this feature existed.
    """
    if order is None or not order.dispatched_at or not order.eta_minutes:
        return None
    now = datetime.now(tz=timezone.utc)
    elapsed_min = (now - order.dispatched_at).total_seconds() / 60.0
    progress = (elapsed_min / order.eta_minutes) if order.eta_minutes > 0 else 0.0
    return {
        "origin_label": order.origin_label,
        "dispatched_at": order.dispatched_at.isoformat(),
        "eta_minutes": order.eta_minutes,
        "route_distance_km": order.route_distance_km,
        "progress_pct": round(min(max(progress, 0.0), 1.15), 4),
        "running_late": progress > 1.0,
    }
