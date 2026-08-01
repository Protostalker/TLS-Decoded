"""Health check endpoint."""
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from schemas import HealthOut

router = APIRouter()


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)):
    # Check DB
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    # Last poller heartbeat: most recent poll_log entry
    poller_last_seen: Optional[datetime] = None
    try:
        result = db.execute(
            text("SELECT polled_at FROM poll_log ORDER BY polled_at DESC LIMIT 1")
        ).scalar()
        if result:
            poller_last_seen = result
    except Exception:
        pass

    status = "ok" if db_ok else "degraded"
    return HealthOut(status=status, db_ok=db_ok, poller_last_seen=poller_last_seen)
