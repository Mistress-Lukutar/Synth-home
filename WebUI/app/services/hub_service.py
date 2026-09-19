"""Business-logic service wrapper around HubClient."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
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
PENDING_COMMAND_TTL_SECONDS = 60

# Per-device command queue: retries and pacing.
COMMAND_RETRY_MAX = 3
COMMAND_RETRY_BACKOFF_S = (0.5, 2.0)
# Wait for a terminal firmware outcome before retrying. Level/color ramp for
# up to ~15 s in the tracker, instant commands time out at 5 s.
COMMAND_RESOLVE_TIMEOUT_S = {"level": 20.0, "color": 20.0, "color_ct": 20.0}
COMMAND_RESOLVE_TIMEOUT_DEFAULT_S = 10.0
# Minimum gap between read_attr sends (the poll storm mitigation).
READ_SEND_MIN_GAP_S = 0.03


@dataclass
class QueuedCommand:
    """One device command waiting in a per-device FIFO."""

    ieee: str
    action: str
    correlation_id: str
    params: Optional[Dict[str, Any]] = None
    endpoint: Optional[int] = None
    attempt: int = 1
    future: Optional[asyncio.Future] = field(default=None, repr=False)


class HubService:
    """Async business-logic wrapper for hub communication.

    This class owns the in-memory device cache used by graph executors and the
    API. All persisted state updates are delegated to
    :class:`DeviceStateManager`, which is the single authority for
    ``Device.state`` and ``Device.online``.

    Device commands go through a per-device FIFO worker: sends to one device
    keep their issue order (``on`` -> ``level`` -> ``color`` scene fan-outs),
    and failed attempts are retried with backoff using the same correlation
    id, so the id returned to the caller stays valid across retries.

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
        # State changes are applied by a single ordered worker: spawning one
        # task per event let rapid reports during a dimming ramp (e.g. 110
        # then 128) race for the per-device lock and leave the older value
        # persisted last.
        self._state_events: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._state_worker: Optional[asyncio.Task] = None
        # Per-device command FIFOs and their consumer tasks.
        self._device_queues: Dict[str, asyncio.Queue[QueuedCommand]] = {}
        # Outbound read pacing state.
        self._read_pace_lock = asyncio.Lock()
        self._last_read_ts = float("-inf")
        # Traffic counters for the periodic summary log.
        self._stats = {
            "commands_sent": 0,
            "reads_sent": 0,
            "events_received": 0,
            "state_changes": 0,
            "hub_errors": 0,
        }

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
        # Drop queued commands: a fresh connect re-syncs everything anyway.
        self._device_queues.clear()
        await self._cancel_background_tasks()
        # Drop state changes that were queued but never applied; a fresh
        # connect re-syncs everything from the hub anyway.
        while not self._state_events.empty():
            self._state_events.get_nowait()
        await self._client.disconnect()
        await self._state_manager.mark_all_devices_offline()
        await self._event_bus.publish("hub_disconnected", {})

    # ------------------------------------------------------------------
    # Command path: per-device FIFO with retries
    # ------------------------------------------------------------------

    async def send_command(
        self, ieee: str, action: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Queue a device command. Returns 202-style tracking info at once.

        The correlation_id is generated here and reused for every retry, so
        callers (HTTP clients, frontend pending maps) track one id per
        logical command.
        """
        if not self.is_connected():
            raise HubConnectionError()
        correlation_id = f"corr-{uuid.uuid4().hex[:12]}"
        endpoint = (params or {}).get("endpoint")
        queue = self._device_queues.get(ieee)
        if queue is None:
            queue = asyncio.Queue()
            self._device_queues[ieee] = queue
            self._spawn_background(self._device_worker(ieee))
        queue.put_nowait(
            QueuedCommand(
                ieee=ieee,
                action=action,
                correlation_id=correlation_id,
                params=dict(params) if params else None,
                endpoint=endpoint,
            )
        )
        self._stats["commands_sent"] += 1
        logger.info(
            "command_queued",
            ieee=ieee,
            action=action,
            endpoint=endpoint,
            correlation_id=correlation_id,
            queued=self._device_queues[ieee].qsize(),
        )
        return {"correlation_id": correlation_id, "status": "pending"}

    async def _device_worker(self, ieee: str) -> None:
        """Consume one device's command FIFO in order, with retries."""
        queue = self._device_queues.get(ieee)
        if queue is None:
            return
        while True:
            cmd = await queue.get()
            try:
                await self._process_command(cmd)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "device_command_crashed", ieee=ieee, action=cmd.action
                )
            finally:
                queue.task_done()

    async def _process_command(self, cmd: QueuedCommand) -> None:
        """Send one command, retrying terminal failures with backoff."""
        timeout = COMMAND_RESOLVE_TIMEOUT_S.get(
            cmd.action, COMMAND_RESOLVE_TIMEOUT_DEFAULT_S
        )
        for attempt in range(1, COMMAND_RETRY_MAX + 1):
            if not self.is_connected():
                logger.warning(
                    "command_aborted_disconnected",
                    ieee=cmd.ieee,
                    action=cmd.action,
                    correlation_id=cmd.correlation_id,
                )
                return

            params = dict(cmd.params) if cmd.params else {}
            # A lamp transitioning from off ignores plain MoveToLevel; when
            # the cache says the device is off (or unknown), send
            # MoveToLevelWithOnOff so the level applies atomically.
            if cmd.action == "level" and cmd.endpoint is not None:
                if not self._cached_on(cmd.ieee, cmd.endpoint):
                    params.setdefault("with_on_off", True)

            self._state_manager.register_command(
                cmd.correlation_id, cmd.ieee, cmd.endpoint, cmd.action
            )
            try:
                await self._client.send_command(
                    cmd.ieee,
                    cmd.action,
                    params,
                    correlation_id=cmd.correlation_id,
                )
            except Exception as exc:
                logger.warning(
                    "command_send_failed",
                    ieee=cmd.ieee,
                    action=cmd.action,
                    attempt=attempt,
                    error=str(exc),
                )
                self._state_manager.fail_pending(cmd.correlation_id, "send_failed")

            outcome = await self._state_manager.wait_resolution(
                cmd.correlation_id, timeout
            )
            result = (outcome or {}).get("outcome")
            if result in ("resolved_by_state_change", "delivered", "completed"):
                logger.info(
                    "command_resolved",
                    ieee=cmd.ieee,
                    action=cmd.action,
                    attempt=attempt,
                    outcome=result,
                    correlation_id=cmd.correlation_id,
                )
                return

            if result == "expired":
                # TTL sweep already gave up on this id; stop retrying.
                return

            logger.info(
                "command_attempt_failed",
                ieee=cmd.ieee,
                action=cmd.action,
                attempt=attempt,
                outcome=result or "no_response",
                correlation_id=cmd.correlation_id,
            )
            if attempt < COMMAND_RETRY_MAX:
                backoff = COMMAND_RETRY_BACKOFF_S[min(attempt - 1, len(COMMAND_RETRY_BACKOFF_S) - 1)]
                await asyncio.sleep(backoff)

        logger.warning(
            "command_failed_final",
            ieee=cmd.ieee,
            action=cmd.action,
            correlation_id=cmd.correlation_id,
        )

    def _cached_on(self, ieee: str, endpoint: int) -> bool:
        """True when the cached state says the endpoint is on."""
        for dev in self._devices:
            if dev.get("ieee") == ieee:
                state = dev.get("state") or {}
                return bool((state.get(str(endpoint)) or {}).get("on"))
        return False

    # ------------------------------------------------------------------
    # Read path: paced multi- and single-attribute reads
    # ------------------------------------------------------------------

    async def _pace_read_send(self) -> None:
        """Serialize outbound reads with a minimum gap between sends."""
        async with self._read_pace_lock:
            now = time.monotonic()
            wait = READ_SEND_MIN_GAP_S - (now - self._last_read_ts)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_read_ts = time.monotonic()

    async def read_attr(
        self, ieee: str, endpoint: Optional[int], cluster: str, attribute: str
    ) -> Dict[str, Any]:
        if not self.is_connected():
            raise HubConnectionError()
        await self._pace_read_send()
        result = await self._client.read_attr(ieee, endpoint, cluster, attribute)
        self._stats["reads_sent"] += 1
        logger.debug(
            "read_attr_sent",
            ieee=ieee,
            endpoint=endpoint,
            cluster=cluster,
            attribute=attribute,
            correlation_id=result.get("correlation_id"),
        )
        return result

    async def read_attrs(
        self, ieee: str, endpoint: Optional[int], cluster: str, attributes: List[str]
    ) -> Dict[str, Any]:
        """Read several attributes of one cluster in a single ZCL frame."""
        if not self.is_connected():
            raise HubConnectionError()
        await self._pace_read_send()
        result = await self._client.read_attrs(ieee, endpoint, cluster, attributes)
        self._stats["reads_sent"] += 1
        logger.debug(
            "read_attrs_sent",
            ieee=ieee,
            endpoint=endpoint,
            cluster=cluster,
            attributes=attributes,
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
        await self._pace_read_send()
        result = await self._client.read_attr_and_wait(ieee, endpoint, cluster, attribute, timeout)
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
        try:
            devices = await self._client.fetch_devices()
        except Exception:
            # Serial write failed mid-recovery; the reader will restore the
            # link. Report "no data" so callers fall back to cached/DB state.
            logger.exception("fetch_devices_send_failed")
            return []
        if not devices:
            logger.warning("fetch_devices_empty_or_timeout")
        else:
            await self._sync_devices(devices)
        return devices

    def get_cached_devices(self) -> List[Dict[str, Any]]:
        return list(self._devices)

    # ------------------------------------------------------------------
    # Inbound hub messages
    # ------------------------------------------------------------------

    def _on_hub_message(self, data: Dict[str, Any]) -> None:
        """Handle incoming messages from the hub (called from reader task via callback)."""
        evt = data.get("evt") or data.get("event")
        self._stats["events_received"] += 1

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
                logger.debug(
                    "device_parsed_from_hub",
                    ieee=d.get("ieee_addr"),
                    name=d.get("name"),
                    endpoint_count=len(ep_list),
                    online=d.get("online", True),
                )
            self._devices = mapped
            self._spawn_background(self._sync_devices(mapped))

        if evt == "command_status":
            self._spawn_background(self._handle_command_status(data))

        if evt == "ping_result":
            self._spawn_background(self._handle_ping_result(data))

        if evt and evt.endswith("_ack"):
            self._spawn_background(self._handle_ack(data, evt))

        if evt == "command_failed":
            self._spawn_background(self._handle_command_failed(data))

        if evt == "error":
            self._spawn_background(self._handle_hub_error(data))

        if evt == "state_change":
            self._stats["state_changes"] += 1
            # Must be applied in arrival order (see _state_events above);
            # fire-and-forget tasks here would reorder ramp reports.
            self._ensure_state_worker()
            self._state_events.put_nowait(data)

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

        self._spawn_background(self._event_bus.publish("hub_message", {"data": data}))

    async def _handle_hub_error(self, data: Dict[str, Any]) -> None:
        """React to firmware ``error`` events instead of ignoring them.

        ``invalid_json`` / ``busy`` mean a command line was lost before it
        executed; resolve the matching (or oldest) pending command so its
        device worker retries it, instead of hanging until the TTL sweep.
        """
        message = data.get("message", "unknown")
        self._stats["hub_errors"] += 1
        correlation_id = data.get("correlation_id")
        logger.warning(
            "hub_error_event", message=message, correlation_id=correlation_id
        )
        if message not in ("invalid_json", "busy"):
            return
        if correlation_id:
            self._state_manager.fail_pending(correlation_id, message)
        else:
            oldest = self._state_manager.fail_oldest_pending(message)
            if oldest:
                logger.info("oldest_pending_failed", correlation_id=oldest, reason=message)

    async def _handle_command_failed(self, data: Dict[str, Any]) -> None:
        """Resolve a pending command the firmware rejected outright."""
        correlation_id = data.get("correlation_id")
        if not correlation_id:
            return
        self._state_manager.fail_pending(correlation_id, "command_failed")

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
        await self._state_manager.on_command_status(correlation_id, status, ieee, cluster)

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

    def _ensure_state_worker(self) -> None:
        """Start the ordered state_change consumer (idempotent)."""
        if self._state_worker is None or self._state_worker.done():
            self._state_worker = asyncio.create_task(self._state_worker_loop())
            self._bg_tasks.add(self._state_worker)
            self._state_worker.add_done_callback(self._bg_tasks.discard)

    async def _state_worker_loop(self) -> None:
        """Apply state_change events strictly in arrival order."""
        while True:
            data = await self._state_events.get()
            try:
                await self._handle_state_change(data)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("state_change_apply_failed")

    async def _cancel_background_tasks(self) -> None:
        """Cancel any outstanding background tasks."""
        if not self._bg_tasks:
            return
        for task in self._bg_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        self._bg_tasks.clear()

    # ------------------------------------------------------------------
    # Liveness ping loop
    # ------------------------------------------------------------------

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
        """Periodically ping all known devices to detect offline state.

        The loop survives transient serial outages: HubClient recovers the
        port on its own, so a down cycle is skipped, not fatal. Only a user
        disconnect (stop event) or task cancellation ends the loop.
        """
        try:
            while not self._stop_ping.is_set():
                try:
                    await asyncio.wait_for(self._stop_ping.wait(), timeout=PING_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    pass
                if self._stop_ping.is_set():
                    break
                if not self.is_connected():
                    logger.info("ping_cycle_skipped_not_connected")
                    continue
                try:
                    self._log_traffic_summary()
                    # Drop pending commands whose firmware event was lost.
                    expired = self._state_manager.sweep_expired(PENDING_COMMAND_TTL_SECONDS)
                    if expired:
                        logger.info("pending_commands_swept", count=expired)
                    await self._ping_all_devices()
                except Exception:
                    logger.exception("ping_cycle_failed")
        except asyncio.CancelledError:
            logger.debug("ping_loop_cancelled")
        except Exception:
            logger.exception("ping_loop_failed")

    def _log_traffic_summary(self) -> None:
        """One summary line per ping cycle so loss is countable (Phase 0)."""
        stats = dict(self._stats)
        logger.info("hub_traffic_summary", period_s=PING_INTERVAL_SECONDS, **stats)
        for key in self._stats:
            self._stats[key] = 0

    async def ping_device(self, ieee: str) -> Dict[str, Any]:
        """Send a single liveness ping to a device and track the result."""
        correlation_id = self._new_correlation_id()
        # Register the response future BEFORE sending: a fast reply would
        # otherwise be dropped by the protocol handler and look like a timeout.
        future = self._register_ping_future(correlation_id)
        try:
            await self._client.ping(ieee, correlation_id)
        except Exception:
            logger.exception("ping_send_failed", ieee=ieee)
            self._client._protocol._resolve_future(correlation_id, {})
            raise
        self._spawn_background(self._wait_ping_result(ieee, correlation_id, future))
        return {"correlation_id": correlation_id, "status": "pending"}

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
                correlation_id = self._new_correlation_id()
                # Register the response future BEFORE sending (see ping_device).
                future = self._register_ping_future(correlation_id)
                await self._client.ping(ieee, correlation_id)
                self._spawn_background(self._wait_ping_result(ieee, correlation_id, future))
            except Exception:
                logger.exception("ping_send_failed", ieee=ieee)
            # Stagger pings so the Zigbee network is not flooded.
            if i < len(devices) - 1:
                await asyncio.sleep(0.5)

    def _register_ping_future(self, correlation_id: str) -> asyncio.Future:
        """Create and register the future that the ping reply will resolve."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._client._protocol.register_future(correlation_id, future)
        return future

    async def _wait_ping_result(
        self, ieee: str, correlation_id: str, future: asyncio.Future
    ) -> None:
        """Wait for the firmware ping_result event and update the DB."""
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
        return f"ping-{uuid.uuid4().hex[:12]}"

    def _update_cached_online(self, ieee: str, online: bool) -> None:
        """Update the in-memory device cache online flag."""
        for dev in self._devices:
            if dev.get("ieee") == ieee:
                dev["online"] = online
                break
