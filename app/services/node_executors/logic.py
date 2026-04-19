"""Executors for logic / flow-control nodes."""

import asyncio

import structlog

from app.services.node_executors.base import NodeExecutor, ExecutionContext, register_executor

logger = structlog.get_logger(__name__)


@register_executor
class FlowIfExecutor(NodeExecutor):
    node_type = "flow_if"

    async def execute(self, ctx: ExecutionContext, node, inputs):
        condition = bool(inputs.get("condition", False))
        return {"true": condition, "false": not condition}


@register_executor
class FlowDelayExecutor(NodeExecutor):
    node_type = "flow_delay"

    async def execute(self, ctx: ExecutionContext, node, inputs):
        triggered = bool(inputs.get("trigger", False))
        seconds = 1.0
        if node.data:
            try:
                seconds = float(node.data.get("seconds", 1.0))
            except (TypeError, ValueError):
                seconds = 1.0

        if triggered and seconds > 0:
            try:
                await asyncio.sleep(seconds)
            except asyncio.CancelledError:
                logger.debug("flow_delay_cancelled", panel_id=ctx.panel_id, node_id=node.id)
                return {"done": False}

        return {"done": triggered}
