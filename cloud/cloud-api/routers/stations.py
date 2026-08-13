"""
T1 (station-scoped dashboard, reused by the cloud-served frontend for
whichever station is selected) + T2 (station picker list, combined stats
across a user's assigned stations). All reads come from the cloud DB's
mirrored copy — never from a station directly, per the Option B design.

Stats logic mirrors api/routers/insights.py's `_compute_tank_stats` /
`get_stats_summary` pattern, adapted to read from cloud_* tables scoped by
station_id, and to loop over stations (not just tanks) for the T2 combined
view — "same pattern one level up," as the design doc puts it.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import assigned_station_ids, get_current_user, require_station_access
from database import get_db
from models import CloudDeliveryEvent, CloudFuelPrice, CloudReading, CloudTank, PendingPriceUpdate, Station, User
from schemas import PredictionOut, PriceUpdateRequest, ReadingOut, StationDashboardOut, StationOut, TankOut
from weather import get_station_weather

router = APIRouter()


def _station_out(db: Session, s: Station) -> StationOut:
    from models import Customer
    cust = db.query(Customer).filter(Customer.id == s.customer_id).first()
    return StationOut(
        id=s.id, name=s.name, customer_id=s.customer_id,
        customer_name=cust.name if cust else None,
        sync_interval_minutes=s.sync_interval_minutes, last_sync_at=s.last_sync_at, active=s.active,
        zip_code=s.zip_code, timezone=s.timezone,
        brand_preset=s.brand_preset, brand_primary_color=s.brand_primary_color,
        brand_secondary_color=s.brand_secondary_color, brand_accent_color=s.brand_accent_color,
        brand_logo_data_url=s.brand_logo_data_url,
    )


# ── T2: station picker ───────────────────────────────────────────────────────

@router.get("/me/stations", response_model=list[StationOut])
def my_stations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = assigned_station_ids(db, user)
    stations = db.query(Station).filter(Station.id.in_(ids)).order_by(Station.name).all() if ids else []
    return [_station_out(db, s) for s in stations]


# ── Shared stats calc ────────────────────────────────────────────────────────

def _latest_reading(db: Session, station_id: int, tank_local_id: int) -> Optional[CloudReading]:
    return (
        db.query(CloudReading)
        .filter(CloudReading.station_id == station_id, CloudReading.tank_local_id == tank_local_id)
        .order_by(CloudReading.polled_at.desc())
        .first()
    )


def _consumed_since(db: Session, station_id: int, tank_local_id: int, since: datetime) -> Optional[float]:
    rows = (
        db.query(CloudReading)
        .filter(
            CloudReading.station_id == station_id, CloudReading.tank_local_id == tank_local_id,
            CloudReading.polled_at >= since, CloudReading.volume_gallons.isnot(None),
        )
        .order_by(CloudReading.polled_at.asc())
        .all()
    )
    if len(rows) < 2:
        return None
    total = 0.0
    for i in range(1, len(rows)):
        delta = rows[i - 1].volume_gallons - rows[i].volume_gallons
        if delta > 0:
            total += delta
    return round(total, 1)


def _effective_margin(db: Session, station_id: int, tank_local_id: int, at: datetime) -> Optional[float]:
    row = (
        db.query(CloudFuelPrice)
        .filter(
            CloudFuelPrice.station_id == station_id, CloudFuelPrice.tank_local_id == tank_local_id,
            CloudFuelPrice.effective_at <= at,
        )
        .order_by(CloudFuelPrice.effective_at.desc())
        .first()
    )
    if not row:
        return None
    cost = float(row.cost_per_gallon or 0)
    tax = float(row.tax_fees_per_gallon or 0)
    sale = float(row.sale_price_per_gallon or 0)
    return round(sale - cost - tax, 6)


def _consumption_rate_gal_per_hour(db: Session, station_id: int, tank_local_id: int, window_hours: int = 168) -> Optional[float]:
    rows = db.execute(
        text(
            """
            SELECT polled_at, volume_gallons FROM cloud_readings
            WHERE station_id = :sid AND tank_local_id = :tlid
              AND polled_at >= NOW() - (:hrs * INTERVAL '1 hour')
              AND volume_gallons IS NOT NULL
            ORDER BY polled_at ASC
            """
        ),
        {"sid": station_id, "tlid": tank_local_id, "hrs": window_hours},
    ).fetchall()
    total_consumed, total_hours = 0.0, 0.0
    for i in range(1, len(rows)):
        prev_t, prev_v = rows[i - 1]
        curr_t, curr_v = rows[i]
        hrs = (curr_t - prev_t).total_seconds() / 3600.0
        delta = prev_v - curr_v
        if hrs > 0 and delta > 0:
            total_consumed += delta
            total_hours += hrs
    return round(total_consumed / total_hours, 4) if total_hours > 0 else None


def station_tz(station: Station) -> ZoneInfo:
    """Station's calendar-day timezone for 'today'/day-by-day math — matches
    api/routers/insights.py's STATION_TZ on the station side. Falls back to
    Pacific (this codebase's original/only station) if unset; set explicitly
    from T3 (Admin -> Stations -> Timezone) for stations elsewhere."""
    try:
        return ZoneInfo(station.timezone) if station.timezone else ZoneInfo("America/Los_Angeles")
    except Exception:
        return ZoneInfo("America/Los_Angeles")


def _build_daily_breakdown(db: Session, station_id: int, tank_local_id: int, num_days: int, tz: ZoneInfo) -> list[dict]:
    """Port of api/routers/insights.py's _build_daily_breakdown, scoped to
    the cloud mirror's station_id/tank_local_id — day-by-day gallons valued
    at the price *in effect on that day*, not today's price applied
    retroactively. This is what total_margin_7d/30d must sum, or a
    mid-week price change silently over/under-values the whole window."""
    today_local = datetime.now(tz=tz).date()
    day_starts = [
        datetime(*(today_local - timedelta(days=num_days - 1 - i)).timetuple()[:3], tzinfo=tz)
        for i in range(num_days)
    ]
    window_start = day_starts[0] - timedelta(hours=2)
    window_end = day_starts[-1] + timedelta(days=1)

    rows = (
        db.query(CloudReading)
        .filter(
            CloudReading.station_id == station_id, CloudReading.tank_local_id == tank_local_id,
            CloudReading.polled_at >= window_start, CloudReading.polled_at < window_end,
            CloudReading.volume_gallons.isnot(None),
        )
        .order_by(CloudReading.polled_at.asc())
        .all()
    )

    day_gallons: dict = {ds.date(): 0.0 for ds in day_starts}
    for i in range(1, len(rows)):
        prev, curr = rows[i - 1], rows[i]
        delta = prev.volume_gallons - curr.volume_gallons
        if delta <= 0:
            continue
        curr_day = curr.polled_at.astimezone(tz).date()
        if curr_day in day_gallons:
            day_gallons[curr_day] = round(day_gallons[curr_day] + delta, 1)

    breakdown = []
    for ds in day_starts:
        d = ds.date()
        gallons = day_gallons.get(d, 0.0)
        mpg = _effective_margin(db, station_id, tank_local_id, ds)
        breakdown.append({
            "date": d.isoformat(), "gallons": gallons,
            "margin_per_gallon": mpg,
            "margin_dollars": round(gallons * mpg, 2) if mpg is not None else None,
        })
    return breakdown


def _safe_margin_sum(breakdown: list[dict]) -> Optional[float]:
    vals = [e["margin_dollars"] for e in breakdown if e["margin_dollars"] is not None]
    return round(sum(vals), 2) if vals else None


def _compute_tank_stats(db: Session, station: Station, tank: CloudTank) -> dict:
    station_id = station.id
    tz = station_tz(station)
    now = datetime.now(tz=timezone.utc)

    # "Today" = midnight in the STATION's own local timezone, not UTC — a
    # station well west of UTC (e.g. Pacific) would otherwise show a
    # truncated "today" for most of the afternoon/evening. Matches the
    # station's own local dashboard exactly (see insights.py).
    now_local = datetime.now(tz=tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_consumed = _consumed_since(db, station_id, tank.local_id, today_start_local)

    # Rolling 7-day window — no calendar boundary involved, UTC is fine.
    week_consumed = _consumed_since(db, station_id, tank.local_id, now - timedelta(days=7))

    rate = _consumption_rate_gal_per_hour(db, station_id, tank.local_id, 720)  # 30d
    avg_daily = round(rate * 24, 1) if rate else None

    last_delivery = (
        db.query(CloudDeliveryEvent)
        .filter(CloudDeliveryEvent.station_id == station_id, CloudDeliveryEvent.tank_local_id == tank.local_id)
        .order_by(CloudDeliveryEvent.detected_at.desc())
        .first()
    )
    days_since_delivery = (
        round((now - last_delivery.detected_at).total_seconds() / 86400.0, 1) if last_delivery else None
    )

    latest = _latest_reading(db, station_id, tank.local_id)
    water = latest.water_inches if latest else None
    current_volume = latest.volume_gallons if latest and latest.volume_gallons else None

    # Day-by-day margin breakdown — each day's gallons valued at the price
    # that was actually in effect that day, then summed. Replaces the old
    # "week_consumed * today's current margin" shortcut, which overstates
    # (or understates) the week whenever a price changed mid-week.
    breakdown_7d = _build_daily_breakdown(db, station_id, tank.local_id, 7, tz)

    current_margin = _effective_margin(db, station_id, tank.local_id, now)
    today_profit = (
        round(today_consumed * current_margin, 2)
        if today_consumed is not None and current_margin is not None else None
    )
    week_margin = _safe_margin_sum(breakdown_7d)

    return {
        "tank_local_id": tank.local_id,
        "tank_name": tank.name,
        "product": tank.product,
        "capacity_gallons": tank.capacity_gallons,
        "today_consumed_gallons": today_consumed,
        "today_profit_dollars": today_profit,
        "week_consumed_gallons": week_consumed,
        "total_margin_7d": week_margin,
        "avg_daily_gallons_30d": avg_daily,
        "days_since_last_delivery": days_since_delivery,
        "water_inches_latest": round(water, 2) if water is not None else None,
        "water_alert": bool(water is not None and water >= 1.0),
        "current_volume_gallons": current_volume,
        "current_margin_per_gallon": current_margin,
    }


# ── T2: combined stats across all assigned stations ─────────────────────────

@router.get("/me/stats/summary")
def combined_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Loop over the user's assigned stations, loop over each station's active
    tanks, reuse the same per-tank stats function, combine — same pattern the
    local /api/stats/summary already uses one level down (tanks within a
    station), just one level up (stations within an account)."""
    ids = assigned_station_ids(db, user)
    stations = db.query(Station).filter(Station.id.in_(ids)).order_by(Station.name).all() if ids else []

    per_station = []
    for s in stations:
        tanks = (
            db.query(CloudTank)
            .filter(CloudTank.station_id == s.id, CloudTank.active == True)  # noqa: E712
            .order_by(CloudTank.local_id)
            .all()
        )
        tank_stats = [_compute_tank_stats(db, s, t) for t in tanks]
        per_station.append((s, tank_stats))

    def _sum_across(tss_list: list[dict], key: str) -> Optional[float]:
        vals = [ts[key] for ts in tss_list if ts[key] is not None]
        return round(sum(vals), 2) if vals else None

    def _sum(key: str) -> Optional[float]:
        vals = [ts[key] for _, tss in per_station for ts in tss if ts[key] is not None]
        return round(sum(vals), 2) if vals else None

    return {
        "today_consumed_gallons": _sum("today_consumed_gallons"),
        "today_profit_dollars": _sum("today_profit_dollars"),
        "week_consumed_gallons": _sum("week_consumed_gallons"),
        "total_margin_7d": _sum("total_margin_7d"),
        "avg_daily_gallons_30d": _sum("avg_daily_gallons_30d"),
        "stations": [
            {
                "station_id": s.id,
                "station_name": s.name,
                "last_sync_at": s.last_sync_at,
                "today_consumed_gallons": _sum_across(tss, "today_consumed_gallons"),
                "today_profit_dollars": _sum_across(tss, "today_profit_dollars"),
                "week_consumed_gallons": _sum_across(tss, "week_consumed_gallons"),
                "total_margin_7d": _sum_across(tss, "total_margin_7d"),
                "avg_daily_gallons_30d": _sum_across(tss, "avg_daily_gallons_30d"),
                "tank_count": len(tss),
                "water_alert": any(t["water_alert"] for t in tss),
                "days_since_last_delivery": (
                    min((t["days_since_last_delivery"] for t in tss if t["days_since_last_delivery"] is not None), default=None)
                ),
                "tanks": tss,
            }
            for s, tss in per_station
        ],
    }


# ── Weather (T1 full panel, T2 condensed) ────────────────────────────────────
#
# Best-effort only — a station without a zip_code, or an upstream hiccup,
# just means the weather panel/chip is omitted; never blocks the dashboard
# or the ingest/sync pipeline. See weather.py for the upstreams + caching.

@router.get("/stations/{station_id}/weather")
def station_weather(station_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    station = require_station_access(station_id, db, user)
    if not station.zip_code:
        return {"configured": False}
    w = get_station_weather(station.zip_code)
    if w is None:
        return {"configured": True, "available": False}
    return {"configured": True, "available": True, **w}


@router.get("/me/weather-summary")
def weather_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Condensed per-station weather for the T2 hub — current conditions plus
    the top recommendation (if any), not the full multi-day forecast. Reuses
    weather.py's cache, so this stays fast after each station's first hit."""
    ids = assigned_station_ids(db, user)
    stations = db.query(Station).filter(Station.id.in_(ids)).all() if ids else []
    out = {}
    for s in stations:
        if not s.zip_code:
            continue
        w = get_station_weather(s.zip_code)
        if not w:
            continue
        out[s.id] = {
            "location": w["location"],
            "current": w["current"],
            "recommendation_count": len(w["recommendations"]),
            "top_recommendation": w["recommendations"][0]["message"] if w["recommendations"] else None,
        }
    return out


# ── T1: single-station dashboard, served from the cloud mirror ──────────────

@router.get("/stations/{station_id}/dashboard", response_model=StationDashboardOut)
def station_dashboard(station_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    station = require_station_access(station_id, db, user)

    tanks = (
        db.query(CloudTank)
        .filter(CloudTank.station_id == station_id, CloudTank.active == True)  # noqa: E712
        .order_by(CloudTank.local_id)
        .all()
    )

    tank_outs: list[TankOut] = []
    predictions: list[PredictionOut] = []

    for tank in tanks:
        latest = _latest_reading(db, station_id, tank.local_id)
        tank_outs.append(TankOut(
            local_id=tank.local_id, name=tank.name, product=tank.product,
            capacity_gallons=tank.capacity_gallons, reorder_threshold_gallons=tank.reorder_threshold_gallons,
            active=tank.active,
            latest_reading=ReadingOut.model_validate(latest, from_attributes=True) if latest else None,
        ))

        current_volume = latest.volume_gallons if latest and latest.volume_gallons else 0.0
        rate = _consumption_rate_gal_per_hour(db, station_id, tank.local_id, 168)

        age_row = db.execute(
            text(
                "SELECT EXTRACT(EPOCH FROM (MAX(polled_at) - MIN(polled_at))) / 3600.0 "
                "FROM cloud_readings WHERE station_id = :sid AND tank_local_id = :tlid"
            ),
            {"sid": station_id, "tlid": tank.local_id},
        ).scalar()
        data_hours = float(age_row) if age_row else 0.0
        confidence = "low" if data_hours < 48 else ("medium" if data_hours < 168 else "high")

        if rate and rate > 0:
            rate_per_day = rate * 24.0
            reorder_threshold = tank.reorder_threshold_gallons or 0.0
            now = datetime.now(tz=timezone.utc)
            days_until_reorder = None
            projected_reorder_date = None
            if current_volume > reorder_threshold:
                days_until_reorder = (current_volume - reorder_threshold) / rate_per_day
                projected_reorder_date = (now + timedelta(days=days_until_reorder)).isoformat()
            days_until_empty = current_volume / rate_per_day if rate_per_day > 0 else None
            predictions.append(PredictionOut(
                tank_local_id=tank.local_id,
                consumption_rate_gal_per_hour=round(rate, 4),
                consumption_rate_gal_per_day=round(rate_per_day, 2),
                days_until_reorder=round(days_until_reorder, 2) if days_until_reorder is not None else None,
                days_until_empty=round(days_until_empty, 2) if days_until_empty is not None else None,
                projected_reorder_date=projected_reorder_date,
                confidence=confidence,
            ))
        else:
            predictions.append(PredictionOut(
                tank_local_id=tank.local_id,
                consumption_rate_gal_per_hour=None, consumption_rate_gal_per_day=None,
                days_until_reorder=None, days_until_empty=None, projected_reorder_date=None,
                confidence="low", note="Insufficient data",
            ))

    last_poll_row = db.execute(
        text(
            "SELECT polled_at, success, error_message FROM cloud_poll_log "
            "WHERE station_id = :sid ORDER BY polled_at DESC LIMIT 1"
        ),
        {"sid": station_id},
    ).first()
    last_poll_at, last_poll_success, last_poll_error = last_poll_row if last_poll_row else (None, None, None)

    return StationDashboardOut(
        station_id=station.id, station_name=station.name, tanks=tank_outs, predictions=predictions,
        last_poll_at=last_poll_at, last_poll_success=last_poll_success, last_poll_error=last_poll_error,
        last_sync_at=station.last_sync_at,
        brand_preset=station.brand_preset, brand_primary_color=station.brand_primary_color,
        brand_secondary_color=station.brand_secondary_color, brand_accent_color=station.brand_accent_color,
        brand_logo_data_url=station.brand_logo_data_url,
    )


@router.get("/stations/{station_id}/tanks", response_model=list[TankOut])
def station_tanks(station_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_station_access(station_id, db, user)
    tanks = (
        db.query(CloudTank)
        .filter(CloudTank.station_id == station_id, CloudTank.active == True)  # noqa: E712
        .order_by(CloudTank.local_id)
        .all()
    )
    out = []
    for tank in tanks:
        latest = _latest_reading(db, station_id, tank.local_id)
        out.append(TankOut(
            local_id=tank.local_id, name=tank.name, product=tank.product,
            capacity_gallons=tank.capacity_gallons, reorder_threshold_gallons=tank.reorder_threshold_gallons,
            active=tank.active,
            latest_reading=ReadingOut.model_validate(latest, from_attributes=True) if latest else None,
        ))
    return out


@router.get("/stations/{station_id}/tanks/{tank_local_id}/readings", response_model=list[ReadingOut])
def station_tank_readings(
    station_id: int, tank_local_id: int, limit: int = 500,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    require_station_access(station_id, db, user)
    rows = (
        db.query(CloudReading)
        .filter(CloudReading.station_id == station_id, CloudReading.tank_local_id == tank_local_id)
        .order_by(CloudReading.polled_at.desc())
        .limit(min(limit, 2000))
        .all()
    )
    return [ReadingOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/stations/{station_id}/tanks/{tank_local_id}/deliveries")
def station_tank_deliveries(
    station_id: int, tank_local_id: int,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    require_station_access(station_id, db, user)
    rows = (
        db.query(CloudDeliveryEvent)
        .filter(CloudDeliveryEvent.station_id == station_id, CloudDeliveryEvent.tank_local_id == tank_local_id)
        .order_by(CloudDeliveryEvent.detected_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "local_id": r.local_id, "tank_local_id": r.tank_local_id, "detected_at": r.detected_at,
            "start_volume_gallons": r.start_volume_gallons, "end_volume_gallons": r.end_volume_gallons,
            "gallons_received": r.gallons_received, "adjusted_gallons_received": r.adjusted_gallons_received,
            "confirmed": r.confirmed, "manual_gallons_received": r.manual_gallons_received,
            "note": r.note,
            "effective_gallons_received": (
                r.manual_gallons_received if r.manual_gallons_received is not None
                else (r.adjusted_gallons_received if r.adjusted_gallons_received is not None else r.gallons_received)
            ),
        }
        for r in rows
    ]


@router.get("/stations/{station_id}/tanks/{tank_local_id}/prices")
def station_tank_prices(
    station_id: int, tank_local_id: int, limit: int = 10,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    if user.role == "supplier":
        raise HTTPException(status_code=403, detail="Suppliers do not have access to pricing data")
    require_station_access(station_id, db, user)
    rows = (
        db.query(CloudFuelPrice)
        .filter(CloudFuelPrice.station_id == station_id, CloudFuelPrice.tank_local_id == tank_local_id)
        .order_by(CloudFuelPrice.effective_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for r in rows:
        cost = float(r.cost_per_gallon or 0)
        tax = float(r.tax_fees_per_gallon or 0)
        sale = float(r.sale_price_per_gallon or 0)
        out.append({
            "local_id": r.local_id, "tank_local_id": r.tank_local_id, "effective_at": r.effective_at,
            "cost_per_gallon": cost, "tax_fees_per_gallon": tax, "sale_price_per_gallon": sale,
            "breakeven_per_gallon": round(cost + tax, 6), "margin_per_gallon": round(sale - cost - tax, 6),
            "source": r.source, "note": r.note,
        })
    return out


@router.get("/stations/{station_id}/tanks/{tank_local_id}/stats")
def station_tank_stats(
    station_id: int, tank_local_id: int,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    station = require_station_access(station_id, db, user)
    tank = db.query(CloudTank).filter(CloudTank.station_id == station_id, CloudTank.local_id == tank_local_id).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")
    stats = _compute_tank_stats(db, station, tank)
    # Suppliers see operational data (gallons, water, deliveries) but not
    # financial data (profit, margin).  Strip those fields before returning.
    if user.role == "supplier":
        for key in ("today_profit_dollars", "total_margin_7d", "current_margin_per_gallon"):
            stats.pop(key, None)
    return stats


# ── Price updates from the cloud side (T1) ───────────────────────────────────
#
# v1 sync is one-way (station -> cloud), so a price change entered here can't
# write straight to the station's DB. Instead it's queued as a
# PendingPriceUpdate; the station's own `sync` container polls for pending
# rows (see routers/ingest.py's device-credential endpoints + sync/main.py)
# and applies them locally, same as an operator typing it in at the station.

def _price_update_out(p: PendingPriceUpdate) -> dict:
    return {
        "id": p.id, "station_id": p.station_id, "tank_local_id": p.tank_local_id,
        "cost_per_gallon": float(p.cost_per_gallon) if p.cost_per_gallon is not None else None,
        "tax_rate_percent": float(p.tax_rate_percent) if p.tax_rate_percent is not None else None,
        "tax_fees_per_gallon": float(p.tax_fees_per_gallon) if p.tax_fees_per_gallon is not None else None,
        "sale_price_per_gallon": float(p.sale_price_per_gallon) if p.sale_price_per_gallon is not None else None,
        "effective_at": p.effective_at, "note": p.note, "created_at": p.created_at, "applied_at": p.applied_at,
    }


@router.post("/stations/{station_id}/tanks/{tank_local_id}/price-updates")
def submit_price_update(
    station_id: int, tank_local_id: int, body: PriceUpdateRequest,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    if user.role == "supplier":
        raise HTTPException(status_code=403, detail="Suppliers do not have access to pricing data")
    require_station_access(station_id, db, user)
    if not db.query(CloudTank).filter(CloudTank.station_id == station_id, CloudTank.local_id == tank_local_id).first():
        raise HTTPException(status_code=404, detail="Tank not found")
    if body.cost_per_gallon < 0 or body.sale_price_per_gallon < 0:
        raise HTTPException(status_code=400, detail="Prices must be >= 0")

    tax_fees = body.tax_fees_per_gallon
    if body.tax_rate_percent is not None:
        tax_fees = round(body.cost_per_gallon * body.tax_rate_percent / 100, 6)

    row = PendingPriceUpdate(
        station_id=station_id, tank_local_id=tank_local_id,
        cost_per_gallon=body.cost_per_gallon, tax_rate_percent=body.tax_rate_percent,
        tax_fees_per_gallon=tax_fees, sale_price_per_gallon=body.sale_price_per_gallon,
        effective_at=body.effective_at or datetime.now(tz=timezone.utc),
        note=body.note, created_by_user_id=user.id, created_at=datetime.now(tz=timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _price_update_out(row)


@router.get("/stations/{station_id}/price-updates")
def list_price_updates(
    station_id: int, limit: int = 20,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Recent price-update requests for this station (pending and applied),
    so the UI can show 'submitted, waiting for the station to pick it up'
    vs. 'applied at {time}' — the station polls on its own sync interval, so
    this isn't instant, same honesty-about-latency as the staleness badges."""
    if user.role == "supplier":
        raise HTTPException(status_code=403, detail="Suppliers do not have access to pricing data")
    require_station_access(station_id, db, user)
    rows = (
        db.query(PendingPriceUpdate)
        .filter(PendingPriceUpdate.station_id == station_id)
        .order_by(PendingPriceUpdate.created_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    return [_price_update_out(r) for r in rows]


@router.get("/stations/{station_id}/stats/summary")
def station_stats_summary(station_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    station = require_station_access(station_id, db, user)
    tanks = (
        db.query(CloudTank)
        .filter(CloudTank.station_id == station_id, CloudTank.active == True)  # noqa: E712
        .order_by(CloudTank.local_id)
        .all()
    )
    tank_stats = [_compute_tank_stats(db, station, t) for t in tanks]

    # Strip financial fields for supplier role before building the summary.
    is_supplier = user.role == "supplier"
    if is_supplier:
        financial_keys = ("today_profit_dollars", "total_margin_7d", "current_margin_per_gallon")
        for ts in tank_stats:
            for k in financial_keys:
                ts.pop(k, None)

    def _sum(key: str) -> Optional[float]:
        vals = [t[key] for t in tank_stats if t.get(key) is not None]
        return round(sum(vals), 2) if vals else None

    out: dict = {
        "today_consumed_gallons": _sum("today_consumed_gallons"),
        "week_consumed_gallons": _sum("week_consumed_gallons"),
        "avg_daily_gallons_30d": _sum("avg_daily_gallons_30d"),
        "tanks": tank_stats,
    }
    if not is_supplier:
        out["today_profit_dollars"] = _sum("today_profit_dollars")
        out["total_margin_7d"] = _sum("total_margin_7d")
    return out
