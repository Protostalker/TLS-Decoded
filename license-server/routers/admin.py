"""
Internal admin tooling — not customer-facing (per the dev handoff doc:
"this can be a manual/internal tool, doesn't need to be customer-facing").
Every route here requires X-Admin-Token (see auth.py).

You choose the passphrase text yourself when creating a license — there's
no auto-generation, since this is a hand-issued codes system, not a
self-serve one. There's no UI for this on purpose — hit it with
curl/httpie/Postman.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import require_admin_token
from database import get_db
from models import License, LicenseRedemption
from schemas import LicenseCreate, LicenseOut, LicenseRenew, LicenseStatusUpdate

router = APIRouter(dependencies=[Depends(require_admin_token)])


def _license_out(db: Session, lic: License) -> LicenseOut:
    redemptions = db.query(LicenseRedemption).filter(LicenseRedemption.license_id == lic.id).all()
    first_redeemed = min((r.redeemed_at for r in redemptions), default=None)
    last_checked = max((r.last_checked_at for r in redemptions if r.last_checked_at), default=None)
    return LicenseOut(
        id=lic.id, passphrase=lic.passphrase, customer_name=lic.customer_name, station_scope=lic.station_scope,
        max_uses=lic.max_uses, use_count=len(redemptions), status=lic.status, is_master=lic.is_master,
        issued_at=lic.issued_at, expires_at=lic.expires_at,
        first_redeemed_at=first_redeemed, last_checked_at=last_checked,
    )


@router.get("/licenses", response_model=list[LicenseOut])
def list_licenses(db: Session = Depends(get_db)):
    licenses = db.query(License).order_by(License.issued_at.desc()).all()
    return [_license_out(db, lic) for lic in licenses]


@router.post("/licenses", response_model=LicenseOut)
def create_license(body: LicenseCreate, db: Session = Depends(get_db)):
    passphrase = body.passphrase.strip()
    if not passphrase:
        raise HTTPException(status_code=400, detail="passphrase is required")
    if db.query(License).filter(License.passphrase == passphrase).first():
        raise HTTPException(status_code=409, detail="A license with this passphrase already exists")
    if body.max_uses is not None and body.max_uses < 1:
        raise HTTPException(status_code=400, detail="max_uses must be >= 1, or omitted for unlimited")

    now = datetime.now(tz=timezone.utc)
    lic = License(
        passphrase=passphrase, customer_name=body.customer_name, station_scope=body.station_scope,
        max_uses=body.max_uses, status="active", issued_at=now,
        expires_at=(now + timedelta(days=body.valid_days)) if body.valid_days else None,
        is_master=False,
    )
    db.add(lic)
    db.commit()
    db.refresh(lic)
    return _license_out(db, lic)


@router.post("/licenses/{license_id}/renew", response_model=LicenseOut)
def renew_license(license_id: int, body: LicenseRenew, db: Session = Depends(get_db)):
    """Extends from the CURRENT expiry if still in the future, otherwise
    from now — a lapsed code that gets renewed doesn't skip the days it
    was lapsed, but renewing early doesn't lose days either."""
    lic = db.query(License).filter(License.id == license_id).first()
    if not lic:
        raise HTTPException(status_code=404, detail="License not found")
    now = datetime.now(tz=timezone.utc)
    expires_at = lic.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    base = expires_at if (expires_at and expires_at > now) else now
    lic.expires_at = base + timedelta(days=body.extend_days)
    lic.status = "active"
    db.commit()
    db.refresh(lic)
    return _license_out(db, lic)


@router.post("/licenses/{license_id}/status", response_model=LicenseOut)
def set_license_status(license_id: int, body: LicenseStatusUpdate, db: Session = Depends(get_db)):
    if body.status not in ("active", "suspended"):
        raise HTTPException(status_code=400, detail="status must be 'active' or 'suspended'")
    lic = db.query(License).filter(License.id == license_id).first()
    if not lic:
        raise HTTPException(status_code=404, detail="License not found")
    lic.status = body.status
    db.commit()
    db.refresh(lic)
    return _license_out(db, lic)


@router.delete("/licenses/{license_id}/redemptions/{instance_id}")
def revoke_redemption(license_id: int, instance_id: str, db: Session = Depends(get_db)):
    """Free up one 'use' — e.g. an instance was decommissioned and you want
    to let a different one activate with the same code. Doesn't affect
    that instance's own copy of the passphrase; it'll just fail its next
    check (and the Cloud Utility will need a different code to reactivate)."""
    row = db.query(LicenseRedemption).filter(
        LicenseRedemption.license_id == license_id, LicenseRedemption.instance_id == instance_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Redemption not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
