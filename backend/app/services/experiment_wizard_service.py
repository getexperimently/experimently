"""
Experiment Wizard Service — step-by-step guided experiment creation.

Stores draft state in memory (or DB in future) for multi-step wizard UX.
Provides validation for each wizard step and builds the final experiment
payload ready for submission to ExperimentService.
"""
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Wizard type -> ``ExperimentType`` value used by ``ExperimentCreate``.
_EXPERIMENT_TYPE_MAP: Dict[str, str] = {
    "ab": "a_b",
    "a_b": "a_b",
    "multivariate": "mv",
    "bandit": "bandit",
    "feature_flag_rollout": "a_b",
}

EXPERIMENT_TYPES = {"ab", "multivariate", "feature_flag_rollout"}

WIZARD_STEPS = [
    "choose_type",
    "define_hypothesis",
    "targeting",
    "sample_size",
    "review",
]


@dataclass
class WizardValidationResult:
    """Result of validating a single wizard step."""

    is_valid: bool
    errors: List[str] = field(default_factory=list)


@dataclass
class WizardDraft:
    """In-progress wizard draft accumulating data across steps."""

    id: str
    user_id: str
    current_step: str
    experiment_type: Optional[str] = None
    hypothesis: Optional[str] = None
    primary_metric_id: Optional[str] = None
    guardrail_metric_ids: List[str] = field(default_factory=list)
    targeting_rules: List[Dict] = field(default_factory=list)
    baseline_rate: Optional[float] = None
    mde: Optional[float] = None
    name: Optional[str] = None
    description: Optional[str] = None


# In-memory draft store (production would use Redis or DB).
_drafts: Dict[str, WizardDraft] = {}


class ExperimentWizardService:
    """Service for managing the no-code experiment creation wizard."""

    @staticmethod
    def validate_wizard_step(step: str, data: Dict[str, Any]) -> WizardValidationResult:
        """Validate the data submitted for a specific wizard step.

        Args:
            step: The wizard step name (one of WIZARD_STEPS).
            data: The step-specific data payload to validate.

        Returns:
            WizardValidationResult with is_valid flag and any error messages.
        """
        errors: List[str] = []

        if step == "choose_type":
            experiment_type = data.get("experiment_type", "")
            if experiment_type not in EXPERIMENT_TYPES:
                errors.append(
                    f"experiment_type must be one of {sorted(EXPERIMENT_TYPES)}"
                )

        elif step == "define_hypothesis":
            hypothesis = data.get("hypothesis") or ""
            if len(hypothesis) < 10:
                errors.append("hypothesis must be at least 10 characters")
            if not data.get("primary_metric_id"):
                errors.append("primary_metric_id is required")

        elif step == "targeting":
            # Empty rules are valid — experiment targets all users.
            pass

        elif step == "sample_size":
            baseline_rate = data.get("baseline_rate")
            mde = data.get("mde")

            if baseline_rate is None or not (0 < baseline_rate < 1):
                errors.append("baseline_rate must be between 0 and 1 (exclusive)")
            if mde is None or not (0 < mde < 1):
                errors.append("mde must be between 0 and 1 (exclusive)")

        elif step == "review":
            required_fields = ["experiment_type", "hypothesis", "primary_metric_id"]
            for required_field in required_fields:
                if not data.get(required_field):
                    errors.append(f"{required_field} is required")

        return WizardValidationResult(is_valid=len(errors) == 0, errors=errors)

    @staticmethod
    def create_draft(user_id: str, experiment_type: str = "ab") -> WizardDraft:
        """Create a new wizard draft for the given user.

        Args:
            user_id: The ID of the user creating the draft.
            experiment_type: Initial experiment type; defaults to 'ab'.

        Returns:
            A new WizardDraft starting at the 'choose_type' step.
        """
        draft = WizardDraft(
            id=str(uuid.uuid4()),
            user_id=user_id,
            current_step="choose_type",
            experiment_type=experiment_type,
        )
        _drafts[draft.id] = draft
        return draft

    @staticmethod
    def get_draft(draft_id: str) -> Optional[WizardDraft]:
        """Retrieve a draft by its ID.

        Args:
            draft_id: The UUID string of the draft.

        Returns:
            The WizardDraft if found, otherwise None.
        """
        return _drafts.get(draft_id)

    @staticmethod
    def delete_draft(draft_id: str) -> bool:
        """Drop a draft. Returns True when one was removed."""
        return _drafts.pop(draft_id, None) is not None

    @staticmethod
    def update_draft(
        draft_id: str, step: str, data: Dict[str, Any]
    ) -> Optional[WizardDraft]:
        """Update a draft with data from the given step and advance to the next step.

        Args:
            draft_id: The ID of the draft to update.
            step: The wizard step being completed.
            data: The data payload for the step.

        Returns:
            The updated WizardDraft or None if the draft was not found.
        """
        draft = _drafts.get(draft_id)
        if not draft:
            return None

        # Apply all matching attributes from the step data.
        for key, value in data.items():
            if hasattr(draft, key):
                setattr(draft, key, value)

        # Advance to the next wizard step.
        if step in WIZARD_STEPS:
            current_index = WIZARD_STEPS.index(step)
            next_index = current_index + 1
            if next_index < len(WIZARD_STEPS):
                draft.current_step = WIZARD_STEPS[next_index]

        return draft

    @staticmethod
    def list_drafts(user_id: str) -> List[WizardDraft]:
        """Return all drafts belonging to the given user.

        Args:
            user_id: The user ID to filter drafts by.

        Returns:
            List of WizardDraft objects owned by the user.
        """
        return [d for d in _drafts.values() if d.user_id == user_id]

    @staticmethod
    def build_experiment_payload(draft: WizardDraft) -> Dict[str, Any]:
        """Construct a valid experiment creation payload from a completed draft.

        Builds variants based on experiment type.  Every type produces exactly
        one control and allocations summing to 100 — ``ExperimentCreate``
        rejects anything else, and every analysis path looks the control up
        with ``next(v for v in variants if v["is_control"])``:

        - ab: 2 variants (control + treatment), 50/50
        - multivariate: 3 variants (control + 2 treatments), 33/33/34
        - feature_flag_rollout: 2 variants — a held-back control with the
          feature off and a treatment with it on, 50/50.  (A single 100%
          "Treatment" arm has nothing to measure against.)

        Args:
            draft: The completed WizardDraft.

        Returns:
            Dict matching the structure expected by ExperimentCreate.
        """
        exp_type = draft.experiment_type or "ab"

        if exp_type == "ab":
            variants = [
                {
                    "name": "Control",
                    "is_control": True,
                    "traffic_percentage": 50,
                },
                {
                    "name": "Variant A",
                    "is_control": False,
                    "traffic_percentage": 50,
                },
            ]
        elif exp_type == "multivariate":
            variants = [
                {
                    "name": "Control",
                    "is_control": True,
                    "traffic_percentage": 33,
                },
                {
                    "name": "Variant A",
                    "is_control": False,
                    "traffic_percentage": 33,
                },
                {
                    "name": "Variant B",
                    "is_control": False,
                    "traffic_percentage": 34,
                },
            ]
        else:  # feature_flag_rollout
            variants = [
                {
                    "name": "Control",
                    "description": "Feature off (held back)",
                    "is_control": True,
                    "traffic_percentage": 50,
                    "configuration": {"enabled": False},
                },
                {
                    "name": "Treatment",
                    "description": "Feature on",
                    "is_control": False,
                    "traffic_percentage": 50,
                    "configuration": {"enabled": True},
                },
            ]

        metric_name = draft.primary_metric_id or "conversion"
        metrics = [
            {
                "name": metric_name,
                "event_name": metric_name,
                "metric_type": "conversion",
                "is_primary": True,
            }
        ] + [
            {
                "name": guardrail,
                "event_name": guardrail,
                "metric_type": "conversion",
                "is_primary": False,
            }
            for guardrail in (draft.guardrail_metric_ids or [])
        ]

        return {
            "name": draft.name or f"Experiment {draft.id[:8]}",
            "description": draft.description or draft.hypothesis or "",
            "hypothesis": draft.hypothesis,
            "experiment_type": _EXPERIMENT_TYPE_MAP.get(exp_type, "a_b"),
            # ``traffic_allocation`` is what ``ExperimentCreate`` expects;
            # ``traffic_percentage`` is kept as an alias for older callers.
            "variants": [
                dict(v, traffic_allocation=v["traffic_percentage"]) for v in variants
            ],
            "metrics": metrics,
            "primary_metric_id": draft.primary_metric_id,
            # The wizard collects a list of condition dicts; ExperimentCreate
            # takes the dashboard's grouped shape (see core/targeting_adapter).
            "targeting_rules": (
                {
                    "logical_operator": "and",
                    "groups": [
                        {"logical_operator": "and", "conditions": list(draft.targeting_rules)}
                    ],
                }
                if draft.targeting_rules
                else None
            ),
        }

    @classmethod
    def validate_and_submit(
        cls, draft_id: str, db: Any = None, user_id: Any = None
    ) -> Dict[str, Any]:
        """Validate a completed draft and create the experiment it describes.

        With *db* and *user_id* the draft is turned into a real DRAFT
        experiment through :class:`ExperimentService`, exactly as
        ``POST /api/v1/experiments/`` would; the draft is then dropped.
        Without them (unit tests, dry runs) only the payload is built and
        validated and no experiment is created — the caller can tell the
        cases apart by ``persisted``.

        Args:
            draft_id: The ID of the draft to submit.
            db: SQLAlchemy session. Required to create the experiment.
            user_id: Owner of the new experiment. Required with *db*.

        Returns:
            Dict with ``success``, ``persisted``, ``experiment_id`` on
            success, or ``errors`` on failure.
        """
        draft = cls.get_draft(draft_id)
        if not draft:
            return {"success": False, "persisted": False, "errors": ["Draft not found"]}

        review_data = {
            "experiment_type": draft.experiment_type,
            "hypothesis": draft.hypothesis,
            "primary_metric_id": draft.primary_metric_id,
        }
        validation = cls.validate_wizard_step("review", review_data)
        if not validation.is_valid:
            return {"success": False, "persisted": False, "errors": validation.errors}

        payload = cls.build_experiment_payload(draft)

        if db is None or user_id is None:
            # Dry run: validated, nothing written.
            return {
                "success": True,
                "persisted": False,
                "experiment_id": None,
                "payload": payload,
            }

        from pydantic import ValidationError

        from backend.app.schemas.experiment import ExperimentCreate
        from backend.app.services.experiment_service import ExperimentService

        try:
            obj_in = ExperimentCreate(**payload)
        except ValidationError as exc:
            # Schema errors describe the caller's own payload, so they are
            # safe (and useful) to return.
            logger.info("Wizard draft %s failed validation: %s", draft_id, exc)
            return {
                "success": False,
                "persisted": False,
                "errors": [
                    f"{'.'.join(str(part) for part in error['loc']) or 'payload'}: {error['msg']}"
                    for error in exc.errors()
                ],
                "payload": payload,
            }

        try:
            created = ExperimentService(db).create_experiment(obj_in=obj_in, user_id=user_id)
        except Exception:  # noqa: BLE001 - never surface internals to the client
            # Driver/ORM messages name tables, columns and constraints, so the
            # detail stays in the server log and the caller gets a generic message.
            logger.exception("Wizard draft %s could not be created", draft_id)
            return {
                "success": False,
                "persisted": False,
                "errors": ["The experiment could not be created. Please try again."],
                "payload": payload,
            }

        cls.delete_draft(draft_id)
        experiment_id = str(created["id"] if isinstance(created, dict) else created.id)
        return {
            "success": True,
            "persisted": True,
            "experiment_id": experiment_id,
            "payload": payload,
        }
