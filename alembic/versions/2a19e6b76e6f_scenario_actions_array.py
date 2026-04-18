"""scenario_actions_array

Revision ID: 2a19e6b76e6f
Revises: d0011bc29292
Create Date: 2026-04-19 00:22:34.444165

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = '2a19e6b76e6f'
down_revision: Union[str, Sequence[str], None] = 'd0011bc29292'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('scenarios', sa.Column('actions', sa.JSON(), nullable=True))

    # Migrate old single-action data to new actions array
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, action_type, action_data FROM scenarios")).fetchall()
    for row in rows:
        actions = []
        if row.action_type:
            actions.append({
                "action_type": row.action_type,
                "action_data": json.loads(row.action_data) if row.action_data else {},
            })
        conn.execute(
            sa.text("UPDATE scenarios SET actions = :actions WHERE id = :id"),
            {"actions": json.dumps(actions), "id": row.id}
        )

    op.drop_column('scenarios', 'action_type')
    op.drop_column('scenarios', 'action_data')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('scenarios', sa.Column('action_data', sqlite.JSON(), nullable=True))
    op.add_column('scenarios', sa.Column('action_type', sa.VARCHAR(length=32), nullable=True))

    # Migrate first action back to single-action columns
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, actions FROM scenarios")).fetchall()
    for row in rows:
        actions = json.loads(row.actions) if row.actions else []
        first = actions[0] if actions else {}
        conn.execute(
            sa.text("UPDATE scenarios SET action_type = :at, action_data = :ad WHERE id = :id"),
            {
                "at": first.get("action_type", "command"),
                "ad": json.dumps(first.get("action_data", {})),
                "id": row.id,
            }
        )

    op.drop_column('scenarios', 'actions')
