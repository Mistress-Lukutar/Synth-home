"""SQLAlchemy database models for ZigbeeHUB WebUI."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DeviceAlias(Base):
    __tablename__ = "device_aliases"

    ieee_addr: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual")
    trigger_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_type: Mapped[str] = mapped_column(String(32), default="command")
    action_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Schedule-specific fields (used when trigger_type == "schedule")
    schedule_days: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    schedule_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    schedule_minute: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=utc_now)
