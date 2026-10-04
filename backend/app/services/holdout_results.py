"""
Results for a global holdout: the users it kept out against everyone else (#445).

``GET /api/v1/holdout/{holdout_id}/results?metric=<event>`` compares, for one
event name, the share of users who sent at least one matching event:

* ``in_holdout``: users the holdout kept out of every experiment;
* ``not_in_holdout``: everyone else first seen while it was active.

Both arms come from ``holdout_population``, which ``assign_user`` writes the
first time it answers a user while a measurable holdout is active.  Every row
is in its arm, users refused by targeting or mutual exclusion included
(intent to treat).  The holdout is the control, so a positive difference
means the running experiments raised the metric.

The counting rules, all in one SQL statement (``_count``):

* **Window.**  A user's window runs from their own ``first_seen_at`` to
  ``window_end``: the holdout's ``deactivated_at``, or the request time while
  it is active.  Population rows written at or after ``window_end`` are left
  out.
* **Converted.**  At least one event matching ``conversion_event_filter``
  whose own time (``events.created_at``) and receive time
  (``events.updated_at``, insert-only on ``Event``) are both in the window.
  Events received after a holdout ends therefore never change its results.
  Tagged and untagged events count alike.
* **Excluded.**  A user with an assignment created before their own
  ``first_seen_at`` is in neither arm (they were enrolled before this
  holdout saw them).  ``excluded_users`` reports how many, per arm.
* **Assigned while held out.**  ``holdout_users_with_assignments`` counts
  analysed held-out users with an assignment inside their window.  It is 0
  unless an image that does not consult the holdout served traffic (a
  rollback); those users stay in their arm and the notice says so.

The comparison types matter, because ``events.created_at`` and
``first_seen_at`` are UTC ISO strings while ``events.updated_at`` and
``assignments.created_at`` are naive UTC timestamps:

* a string column is compared with a string column, or with a bind that goes
  through ``UTCTimestampString`` (``Event.created_at < window_end``);
* a naive timestamp column is compared with
  ``timezone('UTC', CAST(first_seen_at AS timestamptz))`` or with a naive UTC
  bind, never with an aware value, which PostgreSQL would convert with the
  session's time zone.

No raw SQL text is built here (``test_holdout_results_sql_is_typed.py``).

The estimator: a 95% Agresti-Caffo interval for the difference, and a
normal-mixture confidence sequence on the same Agresti-Caffo variance.
``p_value`` and ``is_significant`` are Fisher's exact test from
``binomial_metric_result``, the statistics ``/results`` reports; the interval
is computed separately and can disagree with ``is_significant`` near the
boundary.  Both arms need ``MIN_USERS_PER_GROUP`` analysed users; the
coverage simulation behind that number is pinned by
``test_holdout_results_coverage.py``.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from sqlalchemy import DateTime, and_, cast, func, select
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Session

from backend.app.core.analysis_status import analysis_notice, analysis_status
from backend.app.models.assignment import Assignment
from backend.app.models.event import Event
from backend.app.models.global_holdout import LEGACY_HOLDOUT_SALT, GlobalHoldout
from backend.app.models.holdout_population import HoldoutPopulation
from backend.app.services.event_matching import conversion_event_filter
from backend.app.services.sequential_testing_service import SequentialTestingService
from backend.app.services.sufficient_stats_analysis import (
    BinomialVariant,
    binomial_metric_result,
    two_sided_z,
)

#: Analysed users each arm needs before a difference is reported.  At 100
#: against 1,000 and a 1% rate the Agresti-Caffo interval and the confidence
#: sequence keep their coverage (``test_holdout_results_coverage.py``).
MIN_USERS_PER_GROUP = 100

#: Significance level of ``is_significant``, and 1 - the interval's level.
ALPHA = 0.05

#: Mixing variance of the confidence sequence, as ``/sequential`` uses.
TAU_SQUARED = 0.001

#: Upper bound on the counting statement, in milliseconds, set with SET
#: LOCAL.  A performance guard only: on one million population rows, four
#: million events and 1.46 million assignments the statement ran in about
#: 4 s on a laptop Postgres 16 (EXPLAIN ANALYZE in #445 PR2), so 30 s leaves
#: room for a slower database while keeping one request from holding a
#: pooled connection for minutes.  When it is exceeded the request fails
#: with a 500.
STATEMENT_TIMEOUT_MS = 30_000

IN_HOLDOUT = "in_holdout"
NOT_IN_HOLDOUT = "not_in_holdout"
GROUP_LABELS = {IN_HOLDOUT: "In holdout", NOT_IN_HOLDOUT: "Not in holdout"}

ACTIVATED_BEFORE_MEASUREMENT = "activated_before_measurement"
NOT_ACTIVATED = "not_activated"
TOO_FEW_USERS = "too_few_users"
NO_EVENTS = "no_events"

ACTIVATED_BEFORE_MEASUREMENT_MESSAGE = (
    "Who this holdout kept out was not recorded: it was active before the "
    "release that records holdout membership. Create a new holdout to measure."
)
NOT_ACTIVATED_MESSAGE = (
    "This holdout has not been activated since its users began to be "
    "recorded. Activate it to start measuring."
)
TOO_FEW_USERS_MESSAGE = (
    "Not enough users yet: {in_n} in the holdout and {out_n} not in it. "
    "Results appear when each group has at least {min_n}. Only users first "
    "seen since {activated:%Y-%m-%d} count."
)
NO_EVENTS_MESSAGE = (
    "No '{metric}' events were recorded for either group in this window. "
    "Check the event name."
)


def assigned_while_held_out_sentence(count: int) -> str:
    """The sentence appended to the notice when held-out users were assigned."""
    users = (
        "1 user in the holdout was"
        if count == 1
        else f"{count} users in the holdout were"
    )
    return (
        f"{users} assigned to an experiment while it was active, which happens "
        "after a rollback to a release that does not record holdouts; the "
        "difference is then smaller than the real one. Deactivate this holdout "
        "and create a new one."
    )


# ---------------------------------------------------------------------------
# Estimator
# ---------------------------------------------------------------------------


def agresti_caffo(n_h: int, x_h: int, n_r: int, x_r: int) -> Tuple[float, float]:
    """Agresti-Caffo centre and variance for ``rate_r - rate_h``.

    One success and one failure are added to each arm:
    ``p_h = (x_h + 1) / (n_h + 2)`` and the same for the rest; the variance is
    ``p_h (1 - p_h) / (n_h + 2) + p_r (1 - p_r) / (n_r + 2)``, which is
    positive for any counts.
    """
    p_h = (x_h + 1) / (n_h + 2)
    p_r = (x_r + 1) / (n_r + 2)
    variance = p_h * (1 - p_h) / (n_h + 2) + p_r * (1 - p_r) / (n_r + 2)
    return p_r - p_h, variance


def _clip(value: float) -> float:
    return max(-1.0, min(1.0, value))


def difference_interval(n_h: int, x_h: int, n_r: int, x_r: int) -> Tuple[float, float]:
    """The 95% Agresti-Caffo interval for ``rate_r - rate_h``, clipped to [-1, 1]."""
    centre, variance = agresti_caffo(n_h, x_h, n_r, x_r)
    half = two_sided_z(1.0 - ALPHA) * math.sqrt(variance)
    return _clip(centre - half), _clip(centre + half)


def always_valid_interval(
    n_h: int, x_h: int, n_r: int, x_r: int
) -> Tuple[float, float]:
    """The confidence sequence for ``rate_r - rate_h``, clipped to [-1, 1].

    Centred on the observed difference, with the normal-mixture half-width of
    ``SequentialTestingService`` at ``TAU_SQUARED`` and ``ALPHA`` on the
    Agresti-Caffo variance.  The plug-in variance ``/sequential`` uses is not:
    with a small, low-rate arm it is too small and the sequence undercovers.
    """
    _, variance = agresti_caffo(n_h, x_h, n_r, x_r)
    d = x_r / n_r - x_h / n_h
    half = SequentialTestingService.confidence_sequence_half_width(
        variance, TAU_SQUARED, ALPHA
    )
    return _clip(d - half), _clip(d + half)


class _Metric(NamedTuple):
    id: str
    name: str
    metric_type: str = "conversion"
    is_primary: bool = True


_HOLDOUT_ARM = BinomialVariant(id=IN_HOLDOUT, name="In holdout", is_control=True)
_REST_ARM = BinomialVariant(id=NOT_IN_HOLDOUT, name="Not in holdout", is_control=False)


def compare(n_h: int, x_h: int, n_r: int, x_r: int) -> Dict[str, Any]:
    """The ``difference`` of a results response, for arms with at least one user.

    ``p_value``, ``is_significant`` and ``relative_pct`` come from
    ``binomial_metric_result`` (Fisher's exact test, the holdout as the
    control, no correction); the intervals from the functions above.
    """
    result = binomial_metric_result(
        [(_HOLDOUT_ARM, n_h, x_h), (_REST_ARM, n_r, x_r)],
        ALPHA,
        "none",
        metric=_Metric(id="holdout", name="holdout"),
    )
    rest = next(v for v in result["variants"] if not v["is_control"])
    ci_lower, ci_upper = difference_interval(n_h, x_h, n_r, x_r)
    av_lower, av_upper = always_valid_interval(n_h, x_h, n_r, x_r)
    return {
        "absolute": x_r / n_r - x_h / n_h,
        "relative_pct": rest["relative_improvement_pct"],
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "p_value": rest["p_value"],
        "is_significant": bool(rest["is_significant"]),
        "always_valid_ci_lower": av_lower,
        "always_valid_ci_upper": av_upper,
    }


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


@dataclass
class ArmCounts:
    """One arm's counts: analysed users, converters, and excluded users."""

    users: int = 0
    conversions: int = 0
    excluded: int = 0


@dataclass
class Counts:
    holdout: ArmCounts
    rest: ArmCounts
    holdout_users_with_assignments: int


def count_statement(holdout_id: Any, metric: str, window_end: datetime):
    """The counting statement for one holdout, metric and naive-UTC window end.

    Set-based: the population is a CTE, and each of excluded, converted and
    assigned-while-held-out is a DISTINCT join against it, so each table is
    probed once per population row through its ``user_id`` index rather
    than once per row and predicate.
    """
    window_end_naive = window_end
    window_end_aware = window_end.replace(tzinfo=timezone.utc)
    population = HoldoutPopulation

    first_seen_ts = func.timezone(
        "UTC",
        cast(population.first_seen_at, TIMESTAMP(timezone=True)),
        type_=DateTime(),
    )
    pop = (
        select(
            population.user_id,
            population.in_holdout,
            population.first_seen_at,
            first_seen_ts.label("first_seen_ts"),
        )
        .where(
            population.holdout_id == holdout_id,
            # Bound through UTCTimestampString: an ISO string.
            population.first_seen_at < window_end_aware,
        )
        .cte("pop")
    )

    excluded = (
        select(pop.c.user_id)
        .join(
            Assignment,
            and_(
                Assignment.user_id == pop.c.user_id,
                Assignment.created_at < pop.c.first_seen_ts,
            ),
        )
        .distinct()
        .cte("excluded")
    )

    converted = (
        select(pop.c.user_id)
        .join(
            Event,
            and_(
                Event.user_id == pop.c.user_id,
                conversion_event_filter(metric),
                Event.created_at >= pop.c.first_seen_at,
                # Bound through UTCTimestampString: an ISO string.
                Event.created_at < window_end_aware,
                Event.updated_at >= pop.c.first_seen_ts,
                # A naive bind against a naive column.
                Event.updated_at < window_end_naive,
            ),
        )
        .distinct()
        .cte("converted")
    )

    assigned_in_window = (
        select(pop.c.user_id)
        .join(
            Assignment,
            and_(
                Assignment.user_id == pop.c.user_id,
                Assignment.created_at >= pop.c.first_seen_ts,
                Assignment.created_at < window_end_naive,
            ),
        )
        .where(pop.c.in_holdout.is_(True))
        .distinct()
        .cte("assigned_in_window")
    )

    is_excluded = excluded.c.user_id.isnot(None)
    return (
        select(
            pop.c.in_holdout,
            is_excluded.label("excluded"),
            func.count().label("users"),
            func.count(converted.c.user_id).label("conversions"),
            func.count(assigned_in_window.c.user_id).label("assigned"),
        )
        .select_from(
            pop.outerjoin(excluded, excluded.c.user_id == pop.c.user_id)
            .outerjoin(converted, converted.c.user_id == pop.c.user_id)
            .outerjoin(
                assigned_in_window, assigned_in_window.c.user_id == pop.c.user_id
            )
        )
        .group_by(pop.c.in_holdout, is_excluded)
    )


def _count(db: Session, holdout_id: Any, metric: str, window_end: datetime) -> Counts:
    # set_config(..., true) is SET LOCAL: it ends with this transaction.
    db.execute(
        select(func.set_config("statement_timeout", str(STATEMENT_TIMEOUT_MS), True))
    )
    holdout, rest = ArmCounts(), ArmCounts()
    assigned = 0
    for in_holdout, excluded, users, conversions, assigned_n in db.execute(
        count_statement(holdout_id, metric, window_end)
    ):
        arm = holdout if in_holdout else rest
        if excluded:
            arm.excluded += users
            continue
        arm.users += users
        arm.conversions += conversions
        if in_holdout:
            assigned += assigned_n
    return Counts(holdout=holdout, rest=rest, holdout_users_with_assignments=assigned)


# ---------------------------------------------------------------------------
# The response
# ---------------------------------------------------------------------------


def unmeasurable_reason(holdout: GlobalHoldout) -> Optional[str]:
    """``activated_before_measurement``, ``not_activated`` or None (measurable).

    A legacy-salt row is never measurable, whatever ``activated_at`` says.  A
    row deactivated without ever being stamped is the one the upgrade ended:
    it was active, but nothing was recorded.
    """
    if holdout.hash_salt == LEGACY_HOLDOUT_SALT:
        return ACTIVATED_BEFORE_MEASUREMENT
    if holdout.activated_at is None and holdout.deactivated_at is not None:
        return ACTIVATED_BEFORE_MEASUREMENT
    if holdout.activated_at is None:
        return NOT_ACTIVATED
    return None


def _group(name: str, arm: ArmCounts) -> Dict[str, Any]:
    return {
        "group": name,
        "label": GROUP_LABELS[name],
        "users": arm.users,
        "conversions": arm.conversions,
        "conversion_rate": (arm.conversions / arm.users) if arm.users else None,
        "excluded_users": arm.excluded,
    }


def holdout_results(
    db: Session,
    holdout: GlobalHoldout,
    metric: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """The results response for ``holdout`` and ``metric``, as a dict.

    ``now`` is the request time as naive UTC, read once; tests pass it.
    """
    response: Dict[str, Any] = {
        "holdout_id": holdout.id,
        "holdout_name": holdout.name,
        "holdout_percentage": holdout.holdout_percentage,
        "activated_at": holdout.activated_at,
        "deactivated_at": holdout.deactivated_at,
        "window_end": None,
        "metric": metric,
        "unavailable_reason": None,
        "message": None,
        "excluded_users": None,
        "holdout_users_with_assignments": None,
        "groups": [],
        "difference": None,
        "analysis_status": analysis_status("holdout"),
        "analysis_notice": analysis_notice("holdout"),
    }

    reason = unmeasurable_reason(holdout)
    if reason is not None:
        response["unavailable_reason"] = reason
        response["message"] = (
            ACTIVATED_BEFORE_MEASUREMENT_MESSAGE
            if reason == ACTIVATED_BEFORE_MEASUREMENT
            else NOT_ACTIVATED_MESSAGE
        )
        return response

    if holdout.deactivated_at is not None:
        window_end = holdout.deactivated_at
    else:
        window_end = now or datetime.now(timezone.utc).replace(tzinfo=None)
    counts = _count(db, holdout.id, metric, window_end)

    groups: List[Dict[str, Any]] = [
        _group(IN_HOLDOUT, counts.holdout),
        _group(NOT_IN_HOLDOUT, counts.rest),
    ]
    response.update(
        window_end=window_end,
        excluded_users=counts.holdout.excluded + counts.rest.excluded,
        holdout_users_with_assignments=counts.holdout_users_with_assignments,
        groups=groups,
    )
    if counts.holdout_users_with_assignments > 0 and response["analysis_notice"]:
        response["analysis_notice"] = " ".join(
            [
                response["analysis_notice"],
                assigned_while_held_out_sentence(counts.holdout_users_with_assignments),
            ]
        )

    n_h, x_h = counts.holdout.users, counts.holdout.conversions
    n_r, x_r = counts.rest.users, counts.rest.conversions
    if n_h < MIN_USERS_PER_GROUP or n_r < MIN_USERS_PER_GROUP:
        response["unavailable_reason"] = TOO_FEW_USERS
        response["message"] = TOO_FEW_USERS_MESSAGE.format(
            in_n=n_h,
            out_n=n_r,
            min_n=MIN_USERS_PER_GROUP,
            activated=holdout.activated_at,
        )
        return response
    if x_h + x_r == 0:
        response["unavailable_reason"] = NO_EVENTS
        response["message"] = NO_EVENTS_MESSAGE.format(metric=metric)
        return response

    response["difference"] = compare(n_h, x_h, n_r, x_r)
    return response
