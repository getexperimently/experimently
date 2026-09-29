"""Connectors ship disabled until verified, and recorded fixtures say where they came from."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.backend.app.models.warehouse_connection import WAREHOUSE_TYPES
from modules.backend.app.warehouse import connectors
from modules.backend.app.warehouse.connectors import (
    ENABLED_CONNECTORS,
    KNOWN_CONNECTORS,
    ConnectorDisabled,
    is_enabled,
    require_enabled,
)

pytestmark = pytest.mark.unit

RECORDED = Path(__file__).parent / "recorded"

#: Where each vendor's documentation lives; a recorded file's URL must be there.
VENDOR_DOC_ROOTS = {
    "bigquery": ("https://docs.cloud.google.com/", "https://developers.google.com/"),
    "snowflake": ("https://docs.snowflake.com/",),
}


def test_enabled_connectors_exact():
    """No connector is enabled until its real check has passed (a flip PR changes this)."""
    assert ENABLED_CONNECTORS == frozenset()
    assert isinstance(ENABLED_CONNECTORS, frozenset)
    assert set(KNOWN_CONNECTORS) == set(WAREHOUSE_TYPES)


@pytest.mark.parametrize("warehouse_type", KNOWN_CONNECTORS)
def test_disabled_connector_refused_with_422(warehouse_type):
    with pytest.raises(ConnectorDisabled) as err:
        require_enabled(warehouse_type)
    assert err.value.status_code == 422
    body = err.value.to_body()
    assert body["code"] == "connector_disabled"
    assert body["message"].endswith("isn't available on this deployment yet.")
    assert not is_enabled(warehouse_type)


def test_disabled_copy_names_the_warehouse():
    assert ConnectorDisabled("bigquery").message == (
        "BigQuery isn't available on this deployment yet."
    )
    assert ConnectorDisabled("athena").message == (
        "Amazon Athena isn't available on this deployment yet."
    )


@pytest.mark.parametrize("value", ["BigQuery", "bigquery ", "postgres", "", None, 1])
def test_unknown_types_refused(value):
    with pytest.raises(ConnectorDisabled):
        require_enabled(value, frozenset(KNOWN_CONNECTORS))


def test_an_enabled_connector_is_allowed():
    assert require_enabled("bigquery", frozenset({"bigquery"})) == "bigquery"
    assert not is_enabled("snowflake", frozenset({"bigquery"}))


def test_there_is_no_setting_that_enables_a_connector():
    """Enabling is a code change, not configuration: nothing here reads settings."""
    source = Path(connectors.__file__).read_text(encoding="utf-8")
    assert "settings" not in source and "environ" not in source


def _recorded_files():
    return sorted(RECORDED.rglob("*.json"))


def test_there_are_recorded_fixtures():
    assert len(_recorded_files()) >= 10


@pytest.mark.parametrize(
    "path", _recorded_files(), ids=lambda p: str(p.relative_to(RECORDED))
)
def test_recorded_fixtures_declare_provenance(path):
    """Each recorded response names its vendor-doc row and URL, or a real run id."""
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"_provenance", "status", "body"}
    provenance = data["_provenance"]
    real_run = provenance.get("real_run_id")
    if real_run:
        assert isinstance(real_run, str) and real_run.strip()
        return
    assert provenance.get("source") == "vendor documentation"
    assert isinstance(provenance.get("vendor_docs_row"), str)
    assert provenance["vendor_docs_row"].strip()
    vendor = path.relative_to(RECORDED).parts[0]
    assert provenance.get("url", "").startswith(VENDOR_DOC_ROOTS[vendor])
    assert isinstance(provenance.get("note"), str) and provenance["note"].strip()
