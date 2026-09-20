"""The three Claude-generation assumptions, and guards against re-making them.

`backend/app/core/anthropic_compat.py` exists because three things that were
true of `claude-sonnet-4-6` are false of the current generation, and all three
were baked into services with no test that would notice:

* `content[0]` is the text block — false once thinking is on;
* `temperature` is always accepted — a 400 on Sonnet 5, Opus 5, Opus 4.8/4.7
  and the Fable family;
* the model can be a literal — it was, in three services, a generation behind.

The last two tests here are the durable ones: they scan the tree, so the rot
cannot come back by someone adding a fourth call site.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.app.core.anthropic_compat import (
    MissingTextBlock,
    accepts_sampling_params,
    drop_unsupported_sampling,
    first_text,
    first_text_or_empty,
)

ROOT = Path(__file__).resolve().parents[4]

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def block(block_type: str, text: str | None = None) -> MagicMock:
    b = MagicMock()
    b.type = block_type
    if text is not None:
        b.text = text
    return b


def message(*blocks) -> MagicMock:
    m = MagicMock()
    m.content = list(blocks)
    return m


class TestFirstText:
    def test_skips_a_leading_thinking_block(self) -> None:
        """The whole reason this helper exists."""
        assert (
            first_text(message(block("thinking"), block("text", "answer"))) == "answer"
        )

    def test_plain_text_response(self) -> None:
        assert first_text(message(block("text", "answer"))) == "answer"

    def test_ignores_tool_use_blocks(self) -> None:
        assert (
            first_text(message(block("tool_use"), block("text", "answer"))) == "answer"
        )

    def test_empty_content_raises(self) -> None:
        """No text must be an error, not an empty answer.

        Returning "" made the AI path *succeed* with nothing in it -- an
        interpretation recommending `continue_testing` on no evidence, labelled
        `generated_by="ai"`. The callers all sit in a try/except that falls back
        to a template; raising is what reaches it.
        """
        with pytest.raises(MissingTextBlock):
            first_text(message())

    def test_missing_content_raises(self) -> None:
        m = MagicMock()
        m.content = None
        with pytest.raises(MissingTextBlock):
            first_text(m)

    def test_no_text_block_at_all_raises(self) -> None:
        """The real shape when the budget is spent inside thinking."""
        with pytest.raises(MissingTextBlock) as excinfo:
            first_text(message(block("thinking"), block("tool_use")))
        assert "thinking" in str(excinfo.value)

    def test_or_empty_variant_does_not_raise(self) -> None:
        assert first_text_or_empty(message(block("thinking"))) == ""
        assert first_text_or_empty(message(block("text", "hi"))) == "hi"

    def test_dict_blocks(self) -> None:
        """Some callers and fixtures hand back plain dicts."""
        m = MagicMock()
        m.content = [{"type": "thinking"}, {"type": "text", "text": "answer"}]
        assert first_text(m) == "answer"


class TestAcceptsSamplingParams:
    @pytest.mark.parametrize(
        "model", ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"]
    )
    def test_known_accepting_models(self, model: str) -> None:
        assert accepts_sampling_params(model)

    @pytest.mark.parametrize(
        "model",
        ["claude-sonnet-5", "claude-opus-5", "claude-opus-4-8", "claude-fable-5-1"],
    )
    def test_models_that_reject_sampling(self, model: str) -> None:
        assert not accepts_sampling_params(model)

    def test_dropping_covers_the_merged_parameter_set(self) -> None:
        """top_p arriving via free-form additional_params must go too.

        The first version filtered only the named `temperature` argument, so a
        variant with `additional_params={"top_p": 0.9}` still produced the 400
        this exists to prevent.
        """
        kept = drop_unsupported_sampling(
            "claude-sonnet-5", {"temperature": 0.7, "top_p": 0.9, "max_tokens": 10}
        )
        assert kept == {"max_tokens": 10}

    def test_dropping_keeps_everything_for_an_accepting_model(self) -> None:
        params = {"temperature": 0.7, "top_p": 0.9}
        assert drop_unsupported_sampling("claude-sonnet-4-6", params) == params

    def test_an_unknown_model_is_assumed_to_reject(self) -> None:
        """The allow-list's whole point.

        A deny-list would treat every model released after this line as
        accepting, and be wrong with a hard 400. Omitting the parameter is the
        recoverable direction to be wrong in.
        """
        assert not accepts_sampling_params("claude-something-not-released-yet")


# ---------------------------------------------------------------------------
# Tree scans — these are what stop the rot returning
# ---------------------------------------------------------------------------

SERVICE_DIRS = ("backend/app", "modules/backend/app")


def python_sources() -> list[Path]:
    files: list[Path] = []
    for directory in SERVICE_DIRS:
        base = ROOT / directory
        if base.is_dir():
            files.extend(p for p in base.rglob("*.py") if "migrations" not in p.parts)
    # A scan over nothing passes every assertion below. `backend/app` always
    # exists (modules/ does not, in a core checkout), so an empty list means
    # ROOT is wrong -- a moved test file, a packaging change -- and the gates
    # are reporting OK having read no code at all.
    assert files, f"no Python sources found under {SERVICE_DIRS} from ROOT={ROOT}"
    return files


def test_no_service_reads_content_index_zero() -> None:
    """`content[0].text` must not come back.

    It is the access that breaks the moment thinking is on, and a mocked test
    will not catch it -- a MagicMock answers `.text` whatever the block is.
    """
    # The compat module names the pattern in its own docstring, which this
    # scan duly matched on its first run. A text gate that does not exclude
    # its own source finds itself -- the same way the export sweep did.
    exempt = {"backend/app/core/anthropic_compat.py"}
    offenders = [
        f"{path.relative_to(ROOT)}:{i}"
        for path in python_sources()
        if str(path.relative_to(ROOT)) not in exempt
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\.content\[0\]\s*\.\s*text", line)
    ]
    assert not offenders, (
        "use backend.app.core.anthropic_compat.first_text() instead of "
        f"content[0].text: {offenders}"
    )


def test_no_service_hardcodes_a_claude_model() -> None:
    """The platform's own calls take their model from settings.

    Any ``"claude-..."`` string literal, not just ``model="claude-..."``. The
    first version of this required the token ``model`` immediately before the
    ``=``, and so matched none of the three literals that were in the tree when
    it was written -- ``judge_model: str = "claude-3-5-sonnet-20241022"`` in a
    schema and a service signature, and the setting beside them. It passed, and
    the pull request claimed on its strength that no service hard-codes a
    model. It did.

    A user-selected model (LLM experiments) is passed in as a variable and is
    unaffected.
    """
    # Exempt by file, and only files whose *purpose* is to name models:
    #   config.py       declares the settings other code reads
    #   anthropic_compat the per-generation capability lists
    #   llm_pricing     the price table
    # `llm_proxy_service` was exempt as a whole while it held the price table,
    # which also excused every provider call in it -- the place a stray literal
    # would override a user's variant selection. The table moved out so this
    # list could be precise.
    allowed = {
        "backend/app/core/config.py",
        "backend/app/core/anthropic_compat.py",
        "backend/app/core/llm_pricing.py",
    }
    offenders = [
        f"{path.relative_to(ROOT)}:{i}: {line.strip()}"
        for path in python_sources()
        if str(path.relative_to(ROOT)) not in allowed
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"""['"]claude-[a-z0-9.\-]+['"]""", line, re.IGNORECASE)
    ]
    assert not offenders, "take the model from settings rather than a literal: " + str(
        offenders
    )


#: First-party Anthropic list prices, USD per 1K tokens, for the models this
#: repository names. Written down here as an independent copy so the test is an
#: oracle rather than a restatement of the table it checks.
KNOWN_RATES = {
    "claude-fable-5-1": (0.010, 0.050),
    "claude-opus-5": (0.005, 0.025),
    "claude-opus-4-8": (0.005, 0.025),
    "claude-opus-4-6": (0.005, 0.025),
    "claude-sonnet-5": (0.002, 0.010),
    "claude-sonnet-4-6": (0.003, 0.015),
    "claude-haiku-4-5": (0.001, 0.005),
}


def test_anthropic_prices_match_the_published_rates() -> None:
    """Spot-check the table against rates written down independently.

    A heuristic ceiling was tried first and does not work: `claude-opus-4-6`
    was priced $0.015/$0.075 per 1K, and that is a *real* rate -- Claude 3
    Opus's. The entry was Claude 3 Opus's price under Opus 4.6's name, which no
    plausibility bound can catch, because nothing about the number is
    implausible. Only a second source can.
    """
    from backend.app.core.llm_pricing import COST_PER_1K_TOKENS

    anthropic_costs = COST_PER_1K_TOKENS["anthropic"]
    wrong = {
        model: (anthropic_costs[model]["input"], anthropic_costs[model]["output"])
        for model, expected in KNOWN_RATES.items()
        if model in anthropic_costs
        and (anthropic_costs[model]["input"], anthropic_costs[model]["output"])
        != expected
    }
    assert not wrong, f"priced differently from the published rates: {wrong}"

    missing = sorted(set(KNOWN_RATES) - set(anthropic_costs))
    assert not missing, f"unpriced, so they would record $0.00: {missing}"


def test_every_configured_default_is_priced() -> None:
    """A model the platform is configured to use must have a price.

    Derived from the settings rather than listed, so changing a default cannot
    outrun the table.
    """
    from backend.app.core.config import settings
    from backend.app.core.llm_pricing import COST_PER_1K_TOKENS

    anthropic_costs = COST_PER_1K_TOKENS["anthropic"]
    for configured in (settings.ANTHROPIC_MODEL, settings.LLM_DEFAULT_JUDGE_MODEL):
        assert configured in anthropic_costs, (
            f"{configured} is a configured default but has no price, so an "
            "experiment using it would record $0.00"
        )


def test_output_is_never_cheaper_than_input() -> None:
    from backend.app.core.llm_pricing import COST_PER_1K_TOKENS

    for model, prices in COST_PER_1K_TOKENS["anthropic"].items():
        assert prices["output"] >= prices["input"], model
