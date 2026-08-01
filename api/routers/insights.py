"""Per-poll consumption ledger and "fun stats" endpoints."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from models import DeliveryEvent, Reading, Tank

router = APIRouter()

# Water in a tank above this depth is generally considered worth flagging on
# a TLS-350 (varies by site/alarm config, this is a conservative default).
WATER_ALERT_INCHES = 1.0


@router.get("/tanks/{tank_id}/consumption")
def get_consumption(
    tank_id: int,
    limit: int = Query(15, le=200),
    db: Session = Depends(get_db),
):
    """Gallons consumed (or gained) between each pair of consecutive polls."""
    tank = db.query(Tank).filter(Tank.id == tank_id).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")

    rows = (
        db.query(Reading)
        .filter(Reading.tank_id == tank_id, Reading.volume_gallons.isnot(None))
        .order_by(Reading.polled_at.desc())
        .limit(limit + 1)
        .all()
    )
    rows = list(reversed(rows))  # oldest -> newest

    intervals = []
    for i in range(1, len(rows)):
        prev, curr = rows[i - 1], rows[i]
        hours = (curr.polled_at - prev.polled_at).total_seconds() / 3600.0
        if hours <= 0:
            continue
        delta = prev.volume_gallons - curr.volume_gallons  # positive = consumed
        intervals.append({
            "from_time": prev.polled_at,
            "to_time": curr.polled_at,
            "hours": round(hours, 3),
            "delta_gallons": round(delta, 2),
            "rate_gal_per_hour": round(delta / hours, 2) if hours > 0 else None,
            "is_increase": delta < 0,
        })

    intervals.reverse()  # most recent first, to match the readings/deliveries tables
    return intervals[:limit]


@router.get("/tanks/{tank_id}/stats")
def get_stats(tank_id: int, db: Session = Depends(get_db)):
    tank = db.query(Tank).filter(Tank.id == tank_id).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")

    now = datetime.now(tz=timezone.utc)

    def _consumed_since(since: datetime) -> Optional[float]:
        rows = (
            db.query(Reading)
            .filter(
                Reading.tank_id == tank_id,
                Reading.polled_at >= since,
                Reading.volume_gallons.isnot(None),
            )
            .order_by(Reading.polled_at.asc())
            .all()
        )
        if len(rows) < 2:
            return None
        total = 0.0
        for i in range(1, len(rows)):
            delta = rows[i - 1].volume_gallons - rows[i].volume_gallons
            if delta > 0:  # ignore increases (deliveries) — this is consumption only
                total += delta
        return round(total, 1)

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_consumed = _consumed_since(today_start)
    week_consumed = _consumed_since(now - timedelta(days=7))

    # 30-day average daily consumption (reuses the same "ignore increases" logic).
    rate_rows = db.execute(
        text(
            """
            SELECT polled_at, volume_gallons FROM readings
            WHERE tank_id = :tid AND polled_at >= NOW() - INTERVAL '30 days'
              AND volume_gallons IS NOT NULL
            ORDER BY polled_at ASC
            """
        ),
        {"tid": tank_id},
    ).fetchall()
    total_consumed, total_hours = 0.0, 0.0
    for i in range(1, len(rate_rows)):
        prev_t, prev_v = rate_rows[i - 1]
        curr_t, curr_v = rate_rows[i]
        hrs = (curr_t - prev_t).total_seconds() / 3600.0
        delta = prev_v - curr_v
        if hrs > 0 and delta > 0:
            total_consumed += delta
            total_hours += hrs
    avg_daily = round((total_consumed / total_hours) * 24, 1) if total_hours > 0 else None

    last_delivery = (
        db.query(DeliveryEvent)
        .filter(DeliveryEvent.tank_id == tank_id)
        .order_by(DeliveryEvent.detected_at.desc())
        .first()
    )
    days_since_delivery = (
        round((now - last_delivery.detected_at).total_seconds() / 86400.0, 1)
        if last_delivery else None
    )
    last_delivery_gallons = (
        round(last_delivery.adjusted_gallons_received or last_delivery.gallons_received, 1)
        if last_delivery else None
    )

    temp_row = db.execute(
        text(
            """
            SELECT MIN(temperature_f), MAX(temperature_f) FROM readings
            WHERE tank_id = :tid AND polled_at >= NOW() - INTERVAL '7 days'
              AND temperature_f IS NOT NULL
            """
        ),
        {"tid": tank_id},
    ).first()
    temp_min, temp_max = (temp_row[0], temp_row[1]) if temp_row else (None, None)

    latest = (
        db.query(Reading)
        .filter(Reading.tank_id == tank_id)
        .order_by(Reading.polled_at.desc())
        .first()
    )
    water = latest.water_inches if latest else None
    current_volume = latest.volume_gallons if latest and latest.volume_gallons else None

    turnover_days = (
        round((tank.capacity_gallons or 0) / avg_daily, 1)
        if avg_daily and avg_daily > 0 and tank.capacity_gallons
        else None
    )

    return {
        "tank_id": tank_id,
        "today_consumed_gallons": today_consumed,
        "week_consumed_gallons": week_consumed,
        "avg_daily_gallons_30d": avg_daily,
        "days_since_last_delivery": days_since_delivery,
        "last_delivery_gallons": last_delivery_gallons,
        "temp_min_7d": round(temp_min, 1) if temp_min is not None else None,
        "temp_max_7d": round(temp_max, 1) if temp_max is not None else None,
        "water_inches_latest": round(water, 2) if water is not None else None,
        "water_alert": bool(water is not None and water >= WATER_ALERT_INCHES),
        "turnover_days_estimate": turnover_days,
        "current_volume_gallons": current_volume,
    }
