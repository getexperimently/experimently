"""EP-035: Add Bayesian columns to experiments table

Revision ID: ep035_bayesian_cols
Revises: e181583b4b24
Create Date: 2026-03-02 00:00:00.000000

Adds three columns to the experiments table to support EP-035 Bayesian
experimentation:
  - bayesian_enabled: Boolean flag to enable Bayesian analysis for an experiment.
  - bayesian_config: JSONB column storing the BayesianConfig (prior family,
    hyperparameters, loss threshold, ROPE, credible level).
  - bayesian_decision: String column storing the current BayesianDecision value
    (CONTINUE, STOP_WINNER, STOP_EQUIVALENT, STOP_FUTILE).
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic
revision: str = "ep035_bayesian_cols"
down_revision: Union[str, None] = "e181583b4b24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add Bayesian columns to the experiments table."""
    schema = "experimentation"

    op.add_column(
        "experiments",
        sa.Column(
            "bayesian_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        schema=schema,
    )
    op.add_column(
        "experiments",
        sa.Column(
            "bayesian_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema=schema,
    )
    op.add_column(
        "experiments",
        sa.Column(
            "bayesian_decision",
            sa.String(length=32),
            nullable=True,
        ),
        schema=schema,
    )


def downgrade() -> None:
    """Remove Bayesian columns from the experiments table."""
    schema = "experimentation"

    op.drop_column("experiments", "bayesian_decision", schema=schema)
    op.drop_column("experiments", "bayesian_config", schema=schema)
    op.drop_column("experiments", "bayesian_enabled", schema=schema)
