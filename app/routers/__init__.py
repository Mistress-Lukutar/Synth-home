"""Routers package."""
from app.routers.connection import router as connection
from app.routers.devices import router as devices
from app.routers.network import router as network
from app.routers.scenarios import router as scenarios

__all__ = ["connection", "devices", "network", "scenarios"]
