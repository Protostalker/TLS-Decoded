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
    `order` is either a FuelOrder row (dispatched_at/origin_label) or a
    DeliveryStop row (started_at, no origin_label — the leg's "origin" is
    implicit: the rack or the previous stop) — both carry eta_minutes/
    route_distance_km(or distance_km) with the same meaning, so this reads
    whichever start-time/label attributes are actually present rather than
    assuming one shape. Returns None if this order/stop never got a route
    estimate (no pickup address given, routing failed, or the leg hasn't
    started yet) — callers fall back to the free-text eta_note (FuelOrder)
    or a plain "pending" state (DeliveryStop) in that case.
    """
    if order is None:
        return None
    started_at = getattr(order, "dispatched_at", None) or getattr(order, "started_at", None)
    eta_minutes = getattr(order, "eta_minutes", None)
    if not started_at or not eta_minutes:
        return None
    distance_km = getattr(order, "route_distance_km", None)
    if distance_km is None:
        distance_km = getattr(order, "distance_km", None)
    # Defensive: SQLite (unlike Postgres' TIMESTAMP(timezone=True)) hands
    # back naive datetimes on reload even when a tz-aware one was written,
    # which breaks the subtraction below. Treat a naive value as UTC rather
    # than let this raise.
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    elapsed_min = (now - started_at).total_seconds() / 60.0
    progress = (elapsed_min / eta_minutes) if eta_minutes > 0 else 0.0
    return {
        "origin_label": getattr(order, "origin_label", None),
        "dispatched_at": started_at.isoformat(),
        "eta_minutes": eta_minutes,
        "route_distance_km": distance_km,
        "progress_pct": round(min(max(progress, 0.0), 1.15), 4),
        "running_late": progress > 1.0,
    }
