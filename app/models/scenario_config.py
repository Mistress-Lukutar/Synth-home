"""Structured Pydantic models for Scenario trigger and action configurations."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ManualTrigger(BaseModel):
    type: Literal["manual"] = "manual"


class ScheduleTrigger(BaseModel):
    type: Literal["schedule"] = "schedule"
    cron: Optional[str] = None  # e.g. "0 8 * * 1,2,5"
    days: Optional[str] = None  # e.g. "mon,tue,wed"
    hour: Optional[int] = Field(None, ge=0, le=23)
    minute: Optional[int] = Field(None, ge=0, le=59)


class DeviceEventTrigger(BaseModel):
    type: Literal["device_event"] = "device_event"
    event: Optional[str] = None
    ieee: Optional[str] = None


TriggerConfig = ManualTrigger | ScheduleTrigger | DeviceEventTrigger


class CommandAction(BaseModel):
    type: Literal["command"] = "command"
    ieee: str
    action: str = "toggle"
    params: dict[str, Any] = Field(default_factory=dict)


ActionConfig = CommandAction
