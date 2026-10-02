"""The wizard's sample-size estimate at every significance and power it offers.

``GET /api/v1/experiments/analysis/sample-size`` once took its critical values
from a helper with hard-coded shortcuts keyed on the probability it was given:
``0.05 -> 1.96``, ``0.01 -> 2.58``, ``0.1 -> 1.65``, ``0.5 -> 0.67``. The
two-sided path passes ``alpha / 2``, so the shortcuts fired for a two-sided
10% test (given 1.96, the two-sided 5% value), for one-sided tests at 5%, 1%
and 10%, and for power 0.5 (``z_beta`` 0.67 instead of 0). Those answers were
17-80% too large.

Since #685 the estimate uses the results page's two-proportion formula (pooled
variance under the null, unpooled under the alternative), which needs 1-5 more
users per variant than the unpooled-only formula it replaced; the documented
answer moved from 47,034 to 47,036.

Each case is checked twice: against a literal answer computed once and recorded,
and against the pooled formula evaluated here with ``norm.ppf``, so the test is
not a copy compared with a copy.
"""

import math
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from scipy.stats import norm

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.user import User, UserRole

SAMPLE_SIZE_URL = "/api/v1/experiments/analysis/sample-size"
BASELINE = 0.12
RELATIVE_MDE = 0.05

# (significance_level, statistical_power, is_one_sided, samples_per_variant)
CASES = [
    # Two-sided 10%. Shortcut era 47035 / 62966 / 77871; unpooled 37048 / 51318 / 64851.
    (0.10, 0.80, False, 37050),
    (0.10, 0.90, False, 51320),
    (0.10, 0.95, False, 64853),
    # One-sided. Shortcut era 47035 / 70156 / 37202; unpooled 37048 / 60140 / 27013.
    (0.05, 0.80, True, 37050),
    (0.01, 0.80, True, 60143),
    (0.10, 0.80, True, 27014),
    # Power 0.5. Shortcut era 41448; unpooled 23020.
    (0.05, 0.50, False, 23022),
    # Two-sided 5% and 1%. Unpooled 47034 / 62964 / 77869 / 69985 / 89163 / 106749.
    (0.05, 0.80, False, 47036),
    (0.05, 0.90, False, 62968),
    (0.05, 0.95, False, 77873),
    (0.01, 0.80, False, 69989),
    (0.01, 0.90, False, 89168),
    (0.01, 0.95, False, 106754),
]


def reference_per_variant(alpha: float, power: float, one_sided: bool) -> int:
    z_alpha = norm.ppf(1 - alpha) if one_sided else norm.ppf(1 - alpha / 2)
    z_beta = norm.ppf(power)
    p1 = BASELINE
    p2 = BASELINE * (1 + RELATIVE_MDE)
    p_bar = (p1 + p2) / 2
    root = z_alpha * math.sqrt(2 * p_bar * (1 - p_bar)) + z_beta * math.sqrt(
        p1 * (1 - p1) + p2 * (1 - p2)
    )
    return math.ceil(root**2 / (p2 - p1) ** 2)


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
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides = {}


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize(("alpha", "power", "one_sided", "expected"), CASES)
def test_sample_size_matches_exact_critical_values(
    client, alpha, power, one_sided, expected
):
    assert reference_per_variant(alpha, power, one_sided) == expected

    response = client.get(
        SAMPLE_SIZE_URL,
        params={
            "baseline_rate": BASELINE,
            "minimum_detectable_effect": RELATIVE_MDE,
            "significance_level": alpha,
            "statistical_power": power,
            "is_one_sided": one_sided,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["samples_per_variant"] == expected
    assert body["total_samples"] == expected * 2
