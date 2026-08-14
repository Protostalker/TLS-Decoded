"""
License status + activation surface for the Cloud Utility's own UI.

  - /api/license/banner — any authenticated user. Just enough to render the
    "your license needs attention" banner explaining WHY they might be
    seeing limited data, without exposing full license details to non-admins.
  - /api/license/status — admin only. Full detail for the admin-only License
    page: when it was applied, when it expires, whether currently in grace.
  - /api/license/config, /activate/annual, /activate/unlimited, /deactivate —
    admin only. Submit or clear the actual license credential from the UI —
    env vars (CLOUD_LICENSE_TYPE/KEY/FILE) only ever seed this once, on a
    brand new deployment; every change after that goes through here. See
    licensing.py's module docstring.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import licensing
from auth import get_current_user, require_admin
from database import get_db
from models import User

router = APIRouter()


@router.get("/license/banner")
def license_banner(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    state = licensing.get_state_dict(db)
    degraded = state["status"] == "degraded"
    in_grace = state["status"] == "grace"
    message = None
    if degraded:
        message = (
            "This Cloud Utility's license needs attention. "
            + ("Only admins can currently view data — contact your admin, or renew to restore full access."
               if user.role != "admin" else
               "Renew your license to restore full functionality. See Admin -> License.")
        )
    elif in_grace and user.role == "admin":
        remaining = state.get("grace_days_remaining")
        message = (
            f"License check failing — {remaining} day(s) left before the account enters degraded mode. "
            "See Admin -> License to renew."
        )
    return {"degraded": degraded, "grace": in_grace, "message": message}


@router.get("/license/status")
def license_status(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return licensing.get_state_dict(db)


@router.post("/license/recheck")
def license_recheck(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Force an immediate check — e.g. right after renewing, so the admin
    doesn't have to wait up to LICENSE_CHECK_INTERVAL_HOURS to see it clear."""
    licensing.run_license_check()
    return licensing.get_state_dict(db)


# ── Activation — submit a license from the UI instead of editing env vars.
#    Env vars only seed the very first boot; everything after that goes
#    through here. See licensing.py's module docstring. ────────────────────

@router.get("/license/config")
def license_config(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return licensing.get_config_dict(db)


class ActivateAnnualRequest(BaseModel):
    license_key: str


class ActivateUnlimitedRequest(BaseModel):
    license_file: str


@router.post("/license/activate/annual")
def activate_annual(body: ActivateAnnualRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return licensing.activate_annual(db, body.license_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/license/activate/unlimited")
def activate_unlimited(body: ActivateUnlimitedRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return licensing.activate_unlimited(db, body.license_file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/license/deactivate")
def deactivate_license(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Clears the configured license entirely (back to 'unconfigured') — for
    switching license types or decommissioning, not part of the normal
    renewal flow."""
    return licensing.deactivate(db)
