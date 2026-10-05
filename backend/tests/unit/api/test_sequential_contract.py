"""
The sequential analysis contract after #232/#222 (PR-E1).

``GET /api/v1/results/{id}/sequential``:

* honours a significance level -- the ``alpha`` query parameter, else the
  stored ``sequential_testing_config.alpha``, else 0.05 -- in (0, 0.2]; the
  mSPRT boundary is 1/alpha;
* returns ``alpha_spending == []``, with ``analysis_status`` and an
  ``analysis_notice`` that says the planned-looks table is not computed;
* echoes a stored ``always_valid`` method as ``msprt``, with a notice;
* reports a long-running experiment as the advisory ``at_risk`` and keeps
  ``recommended_action`` to the mSPRT's own decision, whose value set stays
  exactly the dashboard's ``RecommendedAction``.

These run the real ``SequentialTestingService``; only the database reads are
patched, with known per-arm counts.
"""

import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api.deps import get_current_user, get_db
from backend.app.core.analysis_status import GA, AnalysisLabel, analysis_label
from backend.app.main import app
from backend.app.models.user import User
from backend.app.schemas.experiment import SequentialTestingConfigInput
from backend.app.schemas.sequential import RECOMMENDED_ACTIONS

REPO_ROOT = Path(__file__).resolve().parents[4]
DASHBOARD_TYPES = REPO_ROOT / "frontend" / "src" / "types" / "sequential.ts"

EXPERIMENT_UUID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
URL = f"/api/v1/results/{EXPERIMENT_UUID}/sequential"

# Equal arms: no evidence either way (Lambda well below 1/alpha).
EQUAL_ARMS = (200, 2000, 200, 2000)
# A clear lift: 2.5% vs 10%, Lambda far above 1/alpha for any alpha here.
CLEAR_LIFT = (50, 2000, 200, 2000)


@pytest.fixture
def client():
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.is_active = True
    user.is_superuser = True
    user.role = "ADMIN"

    def override_get_db():
        yield MagicMock()

    async def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides = {}


def _experiment(
    config: Optional[Dict[str, Any]] = None,
    method: Optional[str] = "msprt",
    started_days_ago: int = 7,
) -> MagicMock:
    experiment = MagicMock()
    experiment.sequential_testing_enabled = True
    experiment.sequential_testing_method = method
    experiment.sequential_testing_config = config
    experiment.start_date = datetime.now(timezone.utc) - timedelta(
        days=started_days_ago
    )
    return experiment


def _get(client, experiment, counts=EQUAL_ARMS, params=None):
    with (
        patch(
            "backend.app.api.v1.endpoints.results._get_experiment_for_sequential",
            return_value=experiment,
        ),
        patch(
            "backend.app.api.v1.endpoints.results._get_sequential_data",
            return_value=counts,
        ),
    ):
        return client.get(URL, params=params or {})


def _stored(config_in: Dict[str, Any]) -> Dict[str, Any]:
    """What the experiments API stores for a sequential_testing_config body.

    ``ExperimentService.create_experiment`` stores
    ``jsonable_encoder(obj_in, exclude_unset=True)``; this is that encoding of
    the nested config, so a field the input schema drops is dropped here too.
    """
    return jsonable_encoder(
        SequentialTestingConfigInput(**config_in), exclude_unset=True
    )


# ---------------------------------------------------------------------------
# alpha
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_stored_alpha_001_gives_boundary_100(client):
    """A config saved with alpha 0.01 is analysed at 0.01: boundary 1/0.01.

    On main the input schema had no ``alpha``, so the value was dropped on the
    way in and every analysis ran at 0.05 (boundary 20).
    """
    response = _get(client, _experiment(_stored({"alpha": 0.01})))
    assert response.status_code == 200, response.text
    assert response.json()["msprt_result"]["boundary"] == pytest.approx(100.0)


@pytest.mark.regression
def test_alpha_query_001_gives_boundary_100(client):
    """``?alpha=0.01`` is used by the mSPRT; on main it was ignored."""
    response = _get(client, _experiment({}), params={"alpha": 0.01})
    assert response.status_code == 200, response.text
    assert response.json()["msprt_result"]["boundary"] == pytest.approx(100.0)


def test_alpha_query_overrides_the_stored_alpha(client):
    response = _get(
        client, _experiment(_stored({"alpha": 0.01})), params={"alpha": 0.2}
    )
    assert response.status_code == 200, response.text
    assert response.json()["msprt_result"]["boundary"] == pytest.approx(5.0)


def test_alpha_defaults_to_005(client):
    response = _get(client, _experiment(None))
    assert response.status_code == 200, response.text
    assert response.json()["msprt_result"]["boundary"] == pytest.approx(20.0)


def test_alpha_changes_the_decision_not_only_the_label(client):
    """The same data stops at alpha 0.2 and continues at alpha 0.001 when
    Lambda lies between the two boundaries (5 and 1000)."""
    # 10% vs 13% on 2000 per arm: Lambda is about 17 (asserted below).
    counts = (200, 2000, 260, 2000)
    loose = _get(client, _experiment({}), counts, {"alpha": 0.2}).json()
    strict = _get(client, _experiment({}), counts, {"alpha": 0.001}).json()
    lam = loose["msprt_result"]["lambda_ratio"]
    assert 5.0 < lam < 1000.0
    assert loose["recommended_action"] == "stop_for_effect"
    assert strict["recommended_action"] == "continue"


@pytest.mark.parametrize("bad", [0, -0.1, 0.21, 0.5, 1])
def test_alpha_query_outside_range_is_422(client, bad):
    response = _get(client, _experiment({}), params={"alpha": bad})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("bad", [0, -0.1, 0.21, 1])
def test_config_input_refuses_alpha_outside_range(bad):
    with pytest.raises(ValidationError):
        SequentialTestingConfigInput(alpha=bad)


def test_config_input_accepts_the_range_ends():
    assert SequentialTestingConfigInput(alpha=0.2).alpha == 0.2
    assert SequentialTestingConfigInput(alpha=1e-6).alpha == 1e-6
    assert SequentialTestingConfigInput().alpha == 0.05


@pytest.mark.parametrize("stored", [0.5, 0, "0.01", True])
def test_unusable_stored_alpha_uses_005_and_says_so(client, stored):
    response = _get(client, _experiment({"alpha": stored}))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["msprt_result"]["boundary"] == pytest.approx(20.0)
    assert f"The stored alpha {stored!r}" in body["analysis_notice"]


# ---------------------------------------------------------------------------
# alpha_spending
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_alpha_spending_is_empty_with_a_notice(client):
    """No planned-looks table is computed, whatever the config asks for.

    On main a config with five planned looks returned one O'Brien-Fleming
    boundary (#232: those boundaries did not hold the significance level).
    """
    config = _stored({"spending_function": "obrien_fleming", "planned_looks": 5})
    response = _get(client, _experiment(config))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["alpha_spending"] == []
    assert body["analysis_status"] == "beta"
    assert (
        "planned-looks (alpha-spending) table is not computed yet"
        in (body["analysis_notice"])
    )


def test_pocock_config_also_gives_no_table(client):
    config = _stored({"spending_function": "pocock", "planned_looks": 4})
    body = _get(client, _experiment(config)).json()
    assert body["alpha_spending"] == []


# ---------------------------------------------------------------------------
# method
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "config, column",
    [
        ({"method": "always_valid"}, "msprt"),
        ({}, "always_valid"),
    ],
    ids=["config-method", "method-column"],
)
def test_always_valid_is_echoed_as_msprt_with_a_notice(client, config, column):
    """``always_valid`` is accepted as an alias and the response says so.

    On main it was silently reported as ``msprt`` with no notice (#222).
    """
    body = _get(client, _experiment(_stored(config), method=column)).json()
    assert body["method"] == "msprt"
    assert "'always_valid' is an alias of 'msprt'" in body["analysis_notice"]


def test_msprt_has_no_alias_notice(client):
    body = _get(client, _experiment(_stored({"method": "msprt"}))).json()
    assert body["method"] == "msprt"
    assert "alias" not in body["analysis_notice"]


# ---------------------------------------------------------------------------
# at_risk and recommended_action
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_long_running_inconclusive_is_at_risk_and_continue(client):
    """60 days into a 30-day plan with equal arms: at_risk, continue.

    On main this returned ``stop_for_futility``: a time-based rule, not a
    statistical futility boundary.
    """
    body = _get(client, _experiment({}, started_days_ago=60)).json()
    assert body["recommended_action"] == "continue"
    assert body["msprt_result"]["can_stop"] is False
    assert body["long_running_risk"]["is_at_risk"] is True
    assert body["at_risk"] is True


def test_on_schedule_is_not_at_risk(client):
    body = _get(client, _experiment({}, started_days_ago=3), CLEAR_LIFT).json()
    assert body["at_risk"] is False
    assert body["recommended_action"] == "stop_for_effect"


def test_long_running_with_a_clear_effect_still_stops_for_effect(client):
    body = _get(client, _experiment({}, started_days_ago=60), CLEAR_LIFT).json()
    assert body["at_risk"] is True
    assert body["recommended_action"] == "stop_for_effect"


def test_recommended_action_set_is_the_dashboard_type():
    """The value set is exactly the dashboard's ``RecommendedAction`` union,
    and exactly these three values."""
    source = DASHBOARD_TYPES.read_text(encoding="utf-8")
    match = re.search(r"export type RecommendedAction\s*=\s*([^;]+);", source)
    assert match, f"RecommendedAction not found in {DASHBOARD_TYPES}"
    dashboard = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert dashboard == set(RECOMMENDED_ACTIONS)
    assert set(RECOMMENDED_ACTIONS) == {
        "stop_for_effect",
        "stop_for_futility",
        "continue",
    }


# ---------------------------------------------------------------------------
# analysis_status
# ---------------------------------------------------------------------------


# The table itself (statuses, notice iff beta) is pinned in
# backend/tests/unit/core/test_analysis_status.py.


def test_sequential_response_carries_the_table_label(client):
    label = analysis_label("sequential")
    body = _get(client, _experiment(_stored({"method": "msprt"}))).json()
    assert body["analysis_status"] == label.status
    assert body["analysis_notice"] == label.notice


def test_route_reads_the_table_when_it_answers(client):
    """Flip the table entry to ga: the response follows, and the alias and
    bad-alpha sentences do not invent a notice on a ga label."""
    config = {"method": "always_valid", "alpha": 0.5}
    with patch.dict(
        "backend.app.core.analysis_status.ANALYSIS_STATUS",
        {"sequential": AnalysisLabel(GA)},
    ):
        body = _get(client, _experiment(config)).json()
    assert body["analysis_status"] == "ga"
    assert body["analysis_notice"] is None


def test_appended_sentences_follow_the_base_notice(client):
    base = analysis_label("sequential").notice
    body = _get(client, _experiment({"method": "always_valid", "alpha": 0.5})).json()
    assert body["analysis_notice"].startswith(base + " ")
    assert "The stored alpha 0.5" in body["analysis_notice"]
    assert "'always_valid' is an alias of 'msprt'" in body["analysis_notice"]


# ---------------------------------------------------------------------------
# An overwhelming difference
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "counts",
    [
        (1, 100, 99, 100),
        (1_000_000, 10_000_000, 1_100_000, 10_000_000),
    ],
)
def test_overwhelming_difference_answers_a_finite_lambda(client, counts):
    """#854: the response carries a finite number for ``lambda_ratio``.

    The evidence ratio is capped at the largest finite double.  An unbounded
    ``inf`` would serialise as JSON ``null``, which the schema (a required
    ``number``) and the dashboard (``lambda_ratio.toFixed``) do not accept.
    """
    response = _get(client, _experiment({}), counts=counts)
    assert response.status_code == 200, response.text
    msprt = json.loads(response.text)["msprt_result"]
    assert isinstance(msprt["lambda_ratio"], float)
    assert math.isfinite(msprt["lambda_ratio"])
    assert msprt["can_stop"] is True
    assert response.json()["recommended_action"] == "stop_for_effect"
