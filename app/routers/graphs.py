"""Graph router: CRUD for node graphs and validation."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.db_models import GraphConnection, GraphNode, NodeGraph
from app.models.panel_schemas import (
    GraphUpdateRequest,
    NodeGraphData,
    GraphValidationResult,
    GraphNodeData,
    GraphConnectionData,
)
from app.models.schemas import StatusResponse
from app.repositories.graph import (
    GraphConnectionRepository,
    GraphNodeRepository,
    NodeGraphRepository,
)

router = APIRouter()


def _build_graph_data(graph: NodeGraph, nodes: list[GraphNode], connections: list[GraphConnection]) -> NodeGraphData:
    return NodeGraphData(
        id=graph.id,
        version=graph.version,
        nodes=[
            GraphNodeData(
                id=n.id,
                type=n.type,
                pos={"x": n.pos_x, "y": n.pos_y},
                data=n.data or {},
            )
            for n in nodes
        ],
        connections=[
            GraphConnectionData.model_validate(
                {
                    "id": c.id,
                    "from": {"node": c.source_node_id, "output": c.source_output},
                    "to": {"node": c.target_node_id, "input": c.target_input},
                }
            )
            for c in connections
        ],
    )


@router.get("/api/graphs/{panel_id}", response_model=NodeGraphData)
async def get_graph(
    panel_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NodeGraphData:
    graph_repo = NodeGraphRepository(db)
    graph = await graph_repo.get_by_panel_id(panel_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")
    node_repo = GraphNodeRepository(db)
    conn_repo = GraphConnectionRepository(db)
    nodes = await node_repo.get_for_graph(graph.id)
    connections = await conn_repo.get_for_graph(graph.id)
    return _build_graph_data(graph, nodes, connections)


@router.put("/api/graphs/{panel_id}", response_model=NodeGraphData)
async def save_graph(
    panel_id: int,
    req: GraphUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> NodeGraphData:
    graph_repo = NodeGraphRepository(db)
    graph = await graph_repo.get_by_panel_id(panel_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    node_repo = GraphNodeRepository(db)
    conn_repo = GraphConnectionRepository(db)

    # Transactional replacement: delete old, insert new
    await node_repo.delete_for_graph(graph.id)
    await conn_repo.delete_for_graph(graph.id)

    for n in req.nodes:
        node = GraphNode(
            id=n.id,
            graph_id=graph.id,
            type=n.type,
            pos_x=n.pos.get("x", 0.0),
            pos_y=n.pos.get("y", 0.0),
            data=n.data,
        )
        node_repo.add(node)

    for c in req.connections:
        conn = GraphConnection(
            id=c.id,
            graph_id=graph.id,
            source_node_id=c.from_["node"],
            source_output=c.from_["output"],
            target_node_id=c.to["node"],
            target_input=c.to["input"],
        )
        conn_repo.add(conn)

    graph.version += 1
    await db.commit()
    await db.refresh(graph)

    # Re-register triggers after graph change
    panel_trigger_service = request.app.state.panel_trigger_service
    await panel_trigger_service.update_panel(panel_id, db)

    nodes = await node_repo.get_for_graph(graph.id)
    connections = await conn_repo.get_for_graph(graph.id)
    return _build_graph_data(graph, nodes, connections)


@router.post("/api/graphs/{panel_id}/validate", response_model=GraphValidationResult)
async def validate_graph(
    panel_id: int,
    req: GraphUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> GraphValidationResult:
    from app.services.node_registry import NodeRegistry

    graph_repo = NodeGraphRepository(db)
    graph = await graph_repo.get_by_panel_id(panel_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    errors: list[str] = []
    warnings: list[str] = []

    node_ids = {n.id for n in req.nodes}
    node_types = {n.id: n.type for n in req.nodes}

    # Unknown node types
    registry: NodeRegistry = request.app.state.node_registry
    for n in req.nodes:
        if not registry.is_known(n.type):
            warnings.append(f"Node {n.id} uses unknown type '{n.type}' — will be imported as placeholder")

    # Dangling connections
    for c in req.connections:
        if c.from_["node"] not in node_ids:
            errors.append(f"Connection {c.id}: source node {c.from_['node']} not found")
        if c.to["node"] not in node_ids:
            errors.append(f"Connection {c.id}: target node {c.to['node']} not found")

    # Cycles detection (simple DFS)
    adj: dict[str, list[str]] = {n: [] for n in node_ids}
    for c in req.connections:
        adj[c.from_["node"]].append(c.to["node"])

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in node_ids}

    def dfs(node_id: str) -> bool:
        color[node_id] = GRAY
        for neighbor in adj.get(node_id, []):
            if neighbor not in color:
                continue
            if color[neighbor] == GRAY:
                return True
            if color[neighbor] == WHITE and dfs(neighbor):
                return True
        color[node_id] = BLACK
        return False

    for n in node_ids:
        if color[n] == WHITE:
            if dfs(n):
                errors.append("Graph contains cycles")
                break

    # Duplicate inputs
    target_inputs: set[tuple[str, str]] = set()
    for c in req.connections:
        key = (c.to["node"], c.to["input"])
        if key in target_inputs:
            errors.append(f"Node {c.to['node']} input {c.to['input']} has multiple connections")
        target_inputs.add(key)

    return GraphValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)
