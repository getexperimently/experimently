"""EP-046: Add LLM/AI Model Evaluation tables

Revision ID: ep046_llm_experiments
Revises: ep036_split_url
Create Date: 2026-03-03 00:00:00.000000

Creates three tables that back the LLM evaluation framework:

  llm_experiments   — experiment-level configuration (task type, primary metric)
  llm_variants      — per-variant model config (provider, model, prompt template)
  llm_evaluations   — individual request/response records with metrics and scores
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Revision identifiers, used by Alembic.
revision: str = "ep046_llm_experiments"
down_revision: Union[str, None] = "ep036_split_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create llm_experiments, llm_variants, and llm_evaluations tables."""

    # Detect schema from Alembic context (falls back to "public")
    bind = op.get_bind()
    schema = bind.dialect.default_schema_name or "public"

    # Try to get schema from environment / config
    import os
    schema = os.environ.get("POSTGRES_SCHEMA", schema)

    # ------------------------------------------------------------------
    # 1. llm_experiments
    # ------------------------------------------------------------------
    op.create_table(
        "llm_experiments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT", "ACTIVE", "PAUSED", "COMPLETED",
                name="llmexperimentstatus",
                schema=schema,
            ),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "task_type",
            sa.Enum(
                "chat_completion", "text_generation", "classification",
                "summarization", "code_generation", "embedding",
                name="llmtasktype",
                schema=schema,
            ),
            nullable=False,
        ),
        sa.Column(
            "evaluation_metric",
            sa.Enum(
                "human_rating", "latency", "cost", "accuracy",
                "relevance", "fluency", "business_metric",
                name="llmevaluationmetric",
                schema=schema,
            ),
            nullable=False,
        ),
        sa.Column(
            "experiment_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.experiments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        schema=schema,
    )
    op.create_index(
        f"{schema}_llm_experiment_status",
        "llm_experiments",
        ["status"],
        schema=schema,
    )
    op.create_index(
        f"{schema}_llm_experiment_task_type",
        "llm_experiments",
        ["task_type"],
        schema=schema,
    )

    # ------------------------------------------------------------------
    # 2. llm_variants
    # ------------------------------------------------------------------
    op.create_table(
        "llm_variants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "llm_experiment_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.llm_experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_control", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("traffic_split", sa.Float, nullable=False, server_default="0.5"),
        sa.Column(
            "provider",
            sa.Enum(
                "openai", "anthropic", "google", "cohere", "mistral", "local",
                name="llmprovider",
                schema=schema,
            ),
            nullable=False,
        ),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("prompt_template", sa.Text, nullable=False),
        sa.Column("temperature", sa.Float, nullable=False, server_default="0.7"),
        sa.Column("max_tokens", sa.Integer, nullable=False, server_default="1000"),
        sa.Column("additional_params", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "traffic_split >= 0.0 AND traffic_split <= 1.0",
            name="check_llm_traffic_split",
        ),
        schema=schema,
    )
    op.create_index(
        f"{schema}_llm_variant_experiment",
        "llm_variants",
        ["llm_experiment_id"],
        schema=schema,
    )

    # ------------------------------------------------------------------
    # 3. llm_evaluations
    # ------------------------------------------------------------------
    op.create_table(
        "llm_evaluations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "llm_experiment_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.llm_experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.llm_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("input_variables", JSONB, nullable=True),
        sa.Column("rendered_prompt", sa.Text, nullable=True),
        sa.Column("model_response", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("human_rating", sa.Float, nullable=True),
        sa.Column("auto_eval_score", sa.Float, nullable=True),
        sa.Column("business_metric_value", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        schema=schema,
    )
    op.create_index(
        f"{schema}_llm_eval_experiment",
        "llm_evaluations",
        ["llm_experiment_id"],
        schema=schema,
    )
    op.create_index(
        f"{schema}_llm_eval_variant",
        "llm_evaluations",
        ["variant_id"],
        schema=schema,
    )
    op.create_index(
        f"{schema}_llm_eval_user",
        "llm_evaluations",
        ["user_id"],
        schema=schema,
    )


def downgrade() -> None:
    """Drop the three LLM evaluation tables and their enums."""
    import os
    bind = op.get_bind()
    schema = os.environ.get(
        "POSTGRES_SCHEMA", bind.dialect.default_schema_name or "public"
    )

    op.drop_table("llm_evaluations", schema=schema)
    op.drop_table("llm_variants", schema=schema)
    op.drop_table("llm_experiments", schema=schema)

    # Drop custom enum types
    for enum_name in ("llmexperimentstatus", "llmtasktype", "llmevaluationmetric", "llmprovider"):
        op.execute(f"DROP TYPE IF EXISTS {schema}.{enum_name}")
