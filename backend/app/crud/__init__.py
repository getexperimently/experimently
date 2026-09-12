"""
CRUD module for database operations.

This module provides standardized Create, Read, Update, Delete operations
for database models, following the repository pattern.
"""

from backend.app.crud.crud_feature_flag import crud_feature_flag
from backend.app.crud.crud_user import crud_user

__all__ = ["crud_feature_flag", "crud_user"]
