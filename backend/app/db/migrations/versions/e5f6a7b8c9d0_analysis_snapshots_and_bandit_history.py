"""Add analysis_snapshots, bandit_state_history and bandit_states provenance

P0 "statistical credibility": every analysis the platform serves is recorded
with the engine version and the RNG seed / sample count that produced it.

* ``analysis_snapshots`` — one row per fresh computation from the results
  endpoints (frequentist, bayesian, cuped, sequential) and per bandit tick.
* ``bandit_state_history`` — one row per (tick, variant) with the posterior,
  weight and counts the bandit used.
* ``bandit_states`` gains ``seed``, ``n_samples``, ``engine_version`` so the
  status endpoint can echo the provenance of the current weights.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-11
"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")


def upgrade() -> None:
    # ── analysis_snapshots ───────────────────────────────────────────────────
    op.create_table(
        "analysis_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("engine_version", sa.String(length=20), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=True),
        sa.Column("n_samples", sa.Integer(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            [f"{_SCHEMA}.experiments.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "kind IN ('frequentist', 'bayesian', 'cuped', 'sequential', 'bandit')",
            name="check_analysis_snapshot_kind",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_analysis_snapshots_created_at",
        "analysis_snapshots",
        ["created_at"],
        schema=_SCHEMA,
    )
    op.create_index(
        f"{_SCHEMA}_analysis_snapshot_exp_kind_created",
        "analysis_snapshots",
        ["experiment_id", "kind", "created_at"],
        schema=_SCHEMA,
    )

    # ── bandit_state_history ─────────────────────────────────────────────────
    op.create_table(
        "bandit_state_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("algorithm", sa.String(length=50), nullable=False),
        sa.Column("alpha", sa.Float(), nullable=False),
        sa.Column("beta", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("successes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pulls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("seed", sa.BigInteger(), nullable=True),
        sa.Column("n_samples", sa.Integer(), nullable=True),
        sa.Column("engine_version", sa.String(length=20), nullable=False),
        sa.Column("tick_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            [f"{_SCHEMA}.experiments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            [f"{_SCHEMA}.variants.id"],
            ondelete="CASCADE",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_bandit_state_history_created_at",
        "bandit_state_history",
        ["created_at"],
        schema=_SCHEMA,
    )
    op.create_index(
        f"{_SCHEMA}_bandit_history_exp_tick",
        "bandit_state_history",
        ["experiment_id", "tick_at"],
        schema=_SCHEMA,
    )

    # ── bandit_states provenance columns ─────────────────────────────────────
    op.add_column(
        "bandit_states",
        sa.Column("seed", sa.BigInteger(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "bandit_states",
        sa.Column("n_samples", sa.Integer(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "bandit_states",
        sa.Column("engine_version", sa.String(length=20), nullable=True),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("bandit_states", "engine_version", schema=_SCHEMA)
    op.drop_column("bandit_states", "n_samples", schema=_SCHEMA)
    op.drop_column("bandit_states", "seed", schema=_SCHEMA)

    op.drop_index(
        f"{_SCHEMA}_bandit_history_exp_tick",
        table_name="bandit_state_history",
        schema=_SCHEMA,
    )
    op.drop_index(
        f"ix_{_SCHEMA}_bandit_state_history_created_at",
        table_name="bandit_state_history",
        schema=_SCHEMA,
    )
    op.drop_table("bandit_state_history", schema=_SCHEMA)

    op.drop_index(
        f"{_SCHEMA}_analysis_snapshot_exp_kind_created",
        table_name="analysis_snapshots",
        schema=_SCHEMA,
    )
    op.drop_index(
        f"ix_{_SCHEMA}_analysis_snapshots_created_at",
        table_name="analysis_snapshots",
        schema=_SCHEMA,
    )
    op.drop_table("analysis_snapshots", schema=_SCHEMA)
