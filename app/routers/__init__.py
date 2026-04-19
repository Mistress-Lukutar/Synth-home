"""Routers package."""
from app.routers.connection import router as connection
from app.routers.devices import router as devices
from app.routers.network import router as network
from app.routers.scenarios import router as scenarios
from app.routers.panels import router as panels
from app.routers.graphs import router as graphs
from app.routers.node_registry import router as node_registry

__all__ = ["connection", "devices", "network", "scenarios", "panels", "graphs", "node_registry"]
