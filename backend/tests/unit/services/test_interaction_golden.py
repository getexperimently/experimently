"""
Frozen answers of the interaction test (#219), not keyed to ENGINE_VERSION.

The docs page's constant-relative-lift example: n = 2,000 in all four cells,
converters [[200, 400], [300, 600]].  The treatment lifts conversion by 50%
in both of B's arms (10% to 15%, 20% to 30%), which is +5 and +10 percentage
points: on the difference scale that is an interaction (S7).  X^2 is
8.4628326845 (p = 0.00362) by statsmodels, a profile likelihood and the
implementation alike.
"""

import pytest

from backend.app.services.interaction_analysis import floor_reason, interaction_test

pytestmark = pytest.mark.unit

N = [[2000, 2000], [2000, 2000]]
X = [[200, 400], [300, 600]]


def test_the_constant_relative_lift_table_is_frozen():
    assert floor_reason(N, X) is None
    result = interaction_test(N, X)
    assert result.statistic == pytest.approx(8.4628326845, rel=1e-9)
    assert result.degrees_of_freedom == 1
    assert result.p_value == pytest.approx(0.00362, abs=5e-6)


def test_s7_a_constant_relative_lift_is_an_interaction():
    """The scale pin: a relative-lift or log-odds test would not flag this."""
    assert interaction_test(N, X).p_value < 0.05


def test_no_interaction_on_the_difference_scale_gives_x2_zero():
    """+10 points in both arms: the additive model fits exactly."""
    result = interaction_test(N, [[200, 400], [400, 600]])
    assert result.statistic == pytest.approx(0.0, abs=1e-9)
    assert result.p_value == pytest.approx(1.0, abs=1e-9)
