"""Audit text is normalised before it is stored (#221).

The normalisation is on the ``AuditLog`` model itself, so every writer --
``AuditService.log_action``, ``AuditService.log_toggle_operation`` and the
admin user PATCH -- passes through it. These tests walk the table's own
String/Text columns rather than a hand-typed list, so a text column added
later without the normalisation fails here.
"""

import uuid

import pytest
from sqlalchemy import String

from backend.app.models.audit_log import (
    AUDIT_TEXT_COLUMNS,
    AuditLog,
    normalise_audit_text,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

RAW = "x" + chr(0x0) + "y" + chr(0xD800) + "z" + chr(0xDFFF) + "w"
STORED = "x\ufffdy\ufffdz\ufffdw"


def _text_columns():
    return sorted(
        column.name
        for column in AuditLog.__table__.columns
        if isinstance(column.type, String)  # Text is a String
    )


def test_the_table_has_the_text_columns_this_test_expects():
    columns = _text_columns()
    assert "reason" in columns and "entity_name" in columns
    assert "user_email" in columns
    assert sorted(AUDIT_TEXT_COLUMNS) == columns


@pytest.mark.parametrize("column", _text_columns())
def test_every_text_column_is_normalised_on_assignment(column):
    row = AuditLog()
    setattr(row, column, RAW)

    stored = getattr(row, column)
    assert stored == STORED
    stored.encode("utf-8")  # raises if anything unstorable is left


@pytest.mark.parametrize("column", _text_columns())
def test_every_text_column_is_normalised_by_the_constructor(column):
    row = AuditLog(**{column: RAW})
    assert getattr(row, column) == STORED


def test_ordinary_text_and_non_text_values_are_unchanged():
    assert normalise_audit_text("plain text, émoji 🎉") == "plain text, émoji 🎉"
    assert normalise_audit_text(None) is None
    flag_id = uuid.uuid4()
    assert normalise_audit_text(flag_id) is flag_id
