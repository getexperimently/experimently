# Experiment assignment service
# Analysis and reporting service
# backend/app/services/assignment_service.py
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID

from sqlalchemy import and_, desc, func
from sqlalchemy.orm import Session, joinedload

from backend.app.core.targeting_adapter import (
    expand_context,
    normalise_targeting_rules,
)
from backend.app.models.assignment import Assignment
from backend.app.models.experiment import Experiment, ExperimentStatus, Variant
from backend.app.schemas.targeting_rule import TargetingRules
from backend.app.services.event_service import EventService
from backend.app.services.global_holdout_service import GlobalHoldoutService
from backend.app.services.mutual_exclusion_service import MutualExclusionService
from backend.app.services.rules_evaluation_service import RulesEvaluationService

logger = logging.getLogger(__name__)

# Eligibility reasons returned by ``assign_user`` / ``check_eligibility``.
REASON_ASSIGNED = "assigned"
REASON_HOLDOUT = "holdout"
REASON_MUTUAL_EXCLUSION = "mutual_exclusion"
REASON_TARGETING = "targeting"


def _is_dashboard_rules_shape(raw: Dict[str, Any]) -> bool:
    """True for the dashboard editor shape ``{"logical_operator", "groups": [...]}``."""
    return "rules" not in raw and ("groups" in raw or "logical_operator" in raw)


class AssignmentService:
    """
    Service for managing user assignments to experiment variants.

    This service handles:
    - Assigning users to experiment variants using deterministic hashing
    - Eligibility checks for new users (global holdout, mutual exclusion
      groups, targeting rules)
    - Tracking user assignments
    - Retrieving user assignments for experiments
    - Managing sticky assignments
    """

    def __init__(self, db: Session):
        """Initialize with a database session."""
        self.db = db
        self.event_service = EventService(db)
        self.rules_evaluation_service = RulesEvaluationService()
        self.global_holdout_service = GlobalHoldoutService(db)
        self.mutual_exclusion_service = MutualExclusionService(db)

    def get_assignment(
        self, user_id: str, experiment_id: Union[str, UUID]
    ) -> Optional[Dict[str, Any]]:
        """
        Get a user's assignment for a specific experiment.

        Args:
            user_id: ID of the user
            experiment_id: ID of the experiment

        Returns:
            Dictionary containing the assignment data or None if not found
        """
        assignment = (
            self.db.query(Assignment)
            .filter(
                Assignment.user_id == user_id, Assignment.experiment_id == experiment_id
            )
            .order_by(desc(Assignment.created_at))
            .first()
        )

        if not assignment:
            return None

        # Get variant details
        variant = (
            self.db.query(Variant).filter(Variant.id == assignment.variant_id).first()
        )

        return {
            "id": str(assignment.id),
            "user_id": assignment.user_id,
            "experiment_id": str(assignment.experiment_id),
            "variant_id": str(assignment.variant_id),
            "variant_name": variant.name if variant else None,
            "is_control": variant.is_control if variant else None,
            "created_at": (
                assignment.created_at.isoformat()
                if hasattr(assignment.created_at, "isoformat")
                else assignment.created_at
            ),
            "updated_at": (
                assignment.updated_at.isoformat()
                if hasattr(assignment.updated_at, "isoformat")
                else assignment.updated_at
            ),
        }

    def assign_user(
        self,
        user_id: str,
        experiment_id: Union[str, UUID],
        track_exposure: bool = True,
        override_variant_id: Optional[Union[str, UUID]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Assign a user to an experiment variant.

        New users go through the eligibility checks (global holdout, mutual
        exclusion group, targeting rules — in that order) before a variant is
        chosen.  Ineligible users get no ``Assignment`` row and no exposure
        event; the returned dict carries ``assigned=False``, the ``reason``
        (``holdout`` | ``mutual_exclusion`` | ``targeting``) and the control
        variant so callers can fall back to the default experience.  Existing
        (sticky) assignments always win and are returned unchanged even if the
        user would no longer be eligible.

        Args:
            user_id: ID of the user to assign
            experiment_id: ID of the experiment
            track_exposure: Whether to track an exposure event
            override_variant_id: Optional variant ID to force assignment
            context: Optional context data for targeting

        Returns:
            Dictionary containing the assignment data plus ``assigned`` and
            ``reason``

        Raises:
            ValueError: If the experiment is not active or has issues
        """
        # Get experiment with variants
        experiment = (
            self.db.query(Experiment)
            .options(joinedload(Experiment.variants))
            .filter(Experiment.id == experiment_id)
            .first()
        )

        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        # Check experiment status
        if experiment.status != ExperimentStatus.ACTIVE:
            raise ValueError(
                f"Cannot assign users to experiment with status: {experiment.status}"
            )

        # Check for existing assignment (sticky assignment)
        existing_assignment = (
            self.db.query(Assignment)
            .filter(
                Assignment.user_id == user_id, Assignment.experiment_id == experiment_id
            )
            .order_by(desc(Assignment.created_at))
            .first()
        )

        if existing_assignment:
            # Return existing assignment
            logger.debug(
                f"Using existing assignment for user {user_id} in experiment {experiment_id}"
            )
            assignment_dict = self._assigned_result(user_id, experiment_id)

            # Optionally track exposure event
            if track_exposure:
                self.event_service.track_exposure(
                    user_id=user_id,
                    experiment_id=str(experiment_id),
                    variant_id=str(existing_assignment.variant_id),
                    properties=context,
                )

            return assignment_dict

        # Eligibility gate for new users: holdout -> mutual exclusion -> targeting
        eligibility = self.check_eligibility(user_id, experiment, context)
        if not eligibility["eligible"]:
            logger.info(
                f"User {user_id} not eligible for experiment {experiment_id}: "
                f"{eligibility['reason']} ({eligibility.get('detail')})"
            )
            return self._ineligible_result(user_id, experiment, eligibility)

        # Determine variant assignment
        if override_variant_id:
            # Use override if provided (useful for forcing assignment or testing)
            variant_id = override_variant_id

            # Verify override variant is valid for this experiment
            variant_valid = any(
                v.id == override_variant_id for v in experiment.variants
            )
            if not variant_valid:
                raise ValueError(
                    f"Override variant {override_variant_id} not valid for experiment {experiment_id}"
                )
        else:
            # Use deterministic hashing to assign variant
            variant_id = self._hash_user_to_variant(user_id, experiment)

        # Create new assignment
        assignment = Assignment(
            user_id=user_id,
            experiment_id=experiment_id,
            variant_id=variant_id,
        )

        self.db.add(assignment)
        self.db.commit()
        self.db.refresh(assignment)

        logger.info(
            f"Assigned user {user_id} to variant {variant_id} in experiment {experiment_id}"
        )

        # Track exposure event if requested
        if track_exposure:
            self.event_service.track_exposure(
                user_id=user_id,
                experiment_id=str(experiment_id),
                variant_id=str(variant_id),
                properties=context,
            )

        # Get full assignment details
        return self._assigned_result(user_id, experiment_id)

    # ------------------------------------------------------------------
    # Eligibility (global holdout, mutual exclusion, targeting)
    # ------------------------------------------------------------------

    def check_eligibility(
        self,
        user_id: str,
        experiment: Experiment,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Decide whether a *new* user may be assigned to ``experiment``.

        Checks run in order and the first failure wins:

        1. global holdout — an active ``GlobalHoldout`` that buckets the user
           (reason ``holdout``);
        2. mutual exclusion — the experiment belongs to a group and the group's
           consistent hashing selects a different experiment for the user
           (reason ``mutual_exclusion``);
        3. targeting — the experiment has targeting rules and the user context
           does not match them (reason ``targeting``).

        Sticky assignments are handled by ``assign_user`` before this runs.

        Returns:
            ``{"eligible": bool, "reason": str, "detail": Optional[str]}``
            (``reason`` is ``assigned`` when eligible).
        """
        # 1. Global holdout
        (
            in_holdout,
            holdout_percentage,
            bucket,
        ) = self.global_holdout_service.is_user_in_holdout(user_id)
        if in_holdout:
            return {
                "eligible": False,
                "reason": REASON_HOLDOUT,
                "detail": (
                    f"User is in the global holdout "
                    f"({holdout_percentage}%, bucket {bucket})"
                ),
            }

        # 2. Mutual exclusion group
        group_id = getattr(experiment, "mutual_exclusion_group_id", None)
        if group_id:
            if not self.mutual_exclusion_service.is_user_eligible_for_experiment(
                user_id, experiment.id
            ):
                return {
                    "eligible": False,
                    "reason": REASON_MUTUAL_EXCLUSION,
                    "detail": (
                        f"Mutual exclusion group {group_id} selected another "
                        f"experiment (or none) for this user"
                    ),
                }

        # 3. Targeting rules
        if getattr(experiment, "targeting_rules", None):
            targeting_context = self._build_targeting_context(user_id, context)
            targeting = self._evaluate_experiment_targeting(
                experiment, targeting_context
            )
            if not targeting["eligible"]:
                return {
                    "eligible": False,
                    "reason": REASON_TARGETING,
                    "detail": targeting.get("reason"),
                }

        return {"eligible": True, "reason": REASON_ASSIGNED, "detail": None}

    @staticmethod
    def _build_targeting_context(
        user_id: str, context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Request context + ``user_id`` (for rollout bucketing), expanded with the
        shared alias rule (``country`` also answers ``user.country`` etc.)."""
        raw = dict(context or {})
        raw.setdefault("user_id", user_id)
        return expand_context(raw)

    def _assigned_result(
        self, user_id: str, experiment_id: Union[str, UUID]
    ) -> Dict[str, Any]:
        """``get_assignment`` result tagged as an actual assignment."""
        result = self.get_assignment(user_id, experiment_id) or {}
        result["assigned"] = True
        result["reason"] = REASON_ASSIGNED
        return result

    @staticmethod
    def _control_variant(experiment: Experiment) -> Variant:
        """The experiment's control variant (first variant when none is flagged)."""
        variants = list(experiment.variants or [])
        if not variants:
            raise ValueError(f"Experiment {experiment.id} has no variants")
        return next((v for v in variants if v.is_control), variants[0])

    def _ineligible_result(
        self, user_id: str, experiment: Experiment, eligibility: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Assignment-shaped dict for a user that was not assigned.

        Carries the control variant so SDKs (which treat the response as the
        variant) render the default experience; ``id``/timestamps are ``None``
        because no ``Assignment`` row exists.
        """
        control = self._control_variant(experiment)
        return {
            "id": None,
            "user_id": user_id,
            "experiment_id": str(experiment.id),
            "variant_id": str(control.id),
            "variant_name": control.name,
            "is_control": bool(control.is_control),
            "created_at": None,
            "updated_at": None,
            "assigned": False,
            "reason": eligibility["reason"],
            "detail": eligibility.get("detail"),
        }

    def get_user_assignments(
        self, user_id: str, active_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get all assignments for a user.

        Args:
            user_id: ID of the user
            active_only: If True, only return assignments for active experiments

        Returns:
            List of assignment dictionaries
        """
        # Base query
        query = self.db.query(Assignment).filter(Assignment.user_id == user_id)

        if active_only:
            # Join with experiments to filter by status
            query = query.join(
                Experiment, Assignment.experiment_id == Experiment.id
            ).filter(Experiment.status == ExperimentStatus.ACTIVE)

        # Get latest assignment for each experiment
        subq = (
            self.db.query(
                Assignment.experiment_id,
                func.max(Assignment.created_at).label("latest_assignment"),
            )
            .filter(Assignment.user_id == user_id)
            .group_by(Assignment.experiment_id)
            .subquery()
        )

        query = query.join(
            subq,
            and_(
                Assignment.experiment_id == subq.c.experiment_id,
                Assignment.created_at == subq.c.latest_assignment,
            ),
        )

        assignments = query.all()

        # Format results
        results = []
        for assignment in assignments:
            # Get variant details
            variant = (
                self.db.query(Variant)
                .filter(Variant.id == assignment.variant_id)
                .first()
            )

            # Get experiment details
            experiment = (
                self.db.query(Experiment)
                .filter(Experiment.id == assignment.experiment_id)
                .first()
            )

            results.append(
                {
                    "id": str(assignment.id),
                    "user_id": assignment.user_id,
                    "experiment_id": str(assignment.experiment_id),
                    "experiment_name": experiment.name if experiment else None,
                    "variant_id": str(assignment.variant_id),
                    "variant_name": variant.name if variant else None,
                    "is_control": variant.is_control if variant else None,
                    "created_at": (
                        assignment.created_at.isoformat()
                        if hasattr(assignment.created_at, "isoformat")
                        else assignment.created_at
                    ),
                }
            )

        return results

    def bulk_assign_users(
        self,
        user_ids: List[str],
        experiment_id: Union[str, UUID],
        track_exposure: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Assign multiple users to an experiment in bulk.

        Args:
            user_ids: List of user IDs to assign
            experiment_id: ID of the experiment
            track_exposure: Whether to track exposure events
            context: Optional context data for targeting

        Returns:
            Dictionary with counts of assignments
        """
        if not user_ids:
            return {"assigned": 0, "skipped": 0, "errors": 0}

        # Get experiment to verify it exists and is active
        experiment = (
            self.db.query(Experiment)
            .options(joinedload(Experiment.variants))
            .filter(Experiment.id == experiment_id)
            .first()
        )

        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        # Check experiment status
        if experiment.status != ExperimentStatus.ACTIVE:
            raise ValueError(
                f"Cannot assign users to experiment with status: {experiment.status}"
            )

        # Track counts
        assigned = 0
        skipped = 0
        errors = 0

        # Process each user
        for user_id in user_ids:
            try:
                # Check for existing assignment
                existing_assignment = (
                    self.db.query(Assignment)
                    .filter(
                        Assignment.user_id == user_id,
                        Assignment.experiment_id == experiment_id,
                    )
                    .first()
                )

                if existing_assignment:
                    # Skip users who already have an assignment
                    skipped += 1
                    continue

                # Assign user
                variant_id = self._hash_user_to_variant(user_id, experiment)

                # Create new assignment
                assignment = Assignment(
                    user_id=user_id,
                    experiment_id=experiment_id,
                    variant_id=variant_id,
                )

                self.db.add(assignment)

                # Track exposure if requested.  If this fails the user is
                # reported as an error and the pending assignment is dropped
                # so the counts add up and no half-tracked row is committed.
                if track_exposure:
                    try:
                        self.event_service.track_exposure(
                            user_id=user_id,
                            experiment_id=str(experiment_id),
                            variant_id=str(variant_id),
                            properties=context,
                        )
                    except Exception:
                        self.db.expunge(assignment)
                        raise

                assigned += 1

            except Exception as e:
                logger.error(
                    f"Error assigning user {user_id} to experiment {experiment_id}: {e!s}"
                )
                errors += 1

        # Commit all assignments in a single transaction
        self.db.commit()

        logger.info(
            f"Bulk assigned {assigned} users to experiment {experiment_id} (skipped: {skipped}, errors: {errors})"
        )

        return {"assigned": assigned, "skipped": skipped, "errors": errors}

    def assign_user_with_targeting(
        self,
        user_id: str,
        experiment_id: Union[str, UUID],
        user_context: Dict[str, Any],
        track_exposure: bool = True,
        validate_attributes: bool = True,
    ) -> Dict[str, Any]:
        """
        Assign a user to an experiment variant using targeting rules.

        Args:
            user_id: ID of the user to assign
            experiment_id: ID of the experiment
            user_context: User context for targeting evaluation
            track_exposure: Whether to track an exposure event
            validate_attributes: Whether to validate user attributes

        Returns:
            Dictionary containing the assignment data and targeting info

        Raises:
            ValueError: If the experiment is not active or targeting fails
        """
        # Get experiment with variants
        experiment = (
            self.db.query(Experiment)
            .options(joinedload(Experiment.variants))
            .filter(Experiment.id == experiment_id)
            .first()
        )

        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        # Check experiment status
        if experiment.status != ExperimentStatus.ACTIVE:
            raise ValueError(
                f"Cannot assign users to experiment with status: {experiment.status}"
            )

        # Ensure user_id is in context
        if "user_id" not in user_context:
            user_context["user_id"] = user_id

        # Check for existing assignment (sticky assignment)
        existing_assignment = (
            self.db.query(Assignment)
            .filter(
                Assignment.user_id == user_id, Assignment.experiment_id == experiment_id
            )
            .order_by(desc(Assignment.created_at))
            .first()
        )

        if existing_assignment:
            logger.debug(
                f"Using existing assignment for user {user_id} in experiment {experiment_id}"
            )
            assignment_dict = self.get_assignment(user_id, experiment_id)

            # Add targeting info
            assignment_dict.update(
                {
                    "targeting_matched": True,
                    "targeting_rule_id": "existing_assignment",
                    "user_context_validated": True,
                }
            )

            # Optionally track exposure event
            if track_exposure:
                self.event_service.track_exposure(
                    user_id=user_id,
                    experiment_id=str(experiment_id),
                    variant_id=str(existing_assignment.variant_id),
                    properties=user_context,
                )

            return assignment_dict

        # Evaluate targeting rules if experiment has them
        targeting_result = self._evaluate_experiment_targeting(
            experiment, user_context, validate_attributes
        )

        if not targeting_result["eligible"]:
            # User doesn't match targeting criteria
            logger.info(
                f"User {user_id} not eligible for experiment {experiment_id}: {targeting_result['reason']}"
            )
            return {
                "assignment": None,
                "targeting_matched": False,
                "targeting_rule_id": None,
                "reason": targeting_result["reason"],
                "user_context_validated": targeting_result.get(
                    "validation_passed", True
                ),
                "evaluation_metrics": targeting_result.get("metrics"),
            }

        # Determine variant assignment
        variant_id = self._hash_user_to_variant(user_id, experiment)

        # Create new assignment
        assignment = Assignment(
            user_id=user_id,
            experiment_id=experiment_id,
            variant_id=variant_id,
        )

        self.db.add(assignment)
        self.db.commit()
        self.db.refresh(assignment)

        logger.info(
            f"Assigned user {user_id} to variant {variant_id} in experiment {experiment_id} via targeting"
        )

        # Track exposure event if requested
        if track_exposure:
            # Include targeting information in exposure event
            exposure_properties = user_context.copy()
            exposure_properties.update(
                {
                    "targeting_rule_id": targeting_result.get("rule_id"),
                    "targeting_matched": True,
                }
            )

            self.event_service.track_exposure(
                user_id=user_id,
                experiment_id=str(experiment_id),
                variant_id=str(variant_id),
                properties=exposure_properties,
            )

        # Get full assignment details and add targeting info
        assignment_dict = self.get_assignment(user_id, experiment_id)
        assignment_dict.update(
            {
                "targeting_matched": True,
                "targeting_rule_id": targeting_result.get("rule_id"),
                "user_context_validated": targeting_result.get(
                    "validation_passed", True
                ),
                "evaluation_metrics": targeting_result.get("metrics"),
            }
        )

        return assignment_dict

    def _evaluate_experiment_targeting(
        self,
        experiment: Experiment,
        user_context: Dict[str, Any],
        validate_attributes: bool = True,
    ) -> Dict[str, Any]:
        """
        Evaluate if a user meets experiment targeting criteria.

        Args:
            experiment: The experiment model
            user_context: User context for evaluation
            validate_attributes: Whether to validate attributes

        Returns:
            Dictionary with targeting evaluation results
        """
        try:
            # Check if experiment has targeting rules
            if (
                not hasattr(experiment, "targeting_rules")
                or not experiment.targeting_rules
            ):
                # No targeting rules - allow all users
                return {
                    "eligible": True,
                    "rule_id": None,
                    "reason": "No targeting rules defined",
                    "validation_passed": True,
                }

            # Parse targeting rules (native TargetingRules or dashboard shape)
            targeting_rules, skip_reason = self._coerce_targeting_rules(
                experiment.targeting_rules
            )
            if targeting_rules is None:
                return {
                    "eligible": True,
                    "rule_id": None,
                    "reason": skip_reason or "No targeting rules defined",
                    "validation_passed": True,
                }

            # Evaluate rules with validation
            (
                matched_rule,
                metrics,
            ) = self.rules_evaluation_service.evaluate_rules_with_validation(
                targeting_rules=targeting_rules,
                user_context=user_context,
                validate_attributes=validate_attributes,
                track_metrics=True,
            )

            if matched_rule:
                return {
                    "eligible": True,
                    "rule_id": matched_rule.id,
                    "reason": f"Matched targeting rule: {matched_rule.name or matched_rule.id}",
                    "validation_passed": metrics.error is None if metrics else True,
                    "metrics": metrics,
                }
            else:
                return {
                    "eligible": False,
                    "rule_id": None,
                    "reason": "No targeting rules matched",
                    "validation_passed": metrics.error is None if metrics else True,
                    "metrics": metrics,
                }

        except Exception as e:
            logger.error(f"Error evaluating experiment targeting: {e!s}")
            return {
                "eligible": False,
                "rule_id": None,
                "reason": f"Targeting evaluation error: {e!s}",
                "validation_passed": False,
            }

    @staticmethod
    def _coerce_targeting_rules(
        raw: Any,
    ) -> Tuple[Optional[TargetingRules], Optional[str]]:
        """
        Turn the stored ``targeting_rules`` value into a ``TargetingRules``.

        Accepts a JSON string, the native ``TargetingRules`` dict (has ``rules``),
        the dashboard editor shape (``{"logical_operator", "groups": [...]}``,
        converted by ``targeting_adapter.normalise_targeting_rules``) or an
        existing ``TargetingRules`` instance.

        Returns:
            ``(rules, None)`` when there is something to evaluate, or
            ``(None, why)`` when the value carries no evaluable rules — callers
            treat that as "no targeting rules" (everyone eligible).
        """
        no_rules = "Targeting rules contain no evaluable rules"
        rules: Any
        if isinstance(raw, TargetingRules):
            rules = raw
        else:
            if isinstance(raw, str):
                raw = json.loads(raw)

            if isinstance(raw, dict):
                if _is_dashboard_rules_shape(raw):
                    # The adapter returns None for dashboard rules it cannot
                    # convert (and logs why); that means "no rules", not "nobody".
                    rules = normalise_targeting_rules(raw)
                    if rules is None:
                        return None, no_rules
                else:
                    rules = TargetingRules(**raw)
            elif isinstance(raw, list):
                # Legacy feature-flag list shape; never valid for experiments.
                logger.warning(
                    "List-shaped experiment targeting rules are not supported; "
                    "treating as no targeting rules"
                )
                return None, "List-shaped targeting rules ignored"
            else:
                # Assume it's already a TargetingRules-like object
                rules = raw

        if not rules.rules and rules.default_rule is None:
            return None, no_rules
        return rules, None

    def get_targeting_performance_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics for targeting evaluations.

        Returns:
            Dictionary with performance metrics
        """
        return self.rules_evaluation_service.get_performance_stats()

    def clear_targeting_metrics(self):
        """Clear collected targeting metrics."""
        self.rules_evaluation_service.clear_metrics()

    def reassign_user(
        self,
        user_id: str,
        experiment_id: Union[str, UUID],
        variant_id: Optional[Union[str, UUID]] = None,
        track_exposure: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Reassign a user to a new variant in an experiment.

        Args:
            user_id: ID of the user to reassign
            experiment_id: ID of the experiment
            variant_id: Optional variant ID to force assignment
            track_exposure: Whether to track an exposure event
            context: Optional context data

        Returns:
            Dictionary containing the new assignment data
        """
        # Get experiment to verify it exists and is active
        experiment = (
            self.db.query(Experiment)
            .options(joinedload(Experiment.variants))
            .filter(Experiment.id == experiment_id)
            .first()
        )

        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        # Determine variant assignment
        if variant_id:
            # Verify variant is valid for this experiment
            variant_valid = any(v.id == variant_id for v in experiment.variants)
            if not variant_valid:
                raise ValueError(
                    f"Variant {variant_id} not valid for experiment {experiment_id}"
                )
        else:
            # Use deterministic hashing to reassign variant
            variant_id = self._hash_user_to_variant(user_id, experiment)

        # Update the existing assignment in place when there is one: the
        # (experiment_id, user_id) pair is unique, so inserting a second row
        # would violate the index instead of reassigning the user.
        assignment = (
            self.db.query(Assignment)
            .filter(
                Assignment.user_id == user_id,
                Assignment.experiment_id == experiment_id,
            )
            .first()
        )
        if assignment:
            assignment.variant_id = variant_id
            if context is not None:
                assignment.context = context
        else:
            assignment = Assignment(
                user_id=user_id,
                experiment_id=experiment_id,
                variant_id=variant_id,
                context=context,
            )
            self.db.add(assignment)

        self.db.commit()
        self.db.refresh(assignment)

        logger.info(
            f"Reassigned user {user_id} to variant {variant_id} in experiment {experiment_id}"
        )

        # Track exposure event if requested
        if track_exposure:
            self.event_service.track_exposure(
                user_id=user_id,
                experiment_id=str(experiment_id),
                variant_id=str(variant_id),
                properties=context,
            )

        # Get full assignment details
        return self.get_assignment(user_id, experiment_id)

    def _hash_user_to_variant(
        self, user_id: str, experiment: Experiment
    ) -> Union[str, UUID]:
        """
        Determine variant assignment using deterministic hashing.

        This ensures that the same user will always be assigned to the same variant
        for a given experiment, based on their user ID and the experiment ID.

        Args:
            user_id: ID of the user to assign
            experiment: Experiment model object with variants

        Returns:
            ID of the assigned variant
        """
        if not experiment.variants:
            raise ValueError(f"Experiment {experiment.id} has no variants")

        # Create a hash using user ID and experiment ID
        hash_input = f"{user_id}:{experiment.id}"
        hash_value = int(
            hashlib.md5(hash_input.encode(), usedforsecurity=False).hexdigest(), 16
        )

        # Get variants with their traffic allocations
        variants = experiment.variants

        # Create cumulative distribution based on traffic allocation
        total = 0
        distribution = []
        for variant in variants:
            total += variant.traffic_allocation
            distribution.append((total, variant.id))

        # Normalize hash to be within range [0, 100)
        bucket = hash_value % 100

        # Find the assigned variant
        for threshold, variant_id in distribution:
            if bucket < threshold:
                return variant_id

        # Fallback to last variant (should not happen if allocations sum to 100)
        return variants[-1].id if variants else None

    def delete_assignments_by_experiment(self, experiment_id: Union[str, UUID]) -> int:
        """
        Delete all assignments for an experiment.

        Args:
            experiment_id: ID of the experiment

        Returns:
            Number of assignments deleted
        """
        # Count assignments before deletion
        count_query = self.db.query(func.count(Assignment.id)).filter(
            Assignment.experiment_id == experiment_id
        )
        count = count_query.scalar() or 0

        # Delete assignments
        delete_query = self.db.query(Assignment).filter(
            Assignment.experiment_id == experiment_id
        )
        delete_query.delete(synchronize_session=False)

        self.db.commit()

        logger.info(f"Deleted {count} assignments for experiment {experiment_id}")
        return count
