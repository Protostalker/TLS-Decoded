"""
ORM models — deliberately just two simple tables. No JWTs, no signing
keys, no offline verification: every Cloud Utility phones home, every time,
to this server. See main.py's module docstring for the full picture.

  - License: one row per passphrase you (Raffi) hand out. You choose the
    text yourself when creating it (POST /admin/licenses) — this isn't a
    self-serve system, so there's no reason to auto-generate something
    unmemorable. max_uses caps how many different Cloud Utility instances
    can ACTIVATE with it; expires_at is a fixed date set at creation
    ("from creation," not "from first activation," per your call).

  - LicenseRedemption: one row per Cloud Utility instance that has
    activated with a given License. This is what makes "1-time use" and
    "phones home daily" both true at once — activating (binding a new
    instance_id to the license) consumes one use; a routine phone-home
    check afterward, from an instance_id already bound, doesn't consume
    another one. Without this, a 1-use code would only survive its first
    successful check ever.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    passphrase: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    customer_name: Mapped[str] = mapped_column(String, nullable=False)
    station_scope: Mapped[str | None] = mapped_column(Text)

    # How many different Cloud Utility instances may activate with this
    # code. NULL = unlimited (the master code, and any other code you
    # choose to make unlimited-use).
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # "active" | "suspended" — admin kill switch, independent of expiry.
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")

    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Fixed at creation time. NULL = never expires (the master code, or any
    # other code you choose not to expire).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # True only for the auto-seeded master code — informational, so the
    # admin listing can flag it distinctly even though nothing in the
    # validation logic actually branches on this (an ordinary code with
    # max_uses=NULL and expires_at=NULL behaves identically).
    is_master: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    redemptions: Mapped[list["LicenseRedemption"]] = relationship(
        "LicenseRedemption", back_populates="license", cascade="all, delete-orphan"
    )


class LicenseRedemption(Base):
    """One Cloud Utility instance's binding to a License — see module
    docstring. instance_id is a random token the Cloud Utility generates
    for itself once, on first activation, and persists (CloudLicenseState.instance_id)
    — sent on every /license/check from then on."""
    __tablename__ = "license_redemptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    license_id: Mapped[int] = mapped_column(Integer, ForeignKey("licenses.id"), nullable=False)
    instance_id: Mapped[str] = mapped_column(String, nullable=False)

    redeemed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_checked_ip: Mapped[str | None] = mapped_column(String)

    license: Mapped["License"] = relationship("License", back_populates="redemptions")
