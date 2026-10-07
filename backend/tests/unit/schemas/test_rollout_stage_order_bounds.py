"""Rollout stage orders have an upper bound.

* ``stage_order`` had a lower bound only: a create with an order above
  ``sys.maxsize`` answered 500.
* Every request model now bounds ``stage_order`` at ``MAX_STAGE_ORDER``
  (1000), so a larger value answers 422 naming the field.
* The gap check accepts and refuses exactly what the old check did (pinned
  below for every short list).
* The response model is not bounded: a stored order can be higher than a
  request may set (adding a stage in the middle moves later stages up), and a
  read must still describe it.

The request-level answers are pinned by
``backend/tests/integration/api/test_rollout_stage_order_bounds_api.py``.
"""

from __future__ import annotations

import itertools
import tracemalloc
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.app.schemas.rollout_schedule import (
    MAX_STAGE_ORDER,
    RolloutScheduleCreate,
    RolloutScheduleUpdate,
    RolloutStageCreate,
    RolloutStageResponse,
    RolloutStageUpdate,
)

pytestmark = [pytest.mark.unit]

#: The peak traced allocation allowed while one request body is refused.
PEAK_BYTES = 5 * 1024 * 1024


def _stage(order: int, percentage: int = 10) -> dict:
    return {
        "name": f"Stage {order}",
        "stage_order": order,
        "target_percentage": percentage,
        "trigger_type": "manual",
    }


def _schedule(*orders: int) -> dict:
    return {
        "name": "Bounded orders",
        "feature_flag_id": str(uuid.uuid4()),
        "stages": [_stage(order) for order in orders],
    }


def _constructed(*orders: int) -> RolloutScheduleCreate:
    """A schedule whose stages skipped field validation, for the gap check alone."""
    return RolloutScheduleCreate.model_construct(
        name="Gap check",
        feature_flag_id=uuid.uuid4(),
        max_percentage=100,
        stages=[
            RolloutStageCreate.model_construct(stage_order=order, target_percentage=10)
            for order in orders
        ],
    )


def _old_gap_check_accepts(orders: list[int]) -> bool:
    """The check the schema used to make, for small orders only."""
    return sorted(orders) == list(range(min(orders), max(orders) + 1))


def _stage_order_errors(exc: ValidationError) -> list[dict]:
    return [
        error
        for error in exc.errors()
        if error["loc"] and error["loc"][-1] == "stage_order"
    ]


# --- the bound ----------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "orders",
    [(0, 10**20), (0, MAX_STAGE_ORDER + 1), (10**20,), (2**63,)],
    ids=["0-and-1e20", "0-and-bound+1", "1e20-alone", "2**63-alone"],
)
def test_a_create_with_a_stage_order_above_the_bound_is_refused_naming_the_field(
    orders,
):
    # Before: (0, 10**20) raised OverflowError, not ValidationError (a 500 over
    # HTTP); (0, 1001) was refused as a gap, not for the order; a single stage
    # at 10**20 or 2**63 was accepted.
    with pytest.raises(ValidationError) as caught:
        RolloutScheduleCreate.model_validate(_schedule(*orders))
    errors = _stage_order_errors(caught.value)
    assert errors, caught.value.errors()
    assert {error["type"] for error in errors} == {"less_than_equal"}
    assert {error["ctx"]["le"] for error in errors} == {MAX_STAGE_ORDER}


@pytest.mark.regression
@pytest.mark.parametrize("order", [MAX_STAGE_ORDER + 1, 10**20])
def test_a_stage_create_above_the_bound_is_refused(order):
    with pytest.raises(ValidationError) as caught:
        RolloutStageCreate.model_validate(_stage(order))
    assert _stage_order_errors(caught.value)


@pytest.mark.regression
@pytest.mark.parametrize("order", [MAX_STAGE_ORDER + 1, 10**20])
def test_a_stage_update_above_the_bound_is_refused(order):
    # Before: accepted, and handed to the service as it was.
    with pytest.raises(ValidationError) as caught:
        RolloutStageUpdate.model_validate({"stage_order": order})
    assert _stage_order_errors(caught.value)


@pytest.mark.regression
def test_a_schedule_update_with_a_stage_above_the_bound_is_refused():
    with pytest.raises(ValidationError) as caught:
        RolloutScheduleUpdate.model_validate({"stages": [{"stage_order": 10**20}]})
    assert _stage_order_errors(caught.value)


@pytest.mark.parametrize("orders", [(0,), (MAX_STAGE_ORDER,), (1, 2, 3)])
def test_orders_up_to_the_bound_are_accepted(orders):
    schedule = RolloutScheduleCreate.model_validate(_schedule(*orders))
    assert [stage.stage_order for stage in schedule.stages] == list(orders)
    assert RolloutStageUpdate(stage_order=MAX_STAGE_ORDER).stage_order == (
        MAX_STAGE_ORDER
    )


def test_a_negative_order_is_still_refused():
    with pytest.raises(ValidationError) as caught:
        RolloutScheduleCreate.model_validate(_schedule(-1, 0))
    assert _stage_order_errors(caught.value)


def test_the_bound_is_well_above_any_real_schedule():
    # Target percentages run from 0 to 100 and never decrease, so a schedule
    # needs at most a few dozen stages; the bound is well above that and fits
    # the 32-bit column the order is stored in.
    assert 100 < MAX_STAGE_ORDER < 2**31 - 1


@pytest.mark.regression
def test_a_large_order_is_refused_without_building_the_orders():
    body = _schedule(0, 10**6)
    tracemalloc.start()
    try:
        with pytest.raises(ValidationError):
            RolloutScheduleCreate.model_validate(body)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < PEAK_BYTES, f"peak traced allocation {peak} bytes"


# --- the gap check on its own -------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("high", [10**6, 10**20])
def test_the_gap_check_builds_no_sequence(high):
    # The stages skip field validation here, so this is the gap check alone,
    # as it would run if the bound were ever raised or removed.
    schedule = _constructed(0, high)
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="sequential without gaps"):
            schedule.validate_stages()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < PEAK_BYTES, f"peak traced allocation {peak} bytes"


def test_the_gap_check_decides_as_before_for_every_short_list():
    # Every list of one to four orders drawn from 0..5, duplicates and any
    # order of the stages included: the new check accepts exactly the lists
    # the old one did.
    checked = 0
    for length in range(1, 5):
        for orders in itertools.product(range(6), repeat=length):
            schedule = _constructed(*orders)
            try:
                schedule.validate_stages()
                accepted = True
            except ValueError:
                accepted = False
            assert accepted == _old_gap_check_accepts(list(orders)), orders
            checked += 1
    assert checked == 6 + 6**2 + 6**3 + 6**4


@pytest.mark.parametrize(
    "orders, accepted",
    [
        ((1, 2, 3), True),
        ((3, 1, 2), True),
        ((0,), True),
        ((MAX_STAGE_ORDER - 1, MAX_STAGE_ORDER), True),
        ((1, 3), False),
        ((1, 1, 2), False),
        ((0, MAX_STAGE_ORDER), False),
    ],
)
def test_the_gap_check_through_validation(orders, accepted):
    if accepted:
        RolloutScheduleCreate.model_validate(_schedule(*orders))
        return
    with pytest.raises(ValidationError, match="sequential without gaps"):
        RolloutScheduleCreate.model_validate(_schedule(*orders))


# --- the response -------------------------------------------------------------


def test_a_response_describes_a_stored_order_above_the_bound():
    # Adding a stage in the middle of a schedule moves every later stage up by
    # one, so a stored order can pass the request bound.
    now = datetime.now(timezone.utc)
    stage = RolloutStageResponse.model_validate(
        {
            **_stage(MAX_STAGE_ORDER + 1),
            "id": uuid.uuid4(),
            "rollout_schedule_id": uuid.uuid4(),
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
    )
    assert stage.stage_order == MAX_STAGE_ORDER + 1
