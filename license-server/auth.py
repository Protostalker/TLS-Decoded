"""
Guard rails for the license server's admin surface.

Two independent secrets, deliberately not combined into one:

  1. LICENSE_SERVER_ADMIN_TOKEN — required on every /admin/* route (list
     licenses, issue Annual keys, suspend/renew, etc). This is "you're
     allowed to operate this internal tool at all."

  2. Unlimited-license passphrase — required ADDITIONALLY on the one route
     that mints a no-expiry, no-phone-home license (the sold feature, per
     the dev handoff doc). Per Raffi's answer in the doc's open questions:
     "to make the unlimited key, lets use a passphrase instead" — default
     value below, override via UNLIMITED_LICENSE_PASSPHRASE for rotation.
     This is "you're allowed to mint the one license type that, once
     issued, this server can never revoke or expire."

Neither of these is a substitute for running this service somewhere with
normal network-level protections (it should not be reachable from the
public internet at all, ideally) — they're a second gate on top of that,
not instead of it.
"""
import hashlib
import hmac
import os

from fastapi import Header, HTTPException

DEFAULT_UNLIMITED_PASSPHRASE = "PermissionGranted200"


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def require_admin_token(x_admin_token: str | None = Header(None)) -> None:
    expected = os.environ.get("LICENSE_SERVER_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="LICENSE_SERVER_ADMIN_TOKEN is not configured on this server — admin routes are disabled until it is.",
        )
    if not x_admin_token or not _constant_time_eq(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token")


def require_unlimited_passphrase(x_unlimited_passphrase: str | None = Header(None)) -> None:
    expected = os.environ.get("UNLIMITED_LICENSE_PASSPHRASE", DEFAULT_UNLIMITED_PASSPHRASE)
    if not x_unlimited_passphrase or not _constant_time_eq(x_unlimited_passphrase, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Unlimited-Passphrase")


def hash_key(raw: str) -> str:
    # License keys are 256 bits of CSPRNG entropy already (see
    # routers/admin.py's gen_license_key) — same reasoning as session tokens
    # in the main app: SHA-256 is fine, this isn't a low-entropy-secret
    # situation that needs bcrypt's deliberate slowness.
    return hashlib.sha256(raw.encode()).hexdigest()
