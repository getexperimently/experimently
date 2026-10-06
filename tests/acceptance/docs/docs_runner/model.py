"""The expectations file: one journey through one guide, written before the run.

Every model forbids unknown fields and coerces nothing (``extra="forbid"``,
``strict=True``), so a misspelt key or a quoted number is an error at load, not
a field silently ignored. ``loader`` adds the refusals that need more than one
file to decide (the guide's text and anchors, the inventory, the oracles).

A journey (this one walked the docs home page on docs-local, 2026-10-06; it
needs the inventory to classify ``README.md`` as the journey ``docs-site``,
without ``pending``)::

    guide: README.md                         # the nav path, as inventory.toml keys it
    stack: docs-local                        # compose-dev | docs-local | docs-published | marketing-local
    profile: core                            # core | full
    video: true
    written: 2026-10-06                      # the day the expectations were written
    steps:
      - id: home
        doc: start-here                      # an anchor of the guide
        do:
          goto: /
        expect:
          status: 200
          aria: |
            - heading "Experimently Documentation" [level=1]
        fail: the home page does not answer, or its heading is not the source's first heading
      - id: open-quick-start
        doc: start-here
        do:
          click: {role: link, name: Quick Start}
        expect:
          url: /getting-started/quick-start/
          aria: |
            - heading "Quick Start" [level=1]
        fail: the Quick Start link does not lead to the Quick Start page
      - id: deploy-guide
        doc: deployment-operations
        do:
          goto: /deployment/deployment-guide/
        expect:
          status: 200
        snapshot: false                      # no ARIA snapshot: say why
        snapshot_reason: only that the page answers matters here
        fail: the deployment guide does not answer
        not_run: needs-aws                   # a reason from registry.py; reported NOT RUN

``do`` is exactly one action. ``expect`` lists what must hold after it. A step
on a screen (``goto``, ``click``, ``fill``, ``select``) expects an ARIA snapshot
of the page, ``aria``, written before the run, beside any structural
expectation (``url``, ``status``, ``visible``, ``text``, ``number``); only
``snapshot: false`` with a one-line ``snapshot_reason`` drops it, and the step
then needs a structural expectation. ``aria`` is Playwright's ARIA snapshot
template: it must parse as a YAML list. ``api`` and ``ref`` steps take no
snapshot. ``fail`` says what failure looks like; a step without it is refused.
Names, labels, options, ``text`` and ``goto`` are one line each.
"""

from __future__ import annotations

import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

STACKS = ("compose-dev", "docs-local", "docs-published", "marketing-local")
Stack = Literal["compose-dev", "docs-local", "docs-published", "marketing-local"]
Profile = Literal["core", "full"]

#: Who an ``api`` step calls as: nobody, or one of the four role accounts the
#: stack provides (on compose-dev, the ``demo`` seed's accounts).
Caller = Literal["anonymous", "admin", "developer", "analyst", "viewer"]

#: The ARIA roles Playwright's ``get_by_role`` accepts (playwright 1.63.0).
Role = Literal[
    "alert",
    "alertdialog",
    "application",
    "article",
    "banner",
    "blockquote",
    "button",
    "caption",
    "cell",
    "checkbox",
    "code",
    "columnheader",
    "combobox",
    "complementary",
    "contentinfo",
    "definition",
    "deletion",
    "dialog",
    "directory",
    "document",
    "emphasis",
    "feed",
    "figure",
    "form",
    "generic",
    "grid",
    "gridcell",
    "group",
    "heading",
    "img",
    "insertion",
    "link",
    "list",
    "listbox",
    "listitem",
    "log",
    "main",
    "marquee",
    "math",
    "menu",
    "menubar",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "meter",
    "navigation",
    "none",
    "note",
    "option",
    "paragraph",
    "presentation",
    "progressbar",
    "radio",
    "radiogroup",
    "region",
    "row",
    "rowgroup",
    "rowheader",
    "scrollbar",
    "search",
    "searchbox",
    "separator",
    "slider",
    "spinbutton",
    "status",
    "strong",
    "subscript",
    "superscript",
    "switch",
    "tab",
    "table",
    "tablist",
    "tabpanel",
    "term",
    "textbox",
    "time",
    "timer",
    "toolbar",
    "tooltip",
    "tree",
    "treegrid",
    "treeitem",
]

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

#: The browser actions; ``api`` and ``ref`` are not on a screen.
BROWSER_ACTIONS = ("goto", "click", "fill", "select")
#: What a browser step may expect, and what an ``api`` step may.
BROWSER_EXPECTS = ("url", "status", "visible", "text", "number", "aria")
API_EXPECTS = ("status", "json")


def _one_line(value: str, what: str) -> str:
    if not value.strip() or "\n" in value.strip():
        raise ValueError(f"{what} must be one non-empty line")
    return value


def _single_line(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("must be one line")
    return value


#: A string a reader sees or types on one line: a name, a label, a path.
OneLine = Annotated[StrictStr, Field(min_length=1), AfterValidator(_single_line)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _Quoted(_Strict):
    """A name the reader is told to look for, so the guide must say it.

    ``quote: false`` exempts it from the check that the guide's text contains
    it, and then needs a one-line ``reason``.
    """

    quote: StrictBool = True
    reason: Optional[StrictStr] = None

    @model_validator(mode="after")
    def _reason_iff_unquoted(self) -> "_Quoted":
        if self.quote and self.reason is not None:
            raise ValueError("reason is only for quote: false")
        if not self.quote:
            if self.reason is None:
                raise ValueError("quote: false needs a one-line reason")
            _one_line(self.reason, "reason")
        return self


class Named(_Quoted):
    """An element found by its ARIA role and accessible name."""

    role: Role
    name: OneLine


class Fill(_Quoted):
    """Type ``value`` into the field labelled ``label``."""

    label: OneLine
    value: StrictStr


class Select(_Quoted):
    """Choose ``option`` in the select labelled ``label``."""

    label: OneLine
    option: OneLine


class Api(_Strict):
    """One HTTP request to the stack's API, as one of its accounts."""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: StrictStr = Field(pattern=r"^/\S*$")
    as_: Caller = Field(alias="as")
    body: Optional[Union[Dict[str, Any], List[Any]]] = None


class Do(_Strict):
    """Exactly one action."""

    goto: Optional[OneLine] = None
    click: Optional[Named] = None
    fill: Optional[Fill] = None
    select: Optional[Select] = None
    api: Optional[Api] = None
    ref: Optional[Literal["doc-examples"]] = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "Do":
        given = [name for name in type(self).model_fields if getattr(self, name)]
        if len(given) != 1:
            raise ValueError(
                "do must be exactly one of goto, click, fill, select, api, ref;"
                f" got {given or 'none'}"
            )
        return self

    @field_validator("goto")
    @classmethod
    def _goto_is_a_path(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and "://" in value:
            raise ValueError(
                "goto is a path on the stack (its base URL is the stack's), not a URL"
            )
        return value

    @property
    def kind(self) -> str:
        return next(name for name in type(self).model_fields if getattr(self, name))


Scalar = Union[StrictBool, StrictInt, StrictFloat, StrictStr]


class Oracle(_Strict):
    """A named function in ``docs_runner.oracles.ORACLES``, called with ``args``."""

    name: StrictStr = Field(min_length=1)
    args: Dict[str, Scalar] = Field(default_factory=dict)


class NumberExpect(_Strict):
    """The number shown in an element equals what an oracle computes."""

    locator: Named
    oracle: Oracle


class Expect(_Strict):
    """What must hold after the step; at least one entry."""

    url: Optional[StrictStr] = Field(default=None, pattern=r"^/\S*$")
    status: Optional[StrictInt] = Field(default=None, ge=100, le=599)
    visible: Optional[List[Named]] = Field(default=None, min_length=1)
    text: Optional[OneLine] = None
    json_: Optional[Dict[str, Any]] = Field(default=None, alias="json", min_length=1)
    number: Optional[NumberExpect] = None
    aria: Optional[StrictStr] = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _something(self) -> "Expect":
        if not self.given():
            raise ValueError("expect names nothing to check")
        return self

    @field_validator("aria")
    @classmethod
    def _aria_parses(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        try:
            nodes = yaml.safe_load(value)
        except yaml.YAMLError:
            nodes = None
        if not isinstance(nodes, list) or not nodes:
            raise ValueError(
                "aria must be an ARIA snapshot template: a non-empty YAML list of"
                ' nodes, such as - heading "Title" [level=1]'
            )
        return value

    def given(self) -> List[str]:
        """The entries set, by their names in the file."""
        names = []
        for name, field in type(self).model_fields.items():
            if getattr(self, name) is not None:
                names.append(field.alias or name)
        return names


class Step(_Strict):
    id: StrictStr = Field(pattern=SLUG_PATTERN)
    doc: StrictStr = Field(pattern=r"^[^#\s]+$")
    do: Do
    expect: Optional[Expect] = None
    fail: StrictStr
    snapshot: Optional[StrictBool] = None
    snapshot_reason: Optional[StrictStr] = None
    not_run: Optional[StrictStr] = None

    @field_validator("fail")
    @classmethod
    def _fail_one_line(cls, value: str) -> str:
        return _one_line(value, "fail")

    @model_validator(mode="after")
    def _snapshot_reason_iff_no_snapshot(self) -> "Step":
        if self.snapshot is False:
            if self.snapshot_reason is None:
                raise ValueError("snapshot: false needs a one-line snapshot_reason")
            _one_line(self.snapshot_reason, "snapshot_reason")
        elif self.snapshot_reason is not None:
            raise ValueError("snapshot_reason is only for snapshot: false")
        return self

    @property
    def in_browser(self) -> bool:
        return self.do.kind in BROWSER_ACTIONS

    @property
    def takes_screenshot(self) -> bool:
        return self.in_browser and self.snapshot is not False


class Journey(_Strict):
    guide: StrictStr = Field(pattern=r"^[^/\s][^\s]*\.md$")
    stack: Stack
    profile: Profile
    video: StrictBool
    written: datetime.date
    steps: List[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_step_ids(self) -> "Journey":
        seen = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"step id {step.id!r} is used twice")
            seen.add(step.id)
        return self
