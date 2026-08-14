"""
License server DB engine and session factory.

Deliberately its own tiny SQLite file, not another Postgres container — this
service issues/validates license keys and generates a handful of Unlimited
license files; it will never see meaningful write volume, and "keep this
simple" (per the dev handoff doc) means not standing up a fourth Postgres
instance just for a few hundred rows. Swap DATABASE_URL to a Postgres DSN
later if this ever needs to run multi-instance — nothing else here assumes
SQLite specifically.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:////data/license-server.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
