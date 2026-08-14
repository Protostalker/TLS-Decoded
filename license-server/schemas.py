"""Pydantic schemas for the license server."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ── Phone-home (Cloud Utility -> license server) ─────────────────────────────

class LicenseCheckRequest(BaseModel):
    passphrase: str
    instance_id: str  # random token the Cloud Utility generates once and persists


class LicenseCheckResponse(BaseModel):
    status: str  # "valid" | "invalid"
    customer_name: Optional[str] = None
    station_scope: Optional[str] = None
    expires_at: Optional[datetime] = None
    detail: Optional[str] = None


# ── Admin ─────────────────────────────────────────────────────────────────────

class LicenseCreate(BaseModel):
    passphrase: str          # you choose the text — this isn't self-serve
    customer_name: str
    station_scope: Optional[str] = None
    max_uses: Optional[int] = 1     # None = unlimited
    valid_days: Optional[int] = 365  # None = never expires


class LicenseOut(BaseModel):
    id: int
    passphrase: str
    customer_name: str
    station_scope: Optional[str] = None
    max_uses: Optional[int] = None
    use_count: int
    status: str
    is_master: bool
    issued_at: datetime
    expires_at: Optional[datetime] = None
    first_redeemed_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None


class LicenseRenew(BaseModel):
    extend_days: int = 365


class LicenseStatusUpdate(BaseModel):
    status: str  # "active" | "suspended"
