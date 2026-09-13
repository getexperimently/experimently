"""
Tests for IntegrationConfig model — EP-034 Batch 1.
"""

import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB, UUID


class TestIntegrationConfigModel:
    def test_model_inherits_base(self):
        from backend.app.models.base import Base
        from modules.backend.app.models.integration_config import IntegrationConfig

        assert issubclass(IntegrationConfig, Base)

    def test_table_name(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        assert IntegrationConfig.__tablename__ == "integration_configs"

    def test_table_has_schema(self):
        from backend.app.core.database_config import get_schema_name
        from modules.backend.app.models.integration_config import IntegrationConfig

        schema = IntegrationConfig.__table_args__[-1].get("schema")
        assert schema == get_schema_name()

    def test_id_column_is_uuid_pk(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["id"]
        assert col.primary_key
        assert isinstance(col.type, UUID)

    def test_integration_type_column_exists(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["integration_type"]
        assert col is not None

    def test_integration_type_not_nullable(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["integration_type"]
        assert col.nullable is False

    def test_is_active_column_exists(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["is_active"]
        assert col is not None

    def test_is_active_defaults_to_false(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["is_active"]
        assert col.default.arg is False or col.default.arg == False

    def test_is_active_not_nullable(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["is_active"]
        assert col.nullable is False

    def test_encrypted_config_column_exists(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["encrypted_config"]
        assert col is not None

    def test_encrypted_config_nullable(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["encrypted_config"]
        assert col.nullable is True

    def test_last_sync_at_column_exists(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["last_sync_at"]
        assert col is not None

    def test_last_sync_at_nullable(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["last_sync_at"]
        assert col.nullable is True

    def test_last_error_column_exists(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["last_error"]
        assert col is not None

    def test_last_error_nullable(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["last_error"]
        assert col.nullable is True

    def test_created_at_column_exists(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["created_at"]
        assert col is not None

    def test_updated_at_column_exists(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        col = IntegrationConfig.__table__.c["updated_at"]
        assert col is not None

    def test_index_on_integration_type(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        index_names = [idx.name for idx in IntegrationConfig.__table__.indexes]
        assert "ix_integration_configs_type" in index_names

    def test_unique_constraint_on_integration_type(self):
        from modules.backend.app.models.integration_config import IntegrationConfig

        constraint_names = [c.name for c in IntegrationConfig.__table__.constraints]
        assert "uq_integration_configs_type" in constraint_names


class TestIntegrationType:
    def test_enum_has_salesforce(self):
        from modules.backend.app.models.integration_config import IntegrationType

        assert IntegrationType.SALESFORCE.value == "salesforce"

    def test_enum_has_jira(self):
        from modules.backend.app.models.integration_config import IntegrationType

        assert IntegrationType.JIRA.value == "jira"

    def test_enum_has_github(self):
        from modules.backend.app.models.integration_config import IntegrationType

        assert IntegrationType.GITHUB.value == "github"
