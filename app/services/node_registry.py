"""Node Registry — catalogue of all available node types with metadata."""

from typing import Any

from app.models.node_schemas import NodeConfigField, NodePortMeta, NodeTypeMeta


class NodeRegistry:
    """Singleton-like registry that holds metadata for every node type in the system.

    The registry is populated once at application startup and is read-only
    afterwards. It is used by:

    * Frontend palette (GET /api/nodes/registry)
    * Graph validation (unknown type checks)
    * Execution engine (resolving executor classes in later phases)
    """

    def __init__(self) -> None:
        self._types: dict[str, NodeTypeMeta] = {}

    def register(self, meta: NodeTypeMeta) -> None:
        """Register a node type. Duplicates overwrite (last wins)."""
        self._types[meta.type] = meta

    def get(self, type_id: str) -> NodeTypeMeta | None:
        """Retrieve metadata for a single node type."""
        return self._types.get(type_id)

    def list_all(self) -> list[NodeTypeMeta]:
        """Return all registered node types."""
        return list(self._types.values())

    def list_by_category(self) -> dict[str, list[NodeTypeMeta]]:
        """Group node types by category (useful for the palette tree view)."""
        groups: dict[str, list[NodeTypeMeta]] = {}
        for meta in self._types.values():
            groups.setdefault(meta.category, []).append(meta)
        return groups

    def is_known(self, type_id: str) -> bool:
        return type_id in self._types


# ---------------------------------------------------------------------------
# Built-in node catalogue (Phase 2 baseline)
# ---------------------------------------------------------------------------


def _build_builtin_catalogue() -> list[NodeTypeMeta]:
    """Return the built-in node types that ship with the application."""

    return [
        # --- Primitives ----------------------------------------------------
        NodeTypeMeta(
            type="const_bool",
            category="primitive",
            label="Boolean",
            description="Constant boolean value.",
            outputs=[
                NodePortMeta(name="value", label="Value", type="bool"),
            ],
            config_fields=[
                NodeConfigField(name="value", label="Value", type="checkbox", default=False),
            ],
        ),
        NodeTypeMeta(
            type="const_int",
            category="primitive",
            label="Integer",
            description="Constant integer value.",
            outputs=[
                NodePortMeta(name="value", label="Value", type="int"),
            ],
            config_fields=[
                NodeConfigField(name="value", label="Value", type="number", default=0),
            ],
        ),
        NodeTypeMeta(
            type="const_float",
            category="primitive",
            label="Float",
            description="Constant floating-point value.",
            outputs=[
                NodePortMeta(name="value", label="Value", type="float"),
            ],
            config_fields=[
                NodeConfigField(name="value", label="Value", type="number", default=0.0),
            ],
        ),
        NodeTypeMeta(
            type="const_string",
            category="primitive",
            label="String",
            description="Constant text value.",
            outputs=[
                NodePortMeta(name="value", label="Value", type="string"),
            ],
            config_fields=[
                NodeConfigField(name="value", label="Value", type="text", default=""),
            ],
        ),
        NodeTypeMeta(
            type="const_color",
            category="primitive",
            label="Color",
            description="Constant colour (hex or xy).",
            outputs=[
                NodePortMeta(name="color", label="Color", type="color"),
            ],
            config_fields=[
                NodeConfigField(name="color", label="Color", type="color", default="#ffffff"),
            ],
        ),
        # --- Device --------------------------------------------------------
        NodeTypeMeta(
            type="device_picker",
            category="device",
            label="Device",
            description="Pick a Zigbee device by IEEE address.",
            outputs=[
                NodePortMeta(name="device", label="Device", type="device"),
            ],
            config_fields=[
                NodeConfigField(
                    name="ieee",
                    label="Device",
                    type="device_select",
                    required=True,
                ),
            ],
        ),
        NodeTypeMeta(
            type="device_set_on_off",
            category="device",
            label="Set On/Off",
            description="Turn a device on or off.",
            inputs=[
                NodePortMeta(name="trigger", label="Trigger", type="trigger"),
                NodePortMeta(name="device", label="Device", type="device"),
                NodePortMeta(name="state", label="State", type="bool"),
            ],
            outputs=[
                NodePortMeta(name="ack", label="Ack", type="bool", optional=True),
            ],
            config_fields=[],
        ),
        NodeTypeMeta(
            type="device_set_color",
            category="device",
            label="Set Color",
            description="Write a colour to a lamp.",
            inputs=[
                NodePortMeta(name="trigger", label="Trigger", type="trigger"),
                NodePortMeta(name="device", label="Device", type="device"),
                NodePortMeta(name="color", label="Color", type="color"),
            ],
            outputs=[
                NodePortMeta(name="ack", label="Ack", type="bool", optional=True),
            ],
            config_fields=[],
        ),
        # --- Color ---------------------------------------------------------
        NodeTypeMeta(
            type="color_rgb_to_xy",
            category="color",
            label="RGB → XY",
            description="Convert RGB integers to CIE xy coordinates.",
            inputs=[
                NodePortMeta(name="r", label="R", type="int"),
                NodePortMeta(name="g", label="G", type="int"),
                NodePortMeta(name="b", label="B", type="int"),
            ],
            outputs=[
                NodePortMeta(name="x", label="x", type="float"),
                NodePortMeta(name="y", label="y", type="float"),
            ],
            config_fields=[],
        ),
        # --- Panel UI ------------------------------------------------------
        NodeTypeMeta(
            type="panel_switch_input",
            category="panel",
            label="Switch Input",
            description="Toggle switch shown on the dashboard panel.",
            outputs=[
                NodePortMeta(name="value", label="Value", type="bool"),
                NodePortMeta(name="changed", label="Changed", type="trigger"),
            ],
            config_fields=[
                NodeConfigField(name="label", label="Label", type="text", default="Switch"),
            ],
        ),
        NodeTypeMeta(
            type="panel_int_input",
            category="panel",
            label="Number Input",
            description="Slider or number input on the dashboard panel.",
            outputs=[
                NodePortMeta(name="value", label="Value", type="int"),
                NodePortMeta(name="changed", label="Changed", type="trigger"),
            ],
            config_fields=[
                NodeConfigField(name="label", label="Label", type="text", default="Value"),
                NodeConfigField(name="min", label="Min", type="number", default=0),
                NodeConfigField(name="max", label="Max", type="number", default=255),
            ],
        ),
        NodeTypeMeta(
            type="panel_button_input",
            category="panel",
            label="Button",
            description="Push button on the dashboard panel.",
            outputs=[
                NodePortMeta(name="trigger", label="Trigger", type="trigger"),
            ],
            config_fields=[
                NodeConfigField(name="label", label="Label", type="text", default="Button"),
            ],
        ),
        NodeTypeMeta(
            type="panel_int_output",
            category="panel",
            label="Number Display",
            description="Display an integer value on the dashboard panel.",
            inputs=[
                NodePortMeta(name="trigger", label="Trigger", type="trigger"),
                NodePortMeta(name="value", label="Value", type="int"),
            ],
            config_fields=[
                NodeConfigField(name="label", label="Label", type="text", default="Value"),
                NodeConfigField(name="min", label="Min", type="number", default=0),
                NodeConfigField(name="max", label="Max", type="number", default=255),
            ],
        ),
        NodeTypeMeta(
            type="panel_text_output",
            category="panel",
            label="Text Display",
            description="Display a text value on the dashboard panel.",
            inputs=[
                NodePortMeta(name="trigger", label="Trigger", type="trigger"),
                NodePortMeta(name="value", label="Value", type="string"),
            ],
            config_fields=[
                NodeConfigField(name="label", label="Label", type="text", default="Status"),
            ],
        ),
        # --- Math ----------------------------------------------------------
        NodeTypeMeta(
            type="math_add",
            category="math",
            label="Add",
            description="Add two numbers.",
            inputs=[
                NodePortMeta(name="a", label="A", type="float"),
                NodePortMeta(name="b", label="B", type="float"),
            ],
            outputs=[
                NodePortMeta(name="result", label="Result", type="float"),
            ],
            config_fields=[],
        ),
        NodeTypeMeta(
            type="math_compare",
            category="math",
            label="Compare",
            description="Compare two numbers.",
            inputs=[
                NodePortMeta(name="a", label="A", type="float"),
                NodePortMeta(name="b", label="B", type="float"),
            ],
            outputs=[
                NodePortMeta(name="gt", label="A > B", type="bool"),
                NodePortMeta(name="eq", label="A = B", type="bool"),
                NodePortMeta(name="lt", label="A < B", type="bool"),
            ],
            config_fields=[
                NodeConfigField(
                    name="mode",
                    label="Mode",
                    type="select",
                    default="gt",
                    options=[
                        {"value": "gt", "label": "Greater than"},
                        {"value": "eq", "label": "Equal"},
                        {"value": "lt", "label": "Less than"},
                    ],
                ),
            ],
        ),
        # --- Logic / Flow --------------------------------------------------
        NodeTypeMeta(
            type="flow_if",
            category="logic",
            label="If",
            description="Branch execution based on a boolean condition.",
            inputs=[
                NodePortMeta(name="trigger", label="Trigger", type="trigger"),
                NodePortMeta(name="condition", label="Condition", type="bool"),
            ],
            outputs=[
                NodePortMeta(name="true", label="True", type="trigger"),
                NodePortMeta(name="false", label="False", type="trigger"),
            ],
            config_fields=[],
        ),
        NodeTypeMeta(
            type="flow_delay",
            category="logic",
            label="Delay",
            description="Wait N seconds before emitting a trigger.",
            inputs=[
                NodePortMeta(name="trigger", label="Trigger", type="trigger"),
            ],
            outputs=[
                NodePortMeta(name="done", label="Done", type="trigger"),
            ],
            config_fields=[
                NodeConfigField(name="seconds", label="Seconds", type="number", default=1),
            ],
        ),
        # --- Triggers ------------------------------------------------------
        NodeTypeMeta(
            type="trigger_schedule",
            category="trigger",
            label="Schedule",
            description="Emit a trigger on a cron schedule.",
            outputs=[
                NodePortMeta(name="trigger", label="Trigger", type="trigger"),
            ],
            config_fields=[
                NodeConfigField(name="cron", label="Cron", type="text", default="0 8 * * *"),
            ],
        ),
        NodeTypeMeta(
            type="trigger_device_event",
            category="trigger",
            label="Device Event",
            description="React to a Zigbee device event.",
            outputs=[
                NodePortMeta(name="trigger", label="Trigger", type="trigger"),
                NodePortMeta(name="device", label="Device", type="device", optional=True),
            ],
            config_fields=[
                NodeConfigField(
                    name="event",
                    label="Event",
                    type="select",
                    default="state_change",
                    options=[
                        {"value": "state_change", "label": "State Change"},
                        {"value": "device_joined", "label": "Device Joined"},
                        {"value": "device_left", "label": "Device Left"},
                    ],
                ),
                NodeConfigField(
                    name="ieee",
                    label="Device Filter (optional)",
                    type="device_select",
                    required=False,
                ),
            ],
        ),
    ]


def create_node_registry() -> NodeRegistry:
    """Factory that builds and returns a fully populated NodeRegistry."""
    registry = NodeRegistry()
    for meta in _build_builtin_catalogue():
        registry.register(meta)
    return registry
