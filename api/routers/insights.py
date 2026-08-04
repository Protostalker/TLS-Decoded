"""Per-poll consumption ledger and "fun stats" endpoints."""
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from models import DeliveryEvent, FuelPrice, Reading, Tank

# Station is in Los Angeles (Pacific time).  All calendar-day boundaries
# (e.g. "today consumed") are computed in this timezone so that midnight
# means local midnight, not UTC midnight.
STATION_TZ = ZoneInfo("America/Los_Angeles")

router = APIRouter()

# Water in a tank above this depth is generally considered worth flagging on
# a TLS-350 (varies by site/alarm config, this is a conservative default).
WATER_ALERT_INCHES = 1.0


# ── Margin helpers ────────────────────────────────────────────────────────────

def _effective_margin(tank_id: int, at: datetime, db: Session) -> Optional[float]:
    """
    Return the margin/gal in effect as of `at` (tz-aware), or None if no
    price has been entered yet.  Margin = sale_price - cost - tax_fees.

    Uses the same point-in-time lookup as the pricing router: the most recent
    fuel_prices row with effective_at <= `at`.  Retroactively editing a price
    automatically changes any stat that re-queries for that day.
    """
    row = (
        db.query(FuelPrice)
        .filter(FuelPrice.tank_id == tank_id, FuelPrice.effective_at <= at)
        .order_by(FuelPrice.effective_at.desc())
        .first()
    )
    if not row:
        return None
    cost = float(row.cost_per_gallon or 0)
    tax  = float(row.tax_fees_per_gallon or 0)
    sale = float(row.sale_price_per_gallon or 0)
    return round(sale - cost - tax, 6)


def _build_daily_breakdown(tank_id: int, num_days: int, db: Session) -> list[dict]:
    """
    For each of the last `num_days` Pacific calendar days (inclusive of today),
    return:
        date             – ISO date string "YYYY-MM-DD"
        gallons          – net consumption (positive); 0.0 if no drop that day
        margin_per_gallon – effective margin at start-of-day; None if no price set
        margin_dollars   – gallons × margin_per_gallon; None if no price set

    Attribution rule: each poll-to-poll volume drop is assigned to the day
    that contains the *end* (later) reading.  This handles midnight-spanning
    intervals naturally and matches the time the sale was recorded.

    Deliveries (volume increases) are excluded from consumption, same as the
    rolling _consumed_since() helper.
    """
    today_local = datetime.now(tz=STATION_TZ).date()

    # One datetime per day-start, oldest first
    day_starts: list[datetime] = [
        datetime(
            *(today_local - timedelta(days=num_days - 1 - i)).timetuple()[:3],
            tzinfo=STATION_TZ,
        )
        for i in range(num_days)
    ]

    # Fetch readings covering the whole window plus a buffer before the first day
    # so that the interval spanning into day[0] is included.
    window_start = day_starts[0] - timedelta(hours=2)
    window_end   = day_starts[-1] + timedelta(days=1)

    readings = (
        db.query(Reading)
        .filter(
            Reading.tank_id == tank_id,
            Reading.polled_at >= window_start,
            Reading.polled_at < window_end,
            Reading.volume_gallons.isnot(None),
        )
        .order_by(Reading.polled_at.asc())
        .all()
    )

    # Accumulate consumption per calendar day
    day_gallons: dict[date, float] = {ds.date(): 0.0 for ds in day_starts}
    for i in range(1, len(readings)):
        prev, curr = readings[i - 1], readings[i]
        delta = prev.volume_gallons - curr.volume_gallons
        if delta <= 0:
            continue  # delivery or noise — skip
        curr_day = curr.polled_at.astimezone(STATION_TZ).date()
        if curr_day in day_gallons:
            day_gallons[curr_day] = round(day_gallons[curr_day] + delta, 1)

    # Build final list with point-in-time margin lookup for each day
    breakdown: list[dict] = []
    for ds in day_starts:
        d = ds.date()
        gallons = day_gallons.get(d, 0.0)
        mpg = _effective_margin(tank_id, ds, db)
        breakdown.append({
            "date": d.isoformat(),
            "gallons": gallons,
            "margin_per_gallon": mpg,
            "margin_dollars": round(gallons * mpg, 2) if mpg is not None else None,
        })
    return breakdown


def _safe_margin_sum(breakdown: list[dict]) -> Optional[float]:
    """Sum margin_dollars across breakdown; returns None only if every entry has None margin."""
    vals = [e["margin_dollars"] for e in breakdown if e["margin_dollars"] is not None]
    return round(sum(vals), 2) if vals else None


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
        """Sum all poll-to-poll volume drops since `since`, skipping delivery jumps."""
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

    # "Today" = midnight in station's local timezone (Pacific), NOT UTC midnight.
    # At e.g. 17:15 PDT the UTC date has already rolled over, so using UTC
    # midnight would exclude hours 00:00–07:00 local time from the total.
    now_local = datetime.now(tz=STATION_TZ)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_consumed = _consumed_since(today_start_local)

    # "Last 7 days" is a rolling window — no calendar-day boundary involved,
    # so UTC is fine here.
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

    # ── Day-by-day margin breakdown ──────────────────────────────────────────
    # Each entry: {date, gallons, margin_per_gallon, margin_dollars}
    # Gallons use the same delta-sum / delivery-skip logic as _consumed_since.
    # Margin does a point-in-time price lookup so retroactive price edits
    # are automatically reflected the next time stats are fetched.
    breakdown_7d  = _build_daily_breakdown(tank_id, 7,  db)
    breakdown_30d = _build_daily_breakdown(tank_id, 30, db)

    return {
        "tank_id": tank_id,
        "today_consumed_gallons": today_consumed,
        "week_consumed_gallons": week_consumed,
        "total_margin_7d": _safe_margin_sum(breakdown_7d),
        "daily_breakdown_7d": breakdown_7d,
        "avg_daily_gallons_30d": avg_daily,
        "total_margin_30d": _safe_margin_sum(breakdown_30d),
        "daily_breakdown_30d": breakdown_30d,
        "days_since_last_delivery": days_since_delivery,
        "last_delivery_gallons": last_delivery_gallons,
        "temp_min_7d": round(temp_min, 1) if temp_min is not None else None,
        "temp_max_7d": round(temp_max, 1) if temp_max is not None else None,
        "water_inches_latest": round(water, 2) if water is not None else None,
        "water_alert": bool(water is not None and water >= WATER_ALERT_INCHES),
        "turnover_days_estimate": turnover_days,
        "current_volume_gallons": current_volume,
    }
