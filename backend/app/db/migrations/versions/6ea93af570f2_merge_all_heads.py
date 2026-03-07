"""merge_all_heads

Revision ID: 6ea93af570f2
Revises: ep034_integration_configs, ep037_sso_config, ep046_llm_experiments
Create Date: 2026-03-03 21:32:57.739172

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6ea93af570f2'
down_revision: Union[str, None] = ('ep034_integration_configs', 'ep037_sso_config', 'ep046_llm_experiments')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
