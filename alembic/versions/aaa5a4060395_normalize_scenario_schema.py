"""normalize scenario schema

Revision ID: aaa5a4060395
Revises: d101f515302b
Create Date: 2026-04-17 23:12:03.386289

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aaa5a4060395'
down_revision: Union[str, Sequence[str], None] = 'd101f515302b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('scenarios') as batch_op:
        batch_op.add_column(sa.Column('trigger_data', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('action_data', sa.JSON(), nullable=True))
        batch_op.drop_column('trigger_config')
        batch_op.drop_column('schedule_hour')
        batch_op.drop_column('schedule_minute')
        batch_op.drop_column('action_config')
        batch_op.drop_column('schedule_days')


def downgrade() -> None:
    with op.batch_alter_table('scenarios') as batch_op:
        batch_op.add_column(sa.Column('schedule_days', sa.VARCHAR(length=64), nullable=True))
        batch_op.add_column(sa.Column('action_config', sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column('schedule_minute', sa.INTEGER(), nullable=True))
        batch_op.add_column(sa.Column('schedule_hour', sa.INTEGER(), nullable=True))
        batch_op.add_column(sa.Column('trigger_config', sa.TEXT(), nullable=True))
        batch_op.drop_column('action_data')
        batch_op.drop_column('trigger_data')
