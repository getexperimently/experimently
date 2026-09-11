"""
Kill-switch path: disable / enable / toggle a flag through the API.

Regression for a bug found by the StreamPulse demo (2026-09-11): the toggle
endpoints handed the ``FeatureFlagStatus`` enum to the audit log, psycopg2
could not adapt it, the audit service rolled the session back (undoing the
status change) and the endpoint returned 500. The flag never turned off. The
audit writer now serialises enum values, and these tests drive the real
endpoints against the database and check the SDK-facing evaluation flips.
"""

import uuid

import pytest

from backend.app.models.audit_log import AuditLog
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus


@pytest.fixture
def active_flag(db_session, admin_user):
    flag = FeatureFlag(
        key=f"kill-switch-{uuid.uuid4().hex[:8]}",
        name="Kill switch flag",
        status=FeatureFlagStatus.ACTIVE,
        owner_id=admin_user.id,
        rollout_percentage=100,
    )
    db_session.add(flag)
    db_session.commit()
    db_session.refresh(flag)
    yield flag
    db_session.rollback()
    db_session.query(AuditLog).filter(AuditLog.entity_id == flag.id).delete()
    db_session.query(FeatureFlag).filter(FeatureFlag.id == flag.id).delete()
    db_session.commit()


def _audit_rows(db_session, flag):
    db_session.expire_all()
    return (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == flag.id)
        .order_by(AuditLog.created_at)
        .all()
    )


class TestKillSwitch:
    def test_disable_turns_the_flag_off_and_writes_a_readable_audit_row(
        self, admin_client, db_session, active_flag
    ):
        resp = admin_client.post(
            f"/api/v1/feature-flags/{active_flag.id}/disable",
            json={"reason": "demo kill switch"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["audit_log_id"] is not None

        db_session.expire_all()
        stored = (
            db_session.query(FeatureFlag).filter(FeatureFlag.id == active_flag.id).one()
        )
        assert stored.status == FeatureFlagStatus.INACTIVE

        rows = _audit_rows(db_session, active_flag)
        assert len(rows) == 1
        assert rows[0].old_value == "ACTIVE"
        assert rows[0].new_value == "INACTIVE"
        assert rows[0].reason == "demo kill switch"

    def test_disabled_flag_evaluates_off_for_sdk_clients(
        self, admin_client, active_flag
    ):
        before = admin_client.get(
            f"/api/v1/feature-flags/evaluate/{active_flag.key}?user_id=device-1"
        )
        assert before.status_code == 200 and before.json()["enabled"] is True

        assert (
            admin_client.post(
                f"/api/v1/feature-flags/{active_flag.id}/disable",
                json={"reason": "off"},
            ).status_code
            == 200
        )

        after = admin_client.get(
            f"/api/v1/feature-flags/evaluate/{active_flag.key}?user_id=device-1"
        )
        # A disabled flag is "off", not an error: SDKs must not log failures
        # (or fall back to cached "on" values) while the kill switch is pulled.
        assert after.status_code == 200, after.text
        assert after.json()["enabled"] is False
        assert after.json()["reason"] == "inactive"

        unknown = admin_client.get(
            "/api/v1/feature-flags/evaluate/no-such-flag?user_id=device-1"
        )
        assert unknown.status_code == 404

    def test_enable_restores_the_flag(self, admin_client, db_session, active_flag):
        admin_client.post(
            f"/api/v1/feature-flags/{active_flag.id}/disable", json={"reason": "off"}
        )
        resp = admin_client.post(
            f"/api/v1/feature-flags/{active_flag.id}/enable", json={"reason": "fixed"}
        )
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        stored = (
            db_session.query(FeatureFlag).filter(FeatureFlag.id == active_flag.id).one()
        )
        assert stored.status == FeatureFlagStatus.ACTIVE
        rows = _audit_rows(db_session, active_flag)
        assert [r.new_value for r in rows] == ["INACTIVE", "ACTIVE"]

    def test_toggle_flips_status_each_call(self, admin_client, db_session, active_flag):
        first = admin_client.post(
            f"/api/v1/feature-flags/{active_flag.id}/toggle", json={"reason": "flip"}
        )
        assert first.status_code == 200, first.text
        second = admin_client.post(
            f"/api/v1/feature-flags/{active_flag.id}/toggle",
            json={"reason": "flip back"},
        )
        assert second.status_code == 200, second.text

        db_session.expire_all()
        stored = (
            db_session.query(FeatureFlag).filter(FeatureFlag.id == active_flag.id).one()
        )
        assert stored.status == FeatureFlagStatus.ACTIVE
        assert len(_audit_rows(db_session, active_flag)) == 2
