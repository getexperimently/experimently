"""A video's storyboard: the YAML file, its refusals, and the cue list it compiles to.

A storyboard is a list of scenes. A scene is either a page (opened off camera
at ``open``, then recorded) or a card (``card``: an HTML card drawn by the same
browser and recorded like a page). A scene is a list of beats; a beat is

* ``before``: waits for the page the last beat's click opened. Recording
  pauses while they run (a cut: no spinner is filmed, and the capture
  directory allows at most a second without a caption), so a beat's clicks go
  in ``exit``, not here;
* ``cue``: the caption, and ``focus``: the element it is about, which must be
  inside the page area when the cue starts and when it ends (gate 9);
* ``steps``: run while the caption is on screen. None may remove the focus;
* the hold: the cue stays until its reading time (``contract.reading_time_ms``)
  has passed, and a ``payoff`` beat then holds ``config.PAYOFF_MS`` more with
  nothing moving (U5);
* ``exit``: run after the cue's end check, with the caption still up: the
  click that leaves the page.

Refused at load (``StoryboardError``), before any stack starts: an unknown key,
a cue with no focus, a caption ``contract.caption_problems`` refuses, a caption
holding a template (``{``) or anything but plain text, a ``type`` of a
credential into a step not marked secret, an on-camera step that opens the API
keys page, a locator naming nothing, and a scene with no beats. Caption text
never comes from the page or the run: ``compile_cues`` is a pure function of
the file, so the cue list is the same on every run (gate 13a).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from showcase import contract
from showcase.capture import config


class StoryboardError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Locator(_Strict):
    """How a step or a cue finds its element. Exactly one way, plus ``nth``."""

    role: Optional[str] = None
    name: Optional[str] = None
    exact: bool = False
    text: Optional[str] = None
    label: Optional[str] = None
    testid: Optional[str] = None
    css: Optional[str] = None
    nth: int = 0

    @model_validator(mode="after")
    def _one_way(self) -> "Locator":
        ways = [
            w for w in (self.role, self.text, self.label, self.testid, self.css) if w
        ]
        if len(ways) != 1:
            raise ValueError(
                "a locator names exactly one of role, text, label, testid or css"
            )
        if self.name is not None and self.role is None:
            raise ValueError("name is a role's accessible name; give role too")
        return self

    def describe(self) -> str:
        if self.role:
            return f"{self.role} {self.name!r}" if self.name else str(self.role)
        for key in ("text", "label", "testid", "css"):
            value = getattr(self, key)
            if value:
                return f"{key} {value!r}"
        return "?"


class Click(_Strict):
    click: Locator


class Move(_Strict):
    move: Locator


class Type(_Strict):
    type: Locator
    text: str
    #: The field must be a password field, drawn as dots.
    secret: bool = False


class Look(_Strict):
    """A ring around an element, held ``ms`` (at most 2.5 s, one ring at a time)."""

    look: Locator
    ms: int = Field(default=1500, ge=300, le=2500)


class ScrollTo(_Strict):
    scroll_to: Locator


class WaitFor(_Strict):
    """Wait, off the clock of any cue, for an element or an address."""

    wait_for: Optional[Locator] = None
    url: Optional[str] = None
    timeout_ms: int = Field(default=15000, ge=100, le=60000)

    @model_validator(mode="after")
    def _one(self) -> "WaitFor":
        if (self.wait_for is None) == (self.url is None):
            raise ValueError("wait_for names an element or a url, not both")
        return self


Step = Union[Click, Move, Type, Look, ScrollTo, WaitFor]


class Beat(_Strict):
    before: List[Step] = Field(default_factory=list)
    cue: str
    focus: Locator
    steps: List[Step] = Field(default_factory=list)
    exit: List[Step] = Field(default_factory=list)
    payoff: bool = False
    #: Role=alert elements this beat may show (none by default; gate 11).
    alerts: List[str] = Field(default_factory=list)


class Card(_Strict):
    """A card drawn by the browser: a label, one command line and one sentence."""

    label: str
    command: str
    note: str


class Scene(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")
    open: Optional[str] = Field(default=None, pattern=r"^/[A-Za-z0-9/_?=&.-]*$")
    card: Optional[Card] = None
    #: Sign in as the demo admin off camera before the scene.
    signed_in: bool = False
    #: Results to load off camera first, so no skeleton is filmed (by experiment name).
    warm_results: List[str] = Field(default_factory=list)
    beats: List[Beat] = Field(min_length=1)

    @model_validator(mode="after")
    def _page_or_card(self) -> "Scene":
        if (self.open is None) == (self.card is None):
            raise ValueError("a scene opens a page or draws a card, not both")
        return self


class SeedCounts(_Strict):
    experiments: int
    feature_flags: int
    users: int


class EndState(_Strict):
    """Gate 10: what is true after the last scene, checked through the API."""

    signed_in_as: str
    #: The experiments page's rows the video showed == the API's experiments.
    experiments_listed: int


class Storyboard(_Strict):
    slug: str = Field(pattern=r"^[0-9]{2}-[a-z0-9-]+$")
    title: str = Field(min_length=1, max_length=40)
    seed: Literal["demo"]
    seed_counts: SeedCounts
    end_state: EndState
    scenes: List[Scene] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_PLAIN = re.compile(r"^[A-Za-z0-9 ,.:;'’!?%()/&+-]+$")
_STEP_KEYS = {
    "click": Click,
    "move": Move,
    "type": Type,
    "look": Look,
    "scroll_to": ScrollTo,
    "wait_for": WaitFor,
    "url": WaitFor,
}


def _steps(raw: Any, where: str) -> List[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise StoryboardError(f"{where}: steps are a list")
    out = []
    for index, step in enumerate(raw):
        if not isinstance(step, dict) or not step:
            raise StoryboardError(f"{where} step {index + 1}: a step is a mapping")
        kinds = [key for key in step if key in _STEP_KEYS]
        if len(kinds) < 1:
            raise StoryboardError(
                f"{where} step {index + 1}: unknown step {sorted(step)}"
            )
        model = _STEP_KEYS[kinds[0]]
        try:
            out.append(model.model_validate(step, strict=False))
        except ValidationError as error:
            raise StoryboardError(f"{where} step {index + 1}: {error}") from None
    return out


def caption_problem(text: str) -> Optional[str]:
    """Why *text* cannot be a caption, or None."""
    if "{" in text or "}" in text:
        return "a caption is fixed text: no template"
    if not _PLAIN.match(text or ""):
        return "a caption is plain text (letters, digits and ordinary punctuation)"
    problems = contract.caption_problems(text)
    if problems:
        return "the caption " + "; ".join(problems)
    return None


def parse(data: Any, *, source: str = "storyboard") -> Storyboard:
    if not isinstance(data, dict):
        raise StoryboardError(f"{source}: the file is a mapping")
    data = json.loads(json.dumps(data))
    for s_index, scene in enumerate(data.get("scenes") or []):
        if not isinstance(scene, dict):
            raise StoryboardError(f"{source}: scene {s_index + 1} is a mapping")
        for b_index, beat in enumerate(scene.get("beats") or []):
            if not isinstance(beat, dict):
                raise StoryboardError(f"{source}: a beat is a mapping")
            where = f"{source} scene {scene.get('id')} beat {b_index + 1}"
            beat["before"] = _steps(beat.get("before"), where + " before")
            beat["steps"] = _steps(beat.get("steps"), where)
            beat["exit"] = _steps(beat.get("exit"), where + " exit")
    try:
        board = Storyboard.model_validate(data, strict=False)
    except ValidationError as error:
        raise StoryboardError(f"{source}: {error}") from None
    for scene in board.scenes:
        for index, beat in enumerate(scene.beats):
            where = f"{source} scene {scene.id} beat {index + 1}"
            problem = caption_problem(beat.cue)
            if problem:
                raise StoryboardError(f"{where}: {problem}")
            for step in [*beat.before, *beat.steps, *beat.exit]:
                _refuse_step(step, where)
    return board


def _refuse_step(step: Any, where: str) -> None:
    if isinstance(step, Type):
        if step.text in config.STATIC_NEEDLES and not step.secret:
            raise StoryboardError(
                f"{where}: types a credential into a field not marked secret"
            )
        if len(step.text) > 45:
            raise StoryboardError(f"{where}: types more than 45 characters")
    for locator in _locators(step):
        named = " ".join(
            str(v)
            for v in (locator.name, locator.text, locator.css, locator.testid)
            if v
        ).lower()
        if "api key" in named or "api-keys" in named or "api_keys" in named:
            raise StoryboardError(f"{where}: no step opens the API keys page")
    if isinstance(step, WaitFor) and step.url and "api-keys" in step.url:
        raise StoryboardError(f"{where}: no step opens the API keys page")


def _locators(step: Any) -> List[Locator]:
    for key in ("click", "move", "type", "look", "scroll_to", "wait_for"):
        value = getattr(step, key, None)
        if isinstance(value, Locator):
            return [value]
    return []


def load(path: Path) -> Storyboard:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise StoryboardError(f"{path.name}: {error}") from None
    board = parse(data, source=path.name)
    if path.stem != board.slug:
        raise StoryboardError(
            f"{path.name}: slug {board.slug!r} is not the file's name"
        )
    return board


# ---------------------------------------------------------------------------
# Pace and the cue list
# ---------------------------------------------------------------------------


def min_cue_ms(text: str) -> int:
    """How long the capture holds *text*: the contract's reading time, plus a margin
    so that rounding the cue's ends to frames never takes it under."""
    return contract.reading_time_ms(text) + config.CUE_MARGIN_MS


def compile_cues(board: Storyboard) -> List[Dict[str, Any]]:
    """The cue list in order: scene, beat, text, focus, minimum hold. Pure (gate 13a)."""
    cues = []
    for scene in board.scenes:
        for index, beat in enumerate(scene.beats):
            cues.append(
                {
                    "scene": scene.id,
                    "beat": index + 1,
                    "text": beat.cue,
                    "focus": beat.focus.describe(),
                    "min_ms": min_cue_ms(beat.cue)
                    + (config.PAYOFF_MS if beat.payoff else 0),
                    "payoff": beat.payoff,
                }
            )
    return cues


def cue_list_bytes(board: Storyboard) -> bytes:
    return json.dumps(compile_cues(board), sort_keys=True, ensure_ascii=False).encode()
