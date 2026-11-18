"""
Driver account view — a driver only ever sees the delivery runs assigned to
them (DeliveryRun.driver_user_id), nothing else: no pricing, no other
stations' tank levels, no fleet management. Logs in with a normal password
or a magic link (see auth.py's create_magic_link / POST /api/auth/magic-login)
— either way ends up with the same session, and this router is what that
session can actually see.

Reuses fleet.py's run-building blocks (the response shapes, the arrive-stop
core logic) rather than duplicating them — a driver marking a stop arrived
should behave byte-for-byte the same as a supplier doing it, just gated
differently (own runs only, not the whole fleet).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user, require_not_degraded
from database import get_db
from models import DeliveryRun, DeliveryStop, DeliveryStopItem, Station, User
from routers.fleet import _run_out, arrive_stop_core
from schemas import ArriveStopRequest, DeliveryRunOut

router = APIRouter(dependencies=[Depends(require_not_degraded)])


def _require_driver(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("driver", "admin"):
        raise HTTPException(status_code=403, detail="Driver access required")
    return user


def _get_own_run(run_id: int, user: User, db: Session) -> DeliveryRun:
    run = db.query(DeliveryRun).filter(DeliveryRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Delivery run not found")
    if user.role != "admin" and run.driver_user_id != user.id:
        raise HTTPException(status_code=404, detail="Delivery run not found")
    return run


@router.get("/driver/runs", response_model=list[DeliveryRunOut])
def my_runs(user: User = Depends(_require_driver), db: Session = Depends(get_db)):
    """
    This driver's current work — every run assigned to them that isn't
    finished yet (planned/dispatched). Not filtered to "today" by date on
    purpose: a run is short-lived enough in practice that "not yet
    completed" and "today's deliveries" are the same thing, and this way a
    run that started yesterday evening and finishes after midnight doesn't
    vanish from the driver's list at the stroke of 12.
    """
    q = db.query(DeliveryRun).filter(DeliveryRun.status.in_(["planned", "dispatched"]))
    if user.role != "admin":
        q = q.filter(DeliveryRun.driver_user_id == user.id)
    runs = q.order_by(DeliveryRun.created_at.desc()).all()
    return [_run_out(db, r) for r in runs]


@router.get("/driver/runs/{run_id}", response_model=DeliveryRunOut)
def get_my_run(run_id: int, user: User = Depends(_require_driver), db: Session = Depends(get_db)):
    run = _get_own_run(run_id, user, db)
    return _run_out(db, run)


@router.post("/driver/runs/{run_id}/stops/{stop_id}/arrive", response_model=DeliveryRunOut)
def arrive_my_stop(
    run_id: int, stop_id: int, body: ArriveStopRequest,
    user: User = Depends(_require_driver), db: Session = Depends(get_db),
):
    run = _get_own_run(run_id, user, db)
    return arrive_stop_core(db, run, stop_id, body)


@router.get("/driver/reports/today")
def my_today_report(user: User = Depends(_require_driver), db: Session = Depends(get_db)):
    """
    This driver's own daily summary — stops they've completed today (by
    arrived_at, UTC calendar day — see routers/fleet.py's reports for the
    same caveat on the provider side) plus whatever's still ahead of them
    right now. Small and personal on purpose; the full cross-fleet Reports
    tab is supplier/admin-only (routers/fleet.py).
    """
    today_start = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    q = db.query(DeliveryStop).join(DeliveryRun, DeliveryRun.id == DeliveryStop.delivery_run_id)
    if user.role != "admin":
        q = q.filter(DeliveryRun.driver_user_id == user.id)
    stops = q.filter(
        (DeliveryStop.arrived_at >= today_start) | (DeliveryStop.status.in_(["pending", "in_transit"]))
    ).all()
    if not stops:
        return {"completed_stops": 0, "pending_stops": 0, "gallons_delivered_by_product": {}}

    station_names = {s.id: s.name for s in db.query(Station).filter(Station.id.in_([st.station_id for st in stops])).all()}
    items = db.query(DeliveryStopItem).filter(DeliveryStopItem.delivery_stop_id.in_([s.id for s in stops])).all()
    items_by_stop: dict[int, list] = {}
    for i in items:
        items_by_stop.setdefault(i.delivery_stop_id, []).append(i)

    gallons_by_product: dict[str, float] = {}
    completed = pending = 0
    stop_rows = []
    for s in stops:
        stop_items = items_by_stop.get(s.id, [])
        if s.status == "delivered":
            completed += 1
            for it in stop_items:
                gallons_by_product[it.product] = gallons_by_product.get(it.product, 0.0) + (it.gallons_delivered or 0.0)
        else:
            pending += 1
        stop_rows.append({
            "stop_id": s.id, "station_name": station_names.get(s.station_id, "?"), "status": s.status,
            "items": [{"product": it.product, "gallons_planned": it.gallons_planned, "gallons_delivered": it.gallons_delivered} for it in stop_items],
        })

    return {
        "completed_stops": completed,
        "pending_stops": pending,
        "gallons_delivered_by_product": {k: round(v, 1) for k, v in gallons_by_product.items()},
        "stops": stop_rows,
    }
