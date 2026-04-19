"""fix_graph_node_connection_composite_pk

Revision ID: 4e0e90030bd4
Revises: 2c90706fe739
Create Date: 2026-04-19 21:39:54.866545

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e0e90030bd4'
down_revision: Union[str, Sequence[str], None] = '2c90706fe739'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Recreate graph_nodes and graph_connections with composite PK (graph_id, id)."""
    # Drop old tables
    op.drop_table("graph_connections")
    op.drop_table("graph_nodes")

    # Recreate with composite PK
    op.create_table(
        "graph_nodes",
        sa.Column("graph_id", sa.Integer(), sa.ForeignKey("node_graphs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("pos_x", sa.Float(), server_default="0.0"),
        sa.Column("pos_y", sa.Float(), server_default="0.0"),
        sa.Column("data", sa.JSON(), nullable=True),
    )

    op.create_table(
        "graph_connections",
        sa.Column("graph_id", sa.Integer(), sa.ForeignKey("node_graphs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source_node_id", sa.String(32), nullable=False),
        sa.Column("source_output", sa.String(64), nullable=False),
        sa.Column("target_node_id", sa.String(32), nullable=False),
        sa.Column("target_input", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    """Restore single-column PK."""
    op.drop_table("graph_connections")
    op.drop_table("graph_nodes")

    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("graph_id", sa.Integer(), sa.ForeignKey("node_graphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("pos_x", sa.Float(), server_default="0.0"),
        sa.Column("pos_y", sa.Float(), server_default="0.0"),
        sa.Column("data", sa.JSON(), nullable=True),
    )

    op.create_table(
        "graph_connections",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("graph_id", sa.Integer(), sa.ForeignKey("node_graphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_node_id", sa.String(32), nullable=False),
        sa.Column("source_output", sa.String(64), nullable=False),
        sa.Column("target_node_id", sa.String(32), nullable=False),
        sa.Column("target_input", sa.String(64), nullable=False),
    )
