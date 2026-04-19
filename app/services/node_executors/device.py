"""Executors for device-related nodes."""

import structlog

from app.services.node_executors.base import NodeExecutor, ExecutionContext, register_executor

logger = structlog.get_logger(__name__)


def _resolve_device_state(ctx: ExecutionContext | None, node, inputs: dict) -> dict:
    """Helper to extract cached device state for read_* nodes."""
    device = inputs.get("device")
    if not device:
        return {}
    ieee = device.get("ieee") if isinstance(device, dict) else str(device)
    endpoint = 1
    if node.data:
        try:
            endpoint = int(node.data.get("endpoint", 1))
        except (TypeError, ValueError):
            endpoint = 1
    if ctx is None or ctx.hub_service is None:
        return {}
    cached = ctx.hub_service.get_cached_devices()
    dev = next((d for d in cached if d.get("ieee") == ieee), None)
    return dev.get("state", {}).get(str(endpoint), {}) if dev else {}


def _get_ieee_and_endpoint(device, node_data):
    ieee = ""
    endpoint = 1
    if device:
        ieee = device.get("ieee") if isinstance(device, dict) else str(device)
    if node_data:
        try:
            endpoint = int(node_data.get("endpoint", 1))
        except (TypeError, ValueError):
            endpoint = 1
    return ieee, endpoint


@register_executor
class DevicePickerExecutor(NodeExecutor):
    node_type = "device_picker"

    async def execute(self, ctx, node, inputs):
        ieee = node.data.get("ieee", "")
        return {"device": {"ieee": ieee, "name": ""}}


@register_executor
class DeviceSetOnOffExecutor(NodeExecutor):
    node_type = "device_set_on_off"

    async def execute(self, ctx, node, inputs):
        triggered = bool(inputs.get("trigger", False))
        device = inputs.get("device")
        state = inputs.get("state")
        if not triggered:
            return {"device": device, "ack": False}
        if not device or state is None:
            return {"device": device, "ack": False}
        ieee = device.get("ieee") if isinstance(device, dict) else device
        if not ieee:
            return {"device": device, "ack": False}
        if ctx.hub_service is None or not ctx.hub_service.is_connected():
            logger.warning("device_set_on_off_no_hub", ieee=ieee)
            return {"device": device, "ack": False}
        action = "on" if state else "off"
        try:
            result = await ctx.hub_service.send_command(ieee, action)
            logger.info("device_set_on_off_executed", ieee=ieee, action=action)
            return {"device": device, "ack": True, "correlation_id": result.get("correlation_id")}
        except Exception as exc:
            logger.warning("device_set_on_off_failed", ieee=ieee, error=str(exc))
            return {"device": device, "ack": False, "error": str(exc)}


@register_executor
class DeviceSetColorExecutor(NodeExecutor):
    node_type = "device_set_color"

    async def execute(self, ctx, node, inputs):
        triggered = bool(inputs.get("trigger", False))
        device = inputs.get("device")
        color = inputs.get("color")
        if not triggered:
            return {"device": device, "ack": False}
        if not device or not color:
            return {"device": device, "ack": False}
        ieee = device.get("ieee") if isinstance(device, dict) else device
        if not ieee:
            return {"device": device, "ack": False}
        if ctx.hub_service is None or not ctx.hub_service.is_connected():
            logger.warning("device_set_color_no_hub", ieee=ieee)
            return {"device": device, "ack": False}

        mode = "xy"
        endpoint = 1
        if node.data:
            mode = node.data.get("mode", "xy")
            try:
                endpoint = int(node.data.get("endpoint", 1))
            except (TypeError, ValueError):
                endpoint = 1

        params: dict = {"hex": color, "mode": mode, "endpoint": endpoint}
        try:
            result = await ctx.hub_service.send_command(ieee, "color", params)
            logger.info("device_set_color_executed", ieee=ieee, color=color, mode=mode, endpoint=endpoint)
            return {"device": device, "ack": True, "correlation_id": result.get("correlation_id")}
        except Exception as exc:
            logger.warning("device_set_color_failed", ieee=ieee, error=str(exc))
            return {"device": device, "ack": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Read device state (blocking read_attr where possible)
# ---------------------------------------------------------------------------

@register_executor
class ReadOnOffExecutor(NodeExecutor):
    node_type = "read_on_off"

    async def execute(self, ctx, node, inputs):
        device = inputs.get("device")
        ieee, endpoint = _get_ieee_and_endpoint(device, node.data)
        on = False

        if ctx is not None and ctx.hub_service and ctx.hub_service.is_connected() and ieee:
            try:
                result = await ctx.hub_service.read_attr_and_wait(
                    ieee, endpoint, "0x0006", "0x0000", timeout=3.0
                )
                val = result.get("value")
                if val is not None:
                    on = bool(val)
                else:
                    # fallback to cached state
                    state = _resolve_device_state(ctx, node, inputs)
                    on = bool(state.get("on", False))
            except Exception:
                logger.exception("read_on_off_failed", ieee=ieee)
                state = _resolve_device_state(ctx, node, inputs)
                on = bool(state.get("on", False))
        else:
            state = _resolve_device_state(ctx, node, inputs)
            on = bool(state.get("on", False))

        return {"device": device, "on": on}


@register_executor
class ReadLevelExecutor(NodeExecutor):
    node_type = "read_level"

    async def execute(self, ctx, node, inputs):
        device = inputs.get("device")
        ieee, endpoint = _get_ieee_and_endpoint(device, node.data)
        level = 0

        if ctx is not None and ctx.hub_service and ctx.hub_service.is_connected() and ieee:
            try:
                result = await ctx.hub_service.read_attr_and_wait(
                    ieee, endpoint, "0x0008", "0x0000", timeout=3.0
                )
                val = result.get("value")
                if val is not None:
                    level = int(val)
                else:
                    state = _resolve_device_state(ctx, node, inputs)
                    level = int(state.get("level", 0))
            except Exception:
                logger.exception("read_level_failed", ieee=ieee)
                state = _resolve_device_state(ctx, node, inputs)
                level = int(state.get("level", 0))
        else:
            state = _resolve_device_state(ctx, node, inputs)
            level = int(state.get("level", 0))

        return {"device": device, "level": level}


@register_executor
class ReadColorExecutor(NodeExecutor):
    node_type = "read_color"

    async def execute(self, ctx, node, inputs):
        device = inputs.get("device")
        ieee, endpoint = _get_ieee_and_endpoint(device, node.data)

        # Fire-and-forget reads to refresh cached state for next evaluation
        if ctx.hub_service and ctx.hub_service.is_connected() and ieee:
            try:
                # We cannot get hex directly via read_attr; the hub returns
                # individual xy / hs / ct components. We trigger background
                # reads so the cached device state is refreshed via ack events.
                await ctx.hub_service.read_attr(ieee, endpoint, "0x0300", "0x0008")
                await ctx.hub_service.read_attr(ieee, endpoint, "0x0300", "0x0003")
                await ctx.hub_service.read_attr(ieee, endpoint, "0x0300", "0x0004")
            except Exception:
                logger.debug("read_color_background_refresh_failed", ieee=ieee)

        state = _resolve_device_state(ctx, node, inputs)
        return {"device": device, "color": state.get("color", "#ffffff")}
