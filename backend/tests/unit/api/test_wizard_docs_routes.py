"""The endpoint reference lists the wizard routes the API serves (#531).

``docs/api/endpoints.md`` gave the step route as ``PUT .../drafts/{id}``
(the API serves ``.../drafts/{id}/step``) and did not say that any of the
six wizard operations is deprecated.
"""

import re
from pathlib import Path

import pytest

from backend.app.main import app

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
ENDPOINTS_MD = REPO_ROOT / "docs" / "api" / "endpoints.md"

ROUTE_LINE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE)\s+(/api/v1/wizard/\S*)\s+(.*)$")


def _wizard_section_lines() -> list[str]:
    text = ENDPOINTS_MD.read_text(encoding="utf-8")
    section = text.split("### Experiment Wizard", 1)[1].split("\n### ", 1)[0]
    return section.splitlines()


@pytest.mark.regression
def test_the_reference_lists_exactly_the_served_wizard_routes_as_deprecated():
    served = {
        (method.upper(), path.replace("{draft_id}", "{id}"))
        for path, item in app.openapi()["paths"].items()
        if path.startswith("/api/v1/wizard/")
        for method in item
    }
    listed = {}
    for line in _wizard_section_lines():
        match = ROUTE_LINE.match(line.strip())
        if match:
            listed[(match.group(1), match.group(2))] = match.group(3)

    assert set(listed) == served
    assert [key for key, rest in listed.items() if "(deprecated)" not in rest] == []
