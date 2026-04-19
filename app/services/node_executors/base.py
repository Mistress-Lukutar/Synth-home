"""Base class and registry for node executors."""

from abc import ABC, abstractmethod
from typing import Any

import structlog

from app.models.db_models import GraphNode
from app.services.panel_state_service import PanelStateService
from app.services.hub_service import HubService

logger = structlog.get_logger(__name__)


class ExecutionContext:
    """Context object passed to every node during graph execution.

    Holds references to external services, the cache of already-computed
    node outputs, and the current panel identity.
    """

    def __init__(
        self,
        panel_id: int,
        graph_id: int,
        hub_service: HubService | None,
        panel_state_service: PanelStateService | None,
    ) -> None:
        self.panel_id = panel_id
        self.graph_id = graph_id
        self.hub_service = hub_service
        self.panel_state_service = panel_state_service
        self._cache: dict[str, dict[str, Any]] = {}

    def get_cached(self, node_id: str) -> dict[str, Any] | None:
        return self._cache.get(node_id)

    def set_cached(self, node_id: str, outputs: dict[str, Any]) -> None:
        self._cache[node_id] = outputs

    def clear_cache(self) -> None:
        self._cache.clear()


class NodeExecutor(ABC):
    """Abstract base for a node-type-specific executor.

    Subclasses must:
      1. Set ``node_type`` class attribute.
      2. Implement ``execute``.
    """

    node_type: str = ""

    @abstractmethod
    async def execute(
        self,
        ctx: ExecutionContext,
        node: GraphNode,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the node logic and return a dict of output_name → value."""
        ...


# Global executor registry populated by importing concrete modules.
NODE_EXECUTORS: dict[str, NodeExecutor] = {}


def register_executor(executor_cls: type[NodeExecutor]) -> type[NodeExecutor]:
    """Decorator that auto-registers a NodeExecutor subclass."""
    instance = executor_cls()
    NODE_EXECUTORS[instance.node_type] = instance
    logger.debug("executor_registered", node_type=instance.node_type)
    return executor_cls
