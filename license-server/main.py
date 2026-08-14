"""
TLS Fuel Platform — License Server.

Deliberately simple, per Raffi's call: this is a database of passphrases
you (Raffi) hand out — that's it. Every Cloud Utility phones home to
/license/check on startup and periodically thereafter; there's no offline
verification, no signing keys, no JWT files to generate or lose.

  - Each License row is a passphrase you chose yourself when you created
    it, with a use limit (how many different Cloud Utility instances may
    activate with it — default 1) and a fixed expiry date set at creation.
  - The MASTER_PASSPHRASE (default "PermissionGranted200") is auto-seeded
    on first boot as a License with unlimited uses and no expiry — always
    works out of the box, no admin API call needed to set it up.
  - See models.py's module docstring for how "1-time use" and "phones
    home every day" coexist (LicenseRedemption — binding an instance_id to
    a license consumes a use; a routine re-check from an already-bound
    instance doesn't).

Never talks to a Local Instance, ever — only the Cloud Utility (phone-home)
and whoever is running the admin tooling (issuing codes) call this
service. See README.md for the full picture.
"""
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine, SessionLocal
from models import License
from routers import admin, check

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("license-server.main")

app = FastAPI(
    title="TLS Fuel Platform — License Server",
    description="Passphrase-based phone-home licensing",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MASTER_PASSPHRASE_DEFAULT = "PermissionGranted200"


@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)
    _bootstrap_master_license()
    logger.info("License server ready.")


def _bootstrap_master_license() -> None:
    """First-run convenience: auto-create the master (unlimited-use,
    never-expires) license if it doesn't exist yet. No-op on every run
    after that — safe to call every startup. Override the phrase via
    MASTER_PASSPHRASE if you don't want the shared default in a real
    deployment (it's already public — it's in this repo's history)."""
    phrase = os.environ.get("MASTER_PASSPHRASE", MASTER_PASSPHRASE_DEFAULT).strip()
    if not phrase:
        return
    db = SessionLocal()
    try:
        existing = db.query(License).filter(License.passphrase == phrase).first()
        if existing:
            return
        db.add(License(
            passphrase=phrase, customer_name="Master (internal/unlimited)", station_scope=None,
            max_uses=None, status="active", issued_at=datetime.now(tz=timezone.utc),
            expires_at=None, is_master=True,
        ))
        db.commit()
        logger.info("Seeded master license (unlimited uses, never expires).")
    finally:
        db.close()


app.include_router(check.router)                    # /license/* — phone-home, no admin token
app.include_router(admin.router, prefix="/admin")    # /admin/* — internal tool, token-gated


@app.get("/health")
def health():
    return {"status": "ok"}
