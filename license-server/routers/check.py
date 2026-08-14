"""
Public(ish) surface — the Annual phone-home endpoint, plus the signing
public key so a Cloud Utility operator can fetch it once at setup time
instead of it being pasted around by hand. Nothing here requires the admin
token: a Cloud Utility with a valid key must be able to check in even if
the admin tooling's credentials rotate independently.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

import keys
from auth import hash_key
from database import get_db
from models import AnnualLicense
from schemas import LicenseCheckRequest, LicenseCheckResponse

router = APIRouter(prefix="/license", tags=["license"])


@router.post("/check", response_model=LicenseCheckResponse)
def check_license(body: LicenseCheckRequest, request: Request, db: Session = Depends(get_db)):
    lic = db.query(AnnualLicense).filter(AnnualLicense.key_hash == hash_key(body.license_key)).first()
    now = datetime.now(tz=timezone.utc)

    if not lic:
        return LicenseCheckResponse(status="invalid", detail="Unknown license key")

    lic.last_checked_at = now
    lic.last_checked_ip = request.client.host if request.client else None
    db.commit()

    if lic.status == "suspended":
        return LicenseCheckResponse(
            status="invalid", customer_name=lic.customer_name, station_scope=lic.station_scope,
            expires_at=lic.expires_at, renewed_at=lic.renewed_at, detail="License suspended",
        )

    expires_at = lic.expires_at if lic.expires_at.tzinfo else lic.expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        return LicenseCheckResponse(
            status="invalid", customer_name=lic.customer_name, station_scope=lic.station_scope,
            expires_at=lic.expires_at, renewed_at=lic.renewed_at, detail="License period has ended — renew to restore access",
        )

    return LicenseCheckResponse(
        status="valid", customer_name=lic.customer_name, station_scope=lic.station_scope,
        expires_at=lic.expires_at, renewed_at=lic.renewed_at,
    )


@router.get("/public-key")
def public_key():
    """PEM-encoded RSA public key used to verify Unlimited license files
    (RS256-signed JWTs) — configure this as LICENSE_SIGNING_PUBLIC_KEY on
    every Cloud Utility instance that might activate an Unlimited license."""
    return {"public_key_pem": keys.public_key_pem()}
