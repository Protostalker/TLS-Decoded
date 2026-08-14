"""Pydantic schemas for the license server."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ── Phone-home (Cloud Utility -> license server) ─────────────────────────────

class LicenseCheckRequest(BaseModel):
    license_key: str


class LicenseCheckResponse(BaseModel):
    status: str  # "valid" | "invalid" | "grace"
    customer_name: Optional[str] = None
    station_scope: Optional[str] = None
    expires_at: Optional[datetime] = None
    renewed_at: Optional[datetime] = None
    detail: Optional[str] = None


# ── Admin: Annual licenses ───────────────────────────────────────────────────

class AnnualLicenseCreate(BaseModel):
    customer_name: str
    station_scope: Optional[str] = None
    valid_days: int = 365


class AnnualLicenseOut(BaseModel):
    id: int
    key_hint: str
    customer_name: str
    station_scope: Optional[str] = None
    status: str
    issued_at: datetime
    expires_at: datetime
    renewed_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None


class AnnualLicenseIssuedOut(AnnualLicenseOut):
    """Only ever returned once — at issuance — same posture as station device
    credentials in the main app (StationCredentialOut)."""
    license_key: str


class AnnualLicenseRenew(BaseModel):
    extend_days: int = 365


class AnnualLicenseStatusUpdate(BaseModel):
    status: str  # "active" | "suspended"


# ── Admin: Unlimited licenses ─────────────────────────────────────────────────

class UnlimitedLicenseCreate(BaseModel):
    customer_name: str
    station_scope: Optional[str] = None


class UnlimitedLicenseOut(BaseModel):
    id: int
    jti: str
    customer_name: str
    station_scope: Optional[str] = None
    issued_at: datetime
    revoked: bool


class UnlimitedLicenseIssuedOut(UnlimitedLicenseOut):
    license_file: str  # the signed JWT — deliver this to the customer; never stored server-side
