"""The warehouse analysis page says no warehouse is available exactly while none is.

Enabling a connector (``ENABLED_CONNECTORS``) is a public claim, and the page
that says "no warehouse is available yet" has to change in the same pull
request.  The page's other statements are pinned in core,
``backend/tests/unit/docs/test_warehouse_docs_claims.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from modules.backend.app.warehouse.connectors import ENABLED_CONNECTORS

pytestmark = pytest.mark.unit

PAGE = Path(__file__).resolve().parents[4] / "docs" / "api" / "warehouse-analytics.md"


def test_the_page_says_no_warehouse_is_available_exactly_while_none_is():
    text = re.sub(r"\s+", " ", PAGE.read_text(encoding="utf-8")).lower()
    says_none = "no warehouse is available yet" in text
    assert says_none == (not ENABLED_CONNECTORS)
