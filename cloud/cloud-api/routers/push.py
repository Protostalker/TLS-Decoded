"""
Web Push subscription management.

VAPID keys must be set via environment variables for push to work:
  VAPID_PRIVATE_KEY — EC private key (PEM or base64url raw bytes)
  VAPID_PUBLIC_KEY  — Uncompressed EC public key, base64url-encoded
                      (this is what the browser needs for applicationServerKey)
  VAPID_EMAIL       — contact email sent in vapid_claims (defaults to placeholder)

If the keys are absent, /api/push/vapid-public-key returns {"vapid_public_key": null}
and the frontend silently skips the subscription flow.

Generating VAPID keys (one-time, store in .env):
  pip install pywebpush
  python -c "from pywebpush import Vapid; v=Vapid(); v.generate_keys(); \
             print('PRIV:', v.private_key.private_bytes(...)); \
             print('PUB:',  v.public_key.public_bytes(...))"
  Or use https://vapidkeys.com for a quick pair.
"""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import PushSubscription, User
from schemas import PushSubscribeRequest

router = APIRouter()


@router.get("/push/vapid-public-key")
def vapid_public_key():
    """
    Returns the VAPID public key so the browser can subscribe to push.
    Returns null when VAPID is not configured — frontend skips the flow.
    """
    return {"vapid_public_key": os.environ.get("VAPID_PUBLIC_KEY")}


@router.post("/push/subscribe")
def subscribe(
    body: PushSubscribeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Store a push subscription for the current user.
    Idempotent: re-posting the same subscription_json is a no-op (the browser
    sends the same object on every page load after the user has already
    approved, so we de-dup here instead of creating thousands of rows).
    """
    existing = db.query(PushSubscription).filter(
        PushSubscription.user_id == user.id,
        PushSubscription.subscription_json == body.subscription_json,
    ).first()
    if not existing:
        db.add(PushSubscription(
            user_id=user.id,
            subscription_json=body.subscription_json,
            created_at=datetime.now(tz=timezone.utc),
        ))
        db.commit()
    return {"ok": True}


@router.delete("/push/unsubscribe")
def unsubscribe(
    body: PushSubscribeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a specific subscription (called when user revokes permission)."""
    sub = db.query(PushSubscription).filter(
        PushSubscription.user_id == user.id,
        PushSubscription.subscription_json == body.subscription_json,
    ).first()
    if sub:
        db.delete(sub)
        db.commit()
    return {"ok": True}
