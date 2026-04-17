"""Business-logic service wrapper around HubClient."""

import asyncio
from typing import Optional, Dict, Any, List

import structlog

from app.exceptions import HubConnectionError
from app.services.hub_client import HubClient
from app.services.sse_manager import sse_manager

logger = structlog.get_logger(__name__)


class HubService:
    """Async business-logic wrapper for hub communication."""

    def __init__(self) -> None:
        self._client = HubClient()
        self._client.set_on_message(self._on_hub_message)
        self._devices: List[Dict[str, Any]] = []

    def is_connected(self) -> bool:
        return self._client.is_connected()

    def get_port(self) -> Optional[str]:
        return self._client.get_port()

    async def connect(self, port: str) -> bool:
        """Connect to the hub on the given COM port."""
        logger.info("connecting_to_hub", port=port)
        ok = await self._client.connect(port)
        if ok:
            logger.info("hub_connected", port=port)
            await sse_manager.broadcast("connected", {"port": port})
            # Request device list after connect (background)
            asyncio.create_task(self.fetch_devices())
        else:
            logger.warning("hub_connect_failed", port=port)
        return ok

    async def disconnect(self) -> None:
        """Disconnect from the hub."""
        if self.is_connected():
            logger.info("disconnecting_from_hub")
        await self._client.disconnect()
        await sse_manager.broadcast("disconnected", {})

    async def send_command(
        self, ieee: str, action: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not self.is_connected():
            raise HubConnectionError()
        result = await self._client.send_command(ieee, action, params)
        logger.info("command_sent", ieee=ieee, action=action)
        return result

    async def permit_join(self, duration: int) -> Dict[str, Any]:
        if not self.is_connected():
            raise HubConnectionError()
        result = await self._client.permit_join(duration)
        logger.info("permit_join_sent", duration=duration)
        return result

    async def fetch_devices(self) -> List[Dict[str, Any]]:
        if not self.is_connected():
            raise HubConnectionError()
        devices = await self._client.fetch_devices()
        if not devices:
            logger.warning("fetch_devices_empty_or_timeout")
        return devices

    def get_cached_devices(self) -> List[Dict[str, Any]]:
        return list(self._devices)

    def _on_hub_message(self, data: Dict[str, Any]) -> None:
        """Handle incoming messages from the hub (called from reader task via callback)."""
        evt = data.get("evt") or data.get("event")
        if evt == "device_list":
            raw_devices = data.get("devices", [])
            mapped: List[Dict[str, Any]] = []
            for d in raw_devices:
                mapped.append(
                    {
                        "ieee": d.get("ieee_addr", ""),
                        "name": d.get("name") or "Zigbee Device",
                        "network_addr": d.get("network_addr"),
                        "endpoint": d.get("endpoint"),
                        "supports_hs": d.get("supports_hs", False),
                        "supports_xy": d.get("supports_xy", False),
                        "supports_ct": d.get("supports_ct", False),
                        "online": True,
                    }
                )
            self._devices = mapped
        # Evaluate device_event scenarios
        if evt in ("device_joined", "device_left", "state_change", "command_failed"):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
            from app.scheduler_engine import evaluate_device_event
            loop.create_task(evaluate_device_event(data))
        # Broadcast raw message to SSE clients
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        loop.create_task(sse_manager.broadcast("hub_message", {"data": data}))


_hub_service_instance: Optional[HubService] = None


def get_hub_service() -> HubService:
    global _hub_service_instance
    if _hub_service_instance is None:
        _hub_service_instance = HubService()
    return _hub_service_instance


def set_hub_service(service: HubService) -> None:
    """Override the global singleton instance (useful for tests)."""
    global _hub_service_instance
    _hub_service_instance = service


def reset_hub_service() -> None:
    """Reset the global singleton instance (useful for tests)."""
    global _hub_service_instance
    _hub_service_instance = None
