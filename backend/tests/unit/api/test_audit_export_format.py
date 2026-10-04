"""The audit log export's formats, rate limit and headers (#221), without a database.

The route itself is tested against Postgres in
``backend/tests/integration/api/test_audit_export.py``.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

import pytest

from backend.app.middleware.rate_limiter import (
    EXPORT_PATH_PREFIX,
    rate_limit_key,
    resolve_rate_limit,
)
from backend.app.services import audit_export

pytestmark = [pytest.mark.unit]

EXPORT = "/api/v1/audit-logs/export"


def test_the_export_has_its_own_limit_of_ten_a_minute():
    assert resolve_rate_limit(EXPORT) == (10, 60)


def test_the_export_counter_is_its_own():
    """Not the ``/api/v1/export/`` budget, and not the list route's."""
    key = rate_limit_key("10.0.0.1", EXPORT)
    assert key == f"10.0.0.1:{EXPORT}"
    assert key != rate_limit_key("10.0.0.1", f"{EXPORT_PATH_PREFIX}experiments")
    assert resolve_rate_limit("/api/v1/audit-logs/") == (300, 60)


def test_the_browser_may_read_x_total_count():
    """The dashboard compares the rows it received with this header.

    It is not CORS-safelisted: unexposed, a cross-origin dashboard reads null.
    """
    from fastapi.middleware.cors import CORSMiddleware

    from backend.app.main import app

    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    exposed = {h.lower() for h in cors.kwargs.get("expose_headers", [])}
    assert "x-total-count" in exposed


@pytest.mark.parametrize("lead", ["=", "+", "-", "@", "\t", "\r"])
def test_a_cell_starting_with_an_unsafe_sign_is_prefixed(lead):
    assert audit_export.safe_cell(f"{lead}SUM(1)") == f"'{lead}SUM(1)"


@pytest.mark.parametrize("value", ["plain", "a=b", " =x", "", "1-2", "'=x"])
def test_other_cells_are_left_alone(value):
    assert audit_export.safe_cell(value) == value


def test_none_is_an_empty_cell():
    assert audit_export.safe_cell(None) == ""


def test_csv_rows_quote_as_rfc_4180():
    item = dict.fromkeys(audit_export.CSV_COLUMNS)
    item.update(reason='one, "two"\r\nthree', entity_name="plain")
    line = audit_export.csv_row(item)
    assert line.endswith("\r\n")
    assert '"one, ""two""\r\nthree"' in line
    parsed = next(csv.reader(io.StringIO(line, newline="")))
    assert dict(zip(audit_export.CSV_COLUMNS, parsed))["reason"] == (
        'one, "two"\r\nthree'
    )


def test_the_csv_header_is_pinned():
    assert audit_export.csv_header() == (
        "id,timestamp,user_id,user_email,action_type,action_description,"
        "entity_type,entity_id,entity_name,old_value,new_value,reason\r\n"
    )


def test_json_body_is_an_array_and_a_cut_one_does_not_parse():
    items = [{"id": "1"}, {"id": "2"}]
    whole = "".join(audit_export.json_body(items))
    assert json.loads(whole) == items
    assert "".join(audit_export.json_body([])) == "[]"
    cut = "".join(list(audit_export.json_body(items))[:-1])
    with pytest.raises(json.JSONDecodeError):
        json.loads(cut)


def test_the_filename_is_utc_and_names_the_format():
    at = datetime(2026, 10, 4, 9, 5, 7, tzinfo=timezone.utc)
    assert audit_export.export_filename(at, "csv") == "audit-log-20261004T090507Z.csv"
    assert audit_export.export_filename(at, "json") == "audit-log-20261004T090507Z.json"
