"""add event_name column to events table

Revision ID: a1b2c3d4e5f6
Revises: 64e15548d39c
Create Date: 2026-03-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '64e15548d39c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'events',
        sa.Column('event_name', sa.String(255), nullable=True),
        schema='experimentation'
    )
    op.create_index(
        op.f('ix_experimentation_events_event_name'),
        'events',
        ['event_name'],
        schema='experimentation'
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_experimentation_events_event_name'),
        table_name='events',
        schema='experimentation'
    )
    op.drop_column('events', 'event_name', schema='experimentation')
