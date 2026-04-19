"""Executors for device-related nodes."""

import structlog

from app.services.node_executors.base import NodeExecutor, ExecutionContext, register_executor

logger = structlog.get_logger(__name__)


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
        if not triggered:
            return {"ack": False}

        device = inputs.get("device")
        state = inputs.get("state")
        if not device or state is None:
            return {"ack": False}
        ieee = device.get("ieee") if isinstance(device, dict) else device
        if not ieee:
            return {"ack": False}
        if ctx.hub_service is None or not ctx.hub_service.is_connected():
            logger.warning("device_set_on_off_no_hub", ieee=ieee)
            return {"ack": False}
        action = "on" if state else "off"
        try:
            result = await ctx.hub_service.send_command(ieee, action)
            logger.info("device_set_on_off_executed", ieee=ieee, action=action)
            return {"ack": True, "correlation_id": result.get("correlation_id")}
        except Exception as exc:
            logger.warning("device_set_on_off_failed", ieee=ieee, error=str(exc))
            return {"ack": False, "error": str(exc)}


@register_executor
class DeviceSetColorExecutor(NodeExecutor):
    node_type = "device_set_color"

    async def execute(self, ctx, node, inputs):
        triggered = bool(inputs.get("trigger", False))
        if not triggered:
            return {"ack": False}

        device = inputs.get("device")
        color = inputs.get("color")
        if not device or not color:
            return {"ack": False}
        ieee = device.get("ieee") if isinstance(device, dict) else device
        if not ieee:
            return {"ack": False}
        if ctx.hub_service is None or not ctx.hub_service.is_connected():
            logger.warning("device_set_color_no_hub", ieee=ieee)
            return {"ack": False}
        params: dict = {"color": color}
        try:
            result = await ctx.hub_service.send_command(ieee, "color", params)
            logger.info("device_set_color_executed", ieee=ieee, color=color)
            return {"ack": True, "correlation_id": result.get("correlation_id")}
        except Exception as exc:
            logger.warning("device_set_color_failed", ieee=ieee, error=str(exc))
            return {"ack": False, "error": str(exc)}
