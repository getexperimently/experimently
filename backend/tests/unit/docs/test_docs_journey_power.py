"""The power calculator journey's oracles and inputs (#939, QA plan D2).

The journey holds the dashboard's Power Calculator and
``POST /api/v1/power/sample-size`` to the number of users per variant that
``statistics/power-analysis.md`` says a plan needs. What decides whether that
check can fail is pure, and is tested here, in the unit job:

* ``oracles.sample_size_proportions`` is the guide's formula (Fleiss, pooled
  under the null, unpooled under the alternative, two-sided, Bonferroni over
  the comparisons with the control), rounded up to a whole user; it gives the
  guide's worked example, and agrees with a line-by-line transcription of the
  guide's formula on every input the journey uses;
* no input the journey uses sits so near a whole number that the rounding
  could go either way;
* each change a defect would make (alpha one-sided, the z for the power
  rounded to two places, no Bonferroni correction, the pooled formula, Cohen's h)
  gives another whole number on at least one of the journey's inputs, so the
  journey would see it;
* ``oracles.sample_size_means`` solves the z-test on two means, two-sided by
  its near tail, which is the API's closed form;
* ``expect.computed`` with ``rel: 0`` accepts the oracle's whole number and
  refuses either neighbour, and a negative ``rel`` is refused at load;
* a shown number is read again while it changes (``checks.settle``), so a
  page that recalculates after a step is compared once it has, and a number
  that settles on a wrong value is still compared, and fails.

Temporary files only; no network, no browser, no git.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import pytest
import yaml

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER_ROOT = REPO_ROOT / "tests" / "acceptance" / "docs"
if str(RUNNER_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNNER_ROOT))

from docs_runner import checks, oracles
from docs_runner.model import Computed

JOURNEY = RUNNER_ROOT / "journeys" / "power-calculator.yaml"


def _oracle_calls(node: Any) -> Iterator[Dict[str, Any]]:
    """Every ``oracle: {name, args}`` in a journey file, wherever it is."""
    if isinstance(node, dict):
        oracle = node.get("oracle")
        if isinstance(oracle, dict) and "name" in oracle:
            yield oracle
        for value in node.values():
            yield from _oracle_calls(value)
    elif isinstance(node, list):
        for value in node:
            yield from _oracle_calls(value)


def _journey_inputs(name: str) -> List[Dict[str, Any]]:
    """The distinct argument sets the journey gives oracle *name*."""
    document = yaml.safe_load(JOURNEY.read_text(encoding="utf-8"))
    seen: List[Dict[str, Any]] = []
    for call in _oracle_calls(document):
        if call["name"] == name and call["args"] not in seen:
            seen.append(call["args"])
    return seen


PROPORTIONS = _journey_inputs("sample_size_proportions")
MEANS = _journey_inputs("sample_size_means")


def _ids(inputs: List[Dict[str, Any]]) -> List[str]:
    return [",".join(f"{k}={v}" for k, v in args.items()) for args in inputs]


def _by_the_guide(
    baseline_rate: float,
    minimum_detectable_effect: float,
    alpha: float,
    power: float,
    n_variants: int = 2,
    *,
    z_alpha_tail: float = 2,
    z_power: float | None = None,
    bonferroni: bool = True,
) -> float:
    """The guide's formula, line by line ("The Formula"), before rounding.

    The keyword arguments are the defects the journey must tell apart: a
    one-sided alpha (``z_alpha_tail=1``), a rounded z for the power, no
    Bonferroni correction.
    """
    from scipy.stats import norm

    if bonferroni:
        alpha = alpha / (n_variants - 1)
    p1 = baseline_rate
    p2 = baseline_rate + baseline_rate * minimum_detectable_effect
    p_bar = (p1 + p2) / 2
    z_a = norm.ppf(1 - alpha / z_alpha_tail)
    z_b = norm.ppf(power) if z_power is None else z_power
    return (
        z_a * math.sqrt(2 * p_bar * (1 - p_bar))
        + z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    ) ** 2 / (p2 - p1) ** 2


def test_the_journey_holds_six_conversion_inputs_and_a_mean():
    # The property: six fixed inputs, each on the dashboard and the API, and
    # one continuous metric on the API (the dashboard offers none).
    assert len(PROPORTIONS) == 6, _ids(PROPORTIONS)
    assert len(MEANS) == 1, _ids(MEANS)
    alphas = {args["alpha"] for args in PROPORTIONS}
    powers = {args["power"] for args in PROPORTIONS}
    assert {0.05, 0.01} <= alphas
    assert {0.8, 0.9} <= powers
    assert any(args.get("n_variants", 2) > 2 for args in PROPORTIONS)


def test_the_oracle_gives_the_guides_worked_example():
    # statistics/power-analysis.md, "Verification example": baseline 0.05, MDE
    # 10% relative, alpha 0.05, power 0.80 -> n = 31,234 per variant.
    assert oracles.sample_size_proportions(0.05, 0.10, 0.05, 0.80) == 31234


@pytest.mark.parametrize("args", PROPORTIONS, ids=_ids(PROPORTIONS))
def test_the_oracle_is_the_guides_formula_rounded_up(args):
    exact = _by_the_guide(**args)
    assert oracles.sample_size_proportions(**args) == math.ceil(exact)


@pytest.mark.parametrize("args", PROPORTIONS, ids=_ids(PROPORTIONS))
def test_no_input_is_on_a_rounding_edge(args):
    # The API and the dashboard compute the same formula with other code (the
    # dashboard's normal quantile is an approximation good to about 1e-9), so
    # an input whose n is within a millionth of a whole number could round
    # either way there without a defect.
    exact = _by_the_guide(**args)
    assert 1e-6 < exact - math.floor(exact) < 1 - 1e-6, exact


def _defects(args: Dict[str, Any]) -> Dict[str, float]:
    from statsmodels.stats.power import NormalIndPower
    from statsmodels.stats.proportion import proportion_effectsize

    p1 = args["baseline_rate"]
    p2 = p1 + p1 * args["minimum_detectable_effect"]
    k = args.get("n_variants", 2)
    corrected = args["alpha"] / (k - 1)
    p_bar = (p1 + p2) / 2
    from scipy.stats import norm

    z = norm.ppf(1 - corrected / 2) + norm.ppf(args["power"])
    found = {
        "one-sided alpha": _by_the_guide(**args, z_alpha_tail=1),
        "pooled variance only": z**2 * 2 * p_bar * (1 - p_bar) / (p2 - p1) ** 2,
        "Cohen's h": NormalIndPower().solve_power(
            effect_size=proportion_effectsize(p2, p1),
            alpha=corrected,
            power=args["power"],
            ratio=1.0,
            alternative="two-sided",
        ),
    }
    found["z for the power rounded to two places"] = _by_the_guide(
        **args, z_power=round(float(norm.ppf(args["power"])), 2)
    )
    if k > 2:
        found["no Bonferroni correction"] = _by_the_guide(**args, bonferroni=False)
    return found


def test_each_defect_moves_the_number_on_some_input():
    moved: Dict[str, List[str]] = {}
    for args, label in zip(PROPORTIONS, _ids(PROPORTIONS)):
        right = oracles.sample_size_proportions(**args)
        for defect, wrong in _defects(args).items():
            if math.ceil(wrong) != right:
                moved.setdefault(defect, []).append(label)
    assert sorted(moved) == sorted(
        [
            "one-sided alpha",
            "pooled variance only",
            "Cohen's h",
            "z for the power rounded to two places",
            "no Bonferroni correction",
        ]
    ), moved
    # The dashboard's plant (power.ts computes z with normPpf, so the plant
    # rounds it to two places: 0.8416 -> 0.84 at 80 % power) and the oracle's
    # (a one-sided alpha) move every input; so every step can see them.
    assert len(moved["z for the power rounded to two places"]) == len(PROPORTIONS)
    assert len(moved["one-sided alpha"]) == len(PROPORTIONS)


def test_some_input_tells_rounding_up_from_rounding_to_the_nearest():
    # The guide says the calculator and the API round n up to a whole user. An
    # input whose fractional part is below one half is where that differs from
    # rounding to the nearest user; the journey has three.
    below_half = [
        label
        for args, label in zip(PROPORTIONS, _ids(PROPORTIONS))
        if round(_by_the_guide(**args)) != oracles.sample_size_proportions(**args)
    ]
    assert len(below_half) >= 1, below_half


@pytest.mark.parametrize("args", MEANS, ids=_ids(MEANS))
def test_the_mean_oracle_is_the_z_test_by_its_near_tail(args):
    from scipy.stats import norm

    n = oracles.sample_size_means(**args)
    k = args.get("n_variants", 2)
    alpha = args["alpha"] / (k - 1)
    effect = (
        args["baseline_rate"] * args["minimum_detectable_effect"] / args["baseline_std"]
    )
    z_alpha = norm.ppf(1 - alpha / 2)

    def power_at(users: float) -> float:
        return norm.cdf(effect * math.sqrt(users / 2) - z_alpha)

    # n users per variant reach the power; one fewer does not.
    assert power_at(n) >= args["power"] > power_at(n - 1)
    # The API's closed form, 2 (z_alpha + z_power)^2 / effect^2, rounds the same.
    closed = 2 * (z_alpha + norm.ppf(args["power"])) ** 2 / effect**2
    assert math.ceil(closed) == n
    assert 1e-6 < closed - math.floor(closed) < 1 - 1e-6, closed


@pytest.mark.parametrize(
    "call",
    [
        lambda: oracles.sample_size_proportions(0.05, 0.10, 0.05, 0.80, n_variants=1),
        lambda: oracles.sample_size_proportions(0.6, 0.9, 0.05, 0.80),
        lambda: oracles.sample_size_means(0.2, 0.1, 0.1, 0.05, 0.8, n_variants=1),
        # An effect of 3 standard deviations needs under two users: no solution.
        lambda: oracles.sample_size_means(0.5, 0.6, 0.1, 0.05, 0.8),
    ],
    ids=[
        "one variant",
        "treatment rate past 1",
        "a mean with one variant",
        "a mean the solver cannot size",
    ],
)
def test_impossible_inputs_are_refused(call):
    with pytest.raises(ValueError):
        call()


def test_the_absolute_effect_is_the_guides():
    # "An MDE of 10% on a 5% baseline means ... 5% to 5.5% (absolute change =
    # 0.5 percentage points)"; the dashboard shows it in points, two places.
    assert oracles.absolute_effect(0.05, 0.10) == pytest.approx(0.005, rel=1e-12)
    assert checks.agrees("+0.50%", oracles.absolute_effect(0.05, 0.10, points=True))
    assert not checks.agrees("+0.55%", oracles.absolute_effect(0.05, 0.10, points=True))


def test_the_oracles_are_registered():
    assert oracles.ORACLES["sample_size_proportions"] is oracles.sample_size_proportions
    assert oracles.ORACLES["sample_size_means"] is oracles.sample_size_means
    assert oracles.ORACLES["absolute_effect"] is oracles.absolute_effect


# ---------------------------------------------------------------------------
# rel: 0 is equality
# ---------------------------------------------------------------------------
def test_rel_zero_accepts_the_whole_number_and_neither_neighbour():
    right = oracles.sample_size_proportions(0.05, 0.10, 0.05, 0.80)
    assert checks.within(31234, right, 0.0)
    assert not checks.within(31233, right, 0.0)
    assert not checks.within(31235, right, 0.0)
    # Not a boolean, not a string: a number.
    assert not checks.within("31234", right, 0.0)


def test_a_computed_check_takes_rel_zero_and_refuses_a_negative_one():
    oracle = {"name": "sample_size_proportions", "args": {}}
    assert Computed.model_validate({"oracle": oracle, "rel": 0}).rel == 0
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        Computed.model_validate({"oracle": oracle, "rel": -1e-9})
    with pytest.raises(ValueError, match="less than or equal to 0.01"):
        Computed.model_validate({"oracle": oracle, "rel": 0.02})


def test_every_sample_size_on_the_api_is_held_exactly():
    document = yaml.safe_load(JOURNEY.read_text(encoding="utf-8"))
    held = []
    for step in document["steps"]:
        for path, computed in (
            (step.get("expect") or {}).get("computed") or {}
        ).items():
            if computed["oracle"]["name"].startswith("sample_size_"):
                held.append((step["id"], path, computed["rel"]))
    assert len(held) == 7, held
    assert all(rel == 0 for _, _, rel in held), held


# ---------------------------------------------------------------------------
# A shown number is compared once it stops changing
# ---------------------------------------------------------------------------
class _Screen:
    """A figure that shows *texts* in turn, one per change."""

    def __init__(self, *texts: str):
        self.texts = list(texts)
        self.reads = 0
        self.waits = 0

    def read(self) -> str:
        self.reads += 1
        return self.texts[0]

    def changed(self, seen: str) -> bool:
        self.waits += 1
        assert seen == self.texts[0]
        if len(self.texts) == 1:
            return False  # it stays as it is for the whole timeout
        self.texts.pop(0)
        return True


def test_a_number_still_recalculating_is_read_again():
    screen = _Screen("--", "31,234")
    assert checks.settle(screen.read, screen.changed, 31234.0) == "31,234"
    assert screen.waits == 1


def test_an_old_number_is_waited_out():
    screen = _Screen("31,234", "59,211")
    assert checks.settle(screen.read, screen.changed, 59211.0) == "59,211"


def test_a_number_that_agrees_at_once_is_not_waited_for():
    screen = _Screen("31,234")
    assert checks.settle(screen.read, screen.changed, 31234.0) == "31,234"
    assert screen.waits == 0


def test_a_number_that_settles_wrong_is_returned_to_fail():
    # The old number, then a wrong new one (the planted z of 0.84 at 80% power).
    screen = _Screen("59,211", "31,198")
    text = checks.settle(screen.read, screen.changed, 31234.0)
    assert text == "31,198"
    assert not checks.agrees(text, 31234.0)
    assert screen.waits == 2  # read 31,198, then waited the timeout for a change


def test_a_number_that_never_settles_is_given_up_on():
    screen = _Screen(*[f"{n:,}" for n in range(100, 100 + checks.MAX_CHANGES + 5)])
    text = checks.settle(screen.read, screen.changed, 1.0)
    assert not checks.agrees(text, 1.0)
    assert screen.waits == checks.MAX_CHANGES
