"""SQLAlchemy ORM models — fields match what TLS-350 display format actually provides."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, Numeric, Text, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Tank(Base):
    __tablename__ = "tanks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    product: Mapped[str | None] = mapped_column(Text)
    capacity_gallons: Mapped[float | None] = mapped_column(Float)
    reorder_threshold_gallons: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Commander-reader grade id this tank corresponds to, at this station's
    # Commander unit specifically. Grade ids are NOT portable across stations
    # (or even reliably guessable from grade name — duplicate names with
    # different ids are common). NULL means "not wired to Commander" — the
    # hourly price sync skips any tank without this set. Confirm the mapping
    # with whoever knows the station before setting it.
    commander_grade_id: Mapped[int | None] = mapped_column(Integer)

    readings: Mapped[list["Reading"]] = relationship(
        "Reading", back_populates="tank", order_by="Reading.polled_at.desc()"
    )
    delivery_events: Mapped[list["DeliveryEvent"]] = relationship(
        "DeliveryEvent", back_populates="tank"
    )


class Reading(Base):
    __tablename__ = "readings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tank_id: Mapped[int] = mapped_column(Integer, ForeignKey("tanks.id"))
    polled_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    volume_gallons: Mapped[float | None] = mapped_column(Float)
    ullage_gallons: Mapped[float | None] = mapped_column(Float)
    height_inches: Mapped[float | None] = mapped_column(Float)
    water_inches: Mapped[float | None] = mapped_column(Float)
    temperature_f: Mapped[float | None] = mapped_column(Float)

    tank: Mapped["Tank"] = relationship("Tank", back_populates="readings")


class DeliveryEvent(Base):
    __tablename__ = "delivery_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tank_id: Mapped[int] = mapped_column(Integer, ForeignKey("tanks.id"))
    detected_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    start_volume_gallons: Mapped[float | None] = mapped_column(Float)
    end_volume_gallons: Mapped[float | None] = mapped_column(Float)
    gallons_received: Mapped[float | None] = mapped_column(Float)
    adjusted_gallons_received: Mapped[float | None] = mapped_column(Float)
    confirmed: Mapped[bool | None] = mapped_column(Boolean, default=False)
    manual_gallons_received: Mapped[float | None] = mapped_column(Float)
    manually_confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    merged_poll_count: Mapped[int | None] = mapped_column(Integer, default=1)
    session_started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    tank: Mapped["Tank"] = relationship("Tank", back_populates="delivery_events")


class PollLog(Base):
    __tablename__ = "poll_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    polled_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    success: Mapped[bool | None] = mapped_column(Boolean)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class Setting(Base):
    """Key/value store for live-editable runtime settings (poll interval, alignment,
    device id, remote sync). Read/written by both the API and the poller."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)


class FuelPrice(Base):
    """
    Point-in-time pricing for a tank's product — cost, taxes/fees, and retail
    sale price, all per gallon. A new row is added whenever pricing changes;
    the most recent row with effective_at <= a given time is "the price" at
    that time, which is how historical margin/profit gets computed (e.g. in
    the monthly ledger CSV). Numeric(12,6) to support sub-cent pricing.
    """
    __tablename__ = "fuel_prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tank_id: Mapped[int] = mapped_column(Integer, ForeignKey("tanks.id"))
    effective_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    cost_per_gallon: Mapped[float | None] = mapped_column(Numeric(12, 6))
    # Tax/fees per gallon, in dollars — derived automatically from
    # tax_rate_percent * cost_per_gallon when a rate is set (the normal
    # path), or set directly for edge cases (e.g. a flat excise fee) when
    # tax_rate_percent is left blank.
    tax_fees_per_gallon: Mapped[float | None] = mapped_column(Numeric(12, 6), default=0)
    tax_rate_percent: Mapped[float | None] = mapped_column(Numeric(9, 4))
    sale_price_per_gallon: Mapped[float | None] = mapped_column(Numeric(12, 6))
    source: Mapped[str] = mapped_column(Text, default="manual")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    tank: Mapped["Tank"] = relationship("Tank")
