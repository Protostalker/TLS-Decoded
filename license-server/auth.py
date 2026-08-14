"""
Guard rails for the license server's admin surface.

Two independent secrets, deliberately not combined into one — and BOTH now
stored as a hash, never as plaintext, in .env/.env.cloud/docker-compose:

  1. LICENSE_SERVER_ADMIN_TOKEN_HASH — required on every /admin/* route
     (list licenses, issue Annual keys, suspend/renew, etc). This is
     "you're allowed to operate this internal tool at all." The token is
     high-entropy/random (generate it with `hash_secret.py --type
     admin-token`, or your own `openssl rand -hex 32`), so it's hashed with
     plain SHA-256 — same reasoning as session tokens elsewhere in this
     codebase: the secret already has 256 bits of entropy, so there's
     nothing for bcrypt's deliberate slowness to protect against that a
     fast hash doesn't already cover, and a fast hash keeps every admin
     request snappy.

  2. UNLIMITED_LICENSE_PASSPHRASE_HASH — required ADDITIONALLY on the one
     route that mints a no-expiry, no-phone-home license (the sold
     feature, per the dev handoff doc). Per Raffi's answer in the doc's
     open questions: "to make the unlimited key, lets use a passphrase
     instead." Unlike the admin token, this is a short, human-chosen
     phrase — low entropy, guessable/brute-forceable if it ever leaked as
     a fast hash — so it's hashed with bcrypt (same library/pattern as
     user passwords and station device secrets in the main app's
     `api`/`cloud-api`), which is deliberately slow and salted.

Either way: this file NEVER holds a secret it can turn back into the
original value — only something it can check an incoming value against
(hash the input, compare to what's stored — "does it line up with the
stored output"). If `.env`/`.env.cloud`/a `docker inspect` output leaks,
neither secret is directly usable from what's exposed. Use
`hash_secret.py` to turn a chosen secret into the value that goes in your
env file — see README.md's Key management section.

Neither of these is a substitute for running this service somewhere with
normal network-level protections (it should not be reachable from the
public internet at all, ideally) — they're a second gate on top of that,
not instead of it.
"""
import hashlib
import hmac
import logging
import os

from fastapi import Header, HTTPException
from passlib.context import CryptContext

logger = logging.getLogger("license-server.auth")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Hash of "PermissionGranted200" (Raffi's specified default) — precomputed
# with bcrypt so this file never contains the phrase itself in the clear.
# This is a DEV-ONLY convenience default: the phrase is already public
# (it's in this repo's commit history and the original spec doc), so this
# only means "works out of the box for local dev without extra setup," not
# "secure by default." Set UNLIMITED_LICENSE_PASSPHRASE_HASH explicitly —
# to a hash of a passphrase ONLY you know — before issuing a real license.
_DEV_DEFAULT_UNLIMITED_PASSPHRASE_HASH = (
    "$2b$12$Fp3cvqFfjA4w7.SrVeEoBeaDxYthvf7MX2QPh/.NGb69AHKUt0fym"
)


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def hash_token(raw: str) -> str:
    """SHA-256 — for high-entropy, machine-generated secrets (admin token,
    license keys). See module docstring for why this differs from the
    passphrase hash below."""
    return hashlib.sha256(raw.encode()).hexdigest()


def require_admin_token(x_admin_token: str | None = Header(None)) -> None:
    expected_hash = os.environ.get("LICENSE_SERVER_ADMIN_TOKEN_HASH", "")
    if not expected_hash:
        raise HTTPException(
            status_code=503,
            detail=(
                "LICENSE_SERVER_ADMIN_TOKEN_HASH is not configured on this server — admin routes are "
                "disabled until it is. Run `python3 hash_secret.py --type admin-token` to generate one."
            ),
        )
    if not x_admin_token or not _constant_time_eq(hash_token(x_admin_token), expected_hash):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token")


def require_unlimited_passphrase(x_unlimited_passphrase: str | None = Header(None)) -> None:
    expected_hash = os.environ.get("UNLIMITED_LICENSE_PASSPHRASE_HASH", "")
    if not expected_hash:
        logger.warning(
            "UNLIMITED_LICENSE_PASSPHRASE_HASH is not set — falling back to the DEV default "
            "('PermissionGranted200', already public). Set your own via "
            "`python3 hash_secret.py --type passphrase` before issuing a real Unlimited license."
        )
        expected_hash = _DEV_DEFAULT_UNLIMITED_PASSPHRASE_HASH
    if not x_unlimited_passphrase or not _verify_bcrypt(x_unlimited_passphrase, expected_hash):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Unlimited-Passphrase")


def _verify_bcrypt(raw: str, expected_hash: str) -> bool:
    try:
        return pwd_context.verify(raw, expected_hash)
    except Exception:
        return False  # malformed/foreign hash format — fail closed, not 500


def hash_key(raw: str) -> str:
    # License keys are 256 bits of CSPRNG entropy already (see
    # routers/admin.py's gen_license_key) — same reasoning as hash_token()
    # above: SHA-256 is fine, this isn't a low-entropy-secret situation
    # that needs bcrypt's deliberate slowness.
    return hashlib.sha256(raw.encode()).hexdigest()
