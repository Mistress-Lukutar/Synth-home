"""Business-logic service wrapper around HubClient."""

import asyncio
from typing import Optional, Dict, Any, List

import structlog

from app.exceptions import HubConnectionError
from app.services.device_state_manager import DeviceStateManager
from app.services.hub_client import HubClient
from app.services.protocol import ProtocolHandler
from app.services.event_bus import EventBus

logger = structlog.get_logger(__name__)

PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 3.0


class HubService:
    """Async business-logic wrapper for hub communication.

    This class owns the in-memory device cache used by graph executors and the
    API. All persisted state updates are delegated to
    :class:`DeviceStateManager`, which is the single authority for
    ``Device.state`` and ``Device.online``.

    Not a singleton — instantiated per application lifespan or test fixture.
    """

    def __init__(
        self,
        event_bus: EventBus,
        state_manager: Optional[DeviceStateManager] = None,
        client: Optional[HubClient] = None,
    ) -> None:
        self._event_bus = event_bus
        self._client = client or HubClient(ProtocolHandler(), event_bus=event_bus)
        self._client.set_on_message(self._on_hub_message)
        self._devices: List[Dict[str, Any]] = []
        self._bg_tasks: set[asyncio.Task] = set()
        self._ping_task: Optional[asyncio.Task] = None
        self._stop_ping = asyncio.Event()

        self._state_manager = state_manager or DeviceStateManager()
        self._state_manager.set_callbacks(
            on_state_changed=self._update_cached_device_state,
            on_online_changed=self._update_cached_online,
        )

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
            self._start_ping_loop()
        else:
            logger.warning("hub_connect_failed", port=port)
        return ok

    async def disconnect(self) -> None:
        """Disconnect from the hub and cancel background tasks."""
        if self.is_connected():
            logger.info("disconnecting_from_hub")
        self._stop_ping_loop()
        await self._cancel_background_tasks()
        await self._client.disconnect()
        await self._state_manager.mark_all_devices_offline()
        await self._event_bus.publish("hub_disconnected", {})

    async def send_command(
        self, ieee: str, action: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not self.is_connected():
            raise HubConnectionError()
        result = await self._client.send_command(ieee, action, params)
        correlation_id = result.get("correlation_id")
        endpoint = (params or {}).get("endpoint")
        self._state_manager.register_command(correlation_id, ieee, endpoint, action)
        logger.info(
            "command_sent",
            ieee=ieee,
            action=action,
            endpoint=endpoint,
            correlation_id=correlation_id,
        )
        return result

    async def read_attr(
        self, ieee: str, endpoint: Optional[int], cluster: str, attribute: str
    ) -> Dict[str, Any]:
        if not self.is_connected():
            raise HubConnectionError()
        result = await self._client.read_attr(ieee, endpoint, cluster, attribute)
        logger.info(
            "read_attr_sent",
            ieee=ieee,
            endpoint=endpoint,
            cluster=cluster,
            attribute=attribute,
            correlation_id=result.get("correlation_id"),
        )
        return result

    async def read_attr_and_wait(
        self,
        ieee: str,
        endpoint: Optional[int],
        cluster: str,
        attribute: str,
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        if not self.is_connected():
            raise HubConnectionError()
        result = await self._client.read_attr_and_wait(
            ieee, endpoint, cluster, attribute, timeout
        )
        logger.info(
            "read_attr_wait_done",
            ieee=ieee,
            cluster=cluster,
            attribute=attribute,
            status=result.get("status"),
        )
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
                ep_list = d.get("endpoints", [])
                mapped.append(
                    {
                        "ieee": d.get("ieee_addr", ""),
                        "name": d.get("name") or "Zigbee Device",
                        "network_addr": d.get("network_addr"),
                        "endpoints": ep_list,
                        "online": d.get("online", True),
                        "last_seen_ms": d.get("last_seen_ms"),
                    }
                )
                logger.info(
                    "device_parsed_from_hub",
                    ieee=d.get("ieee_addr"),
                    name=d.get("name"),
                    endpoint_count=len(ep_list),
                    endpoints=ep_list,
                    online=d.get("online", True),
                    raw_device_keys=list(d.keys()),
                )
            self._devices = mapped
            self._spawn_background(self._sync_devices(mapped))

        if evt == "command_status":
            self._spawn_background(self._handle_command_status(data))

        if evt == "ping_result":
            self._spawn_background(self._handle_ping_result(data))

        if evt and evt.endswith("_ack"):
            self._spawn_background(self._handle_ack(data, evt))

        if evt == "state_change":
            self._spawn_background(self._handle_state_change(data))

        # Publish domain events for downstream consumers (scheduler, SSE, etc.)
        if evt in (
            "device_joined",
            "device_left",
            "state_change",
            "command_failed",
            "command_status",
            "ping_result",
        ):
            self._spawn_background(
                self._event_bus.publish("device_event", {"event": evt, "data": data})
            )

        self._spawn_background(
            self._event_bus.publish("hub_message", {"data": data})
        )

    async def _sync_devices(self, devices: List[Dict[str, Any]]) -> None:
        """Persist or update device topology in the database.

        The in-memory cache is merged rather than replaced, so attribute state
        received via ``state_change`` while the sync is running is preserved.
        """
        seen_ieees = {
            d.get("ieee_addr") or d.get("ieee", "")
            for d in devices
            if d.get("ieee_addr") or d.get("ieee")
        }
        all_devices = await self._state_manager.sync_topology(devices)
        self._devices = self._merge_device_list(self._devices, all_devices, seen_ieees)

    def _merge_device_list(
        self,
        cached: List[Dict[str, Any]],
        db_devices: List[Dict[str, Any]],
        seen_ieees: set[str],
) -> List[Dict[str, Any]]:
        """Merge DB topology into the cached list, preserving cached state."""
        merged: List[Dict[str, Any]] = []
        for dev in db_devices:
            ieee = dev["ieee"]
            cached_dev = next((d for d in cached if d.get("ieee") == ieee), None)
            merged_dev = dict(dev)
            if cached_dev and cached_dev.get("state"):
                # Preserve potentially fresher in-memory state.
                merged_dev["state"] = cached_dev["state"]
            merged.append(merged_dev)

        # Remove devices no longer reported by the hub.
        merged = [d for d in merged if d["ieee"] in seen_ieees]
        return merged

    async def _handle_ping_result(self, data: Dict[str, Any]) -> None:
        """Update online state from a firmware ping_result event."""
        ieee = data.get("ieee")
        online = bool(data.get("online", False))
        if not ieee:
            return
        await self._state_manager.set_device_online(ieee, online)

    async def _handle_command_status(self, data: Dict[str, Any]) -> None:
        """Delegate command status events to the state manager."""
        status = data.get("status")
        ieee = data.get("ieee_addr")
        cluster = data.get("cluster")
        correlation_id = data.get("correlation_id")
        await self._state_manager.on_command_status(
            correlation_id, status, ieee, cluster
        )

    async def _handle_ack(self, data: Dict[str, Any], evt: str) -> None:
        """Handle *_ack events (on_ack, off_ack, toggle_ack, level_ack, etc.)."""
        correlation_id = data.get("correlation_id")
        ok = data.get("ok", False)
        error = data.get("error")
        if not correlation_id:
            return
        await self._state_manager.on_ack(correlation_id, bool(ok), error)
        logger.info("ack_received", evt=evt, correlation_id=correlation_id, ok=ok)

    async def _handle_state_change(self, data: Dict[str, Any]) -> None:
        """Merge attribute reports into device state."""
        ieee = data.get("ieee_addr")
        if not ieee:
            return

        # A state_change is a sign of life.
        await self._state_manager.set_device_online(ieee, True)

        changes = data.get("changes", [])
        if changes:
            for change in changes:
                cluster_hex = change.get("cluster", "")
                attr_hex = change.get("attribute", "")
                value = change.get("value")
                endpoint_id = change.get("endpoint")
                try:
                    cluster_id = (
                        int(cluster_hex, 16)
                        if isinstance(cluster_hex, str) and cluster_hex.startswith("0x")
                        else int(cluster_hex)
                    )
                    attr_id = (
                        int(attr_hex, 16)
                        if isinstance(attr_hex, str) and attr_hex.startswith("0x")
                        else int(attr_hex)
                    )
                except (ValueError, TypeError):
                    continue
                # Xiaomi private cluster reports are liveness noise.
                if cluster_id == 0xFCC0:
                    continue
                await self._state_manager.apply_state_change(
                    ieee, endpoint_id, cluster_id, attr_id, value
                )
        else:
            # Old flat format fallback
            endpoint_id = data.get("endpoint")
            cluster_id = data.get("cluster_id")
            attr_id = data.get("attr_id")
            value = data.get("value")
            if cluster_id is not None and attr_id is not None and value is not None:
                if cluster_id == 0xFCC0:
                    return
                await self._state_manager.apply_state_change(
                    ieee, endpoint_id, cluster_id, attr_id, value
                )

    def _update_cached_device_state(
        self, ieee: str, endpoint_id: Optional[int], updates: dict
    ) -> None:
        """Update the in-memory device cache (used by graph executors)."""
        for dev in self._devices:
            if dev.get("ieee") == ieee:
                if "state" not in dev:
                    dev["state"] = {}
                ep_key = str(endpoint_id or "1")
                if ep_key not in dev["state"]:
                    dev["state"][ep_key] = {}
                dev["state"][ep_key].update(updates)
                break

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

    def _start_ping_loop(self) -> None:
        """Start the periodic liveness ping loop."""
        self._stop_ping.clear()
        if self._ping_task is not None and not self._ping_task.done():
            return
        self._ping_task = asyncio.create_task(self._ping_loop())

    def _stop_ping_loop(self) -> None:
        """Signal the ping loop to stop."""
        self._stop_ping.set()
        if self._ping_task is not None and not self._ping_task.done():
            self._ping_task.cancel()

    async def _ping_loop(self) -> None:
        """Periodically ping all known devices to detect offline state."""
        try:
            while not self._stop_ping.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_ping.wait(), timeout=PING_INTERVAL_SECONDS
                    )
                except asyncio.TimeoutError:
                    pass
                if self._stop_ping.is_set() or not self.is_connected():
                    break
                await self._ping_all_devices()
        except asyncio.CancelledError:
            logger.debug("ping_loop_cancelled")
        except Exception:
            logger.exception("ping_loop_failed")

    async def ping_device(self, ieee: str) -> Dict[str, Any]:
        """Send a single liveness ping to a device and track the result."""
        correlation_id = self._new_correlation_id()
        result = await self._client.ping(ieee, correlation_id)
        self._spawn_background(self._wait_ping_result(ieee, correlation_id))
        return result

    async def _ping_all_devices(self) -> None:
        """Send a ping to every cached device and update liveness state."""
        if not self.is_connected():
            return
        devices = list(self._devices)
        logger.info("ping_all_devices_start", count=len(devices))
        for i, dev in enumerate(devices):
            ieee = dev.get("ieee")
            if not ieee:
                continue
            try:
                result = await self._client.ping(ieee, self._new_correlation_id())
                correlation_id = result.get("correlation_id")
                if correlation_id:
                    self._spawn_background(
                        self._wait_ping_result(ieee, correlation_id)
                    )
            except Exception:
                logger.exception("ping_send_failed", ieee=ieee)
            # Stagger pings so the Zigbee network is not flooded.
            if i < len(devices) - 1:
                await asyncio.sleep(0.5)

    async def _wait_ping_result(self, ieee: str, correlation_id: str) -> None:
        """Wait for the firmware ping_result event and update the DB."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._client._protocol.register_future(correlation_id, future)
        try:
            data = await asyncio.wait_for(future, timeout=PING_TIMEOUT_SECONDS)
            status = data.get("status")
            if status:
                # Resolved by command_status (emitted before ping_result)
                online = status in ("completed", "delivered")
            else:
                online = bool(data.get("online", False))
            await self._state_manager.set_device_online(ieee, online)
        except asyncio.TimeoutError:
            logger.info("ping_wait_timeout", ieee=ieee, correlation_id=correlation_id)
            await self._state_manager.set_device_online(ieee, False)
        finally:
            self._client._protocol._resolve_future(correlation_id, {})

    def _new_correlation_id(self) -> str:
        """Generate a short correlation id for hub commands."""
        import uuid

        return f"ping-{uuid.uuid4().hex[:12]}"

    def _update_cached_online(self, ieee: str, online: bool) -> None:
        """Update the in-memory device cache online flag."""
        for dev in self._devices:
            if dev.get("ieee") == ieee:
                dev["online"] = online
                break
