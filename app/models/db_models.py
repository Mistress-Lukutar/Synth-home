"""SQLAlchemy database models for ZigbeeHUB WebUI."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DeviceAlias(Base):
    __tablename__ = "device_aliases"

    ieee_addr: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class Device(Base):
    __tablename__ = "devices"

    ieee_addr: Mapped[str] = mapped_column(String(32), primary_key=True)
    network_addr: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    endpoints: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    online: Mapped[bool] = mapped_column(Boolean, default=True)
    last_command: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    last_seen: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual")
    trigger_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    actions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=utc_now)
