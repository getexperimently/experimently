"""
Mutual Exclusion Service for managing experiment groups (EP-022).

Ensures that users can only be assigned to one experiment within a group,
using consistent hashing for deterministic, stable user-to-experiment mapping.
"""

import hashlib
import logging
import struct
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.mutual_exclusion_group import (
    MutualExclusionGroup,
    MutualExclusionGroupStatus,
)

logger = logging.getLogger(__name__)


class MutualExclusionService:
    """Service for managing mutual exclusion groups and user-to-experiment selection."""

    MAX_HASH_VALUE = 0xFFFFFFFF

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_group(
        self,
        name: str,
        description: Optional[str] = None,
        traffic_allocation: float = 1.0,
        owner_id: Optional[UUID] = None,
    ) -> MutualExclusionGroup:
        """Create a new mutual exclusion group."""
        group = MutualExclusionGroup(
            name=name,
            description=description,
            traffic_allocation=traffic_allocation,
            status=MutualExclusionGroupStatus.ACTIVE,
            owner_id=owner_id,
        )
        self.db.add(group)
        self.db.commit()
        self.db.refresh(group)
        return group

    def get_group(self, group_id: UUID) -> Optional[MutualExclusionGroup]:
        """Get a mutual exclusion group by ID."""
        return (
            self.db.query(MutualExclusionGroup)
            .filter(MutualExclusionGroup.id == group_id)
            .first()
        )

    def list_groups(
        self, status: Optional[str] = None, skip: int = 0, limit: int = 100
    ) -> List[MutualExclusionGroup]:
        """List mutual exclusion groups with optional status filter."""
        query = self.db.query(MutualExclusionGroup)
        if status:
            query = query.filter(
                MutualExclusionGroup.status == MutualExclusionGroupStatus(status)
            )
        return query.offset(skip).limit(limit).all()

    def count_groups(self, status: Optional[str] = None) -> int:
        """Count mutual exclusion groups with optional status filter."""
        query = self.db.query(MutualExclusionGroup)
        if status:
            query = query.filter(
                MutualExclusionGroup.status == MutualExclusionGroupStatus(status)
            )
        return query.count()

    def update_group(
        self,
        group_id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        traffic_allocation: Optional[float] = None,
        status: Optional[str] = None,
    ) -> Optional[MutualExclusionGroup]:
        """Update a mutual exclusion group."""
        group = self.get_group(group_id)
        if not group:
            return None

        if name is not None:
            group.name = name
        if description is not None:
            group.description = description
        if traffic_allocation is not None:
            group.traffic_allocation = traffic_allocation
        if status is not None:
            group.status = MutualExclusionGroupStatus(status)

        self.db.commit()
        self.db.refresh(group)
        return group

    def archive_group(self, group_id: UUID) -> Optional[MutualExclusionGroup]:
        """Archive (soft-delete) a mutual exclusion group."""
        return self.update_group(group_id, status="archived")

    # ------------------------------------------------------------------
    # Experiment Management
    # ------------------------------------------------------------------

    def add_experiment_to_group(
        self, group_id: UUID, experiment_id: UUID
    ) -> Optional[Experiment]:
        """Add an experiment to a mutual exclusion group."""
        group = self.get_group(group_id)
        if not group:
            raise ValueError(f"Group {group_id} not found")

        experiment = (
            self.db.query(Experiment)
            .filter(Experiment.id == experiment_id)
            .first()
        )
        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        if experiment.mutual_exclusion_group_id is not None:
            if experiment.mutual_exclusion_group_id == group_id:
                return experiment  # Already in this group
            raise ValueError(
                f"Experiment {experiment_id} is already in another group"
            )

        experiment.mutual_exclusion_group_id = group_id
        self.db.commit()
        self.db.refresh(experiment)
        return experiment

    def remove_experiment_from_group(
        self, group_id: UUID, experiment_id: UUID
    ) -> Optional[Experiment]:
        """Remove an experiment from a mutual exclusion group."""
        experiment = (
            self.db.query(Experiment)
            .filter(
                Experiment.id == experiment_id,
                Experiment.mutual_exclusion_group_id == group_id,
            )
            .first()
        )
        if not experiment:
            raise ValueError(
                f"Experiment {experiment_id} not found in group {group_id}"
            )

        experiment.mutual_exclusion_group_id = None
        self.db.commit()
        self.db.refresh(experiment)
        return experiment

    def get_group_experiments(self, group_id: UUID) -> List[Experiment]:
        """Get all experiments in a mutual exclusion group."""
        return (
            self.db.query(Experiment)
            .filter(Experiment.mutual_exclusion_group_id == group_id)
            .all()
        )

    def get_active_group_experiments(self, group_id: UUID) -> List[Experiment]:
        """Get active experiments in a mutual exclusion group."""
        return (
            self.db.query(Experiment)
            .filter(
                Experiment.mutual_exclusion_group_id == group_id,
                Experiment.status == ExperimentStatus.ACTIVE,
            )
            .all()
        )

    # ------------------------------------------------------------------
    # User-to-Experiment Selection
    # ------------------------------------------------------------------

    def select_experiment_for_user(
        self, user_id: str, group_id: UUID
    ) -> Optional[UUID]:
        """
        Select which experiment a user should participate in within a group.

        Algorithm:
        1. Hash (user_id, group_id) → normalize to [0, 1)
        2. If value >= group.traffic_allocation → exclude from all experiments
        3. Divide [0, traffic_allocation) proportionally among active experiments
        4. Return the experiment whose sub-range contains the hash value

        Returns:
            Experiment ID the user is assigned to, or None if excluded.
        """
        group = self.get_group(group_id)
        if not group or group.status != MutualExclusionGroupStatus.ACTIVE:
            return None

        # Get active experiments in the group
        active_experiments = self.get_active_group_experiments(group_id)
        if not active_experiments:
            return None

        # Hash user into [0, 1)
        hash_value = self._normalized_hash(user_id, str(group_id))

        # Check traffic allocation
        if hash_value >= group.traffic_allocation:
            return None

        # Distribute within traffic allocation proportionally
        num_experiments = len(active_experiments)
        slot_size = group.traffic_allocation / num_experiments
        cumulative = 0.0

        for experiment in sorted(active_experiments, key=lambda e: str(e.id)):
            cumulative += slot_size
            if hash_value < cumulative:
                return experiment.id

        # Fallback to last experiment
        return active_experiments[-1].id

    def _normalized_hash(self, user_id: str, salt: str) -> float:
        """Hash user_id with salt and normalize to [0, 1)."""
        combined = f"{user_id}:{salt}".encode("utf-8")
        hash_bytes = hashlib.md5(combined).digest()[:4]
        hash_int = struct.unpack("<I", hash_bytes)[0]
        return hash_int / (self.MAX_HASH_VALUE + 1)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def get_user_experiment_group(
        self, experiment_id: UUID
    ) -> Optional[MutualExclusionGroup]:
        """Get the mutual exclusion group for an experiment, if any."""
        experiment = (
            self.db.query(Experiment)
            .filter(Experiment.id == experiment_id)
            .first()
        )
        if not experiment or not experiment.mutual_exclusion_group_id:
            return None
        return self.get_group(experiment.mutual_exclusion_group_id)

    def is_user_eligible_for_experiment(
        self, user_id: str, experiment_id: UUID
    ) -> bool:
        """Check if a user is eligible for an experiment given mutual exclusion rules."""
        group = self.get_user_experiment_group(experiment_id)
        if not group:
            return True  # No group constraint

        selected = self.select_experiment_for_user(user_id, group.id)
        return selected == experiment_id
