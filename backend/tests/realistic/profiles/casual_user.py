"""
Behavioral profile: Casual User.

A casual user visits infrequently, converts rarely, and abandons sessions
quickly.  They represent the majority of a typical product's user base.

Characteristics:
  - 1–2 sessions per week
  - Low conversion rate (2–5%)
  - Short session duration (< 2 minutes)
  - High bounce rate on complex flows
  - Sensitive to performance degradation (> 3s load = abandoned)
  - Rarely uses advanced features
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CasualUserBehavior:
    """Encapsulates the behavioral parameters for a casual user profile."""

    sessions_per_week: float = 1.5
    conversion_rate: float = 0.03          # 3% baseline
    session_duration_minutes: float = 1.8  # average
    bounce_rate: float = 0.65              # 65% single-page sessions
    max_tolerated_latency_ms: float = 3000
    feature_discovery_rate: float = 0.10   # rarely finds advanced features
    return_probability: float = 0.30       # 30% chance of returning after 7 days

    def simulate_session(self, rng: random.Random | None = None) -> dict[str, Any]:
        """
        Simulate a single session for this user profile.

        Returns a dict of events representing the session's behavior:
          - page_view: always fired
          - scroll_depth: percentage scrolled
          - click: fired if user engages
          - purchase: fired on conversion
        """
        r = rng or random.Random()
        events: list[dict[str, Any]] = []

        # Always fires a page view
        events.append({"event": "page_view", "value": 1.0})

        # Bounce immediately?
        if r.random() < self.bounce_rate:
            events.append({"event": "bounce", "value": 1.0, "scroll_depth": r.uniform(0, 20)})
            return {"events": events, "converted": False, "session_minutes": r.uniform(0.1, 0.5)}

        # Engaged session
        scroll = r.uniform(20, 80)
        events.append({"event": "scroll", "value": scroll})

        duration = r.lognormvariate(
            mean=self.session_duration_minutes * 0.5,
            sigma=0.4,
        )

        # Conversion
        converted = r.random() < self.conversion_rate
        if converted:
            events.append({"event": "purchase", "value": r.uniform(10, 50)})

        return {
            "events": events,
            "converted": converted,
            "session_minutes": min(duration, 10),
        }

    def simulate_experiment_exposure(
        self, variant: str, rng: random.Random | None = None
    ) -> dict[str, Any]:
        """
        Simulate a casual user's response to an experiment variant.

        Casual users are slightly more sensitive to UI changes — a treatment
        that increases complexity will hurt their conversion rate more than
        it would for a power user.
        """
        r = rng or random.Random()
        # Casual users have a -10% sensitivity to complexity increases
        adjusted_cvr = self.conversion_rate
        if variant == "treatment":
            # Assume treatment adds some feature complexity
            adjusted_cvr *= 0.90
        session = self.simulate_session(r)
        return {
            "variant": variant,
            "profile": "casual",
            **session,
        }


def make_casual_user_population(
    n: int = 1000,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """
    Generate a population of simulated casual users.

    Returns a list of session results that can be used to seed experiment
    events or validate behavioral assumptions.
    """
    rng = random.Random(seed)
    profile = CasualUserBehavior()
    users = []
    for i in range(n):
        variant = "control" if i < n // 2 else "treatment"
        session = profile.simulate_experiment_exposure(variant, rng)
        session["user_id"] = f"casual-{i:06d}"
        users.append(session)
    return users


if __name__ == "__main__":
    population = make_casual_user_population(n=100, seed=42)
    converters = [u for u in population if u["converted"]]
    print(f"Casual user population: {len(population)} users")
    print(f"Converters: {len(converters)} ({100 * len(converters) / len(population):.1f}%)")
