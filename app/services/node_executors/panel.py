"""Executors for panel UI nodes."""

from app.services.node_executors.base import NodeExecutor, ExecutionContext, register_executor


@register_executor
class PanelSwitchInputExecutor(NodeExecutor):
    node_type = "panel_switch_input"

    async def execute(self, ctx, node, inputs):
        value = False
        if ctx.panel_state_service is not None:
            value = ctx.panel_state_service.get_input_value(ctx.panel_id, node.id, False)
        return {"value": bool(value)}


@register_executor
class PanelIntInputExecutor(NodeExecutor):
    node_type = "panel_int_input"

    async def execute(self, ctx, node, inputs):
        value = 0
        if ctx.panel_state_service is not None:
            value = ctx.panel_state_service.get_input_value(ctx.panel_id, node.id, 0)
        return {"value": int(value)}


@register_executor
class PanelButtonInputExecutor(NodeExecutor):
    node_type = "panel_button_input"

    async def execute(self, ctx, node, inputs):
        # Button emits a trigger impulse — always True when graph runs because
        # the graph was triggered by the button press itself.
        return {"trigger": True}


@register_executor
class PanelIntOutputExecutor(NodeExecutor):
    node_type = "panel_int_output"

    async def execute(self, ctx, node, inputs):
        value = inputs.get("value", 0)
        if ctx.panel_state_service is not None:
            ctx.panel_state_service.set_output_value(ctx.panel_id, f"_out_{node.id}", int(value))
        return {}


@register_executor
class PanelTextOutputExecutor(NodeExecutor):
    node_type = "panel_text_output"

    async def execute(self, ctx, node, inputs):
        value = inputs.get("value", "")
        if ctx.panel_state_service is not None:
            ctx.panel_state_service.set_output_value(ctx.panel_id, f"_out_{node.id}", str(value))
        return {}
