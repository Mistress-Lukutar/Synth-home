"""Business-logic service wrapper around HubClient."""

import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import structlog

from app.db import async_session
from app.exceptions import HubConnectionError
from app.repositories.device import DeviceRepository
from app.services.hub_client import HubClient
from app.services.protocol import ProtocolHandler
from app.services.event_bus import EventBus
from app.services.commands import DeviceCommand

logger = structlog.get_logger(__name__)

PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 3.0


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
        self._client = client or HubClient(ProtocolHandler(), event_bus=event_bus)
        self._client.set_on_message(self._on_hub_message)
        self._devices: List[Dict[str, Any]] = []
        self._bg_tasks: set[asyncio.Task] = set()
        self._ping_task: Optional[asyncio.Task] = None
        self._stop_ping = asyncio.Event()

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
        await self._mark_all_devices_offline()
        await self._event_bus.publish("hub_disconnected", {})

    async def send_command(
        self, ieee: str, action: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not self.is_connected():
            raise HubConnectionError()
        result = await self._client.send_command(ieee, action, params)
        logger.info("command_sent", ieee=ieee, action=action, correlation_id=result.get("correlation_id"))
        return result

    async def read_attr(
        self, ieee: str, endpoint: Optional[int], cluster: str, attribute: str
    ) -> Dict[str, Any]:
        if not self.is_connected():
            raise HubConnectionError()
        result = await self._client.read_attr(ieee, endpoint, cluster, attribute)
        logger.info("read_attr_sent", ieee=ieee, endpoint=endpoint, cluster=cluster, attribute=attribute, correlation_id=result.get("correlation_id"))
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
        result = await self._client.read_attr_and_wait(ieee, endpoint, cluster, attribute, timeout)
        logger.info("read_attr_wait_done", ieee=ieee, cluster=cluster, attribute=attribute, status=result.get("status"))
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
            ieee = data.get("ieee_addr")
            if ieee:
                self._spawn_background(self._set_device_online(ieee, True))
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
        Mark devices not present in the hub list as offline."""
        async with async_session() as session:
            repo = DeviceRepository(session)
            seen_ieees = set()
            for d in devices:
                ieee = d.get("ieee_addr") or d.get("ieee", "")
                if not ieee:
                    logger.warning("sync_devices_skip_no_ieee", device=d)
                    continue
                seen_ieees.add(ieee)
                endpoints = d.get("endpoints", [])
                online = d.get("online", True)
                last_seen_ms = d.get("last_seen_ms")
                logger.info(
                    "device_upsert_db",
                    ieee=ieee,
                    network_addr=d.get("network_addr"),
                    endpoint_count=len(endpoints),
                    endpoints=endpoints,
                    online=online,
                )
                upsert_kwargs: Dict[str, Any] = {
                    "network_addr": d.get("network_addr"),
                    "endpoints": endpoints,
                    "online": online,
                }
                if last_seen_ms:
                    upsert_kwargs["last_seen"] = datetime.fromtimestamp(
                        last_seen_ms / 1000.0, tz=timezone.utc
                    )
                await repo.upsert(ieee, **upsert_kwargs)
            # Mark missing devices as offline
            all_devices = await repo.list_with_aliases()
            for dev in all_devices:
                if dev["ieee"] not in seen_ieees:
                    device = await repo.get_by_ieee(dev["ieee"])
                    if device and device.online:
                        device.online = False
                        logger.info("device_marked_offline", ieee=dev["ieee"])
            await session.commit()
            self._devices = all_devices

    async def _handle_ping_result(self, data: Dict[str, Any]) -> None:
        """Update online state from a firmware ping_result event."""
        ieee = data.get("ieee")
        online = bool(data.get("online", False))
        if not ieee:
            return
        await self._set_device_online(ieee, online)

    async def _handle_command_status(self, data: Dict[str, Any]) -> None:
        """Update device state in DB based on command_status events."""
        status = data.get("status")
        ieee = data.get("ieee_addr")
        cluster_id = data.get("cluster_id")
        attr_id = data.get("attr_id")
        endpoint_id = data.get("endpoint")

        if status in ("timeout", "failed") and ieee:
            await self._set_device_online(ieee, False)
        elif status in ("completed", "delivered") and ieee:
            await self._set_device_online(ieee, True)

        if not ieee or not cluster_id:
            return
        try:
            async with async_session() as session:
                repo = DeviceRepository(session)
                device = await repo.get_by_ieee(ieee)
                if not device:
                    return
                state = dict(device.state) if device.state else {}
                ep_key = str(endpoint_id or "1")
                if ep_key not in state:
                    state[ep_key] = {}
                if status == "completed" and cluster_id == 6 and attr_id == 0:
                    # OnOff cluster — determine on/off from context or payload
                    value = data.get("value")
                    if value is not None:
                        state[ep_key]["on"] = bool(value)
                    else:
                        # Fallback: infer from command if value not present
                        pass
                elif status == "completed" and cluster_id == 8:
                    value = data.get("value")
                    if value is not None:
                        state[ep_key]["level"] = int(value)
                elif status == "completed" and cluster_id == 768:
                    value = data.get("value")
                    if value is not None:
                        state[ep_key]["color"] = value
                device.state = state
                await session.commit()
        except Exception:
            logger.exception("command_status_db_update_failed")

    def _update_cached_device_state(self, ieee: str, endpoint_id, updates: dict) -> None:
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

    async def _handle_ack(self, data: Dict[str, Any], evt: str) -> None:
        """Handle *_ack events (on_ack, off_ack, toggle_ack, level_ack, color_ack, etc.)."""
        ieee = data.get("ieee")
        ok = data.get("ok")
        value = data.get("value")
        endpoint_id = data.get("endpoint")
        if not ieee:
            return
        action = evt.replace("_ack", "")
        try:
            async with async_session() as session:
                repo = DeviceRepository(session)
                device = await repo.get_by_ieee(ieee)
                if not device:
                    return
                state = dict(device.state) if device.state else {}
                ep_key = str(endpoint_id or "1")
                if ep_key not in state:
                    state[ep_key] = {}

                if action in (DeviceCommand.ON, DeviceCommand.OFF, DeviceCommand.TOGGLE):
                    if ok is not None:
                        if action == DeviceCommand.ON:
                            state[ep_key]["on"] = bool(ok)
                        elif action == DeviceCommand.OFF:
                            state[ep_key]["on"] = not bool(ok)
                        elif action == DeviceCommand.TOGGLE:
                            state[ep_key]["on"] = not state[ep_key].get("on", False)
                elif action == DeviceCommand.LEVEL:
                    if value is not None:
                        state[ep_key]["level"] = int(value)
                    elif ok is not None:
                        state[ep_key]["level"] = state[ep_key].get("level", 128)
                elif action == DeviceCommand.COLOR:
                    if value is not None:
                        state[ep_key]["color"] = value
                elif action == DeviceCommand.READ_ATTR:
                    cluster_id = data.get("cluster_id")
                    attr_id = data.get("attr_id")
                    val = data.get("value")
                    if cluster_id is None and attr_id is None:
                        cluster_hex = data.get("cluster", "")
                        attr_hex = data.get("attribute", "")
                        try:
                            cluster_id = int(cluster_hex, 16) if isinstance(cluster_hex, str) and cluster_hex.startswith("0x") else int(cluster_hex) if cluster_hex else None
                            attr_id = int(attr_hex, 16) if isinstance(attr_hex, str) and attr_hex.startswith("0x") else int(attr_hex) if attr_hex else None
                        except (ValueError, TypeError):
                            pass
                    if cluster_id is not None and attr_id is not None and val is not None:
                        await self._update_device_state(ieee, endpoint_id, cluster_id, attr_id, val)

                device.state = state
                await session.commit()
                logger.info("ack_state_updated", ieee=ieee, action=action, ep=ep_key, ok=ok, value=value)

            # Update in-memory cache for graph executors
            if action in (DeviceCommand.ON, DeviceCommand.OFF, DeviceCommand.TOGGLE) and ok is not None:
                if action == DeviceCommand.TOGGLE:
                    cached_on = (device.state or {}).get(ep_key, {}).get("on", False)
                else:
                    cached_on = bool(ok) if action == DeviceCommand.ON else not bool(ok)
                self._update_cached_device_state(ieee, endpoint_id, {"on": cached_on})
            elif action == DeviceCommand.LEVEL and value is not None:
                self._update_cached_device_state(ieee, endpoint_id, {"level": int(value)})
            elif action == DeviceCommand.COLOR and value is not None:
                self._update_cached_device_state(ieee, endpoint_id, {"color": value})
        except Exception:
            logger.exception("ack_db_update_failed")

    async def _handle_state_change(self, data: Dict[str, Any]) -> None:
        """Merge attribute report into device state. Handles both old format and new changes[] array."""
        ieee = data.get("ieee_addr")
        if not ieee:
            return

        changes = data.get("changes", [])
        if changes:
            # New format with changes array
            for change in changes:
                cluster_hex = change.get("cluster", "")
                attr_hex = change.get("attribute", "")
                value = change.get("value")
                endpoint_id = change.get("endpoint")
                try:
                    cluster_id = int(cluster_hex, 16) if isinstance(cluster_hex, str) and cluster_hex.startswith("0x") else int(cluster_hex)
                    attr_id = int(attr_hex, 16) if isinstance(attr_hex, str) and attr_hex.startswith("0x") else int(attr_hex)
                except (ValueError, TypeError):
                    continue
                # Xiaomi private cluster reports are liveness noise.
                if cluster_id == 0xFCC0:
                    continue
                await self._update_device_state(ieee, endpoint_id, cluster_id, attr_id, value)
        else:
            # Old flat format
            endpoint_id = data.get("endpoint")
            cluster_id = data.get("cluster_id")
            attr_id = data.get("attr_id")
            value = data.get("value")
            if cluster_id is not None and attr_id is not None and value is not None:
                if cluster_id == 0xFCC0:
                    return
                await self._update_device_state(ieee, endpoint_id, cluster_id, attr_id, value)

    async def _update_device_state(self, ieee: str, endpoint_id: Optional[int], cluster_id: int, attr_id: int, value: Any) -> None:
        try:
            async with async_session() as session:
                repo = DeviceRepository(session)
                device = await repo.get_by_ieee(ieee)
                if not device:
                    return
                state = dict(device.state) if device.state else {}
                ep_key = str(endpoint_id or "1")
                if ep_key not in state:
                    state[ep_key] = {}
                cached_updates = {}
                if cluster_id == 6 and attr_id == 0:
                    state[ep_key]["on"] = bool(value)
                    cached_updates["on"] = bool(value)
                elif cluster_id == 8:
                    if attr_id == 0:
                        state[ep_key]["level"] = int(value)
                        cached_updates["level"] = int(value)
                    elif attr_id == 2:
                        state[ep_key]["level_min"] = int(value)
                        cached_updates["level_min"] = int(value)
                    elif attr_id == 3:
                        state[ep_key]["level_max"] = int(value)
                        cached_updates["level_max"] = int(value)
                elif cluster_id == 768:
                    if attr_id == 0:
                        state[ep_key]["hue"] = int(value)
                        cached_updates["hue"] = int(value)
                    elif attr_id == 1:
                        state[ep_key]["sat"] = int(value)
                        cached_updates["sat"] = int(value)
                    elif attr_id == 3:
                        state[ep_key]["x"] = int(value)
                        cached_updates["x"] = int(value)
                    elif attr_id == 4:
                        state[ep_key]["y"] = int(value)
                        cached_updates["y"] = int(value)
                    elif attr_id == 7:
                        state[ep_key]["ct"] = int(value)
                        cached_updates["ct"] = int(value)
                    elif attr_id == 8:
                        state[ep_key]["color_mode"] = int(value)
                        cached_updates["color_mode"] = int(value)
                    elif attr_id == 0x4002:
                        bitmask = int(value)
                        state[ep_key]["color_caps"] = {
                            "hs": bool(bitmask & 0x01),
                            "xy": bool(bitmask & 0x10),
                            "ct": bool(bitmask & 0x20),
                            "color_loop": bool(bitmask & 0x08),
                        }
                        cached_updates["color_caps"] = state[ep_key]["color_caps"]
                    elif attr_id == 0x400B:
                        state[ep_key]["ct_min"] = int(value)
                        cached_updates["ct_min"] = int(value)
                    elif attr_id == 0x400C:
                        state[ep_key]["ct_max"] = int(value)
                        cached_updates["ct_max"] = int(value)
                    else:
                        state[ep_key]["color"] = value
                        cached_updates["color"] = value
                device.state = state

                # Cache static attributes into endpoints JSON so the frontend
                # can skip re-reading them on the next page load.
                if cluster_id in (8, 768) and attr_id in (2, 3, 0x4002, 0x400B, 0x400C):
                    from sqlalchemy.orm import attributes

                    endpoints: list[dict] = list(device.endpoints or [])
                    ep_found = False
                    target_ep_id = endpoint_id or 1
                    for ep in endpoints:
                        if ep.get("id") == target_ep_id:
                            if cluster_id == 8:
                                if attr_id == 2:
                                    ep["level_min"] = int(value)
                                elif attr_id == 3:
                                    ep["level_max"] = int(value)
                            elif cluster_id == 768:
                                if attr_id == 0x4002:
                                    bitmask = int(value)
                                    ep["color_caps"] = {
                                        "hs": bool(bitmask & 0x01),
                                        "xy": bool(bitmask & 0x10),
                                        "ct": bool(bitmask & 0x20),
                                        "color_loop": bool(bitmask & 0x08),
                                    }
                                elif attr_id == 0x400B:
                                    ep["ct_min"] = int(value)
                                elif attr_id == 0x400C:
                                    ep["ct_max"] = int(value)
                            ep_found = True
                            break
                    if not ep_found:
                        new_ep: dict[str, Any] = {"id": target_ep_id}
                        if cluster_id == 8:
                            if attr_id == 2:
                                new_ep["level_min"] = int(value)
                            elif attr_id == 3:
                                new_ep["level_max"] = int(value)
                        elif cluster_id == 768:
                            if attr_id == 0x4002:
                                bitmask = int(value)
                                new_ep["color_caps"] = {
                                    "hs": bool(bitmask & 0x01),
                                    "xy": bool(bitmask & 0x10),
                                    "ct": bool(bitmask & 0x20),
                                    "color_loop": bool(bitmask & 0x08),
                                }
                            elif attr_id == 0x400B:
                                new_ep["ct_min"] = int(value)
                            elif attr_id == 0x400C:
                                new_ep["ct_max"] = int(value)
                        endpoints.append(new_ep)
                    device.endpoints = endpoints
                    attributes.flag_modified(device, "endpoints")
                    logger.info("endpoints_cache_updated", ieee=ieee, ep=target_ep_id, endpoints=endpoints)

                await session.commit()
                logger.info("device_state_updated", ieee=ieee, ep=ep_key, cluster=cluster_id, attr=attr_id, value=value)
            if cached_updates:
                self._update_cached_device_state(ieee, endpoint_id, cached_updates)
        except Exception:
            logger.exception("device_state_update_failed")

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
            await self._set_device_online(ieee, online)
        except asyncio.TimeoutError:
            logger.info("ping_wait_timeout", ieee=ieee, correlation_id=correlation_id)
            await self._set_device_online(ieee, False)
        finally:
            self._client._protocol._resolve_future(correlation_id, {})

    def _new_correlation_id(self) -> str:
        """Generate a short correlation id for hub commands."""
        import uuid

        return f"ping-{uuid.uuid4().hex[:12]}"

    async def _set_device_online(self, ieee: str, online: bool) -> None:
        """Update the online / last_seen fields for a single device."""
        try:
            async with async_session() as session:
                repo = DeviceRepository(session)
                device = await repo.get_by_ieee(ieee)
                if not device:
                    return
                device.online = online
                if online:
                    device.last_seen = datetime.now(timezone.utc)
                await session.commit()
                logger.info("device_online_updated", ieee=ieee, online=online)
                self._update_cached_online(ieee, online)
        except Exception:
            logger.exception("set_device_online_failed", ieee=ieee, online=online)

    async def _mark_all_devices_offline(self) -> None:
        """Mark every known device offline (used on disconnect)."""
        try:
            async with async_session() as session:
                repo = DeviceRepository(session)
                all_devices = await repo.list_with_aliases()
                for dev in all_devices:
                    device = await repo.get_by_ieee(dev["ieee"])
                    if device:
                        device.online = False
                await session.commit()
                for dev in all_devices:
                    self._update_cached_online(dev["ieee"], False)
                logger.info("all_devices_marked_offline", count=len(all_devices))
        except Exception:
            logger.exception("mark_all_offline_failed")

    def _update_cached_online(self, ieee: str, online: bool) -> None:
        """Update the in-memory device cache online flag."""
        for dev in self._devices:
            if dev.get("ieee") == ieee:
                dev["online"] = online
                break
