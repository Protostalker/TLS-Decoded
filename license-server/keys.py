"""
Signing-key management for Unlimited license files.

Guard LICENSE_SIGNING_PRIVATE_KEY_PATH like a production secret (per the dev
handoff doc's open-question answer: private keys run on a key-issuing
server — this service *is* that key-issuing server). Rotation: generate a
new keypair, point LICENSE_SIGNING_PRIVATE_KEY_PATH at it, redeploy — every
Unlimited license issued *before* the rotation stays valid only as long as
Cloud Utility installs still trust the OLD public key (LICENSE_SIGNING_PUBLIC_KEY
in their env). There's no revocation channel for Unlimited licenses by
design (no phone-home, ever) — see README.md's "Rotation & revocation" note
for the operational consequence of that.

Dev convenience: if no key file is configured, an ephemeral keypair is
generated in memory on startup. This is fine for local development but
means every restart invalidates every previously-issued Unlimited license
(the public key changed) — a loud warning is logged so this is never
accidentally the production posture.
"""
import logging
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

logger = logging.getLogger("license-server.keys")

_private_key = None
_public_key_pem: str | None = None


def _generate_ephemeral() -> None:
    global _private_key, _public_key_pem
    logger.warning(
        "LICENSE_SIGNING_PRIVATE_KEY_PATH is not set — generating an EPHEMERAL "
        "signing key for this process only. Every Unlimited license issued now "
        "will stop validating the next time this container restarts. Set "
        "LICENSE_SIGNING_PRIVATE_KEY_PATH (and mount a persistent key file) "
        "before issuing any license you intend to hand to a real customer."
    )
    _private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _public_key_pem = _private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def _load_from_file(path: str) -> None:
    global _private_key, _public_key_pem
    with open(path, "rb") as f:
        _private_key = serialization.load_pem_private_key(f.read(), password=None)
    _public_key_pem = _private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    logger.info("Loaded license signing key from %s", path)


def init_keys() -> None:
    path = os.environ.get("LICENSE_SIGNING_PRIVATE_KEY_PATH", "")
    if path and os.path.exists(path):
        _load_from_file(path)
    elif path:
        # Path configured but file doesn't exist yet — generate one and write
        # it, so a fresh deploy is self-bootstrapping instead of crash-looping.
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(path, "wb") as f:
            f.write(pem)
        os.chmod(path, 0o600)
        logger.warning(
            "No key found at %s — generated a new one and wrote it there. "
            "Back this file up; losing it means every previously-issued "
            "Unlimited license stops validating.", path,
        )
        _load_from_file(path)
    else:
        _generate_ephemeral()


def private_key():
    if _private_key is None:
        init_keys()
    return _private_key


def public_key_pem() -> str:
    if _public_key_pem is None:
        init_keys()
    return _public_key_pem
