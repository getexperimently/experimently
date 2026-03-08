"""
Behavioral profile: Churn Risk User.

A churn risk user was previously active but engagement is declining.
They represent users who may be saved by the right intervention (feature
flag rollout, personalized experiment) but will leave if not acted upon.

Characteristics:
  - Declining sessions per week (2 → 0.5 over 4 weeks)
  - Falling conversion rate (10% → 2% over 4 weeks)
  - Increasingly short sessions
  - High sensitivity to negative UX changes
  - Significant re-engagement potential if targeted correctly

Use this profile to test:
  - Holdout group effectiveness (do churned users return with treatment?)
  - Novelty effect decay (initial lift fades for at-risk users)
  - Targeting rule accuracy (segment by declining engagement)
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class ChurnRiskBehavior:
    """Behavioral parameters for a user in the churn risk segment."""

    initial_sessions_per_week: float = 2.0
    final_sessions_per_week: float = 0.5
    initial_conversion_rate: float = 0.10
    final_conversion_rate: float = 0.02
    decay_weeks: int = 4
    re_engagement_boost: float = 0.15    # treatment uplift potential
    sensitivity_to_negative_ux: float = 2.0  # 2× more likely to leave on bad UX

    def _decay_factor(self, week: int) -> float:
        """Linear decay from 1.0 at week 0 to 0.0 at decay_weeks."""
        return max(0.0, 1.0 - week / self.decay_weeks)

    def sessions_at_week(self, week: int) -> float:
        factor = self._decay_factor(week)
        return (
            self.initial_sessions_per_week * factor
            + self.final_sessions_per_week * (1 - factor)
        )

    def conversion_rate_at_week(self, week: int) -> float:
        factor = self._decay_factor(week)
        return (
            self.initial_conversion_rate * factor
            + self.final_conversion_rate * (1 - factor)
        )

    def simulate_session(
        self,
        week: int,
        variant: str,
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """
        Simulate a session for a churn risk user at the given week into the experiment.

        The treatment provides a re-engagement boost for churn risk users.
        """
        r = rng or random.Random()
        cvr = self.conversion_rate_at_week(week)

        if variant == "treatment":
            # Treatment boosts re-engagement
            cvr = min(cvr + self.re_engagement_boost, 1.0)

        # Session duration decays with engagement
        base_duration = max(0.5, 5.0 - week * 0.8)
        duration = r.lognormvariate(base_duration * 0.5, 0.3)

        converted = r.random() < cvr
        events: list[dict[str, Any]] = [{"event": "page_view", "value": 1.0}]

        if converted:
            events.append({"event": "purchase", "value": round(r.uniform(5, 30), 2)})
        elif r.random() < 0.4:  # churned users often look but don't engage
            events.append({"event": "scroll", "value": r.uniform(10, 40)})

        return {
            "variant": variant,
            "profile": "churn_risk",
            "week": week,
            "events": events,
            "converted": converted,
            "session_minutes": min(duration, 15),
            "churn_probability": round(1.0 - self._decay_factor(week), 2),
        }


def make_churn_risk_population(
    n: int = 500,
    weeks: int = 4,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """
    Generate a population of churn risk users across the experiment duration.

    Each user gets one session per simulated week, with decaying engagement
    over time.  Half are in control, half in treatment (which provides a
    re-engagement boost).
    """
    rng = random.Random(seed)
    profile = ChurnRiskBehavior()
    users = []

    for i in range(n):
        variant = "control" if i < n // 2 else "treatment"
        user_id = f"churn-{i:06d}"
        user_sessions = []
        for week in range(weeks):
            session = profile.simulate_session(week, variant, rng)
            session["user_id"] = user_id
            session["session_week"] = week
            user_sessions.append(session)
        users.append({
            "user_id": user_id,
            "variant": variant,
            "profile": "churn_risk",
            "sessions": user_sessions,
            "total_conversions": sum(1 for s in user_sessions if s["converted"]),
        })

    return users


def compute_churn_risk_lift(population: list[dict[str, Any]]) -> dict[str, float]:
    """
    Compute conversion lift for treatment vs control in a churn risk population.

    Returns:
        control_cvr: Overall conversion rate for control
        treatment_cvr: Overall conversion rate for treatment
        relative_lift: (treatment_cvr - control_cvr) / control_cvr
    """
    control_users = [u for u in population if u["variant"] == "control"]
    treatment_users = [u for u in population if u["variant"] == "treatment"]

    control_converters = sum(1 for u in control_users if u["total_conversions"] > 0)
    treatment_converters = sum(1 for u in treatment_users if u["total_conversions"] > 0)

    c_cvr = control_converters / max(len(control_users), 1)
    t_cvr = treatment_converters / max(len(treatment_users), 1)

    lift = (t_cvr - c_cvr) / c_cvr if c_cvr > 0 else 0.0

    return {
        "control_cvr": round(c_cvr, 4),
        "treatment_cvr": round(t_cvr, 4),
        "relative_lift": round(lift, 4),
        "control_users": len(control_users),
        "treatment_users": len(treatment_users),
    }


if __name__ == "__main__":
    population = make_churn_risk_population(n=200, weeks=4, seed=42)
    metrics = compute_churn_risk_lift(population)
    print("Churn Risk Population Metrics:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
