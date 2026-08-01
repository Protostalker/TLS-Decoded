"""Readings and predictions endpoints."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import engine, get_db
from models import Reading, Tank
from schemas import DeliveryEventOut, PredictionOut, ReadingOut
from models import DeliveryEvent
from routers.deliveries import _to_out as _delivery_to_out

router = APIRouter()


@router.get("/tanks/{tank_id}/readings", response_model=list[ReadingOut])
def get_readings(
    tank_id: int,
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    limit: int = Query(500, le=5000),
    db: Session = Depends(get_db),
):
    tank = db.query(Tank).filter(Tank.id == tank_id).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")

    q = db.query(Reading).filter(Reading.tank_id == tank_id)
    if from_:
        q = q.filter(Reading.polled_at >= from_)
    if to:
        q = q.filter(Reading.polled_at <= to)
    q = q.order_by(Reading.polled_at.desc()).limit(limit)
    return [ReadingOut.model_validate(r) for r in q.all()]


@router.get("/tanks/{tank_id}/deliveries", response_model=list[DeliveryEventOut])
def get_deliveries(
    tank_id: int,
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
):
    tank = db.query(Tank).filter(Tank.id == tank_id).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")

    events = (
        db.query(DeliveryEvent)
        .filter(DeliveryEvent.tank_id == tank_id)
        .order_by(DeliveryEvent.detected_at.desc())
        .limit(limit)
        .all()
    )
    return [_delivery_to_out(e) for e in events]


@router.get("/tanks/{tank_id}/prediction", response_model=PredictionOut)
def get_prediction(tank_id: int, db: Session = Depends(get_db)):
    tank = db.query(Tank).filter(Tank.id == tank_id, Tank.active == True).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")

    # Get latest volume
    latest = (
        db.query(Reading)
        .filter(Reading.tank_id == tank_id)
        .order_by(Reading.polled_at.desc())
        .first()
    )
    current_volume = latest.volume_gallons if latest and latest.volume_gallons else 0.0

    # Consumption rate from DB
    window_hours = 168  # default; could be loaded from config
    rate_result = db.execute(
        text(
            f"""
            SELECT polled_at, volume_gallons
            FROM readings
            WHERE tank_id = :tid
              AND polled_at >= NOW() - INTERVAL '{window_hours} hours'
              AND volume_gallons IS NOT NULL
            ORDER BY polled_at ASC
            """
        ),
        {"tid": tank_id},
    ).fetchall()

    rate = _calc_rate(rate_result)

    # Data age for confidence
    age_result = db.execute(
        text(
            """
            SELECT EXTRACT(EPOCH FROM (MAX(polled_at) - MIN(polled_at))) / 3600.0
            FROM readings WHERE tank_id = :tid
            """
        ),
        {"tid": tank_id},
    ).scalar()
    data_hours = float(age_result) if age_result else 0.0
    confidence = "low" if data_hours < 48 else ("medium" if data_hours < 168 else "high")

    if rate is None or rate <= 0:
        return PredictionOut(
            tank_id=tank_id,
            consumption_rate_gal_per_hour=None,
            consumption_rate_gal_per_day=None,
            days_until_reorder=None,
            days_until_empty=None,
            projected_reorder_date=None,
            confidence="low",
            note="Insufficient data for rate calculation",
        )

    rate_per_day = rate * 24.0
    reorder_threshold = tank.reorder_threshold_gallons or 0.0
    now = datetime.now(tz=timezone.utc)

    days_until_reorder = None
    projected_reorder_date = None
    if current_volume > reorder_threshold and rate_per_day > 0:
        from datetime import timedelta
        days_until_reorder = (current_volume - reorder_threshold) / rate_per_day
        projected_reorder_date = (now + timedelta(days=days_until_reorder)).isoformat()

    days_until_empty = current_volume / rate_per_day if rate_per_day > 0 else None

    return PredictionOut(
        tank_id=tank_id,
        consumption_rate_gal_per_hour=round(rate, 4),
        consumption_rate_gal_per_day=round(rate_per_day, 2),
        days_until_reorder=round(days_until_reorder, 2) if days_until_reorder is not None else None,
        days_until_empty=round(days_until_empty, 2) if days_until_empty is not None else None,
        projected_reorder_date=projected_reorder_date,
        confidence=confidence,
    )


def _calc_rate(rows) -> Optional[float]:
    """Rolling average consumption gal/hr, ignoring delivery periods."""
    if len(rows) < 2:
        return None
    total_consumed = 0.0
    total_hours = 0.0
    for i in range(1, len(rows)):
        prev_time, prev_vol = rows[i - 1]
        curr_time, curr_vol = rows[i]
        if prev_vol is None or curr_vol is None:
            continue
        delta_vol = prev_vol - curr_vol
        delta_secs = (curr_time - prev_time).total_seconds()
        delta_hours = delta_secs / 3600.0
        if delta_hours <= 0 or delta_vol < 0:
            continue
        total_consumed += delta_vol
        total_hours += delta_hours
    if total_hours == 0:
        return None
    return total_consumed / total_hours
