"""Pydantic schemas for node type metadata (Node Registry)."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class NodePortMeta(BaseModel):
    """Metadata for a single input or output port on a node."""

    name: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=64)
    type: str = Field(..., min_length=1, max_length=32)
    default: Any | None = None
    optional: bool = False


class NodeConfigField(BaseModel):
    """Description of a single configuration field shown in the properties panel."""

    name: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=64)
    type: Literal[
        "text",
        "number",
        "checkbox",
        "select",
        "color",
        "textarea",
        "device_select",
    ] = "text"
    default: Any | None = None
    options: list[dict[str, Any]] | None = None
    required: bool = True


class NodeTypeMeta(BaseModel):
    """Complete metadata for a node type (used by palette, validation and docs)."""

    type: str = Field(..., min_length=1, max_length=64)
    category: str = Field(..., min_length=1, max_length=32)
    label: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    inputs: list[NodePortMeta] = Field(default_factory=list)
    outputs: list[NodePortMeta] = Field(default_factory=list)
    config_fields: list[NodeConfigField] = Field(default_factory=list)
