"""EP-036: Add split URL testing support to experiments

Revision ID: ep036_split_url
Revises: ep035_bayesian_cols
Create Date: 2026-03-03 00:00:00.000000

Adds the ``split_url_config`` JSONB column to the experiments table to support
EP-036 Split URL Testing.  The column stores a serialised :class:`SplitUrlConfig`
object, for example:

    {
        "variants": [
            {"name": "control",   "url": "https://example.com/a", "traffic_allocation": 50},
            {"name": "treatment", "url": "https://example.com/b", "traffic_allocation": 50}
        ],
        "cookie_name": "split_url_exp_key",
        "cookie_ttl_days": 30,
        "canonical_url": null
    }

The ``ExperimentType.SPLIT_URL`` enum value (``"split_url"``) was already present
in the SQLAlchemy model from earlier work; no enum DDL change is required.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# Revision identifiers, used by Alembic.
revision: str = "ep036_split_url"
down_revision: Union[str, None] = "ep035_bayesian_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add split_url_config column to the experiments table."""
    op.add_column(
        "experiments",
        sa.Column("split_url_config", JSONB, nullable=True),
        schema="experimentation",
    )


def downgrade() -> None:
    """Remove split_url_config column from the experiments table."""
    op.drop_column("experiments", "split_url_config", schema="experimentation")
