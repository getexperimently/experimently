"""The warehouse analysis page says which warehouses are available, and no others.

Enabling a connector (``ENABLED_CONNECTORS``) is a public claim, and the page
that says which warehouses are available has to change in the same pull
request.  The page's other statements are pinned in core,
``backend/tests/unit/docs/test_warehouse_docs_claims.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from modules.backend.app.warehouse.connectors import (
    ENABLED_CONNECTORS,
    KNOWN_CONNECTORS,
)

pytestmark = pytest.mark.unit

PAGE = Path(__file__).resolve().parents[4] / "docs" / "api" / "warehouse-analytics.md"


NAMES = {"bigquery": "BigQuery", "snowflake": "Snowflake", "athena": "Amazon Athena"}


def _text() -> str:
    return re.sub(r"\s+", " ", PAGE.read_text(encoding="utf-8"))


def test_the_page_says_no_warehouse_is_available_exactly_while_none_is():
    says_none = "no warehouse is available yet" in _text().lower()
    assert says_none == (not ENABLED_CONNECTORS)


@pytest.mark.parametrize("warehouse_type", KNOWN_CONNECTORS)
def test_the_page_says_a_warehouse_is_available_exactly_while_it_is(warehouse_type):
    says_available = f"{NAMES[warehouse_type]} is available" in _text()
    assert says_available == (warehouse_type in ENABLED_CONNECTORS)
