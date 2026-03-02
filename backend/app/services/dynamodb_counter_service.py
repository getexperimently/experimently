"""
DynamoDB Atomic Counter Service (P2-B).

Provides real-time atomic counters for experiment assignment, event, and
conversion tracking.  Each counter lives in a single DynamoDB item keyed by:

    pk = "EXPERIMENT#{experiment_id}"
    sk = "VARIANT#{variant_id}"

Attributes per item:
    assignments   (Number) — atomic counter via ADD expression
    events        (Number) — atomic counter via ADD expression
    conversions   (Number) — atomic counter via ADD expression
    last_updated  (String) — ISO-8601 timestamp of last write

All increment operations use DynamoDB's ADD update expression, which is
atomic and safe under concurrent writes.
"""

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from backend.app.schemas.realtime_counters import (
    BulkIncrementRequest,
    BulkIncrementResponse,
    CounterType,
    ExperimentCounters,
    IncrementRequest,
    IncrementResponse,
    VariantCounters,
)

logger = logging.getLogger(__name__)

# Map CounterType enum to DynamoDB attribute name
_COUNTER_ATTR: dict[CounterType, str] = {
    CounterType.ASSIGNMENT: "assignments",
    CounterType.EVENT: "events",
    CounterType.CONVERSION: "conversions",
}

_ALL_COUNTER_ATTRS = list(_COUNTER_ATTR.values())


class DynamoDBCounterService:
    """
    Service for managing real-time experiment counters in DynamoDB.

    Args:
        table_name: DynamoDB table name (default: value of DYNAMODB_COUNTERS_TABLE
                    env var, or "experiment-counters").
        dynamodb_resource: Optional pre-built boto3 DynamoDB resource.
                           If omitted, a new resource is created using the
                           default boto3 credential chain.
    """

    def __init__(
        self,
        table_name: Optional[str] = None,
        dynamodb_resource=None,
    ) -> None:
        if table_name is None:
            table_name = os.environ.get(
                "DYNAMODB_COUNTERS_TABLE", "experiment-counters"
            )
        self.table_name = table_name

        if dynamodb_resource is None:
            dynamodb_resource = boto3.resource("dynamodb")

        self._dynamodb = dynamodb_resource
        self._table = dynamodb_resource.Table(table_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def increment_counter(
        self,
        experiment_id: str,
        variant_id: str,
        counter_type: CounterType,
        amount: int = 1,
    ) -> int:
        """
        Atomically increment a counter for an experiment variant.

        Uses DynamoDB's ADD update expression which is both atomic and
        safe under concurrent writers (no read-modify-write race).

        Args:
            experiment_id: Experiment identifier.
            variant_id:    Variant identifier.
            counter_type:  Which counter to increment (ASSIGNMENT/EVENT/CONVERSION).
            amount:        How much to add (must be >= 1).

        Returns:
            The new counter value after the increment.
        """
        attr_name = _COUNTER_ATTR[counter_type]
        now = datetime.now(tz=timezone.utc).isoformat()

        response = self._table.update_item(
            Key={
                "pk": f"EXPERIMENT#{experiment_id}",
                "sk": f"VARIANT#{variant_id}",
            },
            UpdateExpression="ADD #attr :val SET last_updated = :ts",
            ExpressionAttributeNames={"#attr": attr_name},
            ExpressionAttributeValues={
                ":val": Decimal(amount),
                ":ts": now,
            },
            ReturnValues="ALL_NEW",
        )

        updated = response.get("Attributes", {})
        return int(updated.get(attr_name, 0))

    def get_experiment_counters(self, experiment_id: str) -> ExperimentCounters:
        """
        Retrieve aggregated counters for all variants of an experiment.

        Queries the DynamoDB table using the partition key prefix
        ``EXPERIMENT#{experiment_id}`` to retrieve every variant row.

        Args:
            experiment_id: Experiment identifier.

        Returns:
            ExperimentCounters with per-variant breakdown and totals.
        """
        pk_value = f"EXPERIMENT#{experiment_id}"
        sk_prefix = "VARIANT#"

        response = self._table.query(
            KeyConditionExpression=(
                "pk = :pk AND begins_with(sk, :sk_prefix)"
            ),
            ExpressionAttributeValues={
                ":pk": pk_value,
                ":sk_prefix": sk_prefix,
            },
        )

        items = response.get("Items", [])

        variant_counters = []
        total_assignments = 0
        total_events = 0
        total_conversions = 0
        last_updated: Optional[str] = None

        for item in items:
            # Extract variant_id from the sort key "VARIANT#{id}"
            sk: str = item.get("sk", "")
            variant_id = sk[len("VARIANT#"):] if sk.startswith("VARIANT#") else sk

            assignments = int(item.get("assignments", 0))
            events = int(item.get("events", 0))
            conversions = int(item.get("conversions", 0))
            item_ts = item.get("last_updated")

            conversion_rate = (
                conversions / assignments if assignments > 0 else 0.0
            )

            variant_counters.append(
                VariantCounters(
                    variant_id=variant_id,
                    variant_name=variant_id,  # name not stored; use id as fallback
                    is_control=False,         # cannot determine from counter data alone
                    assignments=assignments,
                    events=events,
                    conversions=conversions,
                    conversion_rate=conversion_rate,
                )
            )

            total_assignments += assignments
            total_events += events
            total_conversions += conversions

            # Keep the most-recent last_updated across variants
            if item_ts and (last_updated is None or item_ts > last_updated):
                last_updated = item_ts

        return ExperimentCounters(
            experiment_id=experiment_id,
            total_assignments=total_assignments,
            total_events=total_events,
            total_conversions=total_conversions,
            variants=variant_counters,
            last_updated=last_updated,
        )

    def bulk_increment(
        self, increments: list[IncrementRequest]
    ) -> BulkIncrementResponse:
        """
        Perform multiple counter increments, each atomically.

        Each item is processed individually (DynamoDB's UpdateItem is atomic
        per item; TransactWriteItems caps at 25 items but cannot use ADD with
        transactions). Failures are collected and reported without aborting the
        rest.

        Args:
            increments: List of IncrementRequest objects.

        Returns:
            BulkIncrementResponse with processed/failed counts and per-item results.
        """
        results: list[IncrementResponse] = []
        processed = 0
        failed = 0

        for req in increments:
            try:
                new_value = self.increment_counter(
                    experiment_id=req.experiment_id,
                    variant_id=req.variant_id,
                    counter_type=req.counter_type,
                    amount=req.amount,
                )
                results.append(
                    IncrementResponse(
                        experiment_id=req.experiment_id,
                        variant_id=req.variant_id,
                        counter_type=req.counter_type,
                        new_value=new_value,
                    )
                )
                processed += 1
            except Exception as exc:
                logger.error(
                    "bulk_increment failed for exp=%s variant=%s type=%s: %s",
                    req.experiment_id,
                    req.variant_id,
                    req.counter_type,
                    exc,
                )
                failed += 1

        return BulkIncrementResponse(
            processed=processed,
            failed=failed,
            results=results,
        )

    def reset_counters(
        self,
        experiment_id: str,
        variant_id: Optional[str] = None,
        counter_type: Optional[CounterType] = None,
        reason: str = "",
    ) -> None:
        """
        Reset one or more counters to zero.

        Args:
            experiment_id: Experiment whose counters to reset.
            variant_id:    If provided, reset only this variant.
                           If None, reset all variants for the experiment.
            counter_type:  If provided, reset only this counter type.
                           If None, reset all counter types.
            reason:        Human-readable reason for the reset (for audit
                           purposes; currently stored in logs only).
        """
        logger.info(
            "Resetting counters: experiment=%s variant=%s counter_type=%s reason=%s",
            experiment_id,
            variant_id,
            counter_type,
            reason,
        )

        # Collect the items to reset
        if variant_id is not None:
            # Single variant
            items_to_reset = [
                {
                    "pk": f"EXPERIMENT#{experiment_id}",
                    "sk": f"VARIANT#{variant_id}",
                }
            ]
        else:
            # All variants for the experiment
            pk_value = f"EXPERIMENT#{experiment_id}"
            response = self._table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :sk_prefix)",
                ExpressionAttributeValues={
                    ":pk": pk_value,
                    ":sk_prefix": "VARIANT#",
                },
                ProjectionExpression="pk, sk",
            )
            items_to_reset = [
                {"pk": item["pk"], "sk": item["sk"]}
                for item in response.get("Items", [])
            ]

        # Determine which attributes to reset
        if counter_type is not None:
            attrs_to_reset = [_COUNTER_ATTR[counter_type]]
        else:
            attrs_to_reset = _ALL_COUNTER_ATTRS

        now = datetime.now(tz=timezone.utc).isoformat()

        for key in items_to_reset:
            # Build a SET expression that zeroes out each attribute
            set_parts = [f"#attr_{i} = :zero" for i, _ in enumerate(attrs_to_reset)]
            set_parts.append("last_updated = :ts")
            update_expr = "SET " + ", ".join(set_parts)

            expr_names = {
                f"#attr_{i}": attr
                for i, attr in enumerate(attrs_to_reset)
            }
            expr_values = {
                f":zero": Decimal(0),
                ":ts": now,
            }

            try:
                self._table.update_item(
                    Key=key,
                    UpdateExpression=update_expr,
                    ExpressionAttributeNames=expr_names,
                    ExpressionAttributeValues=expr_values,
                )
            except ClientError as exc:
                logger.error("reset_counters failed for key=%s: %s", key, exc)
                raise
