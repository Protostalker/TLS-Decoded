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
    commander_grade_id: Optional[int] = None
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
    # Optional[int] with no default sentinel: whether this was actually sent
    # (vs. just defaulted) is checked via model_fields_set in the router, so
    # sending commander_grade_id: null explicitly clears it (disconnects the
    # tank from Commander sync) instead of being indistinguishable from "not
    # provided" the way the other fields above are.
    commander_grade_id: Optional[int] = None


class FuelPriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tank_id: int
    effective_at: datetime
    cost_per_gallon: float
    tax_rate_percent: Optional[float] = None
    tax_fees_per_gallon: float  # dollar amount — derived from tax_rate_percent when a rate is set
    sale_price_per_gallon: float
    source: str
    note: Optional[str] = None
    # Computed, not stored:
    breakeven_per_gallon: float
    margin_per_gallon: float
    margin_percent: Optional[float] = None


class FuelPriceCreate(BaseModel):
    # Both optional and independently "sticky": omit either one and it
    # carries forward from the tank's most recent price entry instead of
    # being required every time. This is what lets a manual update just be
    # "here's the new cost" without re-typing the sale price, and what lets
    # the Commander price sync post just "here's the new sale price" without
    # knowing the wholesale cost (it never can — Commander only knows what's
    # live at the pump). At least one of the two must be given (or a prior
    # row must exist) or there's nothing to compute a price from.
    cost_per_gallon: Optional[float] = None
    sale_price_per_gallon: Optional[float] = None
    # Preferred: a rate like 9.75 for 9.75% — tax_fees_per_gallon is computed
    # automatically as cost_per_gallon * tax_rate_percent / 100. Leave blank
    # to use DEFAULT_TAX_RATE_PERCENT (set once as an env var rather than
    # entered per price change). Set explicitly only for a one-off override.
    tax_rate_percent: Optional[float] = None
    tax_fees_per_gallon: Optional[float] = None
    effective_at: Optional[datetime] = None
    note: Optional[str] = None
    # "manual" (default, from the dashboard) vs "commander_auto" (from the
    # hourly Commander price sync). Not meant to be set from the UI.
    source: Optional[str] = None


class FuelPriceUpdate(BaseModel):
    cost_per_gallon: Optional[float] = None
    tax_rate_percent: Optional[float] = None
    tax_fees_per_gallon: Optional[float] = None
    sale_price_per_gallon: Optional[float] = None
    effective_at: Optional[datetime] = None
    note: Optional[str] = None


class SettingsOut(BaseModel):
    poll_interval_minutes: int
    poll_aligned: bool
    available_intervals: list[int]
    device_id: str
    remote_enabled: bool
    remote_server_url: str
    poll_now_pending: bool
    # Cloud sync (cloud/) — distinct from the legacy remote_* fields above,
    # which belong to the older, still-inactive RemoteUploader stub. These
    # back the real cloud hub built in cloud/ — see CLOUD-ARCHITECTURE.md.
    cloud_sync_enabled: bool
    cloud_sync_url: str
    cloud_sync_device_id: str
    cloud_sync_device_secret: str
    cloud_sync_interval_minutes: int
    cloud_sync_last_synced_at: Optional[datetime] = None
    # Commander price sync — distinct from cloud sync above. Stations that
    # don't run Verifone Commander, or whose operator won't allow the
    # integration, just leave commander_sync_enabled off (or the URL blank)
    # and keep entering both cost and sale price manually — nothing else
    # about the app depends on this being configured.
    commander_sync_enabled: bool
    commander_reader_url: str
    commander_price_tier: str
    commander_sync_interval_minutes: int
    commander_last_check_at: Optional[datetime] = None
    commander_last_connected: Optional[bool] = None
    commander_last_error: Optional[str] = None
    # Branding — see routers/settings.py's _brand_defaults()/validation.
    brand_preset: str
    brand_primary_color: str
    brand_secondary_color: str
    brand_accent_color: str
    brand_logo_data_url: str


class SettingsUpdate(BaseModel):
    poll_interval_minutes: Optional[int] = None
    poll_aligned: Optional[bool] = None
    remote_enabled: Optional[bool] = None
    remote_server_url: Optional[str] = None
    device_id: Optional[str] = None
    cloud_sync_enabled: Optional[bool] = None
    cloud_sync_url: Optional[str] = None
    cloud_sync_device_id: Optional[str] = None
    cloud_sync_device_secret: Optional[str] = None
    cloud_sync_interval_minutes: Optional[int] = None
    commander_sync_enabled: Optional[bool] = None
    commander_reader_url: Optional[str] = None
    commander_price_tier: Optional[str] = None
    commander_sync_interval_minutes: Optional[int] = None
    brand_preset: Optional[str] = None
    brand_primary_color: Optional[str] = None
    brand_secondary_color: Optional[str] = None
    brand_accent_color: Optional[str] = None
    brand_logo_data_url: Optional[str] = None


class DeviceIdOut(BaseModel):
    device_id: str


class CommanderTestOut(BaseModel):
    connected: bool
    checked_at: datetime
    error: Optional[str] = None
    grades_count: Optional[int] = None


class HealthOut(BaseModel):
    status: str
    db_ok: bool
    poller_last_seen: Optional[datetime]


class PollLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    polled_at: datetime
    success: Optional[bool]
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None


class DashboardOut(BaseModel):
    station_name: str
    tanks: list[TankOut]
    predictions: list[PredictionOut]
    last_poll_at: Optional[datetime]
    last_poll_success: Optional[bool] = None
    last_poll_error: Optional[str] = None
