"""Pydantic schemas for Panel, NodeGraph and export/import."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Panel schemas
# ---------------------------------------------------------------------------


class PanelLayout(BaseModel):
    x: int = 0
    y: int = 0
    w: int = 1
    h: int = 1


class PanelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    is_enabled: bool = True
    sort_order: int = 0
    layout: PanelLayout = Field(default_factory=PanelLayout)


class PanelUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    is_enabled: Optional[bool] = None
    sort_order: Optional[int] = None
    layout: Optional[PanelLayout] = None


class PanelOut(BaseModel):
    id: int
    name: str
    is_enabled: bool
    sort_order: int
    layout: Optional[dict]
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ReorderItem(BaseModel):
    id: int
    sort_order: int


# ---------------------------------------------------------------------------
# Graph node / connection schemas
# ---------------------------------------------------------------------------


class GraphNodeData(BaseModel):
    id: str = Field(..., pattern=r"^[a-zA-Z0-9_\-]+$", max_length=32)
    type: str = Field(..., min_length=1, max_length=64)
    pos: dict = Field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    data: dict = Field(default_factory=dict)

    @field_validator("pos")
    @classmethod
    def validate_pos(cls, v: dict) -> dict:
        if isinstance(v, list) and len(v) == 2:
            return {"x": float(v[0]), "y": float(v[1])}
        if not isinstance(v, dict):
            raise ValueError("pos must be a dict or [x, y] list")
        return {"x": float(v.get("x", 0)), "y": float(v.get("y", 0))}


class GraphConnectionData(BaseModel):
    id: str = Field(..., pattern=r"^[a-zA-Z0-9_\-]+$", max_length=32)
    from_: dict = Field(..., alias="from")
    to: dict

    @field_validator("from_")
    @classmethod
    def validate_from(cls, v: dict) -> dict:
        if "node" not in v or "output" not in v:
            raise ValueError('"from" must contain "node" and "output"')
        return v

    @field_validator("to")
    @classmethod
    def validate_to(cls, v: dict) -> dict:
        if "node" not in v or "input" not in v:
            raise ValueError('"to" must contain "node" and "input"')
        return v


class NodeGraphData(BaseModel):
    """Full graph representation for frontend / API."""

    id: int
    version: int = 1
    nodes: list[GraphNodeData]
    connections: list[GraphConnectionData]


class GraphUpdateRequest(BaseModel):
    nodes: list[GraphNodeData]
    connections: list[GraphConnectionData]


# ---------------------------------------------------------------------------
# Validation / import helpers
# ---------------------------------------------------------------------------


class GraphValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Export / import schemas
# ---------------------------------------------------------------------------


class ExportHeader(BaseModel):
    format: Literal["zigbeehub_panel", "zigbeehub_panel_bundle", "zigbeehub_graph_template"] = Field(
        ..., alias="_format"
    )
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$", alias="_version")
    exported_at: Optional[str] = Field(default=None, alias="_exported_at")
    app_version: Optional[str] = Field(default=None, alias="_app_version")

    model_config = {"populate_by_name": True}


class PanelExportData(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    is_enabled: bool = True
    sort_order: int = 0
    layout: dict = Field(default_factory=dict)


class GraphExport(BaseModel):
    version: int = Field(default=1, ge=1)
    nodes: list[GraphNodeData]
    connections: list[GraphConnectionData]


class PanelExport(BaseModel):
    header: ExportHeader
    panel: PanelExportData
    graph: GraphExport

    model_config = {"populate_by_name": True}


class PanelBundleExport(BaseModel):
    header: ExportHeader
    panels: list[PanelExport]

    model_config = {"populate_by_name": True}
