"""Read one journey file, and refuse what the runner will not run.

``load`` returns a ``Journey`` or raises ``Refused`` with every problem found,
each one line naming the step. Refused, besides what ``model`` refuses:

* a CSS or XPath selector, anywhere a role, name or label goes, or under a key
  of its own (``selector``, ``css``, ``xpath``, a string ``locator``): elements
  are found by role and accessible name, as a reader finds them;
* a sleep (``sleep``, ``wait``, ``delay``, ``pause``, ...): a step waits for
  what it expects, never for a time;
* a step without ``fail``: what failure looks like is written before the run;
* an unknown stack;
* a ``guide`` the inventory does not classify ``journey`` with this file's
  name as its id, or classifies ``pending = true``;
* a ``doc`` anchor the guide does not have;
* an accessible name or label the guide's text does not contain, unless it says
  ``quote: false`` with a reason, so a label renamed in the UI or in the guide
  alone fails;
* a step in a browser with no ``aria`` and no structural expectation (``url``,
  ``status``, ``visible``, ``text``, ``number``), an ``api`` step with neither
  ``status`` nor ``json``, and an expectation the step's kind cannot have;
* ``ref: doc-examples`` on a section with no shell block Doc Examples runs, or
  on a guide ``scripts/doc_examples.toml`` does not enrol;
* an ``api`` step on a stack with no API (every stack but compose-dev);
* an oracle not in ``docs_runner.oracles.ORACLES``;
* a ``not_run`` reason the registry does not let a journey declare;
* a ``written`` date after today.
"""

from __future__ import annotations

import datetime
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

import yaml
from pydantic import ValidationError

from docs_runner import guide as guides
from docs_runner import registry
from docs_runner.model import (
    API_EXPECTS,
    BROWSER_EXPECTS,
    STACKS,
    Journey,
    Step,
)

#: Keys that would make a step wait for a time instead of for what it expects.
SLEEP_KEYS = frozenset(
    {
        "sleep",
        "wait",
        "wait_for",
        "wait_for_timeout",
        "wait_ms",
        "wait_seconds",
        "delay",
        "pause",
    }
)
#: Keys that would carry a selector rather than a role and a name.
SELECTOR_KEYS = frozenset({"selector", "css", "xpath"})
#: The keys whose string values name an element.
NAME_KEYS = frozenset({"role", "name", "label", "option", "locator"})

_SELECTOR_SHAPES = (
    re.compile(r"^(css|xpath|text|id|role|nth|data-testid|data-test-id)\s*="),
    re.compile(r"^\(?\s*\.{0,2}//"),  # XPath: //div, (//a)[1], .//span
    re.compile(r">>"),  # Playwright selector chaining
    re.compile(r"^[#.][A-Za-z_][\w-]*$"),  # #submit, .btn-primary
    re.compile(r"^[a-z][a-z0-9]*(?:[#.][\w-]+)+$"),  # button#go, div.card
    re.compile(r"^[a-z][a-z0-9-]*\s*\[[^\]]+\]"),  # input[name="email"]
    re.compile(r"^[a-z][a-z0-9]*\s*>\s*[a-z]"),  # form > button
    re.compile(r":nth-(child|of-type)\(|:has\(|:is\("),
)


def looks_like_selector(value: str) -> bool:
    text = value.strip()
    return any(shape.search(text) for shape in _SELECTOR_SHAPES)


class Refused(Exception):
    """The journey file will not be run; ``problems`` says why, one line each."""

    def __init__(self, path: str, problems: List[str]):
        self.path = path
        self.problems = problems
        super().__init__(f"{path}: refused\n" + "\n".join(f"  - {p}" for p in problems))


@dataclass(frozen=True)
class Context:
    """What a journey is checked against, besides its own file."""

    docs_root: Path
    inventory: Mapping[str, Any]
    #: ``scripts/doc_examples.toml``'s exec-block count per page under docs/.
    doc_examples: Mapping[str, int]
    oracles: Mapping[str, Callable[..., float]]
    today: datetime.date


def read_inventory(path: Path) -> Dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def read_doc_examples(path: Path) -> Dict[str, int]:
    """Each page under docs/ that ``doc_examples.toml`` enrols, with its exec count."""
    counts: Dict[str, int] = {}
    for document in tomllib.loads(path.read_text(encoding="utf-8")).get("document", []):
        page = document["path"]
        if page.startswith("docs/"):
            counts[page[len("docs/") :]] = int(document.get("exec", 0))
    return counts


def context_for(repo_root: Path, today: Optional[datetime.date] = None) -> Context:
    """The real tree's context: docs/, the inventory, Doc Examples, the oracles."""
    from docs_runner.oracles import ORACLES

    here = repo_root / "tests" / "acceptance" / "docs"
    return Context(
        docs_root=repo_root / "docs",
        inventory=read_inventory(here / "inventory.toml"),
        doc_examples=read_doc_examples(repo_root / "scripts" / "doc_examples.toml"),
        oracles=ORACLES,
        today=today or datetime.datetime.now(datetime.timezone.utc).date(),
    )


# ---------------------------------------------------------------------------
# Refusals on the raw file, before the model: each has a message of its own
# ---------------------------------------------------------------------------
def _walk(node: Any, where: str) -> Iterable[tuple]:
    """Every (where, key, value) in a nested mapping/list."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield where, key, value
            yield from _walk(value, f"{where}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{where}[{index}]")


def _step_label(index: int, step: Any) -> str:
    if isinstance(step, dict) and isinstance(step.get("id"), str):
        return f"step {index + 1} ({step['id']})"
    return f"step {index + 1}"


def raw_problems(data: Any) -> List[str]:
    """Refusals that need only the parsed YAML."""
    if not isinstance(data, dict):
        return ["the file is not a mapping"]
    found: List[str] = []
    stack = data.get("stack")
    if stack is not None and stack not in STACKS:
        found.append(f"unknown stack {stack!r}; a stack is one of {', '.join(STACKS)}")
    steps = data.get("steps")
    if not isinstance(steps, list):
        return found
    for index, step in enumerate(steps):
        label = _step_label(index, step)
        if not isinstance(step, dict):
            continue
        if False:
            found.append(
                f"{label}: no fail; write what failure looks like before the run"
            )
        for where, key, value in _walk(step, label):
            key_text = str(key).lower()
            if key_text in SLEEP_KEYS:
                found.append(
                    f"{where}: {key} is a sleep; a step waits for what it expects,"
                    " never for a time"
                )
            if key_text in SELECTOR_KEYS or (
                key_text == "locator" and isinstance(value, str)
            ):
                found.append(
                    f"{where}: {key} is a CSS or XPath selector; find the element"
                    " by role and name"
                )
            elif key_text in NAME_KEYS and isinstance(value, str):
                if looks_like_selector(value):
                    found.append(
                        f"{where}.{key}: {value!r} is a CSS or XPath selector;"
                        " give the role and accessible name a reader sees"
                    )
    return found


def _model_problems(error: ValidationError, data: Dict[str, Any]) -> List[str]:
    """Pydantic's errors, each placed as ``step N (id).field`` and kept short."""
    steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    found = []
    for item in error.errors():
        loc = list(item["loc"])
        if len(loc) >= 2 and loc[0] == "steps" and isinstance(loc[1], int):
            label = _step_label(loc[1], steps[loc[1]] if loc[1] < len(steps) else None)
            loc = [label, *loc[2:]]
        where = ".".join(str(part) for part in loc) or "journey"
        if item["type"] == "literal_error":
            message = f"{item['input']!r} is not one of the values allowed here"
        else:
            message = item["msg"].removeprefix("Value error, ")
        found.append(f"{where}: {message}")
    return found


# ---------------------------------------------------------------------------
# Refusals that need the guide, the inventory and the registry
# ---------------------------------------------------------------------------
def _quoted_names(step: Step) -> List[tuple]:
    """(what, name, quote) for every name or label the step asks a reader to find."""
    names: List[tuple] = []
    do = step.do
    if do.click is not None:
        names.append(("click.name", do.click.name, do.click.quote))
    if do.fill is not None:
        names.append(("fill.label", do.fill.label, do.fill.quote))
    if do.select is not None:
        names.append(("select.label", do.select.label, do.select.quote))
    expect = step.expect
    if expect is not None:
        for index, named in enumerate(expect.visible or []):
            names.append((f"expect.visible[{index}].name", named.name, named.quote))
        if expect.number is not None:
            locator = expect.number.locator
            names.append(("expect.number.locator.name", locator.name, locator.quote))
    return names


def _expect_problems(label: str, step: Step, stack: str) -> List[str]:
    found: List[str] = []
    kind = step.do.kind
    given = step.expect.given() if step.expect is not None else []
    if kind == "ref":
        if given:
            found.append(
                f"{label}: ref: doc-examples is checked by Doc Examples; it has no"
                " expect here"
            )
        if step.snapshot:
            found.append(f"{label}: ref: doc-examples has no screen to snapshot")
        return found
    if kind == "api":
        if stack != "compose-dev":
            found.append(
                f"{label}: an api step needs a stack with an API; {stack} has none"
            )
        wrong = [name for name in given if name not in API_EXPECTS]
        if wrong:
            found.append(
                f"{label}: an api step expects only status or json, not {wrong}"
            )
        if not [name for name in given if name in API_EXPECTS]:
            found.append(f"{label}: an api step needs status or json in expect")
        if step.snapshot:
            found.append(f"{label}: an api step has no screen to snapshot")
        return found
    wrong = [name for name in given if name not in BROWSER_EXPECTS]
    if wrong:
        found.append(f"{label}: a step in a browser cannot expect {wrong}")
    if not [name for name in given if name in BROWSER_EXPECTS]:
        found.append(
            f"{label}: a step on one screen needs an aria snapshot or a structural"
            " expect (url, status, visible, text, number)"
        )
    if "status" in given and kind != "goto":
        found.append(f"{label}: status is the answer to a goto; {kind} has none")
    return found


def semantic_problems(journey: Journey, stem: str, context: Context) -> List[str]:
    found: List[str] = []
    pages = context.inventory.get("pages", {})
    entry = pages.get(journey.guide)
    if entry is None:
        found.append(f"guide {journey.guide!r} is not a page in inventory.toml")
    elif entry.get("class") != "journey":
        found.append(
            f"guide {journey.guide!r} is classified {entry.get('class')!r} in"
            " inventory.toml, not journey"
        )
    elif entry.get("journey") != stem:
        found.append(
            f"inventory.toml names {entry.get('journey')!r} as the journey of"
            f" {journey.guide!r}, not {stem!r}"
        )
    elif entry.get("pending") is True:
        found.append(
            f"journey {stem!r} is pending = true in inventory.toml; a pending"
            " journey is not run"
        )

    if journey.written > context.today:
        found.append(f"written {journey.written} is after today ({context.today})")

    guide_file = context.docs_root / journey.guide
    if not guide_file.is_file():
        found.append(f"guide {journey.guide!r} is not a file under docs/")
        return found
    guide = guides.load(context.docs_root, journey.guide)
    anchors = guide.anchors

    for index, step in enumerate(journey.steps):
        label = f"step {index + 1} ({step.id})"
        if step.doc not in anchors:
            found.append(f"{label}: the guide has no anchor #{step.doc}")
        for what, name, quote in _quoted_names(step):
            if quote and not guide.contains(name):
                found.append(
                    f"{label}: {what} {name!r} is not in the guide's text; quote what"
                    " the guide says, or give quote: false and a reason"
                )
        found.extend(_expect_problems(label, step, journey.stack))
        if step.not_run is not None and not registry.is_declarable(step.not_run):
            found.append(
                f"{label}: not_run {step.not_run!r} is not a reason a journey may"
                " give (needs-aws, needs-founder-account, waived #<issue>)"
            )
        if step.do.kind == "ref":
            if context.doc_examples.get(journey.guide, 0) < 1:
                found.append(
                    f"{label}: ref: doc-examples, but scripts/doc_examples.toml"
                    f" enrols no exec block of {journey.guide}"
                )
            elif step.doc in anchors and not guide.has_exec_block(step.doc):
                found.append(
                    f"{label}: ref: doc-examples, but the section #{step.doc} has no"
                    " {.bash exec} block"
                )
        if step.expect is not None and step.expect.number is not None:
            oracle = step.expect.number.oracle.name
            if oracle not in context.oracles:
                found.append(f"{label}: no oracle named {oracle!r}")
    return found


def load(path: Path, context: Context) -> Journey:
    """The journey in *path*, or ``Refused`` with every problem found."""
    shown = path.name
    stem = path.stem
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise Refused(shown, [f"not YAML: {error}".splitlines()[0]]) from None
    problems = raw_problems(data)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", stem):
        problems.append(f"the file name {stem!r} is not a lower-case slug")
    if problems:
        raise Refused(shown, problems)
    try:
        journey = Journey.model_validate(data)
    except ValidationError as error:
        raise Refused(shown, _model_problems(error, data)) from None
    problems = semantic_problems(journey, stem, context)
    if problems:
        raise Refused(shown, problems)
    return journey
