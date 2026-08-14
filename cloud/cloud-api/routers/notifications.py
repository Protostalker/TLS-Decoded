"""
In-app notifications — delivered to admin/user-role recipients when a
supplier marks fuel as ordered for one of their stations (and in the future,
for other event types like low-tank alarms or delivery confirmations).

The bell icon in the frontend polls this endpoint every 30 s; unread count
drives the badge; clicking a notification row marks it read and (if it has a
station_id) navigates to that station's dashboard.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user, require_not_degraded
from database import get_db
from models import Notification, User

router = APIRouter(dependencies=[Depends(require_not_degraded)])


@router.get("/notifications")
def list_notifications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Most-recent 50 notifications for the current user (read + unread)."""
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    return [_out(n) for n in rows]


@router.post("/notifications/{notification_id}/read")
def mark_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user.id,
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not n.read_at:
        n.read_at = datetime.now(tz=timezone.utc)
        db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(tz=timezone.utc)
    db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.read_at.is_(None),
    ).update({"read_at": now})
    db.commit()
    return {"ok": True}


def _out(n: Notification) -> dict:
    return {
        "id": n.id,
        "station_id": n.station_id,
        "type": n.type,
        "message": n.message,
        "eta_note": n.eta_note,
        "created_at": n.created_at,
        "read_at": n.read_at,
    }
