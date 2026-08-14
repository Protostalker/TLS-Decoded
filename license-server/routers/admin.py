"""
Internal admin tooling — not customer-facing (per the dev handoff doc:
"this can be a manual/internal tool, doesn't need to be customer-facing").
Every route here requires X-Admin-Token; the two Unlimited-issuance routes
additionally require X-Unlimited-Passphrase (see auth.py).

There's no UI for this on purpose — hit it with curl/httpie/Postman, or
build an internal script around it later if issuance volume ever justifies
one. Keeping this a thin API-only surface is what "doesn't need to be
fancy" (per the doc) means in practice.
"""
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import keys
from auth import hash_key, require_admin_token, require_unlimited_passphrase
from database import get_db
from models import AnnualLicense, UnlimitedLicense
from schemas import (
    AnnualLicenseCreate, AnnualLicenseIssuedOut, AnnualLicenseOut, AnnualLicenseRenew,
    AnnualLicenseStatusUpdate, UnlimitedLicenseCreate, UnlimitedLicenseIssuedOut, UnlimitedLicenseOut,
)

router = APIRouter(dependencies=[Depends(require_admin_token)])


def gen_license_key() -> str:
    return "tlsfp-" + secrets.token_urlsafe(24)


def _annual_out(lic: AnnualLicense) -> AnnualLicenseOut:
    return AnnualLicenseOut(
        id=lic.id, key_hint=lic.key_hint, customer_name=lic.customer_name, station_scope=lic.station_scope,
        status=lic.status, issued_at=lic.issued_at, expires_at=lic.expires_at,
        renewed_at=lic.renewed_at, last_checked_at=lic.last_checked_at,
    )


# ── Annual licenses ───────────────────────────────────────────────────────────

@router.get("/licenses/annual", response_model=list[AnnualLicenseOut])
def list_annual(db: Session = Depends(get_db)):
    return [_annual_out(lic) for lic in db.query(AnnualLicense).order_by(AnnualLicense.issued_at.desc()).all()]


@router.post("/licenses/annual", response_model=AnnualLicenseIssuedOut)
def create_annual(body: AnnualLicenseCreate, db: Session = Depends(get_db)):
    """Returns the raw license key — the ONLY time it's ever shown. Deliver
    it to the customer for entry into their Cloud Utility's license
    settings; only its hash is stored here from this point on."""
    raw_key = gen_license_key()
    now = datetime.now(tz=timezone.utc)
    lic = AnnualLicense(
        key_hash=hash_key(raw_key), key_hint=raw_key[-4:],
        customer_name=body.customer_name, station_scope=body.station_scope,
        status="active", issued_at=now, expires_at=now + timedelta(days=body.valid_days),
    )
    db.add(lic)
    db.commit()
    db.refresh(lic)
    return AnnualLicenseIssuedOut(**_annual_out(lic).model_dump(), license_key=raw_key)


@router.post("/licenses/annual/{license_id}/renew", response_model=AnnualLicenseOut)
def renew_annual(license_id: int, body: AnnualLicenseRenew, db: Session = Depends(get_db)):
    """Extends from the CURRENT expiry if still in the future, otherwise
    from now — a lapsed customer who pays up doesn't get to skip the days
    they were lapsed, but a customer renewing early doesn't lose days either."""
    lic = db.query(AnnualLicense).filter(AnnualLicense.id == license_id).first()
    if not lic:
        raise HTTPException(status_code=404, detail="License not found")
    now = datetime.now(tz=timezone.utc)
    expires_at = lic.expires_at if lic.expires_at.tzinfo else lic.expires_at.replace(tzinfo=timezone.utc)
    base = expires_at if expires_at > now else now
    lic.expires_at = base + timedelta(days=body.extend_days)
    lic.renewed_at = now
    lic.status = "active"
    db.commit()
    db.refresh(lic)
    return _annual_out(lic)


@router.post("/licenses/annual/{license_id}/status", response_model=AnnualLicenseOut)
def set_annual_status(license_id: int, body: AnnualLicenseStatusUpdate, db: Session = Depends(get_db)):
    if body.status not in ("active", "suspended"):
        raise HTTPException(status_code=400, detail="status must be 'active' or 'suspended'")
    lic = db.query(AnnualLicense).filter(AnnualLicense.id == license_id).first()
    if not lic:
        raise HTTPException(status_code=404, detail="License not found")
    lic.status = body.status
    db.commit()
    db.refresh(lic)
    return _annual_out(lic)


# ── Unlimited licenses ────────────────────────────────────────────────────────

@router.get("/licenses/unlimited", response_model=list[UnlimitedLicenseOut])
def list_unlimited(db: Session = Depends(get_db)):
    rows = db.query(UnlimitedLicense).order_by(UnlimitedLicense.issued_at.desc()).all()
    return [
        UnlimitedLicenseOut(
            id=r.id, jti=r.jti, customer_name=r.customer_name, station_scope=r.station_scope,
            issued_at=r.issued_at, revoked=r.revoked,
        )
        for r in rows
    ]


@router.post(
    "/licenses/unlimited",
    response_model=UnlimitedLicenseIssuedOut,
    dependencies=[Depends(require_unlimited_passphrase)],
)
def create_unlimited(body: UnlimitedLicenseCreate, db: Session = Depends(get_db)):
    """
    Generates a signed, no-expiry license file (JWT, RS256) and returns it.
    This is the ONLY output — the license server never validates this file
    again after today; every future check happens entirely offline inside
    the customer's Cloud Utility (see cloud/cloud-api/licensing.py's
    verify_unlimited). Requires X-Unlimited-Passphrase per Raffi's answer
    in the dev handoff doc's open questions — this is deliberately a
    slightly heavier-weight action than issuing an Annual key.
    """
    now = datetime.now(tz=timezone.utc)
    jti = secrets.token_hex(16)
    claims = {
        "license_type": "unlimited",
        "sub": body.customer_name,
        "station_scope": body.station_scope,
        "iat": int(now.timestamp()),
        "jti": jti,
        # Deliberately no "exp" claim — see main.py's module docstring and
        # README.md: no expiry, no phone-home, ever, by design.
    }
    token = jwt.encode(claims, keys.private_key(), algorithm="RS256")

    row = UnlimitedLicense(
        jti=jti, customer_name=body.customer_name, station_scope=body.station_scope,
        issued_at=now, revoked=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return UnlimitedLicenseIssuedOut(
        id=row.id, jti=row.jti, customer_name=row.customer_name, station_scope=row.station_scope,
        issued_at=row.issued_at, revoked=row.revoked, license_file=token,
    )
