"""Pydantic schemas — fields match what TLS-350 display format actually provides."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tank_id: int
    polled_at: datetime
    volume_gallons: Optional[float]
    ullage_gallons: Optional[float]
    height_inches: Optional[float]
    water_inches: Optional[float]
    temperature_f: Optional[float]


class TankOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    product: Optional[str]
    capacity_gallons: Optional[float]
    reorder_threshold_gallons: Optional[float]
    active: bool
    latest_reading: Optional[ReadingOut] = None


class DeliveryEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tank_id: int
    detected_at: datetime
    start_volume_gallons: Optional[float]
    end_volume_gallons: Optional[float]
    gallons_received: Optional[float]
    adjusted_gallons_received: Optional[float] = None
    confirmed: Optional[bool] = None
    manual_gallons_received: Optional[float] = None
    manually_confirmed_at: Optional[datetime] = None
    merged_poll_count: Optional[int] = None
    session_started_at: Optional[datetime] = None
    note: Optional[str] = None
    # Convenience field: the number the UI should treat as authoritative —
    # an operator's manual figure if set, else the concurrent-sales-adjusted
    # estimate, else the raw net change.
    effective_gallons_received: Optional[float] = None


class DeliveryConfirm(BaseModel):
    gallons_received: float
    note: Optional[str] = None


class DeliveryManualCreate(BaseModel):
    gallons_received: float
    detected_at: Optional[datetime] = None
    note: Optional[str] = None


class PredictionOut(BaseModel):
    tank_id: int
    consumption_rate_gal_per_hour: Optional[float]
    consumption_rate_gal_per_day: Optional[float]
    days_until_reorder: Optional[float]
    days_until_empty: Optional[float]
    projected_reorder_date: Optional[str]
    confidence: str
    note: Optional[str] = None


class ConsumptionIntervalOut(BaseModel):
    from_time: datetime
    to_time: datetime
    hours: float
    delta_gallons: float          # positive = consumed, negative = volume increased (delivery/noise)
    rate_gal_per_hour: Optional[float]
    is_increase: bool


class TankStatsOut(BaseModel):
    tank_id: int
    today_consumed_gallons: Optional[float]
    week_consumed_gallons: Optional[float]
    avg_daily_gallons_30d: Optional[float]
    days_since_last_delivery: Optional[float]
    last_delivery_gallons: Optional[float]
    temp_min_7d: Optional[float]
    temp_max_7d: Optional[float]
    water_inches_latest: Optional[float]
    water_alert: bool
    turnover_days_estimate: Optional[float]


class TankUpdate(BaseModel):
    name: Optional[str] = None
    product: Optional[str] = None
    capacity_gallons: Optional[float] = None
    reorder_threshold_gallons: Optional[float] = None


class SettingsOut(BaseModel):
    poll_interval_minutes: int
    poll_aligned: bool
    available_intervals: list[int]
    device_id: str
    remote_enabled: bool
    remote_server_url: str
    poll_now_pending: bool


class SettingsUpdate(BaseModel):
    poll_interval_minutes: Optional[int] = None
    poll_aligned: Optional[bool] = None
    remote_enabled: Optional[bool] = None
    remote_server_url: Optional[str] = None
    device_id: Optional[str] = None


class DeviceIdOut(BaseModel):
    device_id: str


class HealthOut(BaseModel):
    status: str
    db_ok: bool
    poller_last_seen: Optional[datetime]


class DashboardOut(BaseModel):
    station_name: str
    tanks: list[TankOut]
    predictions: list[PredictionOut]
    last_poll_at: Optional[datetime]
