"""
The phone-home endpoint — no admin token needed, a Cloud Utility with a
valid passphrase must be able to check in even if the admin tooling's
credentials rotate independently.

Redemption logic (see models.py's module docstring for why this is two
tables, not one):

  1. Look up the passphrase. Unknown / suspended / past its expires_at ->
     invalid.
  2. Does a LicenseRedemption already exist for (this license, this
     instance_id)? -> this is a routine re-check from an already-activated
     instance. Touch last_checked_at, return valid. Doesn't consume a use.
  3. Otherwise, this instance is trying to activate for the first time.
     If max_uses is NULL (unlimited/master) or the current redemption count
     is still below max_uses -> create the redemption (consumes one use),
     return valid. Otherwise -> invalid, "this code has already been used
     its maximum number of times."
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from models import License, LicenseRedemption
from schemas import LicenseCheckRequest, LicenseCheckResponse

router = APIRouter(prefix="/license", tags=["license"])


@router.post("/check", response_model=LicenseCheckResponse)
def check_license(body: LicenseCheckRequest, request: Request, db: Session = Depends(get_db)):
    lic = db.query(License).filter(License.passphrase == body.passphrase).first()
    now = datetime.now(tz=timezone.utc)
    ip = request.client.host if request.client else None

    if not lic:
        return LicenseCheckResponse(status="invalid", detail="Unknown passphrase")

    if lic.status == "suspended":
        return LicenseCheckResponse(
            status="invalid", customer_name=lic.customer_name, station_scope=lic.station_scope,
            expires_at=lic.expires_at, detail="This license has been suspended",
        )

    expires_at = lic.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            return LicenseCheckResponse(
                status="invalid", customer_name=lic.customer_name, station_scope=lic.station_scope,
                expires_at=lic.expires_at, detail="This license has expired — renew to restore access",
            )

    existing = (
        db.query(LicenseRedemption)
        .filter(LicenseRedemption.license_id == lic.id, LicenseRedemption.instance_id == body.instance_id)
        .first()
    )
    if existing:
        existing.last_checked_at = now
        existing.last_checked_ip = ip
        db.commit()
        return LicenseCheckResponse(
            status="valid", customer_name=lic.customer_name, station_scope=lic.station_scope, expires_at=lic.expires_at,
        )

    # First check-in from this instance_id — this is an activation attempt.
    if lic.max_uses is not None:
        use_count = db.query(LicenseRedemption).filter(LicenseRedemption.license_id == lic.id).count()
        if use_count >= lic.max_uses:
            return LicenseCheckResponse(
                status="invalid", customer_name=lic.customer_name, station_scope=lic.station_scope,
                expires_at=lic.expires_at,
                detail=f"This license has already been used its maximum number of times ({lic.max_uses}).",
            )

    db.add(LicenseRedemption(
        license_id=lic.id, instance_id=body.instance_id,
        redeemed_at=now, last_checked_at=now, last_checked_ip=ip,
    ))
    db.commit()
    return LicenseCheckResponse(
        status="valid", customer_name=lic.customer_name, station_scope=lic.station_scope, expires_at=lic.expires_at,
    )
