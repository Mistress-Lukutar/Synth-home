"""Executors for primitive / constant nodes."""

from app.services.node_executors.base import NodeExecutor, ExecutionContext, register_executor


@register_executor
class ConstBoolExecutor(NodeExecutor):
    node_type = "const_bool"

    async def execute(self, ctx, node, inputs):
        value = node.data.get("value", False)
        return {"value": bool(value)}


@register_executor
class ConstIntExecutor(NodeExecutor):
    node_type = "const_int"

    async def execute(self, ctx, node, inputs):
        value = node.data.get("value", 0)
        return {"value": int(value)}


@register_executor
class ConstFloatExecutor(NodeExecutor):
    node_type = "const_float"

    async def execute(self, ctx, node, inputs):
        value = node.data.get("value", 0.0)
        return {"value": float(value)}


@register_executor
class ConstStringExecutor(NodeExecutor):
    node_type = "const_string"

    async def execute(self, ctx, node, inputs):
        value = node.data.get("value", "")
        return {"value": str(value)}


@register_executor
class ConstColorExecutor(NodeExecutor):
    node_type = "const_color"

    async def execute(self, ctx, node, inputs):
        value = node.data.get("color", "#ffffff")
        return {"color": value}
