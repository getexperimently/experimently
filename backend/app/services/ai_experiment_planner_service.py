"""
AI-Enhanced Experiment Planning Service (EP-056).

Integrates the Claude API to provide plain-English experiment planning advice.
Gracefully degrades to template-based advice when the API is unavailable.
"""

import logging
import os

from backend.app.core.anthropic_compat import first_text
from backend.app.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AIExperimentPlannerService
# ---------------------------------------------------------------------------


class AIExperimentPlannerService:
    """
    Generates plain-English experiment planning advice.

    Uses the Anthropic Claude API when ANTHROPIC_API_KEY is set;
    falls back to a deterministic template otherwise.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def is_ai_available() -> bool:
        """Return True when ANTHROPIC_API_KEY is present in the environment."""
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    async def get_planning_advice(
        self,
        experiment_name: str,
        metric_description: str,
        baseline_rate: float,
        mde: float,
        runtime_days: float,
        business_context: str = "",
    ) -> dict:
        """
        Generate planning advice for an experiment.

        Attempts to use the Claude API; degrades to a template on failure.

        Parameters
        ----------
        experiment_name:
            Human-readable name of the experiment.
        metric_description:
            Plain-English description of the primary metric.
        baseline_rate:
            Current baseline metric rate (0–1).
        mde:
            Minimum detectable relative effect (e.g. 0.10 = 10% lift).
        runtime_days:
            Estimated days to reach significance.
        business_context:
            Optional additional business context.

        Returns
        -------
        dict with keys:
            - advice (str): plain-English advice
            - generated_by (str): 'ai' or 'template'
        """
        if self.is_ai_available():
            try:
                return await self._ai_advice(
                    experiment_name=experiment_name,
                    metric_description=metric_description,
                    baseline_rate=baseline_rate,
                    mde=mde,
                    runtime_days=runtime_days,
                    business_context=business_context,
                )
            except Exception as exc:
                logger.warning(
                    "AI planning advice failed, falling back to template: %s", exc
                )

        return self._template_advice(
            experiment_name=experiment_name,
            metric_description=metric_description,
            baseline_rate=baseline_rate,
            mde=mde,
            runtime_days=runtime_days,
            business_context=business_context,
        )

    # ------------------------------------------------------------------
    # Private helpers — AI path
    # ------------------------------------------------------------------

    async def _ai_advice(
        self,
        experiment_name: str,
        metric_description: str,
        baseline_rate: float,
        mde: float,
        runtime_days: float,
        business_context: str,
    ) -> dict:
        """Call Claude API for planning advice (async wrapper)."""
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("anthropic package not installed")

        prompt = self._build_prompt(
            experiment_name=experiment_name,
            metric_description=metric_description,
            baseline_rate=baseline_rate,
            mde=mde,
            runtime_days=runtime_days,
            business_context=business_context,
        )

        # Run sync Anthropic client in the same thread (no async client needed
        # because anthropic's sync client is fine in FastAPI endpoints).
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            # Raised from 800: adaptive thinking draws on the same budget.
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        advice = first_text(message)
        return {"advice": advice, "generated_by": "ai"}

    # ------------------------------------------------------------------
    # Private helpers — template path
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(
        experiment_name: str,
        metric_description: str,
        baseline_rate: float,
        mde: float,
        runtime_days: float,
        business_context: str,
    ) -> str:
        """Build the Claude prompt string."""
        context_section = (
            f"\nBusiness context: {business_context}" if business_context else ""
        )
        return (
            f"You are an expert in A/B experimentation and statistical power analysis.\n\n"
            f"An experimenter has completed a power analysis with the following results:\n\n"
            f"Experiment: {experiment_name}\n"
            f"Primary metric: {metric_description}\n"
            f"Baseline rate: {baseline_rate:.1%}\n"
            f"Minimum detectable effect (MDE): {mde:.1%} relative lift\n"
            f"MDE absolute: {baseline_rate * mde:.4f} "
            f"({baseline_rate:.3f} → {baseline_rate + baseline_rate * mde:.3f})\n"
            f"Estimated runtime: {runtime_days:.1f} days{context_section}\n\n"
            f"Please provide:\n"
            f"1. A plain-English interpretation of these results (1–2 sentences)\n"
            f"2. A risk assessment: is the MDE realistic? Is the runtime acceptable?\n"
            f"3. Practical suggestions to reduce runtime if it is > 30 days "
            f"(e.g. increase traffic allocation, use CUPED variance reduction, "
            f"use sequential testing / mSPRT)\n"
            f"4. Whether sequential/mSPRT testing might be more appropriate\n\n"
            f"Be concise and actionable. Focus on practical advice."
        )

    @staticmethod
    def _template_advice(
        experiment_name: str,
        metric_description: str,
        baseline_rate: float,
        mde: float,
        runtime_days: float,
        business_context: str,
    ) -> dict:
        """
        Generate deterministic template-based planning advice.

        Rules:
        - runtime < 7 days  → good runtime, quick experiment
        - 7 <= runtime <= 30 → reasonable runtime
        - 30 < runtime <= 90 → long, suggest optimisations
        - runtime > 90       → very long, suggest reducing scope
        """
        mde_pct = mde * 100
        baseline_pct = baseline_rate * 100
        mde_abs = baseline_rate * mde
        p2_pct = (baseline_rate + mde_abs) * 100

        parts: list[str] = []

        # 1. Interpretation
        parts.append(
            f"Your power analysis for '{experiment_name}' targets a {mde_pct:.1f}% "
            f"relative lift in {metric_description} "
            f"(from {baseline_pct:.2f}% to {p2_pct:.2f}%)."
        )

        # 2. Runtime assessment
        if runtime_days < 7:
            parts.append(
                f"The estimated runtime of {runtime_days:.1f} days is excellent — "
                "this is a good runtime for a quick, decisive experiment."
            )
        elif runtime_days <= 30:
            parts.append(
                f"The estimated runtime of {runtime_days:.1f} days is reasonable. "
                "This is within a normal experimentation window."
            )
        elif runtime_days <= 90:
            parts.append(
                f"The estimated runtime of {runtime_days:.1f} days is long. "
                "Consider ways to reduce it (see suggestions below)."
            )
        else:
            parts.append(
                f"The estimated runtime of {runtime_days:.1f} days is very long. "
                "Consider reducing scope: either increase the MDE, grow your "
                "traffic, or use a more sensitive analysis method."
            )

        # 3. MDE risk assessment
        if mde < 0.02:
            parts.append(
                f"Warning: an MDE of {mde_pct:.1f}% is very small. "
                "Ensure the expected lift is actually this small and not just "
                "noise — tiny MDEs require very large samples."
            )
        elif mde > 0.30:
            parts.append(
                f"Note: an MDE of {mde_pct:.1f}% is quite large. "
                "This may be achievable with fewer samples, but verify "
                "this lift is realistic for your use case."
            )

        # 4. Suggestions to reduce runtime
        if runtime_days > 30:
            suggestions = [
                "Increase traffic allocation to the experiment (more users per day).",
                "Apply CUPED (Covariate-Adjusted Pre-Experiment data) to reduce metric variance.",
                "Use sequential testing (mSPRT) to stop early when significance is reached.",
                "Increase the MDE threshold if a smaller lift is acceptable for your business.",
                "Focus on a single high-variance segment where the effect is likely largest.",
            ]
            parts.append("Suggestions to reduce runtime:")
            for s in suggestions:
                parts.append(f"  - {s}")

        # 5. Sequential testing recommendation
        if runtime_days > 14:
            parts.append(
                "Recommendation: with a runtime > 14 days, sequential testing (mSPRT) "
                "could allow you to call the experiment early — potentially saving "
                "weeks of experimentation time while controlling false-positive rates."
            )

        advice = "\n\n".join(parts)
        return {"advice": advice, "generated_by": "template"}
