"""merge_6ea93af_and_ep057

Revision ID: a0ce135350af
Revises: 6ea93af570f2, ep057_workspaces
Create Date: 2026-03-07 15:02:18.124934

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a0ce135350af'
down_revision: Union[str, None] = ('6ea93af570f2', 'ep057_workspaces')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
