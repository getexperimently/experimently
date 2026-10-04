"""The demo seed's CUPED history is balanced across the arms (#217).

``seed_demo_data.py`` gives ``checkout_button_color``'s users a key-less
``checkout_completed`` before their assignment, with a probability that
depends on whether they convert in the experiment and on their arm.  That
models a habit formed before assignment only if the share of users with
history is the same in both arms: ``P(X=1 | arm) = p1 * cvr + p0 * (1 - cvr)``.
Equal probabilities in both arms would not be (green converts more), and the
documentation's CUPED example would then remove part of the real effect.

The gate is arithmetic on the seed's own constants, so it is exact.  With the
probabilities (0.6, 0.04) in both arms the shares are 0.0848 and 0.0904, a gap
of 0.0056, and it fails.
"""

import random
from datetime import datetime, timedelta, timezone

import pytest

from backend.scripts import seed_demo_data as seed

pytestmark = pytest.mark.unit


def test_history_is_equally_likely_in_both_arms():
    blue = seed.checkout_history_share("blue_button")
    green = seed.checkout_history_share("green_button")
    assert abs(blue - green) < 1e-3, (blue, green)


def test_the_shares_come_from_the_arms_own_conversion_rates():
    assert seed.CHECKOUT_CVR == {"blue_button": 0.08, "green_button": 0.09}
    p1, p0 = seed.CHECKOUT_HISTORY_P["blue_button"]
    assert seed.checkout_history_share("blue_button") == pytest.approx(
        p1 * 0.08 + p0 * 0.92, abs=1e-15
    )


def test_a_history_event_is_untagged_and_stored_a_day_before_assignment():
    assigned = datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)
    rng = random.Random(1)
    events = [
        seed._checkout_history_event(rng, "green_button", "u", assigned, True)
        for _ in range(200)
    ]
    events = [e for e in events if e is not None]
    assert events, "the probe drew no history at all"
    for event in events:
        assert event.experiment_id is None
        assert event.variant_id is None
        assert event.feature_flag_id is None
        assert event.event_name == "checkout_completed"
        # Naive UTC, at least a day before the (aware) assignment.
        assert event.updated_at.tzinfo is None
        received = event.updated_at.replace(tzinfo=timezone.utc)
        assert received <= assigned - timedelta(days=1)
        assert datetime.fromisoformat(event.created_at) == received
