from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SensorReading(Base):
    __tablename__ = "sensor_reading"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    sensor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sensor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")


class Alert(Base):
    __tablename__ = "alert"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sensor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)


class PowerEvent(Base):
    __tablename__ = "power_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    initiated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class FanControlLog(Base):
    __tablename__ = "fan_control_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    server: Mapped[str] = mapped_column(String(32), nullable=False)
    zone: Mapped[int] = mapped_column(Integer, nullable=False)
    source_temp: Mapped[float] = mapped_column(Float, nullable=False)
    source_label: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    target_duty: Mapped[int] = mapped_column(Integer, nullable=False)
    prev_duty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
