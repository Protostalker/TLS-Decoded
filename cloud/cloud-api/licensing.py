"""
License state for the Cloud Utility — the ONLY piece of this codebase that
ever checks a license (see the dev handoff doc's Scope Split section; the
Local Instance never touches any of this).

Deliberately simple, per Raffi's call: one passphrase, phoned home to the
license server on startup and every LICENSE_CHECK_INTERVAL_HOURS
thereafter (default 24). No offline verification, no signing keys, no
license files — every check is a live network call. A run of failures
(unreachable OR the server says invalid) starts a clock; once that clock
passes LICENSE_GRACE_DAYS (45, per the dev handoff doc), the Cloud Utility
enters degraded mode. A single successful check clears the clock
immediately and restores full functionality — "no data loss, immediate
restoration" per the spec.

Degraded mode itself (what it actually restricts) lives in auth.py's
require_not_degraded — this module only computes and persists the state.

Two layers of configuration:

  - Deployment/infra settings (LICENSE_SERVER_URL, LICENSE_GRACE_DAYS,
    LICENSE_CHECK_INTERVAL_HOURS) — env vars only, always. These describe
    *how this deployment is wired up*, not which license it holds.

  - The passphrase itself — CLOUD_LICENSE_KEY only SEEDS this once, on
    first boot with an empty DB (initial-deployment convenience, same
    pattern as cloud_sync_* on the station side). From then on it's
    stored in CloudLicenseState.configured_passphrase and managed
    entirely through Admin -> License in the cloud frontend (see
    routers/license.py's activate/deactivate) — no env edits or restarts
    needed to activate or switch to a different code.
"""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from database import SessionLocal
from models import CloudLicenseState

logger = logging.getLogger("cloud-api.licensing")

STATE_ID = 1  # single-row table


def _get_or_create_state(db: Session) -> CloudLicenseState:
    state = db.query(CloudLicenseState).filter(CloudLicenseState.id == STATE_ID).first()
    if not state:
        state = CloudLicenseState(id=STATE_ID, status="unconfigured")
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _ensure_instance_id(db: Session, state: CloudLicenseState) -> str:
    """Generated once, ever, for this Cloud Utility deployment — persists
    across activating/deactivating/switching license codes. See
    models.CloudLicenseState's docstring for why the license server needs
    this (telling 'same instance re-checking' apart from 'a different
    instance trying to activate')."""
    if not state.instance_id:
        state.instance_id = secrets.token_hex(16)
        db.commit()
    return state.instance_id


def _load_infra_config() -> dict:
    """Deployment-level settings — always from env, never from the DB/UI."""
    return {
        "license_server_url": os.environ.get("LICENSE_SERVER_URL", "").rstrip("/"),
        "grace_days": int(os.environ.get("LICENSE_GRACE_DAYS", "45")),
        "check_interval_hours": float(os.environ.get("LICENSE_CHECK_INTERVAL_HOURS", "24")),
    }


def _seed_from_env_once(db: Session, state: CloudLicenseState) -> None:
    """First boot only: if nothing has ever been configured via the UI (or
    a previous seed), and CLOUD_LICENSE_KEY is set, persist it as the
    configured passphrase. No-ops instantly on every later boot."""
    if state.configured_passphrase:
        return  # already configured — env var is never consulted again
    seed = os.environ.get("CLOUD_LICENSE_KEY", "").strip()
    if not seed:
        return
    state.configured_passphrase = seed
    db.commit()
    logger.info("Seeded license passphrase from CLOUD_LICENSE_KEY — future changes go through Admin -> License, not env.")


def check_license(passphrase: str, instance_id: str, infra: dict) -> dict:
    """Phone home once. Returns the server's response dict; raises on
    network failure (caller treats that the same as an 'invalid' response
    for grace-clock purposes — see the dev handoff doc: 'unreachable OR
    invalid' both count)."""
    if not passphrase:
        raise ValueError("No license passphrase is configured.")
    if not infra["license_server_url"]:
        raise ValueError("LICENSE_SERVER_URL is not configured on this deployment.")
    resp = httpx.post(
        f"{infra['license_server_url']}/license/check",
        json={"passphrase": passphrase, "instance_id": instance_id},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def run_license_check() -> None:
    """One evaluation cycle — called on startup and on the interval loop
    (main.py). Owns its own DB session since it's called from a background
    task, not a request."""
    db = SessionLocal()
    try:
        state = _get_or_create_state(db)
        _seed_from_env_once(db, state)
        infra = _load_infra_config()
        now = datetime.now(tz=timezone.utc)

        if not state.configured_passphrase:
            state.status = "unconfigured"
            state.last_check_at = now
            state.last_check_ok = None
            state.last_check_detail = "No license configured — set one from Admin -> License."
            state.updated_at = now
            db.commit()
            return

        instance_id = _ensure_instance_id(db, state)
        try:
            result = check_license(state.configured_passphrase, instance_id, infra)
            ok = result.get("status") == "valid"
            state.customer_name = result.get("customer_name") or state.customer_name
            state.station_scope = result.get("station_scope") or state.station_scope
            state.expires_at = _parse_dt(result.get("expires_at"))
            state.last_check_at = now
            state.last_check_ok = ok
            state.last_check_detail = result.get("detail")

            if ok:
                state.status = "active"
                state.activated_at = state.activated_at or now
                state.failing_since = None
            else:
                _apply_failure(state, infra, now)
        except Exception as exc:
            logger.warning("License phone-home failed (server unreachable?): %s", exc)
            state.last_check_at = now
            state.last_check_ok = False
            state.last_check_detail = f"License server unreachable: {exc}"
            _apply_failure(state, infra, now)

        state.updated_at = now
        db.commit()
    finally:
        db.close()


def _apply_failure(state: CloudLicenseState, infra: dict, now: datetime) -> None:
    if state.failing_since is None:
        state.failing_since = now
    failing_since = state.failing_since
    if failing_since.tzinfo is None:
        failing_since = failing_since.replace(tzinfo=timezone.utc)
    days_failing = (now - failing_since).total_seconds() / 86400.0
    state.status = "degraded" if days_failing >= infra["grace_days"] else "grace"


def _parse_dt(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")) if isinstance(raw, str) else raw
    except Exception:
        return None


def get_state_dict(db: Session) -> dict:
    state = _get_or_create_state(db)
    infra = _load_infra_config()
    days_remaining_in_grace = None
    if state.status == "grace" and state.failing_since:
        failing_since = state.failing_since
        if failing_since.tzinfo is None:
            failing_since = failing_since.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(tz=timezone.utc) - failing_since).total_seconds() / 86400.0
        days_remaining_in_grace = max(0, round(infra["grace_days"] - elapsed, 1))
    return {
        "customer_name": state.customer_name,
        "station_scope": state.station_scope,
        "status": state.status,
        "activated_at": state.activated_at,
        "expires_at": state.expires_at,
        "last_check_at": state.last_check_at,
        "last_check_ok": state.last_check_ok,
        "last_check_detail": state.last_check_detail,
        "grace_days_total": infra["grace_days"],
        "grace_days_remaining": days_remaining_in_grace,
    }


def get_config_dict(db: Session) -> dict:
    """For Admin -> License's activation form — what's currently configured,
    without ever exposing the full passphrase back to the browser."""
    state = _get_or_create_state(db)
    passphrase = state.configured_passphrase or ""
    return {
        "configured": bool(passphrase),
        "passphrase_hint": (passphrase[-4:] if len(passphrase) >= 4 else passphrase) or None,
    }


# ── Activation (Admin -> License in the cloud frontend) ─────────────────────
# Validates BEFORE persisting — a bad paste fails loudly right away instead
# of silently starting a 45-day degrade clock.

def activate(db: Session, passphrase: str) -> dict:
    passphrase = (passphrase or "").strip()
    if not passphrase:
        raise ValueError("License passphrase is required.")
    infra = _load_infra_config()
    state = _get_or_create_state(db)
    instance_id = _ensure_instance_id(db, state)

    result = check_license(passphrase, instance_id, infra)
    if result.get("status") != "valid":
        raise ValueError(result.get("detail") or "License server rejected this passphrase.")

    state.configured_passphrase = passphrase
    db.commit()
    run_license_check()
    db.refresh(state)
    return get_state_dict(db)


def deactivate(db: Session) -> dict:
    """Clears the configured license — the instance_id is deliberately
    KEPT (same instance, no license, for now); reactivating with a new or
    the same code just phones home again with that same instance_id."""
    state = _get_or_create_state(db)
    state.configured_passphrase = None
    state.customer_name = None
    state.station_scope = None
    state.status = "unconfigured"
    state.activated_at = None
    state.expires_at = None
    state.failing_since = None
    state.last_check_detail = "Deactivated from Admin -> License."
    state.updated_at = datetime.now(tz=timezone.utc)
    db.commit()
    db.refresh(state)
    return get_state_dict(db)
