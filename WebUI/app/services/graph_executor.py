"""Graph execution engine — trigger-driven execution with lazy data-flow."""

from collections import deque
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import GraphConnection, GraphNode, NodeGraph
from app.repositories.graph import GraphConnectionRepository, GraphNodeRepository, NodeGraphRepository
from app.services.hub_service import HubService
from app.services.node_registry import NodeRegistry
from app.services.panel_state_service import PanelStateService
from app.services.node_executors.base import ExecutionContext, NODE_EXECUTORS

logger = structlog.get_logger(__name__)


class GraphExecutor:
    """Executes a node graph using trigger-driven semantics.

    Trigger nodes (panel inputs, schedules, device events) initiate execution.
    When a node produces a truthy trigger output, all downstream nodes connected
    to that trigger output are queued for execution. Data-flow values (constants,
    math, device pickers) are computed lazily when requested by an executing node.
    """

    def __init__(
        self,
        hub_service: HubService | None,
        panel_state_service: PanelStateService | None,
        node_registry: NodeRegistry | None = None,
    ) -> None:
        self._hub_service = hub_service
        self._panel_state_service = panel_state_service
        self._node_registry = node_registry

    async def run(
        self,
        panel_id: int,
        db: AsyncSession,
        triggered_node_id: str | None = None,
    ) -> dict[str, Any]:
        """Load and execute the graph attached to *panel_id*.

        Args:
            panel_id: The panel whose graph should run.
            db: Active SQLAlchemy async session.
            triggered_node_id: The node that fired the trigger (if any).

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
            triggered_node_id=triggered_node_id,
        )

        try:
            executed = await self._execute_graph(ctx, nodes, connections, triggered_node_id)
            return {"success": True, "executed_nodes": executed}
        except Exception as exc:
            logger.exception("graph_execution_failed", panel_id=panel_id)
            return {"success": False, "error": str(exc)}

    async def _execute_graph(
        self,
        ctx: ExecutionContext,
        nodes: list[GraphNode],
        connections: list[GraphConnection],
        triggered_node_id: str | None,
    ) -> int:
        """Run the graph using trigger-driven BFS and return the number of nodes executed."""
        node_map = {n.id: n for n in nodes}

        # Data cache for lazy evaluation
        data_cache: dict[str, dict[str, Any]] = {}
        executed: set[str] = set()

        async def resolve_data(node_id: str, input_name: str) -> Any:
            """Lazily compute a data input by evaluating upstream data nodes."""
            for c in connections:
                if c.target_node_id == node_id and c.target_input == input_name:
                    upstream_id = c.source_node_id
                    upstream_output = c.source_output
                    if upstream_id not in data_cache:
                        await _execute_data_node(upstream_id)
                    return data_cache.get(upstream_id, {}).get(upstream_output)
            return None

        async def _execute_data_node(node_id: str) -> None:
            """Evaluate a pure data node and cache its outputs."""
            if node_id in data_cache:
                return
            node = node_map[node_id]
            executor = NODE_EXECUTORS.get(node.type)
            if executor is None:
                logger.warning("unknown_data_node_skipped", node_id=node.id, type=node.type)
                data_cache[node_id] = {}
                executed.add(node_id)
                return

            # Gather all upstream data inputs recursively
            node_inputs: dict[str, Any] = {}
            for c in connections:
                if c.target_node_id == node_id:
                    val = await resolve_data(node_id, c.target_input)
                    node_inputs[c.target_input] = val

            try:
                outputs = await executor.execute(ctx, node, node_inputs)
                data_cache[node_id] = outputs or {}
                executed.add(node_id)
                logger.debug("data_node_executed", node_id=node.id, type=node.type, outputs=outputs)
            except Exception:
                logger.exception("data_node_execution_failed", node_id=node.id, type=node.type)
                data_cache[node_id] = {}
                executed.add(node_id)

        async def _execute_trigger_node(node_id: str) -> dict[str, Any]:
            """Evaluate a trigger/action node (called when it is activated)."""
            node = node_map[node_id]
            executor = NODE_EXECUTORS.get(node.type)
            if executor is None:
                logger.warning("unknown_trigger_node_skipped", node_id=node.id, type=node.type)
                return {}

            # Gather non-trigger data inputs lazily
            node_inputs: dict[str, Any] = {}
            for c in connections:
                if c.target_node_id == node_id and c.target_input != "trigger":
                    val = await resolve_data(node_id, c.target_input)
                    node_inputs[c.target_input] = val

            # Mark trigger input as active since this node was queued via trigger-flow
            node_inputs["trigger"] = True

            try:
                outputs = await executor.execute(ctx, node, node_inputs)
                logger.debug("trigger_node_executed", node_id=node.id, type=node.type, outputs=outputs)
                return outputs or {}
            except Exception:
                logger.exception("trigger_node_execution_failed", node_id=node.id, type=node.type)
                return {}

        def _is_trigger_output(node_type: str, output_name: str) -> bool:
            """Check whether a given output port is a trigger type."""
            if self._node_registry is None:
                # Fallback heuristic
                return output_name in ("trigger", "changed", "true", "false", "done")
            meta = self._node_registry.get(node_type)
            if meta is None:
                return output_name in ("trigger", "changed", "true", "false", "done")
            out_meta = next((o for o in meta.outputs if o.name == output_name), None)
            return out_meta is not None and out_meta.type == "trigger"

        # BFS over trigger-flow
        queue: deque[str] = deque()
        if triggered_node_id and triggered_node_id in node_map:
            queue.append(triggered_node_id)

        while queue:
            current_id = queue.popleft()
            if current_id in executed:
                continue
            executed.add(current_id)

            outputs = await _execute_trigger_node(current_id)

            # Propagate along trigger connections
            for c in connections:
                if c.source_node_id == current_id:
                    if _is_trigger_output(node_map[current_id].type, c.source_output):
                        if outputs.get(c.source_output):
                            queue.append(c.target_node_id)

        return len(executed)
