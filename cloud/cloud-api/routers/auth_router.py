"""T2 — login, logout, current user, and a user's own session list."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from auth import create_session, get_current_user, hash_token, verify_secret, _extract_token
from database import get_db
from models import Customer, User, UserSession
from schemas import LoginRequest, LoginResponse, MeOut, SessionOut

router = APIRouter()

COOKIE_NAME = "session_token"


def _me_out(db: Session, user: User) -> MeOut:
    customer_name = None
    if user.customer_id:
        c = db.query(Customer).filter(Customer.id == user.customer_id).first()
        customer_name = c.name if c else None
    return MeOut(
        id=user.id, email=user.email, role=user.role,
        customer_id=user.customer_id, customer_name=customer_name,
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not user.active or not verify_secret(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_session(
        db, user, duration=body.duration,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )

    # Cookie for browser use; the token is also returned in the body for
    # non-cookie (e.g. mobile) clients that want to send it as a Bearer token.
    max_age = None if body.duration == "never" else (90 * 86400 if body.duration == "90d" else None)
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="lax", max_age=max_age, path="/",
    )
    return LoginResponse(token=token, user=_me_out(db, user))


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = _extract_token(request, request.headers.get("authorization"))
    if token:
        sess = db.query(UserSession).filter(UserSession.token_hash == hash_token(token)).first()
        if sess:
            sess.revoked_at = datetime.now(tz=timezone.utc)
            db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _me_out(db, user)


@router.get("/auth/sessions", response_model=list[SessionOut])
def my_sessions(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_token = _extract_token(request, request.headers.get("authorization"))
    current_hash = hash_token(current_token) if current_token else None

    rows = (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id)
        .order_by(UserSession.created_at.desc())
        .all()
    )
    return [
        SessionOut(
            id=s.id, created_at=s.created_at, expires_at=s.expires_at, revoked_at=s.revoked_at,
            last_used_at=s.last_used_at, user_agent=s.user_agent, ip_address=s.ip_address,
            is_current=(s.token_hash == current_hash),
        )
        for s in rows
    ]


@router.delete("/auth/sessions/{session_id}")
def revoke_my_session(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sess = db.query(UserSession).filter(UserSession.id == session_id, UserSession.user_id == user.id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    sess.revoked_at = datetime.now(tz=timezone.utc)
    db.commit()
    return {"ok": True}
