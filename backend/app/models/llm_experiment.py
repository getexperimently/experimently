"""
LLM/AI Model Evaluation models for EP-046.

Provides SQLAlchemy models for LLM experiments, variants, and individual
evaluation runs. Enables comparing prompt versions, model variants (GPT-4 vs
Claude vs Gemini), agent configs, and system prompts against real business
metrics.
"""

import enum
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SQLAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship

from backend.app.models.base import Base, BaseModel
from backend.app.core.database_config import get_schema_name


class LLMExperimentStatus(enum.Enum):
    """Status of an LLM experiment."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class LLMTaskType(enum.Enum):
    """Types of LLM tasks that can be evaluated."""

    CHAT_COMPLETION = "chat_completion"
    TEXT_GENERATION = "text_generation"
    CLASSIFICATION = "classification"
    SUMMARIZATION = "summarization"
    CODE_GENERATION = "code_generation"
    EMBEDDING = "embedding"


class LLMEvaluationMetric(enum.Enum):
    """Primary evaluation metric for an LLM experiment."""

    HUMAN_RATING = "human_rating"
    LATENCY = "latency"
    COST = "cost"
    ACCURACY = "accuracy"
    RELEVANCE = "relevance"
    FLUENCY = "fluency"
    BUSINESS_METRIC = "business_metric"


class LLMProvider(enum.Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    COHERE = "cohere"
    MISTRAL = "mistral"
    LOCAL = "local"


class LLMExperiment(Base, BaseModel):
    """
    LLM experiment model for comparing prompt versions and model variants.

    Extends the platform's existing experiment concept with LLM-specific
    fields for task type, evaluation metrics, and provider configuration.
    """

    __tablename__ = "llm_experiments"

    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    status = Column(
        SQLAEnum(LLMExperimentStatus),
        default=LLMExperimentStatus.DRAFT,
        nullable=False,
        index=True,
    )
    task_type = Column(
        SQLAEnum(LLMTaskType),
        nullable=False,
    )
    evaluation_metric = Column(
        SQLAEnum(LLMEvaluationMetric),
        nullable=False,
    )

    # Optional link to the standard Experiment for statistical analysis
    experiment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.experiments.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Owner / creator
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    variants = relationship(
        "LLMVariant",
        back_populates="llm_experiment",
        cascade="all, delete-orphan",
    )
    evaluations = relationship(
        "LLMEvaluation",
        back_populates="llm_experiment",
        cascade="all, delete-orphan",
    )

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            Index(f"{schema_name}_llm_experiment_status", "status"),
            Index(f"{schema_name}_llm_experiment_task_type", "task_type"),
            Index(f"{schema_name}_llm_experiment_created_by", "created_by"),
            {"schema": schema_name},
        )

    def __repr__(self):
        return f"<LLMExperiment {self.name} ({self.status})>"


class LLMVariant(Base, BaseModel):
    """
    A variant in an LLM experiment — defines the model, prompt, and parameters.
    """

    __tablename__ = "llm_variants"

    llm_experiment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.llm_experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(200), nullable=False)
    is_control = Column(Boolean, default=False, nullable=False)
    traffic_split = Column(Float, default=0.5, nullable=False)

    # Model config
    provider = Column(
        SQLAEnum(LLMProvider),
        nullable=False,
    )
    model_name = Column(String(200), nullable=False)
    system_prompt = Column(Text, default="")
    prompt_template = Column(Text, nullable=False)
    temperature = Column(Float, default=0.7)
    max_tokens = Column(Integer, default=1000)
    additional_params = Column(JSONB, default=dict)

    # Relationships
    llm_experiment = relationship("LLMExperiment", back_populates="variants")
    evaluations = relationship(
        "LLMEvaluation",
        back_populates="variant",
        cascade="all, delete-orphan",
    )

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            Index(
                f"{schema_name}_llm_variant_experiment",
                "llm_experiment_id",
            ),
            CheckConstraint(
                "traffic_split >= 0.0 AND traffic_split <= 1.0",
                name="check_llm_traffic_split",
            ),
            {"schema": schema_name},
        )

    def __repr__(self):
        return f"<LLMVariant {self.name} ({self.provider}/{self.model_name})>"


class LLMEvaluation(Base, BaseModel):
    """
    An individual evaluation run: one request/response pair with metrics.

    Stores the rendered prompt, model response, latency, token counts,
    estimated cost, and any evaluation scores (human rating, LLM-as-judge,
    business metric).
    """

    __tablename__ = "llm_evaluations"

    llm_experiment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.llm_experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.llm_variants.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(String(255), nullable=False)

    # Request / Response
    input_variables = Column(JSONB, default=dict)
    rendered_prompt = Column(Text, default="")
    model_response = Column(Text, default="")

    # Performance metrics
    latency_ms = Column(Integer, default=0)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    estimated_cost_usd = Column(Float, default=0.0)

    # Evaluation scores (nullable — filled in post-hoc)
    human_rating = Column(Float, nullable=True)       # 1–5 scale
    auto_eval_score = Column(Float, nullable=True)    # LLM-as-judge: 0–1
    business_metric_value = Column(Float, nullable=True)  # downstream metric

    # Relationships
    llm_experiment = relationship("LLMExperiment", back_populates="evaluations")
    variant = relationship("LLMVariant", back_populates="evaluations")

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            Index(
                f"{schema_name}_llm_eval_experiment",
                "llm_experiment_id",
            ),
            Index(f"{schema_name}_llm_eval_variant", "variant_id"),
            Index(f"{schema_name}_llm_eval_user", "user_id"),
            {"schema": schema_name},
        )

    def __repr__(self):
        return f"<LLMEvaluation exp={self.llm_experiment_id} user={self.user_id}>"
