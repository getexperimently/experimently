"""
Counter Integration for Event Processor Lambda (P2-B).

Provides helpers that the event processor Lambda can call when it processes
assignment/event Kinesis records to auto-increment the DynamoDB atomic counters
that power the real-time experiment dashboard.

Usage inside the event processor Lambda::

    from counter_integration import process_assignment_event, process_conversion_event
    from backend.app.services.dynamodb_counter_service import DynamoDBCounterService

    counter_service = DynamoDBCounterService()

    # Inside the per-record processing loop:
    if event_data["event_type"] == "assignment":
        process_assignment_event(event_data, counter_service)
    elif event_data["event_type"] in ("conversion", "purchase", "goal"):
        process_conversion_event(event_data, counter_service)
    elif event_data["event_type"] == "event":
        process_event(event_data, counter_service)

Expected event_data keys:
    experiment_id  (str, required)
    variant_id     (str, required)
    event_type     (str, required) — "assignment" | "conversion" | "event"
    user_id        (str, optional) — for logging
"""

import logging
from typing import Optional

from backend.app.schemas.realtime_counters import CounterType
from backend.app.services.dynamodb_counter_service import DynamoDBCounterService

logger = logging.getLogger(__name__)


def process_assignment_event(
    event_data: dict,
    counter_service: DynamoDBCounterService,
) -> Optional[int]:
    """
    Increment the assignment counter when a Kinesis record has
    ``event_type='assignment'``.

    Args:
        event_data:      Parsed Kinesis record payload.  Must contain
                         ``experiment_id`` and ``variant_id``.
        counter_service: DynamoDBCounterService instance to use.

    Returns:
        The new assignment counter value, or None if the event was skipped
        due to missing required fields.
    """
    experiment_id = event_data.get("experiment_id")
    variant_id = event_data.get("variant_id")

    if not experiment_id or not variant_id:
        logger.warning(
            "process_assignment_event: skipping event — missing experiment_id or variant_id. "
            "event_data keys: %s",
            list(event_data.keys()),
        )
        return None

    try:
        new_value = counter_service.increment_counter(
            experiment_id=experiment_id,
            variant_id=variant_id,
            counter_type=CounterType.ASSIGNMENT,
            amount=1,
        )
        logger.debug(
            "Incremented assignment counter: experiment=%s variant=%s new_value=%s",
            experiment_id,
            variant_id,
            new_value,
        )
        return new_value
    except Exception as exc:
        logger.error(
            "Failed to increment assignment counter: experiment=%s variant=%s error=%s",
            experiment_id,
            variant_id,
            exc,
        )
        # Do not re-raise — counter failure should not block event processing
        return None


def process_conversion_event(
    event_data: dict,
    counter_service: DynamoDBCounterService,
) -> Optional[int]:
    """
    Increment both the event and conversion counters when a Kinesis record
    represents a goal/conversion.

    Increments:
    - ``CounterType.EVENT``      — so the event is counted in total events
    - ``CounterType.CONVERSION`` — so it is also counted as a conversion

    Args:
        event_data:      Parsed Kinesis record payload.  Must contain
                         ``experiment_id`` and ``variant_id``.
        counter_service: DynamoDBCounterService instance to use.

    Returns:
        The new conversion counter value, or None if the event was skipped.
    """
    experiment_id = event_data.get("experiment_id")
    variant_id = event_data.get("variant_id")

    if not experiment_id or not variant_id:
        logger.warning(
            "process_conversion_event: skipping event — missing experiment_id or variant_id. "
            "event_data keys: %s",
            list(event_data.keys()),
        )
        return None

    try:
        # Count the event in the general event counter first
        counter_service.increment_counter(
            experiment_id=experiment_id,
            variant_id=variant_id,
            counter_type=CounterType.EVENT,
            amount=1,
        )

        # Then count it as a conversion
        conversion_value = counter_service.increment_counter(
            experiment_id=experiment_id,
            variant_id=variant_id,
            counter_type=CounterType.CONVERSION,
            amount=1,
        )

        logger.debug(
            "Incremented event+conversion counters: experiment=%s variant=%s "
            "new_conversion_value=%s",
            experiment_id,
            variant_id,
            conversion_value,
        )
        return conversion_value
    except Exception as exc:
        logger.error(
            "Failed to increment conversion counters: experiment=%s variant=%s error=%s",
            experiment_id,
            variant_id,
            exc,
        )
        return None


def process_event(
    event_data: dict,
    counter_service: DynamoDBCounterService,
) -> Optional[int]:
    """
    Increment the general event counter for non-conversion tracking events.

    Args:
        event_data:      Parsed Kinesis record payload.  Must contain
                         ``experiment_id`` and ``variant_id``.
        counter_service: DynamoDBCounterService instance to use.

    Returns:
        The new event counter value, or None if skipped.
    """
    experiment_id = event_data.get("experiment_id")
    variant_id = event_data.get("variant_id")

    if not experiment_id or not variant_id:
        logger.warning(
            "process_event: skipping event — missing experiment_id or variant_id. "
            "event_data keys: %s",
            list(event_data.keys()),
        )
        return None

    try:
        new_value = counter_service.increment_counter(
            experiment_id=experiment_id,
            variant_id=variant_id,
            counter_type=CounterType.EVENT,
            amount=1,
        )
        logger.debug(
            "Incremented event counter: experiment=%s variant=%s new_value=%s",
            experiment_id,
            variant_id,
            new_value,
        )
        return new_value
    except Exception as exc:
        logger.error(
            "Failed to increment event counter: experiment=%s variant=%s error=%s",
            experiment_id,
            variant_id,
            exc,
        )
        return None
