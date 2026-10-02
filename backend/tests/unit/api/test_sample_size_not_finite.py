"""The sample-size routes refuse, with a 422, a size that is not a finite number.

``GET /api/v1/experiments/analysis/sample-size`` (the guided setup's estimate)
and ``POST /api/v1/utils/utils/sample-size`` both call
``sample_size_two_proportions``, which divides by ``(p2 - p1) ** 2``. Before
#694 two kinds of input answered 500:

* the treatment rate rounds to the baseline in floating point (a 0.12 baseline
  with a 1e-17 effect, or a 5e-324 baseline), and the helper raised
  ``ValueError``;
* the squared difference underflows to zero (any difference below about
  1.6e-162, so a 1e-300 baseline with a 5% effect), the quotient is infinity,
  and ``math.ceil`` raised ``OverflowError``.

Both now answer 422 with ``SAMPLE_SIZE_NOT_FINITE_MESSAGE``. Nothing else
changes: every input that was answered before gets the same number, however
large, because the refusal fires only where the old code raised.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.app.services.power_calculator_service import (
    SAMPLE_SIZE_NOT_FINITE_MESSAGE,
    SampleSizeNotFiniteError,
    sample_size_two_proportions,
)

WIZARD_URL = "/api/v1/experiments/analysis/sample-size"
UTILS_URL = "/api/v1/utils/utils/sample-size"
POWER_URL = "/api/v1/power/sample-size"

# Every input below answered 500 on both routes before #694.
NOT_FINITE = [
    pytest.param(1e-300, 0.05, id="baseline-1e-300"),  # square underflows
    pytest.param(1e-200, 0.05, id="baseline-1e-200"),  # square underflows
    pytest.param(1e-161, 0.05, id="baseline-1e-161"),  # square underflows
    pytest.param(5e-324, 0.05, id="baseline-5e-324"),  # rates equal
    pytest.param(1e-160, 1e-6, id="baseline-1e-160-mde-1e-6"),  # square underflows
    pytest.param(0.12, 1e-17, id="mde-1e-17"),  # rates equal
    pytest.param(0.12, 1e-300, id="mde-1e-300"),  # rates equal
    pytest.param(0.5, 1e-16, id="baseline-0.5-mde-1e-16"),  # rates equal
]


@pytest.fixture
def client():
    user = MagicMock(spec=User)
    user.id = 1
    user.username = "analyst"
    user.email = "analyst@example.com"
    user.role = UserRole.ANALYST
    user.is_active = True
    user.is_superuser = False
    user.hashed_password = "hashed"

    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    app.dependency_overrides[deps.get_current_user] = lambda: user
    try:
        # raise_server_exceptions=False: an unhandled error must surface as the
        # 500 a caller would see, so these tests can tell 422 from 500.
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides = {}


def ask_both(client, baseline, mde, power=0.8, alpha=0.05, one_sided=False):
    wizard = client.get(
        WIZARD_URL,
        params={
            "baseline_rate": baseline,
            "minimum_detectable_effect": mde,
            "statistical_power": power,
            "significance_level": alpha,
            "is_one_sided": one_sided,
        },
    )
    utils = client.post(
        UTILS_URL,
        params={"variant_count": 2},
        json={
            "baseline_rate": baseline,
            "minimum_detectable_effect": mde,
            "statistical_power": power,
            "significance_level": alpha,
            "is_one_sided": one_sided,
        },
    )
    return wizard, utils


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize(("baseline", "mde"), NOT_FINITE)
def test_a_size_that_is_not_finite_is_refused_on_both_routes(client, baseline, mde):
    for response in ask_both(client, baseline, mde):
        assert response.status_code == 422, response.text
        assert response.json()["detail"] == SAMPLE_SIZE_NOT_FINITE_MESSAGE


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize(
    ("power", "alpha", "one_sided"),
    [(0.5, 0.1, True), (0.99, 0.01, False)],
)
def test_the_refusal_holds_at_the_power_and_significance_edges(
    client, power, alpha, one_sided
):
    for response in ask_both(client, 1e-300, 0.05, power, alpha, one_sided):
        assert response.status_code == 422, response.text
        assert response.json()["detail"] == SAMPLE_SIZE_NOT_FINITE_MESSAGE


@pytest.mark.unit
@pytest.mark.regression
def test_the_power_calculator_route_refuses_it_too(client):
    """``POST /power/sample-size`` turns any ``ValueError`` into a 422, and the
    new error is one; the underflow case used to be its 500 too."""
    response = client.post(
        POWER_URL, json={"baseline_rate": 1e-300, "minimum_detectable_effect": 0.05}
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == SAMPLE_SIZE_NOT_FINITE_MESSAGE


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize(("baseline", "mde"), NOT_FINITE)
def test_the_helper_raises_a_value_error(baseline, mde):
    with pytest.raises(SampleSizeNotFiniteError) as caught:
        sample_size_two_proportions(
            baseline, baseline + baseline * mde, 0.05, 0.8, True
        )
    assert isinstance(caught.value, ValueError)
    assert str(caught.value) == SAMPLE_SIZE_NOT_FINITE_MESSAGE


# Answers both routes gave before #694, unchanged.
@pytest.mark.unit
@pytest.mark.parametrize(
    ("baseline", "mde", "power", "alpha", "one_sided", "expected"),
    [
        (0.12, 0.05, 0.8, 0.05, False, 47036),  # the documented case
        (0.10, 2.0, 0.8, 0.05, False, 62),
        (0.12, 0.05, 0.99, 0.01, False, 144011),
        (0.12, 0.05, 0.5, 0.1, True, 9843),
        (1e-300, 1e299, 0.8, 0.05, False, 74),
        (1e-6, 0.05, 0.8, 0.05, False, 6436074785),
        (0.12, 1e-3, 0.8, 0.05, False, 115166608),
    ],
)
def test_answers_that_worked_do_not_change(
    client, baseline, mde, power, alpha, one_sided, expected
):
    for response in ask_both(client, baseline, mde, power, alpha, one_sided):
        assert response.status_code == 200, response.text
        assert response.json()["samples_per_variant"] == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("baseline", "mde"),
    [
        (1e-160, 0.05),  # the smallest power of ten still answered at 5%
        (0.12, 1e-16),  # the smallest effect still answered at 12%
        (0.5, 2e-16),
    ],
)
def test_the_last_answered_inputs_are_still_answered(client, baseline, mde):
    """Just inside the refusal: still a 200, and the helper's own number."""
    expected = sample_size_two_proportions(
        baseline, baseline + baseline * mde, 0.05, 0.8, True
    )
    for response in ask_both(client, baseline, mde):
        assert response.status_code == 200, response.text
        assert response.json()["samples_per_variant"] == expected
