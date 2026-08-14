"""
License status surface for the Cloud Utility's own UI. Two endpoints, two
different audiences per the dev handoff doc's open-question answer:

  - /api/license/banner — any authenticated user. Just enough to render the
    "your license needs attention" banner explaining WHY they might be
    seeing limited data, without exposing full license details to non-admins.
  - /api/license/status — admin only. Full detail for the admin-only License
    page: when it was applied, when it expires, whether currently in grace.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
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
