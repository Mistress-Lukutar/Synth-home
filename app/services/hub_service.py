"""Business-logic service wrapper around HubClient."""

import asyncio
from typing import Optional, Dict, Any, List

import structlog

from app.db import async_session
from app.exceptions import HubConnectionError
from app.repositories.device import DeviceRepository
from app.services.hub_client import HubClient
from app.services.protocol import ProtocolHandler
from app.services.event_bus import EventBus

logger = structlog.get_logger(__name__)


class HubService:
    """Async business-logic wrapper for hub communication.

    Not a singleton — instantiated per application lifespan or test fixture.
    """

    def __init__(
        self,
        event_bus: EventBus,
        client: Optional[HubClient] = None,
    ) -> None:
        self._event_bus = event_bus
        self._client = client or HubClient(ProtocolHandler())
        self._client.set_on_message(self._on_hub_message)
        self._devices: List[Dict[str, Any]] = []
        self._bg_tasks: set[asyncio.Task] = set()

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
            await self._event_bus.publish("hub_connected", {"port": port})
            self._spawn_background(self.fetch_devices())
        else:
            logger.warning("hub_connect_failed", port=port)
        return ok

    async def disconnect(self) -> None:
        """Disconnect from the hub and cancel background tasks."""
        if self.is_connected():
            logger.info("disconnecting_from_hub")
        await self._cancel_background_tasks()
        await self._client.disconnect()
        await self._event_bus.publish("hub_disconnected", {})

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
        else:
            await self._sync_devices(devices)
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
            self._spawn_background(self._sync_devices(mapped))

        # Publish domain events for downstream consumers (scheduler, SSE, etc.)
        if evt in ("device_joined", "device_left", "state_change", "command_failed"):
            self._spawn_background(
                self._event_bus.publish("device_event", {"event": evt, "data": data})
            )

        self._spawn_background(
            self._event_bus.publish("hub_message", {"data": data})
        )

    async def _sync_devices(self, devices: List[Dict[str, Any]]) -> None:
        """Persist or update device topology in the database."""
        async with async_session() as session:
            repo = DeviceRepository(session)
            for d in devices:
                ieee = d.get("ieee_addr") or d.get("ieee", "")
                if not ieee:
                    continue
                await repo.upsert(
                    ieee,
                    network_addr=d.get("network_addr"),
                    endpoint=d.get("endpoint"),
                    supports_hs=d.get("supports_hs", False),
                    supports_xy=d.get("supports_xy", False),
                    supports_ct=d.get("supports_ct", False),
                    online=d.get("online", True),
                )
            await session.commit()

    def _spawn_background(self, coro: asyncio.coroutines) -> None:
        """Spawn a background task and keep a weak reference for cleanup."""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _cancel_background_tasks(self) -> None:
        """Cancel any outstanding background tasks."""
        if not self._bg_tasks:
            return
        for task in self._bg_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        self._bg_tasks.clear()
