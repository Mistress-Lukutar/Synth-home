"""Single source of truth for persisted device state.

The firmware protocol separates command acceptance, command completion and
actual attribute values:

- ``*_ack`` events (``on_ack``, ``off_ack``, ``read_attr_ack``, ...) contain
  only ``ok``/``error`` and report whether the command was accepted by the
  Zigbee stack. They do **not** contain ``value``, ``endpoint``,
  ``cluster_id`` or ``attr_id``.
- ``command_status`` events report delivery/completion/timeout and contain
  ``status``, ``ieee`` and ``cluster`` (as a hex string). They do **not**
  contain ``value``, ``attr_id`` or ``endpoint``.
- ``state_change`` events are the only source of real attribute values.

Therefore this manager updates ``Device.state`` **only** when a
``state_change`` arrives or when an explicit read/write is confirmed by a
following ``state_change``. ``*_ack`` and ``command_status`` are tracked only
for command lifecycle / online status.
"""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import structlog
from sqlalchemy.orm import attributes

from app.db import async_session
from app.models.db_models import Device
from app.repositories.device import DeviceRepository

logger = structlog.get_logger(__name__)

_StateChangedCallback = Callable[[str, Optional[int], dict[str, Any]], None]
_OnlineChangedCallback = Callable[[str, bool], None]


class DeviceStateManager:
    """Central authority for device on/off/level/color state and liveness.

    All writes to ``Device.state`` go through this class. Callers that want to
    change a device must send a command through ``HubService`` and register the
    pending command here; the actual state update happens when the firmware
    reports a ``state_change``.
    """

    def __init__(
        self,
        on_state_changed: Optional[_StateChangedCallback] = None,
        on_online_changed: Optional[_OnlineChangedCallback] = None,
    ) -> None:
        self._on_state_changed = on_state_changed
        self._on_online_changed = on_online_changed
        self._pending_commands: dict[str, dict[str, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_callbacks(
        self,
        on_state_changed: Optional[_StateChangedCallback] = None,
        on_online_changed: Optional[_OnlineChangedCallback] = None,
    ) -> None:
        """Attach callbacks used to keep the in-memory cache in sync."""
        if on_state_changed is not None:
            self._on_state_changed = on_state_changed
        if on_online_changed is not None:
            self._on_online_changed = on_online_changed

    # ------------------------------------------------------------------
    # State changes - the only path that writes Device.state
    # ------------------------------------------------------------------

    async def apply_state_change(
        self,
        ieee: str,
        endpoint_id: Optional[int],
        cluster_id: int,
        attr_id: int,
        value: Any,
    ) -> None:
        """Persist an attribute report/read_attr response and update caches."""
        if not ieee:
            return

        async with self._device_lock(ieee):
            async with async_session() as session:
                repo = DeviceRepository(session)
                device = await repo.get_by_ieee(ieee)
                if not device:
                    logger.warning("state_change_unknown_device", ieee=ieee)
                    return

                # Deep-copy so SQLAlchemy detects the change when we assign
                # the mutated dict back to the JSON column.
                state: dict[str, dict[str, Any]] = (
                    copy.deepcopy(device.state) if device.state else {}
                )
                ep_key = self._endpoint_key(endpoint_id)
                if ep_key not in state:
                    state[ep_key] = {}

                cached_updates: dict[str, Any] = {}
                self._apply_attr_to_state(
                    state[ep_key], cluster_id, attr_id, value, cached_updates
                )
                device.state = state
                attributes.flag_modified(device, "state")

                self._cache_static_attr_in_endpoints(device, endpoint_id, cluster_id, attr_id, value)

                await session.commit()
                logger.info(
                    "device_state_updated",
                    ieee=ieee,
                    ep=ep_key,
                    cluster=cluster_id,
                    attr=attr_id,
                    value=value,
                )

        if cached_updates and self._on_state_changed:
            self._on_state_changed(ieee, endpoint_id, cached_updates)

        # A confirmed state change may satisfy a pending command.
        self._maybe_resolve_pending(ieee, endpoint_id, cluster_id, attr_id, value)

    # ------------------------------------------------------------------
    # Command lifecycle tracking
    # ------------------------------------------------------------------

    def register_command(
        self,
        correlation_id: str,
        ieee: str,
        endpoint: Optional[int],
        action: str,
    ) -> None:
        """Track a command that was just sent to the firmware."""
        if not correlation_id or not ieee:
            return
        self._pending_commands[correlation_id] = {
            "ieee": ieee,
            "endpoint": endpoint,
            "action": action,
            "registered_at": datetime.now(timezone.utc),
        }
        logger.info(
            "command_registered",
            correlation_id=correlation_id,
            ieee=ieee,
            endpoint=endpoint,
            action=action,
        )

    async def on_ack(
        self,
        correlation_id: str,
        ok: bool,
        error: Optional[str],
    ) -> None:
        """Handle a command acceptance ack from the firmware.

        The ack tells us whether the command was accepted by the Zigbee stack.
        It does **not** mean the device state has changed. We only drop failed
        commands from pending here; successful commands stay pending until a
        ``state_change`` or ``command_status`` resolves them.
        """
        pending = self._pending_commands.get(correlation_id)
        if not pending:
            return

        if not ok:
            self._pending_commands.pop(correlation_id, None)
            logger.warning(
                "command_ack_failed",
                correlation_id=correlation_id,
                ieee=pending["ieee"],
                action=pending["action"],
                error=error,
            )
        else:
            logger.info(
                "command_ack_ok",
                correlation_id=correlation_id,
                ieee=pending["ieee"],
                action=pending["action"],
            )

    async def on_command_status(
        self,
        correlation_id: Optional[str],
        status: str,
        ieee: Optional[str],
        cluster: Optional[str],
    ) -> None:
        """Handle a command_status event.

        Updates liveness only. The actual attribute value is applied later via
        ``apply_state_change``.
        """
        if status in ("timeout", "failed") and ieee:
            await self.set_device_online(ieee, False)
        elif status in ("completed", "delivered") and ieee:
            await self.set_device_online(ieee, True)

        if correlation_id:
            pending = self._pending_commands.get(correlation_id)
            if pending and status in ("completed", "delivered", "timeout", "failed"):
                self._pending_commands.pop(correlation_id, None)
                logger.info(
                    "command_resolved",
                    correlation_id=correlation_id,
                    status=status,
                    ieee=pending.get("ieee"),
                    action=pending.get("action"),
                )

    def get_pending_command(self, correlation_id: str) -> Optional[dict[str, Any]]:
        return self._pending_commands.get(correlation_id)

    def get_pending_for_device(
        self, ieee: str, endpoint: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Return pending commands for a device, optionally filtered by endpoint."""
        result = []
        for pending in self._pending_commands.values():
            if pending.get("ieee") != ieee:
                continue
            if endpoint is not None and pending.get("endpoint") != endpoint:
                continue
            result.append(pending)
        return result

    # ------------------------------------------------------------------
    # Online / liveness
    # ------------------------------------------------------------------

    async def set_device_online(self, ieee: str, online: bool) -> None:
        """Update the online flag and last_seen timestamp for a device."""
        if not ieee:
            return
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
        except Exception:
            logger.exception("set_device_online_failed", ieee=ieee, online=online)
            return

        if self._on_online_changed:
            self._on_online_changed(ieee, online)

    async def mark_all_devices_offline(self) -> None:
        """Mark every known device offline (used on hub disconnect)."""
        try:
            async with async_session() as session:
                repo = DeviceRepository(session)
                all_devices = await repo.list_with_aliases()
                for dev in all_devices:
                    device = await repo.get_by_ieee(dev["ieee"])
                    if device:
                        device.online = False
                await session.commit()
                logger.info("all_devices_marked_offline", count=len(all_devices))
        except Exception:
            logger.exception("mark_all_offline_failed")
            return

        if self._on_online_changed:
            for dev in all_devices:
                self._on_online_changed(dev["ieee"], False)

    # ------------------------------------------------------------------
    # Topology sync helpers
    # ------------------------------------------------------------------

    async def sync_topology(
        self, devices: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Persist device topology and return the merged device list.

        Existing ``Device.state`` is preserved. Devices not present in the hub
        list are marked offline.
        """
        async with async_session() as session:
            repo = DeviceRepository(session)
            seen_ieees: set[str] = set()
            for d in devices:
                ieee = d.get("ieee_addr") or d.get("ieee", "")
                if not ieee:
                    logger.warning("sync_topology_skip_no_ieee", device=d)
                    continue
                seen_ieees.add(ieee)
                upsert_kwargs: dict[str, Any] = {
                    "network_addr": d.get("network_addr"),
                    "endpoints": d.get("endpoints", []),
                    "online": d.get("online", True),
                }
                last_seen_ms = d.get("last_seen_ms")
                if last_seen_ms:
                    upsert_kwargs["last_seen"] = datetime.fromtimestamp(
                        last_seen_ms / 1000.0, tz=timezone.utc
                    )
                await repo.upsert(ieee, **upsert_kwargs)

            all_devices = await repo.list_with_aliases()
            for dev in all_devices:
                if dev["ieee"] not in seen_ieees:
                    device = await repo.get_by_ieee(dev["ieee"])
                    if device and device.online:
                        device.online = False
                        logger.info("device_marked_offline", ieee=dev["ieee"])
            await session.commit()
            return all_devices

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _device_lock(self, ieee: str) -> asyncio.Lock:
        if ieee not in self._locks:
            self._locks[ieee] = asyncio.Lock()
        return self._locks[ieee]

    @staticmethod
    def _endpoint_key(endpoint_id: Optional[int]) -> str:
        if endpoint_id is not None:
            return str(endpoint_id)
        logger.warning("state_change_missing_endpoint", fallback="1")
        return "1"

    @staticmethod
    def _apply_attr_to_state(
        ep_state: dict[str, Any],
        cluster_id: int,
        attr_id: int,
        value: Any,
        cached_updates: dict[str, Any],
    ) -> None:
        if cluster_id == 0x0006 and attr_id == 0x0000:
            ep_state["on"] = bool(value)
            cached_updates["on"] = bool(value)
        elif cluster_id == 0x0008:
            if attr_id == 0x0000:
                ep_state["level"] = int(value)
                cached_updates["level"] = int(value)
            elif attr_id == 0x0002:
                ep_state["level_min"] = int(value)
                cached_updates["level_min"] = int(value)
            elif attr_id == 0x0003:
                ep_state["level_max"] = int(value)
                cached_updates["level_max"] = int(value)
        elif cluster_id == 0x0300:
            if attr_id == 0x0000:
                ep_state["hue"] = int(value)
                cached_updates["hue"] = int(value)
            elif attr_id == 0x0001:
                ep_state["sat"] = int(value)
                cached_updates["sat"] = int(value)
            elif attr_id == 0x0003:
                ep_state["x"] = int(value)
                cached_updates["x"] = int(value)
            elif attr_id == 0x0004:
                ep_state["y"] = int(value)
                cached_updates["y"] = int(value)
            elif attr_id == 0x0007:
                ep_state["ct"] = int(value)
                cached_updates["ct"] = int(value)
            elif attr_id == 0x0008:
                mode_val = int(value)
                mode = "hs" if mode_val == 0 else "xy" if mode_val == 1 else "ct" if mode_val == 2 else mode_val
                ep_state["color_mode"] = mode
                cached_updates["color_mode"] = mode
            elif attr_id == 0x4002:
                bitmask = int(value)
                caps = {
                    "hs": bool(bitmask & 0x01),
                    "xy": bool(bitmask & 0x10),
                    "ct": bool(bitmask & 0x20),
                    "color_loop": bool(bitmask & 0x08),
                }
                ep_state["color_caps"] = caps
                cached_updates["color_caps"] = caps
            elif attr_id == 0x400B:
                ep_state["ct_min"] = int(value)
                cached_updates["ct_min"] = int(value)
            elif attr_id == 0x400C:
                ep_state["ct_max"] = int(value)
                cached_updates["ct_max"] = int(value)
            else:
                ep_state["color"] = value
                cached_updates["color"] = value

    @staticmethod
    def _cache_static_attr_in_endpoints(
        device: Device,
        endpoint_id: Optional[int],
        cluster_id: int,
        attr_id: int,
        value: Any,
    ) -> None:
        """Cache static min/max/caps attributes inside the endpoints JSON."""
        if cluster_id not in (0x0008, 0x0300) or attr_id not in (
            0x0002,
            0x0003,
            0x4002,
            0x400B,
            0x400C,
        ):
            return

        endpoints: list[dict[str, Any]] = list(device.endpoints or [])
        target_ep_id = endpoint_id or 1
        ep_found = False
        for ep in endpoints:
            if ep.get("id") != target_ep_id:
                continue
            if cluster_id == 0x0008:
                if attr_id == 0x0002:
                    ep["level_min"] = int(value)
                elif attr_id == 0x0003:
                    ep["level_max"] = int(value)
            elif cluster_id == 0x0300:
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
            if cluster_id == 0x0008:
                if attr_id == 0x0002:
                    new_ep["level_min"] = int(value)
                elif attr_id == 0x0003:
                    new_ep["level_max"] = int(value)
            elif cluster_id == 0x0300:
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

    def _maybe_resolve_pending(
        self,
        ieee: str,
        endpoint_id: Optional[int],
        cluster_id: int,
        attr_id: int,
        value: Any,
    ) -> None:
        """Resolve pending commands when a matching state_change arrives."""
        to_remove: list[str] = []
        for correlation_id, pending in self._pending_commands.items():
            if pending.get("ieee") != ieee:
                continue
            if endpoint_id is not None and pending.get("endpoint") != endpoint_id:
                continue

            action = pending.get("action", "")
            resolved = False

            if action in ("on", "off") and cluster_id == 0x0006 and attr_id == 0x0000:
                expected = action == "on"
                resolved = bool(value) == expected
            elif action == "toggle" and cluster_id == 0x0006 and attr_id == 0x0000:
                resolved = True
            elif action == "level" and cluster_id == 0x0008 and attr_id == 0x0000:
                resolved = True
            elif action in ("color", "color_ct") and cluster_id == 0x0300:
                resolved = True

            if resolved:
                to_remove.append(correlation_id)
                logger.info(
                    "pending_command_resolved_by_state_change",
                    correlation_id=correlation_id,
                    ieee=ieee,
                    action=action,
                )

        for correlation_id in to_remove:
            self._pending_commands.pop(correlation_id, None)
