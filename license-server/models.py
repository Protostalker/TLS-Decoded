"""ORM models for the license server.

Two license types, two tables — deliberately not unified into one, because
they're validated completely differently (Annual is a DB lookup on every
phone-home; Unlimited is a signed offline blob the server never sees again
after issuing it). AnnualLicense is the live, mutable record of an
ongoing relationship; UnlimitedLicense is just an issuance log — once
generated, the license server has no further role in that license's life.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AnnualLicense(Base):
    """
    Annual (phone-home) license. The key itself is never stored in plain
    text — only its hash — same posture as station device secrets and user
    passwords elsewhere in this codebase. The raw key is shown to the admin
    exactly once, at issuance.
    """
    __tablename__ = "annual_licenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    key_hint: Mapped[str] = mapped_column(String, nullable=False)  # last 4 chars, for display/support calls only

    customer_name: Mapped[str] = mapped_column(String, nullable=False)
    station_scope: Mapped[str | None] = mapped_column(Text)  # free-text for now, e.g. "up to 5 stations"

    # "active" | "suspended" — admin-controlled kill switch, independent of
    # expires_at (e.g. a chargeback or a customer who asked to be paused).
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")

    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # end of current paid period
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime)  # most recent renewal, if any

    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_checked_ip: Mapped[str | None] = mapped_column(String)


class UnlimitedLicense(Base):
    """
    Issuance log for one-time offline-activation licenses. The license
    FILE (a signed JWT) is handed to the customer and validated entirely
    client-side by the Cloud Utility from then on — this row exists purely
    so an admin can see what's been issued and to whom; it is never read
    back at validation time.
    """
    __tablename__ = "unlimited_licenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # JWT id claim, for audit/revocation-list use later
    customer_name: Mapped[str] = mapped_column(String, nullable=False)
    station_scope: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # informational only — see README
