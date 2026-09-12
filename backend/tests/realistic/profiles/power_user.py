"""
Behavioral profile: Power User.

A power user engages deeply with the product, converts at higher rates,
and actively explores advanced features.  They represent the top 5–15% of
a product's user base but often drive a disproportionate share of revenue.

Characteristics:
  - 5–7 sessions per week
  - High conversion rate (15–25%)
  - Long session duration (10–30 minutes)
  - Low bounce rate — they explore the product
  - Feature-hungry: tries new functionality immediately
  - Tolerant of minor UX friction (up to 5s latency)
  - Very likely to return (85% 7-day retention)
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass
class PowerUserBehavior:
    """Encapsulates the behavioral parameters for a power user profile."""

    sessions_per_week: float = 6.0
    conversion_rate: float = 0.20  # 20% baseline
    session_duration_minutes: float = 18.0
    bounce_rate: float = 0.10  # rarely bounces
    max_tolerated_latency_ms: float = 5000
    feature_discovery_rate: float = 0.75  # discovers most new features
    return_probability: float = 0.85  # highly sticky

    def simulate_session(self, rng: random.Random | None = None) -> dict[str, Any]:
        """
        Simulate a single session for this user profile.

        Power users trigger far more events per session than casual users:
          - Multiple page views
          - Deep scroll engagement
          - Multiple clicks and interactions
          - High probability of purchase
        """
        r = rng or random.Random()
        events: list[dict[str, Any]] = []

        # Multiple page views per session
        page_views = r.randint(3, 12)
        for _ in range(page_views):
            events.append({"event": "page_view", "value": 1.0})

        # Very rarely bounces
        if r.random() < self.bounce_rate:
            return {"events": events, "converted": False, "session_minutes": 0.5}

        # Deep scroll engagement
        scroll = r.uniform(60, 100)
        events.append({"event": "scroll", "value": scroll})

        # Clicks and interactions
        clicks = r.randint(5, 20)
        for _ in range(clicks):
            events.append({"event": "click", "value": 1.0})

        # Feature exploration
        if r.random() < self.feature_discovery_rate:
            events.append({"event": "feature_explore", "value": 1.0})

        duration = r.lognormvariate(
            mean=self.session_duration_minutes * 0.5,
            sigma=0.3,
        )

        # Conversion — power users buy more frequently AND at higher value
        converted = r.random() < self.conversion_rate
        if converted:
            # Power users have higher average order value
            value = r.lognormvariate(mean=4.0, sigma=0.5)  # ~$55 average
            events.append({"event": "purchase", "value": round(value, 2)})

        return {
            "events": events,
            "converted": converted,
            "session_minutes": min(duration, 60),
        }

    def simulate_experiment_exposure(
        self, variant: str, rng: random.Random | None = None
    ) -> dict[str, Any]:
        """
        Simulate a power user's response to an experiment variant.

        Power users are early adopters — they respond more positively to
        treatments that add capability, and less negatively to added
        complexity vs. casual users.
        """
        r = rng or random.Random()
        adjusted_cvr = self.conversion_rate
        if variant == "treatment":
            # Power users embrace new features — slight positive bias
            adjusted_cvr = min(adjusted_cvr * 1.05, 1.0)
        session = self.simulate_session(r)
        # Override converted based on adjusted CVR
        session["converted"] = r.random() < adjusted_cvr
        if session["converted"] and not any(
            e["event"] == "purchase" for e in session["events"]
        ):
            session["events"].append(
                {
                    "event": "purchase",
                    "value": round(r.lognormvariate(4.0, 0.5), 2),
                }
            )
        return {
            "variant": variant,
            "profile": "power",
            **session,
        }


def make_power_user_population(
    n: int = 200,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """
    Generate a population of simulated power users.

    Power users are a minority — typically 5–15% of total users.
    Returns a list of session results for seeding or validation.
    """
    rng = random.Random(seed)
    profile = PowerUserBehavior()
    users = []
    for i in range(n):
        variant = "control" if i < n // 2 else "treatment"
        session = profile.simulate_experiment_exposure(variant, rng)
        session["user_id"] = f"power-{i:06d}"
        users.append(session)
    return users


if __name__ == "__main__":
    population = make_power_user_population(n=100, seed=42)
    converters = [u for u in population if u["converted"]]
    total_revenue = sum(
        e["value"] for u in converters for e in u["events"] if e["event"] == "purchase"
    )
    print(f"Power user population: {len(population)} users")
    print(
        f"Converters: {len(converters)} ({100 * len(converters) / len(population):.1f}%)"
    )
    print(f"Total revenue: ${total_revenue:.2f}")
    print(f"Revenue per converter: ${total_revenue / max(len(converters), 1):.2f}")
