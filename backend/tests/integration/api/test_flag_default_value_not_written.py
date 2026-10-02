"""The ``default_value`` column changes no answer of the flag API yet (#94).

``feature_flags.default_value`` exists from ``a89544fb1075`` on, but the
contract that types the field and refuses ``true`` comes later.  Until then the
request schemas still declare ``default_value`` untyped, and every flag writer
keeps exactly the keys that are columns.  Adding the column would therefore make
the field writable by accident: ``true`` would be stored, and a non-boolean such
as ``"control"`` would fail the INSERT (a 500).

These pin today's behaviour through that change: the field is accepted and
ignored on create and update, the stored value stays false, and the list
reports false, as it did when the value came from the schema's default.
"""

from __future__ import annotations

import pytest

from backend.app.crud.crud_feature_flag import crud_feature_flag
from backend.app.models.feature_flag import FeatureFlag
from backend.app.schemas.feature_flag import FeatureFlagCreate, FeatureFlagUpdate
from backend.tests.integration.helpers import unique_flag_key

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

COLLECTION = "/api/v1/feature-flags"

#: What a client could send before the column existed, and still may.
SENT_VALUES = [True, "control", 1]


def _stored(db_session, flag_id) -> bool:
    db_session.expire_all()
    return db_session.get(FeatureFlag, flag_id).default_value


@pytest.mark.regression
@pytest.mark.parametrize("sent", SENT_VALUES, ids=repr)
def test_create_ignores_default_value_and_stores_false(admin_client, db_session, sent):
    key = unique_flag_key("dv-create")
    response = admin_client.post(
        f"{COLLECTION}/",
        json={"key": key, "name": "Default value", "default_value": sent},
    )

    assert response.status_code == 201, response.text
    flag = db_session.query(FeatureFlag).filter(FeatureFlag.key == key).one()
    assert _stored(db_session, flag.id) is False


@pytest.mark.regression
@pytest.mark.parametrize("sent", SENT_VALUES, ids=repr)
def test_update_ignores_default_value_and_keeps_false(
    admin_client, db_session, make_feature_flag, sent
):
    flag = make_feature_flag(key=unique_flag_key("dv-put"))

    response = admin_client.put(
        f"{COLLECTION}/{flag.id}",
        json={"default_value": sent, "rollout_percentage": 30},
    )

    assert response.status_code == 200, response.text
    assert response.json()["rollout_percentage"] == 30
    assert _stored(db_session, flag.id) is False


def test_the_list_reports_false(admin_client, make_feature_flag):
    flag = make_feature_flag(key=unique_flag_key("dv-list"))

    response = admin_client.get(f"{COLLECTION}/", params={"search": flag.key})

    assert response.status_code == 200, response.text
    (item,) = [i for i in response.json()["items"] if i["key"] == flag.key]
    assert item["default_value"] is False


@pytest.mark.regression
def test_the_crud_writers_ignore_default_value(db_session):
    """The list route's CRUD object has the same column filter as the service."""
    created = crud_feature_flag.create(
        db_session,
        obj_in=FeatureFlagCreate(
            key=unique_flag_key("dv-crud"), name="CRUD", default_value=True
        ),
    )
    assert _stored(db_session, created.id) is False

    crud_feature_flag.update(
        db_session, db_obj=created, obj_in=FeatureFlagUpdate(default_value=True)
    )
    assert _stored(db_session, created.id) is False
