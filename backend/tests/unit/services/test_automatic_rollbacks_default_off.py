"""Automatic rollbacks stay off until an administrator turns them on (#629).

A safety rollback to 0% now turns a flag off for every user, and the monitor
looks at every ACTIVE flag. So the global switch that lets the monitor act
without a person, ``enable_automatic_rollbacks``, must keep defaulting to
False in each place a settings row can come from: the column default, the
request schema's default, and the row the service creates on first read.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.app.models.safety import SafetySettings
from backend.app.schemas.safety import SafetySettingsCreate
from backend.app.services.safety_service import SafetyService

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_the_column_defaults_to_off():
    default = SafetySettings.__table__.c.enable_automatic_rollbacks.default
    assert default is not None
    assert default.arg is False


def test_the_request_schema_defaults_to_off():
    assert SafetySettingsCreate().enable_automatic_rollbacks is False


def test_the_first_read_creates_the_settings_switched_off():
    db = MagicMock()
    db.query.return_value.first.return_value = None
    added = []
    db.add.side_effect = added.append

    def refresh(row):
        # What the database fills in on insert.
        row.id = uuid.uuid4()
        row.created_at = row.updated_at = datetime.now(timezone.utc)

    db.refresh.side_effect = refresh

    settings = asyncio.run(SafetyService(db).get_safety_settings())

    (row,) = added
    assert isinstance(row, SafetySettings)
    assert row.enable_automatic_rollbacks is False
    assert settings.enable_automatic_rollbacks is False
