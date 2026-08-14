"""
TLS Fuel Platform — License Server.

A small, standalone service with two jobs (see tls-fuel-platform strategy /
dev-handoff docs for the "why"):

  1. Issue and validate Annual licenses — the phone-home endpoint the Cloud
     Utility hits on startup and daily thereafter.
  2. Generate signed Unlimited license files — a one-off, admin-triggered
     action; this is an internal tool, not a customer-facing surface.

Deliberately NOT fancy: no customer-facing UI, no self-serve signup, one
SQLite file for storage. It needs to be hard to forge, not impressive — see
auth.py for the two guard rails (admin token for all /admin/* routes, plus a
separate passphrase specifically for minting Unlimited licenses, per Raffi's
answer in the dev handoff doc's open questions).

Never talks to a Local Instance, ever — only the Cloud Utility (Annual
phone-home) and whoever is running the admin tooling (Unlimited issuance)
call this service. See README.md for the full picture.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import keys
from database import Base, engine
from routers import admin, check

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("license-server.main")

app = FastAPI(
    title="TLS Fuel Platform — License Server",
    description="Annual phone-home validation + Unlimited offline license issuance",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)
    keys.init_keys()  # fail fast / warn loudly here, not on the first request
    logger.info("License server ready.")


app.include_router(check.router)          # /license/* — public-ish phone-home + public key
app.include_router(admin.router, prefix="/admin")  # /admin/* — internal tool, token-gated


@app.get("/health")
def health():
    return {"status": "ok"}
