"""Graph execution engine — data-flow DAG evaluator."""

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import GraphConnection, GraphNode, NodeGraph
from app.repositories.graph import GraphConnectionRepository, GraphNodeRepository, NodeGraphRepository
from app.services.hub_service import HubService
from app.services.panel_state_service import PanelStateService
from app.services.node_executors.base import ExecutionContext, NODE_EXECUTORS

logger = structlog.get_logger(__name__)


class GraphExecutor:
    """Executes a node graph using data-flow semantics with topological ordering."""

    def __init__(
        self,
        hub_service: HubService | None,
        panel_state_service: PanelStateService | None,
    ) -> None:
        self._hub_service = hub_service
        self._panel_state_service = panel_state_service

    async def run(self, panel_id: int, db: AsyncSession) -> dict[str, Any]:
        """Load and execute the graph attached to *panel_id*.

        Returns a result dict with ``success``, ``executed_nodes``, and optional
        ``error`` fields.
        """
        graph_repo = NodeGraphRepository(db)
        graph = await graph_repo.get_by_panel_id(panel_id)
        if not graph:
            return {"success": False, "error": "Graph not found"}

        node_repo = GraphNodeRepository(db)
        conn_repo = GraphConnectionRepository(db)
        nodes = await node_repo.get_for_graph(graph.id)
        connections = await conn_repo.get_for_graph(graph.id)

        if not nodes:
            return {"success": True, "executed_nodes": 0}

        ctx = ExecutionContext(
            panel_id=panel_id,
            graph_id=graph.id,
            hub_service=self._hub_service,
            panel_state_service=self._panel_state_service,
        )

        try:
            executed = await self._execute_graph(ctx, nodes, connections)
            return {"success": True, "executed_nodes": executed}
        except Exception as exc:
            logger.exception("graph_execution_failed", panel_id=panel_id)
            return {"success": False, "error": str(exc)}

    async def _execute_graph(
        self,
        ctx: ExecutionContext,
        nodes: list[GraphNode],
        connections: list[GraphConnection],
    ) -> int:
        """Run the DAG and return the number of nodes actually executed."""
        node_map = {n.id: n for n in nodes}

        # Build adjacency list and in-degree map for topological sort
        in_degree: dict[str, int] = {n.id: 0 for n in nodes}
        adj: dict[str, list[GraphConnection]] = {n.id: [] for n in nodes}
        for c in connections:
            adj[c.source_node_id].append(c)
            in_degree[c.target_node_id] += 1

        # Kahn's algorithm
        queue = [n_id for n_id, deg in in_degree.items() if deg == 0]
        order: list[str] = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            for c in adj.get(current, []):
                in_degree[c.target_node_id] -= 1
                if in_degree[c.target_node_id] == 0:
                    queue.append(c.target_node_id)

        if len(order) != len(nodes):
            # Cycle detected — should have been caught by validation, but guard anyway
            raise ValueError("Graph contains cycles")

        executed_count = 0
        for node_id in order:
            node = node_map[node_id]
            if ctx.get_cached(node_id) is not None:
                continue

            # Gather inputs from upstream cached outputs
            node_inputs: dict[str, Any] = {}
            for c in connections:
                if c.target_node_id == node_id:
                    upstream_outputs = ctx.get_cached(c.source_node_id)
                    if upstream_outputs is not None:
                        node_inputs[c.target_input] = upstream_outputs.get(c.source_output)

            executor = NODE_EXECUTORS.get(node.type)
            if executor is None:
                logger.warning("unknown_node_type_skipped", node_id=node.id, type=node.type)
                ctx.set_cached(node.id, {})
                continue

            try:
                outputs = await executor.execute(ctx, node, node_inputs)
                ctx.set_cached(node.id, outputs or {})
                executed_count += 1
                logger.debug("node_executed", node_id=node.id, type=node.type, outputs=outputs)
            except Exception:
                logger.exception("node_execution_failed", node_id=node.id, type=node.type)
                ctx.set_cached(node.id, {})
                # Continue with other nodes — don't break the whole graph

        return executed_count
