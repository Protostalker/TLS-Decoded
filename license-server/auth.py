"""
Guard rail for the license server's admin surface — one secret:
LICENSE_SERVER_ADMIN_TOKEN_HASH, required on every /admin/* route (list
licenses, create/renew/suspend codes). This is "you're allowed to operate
this internal tool at all."

Stored as a hash (SHA-256 — the token is a long random string, so there's
nothing for bcrypt's deliberate slowness to protect against that a fast
hash doesn't already cover), never as plaintext, so `.env`/`docker
inspect` never expose a directly-usable secret. Generate the hash with
`hash_secret.py` — see README.md's Key management section.

This is not a substitute for running this service somewhere with normal
network-level protections (it should not be reachable from the public
internet at all, ideally) — it's a second gate on top of that, not
instead of it.
"""
import hashlib
import hmac
import os

from fastapi import Header, HTTPException


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def hash_token(raw: str) -> str:
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
