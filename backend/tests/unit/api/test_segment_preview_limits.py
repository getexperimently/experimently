"""
The ruleset limits on ``POST /api/v1/segments/{segment_id}/preview``.

A preview answers 422 -- in the declared ``HTTPValidationError`` shape and
before any database query -- when the request's ruleset, counted recursively
over nested groups, has

(a) more than 50 conditions,
(b) more than 10 ``match_regex`` conditions,
(c) more than 1,000 list elements across condition values, or
(d) ``match_regex`` conditions x the requested ``sample_size`` above 500,
(a') more than 20 groups, or
(e) conditions plus groups x the requested ``sample_size`` above 50,000.

The endpoint tests run the real endpoint and the real
``AudienceService.preview_audience_size`` against a ``MagicMock`` session whose
assignment query returns no rows (an empty table). Every call made on the
session is recorded in ``session.mock_calls``, which is how the "no database
query" property is observed.
"""

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.core.segment_preview_limits import (
    MAX_PREVIEW_CONDITIONS,
    MAX_PREVIEW_GROUPS,
    MAX_PREVIEW_LIST_ELEMENTS,
    MAX_PREVIEW_NODE_EVALUATIONS,
    MAX_PREVIEW_REGEX_CONDITIONS,
    MAX_PREVIEW_REGEX_EVALUATIONS,
    count_ruleset,
    preview_ruleset_violations,
)
from backend.app.main import app
from backend.app.models.user import User, UserRole

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
STABLE_SNAPSHOT = REPO_ROOT / "docs" / "api" / "openapi-v1.stable.json"
PREVIEW_PATH = "/api/v1/segments/{segment_id}/preview"

# Present in the request body so a test can prove no message echoes it.
MARKER = "zq_request_marker_7c1f"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _eq(i: int = 0) -> dict:
    return {"attribute": f"{MARKER}_attr_{i}", "operator": "eq", "value": MARKER}


def _regex(i: int = 0) -> dict:
    return {
        "attribute": f"{MARKER}_attr_{i}",
        "operator": "match_regex",
        "value": f"^{MARKER}[a-z]+$",
    }


def _in(n: int) -> dict:
    return {
        "attribute": "country",
        "operator": "in",
        "value": [f"{MARKER}{i}" for i in range(n)],
    }


def _nested_conditions(total: int) -> dict:
    """``total`` eq conditions: 5 at the top, the rest two and three levels deep."""
    top = min(total, 5)
    rest = total - top
    middle = rest // 2
    deepest = rest - middle
    return {
        "operator": "and",
        "conditions": [_eq(i) for i in range(top)],
        "groups": [
            {
                "operator": "or",
                "conditions": [_eq(i) for i in range(middle)],
                "groups": [
                    {
                        "operator": "and",
                        "conditions": [_eq(i) for i in range(deepest)],
                    }
                ],
            }
        ],
    }


def _flat(conditions: list) -> dict:
    return {"operator": "and", "conditions": conditions}


def _with_groups(conditions: int, groups: int) -> dict:
    """``conditions`` eq conditions at the top and ``groups`` empty groups."""
    return {
        "operator": "and",
        "conditions": [_eq(i) for i in range(conditions)],
        "groups": [{"operator": "and", "conditions": []} for _ in range(groups)],
    }


def _every_limit() -> dict:
    """A ruleset over (a), (a'), (b) and (c); at sample 1000 also (d) and (e)."""
    rules = {**_nested_conditions(60), "conditions": [_in(1001)] + [_regex()] * 11}
    rules["groups"] = rules["groups"] + [{} for _ in range(MAX_PREVIEW_GROUPS)]
    return rules


def _viewer() -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "viewer"
    user.email = "viewer@example.com"
    user.is_active = True
    user.is_superuser = False
    user.role = UserRole.VIEWER
    return user


def _empty_table_session() -> MagicMock:
    """A session whose segment lookup finds a row and whose assignments are empty."""
    session = MagicMock()
    session.query.return_value.limit.return_value.all.return_value = []
    return session


@pytest.fixture
def preview():
    """POST a preview as a VIEWER; returns (response, session)."""
    app.dependency_overrides.clear()
    client = TestClient(app)

    def _post(rules: dict, sample_size: int | None = None):
        session = _empty_table_session()
        app.dependency_overrides[deps.get_current_active_user] = _viewer
        app.dependency_overrides[deps.get_db] = lambda: session
        url = f"/api/v1/segments/{uuid.uuid4()}/preview"
        if sample_size is not None:
            url += f"?sample_size={sample_size}"
        response = client.post(url, json={"name": "Preview", "rules": rules})
        return response, session

    yield _post
    app.dependency_overrides.clear()


def _assert_refused(response, loc: list) -> list:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail, detail
    assert all(item["type"] == "value_error" for item in detail), detail
    assert loc in [item["loc"] for item in detail], detail
    return detail


def _assert_previewed(response) -> None:
    assert response.status_code == 200, response.text
    body = response.json()
    # The empty table: the real service ran and sampled nothing.
    assert body == {"estimated_percentage": 0.0, "sample_size": 0, "matched": 0}


# ---------------------------------------------------------------------------
# (i) match_regex conditions
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_eleven_match_regex_conditions_are_refused(preview):
    rules = _flat([_regex(i) for i in range(MAX_PREVIEW_REGEX_CONDITIONS + 1)])
    # sample_size 10 keeps (d) at 110, so only (b) applies.
    response, _ = preview(rules, sample_size=10)
    detail = _assert_refused(response, ["body", "rules"])
    assert len(detail) == 1
    assert "11 match_regex conditions" in detail[0]["msg"]
    assert "at most 10" in detail[0]["msg"]


@pytest.mark.regression
def test_ten_match_regex_conditions_with_sample_size_50_are_previewed(preview):
    rules = _flat([_regex(i) for i in range(MAX_PREVIEW_REGEX_CONDITIONS)])
    response, _ = preview(rules, sample_size=50)
    _assert_previewed(response)


# ---------------------------------------------------------------------------
# (ii) conditions in total, nested groups included
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_51_conditions_split_across_nested_groups_are_refused(preview):
    rules = _nested_conditions(MAX_PREVIEW_CONDITIONS + 1)
    # Nearly all of them sit below the top level.
    assert len(rules["conditions"]) == 5
    response, _ = preview(rules)
    detail = _assert_refused(response, ["body", "rules"])
    assert "51 conditions" in detail[0]["msg"]


@pytest.mark.regression
def test_50_conditions_split_across_nested_groups_are_previewed(preview):
    # 50 conditions + 2 groups = 52 nodes; at sample_size 961, 49,972 (e).
    response, _ = preview(_nested_conditions(MAX_PREVIEW_CONDITIONS), 961)
    _assert_previewed(response)


# ---------------------------------------------------------------------------
# (iii) list elements across condition values
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_1001_list_elements_are_refused(preview):
    rules = _nested_conditions(0)
    rules["conditions"] = [_in(500)]
    rules["groups"][0]["conditions"] = [_in(501)]
    response, _ = preview(rules)
    detail = _assert_refused(response, ["body", "rules"])
    assert "1001 list elements" in detail[0]["msg"]


@pytest.mark.regression
def test_1000_list_elements_are_previewed(preview):
    rules = _nested_conditions(0)
    rules["conditions"] = [_in(500)]
    rules["groups"][0]["conditions"] = [_in(MAX_PREVIEW_LIST_ELEMENTS - 500)]
    response, _ = preview(rules)
    _assert_previewed(response)


# ---------------------------------------------------------------------------
# (iv) match_regex conditions x the requested sample_size
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("patterns,sample_size", [(1, 501), (3, 167), (7, 72)])
def test_regex_conditions_times_sample_size_over_500_are_refused(
    preview, patterns, sample_size
):
    assert patterns * sample_size > MAX_PREVIEW_REGEX_EVALUATIONS
    rules = _flat([_regex(i) for i in range(patterns)])
    # The table is empty: the refusal must come from the REQUESTED sample_size.
    response, _ = preview(rules, sample_size=sample_size)
    detail = _assert_refused(response, ["query", "sample_size"])
    assert len(detail) == 1
    assert f"= {patterns * sample_size}" in detail[0]["msg"]


@pytest.mark.regression
@pytest.mark.parametrize("patterns,sample_size", [(1, 500), (5, 100), (10, 50)])
def test_regex_conditions_times_sample_size_of_500_are_previewed(
    preview, patterns, sample_size
):
    rules = _flat([_regex(i) for i in range(patterns)])
    response, _ = preview(rules, sample_size=sample_size)
    _assert_previewed(response)


def test_the_default_sample_size_counts_for_d(preview):
    # One pattern with the default sample_size of 1000 is 1000 > 500.
    response, _ = preview(_flat([_regex()]))
    _assert_refused(response, ["query", "sample_size"])


# ---------------------------------------------------------------------------
# (a') groups in total
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_21_empty_groups_are_refused(preview):
    response, _ = preview(_with_groups(0, MAX_PREVIEW_GROUPS + 1))
    detail = _assert_refused(response, ["body", "rules"])
    assert len(detail) == 1
    assert "21 groups" in detail[0]["msg"]
    assert "at most 20" in detail[0]["msg"]


@pytest.mark.regression
def test_20_empty_groups_are_previewed(preview):
    response, _ = preview(_with_groups(0, MAX_PREVIEW_GROUPS))
    _assert_previewed(response)


@pytest.mark.regression
def test_21_groups_nested_one_inside_another_are_refused(preview):
    rules: dict = {"conditions": [_eq()]}
    for _ in range(MAX_PREVIEW_GROUPS + 1):
        rules = {"groups": [rules]}
    response, _ = preview(rules)
    _assert_refused(response, ["body", "rules"])


# ---------------------------------------------------------------------------
# (e) conditions plus groups x the requested sample_size
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "conditions,groups,sample_size",
    # 1 + 6 = 7 nodes x 7143 = 50,001; 10 + 20 = 30 nodes x 1667 = 50,010.
    [(1, 6, 7143), (10, 20, 1667)],
)
def test_nodes_times_sample_size_over_50000_are_refused(
    preview, conditions, groups, sample_size
):
    nodes = conditions + groups
    assert nodes * sample_size > MAX_PREVIEW_NODE_EVALUATIONS
    # Conditions alone stay inside the limit: only counting the groups as
    # well refuses these.
    assert conditions * sample_size <= MAX_PREVIEW_NODE_EVALUATIONS
    response, _ = preview(_with_groups(conditions, groups), sample_size)
    detail = _assert_refused(response, ["query", "sample_size"])
    assert len(detail) == 1
    assert f"= {nodes * sample_size}" in detail[0]["msg"]
    largest = MAX_PREVIEW_NODE_EVALUATIONS // nodes
    assert f"sample_size of {largest} or less" in detail[0]["msg"]


@pytest.mark.regression
@pytest.mark.parametrize(
    "conditions,groups,sample_size",
    # 5 + 20 = 25 x 2000; 50 + 0 at the default 1000; 5 + 0 x 10,000.
    [(5, 20, 2000), (50, 0, None), (5, 0, 10000)],
)
def test_nodes_times_sample_size_of_50000_are_previewed(
    preview, conditions, groups, sample_size
):
    response, _ = preview(_with_groups(conditions, groups), sample_size)
    _assert_previewed(response)


def test_no_node_sample_size_suggestion_below_the_endpoint_minimum():
    errors = preview_ruleset_violations(_with_groups(6000, 0), 10)
    node_error = errors[-1]
    assert node_error["loc"] == ["query", "sample_size"]
    assert "sample_size of" not in node_error["msg"]
    assert "fewer conditions and groups" in node_error["msg"]


# ---------------------------------------------------------------------------
# (v) a refusal issues no database query
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "rules,sample_size",
    [
        (_flat([_regex(i) for i in range(11)]), 10),
        (_nested_conditions(51), None),
        (_flat([_in(1001)]), None),
        (_flat([_regex()]), 501),
        (_with_groups(0, 21), None),
        (_with_groups(1, 6), 7143),
    ],
    ids=["b-regex", "a-conditions", "c-list", "d-sample", "a2-groups", "e-nodes"],
)
def test_a_refusal_issues_no_database_query(preview, rules, sample_size):
    response, session = preview(rules, sample_size)
    assert response.status_code == 422, response.text
    assert session.mock_calls == []


def test_the_session_probe_sees_the_queries_of_an_accepted_preview(preview):
    """The probe above is live: an accepted preview does query the session."""
    response, session = preview(_flat([_eq()]))
    _assert_previewed(response)
    queried = [c for c in session.mock_calls if c[0] == "query"]
    assert len(queried) == 2, session.mock_calls  # the segment, the assignments


# ---------------------------------------------------------------------------
# (vi) the 422 body is the declared HTTPValidationError
# ---------------------------------------------------------------------------


def _http_validation_error_schema() -> dict:
    snapshot = json.loads(STABLE_SNAPSHOT.read_text())
    operation = snapshot["paths"][PREVIEW_PATH]["post"]
    declared = operation["responses"]["422"]["content"]["application/json"]["schema"]
    assert declared == {"$ref": "#/components/schemas/HTTPValidationError"}
    return {"components": snapshot["components"], **declared}


@pytest.mark.regression
@pytest.mark.parametrize(
    "rules,sample_size",
    [
        (_flat([_regex(i) for i in range(11)]), 10),
        (_nested_conditions(51), None),
        (_flat([_in(1001)]), None),
        (_flat([_regex()]), 501),
        (_with_groups(0, 21), None),
        (_with_groups(1, 6), 7143),
        # Every limit at once.
        (_every_limit(), 1000),
    ],
    ids=[
        "b-regex",
        "a-conditions",
        "c-list",
        "d-sample",
        "a2-groups",
        "e-nodes",
        "all",
    ],
)
def test_the_refusal_matches_the_snapshot_and_echoes_no_request_content(
    preview, rules, sample_size
):
    response, _ = preview(rules, sample_size)
    assert response.status_code == 422, response.text
    body = response.json()
    jsonschema.validate(body, _http_validation_error_schema())
    for item in body["detail"]:
        assert set(item) == {"loc", "msg", "type"}
        assert MARKER not in item["msg"]
        assert item["loc"] in (["body", "rules"], ["query", "sample_size"])


def test_every_limit_is_reported_at_once(preview):
    response, _ = preview(_every_limit(), sample_size=1000)
    detail = _assert_refused(response, ["body", "rules"])
    assert [item["loc"] for item in detail] == [
        ["body", "rules"],  # (a) conditions
        ["body", "rules"],  # (a') groups
        ["body", "rules"],  # (b) match_regex
        ["body", "rules"],  # (c) list elements
        ["query", "sample_size"],  # (d)
        ["query", "sample_size"],  # (e)
    ]


# ---------------------------------------------------------------------------
# The counting, directly
# ---------------------------------------------------------------------------


def test_counts_the_dashboard_shape_and_the_regex_alias():
    rules = {
        "logical_operator": "AND",
        "groups": [
            {
                "logical_operator": "OR",
                "conditions": [
                    {"attribute": "email", "operator": "regex", "value": "x"},
                    {"attribute": "email", "operator": "MATCH_REGEX", "value": "y"},
                    {"attribute": "plan", "operator": "in", "value": ["a", "b"]},
                ],
            }
        ],
    }
    assert count_ruleset(rules) == {
        "conditions": 3,
        "groups": 1,
        "regex_conditions": 2,
        "list_elements": 2,
    }


def test_counts_nested_lists_and_additional_value():
    condition = {
        "attribute": "a",
        "operator": "between",
        "value": [[1, 2], [3]],  # 2 outer + 3 inner
        "additional_value": {"k": [4, 5]},  # 2
    }
    assert count_ruleset(_flat([condition]))["list_elements"] == 7


def test_malformed_items_still_count_as_conditions():
    rules = {"conditions": ["x", 1, None, {"operator": 5}], "groups": ["y", None]}
    assert count_ruleset(rules) == {
        "conditions": 4,
        "groups": 2,
        "regex_conditions": 0,
        "list_elements": 0,
    }


@pytest.mark.parametrize("rules", [None, [], "rules", 3, {"conditions": "x"}])
def test_rules_that_are_not_a_group_count_as_empty(rules):
    assert preview_ruleset_violations(rules, 10_000) == []


def test_deep_nesting_is_counted_without_recursion():
    rules: dict = {"conditions": [_regex()]}
    for _ in range(5000):
        rules = {"groups": [rules]}
    assert count_ruleset(rules)["regex_conditions"] == 1


def test_the_largest_accepted_sample_size_is_suggested():
    [error] = preview_ruleset_violations(_flat([_regex()] * 3), 200)
    assert "sample_size of 166 or less" in error["msg"]


def test_no_sample_size_suggestion_below_the_endpoint_minimum():
    errors = preview_ruleset_violations(_flat([_regex()] * 60), 10)
    assert "sample_size of" not in errors[-1]["msg"]
    assert errors[-1]["loc"] == ["query", "sample_size"]
