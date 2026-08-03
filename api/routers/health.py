"""Health check + poll log (recent poll attempts, for hardware diagnostics)."""
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from models import PollLog
from schemas import HealthOut, PollLogOut

router = APIRouter()


@router.get("/poll-log", response_model=list[PollLogOut])
def poll_log(limit: int = Query(20, le=200), db: Session = Depends(get_db)):
    """Recent poll attempts with success/failure and the actual error text —
    e.g. distinguishing 'adapter unreachable' from 'connected fine but the
    gauge sent nothing back' (a serial wiring issue) from 'got bytes but
    couldn't parse them' (baud/parity mismatch)."""
    rows = (
        db.query(PollLog)
        .order_by(PollLog.polled_at.desc())
        .limit(limit)
        .all()
    )
    return [PollLogOut.model_validate(r) for r in rows]


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
