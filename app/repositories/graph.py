"""NodeGraph and related repositories."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import GraphConnection, GraphNode, NodeGraph
from app.repositories.base import BaseRepository


class NodeGraphRepository(BaseRepository[NodeGraph]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, NodeGraph)

    async def get_by_panel_id(self, panel_id: int) -> NodeGraph | None:
        result = await self._session.execute(
            select(NodeGraph).where(NodeGraph.panel_id == panel_id)
        )
        return result.scalar_one_or_none()

    async def create_for_panel(self, panel_id: int) -> NodeGraph:
        graph = NodeGraph(panel_id=panel_id)
        self._session.add(graph)
        await self._session.flush()
        await self._session.refresh(graph)
        return graph


class GraphNodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_graph(self, graph_id: int) -> list[GraphNode]:
        result = await self._session.execute(
            select(GraphNode).where(GraphNode.graph_id == graph_id)
        )
        return list(result.scalars().all())

    def add(self, node: GraphNode) -> None:
        self._session.add(node)

    async def delete_for_graph(self, graph_id: int) -> None:
        await self._session.execute(
            delete(GraphNode).where(GraphNode.graph_id == graph_id)
        )


class GraphConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_graph(self, graph_id: int) -> list[GraphConnection]:
        result = await self._session.execute(
            select(GraphConnection).where(GraphConnection.graph_id == graph_id)
        )
        return list(result.scalars().all())

    def add(self, conn: GraphConnection) -> None:
        self._session.add(conn)

    async def delete_for_graph(self, graph_id: int) -> None:
        await self._session.execute(
            delete(GraphConnection).where(GraphConnection.graph_id == graph_id)
        )
