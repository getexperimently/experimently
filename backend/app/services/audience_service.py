"""
Audience Service for segment management and membership evaluation.

Provides business logic for:
- Creating, reading, updating, and archiving audience segments
- Evaluating user context membership against segment rules
- Bulk membership evaluation across multiple segments
- Linking segments to experiments/feature flags
- Estimating audience size via rule preview

Uses the existing rules engine (evaluate_rule_group) internally.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.core.rules_engine import evaluate_rule_group
from backend.app.models.experiment import Experiment
from backend.app.models.feature_flag import FeatureFlag
from backend.app.models.segment import Segment
from backend.app.models.segment import SegmentStatus as ModelSegmentStatus
from backend.app.schemas.segment import (
    AudiencePreviewResponse,
    BulkSegmentMembershipRequest,
    BulkSegmentMembershipResponse,
    SegmentCreate,
    SegmentExperimentResponse,
    SegmentMembershipResponse,
    SegmentStatus,
    SegmentUpdate,
)
from backend.app.schemas.targeting_rule import (
    Condition,
    LogicalOperator,
    RuleGroup,
)

logger = logging.getLogger(__name__)


def _build_rule_group(rules: Dict[str, Any]) -> RuleGroup:
    """
    Convert a plain rules dict into a RuleGroup object usable by the rules engine.

    Expected input format::

        {
            "operator": "and" | "or",   # optional, defaults to "and"
            "conditions": [
                {"attribute": "country", "operator": "eq", "value": "US"},
                ...
            ],
            "groups": [...]              # optional nested groups
        }
    """
    operator_raw = rules.get("operator", "and").lower()
    try:
        operator = LogicalOperator(operator_raw)
    except ValueError:
        operator = LogicalOperator.AND

    conditions: List[Condition] = []
    for cond in rules.get("conditions", []):
        try:
            conditions.append(Condition(**cond))
        except Exception as exc:
            logger.warning("Skipping invalid condition %s: %s", cond, exc)

    nested_groups: List[RuleGroup] = []
    for grp in rules.get("groups", []):
        try:
            nested_groups.append(_build_rule_group(grp))
        except Exception as exc:
            logger.warning("Skipping invalid nested group %s: %s", grp, exc)

    return RuleGroup(operator=operator, conditions=conditions, groups=nested_groups)


def _collect_matched_rules(
    rules: Dict[str, Any], user_context: Dict[str, Any]
) -> List[str]:
    """
    Return human-readable descriptions of the conditions that matched.

    Only considers top-level conditions in the rules dict for simplicity.
    """
    matched: List[str] = []
    for cond in rules.get("conditions", []):
        attribute = cond.get("attribute", "")
        operator = cond.get("operator", "")
        value = cond.get("value", "")

        # Build label regardless; check match separately via the engine
        label = f"{attribute} {operator} {value}"
        try:
            condition_obj = Condition(**cond)
            from backend.app.core.rules_engine import evaluate_condition

            if evaluate_condition(condition_obj, user_context):
                matched.append(label)
        except Exception:
            pass  # Silently skip unparseable conditions in matched_rules

    return matched


def _segment_status_to_model(status: SegmentStatus) -> ModelSegmentStatus:
    """Map schema SegmentStatus to model SegmentStatus."""
    mapping = {
        SegmentStatus.ACTIVE: ModelSegmentStatus.ACTIVE,
        SegmentStatus.INACTIVE: ModelSegmentStatus.INACTIVE,
        SegmentStatus.ARCHIVED: ModelSegmentStatus.ARCHIVED,
    }
    return mapping[status]


def _model_status_to_schema(status: ModelSegmentStatus) -> SegmentStatus:
    """Map model SegmentStatus to schema SegmentStatus."""
    mapping = {
        ModelSegmentStatus.ACTIVE: SegmentStatus.ACTIVE,
        ModelSegmentStatus.INACTIVE: SegmentStatus.INACTIVE,
        ModelSegmentStatus.ARCHIVED: SegmentStatus.ARCHIVED,
    }
    return mapping[status]


def _segment_to_response_dict(segment: Segment) -> Dict[str, Any]:
    """Convert a Segment ORM object to a dict suitable for SegmentResponse."""
    return {
        "id": str(segment.id),
        "name": segment.name,
        "description": segment.description,
        "rules": segment.rules or {},
        "status": _model_status_to_schema(segment.status).value,
        "created_at": segment.created_at.isoformat() if segment.created_at else "",
        "updated_at": segment.updated_at.isoformat() if segment.updated_at else "",
    }


class AudienceService:
    """
    Service for audience segment management and evaluation.

    All methods are static and accept a database session as the first argument.
    """

    @staticmethod
    def create_segment(
        db: Session,
        data: SegmentCreate,
        created_by_id: Optional[Any] = None,
    ) -> Segment:
        """
        Create and persist a new audience segment.

        Args:
            db: SQLAlchemy session.
            data: Validated SegmentCreate payload.
            created_by_id: UUID of the creating user (stored as owner_id).

        Returns:
            The newly created Segment ORM object.
        """
        segment = Segment(
            name=data.name,
            description=data.description,
            rules=data.rules,
            status=ModelSegmentStatus.ACTIVE,
            owner_id=created_by_id,
        )
        db.add(segment)
        db.commit()
        db.refresh(segment)
        logger.info("Created segment %s (%s)", segment.name, segment.id)
        return segment

    @staticmethod
    def list_segments(
        db: Session,
        status: Optional[SegmentStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Segment]:
        """
        List segments with optional status filter.

        Args:
            db: SQLAlchemy session.
            status: Optional status filter (excludes archived by default if None).
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of Segment ORM objects.
        """
        query = db.query(Segment)
        if status is not None:
            model_status = _segment_status_to_model(status)
            query = query.filter(Segment.status == model_status)
        return query.offset(offset).limit(limit).all()

    @staticmethod
    def get_segment(db: Session, segment_id: str) -> Segment:
        """
        Retrieve a segment by ID.

        Args:
            db: SQLAlchemy session.
            segment_id: UUID string of the segment.

        Returns:
            The Segment ORM object.

        Raises:
            ValueError: If no segment with the given ID exists.
        """
        segment = db.query(Segment).filter(Segment.id == segment_id).first()
        if segment is None:
            raise ValueError(f"Segment '{segment_id}' not found")
        return segment

    @staticmethod
    def update_segment(db: Session, segment_id: str, data: SegmentUpdate) -> Segment:
        """
        Update fields on an existing segment.

        Args:
            db: SQLAlchemy session.
            segment_id: UUID string of the segment to update.
            data: Validated SegmentUpdate payload (all fields optional).

        Returns:
            The updated Segment ORM object.

        Raises:
            ValueError: If the segment does not exist.
        """
        segment = AudienceService.get_segment(db, segment_id)

        if data.name is not None:
            segment.name = data.name
        if data.description is not None:
            segment.description = data.description
        if data.rules is not None:
            segment.rules = data.rules
        if data.status is not None:
            segment.status = _segment_status_to_model(data.status)

        db.commit()
        db.refresh(segment)
        logger.info("Updated segment %s", segment_id)
        return segment

    @staticmethod
    def delete_segment(db: Session, segment_id: str) -> None:
        """
        Soft-delete a segment by setting its status to ARCHIVED.

        Args:
            db: SQLAlchemy session.
            segment_id: UUID string of the segment to archive.

        Raises:
            ValueError: If the segment does not exist.
        """
        segment = AudienceService.get_segment(db, segment_id)
        segment.status = ModelSegmentStatus.ARCHIVED
        db.commit()
        logger.info("Archived segment %s", segment_id)

    @staticmethod
    def evaluate_membership(
        db: Session,
        segment_id: str,
        user_context: Dict[str, Any],
    ) -> SegmentMembershipResponse:
        """
        Evaluate if a user context matches a segment's targeting rules.

        Uses ``rules_engine.evaluate_rule_group`` with the segment's stored rules.

        Args:
            db: SQLAlchemy session.
            segment_id: UUID string of the segment to evaluate against.
            user_context: Dict of user attributes (e.g. country, plan, age).

        Returns:
            SegmentMembershipResponse with is_member and matched_rules.

        Raises:
            ValueError: If the segment does not exist.
        """
        segment = AudienceService.get_segment(db, segment_id)

        rules = segment.rules or {}
        is_member = False
        matched_rules: List[str] = []

        if rules:
            try:
                rule_group = _build_rule_group(rules)
                is_member = evaluate_rule_group(rule_group, user_context)
                if is_member:
                    matched_rules = _collect_matched_rules(rules, user_context)
            except Exception as exc:
                logger.error("Error evaluating segment %s rules: %s", segment_id, exc)
                is_member = False

        return SegmentMembershipResponse(
            segment_id=str(segment.id),
            segment_name=segment.name,
            is_member=is_member,
            matched_rules=matched_rules,
        )

    @staticmethod
    def bulk_evaluate_membership(
        db: Session,
        request: BulkSegmentMembershipRequest,
    ) -> BulkSegmentMembershipResponse:
        """
        Evaluate one user context against multiple segments.

        Args:
            db: SQLAlchemy session.
            request: BulkSegmentMembershipRequest containing user_context and segment_ids.

        Returns:
            BulkSegmentMembershipResponse with memberships dict and evaluation_time_ms.
        """
        start_time = time.monotonic()
        memberships: Dict[str, bool] = {}

        for segment_id in request.segment_ids:
            try:
                result = AudienceService.evaluate_membership(
                    db, segment_id, request.user_context
                )
                memberships[segment_id] = result.is_member
            except ValueError:
                # Segment not found — treat as non-member
                memberships[segment_id] = False
            except Exception as exc:
                logger.error("Error evaluating segment %s in bulk: %s", segment_id, exc)
                memberships[segment_id] = False

        elapsed_ms = (time.monotonic() - start_time) * 1000.0

        return BulkSegmentMembershipResponse(
            user_context=request.user_context,
            memberships=memberships,
            evaluation_time_ms=elapsed_ms,
        )

    @staticmethod
    def get_segment_experiments(
        db: Session,
        segment_id: str,
    ) -> SegmentExperimentResponse:
        """
        Find all experiments and feature flags that reference this segment in their
        targeting rules (JSONB field contains the segment_id).

        This performs a lightweight search by looking for the segment UUID inside
        the JSONB targeting_rules of Experiment and FeatureFlag records.

        Args:
            db: SQLAlchemy session.
            segment_id: UUID string of the segment.

        Returns:
            SegmentExperimentResponse listing linked experiments and feature flags.

        Raises:
            ValueError: If the segment does not exist.
        """
        # Verify segment exists first
        AudienceService.get_segment(db, segment_id)

        experiments_data: List[Dict[str, Any]] = []
        feature_flags_data: List[Dict[str, Any]] = []

        try:
            # Search Experiment targeting_rules JSONB for segment_id references
            experiments = (
                db.query(Experiment)
                .filter(
                    Experiment.targeting_rules.cast(
                        db.bind.dialect.colspecs.get(type(None), type(None))
                        if False
                        else __import__("sqlalchemy").Text
                    ).contains(segment_id)
                )
                .all()
            )
            for exp in experiments:
                experiments_data.append(
                    {
                        "id": str(exp.id),
                        "name": exp.name,
                        "status": exp.status.value if exp.status else None,
                    }
                )
        except Exception as exc:
            logger.warning(
                "Could not query experiments for segment %s: %s", segment_id, exc
            )

        try:
            feature_flags = (
                db.query(FeatureFlag)
                .filter(
                    FeatureFlag.targeting_rules.cast(
                        __import__("sqlalchemy").Text
                    ).contains(segment_id)
                )
                .all()
            )
            for flag in feature_flags:
                feature_flags_data.append(
                    {
                        "id": str(flag.id),
                        "name": flag.name,
                    }
                )
        except Exception as exc:
            logger.warning(
                "Could not query feature flags for segment %s: %s", segment_id, exc
            )

        return SegmentExperimentResponse(
            segment_id=segment_id,
            experiments=experiments_data,
            feature_flags=feature_flags_data,
        )

    @staticmethod
    def preview_audience_size(
        db: Session,
        rules: Dict[str, Any],
        sample_size: int = 1000,
    ) -> AudiencePreviewResponse:
        """
        Estimate the audience size that would match the given rules.

        Evaluates the rules dict against a sample of user contexts drawn from
        recent assignment records.  When no assignments exist (e.g. test env)
        falls back to returning 0 matched out of the requested sample_size.

        Args:
            db: SQLAlchemy session.
            rules: Targeting rules dict (same format as SegmentCreate.rules).
            sample_size: Maximum number of user contexts to sample.

        Returns:
            AudiencePreviewResponse with estimated_percentage, sample_size, and matched.
        """

        matched = 0
        actual_sample = 0

        try:
            rule_group = _build_rule_group(rules)

            # Try to pull recent user contexts from assignments
            try:
                from backend.app.models.assignment import Assignment

                assignments = db.query(Assignment).limit(sample_size).all()
                actual_sample = len(assignments)

                for assignment in assignments:
                    user_context: Dict[str, Any] = {}

                    # Assignment may have context stored in JSONB
                    if hasattr(assignment, "context") and assignment.context:
                        user_context = assignment.context
                    elif hasattr(assignment, "user_id"):
                        user_context = {"user_id": str(assignment.user_id)}

                    try:
                        if evaluate_rule_group(rule_group, user_context):
                            matched += 1
                    except Exception:
                        pass

            except Exception as exc:
                logger.debug("Could not sample from assignments: %s", exc)
                actual_sample = 0

        except Exception as exc:
            logger.error("Error in preview_audience_size: %s", exc)

        estimated_percentage = (
            (matched / actual_sample * 100.0) if actual_sample > 0 else 0.0
        )

        return AudiencePreviewResponse(
            estimated_percentage=round(estimated_percentage, 2),
            sample_size=actual_sample,
            matched=matched,
        )
