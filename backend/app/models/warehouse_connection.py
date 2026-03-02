"""
Warehouse Connection model for Issue #26: POST-MVP Warehouse-Native Analytics.

Stores encrypted credentials for Snowflake, BigQuery, and Redshift connections.
Credentials are NEVER stored in plaintext — the `encrypted_credentials` column
holds a base64-encoded (or KMS-encrypted in production) JSON blob.
"""

import uuid as _uuid_mod

from sqlalchemy import Column, String, Boolean, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declared_attr

from .base import Base, BaseModel
from backend.app.core.database_config import get_schema_name


class WarehouseConnection(Base, BaseModel):
    """
    Represents a customer data warehouse connection configuration.

    Supported warehouse types: snowflake | bigquery | redshift

    Credentials are stored encrypted; never exposed in API responses.
    Soft-delete is implemented via is_active=False.
    """

    __tablename__ = "warehouse_connections"

    name = Column(String(200), nullable=False)
    warehouse_type = Column(String(50), nullable=False)  # snowflake | bigquery | redshift
    encrypted_credentials = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="SET NULL"),
        nullable=True,
    )

    owner = relationship("User")

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            Index(f"ix_{schema_name}_warehouse_conn_active", "is_active"),
            {"schema": schema_name},
        )

    def __repr__(self) -> str:
        return f"<WarehouseConnection id={self.id} name={self.name!r} type={self.warehouse_type!r}>"
