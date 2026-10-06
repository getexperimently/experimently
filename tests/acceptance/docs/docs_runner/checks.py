"""What a step's log line says, and the comparisons a step makes, without a browser.

Kept apart from ``execute`` (which imports Playwright) so the unit job can test
them: how an action and an expectation are written in the log, how a failure is
cut to one line, and how a JSON value and a shown number are compared.
"""

from __future__ import annotations

import json
import re
from typing import Any, List

from docs_runner.model import SEARCH_TOP, Step

OBSERVED_CHARS = 300
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+")


class StepFailed(AssertionError):
    """The step did not do what the journey expects; the message says what was seen."""


def one_line(text: str, limit: int = OBSERVED_CHARS) -> str:
    """The first lines of an error, before Playwright's call log, on one line."""
    kept = []
    for line in str(text).splitlines():
        if line.strip().lower().startswith("call log"):
            break
        if line.strip():
            kept.append(line.strip())
    flat = "; ".join(kept)
    flat = re.sub(r"\s+", " ", flat)
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def describe_action(step: Step) -> str:
    do = step.do
    if do.goto is not None:
        return f"open {do.goto}"
    if do.click is not None:
        return f'click the {do.click.role} "{do.click.name}"'
    if do.fill is not None:
        return f'fill "{do.fill.label}"'
    if do.select is not None:
        return f'choose "{do.select.option}" in "{do.select.label}"'
    if do.api is not None:
        return f"{do.api.method} {do.api.path} as {do.api.as_}"
    if do.search is not None:
        return f'search the site for "{do.search}"'
    if do.crawl == "nav":
        return "open every page of the nav on the site"
    if do.crawl == "links":
        return "follow every link to the site from the nav pages and their source"
    return "its shell blocks, run by Doc Examples"


#: What each crawl expects; the action itself is the check.
CRAWL_EXPECTS = {
    "nav": (
        "every nav page of the source answers 2xx on the site, and its first-level"
        " heading is the source page's first # heading"
    ),
    "links": (
        "every link to the site on the nav pages, and every absolute link to the site"
        " in their source, answers 2xx, redirected only within the site"
    ),
}


def describe_expect(step: Step) -> str:
    if step.do.crawl is not None:
        return CRAWL_EXPECTS[step.do.crawl]
    expect_ = step.expect
    if expect_ is None:
        return "Doc Examples runs this section's blocks"
    parts: List[str] = []
    if expect_.url is not None:
        parts.append(f"at {expect_.url}")
    if expect_.status is not None:
        parts.append(f"status {expect_.status}")
    for named in expect_.visible or []:
        parts.append(f'{named.role} "{named.name}" visible')
    if expect_.text is not None:
        parts.append(f'text "{expect_.text}"')
    for path, value in (expect_.json_ or {}).items():
        parts.append(f"json {path} = {json.dumps(value)}")
    if expect_.number is not None:
        number = expect_.number
        args = ", ".join(f"{k}={v}" for k, v in number.oracle.args.items())
        parts.append(
            f'the number in {number.locator.role} "{number.locator.name}" equals'
            f" {number.oracle.name}({args})"
        )
    if expect_.found is not None:
        parts.append(f"{expect_.found} among the first {SEARCH_TOP} results")
    if expect_.aria is not None:
        parts.append(
            f"the screen matches its ARIA snapshot ({len(expect_.aria.splitlines())} lines)"
        )
    return "; ".join(parts)


def json_at(document: Any, path: str) -> Any:
    """The value at a dotted *path* (``items.0.key``); KeyError when absent."""
    node = document
    for part in path.split("."):
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError(path)
    return node


def same_json(seen: Any, wanted: Any) -> bool:
    """Equal as JSON values: ``true`` is not ``1``, as it would be in Python."""
    if isinstance(seen, bool) or isinstance(wanted, bool):
        return isinstance(seen, bool) and isinstance(wanted, bool) and seen == wanted
    return seen == wanted


def parse_number(text: str) -> float:
    match = NUMBER.search(text)
    if match is None:
        raise StepFailed(f"no number in {one_line(text, 80)!r}")
    return float(match.group(0).replace(",", ""))
