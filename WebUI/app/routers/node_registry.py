"""Node registry router: exposes the catalogue of available node types."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.dependencies import verify_api_key
from app.models.node_schemas import NodeTypeMeta
from app.services.node_registry import NodeRegistry

router = APIRouter()


def _get_registry(request: Request) -> NodeRegistry:
    return request.app.state.node_registry


@router.get("/api/nodes/registry")
async def list_node_registry(
    registry: Annotated[NodeRegistry, Depends(_get_registry)],
) -> dict[str, list[NodeTypeMeta]]:
    """Return all registered node types grouped by category."""
    return registry.list_by_category()
