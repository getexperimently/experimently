"""The docs-defect issue form (QA plan UX D11.5): one measured defect of one
guide step per issue, in the shape the docs journeys report it.

``.github/ISSUE_TEMPLATE/docs_defect.yml`` is a GitHub issue form. Its title
and fields are D11.5's: the guide and its anchor at a commit, the step and its
heading, the sentence the guide says, what a reader sees, what was expected
before the run, which of the guide and the product is wrong, the steps to
reproduce, and the run. It carries the labels ``documentation`` and
``qa-agent``; ``launch-blocking`` or ``post-launch`` is chosen by the
walkthrough question, since a form cannot pick a label from an answer. The
form is public text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from backend.tests.unit.infrastructure.test_qa_templates_public_text import (
    BANNED_STEMS,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
FORM = REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "docs_defect.yml"

FIELDS = [
    ("input", "guide", "Guide"),
    ("input", "step", "Step"),
    ("textarea", "guide-says", "The guide says"),
    ("input", "reader-sees", "Following it, a reader sees"),
    ("input", "expected", "Expected (written before the run)"),
    ("dropdown", "which-is-wrong", "Which is wrong"),
    ("dropdown", "walkthrough", "Is the guide a launch walkthrough (R1-R8)?"),
    ("textarea", "reproduce", "Reproduce"),
    ("input", "run", "Run"),
]
#: The word stems kept out of public text (the QA templates' own list).
BANNED = re.compile("|".join(BANNED_STEMS), re.IGNORECASE)


def form():
    return yaml.safe_load(FORM.read_text(encoding="utf-8"))


def test_the_title_is_the_defect_line():
    assert form()["title"] == (
        'Docs: <guide title>, step <n> ("<heading>"): <what the reader cannot do>'
    )


def test_the_labels_are_documentation_and_qa_agent():
    assert form()["labels"] == ["documentation", "qa-agent"]


def test_the_fields_are_d11_5s_in_order_and_all_required():
    fields = [item for item in form()["body"] if item["type"] != "markdown"]
    assert [(f["type"], f["id"], f["attributes"]["label"]) for f in fields] == FIELDS
    assert all(f["validations"]["required"] is True for f in fields)


def test_the_choices_name_what_is_wrong_and_the_label_to_add():
    by_id = {item.get("id"): item for item in form()["body"]}
    assert by_id["which-is-wrong"]["attributes"]["options"] == [
        "The guide",
        "The product",
        "Undecided",
    ]
    options = by_id["walkthrough"]["attributes"]["options"]
    assert [o.split(", so ")[1] for o in options] == ["launch-blocking", "post-launch"]
    intro = form()["body"][0]["attributes"]["value"]
    for rule in ("two**", "One defect per issue", "launch-blocking", "post-launch"):
        assert rule in intro


def test_the_reproduction_names_the_compose_stack_and_a_commit():
    by_id = {item.get("id"): item for item in form()["body"]}
    assert by_id["reproduce"]["attributes"]["value"] == (
        "Follow steps 1-<n> of the guide on `docker compose up` at <commit>."
    )


def test_the_form_is_public_text():
    text = FORM.read_text(encoding="utf-8")
    assert not BANNED.search(text), BANNED.search(text)
    assert "Demo1234" not in text
