"""Executors for panel UI nodes."""

from app.services.node_executors.base import NodeExecutor, ExecutionContext, register_executor


@register_executor
class PanelSwitchInputExecutor(NodeExecutor):
    node_type = "panel_switch_input"

    async def execute(self, ctx: ExecutionContext, node, inputs):
        value = False
        if ctx.panel_state_service is not None:
            value = ctx.panel_state_service.get_input_value(ctx.panel_id, node.id, False)
        triggered = ctx.triggered_node_id == node.id
        return {"value": bool(value), "changed": triggered}


@register_executor
class PanelIntInputExecutor(NodeExecutor):
    node_type = "panel_int_input"

    async def execute(self, ctx: ExecutionContext, node, inputs):
        value = 0
        if ctx.panel_state_service is not None:
            value = ctx.panel_state_service.get_input_value(ctx.panel_id, node.id, 0)
        triggered = ctx.triggered_node_id == node.id
        return {"value": int(value), "changed": triggered}


@register_executor
class PanelButtonInputExecutor(NodeExecutor):
    node_type = "panel_button_input"

    async def execute(self, ctx: ExecutionContext, node, inputs):
        # Button emits a trigger impulse when the graph was triggered by this node.
        triggered = ctx.triggered_node_id == node.id
        return {"trigger": triggered}


@register_executor
class PanelIntOutputExecutor(NodeExecutor):
    node_type = "panel_int_output"

    async def execute(self, ctx: ExecutionContext, node, inputs):
        triggered = bool(inputs.get("trigger", False))
        if triggered:
            value = inputs.get("value", 0)
            if ctx.panel_state_service is not None:
                ctx.panel_state_service.set_output_value(ctx.panel_id, f"_out_{node.id}", int(value))
        return {}


@register_executor
class PanelTextOutputExecutor(NodeExecutor):
    node_type = "panel_text_output"

    async def execute(self, ctx: ExecutionContext, node, inputs):
        triggered = bool(inputs.get("trigger", False))
        if triggered:
            value = inputs.get("value", "")
            if ctx.panel_state_service is not None:
                ctx.panel_state_service.set_output_value(ctx.panel_id, f"_out_{node.id}", str(value))
        return {}
