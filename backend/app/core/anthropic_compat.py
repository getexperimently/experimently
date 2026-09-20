"""What changed between Claude model generations, in one place.

Three assumptions about the Anthropic API are baked into this codebase, and all
three were true for ``claude-sonnet-4-6`` and are false for the current
generation. They are collected here so that moving models is a change to one
file rather than a hunt through five services.

1. **``content[0]`` is the text.** It is not: ``content`` is a list of typed
   blocks. It happened to hold text first only because thinking was off. On
   Sonnet 5 and Opus 5, omitting ``thinking`` runs *adaptive* thinking, so
   ``content[0]`` is a ``ThinkingBlock`` and ``.text`` raises
   ``AttributeError``. (Opus 4.8 and 4.7 are the other way round -- omitting
   it means *no* thinking there, and ``{"type": "adaptive"}`` has to be asked
   for; adaptive-by-default starts at Opus 5. An earlier version of this
   paragraph said "every Opus from 4.8", which was wrong in the one file whose
   job is to be right about this.)
2. **``temperature`` is always accepted.** It is removed on Sonnet 5, Opus 5,
   Opus 4.8/4.7 and the Fable family -- sending it returns a 400.
3. **``max_tokens`` only bounds the answer.** Thinking tokens come out of the
   same budget, so a limit sized for a short answer can now be consumed before
   the answer starts.

Nothing here talks to the API; it is all local reasoning about a response or a
model name, so it is cheap to test and impossible to get wrong at runtime in a
way a mock would hide.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

#: Models known to accept ``temperature`` / ``top_p`` / ``top_k``.
#:
#: An ALLOW-list, not a deny-list, and deliberately so. A deny-list of
#: "models that reject sampling" would treat every model released after this
#: line was written as accepting, and the failure mode there is a hard 400 on
#: a model nobody has tried yet. With an allow-list the unknown case omits the
#: parameter instead: the request succeeds and the model uses its own default,
#: which is a far better thing to be wrong about.
SAMPLING_MODELS: frozenset = frozenset(
    {
        # 4.6 generation and earlier still take sampling parameters.
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        "claude-sonnet-4-5",
        "claude-opus-4-5",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet-20240620",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-haiku-20240307",
    }
)

#: Sampling parameters that the models above accept and the current generation
#: rejects. ``top_p``/``top_k`` are here because a caller can pass them through
#: free-form ``additional_params``, which bypassed a check that looked only at
#: the named ``temperature`` argument.
SAMPLING_PARAMS: frozenset = frozenset({"temperature", "top_p", "top_k"})

logger = logging.getLogger(__name__)


def accepts_sampling_params(model: str) -> bool:
    """Whether *model* accepts ``temperature``/``top_p``/``top_k``.

    Unknown models are treated as *not* accepting them -- see the note on
    :data:`SAMPLING_MODELS`.
    """
    return model in SAMPLING_MODELS


class MissingTextBlock(ValueError):
    """An Anthropic response carried no text block.

    Raised rather than returned as ``""`` on purpose. Every caller of
    :func:`first_text` sits inside a ``try/except`` whose job is to fall back
    to a template or a logged default, and the old ``content[0].text`` raised
    ``AttributeError`` in exactly this case, so the fallbacks fired. Returning
    an empty string instead made the AI path *succeed* with nothing in it --
    an ``ExperimentDesignSuggestion`` with an empty hypothesis, or a
    ``ResultsInterpretation`` recommending ``continue_testing`` on no evidence
    and labelled ``generated_by="ai"``. A fabricated verdict is worse than a
    template one, and worse than an error.

    It happens for real: a response can be all thinking when the budget is
    spent inside it, and a refusal carries no text at all.
    """


def first_text(message: Any) -> str:
    """The first text block of an Anthropic response.

    Replaces ``message.content[0].text``, which assumes the first block is
    text. Scans for ``type == "text"`` instead, so a leading thinking block --
    the normal shape once adaptive thinking is on -- is skipped rather than
    crashed on.

    Raises :class:`MissingTextBlock` when there is no text block; use
    :func:`first_text_or_empty` where an empty answer is genuinely acceptable.

    Tolerant of the shapes a test double produces: blocks may be objects with
    ``.type``/``.text`` or plain dicts, and ``content`` may be missing or None.
    """
    text = first_text_or_empty(message)
    if not text:
        kinds = [
            (b.get("type") if isinstance(b, dict) else getattr(b, "type", "?"))
            for b in (getattr(message, "content", None) or [])
        ]
        raise MissingTextBlock(
            f"response carried no text block (blocks: {kinds or 'none'}; "
            f"stop_reason={getattr(message, 'stop_reason', None)!r})"
        )
    return text


def first_text_or_empty(message: Any) -> str:
    """As :func:`first_text`, but ``""`` when there is no text block."""
    content: Iterable[Any] = getattr(message, "content", None) or []
    for block in content:
        block_type = (
            block.get("type")
            if isinstance(block, dict)
            else getattr(block, "type", None)
        )
        if block_type != "text":
            continue
        text = (
            block.get("text")
            if isinstance(block, dict)
            else getattr(block, "text", None)
        )
        if text:
            return str(text)
    return ""


def drop_unsupported_sampling(model: str, params: dict) -> dict:
    """Strip sampling parameters *model* would reject, logging what went.

    Applied to the **merged** parameter set -- named arguments and free-form
    passthrough together -- because a caller can put ``top_p`` in
    ``additional_params`` and reach the API without touching the named
    ``temperature`` argument a narrower check was watching.

    Logged rather than dropped quietly: for an LLM experiment, "same prompt,
    different temperature" is a legitimate design, and two variants silently
    reduced to byte-identical requests would measure nothing while looking
    like they measured something.
    """
    if accepts_sampling_params(model):
        return dict(params)
    kept = {k: v for k, v in params.items() if k not in SAMPLING_PARAMS}
    dropped = sorted(set(params) - set(kept))
    if dropped:
        logger.warning(
            "Model %s does not accept %s; sending the request without them. "
            "Variants differing only in these parameters are identical requests.",
            model,
            ", ".join(dropped),
        )
    return kept
