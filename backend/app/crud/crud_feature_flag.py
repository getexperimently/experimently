"""
CRUD for feature flag management.

This module provides database operations for FeatureFlag models.
"""

from typing import Any, Dict, List, Optional, Union

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from backend.app.crud.base import CRUDBase
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.schemas.feature_flag import (
    READ_ONLY_FIELDS,
    FeatureFlagCreate,
    FeatureFlagUpdate,
)


class CRUDFeatureFlag(CRUDBase[FeatureFlag, FeatureFlagCreate, FeatureFlagUpdate]):
    """Feature flag CRUD operations."""

    def get_by_key(self, db: Session, *, key: str) -> Optional[FeatureFlag]:
        """
        Get a feature flag by key.

        Args:
            db: Database session
            key: Key of the feature flag to get

        Returns:
            The feature flag if found, None otherwise
        """
        return db.query(FeatureFlag).filter(FeatureFlag.key == key).first()

    def create(self, db: Session, *, obj_in: FeatureFlagCreate) -> FeatureFlag:
        """
        Create a new feature flag.

        Args:
            db: Database session
            obj_in: Data to create the feature flag with

        Returns:
            The created feature flag
        """
        # Keep only columns, and never a read-only field: each of those names a
        # column (the primary key, the owner, a timestamp, the status), and a
        # request may carry them because a GET body round-trips (#94).  No
        # route calls this; the service is the writer the API uses.
        obj_in_data = (
            obj_in.model_dump()
            if hasattr(obj_in, "model_dump")
            else jsonable_encoder(obj_in)
        )
        status = (
            FeatureFlagStatus.ACTIVE.value
            if obj_in_data.pop("is_active", False)
            else FeatureFlagStatus.INACTIVE.value
        )
        model_fields = [c.name for c in FeatureFlag.__table__.columns]
        obj_in_data = {
            k: v
            for k, v in obj_in_data.items()
            if k in model_fields and k not in READ_ONLY_FIELDS
        }
        obj_in_data["status"] = status

        # Create feature flag
        db_obj = FeatureFlag(**obj_in_data)
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def update(
        self,
        db: Session,
        *,
        db_obj: FeatureFlag,
        obj_in: Union[FeatureFlagUpdate, Dict[str, Any]],
    ) -> FeatureFlag:
        """
        Update a feature flag.

        Args:
            db: Database session
            db_obj: The feature flag to update
            obj_in: New data to update the feature flag with

        Returns:
            The updated feature flag
        """
        # Convert to dict if it's a Pydantic model
        if hasattr(obj_in, "model_dump"):
            update_data = obj_in.model_dump(exclude_unset=True)
        elif hasattr(obj_in, "dict"):
            update_data = obj_in.dict(exclude_unset=True)
        else:
            update_data = dict(obj_in)

        # Keep only columns, and never a read-only field (see ``create``); the
        # status comes from ``is_active`` alone.
        is_active = update_data.pop("is_active", None)
        model_fields = [c.name for c in FeatureFlag.__table__.columns]
        update_data = {
            k: v
            for k, v in update_data.items()
            if k in model_fields and k not in READ_ONLY_FIELDS
        }
        if is_active is not None:
            update_data["status"] = (
                FeatureFlagStatus.ACTIVE.value
                if is_active
                else FeatureFlagStatus.INACTIVE.value
            )

        return super().update(db, db_obj=db_obj, obj_in=update_data)

    def get_active_flags(self, db: Session) -> List[FeatureFlag]:
        """
        Get all active feature flags.

        Args:
            db: Database session

        Returns:
            List of active feature flags
        """
        return (
            db.query(FeatureFlag)
            .filter(FeatureFlag.status == FeatureFlagStatus.ACTIVE.value)
            .all()
        )

    def activate(self, db: Session, *, db_obj: FeatureFlag) -> FeatureFlag:
        """
        Activate a feature flag.

        Args:
            db: Database session
            db_obj: The feature flag to activate

        Returns:
            The activated feature flag
        """
        db_obj.status = FeatureFlagStatus.ACTIVE.value
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def deactivate(self, db: Session, *, db_obj: FeatureFlag) -> FeatureFlag:
        """
        Deactivate a feature flag.

        Args:
            db: Database session
            db_obj: The feature flag to deactivate

        Returns:
            The deactivated feature flag
        """
        db_obj.status = FeatureFlagStatus.INACTIVE.value
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj


crud_feature_flag = CRUDFeatureFlag(FeatureFlag)
