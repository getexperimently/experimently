"""The audit log export (#221): the file formats, built one entry at a time.

``GET /api/v1/audit-logs/export`` streams the entries a filter matches as CSV
or JSON. This module owns the formats, so the route only decides which
entries go in:

* JSON is an array of the list route's item objects (``AuditLogResponse``).
* CSV is one header row (``CSV_COLUMNS``) and one row per entry, quoted as
  RFC 4180 says, through Python's ``csv`` module. Each cell is the text of the
  same field in the JSON item (empty for null), and export cells are made safe
  for spreadsheets: a cell that starts with one of ``CSV_UNSAFE_LEADS`` gets a
  leading apostrophe.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Dict, Iterable, Iterator

from backend.app.schemas.audit_log import AuditLogResponse

#: Most entries one export holds. Above it the route refuses with 422; it
#: never cuts the file short.
EXPORT_MAX_ROWS = 50_000

#: Rows fetched from the database at a time while the body streams.
EXPORT_BATCH_SIZE = 1000

#: The CSV header, in column order. Every name is a field of
#: ``AuditLogResponse``.
CSV_COLUMNS = (
    "id",
    "timestamp",
    "user_id",
    "user_email",
    "action_type",
    "action_description",
    "entity_type",
    "entity_id",
    "entity_name",
    "old_value",
    "new_value",
    "reason",
)

#: A CSV cell starting with one of these gets a leading apostrophe.
CSV_UNSAFE_LEADS = ("=", "+", "-", "@", "\t", "\r")

MEDIA_TYPES = {"csv": "text/csv; charset=utf-8", "json": "application/json"}


def export_filename(requested_at: datetime, fmt: str) -> str:
    """``audit-log-<UTC YYYYMMDDTHHMMSSZ>.<fmt>``; ``requested_at`` is UTC."""
    return f"audit-log-{requested_at.strftime('%Y%m%dT%H%M%SZ')}.{fmt}"


def entry_item(row: Any) -> Dict[str, Any]:
    """One entry as the list route returns it, as JSON-ready values."""
    return AuditLogResponse.model_validate(row).model_dump(mode="json")


def safe_cell(value: Any) -> str:
    """A CSV cell: the value's text (empty for None), made safe for spreadsheets."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if text.startswith(CSV_UNSAFE_LEADS):
        return "'" + text
    return text


def _csv_line(cells: Iterable[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerow(list(cells))
    return buffer.getvalue()


def csv_header() -> str:
    return _csv_line(CSV_COLUMNS)


def csv_row(item: Dict[str, Any]) -> str:
    return _csv_line(safe_cell(item.get(column)) for column in CSV_COLUMNS)


def csv_body(items: Iterable[Dict[str, Any]]) -> Iterator[str]:
    """The CSV file: the header, then one row per item."""
    yield csv_header()
    for item in items:
        yield csv_row(item)


def json_body(items: Iterable[Dict[str, Any]]) -> Iterator[str]:
    """The JSON file: ``[`` + the items, comma-separated + ``]``.

    A body cut short ends without its ``]``, so it does not parse.
    """
    yield "["
    first = True
    for item in items:
        yield ("" if first else ",") + json.dumps(item, ensure_ascii=False)
        first = False
    yield "]"
