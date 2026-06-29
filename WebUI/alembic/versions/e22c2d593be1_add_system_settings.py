"""add_system_settings

Revision ID: e22c2d593be1
Revises: 53b61700e60d
Create Date: 2026-05-03 01:44:03.966650

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e22c2d593be1'
down_revision: Union[str, Sequence[str], None] = '53b61700e60d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'system_settings',
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('value', sa.String(length=512), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('system_settings')
