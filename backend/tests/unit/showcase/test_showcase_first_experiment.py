"""Video 2, "Your first experiment" (#1066): its storyboard, its traffic and its gates.

The numbers the video states are pinned here, against the code that produces
them on the platform: the estimate's sample size and days, the traffic's users
and conversions at the documented seed, and the result the results API gives
for them. Every refusal is shown firing on one planted defect. No browser,
Docker, network or database: the traffic is sent to a stand-in platform that
assigns by the server's hash.
"""

from __future__ import annotations

import math
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from showcase import contract
from showcase.capture import config, gates, storyboard, traffic

from backend.app.core.consistent_hash import bucket_of
from backend.app.services.analysis_service import AnalysisService
from backend.app.services.power_calculator_service import sample_size_two_proportions
from backend.app.services.srm_service import compute_srm
from backend.app.services.sufficient_stats_analysis import (
    BinomialVariant,
    binomial_metric_result,
)

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[4]
ACCEPTANCE = REPO / "tests" / "acceptance"
V1 = ACCEPTANCE / "showcase" / "storyboards" / "01-getting-started.yaml"
V2 = ACCEPTANCE / "showcase" / "storyboards" / "02-first-experiment.yaml"

#: Video 1 as approved (D65): the recording between its title and end cards,
#: from the .vtt of the approved render (61.733 s with its 7 s of cards).
V1_RECORDED_MS = 54_733

#: At seed 40, the server's hash and the generator's draws give these (gate 10
#: holds the platform to the same numbers on every recording).
PLANNED = {
    "control": {"users": 31_309, "converting_users": 1_569},
    "treatment": {"users": 31_691, "converting_users": 1_781},
}


def board() -> storyboard.Storyboard:
    return storyboard.load(V2)


def v2_data() -> dict:
    return yaml.safe_load(V2.read_text(encoding="utf-8"))


def beat(text_start: str) -> storyboard.Beat:
    for scene in board().scenes:
        for item in scene.beats:
            if item.cue.startswith(text_start):
                return item
    raise AssertionError(f"no cue starts {text_start!r}")


def form_key(name: str) -> str:
    """The wizard's ``generateKey`` (frontend/src/components/experiments/new/formState.ts)."""
    return re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9]+", "_", name.lower()))[:64]


@pytest.fixture(scope="module")
def plan() -> traffic.Plan:
    made = board()
    assert made.traffic is not None
    return traffic.plan(made.traffic, made.end_state.experiment.key)


# --- The storyboard -----------------------------------------------------------------


def test_the_storyboard_loads_its_captions_are_fixed_and_it_fits_the_video():
    made = board()
    for cue in storyboard.compile_cues(made):
        assert contract.caption_problems(cue["text"]) == []
    assert storyboard.cue_list_bytes(made) == storyboard.cue_list_bytes(
        storyboard.parse(v2_data())
    )
    length = (
        storyboard.estimate_ms(made) + contract.TITLE_CARD_MS + contract.END_CARD_MS
    )
    # Scrolling is not in the estimate: leave room for it under 75 s.
    assert contract.MIN_VIDEO_MS + 5_000 <= length <= contract.MAX_VIDEO_MS - 5_000


def test_the_length_estimate_is_within_two_percent_of_video_1s_recording():
    estimate = storyboard.estimate_ms(storyboard.load(V1))
    assert abs(estimate - V1_RECORDED_MS) <= 0.02 * V1_RECORDED_MS, estimate


def test_the_experiment_is_made_with_the_key_the_wizard_gives_its_name():
    made = board()
    assert made.traffic.experiment == made.end_state.experiment.name
    assert form_key(made.end_state.experiment.name) == made.end_state.experiment.key
    typed = [
        step.text
        for scene in made.scenes
        for item in scene.beats
        for step in item.steps
        if isinstance(step, storyboard.Type)
    ]
    assert made.end_state.experiment.name in typed
    assert made.end_state.experiment.winner in typed
    assert made.traffic.event in typed


def test_the_estimate_caption_is_the_calculators_answer_for_the_typed_inputs():
    """Baseline 5%, effect 10%, 80% power, 95% confidence; 10,000 a day, half in the test."""
    typed = [s.text for s in beat("Size it first").steps]
    assert typed == ["5", "10", "10000", "50"]
    per_variant = sample_size_two_proportions(
        p1=0.05, p2=0.05 * 1.10, alpha=0.05, power=0.8, two_tailed=True
    )
    days = math.ceil(per_variant / (10_000 * 0.50 / 2))
    caption = beat("31,234").cue
    assert storyboard.numbers_in(caption) == [f"{per_variant:,}", str(days)]


def test_the_time_card_states_the_traffics_users():
    made = board()
    headline = next(s.card.headline for s in made.scenes if s.card and s.card.headline)
    assert storyboard.numbers_in(headline) == [f"{made.traffic.users:,}"]


def test_a_code_card_that_names_a_host_and_port_is_refused():
    data = v2_data()
    card = next(s["card"] for s in data["scenes"] if "code" in s.get("card", {}))
    card["code"]["lines"] = ["  apiUrl: 'http://localhost:8000',"]
    with pytest.raises(storyboard.StoryboardError, match="names a host and port"):
        storyboard.parse(data)


@pytest.mark.parametrize(
    "change, match",
    [
        (lambda d: d["scenes"][1].update(traffic="finish"), "started once"),
        (lambda d: d["scenes"][3].pop("traffic"), "started once"),
        (lambda d: d.pop("traffic"), "storyboard has none"),
        (lambda d: d["scenes"][2].update(open="/experiments"), "exactly one"),
        (lambda d: d["scenes"][1]["card"].update(headline="Two"), "exactly one of"),
    ],
)
def test_a_storyboard_out_of_shape_is_refused(change, match):
    data = v2_data()
    change(data)
    with pytest.raises(storyboard.StoryboardError, match=match):
        storyboard.parse(data)


# --- The traffic at the documented seed ---------------------------------------------


def test_the_traffic_at_the_documented_seed_is_what_the_storyboard_says(plan):
    assert plan.key == "sticky_add_to_cart_bar"
    assert plan.split == PLANNED
    assert sum(arm["users"] for arm in plan.split.values()) == board().traffic.users
    # Both variants reach the sample the estimate asked for.
    assert min(arm["users"] for arm in plan.split.values()) >= 31_234
    assert plan.p_value is not None and plan.p_value < 0.05


def test_the_result_caption_is_what_the_results_api_computes_for_that_traffic(plan):
    """The engine's own functions on the planned counts: the lift, the p-value, the winner."""
    variants = [
        (BinomialVariant("v-control", "Control", True), *_counts(plan, "control")),
        (BinomialVariant("v-sticky", "Sticky bar", False), *_counts(plan, "treatment")),
    ]
    metric = SimpleNamespace(
        id="m-1", name="Conversion", metric_type="conversion", is_primary=True
    )
    result = binomial_metric_result(variants, 0.05, "benjamini_hochberg", metric=metric)
    decision = AnalysisService._summarise_decision(None, [result], True)
    assert decision["recommendation"] == "SHIP_VARIANT"
    assert decision["winning_variant_id"] == "v-sticky"
    reason = decision["recommendation_reason"]
    assert reason == "Sticky bar shows 12.1% improvement on Conversion (p=0.0007)."
    caption = beat("Sticky bar wins").cue
    # "95%" is the analysis line's confidence, the experiment's default.
    assert storyboard.numbers_in(caption) == ["12.1%", "95%"]
    assert storyboard.numbers_in(caption)[0] in storyboard.numbers_in(reason)
    # No sample-ratio warning overrides the recommendation.
    srm = compute_srm(
        {
            "v-control": PLANNED["control"]["users"],
            "v-sticky": PLANNED["treatment"]["users"],
        },
        {"v-control": 50, "v-sticky": 50},
    )
    assert srm is not None and not srm.warning


def _counts(made: traffic.Plan, arm: str):
    return made.split[arm]["users"], made.split[arm]["converting_users"]


def test_the_generator_is_this_checkouts(monkeypatch, tmp_path):
    assert traffic.REPO_ROOT in Path(traffic.generator().__file__).resolve().parents
    monkeypatch.setattr(traffic, "REPO_ROOT", tmp_path)
    with pytest.raises(traffic.TrafficFailed, match="not from this checkout"):
        traffic.generator()


# --- The sender, against a stand-in platform ----------------------------------------


class Answer:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self._body = body

    def json(self) -> dict:
        return self._body


class Platform:
    """Assigns as the server does (``bucket_of`` over Control then Sticky bar,
    50/50) and stores events; can answer one status at the Nth assign."""

    def __init__(self, key: str, fail_at: int = 0, status: int = 429):
        self.key = key
        self.fail_at = fail_at
        self.status = status
        self.assigns = 0
        self.lock = threading.Lock()
        self.assigned = {}
        self.events = []

    def session(self):
        return self

    def post(self, url, json, headers, timeout):
        assert headers == {"X-API-Key": "made-up-traffic-key-0123456789"}
        with self.lock:
            if url.endswith("/api/v1/tracking/assign"):
                self.assigns += 1
                if self.assigns == self.fail_at:
                    return Answer(self.status, {"detail": "slow down"})
                control = bucket_of(json["user_id"], json["experiment_key"]) < 50
                self.assigned[json["user_id"]] = control
                return Answer(
                    200,
                    {
                        "variant_name": "Control" if control else "Sticky bar",
                        "is_control": control,
                        "assigned": True,
                    },
                )
            assert json["event_type"] == json["event_name"] == "purchase"
            assert json["experiment_key"] == self.key
            self.events.append(json["user_id"])
            return Answer(200, {"id": f"event-{len(self.events)}"})


def small_plan(users: int = 400) -> traffic.Plan:
    made = board().traffic.model_copy(update={"users": users})
    return traffic.plan(made, "sticky_add_to_cart_bar")


def test_the_sender_reports_what_the_platform_answered_and_it_is_the_plan():
    made = small_plan()
    platform = Platform(made.key)
    sender = traffic.Sender(
        made,
        api_url="http://127.0.0.1:28400",
        api_key="made-up-traffic-key-0123456789",
        workers=3,
        session=platform.session,
    )
    sender.start()
    report = sender.finish(timeout=60)
    assert report.sent == 400 and report.mismatches == 0 and report.not_assigned == 0
    assert report.by_arm == made.split
    assert report.names == {"control": "Control", "treatment": "Sticky bar"}
    converting = sum(arm["converting_users"] for arm in made.split.values())
    assert len(set(platform.events)) == converting == report.events


@pytest.mark.regression
def test_a_refused_call_stops_the_traffic_and_never_names_the_key():
    made = small_plan()
    platform = Platform(made.key, fail_at=50, status=429)
    sender = traffic.Sender(
        made,
        api_url="http://127.0.0.1:28400",
        api_key="made-up-traffic-key-0123456789",
        workers=2,
        session=platform.session,
    )
    sender.start()
    with pytest.raises(traffic.TrafficFailed, match="answered 429") as raised:
        sender.finish(timeout=60)
    assert "made-up-traffic-key" not in str(raised.value)
    assert platform.assigns < 400


def test_waiting_for_the_first_users_gives_up_with_the_count():
    made = small_plan(100)
    sender = traffic.Sender(
        made,
        api_url="http://127.0.0.1:28400",
        api_key="made-up-traffic-key-0123456789",
        workers=1,
        session=Platform(made.key).session,
    )
    with pytest.raises(traffic.TrafficFailed, match="0 of 50 users in"):
        sender.wait_for(50, timeout=0.2)  # never started


# --- U2: the numbers in a caption are on the page -----------------------------------


@pytest.mark.parametrize(
    "caption, shown, ok",
    [
        (
            "31,234 users per variant, about 13 days here.",
            "31,234 users per variant 62,468 users in total About 13 days (about 2 weeks).",
            True,
        ),
        # The UX plant: a rounded number the page never shows.
        (
            "31,000 users per variant, about 13 days here.",
            "31,234 users per variant About 13 days.",
            False,
        ),
        # 13 is not found inside 31,234.
        ("About 13 days here.", "31,234 users per variant", False),
        ("Sticky bar wins: 12.1% more purchases.", "11.8% improvement", False),
        ("Two variants, split evenly between users.", "Currently 100%", True),
    ],
)
def test_a_caption_number_the_page_does_not_show_is_refused(caption, shown, ok):
    verdict, _numbers, why = gates.caption_numbers(caption, shown)
    assert verdict is ok
    if not ok:
        assert why.startswith("the caption says")


# --- Gate 10: the experiment the video made ------------------------------------------

REASON = "Sticky bar shows 12.1% improvement on Conversion (p=0.0007)."


def results_for(split: dict, p_value: float, reason: str = REASON) -> dict:
    return {
        "metrics": [
            {
                "is_primary": True,
                "variants": [
                    {
                        "variant_id": "v-control",
                        "variant_name": "Control",
                        "is_control": True,
                        "sample_size": split["control"]["users"],
                        "conversions": split["control"]["converting_users"],
                        "p_value": None,
                    },
                    {
                        "variant_id": "v-sticky",
                        "variant_name": "Sticky bar",
                        "is_control": False,
                        "sample_size": split["treatment"]["users"],
                        "conversions": split["treatment"]["converting_users"],
                        "p_value": p_value,
                    },
                ],
            }
        ],
        "summary": {
            "recommendation": "SHIP_VARIANT",
            "winning_variant_id": "v-sticky",
            "recommendation_reason": reason,
        },
    }


def end_check(**changes):
    end = board().end_state.experiment
    oracle = traffic.generator().fisher_p_value(PLANNED)
    kwargs = {
        "named": [{"key": end.key, "status": "active"}],
        "results": results_for(PLANNED, oracle),
        "planned": PLANNED,
        "report": PLANNED,
        "oracle_p": oracle,
        "shown": " " + REASON + "\n",
    }
    kwargs.update(changes)
    return gates.experiment_end(end, **kwargs)


def test_the_experiment_end_state_passes_when_all_three_counts_and_the_page_agree():
    ok, numbers, why = end_check()
    assert ok, why
    assert numbers["counted"] == PLANNED


@pytest.mark.regression
def test_one_conversion_more_on_the_platform_is_refused():
    """QA's plant for gate 10/2: one variant's conversions changed by one."""
    counted = {
        "control": dict(PLANNED["control"]),
        "treatment": {**PLANNED["treatment"], "converting_users": 1_782},
    }
    oracle = traffic.generator().fisher_p_value(PLANNED)
    ok, _numbers, why = end_check(results=results_for(counted, oracle))
    assert not ok and "users and conversions differ" in why


@pytest.mark.parametrize(
    "changes, words",
    [
        ({"named": []}, "0 experiments are named"),
        ({"named": [{"key": "sticky", "status": "active"}]}, "has key"),
        ({"named": [{"key": "sticky_add_to_cart_bar", "status": "draft"}]}, "status"),
        ({"report": {"control": {"users": 1, "converting_users": 0}}}, "differ"),
        ({"oracle_p": 0.5}, "is not Fisher's"),
        (
            {"shown": "Sticky bar shows 9.9% improvement on Conversion (p=0.0400)."},
            "the page showed",
        ),
        ({"shown": None}, "the page showed"),
        ({"results": None}, "no answer"),
    ],
)
def test_an_end_state_that_disagrees_anywhere_is_refused(changes, words):
    ok, _numbers, why = end_check(**changes)
    assert not ok and words in why


def test_a_winner_the_storyboard_did_not_name_is_refused():
    results = results_for(PLANNED, traffic.generator().fisher_p_value(PLANNED))
    results["summary"]["recommendation"] = "CONTINUE_TESTING"
    ok, _numbers, why = end_check(results=results)
    assert not ok and "CONTINUE_TESTING" in why


def test_video_2_registers_in_the_tool():
    assert (
        config.VIDEOS["02-first-experiment"] == "storyboards/02-first-experiment.yaml"
    )
    assert "U2" in contract.REQUIRED_CAPTURE_GATES


# --- The wiring: the director's U2 check and the code card's check at capture time ---


class Found:
    """A located element with its text."""

    def __init__(self, text: str):
        self.text = text

    def inner_text(self) -> str:
        return self.text


def a_director(tmp_path):
    from showcase.capture import director, guard

    return director.Director(
        context=object(),
        page=object(),
        frames=tmp_path / "work" / "video" / "capture" / "frames",
        dashboard="http://127.0.0.1:28401",
        api_port=28400,
        dashboard_port=28401,
        redactor=director.redaction.Redactor(),
        forbidden=(),
        work=guard.WorkRoot(tmp_path / "work"),
    )


@pytest.mark.regression
def test_the_director_refuses_a_caption_number_its_focus_does_not_show(tmp_path):
    from showcase.capture import director

    made = a_director(tmp_path)
    made.where = "scene setup beat 6"
    with pytest.raises(director.CaptureFailed, match="U2: scene setup beat 6"):
        made.check_numbers(
            "31,000 users per variant, about 13 days here.",
            Found("31,234 users per variant About 13 days (about 2 weeks)."),
        )
    made.check_numbers(
        "31,234 users per variant, about 13 days here.",
        Found("31,234 users per variant About 13 days (about 2 weeks)."),
    )
    made.check_numbers("Review it, then create it.", Found("no number at all"))
    assert (made.tally.number_checks, made.tally.numbered_cues) == (3, 2)
