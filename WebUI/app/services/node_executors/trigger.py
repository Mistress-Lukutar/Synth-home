"""Executors for trigger nodes.

Trigger nodes are special: their purpose is to *initiate* graph execution.
When a graph is executed because an external trigger fired, the trigger node
simply emits its output so downstream flow nodes can react to it.
"""

from app.services.node_executors.base import NodeExecutor, ExecutionContext, register_executor


@register_executor
class TriggerScheduleExecutor(NodeExecutor):
    node_type = "trigger_schedule"

    async def execute(self, ctx: ExecutionContext, node, inputs):
        # The graph was already started by the APScheduler job; this node
        # just signals that the trigger is active.
        return {"trigger": True}


@register_executor
class TriggerDeviceEventExecutor(NodeExecutor):
    node_type = "trigger_device_event"

    async def execute(self, ctx: ExecutionContext, node, inputs):
        # Emit trigger and optionally the filtered device IEEE.
        ieee = ""
        if node.data:
            ieee = node.data.get("ieee", "")
        return {"trigger": True, "device": {"ieee": ieee, "name": ""}}
