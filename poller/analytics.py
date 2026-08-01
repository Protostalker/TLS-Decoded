"""
Analytics: consumption rates, delivery detection, predictions.

All calculations are performed against historical readings stored in the DB.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from config import AnalyticsConfig, TankConfig
from models import DeliveryEvent, TankReading

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Consumption rate ──────────────────────────────────────────────────────────

def compute_consumption_rate(
    engine: Engine,
    tank_id: int,
    window_hours: int,
) -> Optional[float]:
    """
    Rolling average consumption in gallons/hour over the last window_hours.
    Returns None if fewer than 2 readings exist in the window.
    """
    sql = text(
        """
        SELECT polled_at, volume_gallons
        FROM readings
        WHERE tank_id = :tank_id
          AND polled_at >= NOW() - INTERVAL ':hours hours'
          AND volume_gallons IS NOT NULL
        ORDER BY polled_at ASC
        """
    )
    # SQLAlchemy doesn't allow binding interval units via param easily; use format
    sql = text(
        f"""
        SELECT polled_at, volume_gallons
        FROM readings
        WHERE tank_id = :tank_id
          AND polled_at >= NOW() - INTERVAL '{window_hours} hours'
          AND volume_gallons IS NOT NULL
        ORDER BY polled_at ASC
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"tank_id": tank_id}).fetchall()

    if len(rows) < 2:
        return None

    # Use only "normal" periods: filter out deliveries (volume increases)
    segments: list[tuple[float, float]] = []  # (delta_vol, delta_hours)
    for i in range(1, len(rows)):
        prev_time, prev_vol = rows[i - 1]
        curr_time, curr_vol = rows[i]
        delta_vol = prev_vol - curr_vol  # positive = consumption
        delta_secs = (curr_time - prev_time).total_seconds()
        delta_hours = delta_secs / 3600.0
        if delta_hours <= 0:
            continue
        if delta_vol < 0:
            # Volume increased — skip (delivery or noise)
            continue
        segments.append((delta_vol, delta_hours))

    if not segments:
        return None

    total_consumed = sum(d for d, _ in segments)
    total_hours = sum(h for _, h in segments)
    if total_hours == 0:
        return None

    return total_consumed / total_hours


# ── Delivery detection ────────────────────────────────────────────────────────

def detect_delivery(
    prev_reading: Optional[TankReading],
    curr_reading: TankReading,
    jump_gallons: float,
) -> Optional[DeliveryEvent]:
    """Return a DeliveryEvent if volume jumped by more than jump_gallons."""
    if prev_reading is None:
        return None
    delta = curr_reading.volume_gallons - prev_reading.volume_gallons
    if delta >= jump_gallons:
        logger.info(
            "Delivery detected on tank %d: +%.0f gal (%.0f → %.0f)",
            curr_reading.tank_id,
            delta,
            prev_reading.volume_gallons,
            curr_reading.volume_gallons,
        )
        return DeliveryEvent(
            tank_id=curr_reading.tank_id,
            detected_at=curr_reading.polled_at,
            start_volume_gallons=prev_reading.volume_gallons,
            end_volume_gallons=curr_reading.volume_gallons,
            gallons_received=delta,
        )
    return None


# ── Confidence ────────────────────────────────────────────────────────────────

def _data_age_hours(engine: Engine, tank_id: int) -> float:
    """Hours of reading history available for this tank."""
    sql = text(
        """
        SELECT EXTRACT(EPOCH FROM (MAX(polled_at) - MIN(polled_at))) / 3600.0
        FROM readings
        WHERE tank_id = :tank_id
        """
    )
    with engine.connect() as conn:
        result = conn.execute(sql, {"tank_id": tank_id}).scalar()
    return float(result) if result else 0.0


def confidence_label(data_hours: float) -> str:
    if data_hours < 48:
        return "low"
    if data_hours < 168:
        return "medium"
    return "high"


# ── Full prediction ───────────────────────────────────────────────────────────

def build_prediction(
    engine: Engine,
    tank_cfg: TankConfig,
    current_volume: float,
    analytics_cfg: AnalyticsConfig,
) -> dict:
    """
    Returns a dict with all prediction fields for the /prediction endpoint.
    """
    rate = compute_consumption_rate(engine, tank_cfg.id, analytics_cfg.consumption_window_hours)
    data_hours = _data_age_hours(engine, tank_cfg.id)
    conf = confidence_label(data_hours)

    now = _utcnow()

    if rate is None or rate <= 0:
        return {
            "tank_id": tank_cfg.id,
            "consumption_rate_gal_per_hour": None,
            "consumption_rate_gal_per_day": None,
            "days_until_reorder": None,
            "days_until_empty": None,
            "projected_reorder_date": None,
            "confidence": "low",
            "note": "Insufficient data for rate calculation",
        }

    rate_per_day = rate * 24.0
    reorder_threshold = tank_cfg.reorder_threshold_gallons

    days_until_reorder = None
    projected_reorder_date = None
    if current_volume > reorder_threshold:
        days_until_reorder = (current_volume - reorder_threshold) / rate_per_day
        from datetime import timedelta
        projected_reorder_date = (now + timedelta(days=days_until_reorder)).isoformat()

    days_until_empty = current_volume / rate_per_day if rate_per_day > 0 else None

    return {
        "tank_id": tank_cfg.id,
        "consumption_rate_gal_per_hour": round(rate, 4),
        "consumption_rate_gal_per_day": round(rate_per_day, 2),
        "days_until_reorder": round(days_until_reorder, 2) if days_until_reorder is not None else None,
        "days_until_empty": round(days_until_empty, 2) if days_until_empty is not None else None,
        "projected_reorder_date": projected_reorder_date,
        "confidence": conf,
    }
