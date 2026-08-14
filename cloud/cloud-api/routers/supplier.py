"""
Supplier-facing API — urgency-sorted station list + fuel-order actions.

Suppliers see tank levels, deliveries, and alarms — no pricing or financials
(those are gated in stations.py). The urgency sort puts the most critical
station (lowest fill % across all tanks) at the top so a driver opening the
app immediately knows where to go next. A 6-hour snooze pushes an ordered
station to the bottom with a countdown badge.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import assigned_station_ids, get_current_user, require_not_degraded, require_station_access
from database import get_db
from models import (
    CloudReading, CloudTank, Customer, FuelOrder,
    Notification, PushSubscription, Station, User,
)
from schemas import FuelOrderRequest

# Gated by license state — supplier ordering is explicit-non-gated-item #1 in
# the dev handoff doc, and Raffi's degraded-mode answer extends that to ALL
# supplier data access, not just the order action itself.
router = APIRouter(dependencies=[Depends(require_not_degraded)])

# ── Auth guard ────────────────────────────────────────────────────────────────

def _require_supplier(user: User = Depends(get_current_user)) -> User:
    """Suppliers and admins can both use the supplier view."""
    if user.role not in ("supplier", "admin"):
        raise HTTPException(status_code=403, detail="Supplier access required")
    return user


# ── Station urgency helpers ───────────────────────────────────────────────────

def _latest_reading(db: Session, station_id: int, tank_local_id: int) -> Optional[CloudReading]:
    return (
        db.query(CloudReading)
        .filter(CloudReading.station_id == station_id, CloudReading.tank_local_id == tank_local_id)
        .order_by(CloudReading.polled_at.desc())
        .first()
    )


def _active_snooze(db: Session, station_id: int) -> Optional[FuelOrder]:
    """Most-recent FuelOrder whose snooze hasn't expired yet, if any."""
    now = datetime.now(tz=timezone.utc)
    return (
        db.query(FuelOrder)
        .filter(FuelOrder.station_id == station_id, FuelOrder.snoozed_until > now)
        .order_by(FuelOrder.ordered_at.desc())
        .first()
    )


def _build_supplier_station(db: Session, station: Station) -> dict:
    cust = db.query(Customer).filter(Customer.id == station.customer_id).first()
    tanks = (
        db.query(CloudTank)
        .filter(CloudTank.station_id == station.id, CloudTank.active == True)  # noqa: E712
        .order_by(CloudTank.local_id)
        .all()
    )

    tank_summaries = []
    min_pct: Optional[float] = None
    min_vol: Optional[float] = None

    for tank in tanks:
        reading = _latest_reading(db, station.id, tank.local_id)
        vol = reading.volume_gallons if reading else None
        cap = tank.capacity_gallons
        pct = round(vol / cap, 4) if (vol is not None and cap and cap > 0) else None
        tank_summaries.append({
            "tank_local_id": tank.local_id,
            "name": tank.name,
            "product": tank.product,
            "capacity_gallons": cap,
            "current_volume_gallons": vol,
            "fill_pct": pct,          # 0.0–1.0, None if no reading
        })
        if pct is not None and (min_pct is None or pct < min_pct):
            min_pct = pct
            min_vol = vol

    snooze = _active_snooze(db, station.id)

    return {
        "id": station.id,
        "name": station.name,
        "customer_name": cust.name if cust else None,
        "last_sync_at": station.last_sync_at,
        "tanks": tank_summaries,
        # Urgency: driven by the single most-critical tank.
        "urgency_pct": min_pct,        # lowest fill % — primary sort key
        "urgency_volume": min_vol,     # gallons in that tank, shown in the card
        # Snooze state.
        "snooze_active": snooze is not None,
        "snoozed_until": snooze.snoozed_until.isoformat() if snooze else None,
        "latest_order": {
            "id": snooze.id,
            "ordered_at": snooze.ordered_at.isoformat(),
            "eta_note": snooze.eta_note,
            "snoozed_until": snooze.snoozed_until.isoformat(),
        } if snooze else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/supplier/stations")
def supplier_stations(
    user: User = Depends(_require_supplier),
    db: Session = Depends(get_db),
):
    """
    Returns the user's assigned stations sorted by fuel urgency:
      1. Non-snoozed stations, urgency_pct ASC (lowest fill first)
      2. Snoozed stations at the end, also urgency_pct ASC within that group

    Stations with no readings yet (urgency_pct = None) sort after stations
    with real data in each group.
    """
    ids = assigned_station_ids(db, user)
    stations = (
        db.query(Station)
        .filter(Station.id.in_(ids), Station.active == True)  # noqa: E712
        .all()
        if ids else []
    )
    result = [_build_supplier_station(db, s) for s in stations]

    def _sort_key(s: dict):
        pct = s["urgency_pct"] if s["urgency_pct"] is not None else 2.0  # no data → sort last
        return (int(s["snooze_active"]), pct)

    result.sort(key=_sort_key)
    return result


@router.post("/supplier/stations/{station_id}/order")
def mark_fuel_ordered(
    station_id: int,
    body: FuelOrderRequest,
    user: User = Depends(_require_supplier),
    db: Session = Depends(get_db),
):
    """
    Mark fuel as ordered for a station.

    Effects:
      1. Creates a FuelOrder row (6h snooze from now).
      2. Creates Notification rows for every admin/user assigned to the station
         (or, for admins, all admins of the customer).
      3. Fires a best-effort Web Push to those users' stored subscriptions.
         Push failures are swallowed — the HTTP response never depends on it.
    """
    station = require_station_access(station_id, db, user)
    now = datetime.now(tz=timezone.utc)
    snoozed_until = now + timedelta(hours=6)

    order = FuelOrder(
        station_id=station_id,
        supplier_user_id=user.id,
        ordered_at=now,
        eta_note=body.eta_note or None,
        snoozed_until=snoozed_until,
    )
    db.add(order)
    db.flush()  # populate order.id before creating notifications

    eta_str = body.eta_note.strip() if body.eta_note else "not specified"
    message = (
        f"Supplier {user.email} marked fuel as ordered for {station.name}. "
        f"Expected delivery: {eta_str}."
    )

    recipient_ids = _station_recipients(db, station_id)
    for rid in recipient_ids:
        db.add(Notification(
            user_id=rid,
            station_id=station_id,
            type="fuel_ordered",
            message=message,
            eta_note=body.eta_note or None,
            created_at=now,
        ))
    db.commit()

    _fire_push(db, recipient_ids, {
        "title": f"Fuel ordered — {station.name}",
        "body": f"Supplier: {user.email}  ·  ETA: {eta_str}",
        "tag": f"fuel-ordered-{station_id}",
    })

    return {"ok": True, "snoozed_until": snoozed_until.isoformat()}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _station_recipients(db: Session, station_id: int) -> list[int]:
    """
    Return IDs of active admin and user-role accounts that should receive
    notifications about this station.
      - Admins: all active admins (they see everything).
      - Users: only those explicitly assigned to this station.
    Suppliers are excluded — they're the ones triggering the action.
    """
    rows = db.execute(
        text(
            """
            SELECT DISTINCT u.id
            FROM users u
            LEFT JOIN user_station_assignments a ON a.user_id = u.id AND a.station_id = :sid
            WHERE u.active = TRUE
              AND u.role IN ('admin', 'user')
              AND (u.role = 'admin' OR a.station_id IS NOT NULL)
            """
        ),
        {"sid": station_id},
    ).fetchall()
    return [r[0] for r in rows]


def _fire_push(db: Session, recipient_ids: list[int], payload: dict) -> None:
    """
    Send a Web Push notification to every stored subscription for each
    recipient. Best-effort: individual failures (expired sub, browser
    permission revoked, VAPID not configured) are silently swallowed.

    Requires env vars:
      VAPID_PRIVATE_KEY — EC private key, PEM or base64url raw format
      VAPID_EMAIL       — mailto contact for the push service
    """
    private_key = os.environ.get("VAPID_PRIVATE_KEY")
    email = os.environ.get("VAPID_EMAIL", "admin@example.com")
    if not private_key:
        return  # push not configured — skip quietly

    try:
        from pywebpush import webpush, WebPushException  # type: ignore
    except ImportError:
        return  # pywebpush not installed — degrade gracefully

    data = json.dumps(payload)
    for uid in recipient_ids:
        subs = db.query(PushSubscription).filter(PushSubscription.user_id == uid).all()
        for sub in subs:
            try:
                webpush(
                    subscription_info=json.loads(sub.subscription_json),
                    data=data,
                    vapid_private_key=private_key,
                    vapid_claims={"sub": f"mailto:{email}"},
                    ttl=3600,
                )
            except Exception:
                pass
