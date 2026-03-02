"""
Global Holdout Service for managing user holdout groups (EP-022).

Reserves a fixed percentage of users from all experiments to provide a clean
baseline for measuring the cumulative effect of running experiments.
"""

import hashlib
import logging
import struct
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.models.global_holdout import GlobalHoldout

logger = logging.getLogger(__name__)

# Fixed salt for holdout hashing — ensures holdout bucket is independent of
# experiment-specific hashing
HOLDOUT_SALT = "global_holdout_v1"


class GlobalHoldoutService:
    """Service for managing global holdout configuration and user checks."""

    MAX_HASH_VALUE = 0xFFFFFFFF

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_holdout(
        self,
        name: str,
        description: Optional[str] = None,
        holdout_percentage: int = 10,
        is_active: bool = False,
        owner_id: Optional[UUID] = None,
    ) -> GlobalHoldout:
        """Create a new global holdout configuration."""
        holdout = GlobalHoldout(
            name=name,
            description=description,
            holdout_percentage=holdout_percentage,
            is_active=is_active,
            owner_id=owner_id,
        )
        self.db.add(holdout)
        self.db.commit()
        self.db.refresh(holdout)
        return holdout

    def get_holdout(self, holdout_id: UUID) -> Optional[GlobalHoldout]:
        """Get a holdout by ID."""
        return (
            self.db.query(GlobalHoldout)
            .filter(GlobalHoldout.id == holdout_id)
            .first()
        )

    def get_active_holdout(self) -> Optional[GlobalHoldout]:
        """Get the currently active global holdout (at most one should be active)."""
        return (
            self.db.query(GlobalHoldout)
            .filter(GlobalHoldout.is_active == True)
            .first()
        )

    def list_holdouts(
        self, skip: int = 0, limit: int = 100
    ) -> List[GlobalHoldout]:
        """List all holdouts."""
        return self.db.query(GlobalHoldout).offset(skip).limit(limit).all()

    def count_holdouts(self) -> int:
        """Count all holdouts."""
        return self.db.query(GlobalHoldout).count()

    def update_holdout(
        self,
        holdout_id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        holdout_percentage: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[GlobalHoldout]:
        """Update a holdout configuration."""
        holdout = self.get_holdout(holdout_id)
        if not holdout:
            return None

        if name is not None:
            holdout.name = name
        if description is not None:
            holdout.description = description
        if holdout_percentage is not None:
            holdout.holdout_percentage = holdout_percentage
        if is_active is not None:
            # If activating, deactivate any other active holdout first
            if is_active:
                self._deactivate_all()
            holdout.is_active = is_active

        self.db.commit()
        self.db.refresh(holdout)
        return holdout

    def activate_holdout(self, holdout_id: UUID) -> Optional[GlobalHoldout]:
        """Activate a holdout (deactivates any currently active holdout)."""
        return self.update_holdout(holdout_id, is_active=True)

    def deactivate_holdout(self, holdout_id: UUID) -> Optional[GlobalHoldout]:
        """Deactivate a holdout."""
        return self.update_holdout(holdout_id, is_active=False)

    # ------------------------------------------------------------------
    # User Holdout Check
    # ------------------------------------------------------------------

    def is_user_in_holdout(self, user_id: str) -> Tuple[bool, int, int]:
        """
        Check if a user is in the global holdout.

        Algorithm:
        1. Hash (user_id, HOLDOUT_SALT) with fixed salt → bucket 0-99
        2. Return bucket < holdout_percentage

        Returns:
            Tuple of (is_in_holdout, holdout_percentage, bucket)
        """
        holdout = self.get_active_holdout()
        if not holdout:
            return (False, 0, 0)

        bucket = self._get_holdout_bucket(user_id)
        is_in = bucket < holdout.holdout_percentage
        return (is_in, holdout.holdout_percentage, bucket)

    @staticmethod
    def is_user_in_holdout_static(
        user_id: str, holdout_percentage: int
    ) -> Tuple[bool, int]:
        """
        Static version for Lambda use — no DB dependency.

        Returns:
            Tuple of (is_in_holdout, bucket)
        """
        bucket = GlobalHoldoutService._get_holdout_bucket_static(user_id)
        return (bucket < holdout_percentage, bucket)

    @staticmethod
    def _get_holdout_bucket_static(user_id: str) -> int:
        """Get holdout bucket for a user (0-99). Static version."""
        combined = f"{user_id}:{HOLDOUT_SALT}".encode("utf-8")
        hash_bytes = hashlib.md5(combined).digest()[:4]
        hash_int = struct.unpack("<I", hash_bytes)[0]
        return hash_int % 100

    def _get_holdout_bucket(self, user_id: str) -> int:
        """Get holdout bucket for a user (0-99)."""
        return self._get_holdout_bucket_static(user_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _deactivate_all(self) -> None:
        """Deactivate all currently active holdouts."""
        self.db.query(GlobalHoldout).filter(
            GlobalHoldout.is_active == True
        ).update({"is_active": False})
        self.db.flush()
