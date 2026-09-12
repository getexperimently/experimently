"""
Integration tests: FeatureFlagService.evaluate_flag / evaluate_flag_detailed
with dashboard-shaped and native targeting rules against a real DB session.

Complements ``test_feature_flag_evaluation.py`` (legacy list rules, global
rollout). Every test cleans up the metric rows the evaluation records and the
flag it created.
"""

import pytest

from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.metrics.metric import ErrorLog, RawMetric
from backend.app.services.feature_flag_service import (
    REASON_INACTIVE,
    REASON_ROLLOUT,
    REASON_TARGETING_RULE,
    FeatureFlagService,
)
from backend.tests.integration.helpers import unique_flag_key


def _dashboard(groups, logical_operator="AND"):
    return {
        "logical_operator": logical_operator,
        "groups": [
            {"logical_operator": op, "conditions": conditions}
            for op, conditions in groups
        ],
    }


def _cond(attribute, operator, value=None):
    return {"attribute": attribute, "operator": operator, "value": value}


@pytest.fixture
def flag_factory(db_session, make_feature_flag):
    """``make_feature_flag`` that removes its flag and metric rows afterwards."""
    created = []

    def _make(**kwargs):
        kwargs.setdefault("status", FeatureFlagStatus.ACTIVE)
        flag = make_feature_flag(**kwargs)
        created.append(flag.id)
        return flag

    yield _make

    db_session.rollback()
    for flag_id in created:
        db_session.query(RawMetric).filter(
            RawMetric.feature_flag_id == flag_id
        ).delete()
        db_session.query(ErrorLog).filter(ErrorLog.feature_flag_id == flag_id).delete()
        db_session.query(FeatureFlag).filter(FeatureFlag.id == flag_id).delete()
    db_session.commit()


def _bucket_split(service, flag, percentage, n=200):
    """Users whose flag-level bucket is inside / outside ``percentage``."""
    inside, outside = [], []
    for i in range(n):
        user = f"bucket-user-{i}"
        (
            inside
            if service._evaluate_percentage_rollout(flag, user, percentage)
            else outside
        ).append(user)
    assert inside and outside
    return inside, outside


@pytest.mark.integration
@pytest.mark.requires_db
class TestDashboardRules:
    def test_semver_gte_on_os_version(self, db_session, flag_factory):
        flag = flag_factory(
            key=unique_flag_key("semver"),
            name="Semver Rule",
            rollout_percentage=0,
            targeting_rules=_dashboard(
                [("AND", [_cond("os_version", "semver_gte", "17.0.0")])]
            ),
        )
        service = FeatureFlagService(db_session)

        assert service.evaluate_flag(flag, "u1", {"os_version": "17.4.0"}) is True
        assert service.evaluate_flag(flag, "u2", {"os_version": "16.7.0"}) is False
        assert service.evaluate_flag(flag, "u3", {}) is False
        assert service.evaluate_flag(flag, "u4") is False

    def test_region_in_list(self, db_session, flag_factory):
        flag = flag_factory(
            key=unique_flag_key("region"),
            name="Region Rule",
            rollout_percentage=0,
            targeting_rules=_dashboard(
                [("AND", [_cond("region", "in", ["US", "GB"])])]
            ),
        )
        service = FeatureFlagService(db_session)

        assert service.evaluate_flag(flag, "u1", {"region": "US"}) is True
        assert service.evaluate_flag(flag, "u2", {"region": "GB"}) is True
        assert service.evaluate_flag(flag, "u3", {"region": "DE"}) is False
        # dotted attribute + alias also work
        assert service.evaluate_flag(flag, "u4", {"user": {"region": "US"}}) is True

    def test_employee_boolean(self, db_session, flag_factory):
        flag = flag_factory(
            key=unique_flag_key("employee"),
            name="Employee Rule",
            rollout_percentage=0,
            targeting_rules=_dashboard(
                [("AND", [_cond("employee", "equals", "true")])]
            ),
        )
        service = FeatureFlagService(db_session)

        assert service.evaluate_flag(flag, "u1", {"employee": True}) is True
        assert service.evaluate_flag(flag, "u2", {"employee": False}) is False
        assert service.evaluate_flag(flag, "u3", {"employee": "true"}) is True
        assert service.evaluate_flag(flag, "u4", {}) is False

    def test_streampulse_ai_search_rule(self, db_session, flag_factory):
        """AND group: os == iOS, os_version >= 17.0.0, region == US, tier == premium."""
        flag = flag_factory(
            key=unique_flag_key("ai-search"),
            name="AI Search",
            rollout_percentage=0,
            targeting_rules=_dashboard(
                [
                    (
                        "AND",
                        [
                            _cond("os", "equals", "iOS"),
                            _cond("os_version", "semver_gte", "17.0.0"),
                            _cond("region", "equals", "US"),
                            _cond("tier", "equals", "premium"),
                        ],
                    )
                ]
            ),
        )
        service = FeatureFlagService(db_session)
        iphone_15 = {
            "os": "iOS",
            "os_version": "17.4.0",
            "region": "US",
            "tier": "premium",
        }
        pixel_7 = {
            "os": "Android",
            "os_version": "14.0.0",
            "region": "DE",
            "tier": "free",
        }
        iphone_14 = {
            "os": "iOS",
            "os_version": "16.7.0",
            "region": "GB",
            "tier": "free",
        }

        assert service.evaluate_flag(flag, "d1", iphone_15) is True
        assert service.evaluate_flag(flag, "d2", pixel_7) is False
        assert service.evaluate_flag(flag, "d3", iphone_14) is False

    def test_matched_rule_uses_rule_percentage_unmatched_uses_global(
        self, db_session, flag_factory
    ):
        """Matched -> rule % (100 here); unmatched -> the flag's global %."""
        rules = _dashboard([("AND", [_cond("employee", "equals", "true")])])
        flag = flag_factory(
            key=unique_flag_key("rule-vs-global"),
            name="Rule vs Global",
            rollout_percentage=5,
            targeting_rules=rules,
        )
        service = FeatureFlagService(db_session)
        inside, outside = _bucket_split(service, flag, 5)

        # Matched: rule is 100% -> every employee is on, regardless of bucket
        for user in (inside[0], outside[0]):
            detail = service.evaluate_flag_detailed(flag, user, {"employee": True})
            assert detail == {
                "enabled": True,
                "reason": REASON_TARGETING_RULE,
                "rule_id": "dashboard",
            }

        # Unmatched: the global 5% decides, with the same flag-level bucket
        assert service.evaluate_flag_detailed(flag, inside[0], {"employee": False}) == {
            "enabled": True,
            "reason": REASON_ROLLOUT,
            "rule_id": None,
        }
        assert service.evaluate_flag_detailed(
            flag, outside[0], {"employee": False}
        ) == {
            "enabled": False,
            "reason": REASON_ROLLOUT,
            "rule_id": None,
        }

    def test_rule_rollout_percentage_buckets_with_flag_hash(
        self, db_session, flag_factory
    ):
        """A dashboard rule with rollout_percentage < 100 buckets on user_id:flag.key."""
        rules = {
            **_dashboard([("AND", [_cond("region", "equals", "US")])]),
            "rollout_percentage": 30,
        }
        flag = flag_factory(
            key=unique_flag_key("rule-pct"),
            name="Rule Percentage",
            rollout_percentage=0,
            targeting_rules=rules,
        )
        service = FeatureFlagService(db_session)
        inside, outside = _bucket_split(service, flag, 30)

        assert service.evaluate_flag_detailed(flag, inside[0], {"region": "US"}) == {
            "enabled": True,
            "reason": REASON_TARGETING_RULE,
            "rule_id": "dashboard",
        }
        assert service.evaluate_flag_detailed(flag, outside[0], {"region": "US"}) == {
            "enabled": False,
            "reason": REASON_TARGETING_RULE,
            "rule_id": "dashboard",
        }
        # Not in the rule -> global 0%
        assert service.evaluate_flag(flag, inside[0], {"region": "DE"}) is False

    def test_or_groups(self, db_session, flag_factory):
        """seed_demo_data beta_features: user.role in [beta, internal] OR user.email ends_with @acme.com."""
        flag = flag_factory(
            key=unique_flag_key("beta"),
            name="Beta Features",
            rollout_percentage=0,
            targeting_rules=_dashboard(
                [
                    ("AND", [_cond("user.role", "in", ["beta", "internal"])]),
                    ("AND", [_cond("user.email", "ends_with", "@acme.com")]),
                ],
                logical_operator="OR",
            ),
        )
        service = FeatureFlagService(db_session)

        assert service.evaluate_flag(flag, "u1", {"role": "beta"}) is True
        assert service.evaluate_flag(flag, "u2", {"email": "eve@acme.com"}) is True
        assert (
            service.evaluate_flag(
                flag, "u3", {"role": "free", "email": "eve@example.com"}
            )
            is False
        )

    def test_empty_dashboard_rules_fall_back_to_global(self, db_session, flag_factory):
        flag = flag_factory(
            key=unique_flag_key("empty-rules"),
            name="Empty Rules",
            rollout_percentage=100,
            targeting_rules={"logical_operator": "AND", "groups": []},
        )
        service = FeatureFlagService(db_session)
        assert service.evaluate_flag_detailed(flag, "u1", {"anything": 1}) == {
            "enabled": True,
            "reason": REASON_ROLLOUT,
            "rule_id": None,
        }

    def test_uninterpretable_dict_rules_fall_back_to_global(
        self, db_session, flag_factory
    ):
        flag = flag_factory(
            key=unique_flag_key("odd-rules"),
            name="Odd Rules",
            rollout_percentage=100,
            targeting_rules={"country": ["US", "CA"], "user_group": "beta"},
        )
        service = FeatureFlagService(db_session)
        assert service.evaluate_flag(flag, "u1", {"country": "DE"}) is True
        assert service.evaluate_flag_detailed(flag, "u1")["reason"] == REASON_ROLLOUT


@pytest.mark.integration
@pytest.mark.requires_db
class TestNativeRulesAndReasons:
    def test_native_rules_shape(self, db_session, flag_factory):
        flag = flag_factory(
            key=unique_flag_key("native"),
            name="Native Rules",
            rollout_percentage=0,
            targeting_rules={
                "rules": [
                    {
                        "id": "premium-us",
                        "rule": {
                            "operator": "and",
                            "conditions": [
                                {
                                    "attribute": "country",
                                    "operator": "eq",
                                    "value": "US",
                                },
                                {
                                    "attribute": "tier",
                                    "operator": "eq",
                                    "value": "premium",
                                },
                            ],
                        },
                        "rollout_percentage": 100,
                        "priority": 1,
                    }
                ]
            },
        )
        service = FeatureFlagService(db_session)

        assert service.evaluate_flag_detailed(
            flag, "u1", {"country": "US", "tier": "premium"}
        ) == {
            "enabled": True,
            "reason": REASON_TARGETING_RULE,
            "rule_id": "premium-us",
        }
        assert (
            service.evaluate_flag(flag, "u2", {"country": "US", "tier": "free"})
            is False
        )

    def test_inactive_reason(self, db_session, flag_factory):
        flag = flag_factory(
            key=unique_flag_key("inactive"),
            name="Inactive",
            status=FeatureFlagStatus.INACTIVE,
            rollout_percentage=100,
        )
        service = FeatureFlagService(db_session)
        assert service.evaluate_flag_detailed(flag, "u1") == {
            "enabled": False,
            "reason": REASON_INACTIVE,
            "rule_id": None,
        }

    def test_legacy_rules_report_rule_id(self, db_session, flag_factory):
        flag = flag_factory(
            key=unique_flag_key("legacy"),
            name="Legacy",
            rollout_percentage=0,
            targeting_rules=[
                {
                    "id": "vip",
                    "type": "user_id",
                    "user_ids": ["vip-1"],
                    "percentage": 100,
                }
            ],
        )
        service = FeatureFlagService(db_session)
        assert service.evaluate_flag_detailed(flag, "vip-1") == {
            "enabled": True,
            "reason": REASON_TARGETING_RULE,
            "rule_id": "vip",
        }
        assert (
            service.evaluate_flag_detailed(flag, "nobody")["reason"] == REASON_ROLLOUT
        )

    def test_evaluation_records_matched_rule_id(self, db_session, flag_factory):
        flag = flag_factory(
            key=unique_flag_key("metrics"),
            name="Metrics",
            rollout_percentage=0,
            targeting_rules=_dashboard([("AND", [_cond("region", "equals", "US")])]),
        )
        service = FeatureFlagService(db_session)
        service.evaluate_flag(flag, "metrics-user", {"region": "US"})

        metric = (
            db_session.query(RawMetric)
            .filter(
                RawMetric.feature_flag_id == flag.id,
                RawMetric.user_id == "metrics-user",
            )
            .filter(RawMetric.targeting_rule_id.isnot(None))
            .first()
        )
        assert metric is not None
        assert metric.targeting_rule_id == "dashboard"

    def test_get_user_flags_passes_context(self, db_session, flag_factory):
        flag = flag_factory(
            key=unique_flag_key("user-flags"),
            name="User Flags",
            rollout_percentage=0,
            targeting_rules=_dashboard([("AND", [_cond("tier", "equals", "premium")])]),
        )
        service = FeatureFlagService(db_session)
        assert service.get_user_flags("u1", {"tier": "premium"})[flag.key] is True
        assert service.get_user_flags("u1", {"tier": "free"})[flag.key] is False
