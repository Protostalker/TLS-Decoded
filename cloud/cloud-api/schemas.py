"""Pydantic schemas for the cloud API (Ingest + T1/T2/T3 app API)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr


# ── Ingest (station -> cloud) ────────────────────────────────────────────────

class IngestTank(BaseModel):
    local_id: int
    name: str
    product: Optional[str] = None
    capacity_gallons: Optional[float] = None
    reorder_threshold_gallons: Optional[float] = None
    active: bool = True
    updated_at: Optional[datetime] = None


class IngestReading(BaseModel):
    local_id: int
    tank_local_id: int
    polled_at: datetime
    volume_gallons: Optional[float] = None
    ullage_gallons: Optional[float] = None
    height_inches: Optional[float] = None
    water_inches: Optional[float] = None
    temperature_f: Optional[float] = None


class IngestDeliveryEvent(BaseModel):
    local_id: int
    tank_local_id: int
    detected_at: datetime
    start_volume_gallons: Optional[float] = None
    end_volume_gallons: Optional[float] = None
    gallons_received: Optional[float] = None
    adjusted_gallons_received: Optional[float] = None
    confirmed: Optional[bool] = None
    manual_gallons_received: Optional[float] = None
    manually_confirmed_at: Optional[datetime] = None
    merged_poll_count: Optional[int] = None
    session_started_at: Optional[datetime] = None
    note: Optional[str] = None
    updated_at: Optional[datetime] = None


class IngestFuelPrice(BaseModel):
    local_id: int
    tank_local_id: int
    effective_at: datetime
    cost_per_gallon: Optional[float] = None
    tax_fees_per_gallon: Optional[float] = None
    tax_rate_percent: Optional[float] = None
    sale_price_per_gallon: Optional[float] = None
    source: Optional[str] = "manual"
    note: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class IngestPollLog(BaseModel):
    local_id: int
    polled_at: datetime
    success: Optional[bool] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None


class IngestBatch(BaseModel):
    tanks: list[IngestTank] = []
    readings: list[IngestReading] = []
    delivery_events: list[IngestDeliveryEvent] = []
    fuel_prices: list[IngestFuelPrice] = []
    poll_log: list[IngestPollLog] = []


class IngestResult(BaseModel):
    received: dict[str, int]
    synced_at: datetime


# ── Auth (T2) ─────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    duration: str = "short"  # "short" | "90d" | "never"


class LoginResponse(BaseModel):
    token: str
    user: "MeOut"


class MeOut(BaseModel):
    id: int
    email: str
    role: str
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None


class SessionOut(BaseModel):
    id: int
    created_at: datetime
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    is_current: bool = False


# ── Stations (T2 picker, T3 admin) ───────────────────────────────────────────

class StationOut(BaseModel):
    id: int
    name: str
    customer_id: int
    customer_name: Optional[str] = None
    sync_interval_minutes: int
    last_sync_at: Optional[datetime] = None
    active: bool
    zip_code: Optional[str] = None


class StationCreate(BaseModel):
    customer_id: int
    name: str
    sync_interval_minutes: int = 30
    zip_code: Optional[str] = None


class StationUpdate(BaseModel):
    name: Optional[str] = None
    sync_interval_minutes: Optional[int] = None
    active: Optional[bool] = None
    zip_code: Optional[str] = None


class StationCredentialOut(BaseModel):
    """Only ever returned once — at provisioning or explicit rotation."""
    station_id: int
    device_id: str
    device_secret: str


# ── T3 admin: customers/users/assignments ────────────────────────────────────

class CustomerOut(BaseModel):
    id: int
    name: str
    plan: Optional[str] = None
    created_at: datetime
    station_count: int = 0
    user_count: int = 0


class CustomerCreate(BaseModel):
    name: str
    plan: Optional[str] = None


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    active: bool
    created_at: datetime
    assigned_station_ids: list[int] = []


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: str = "user"
    customer_id: Optional[int] = None


class UserUpdate(BaseModel):
    role: Optional[str] = None
    active: Optional[bool] = None
    customer_id: Optional[int] = None
    password: Optional[str] = None


class AssignmentCreate(BaseModel):
    user_id: int
    station_id: int


# ── T1 (station-scoped, mirrors local api/schemas.py) ────────────────────────

class ReadingOut(BaseModel):
    tank_local_id: int
    polled_at: datetime
    volume_gallons: Optional[float]
    ullage_gallons: Optional[float]
    height_inches: Optional[float]
    water_inches: Optional[float]
    temperature_f: Optional[float]


class TankOut(BaseModel):
    local_id: int
    name: str
    product: Optional[str]
    capacity_gallons: Optional[float]
    reorder_threshold_gallons: Optional[float]
    active: bool
    latest_reading: Optional[ReadingOut] = None


class PredictionOut(BaseModel):
    tank_local_id: int
    consumption_rate_gal_per_hour: Optional[float]
    consumption_rate_gal_per_day: Optional[float]
    days_until_reorder: Optional[float]
    days_until_empty: Optional[float]
    projected_reorder_date: Optional[str]
    confidence: str
    note: Optional[str] = None


class StationDashboardOut(BaseModel):
    station_id: int
    station_name: str
    tanks: list[TankOut]
    predictions: list[PredictionOut]
    last_poll_at: Optional[datetime] = None   # station's own local poll (freshness of the reading itself)
    last_poll_success: Optional[bool] = None
    last_poll_error: Optional[str] = None
    last_sync_at: Optional[datetime] = None   # cloud sync freshness — separate signal, see design doc
