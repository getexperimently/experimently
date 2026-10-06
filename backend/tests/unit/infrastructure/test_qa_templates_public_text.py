"""The QA alerts and summaries say what to do, and stay safe to publish.

``.github/qa-templates/`` holds the fixed wording of every issue, comment and
step summary the automated QA workflows post, one ``.tmpl`` file each: the
synthetic staging check, API fuzzing and the docs journeys (QA plan, UX D1-D3,
D9, D11.2, D11.5). This
repository is public, so each of those is public the moment it is posted, and
an edit afterwards does not recall the notification e-mail. The rules are
therefore checked on the template, before anything is posted:

* placeholders are only the names in ``PLACEHOLDERS``, whose kinds are the ones
  the plan allows in public text (UX check V1); no other brace, no dollar sign
  (a shell, ``envsubst`` or a workflow expression would expand it), no angle
  brackets, no printf-style placeholder;
* no e-mail address outside ``@example.com``, no ``@`` mention, no UUID, no
  long number, nothing shaped like a key, token or credential header, no fenced
  block, no URL or hostname other than this repository's and its docs site's,
  and none of the words the project keeps out of automated public text
  (UX D9, check V2);
* the first two lines carry a verdict word and either "What to do" or a count;
  an output that is not green says "What to do" there (UX check V7). For an
  issue the title carries the verdict and the body's first two lines the rest;
* each template's placeholders are pinned, title and body separately, so a
  docs-defect issue cannot lose its step number (UX check V11), and the
  synthetic issue names all eight steps.

Every refusal is also planted against a real template in ``PLANTS`` below, so
a rule that stops firing fails here, not only when a template breaks it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATES_DIR = REPO_ROOT / ".github" / "qa-templates"
README = "README.md"

#: Every placeholder name, by the kind of value it holds. The kinds are exactly
#: the ones the QA plan allows in public text (UX check V1): date, commit, run
#: link, check name, step, HTTP status, count, seed, duration, and for the docs
#: runs the guide path, step number and heading. A name starts with its kind;
#: the suffix only tells two values of one kind apart in one template.
PLACEHOLDERS: Dict[str, Tuple[str, ...]] = {
    "date": ("date", "date_time"),
    "sha": ("sha",),
    "run_link": ("run_link",),
    "check": ("check",),
    "step": ("step",),
    "status": ("status",),
    "count": (
        "count_runs",
        "count_fuzzed",
        "count_operations",
        "count_5xx",
        "count_5xx_unlisted",
        "count_known_quiet",
        "count_reached",
        "count_unreached",
        "count_unreached_unlisted",
        "count_unreached_stale",
        "count_pass",
        "count_fail",
        "count_partial",
        "count_nav",
        "count_not_covered",
        "count_steps",
        "count_steps_pass",
        "count_not_run",
    ),
    "seed": ("seed",),
    "duration": ("duration",),
    "guide_path": ("guide_path",),
    "step_number": ("step_number",),
    "heading": ("heading_guide", "heading_step"),
}
ALLOWED = frozenset(name for names in PLACEHOLDERS.values() for name in names)

_FUZZ_RED = frozenset(
    {
        "check",
        "date",
        "sha",
        "seed",
        "count_fuzzed",
        "count_operations",
        "count_5xx",
        "count_5xx_unlisted",
        "count_known_quiet",
        "count_reached",
        "count_unreached_unlisted",
        "count_unreached_stale",
        "run_link",
    }
)
_DOCS_RUN = frozenset(
    {
        "date",
        "sha",
        "count_pass",
        "count_fail",
        "count_partial",
        "count_nav",
        "count_not_covered",
    }
)

#: Every template and its placeholders, as (title, body). Only an
#: ``-issue.tmpl`` file has a title (its first line); the others have None. A
#: renderer can rely on this set: it is exactly what it must supply.
TEMPLATES: Dict[str, Tuple[Optional[FrozenSet[str]], FrozenSet[str]]] = {
    "synthetic-issue.tmpl": (
        frozenset({"check"}),
        frozenset({"check", "count_runs", "date_time", "run_link", "step", "status"}),
    ),
    "synthetic-step-changed.tmpl": (
        None,
        frozenset({"check", "step", "status", "run_link", "count_runs"}),
    ),
    "synthetic-recovered.tmpl": (
        None,
        frozenset({"date_time", "count_runs", "duration", "run_link"}),
    ),
    "fuzz-green.tmpl": (
        None,
        frozenset(
            {
                "check",
                "date",
                "sha",
                "seed",
                "count_fuzzed",
                "count_operations",
                "count_5xx",
                "count_reached",
                "count_unreached",
            }
        ),
    ),
    "fuzz-red.tmpl": (None, _FUZZ_RED),
    "fuzz-issue.tmpl": (frozenset(), _FUZZ_RED),
    "docs-run-green.tmpl": (None, _DOCS_RUN),
    "docs-run-red.tmpl": (None, _DOCS_RUN | {"run_link"}),
    "docs-guide-pass.tmpl": (
        None,
        frozenset({"heading_guide", "guide_path", "date", "sha", "count_steps"}),
    ),
    "docs-guide-fail.tmpl": (
        None,
        frozenset(
            {
                "heading_guide",
                "guide_path",
                "date",
                "sha",
                "step_number",
                "heading_step",
                "count_steps_pass",
                "count_steps",
            }
        ),
    ),
    "docs-guide-partial.tmpl": (
        None,
        frozenset(
            {
                "heading_guide",
                "guide_path",
                "date",
                "sha",
                "count_not_run",
                "count_steps_pass",
                "count_steps",
            }
        ),
    ),
    "docs-defect-issue.tmpl": (
        frozenset({"heading_guide", "step_number", "heading_step"}),
        frozenset(
            {
                "step_number",
                "guide_path",
                "count_runs",
                "sha",
                "run_link",
                "heading_step",
            }
        ),
    ),
}

#: The labels the workflows create on first use; the README documents each.
LABELS = ("synthetic-failure", "fuzz-failure", "docs-journey-failure", "qa-agent")

#: The synthetic check's steps, in order (QA plan v1.1, section S).
SYNTHETIC_STEPS = [
    "Ready",
    "Sign in",
    "Key expiry",
    "Results before",
    "Assign",
    "Track",
    "Evaluate",
    "Results after",
]

# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------

PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")

#: Word stems the project keeps out of automated public text, matched
#: case-insensitively anywhere in a word.
BANNED_STEMS = (
    "security",
    "vulnerab",
    "attack",
    "exploit",
    "inject",
    "enumerat",
    "leak",
    "disclos",
    "exposure",
    "privilege",
    "escalat",
    "internal",
    "echo",
    "bypass",
)

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
MENTION = re.compile(r"(?<![A-Za-z0-9._%+-])@[A-Za-z0-9]")
UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
LONG_NUMBER = re.compile(r"[0-9]{7,}")
CREDENTIAL_SHAPES = (
    ("an API key prefix", re.compile(r"eptk", re.I)),
    ("a live or test key prefix", re.compile(r"\b[a-z]{2,4}_(?:live|test)_", re.I)),
    ("an AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{12,}")),
    ("a GitHub token", re.compile(r"\b(?:gh[pousr]_|github_pat_)")),
    ("a JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}")),
    ("a bearer credential", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")),
    (
        "a credential header",
        re.compile(r"\b(?:authorization|cookie|set-cookie|x-api-key)\s*:", re.I),
    ),
)
FENCE = re.compile(r"^\s*(?:```|~~~)", re.M)
URL = re.compile(r"https?://[^\s)\]]+")
ALLOWED_URL_PREFIXES = (
    "https://github.com/getexperimently/experimently/",
    "https://getexperimently.github.io/experimently/",
)
HOST = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|io|net|org|dev|app|cloud|ai|co)\b", re.I
)
ALLOWED_HOSTS = {"github.com", "getexperimently.github.io", "example.com"}

#: Verdict words, case-sensitive: "pass" in "superuser pass" is not one.
VERDICT = re.compile(r"\b(GREEN|RED|PASS|FAIL|PARTIAL|Green|red|failed|fails)\b")
GREEN_VERDICTS = {"GREEN", "PASS", "Green"}
WHAT_TO_DO = "What to do"
COUNT = re.compile(r"\{count(?:_[a-z0-9_]+)?\}")


def syntax_problems(text: str) -> List[str]:
    """Placeholders outside the allowed names, and every other way to template."""
    found = [
        f"placeholder {{{name}}} is not one the QA plan allows"
        for name in sorted(set(PLACEHOLDER.findall(text)) - ALLOWED)
    ]
    rest = PLACEHOLDER.sub("", text)
    if "{" in rest or "}" in rest:
        found.append("a brace that is not a placeholder")
    if "$" in text:
        found.append(
            "a dollar sign: a shell, envsubst or a workflow expression would expand it"
        )
    if "<" in text or ">" in text:
        found.append(
            "angle brackets: an HTML tag hides text, and <name> is no placeholder"
        )
    if re.search(r"%\(|%[sdr]\b", text):
        found.append("a printf-style placeholder")
    return found


def shape_problems(text: str) -> List[str]:
    """What never goes in public text (UX D9), and the words kept out of it."""
    found = []
    lowered = text.lower()
    found += [f"the word stem {stem!r}" for stem in BANNED_STEMS if stem in lowered]
    for match in EMAIL.finditer(text):
        if match.group(1).lower() != "example.com":
            found.append(f"an e-mail address outside @example.com: {match.group(0)}")
    if MENTION.search(text):
        found.append("an @ mention")
    if UUID.search(text):
        found.append("a UUID: ids never go in public text")
    if LONG_NUMBER.search(text):
        found.append("a run of seven or more digits: an id belongs in a placeholder")
    found += [label for label, shape in CREDENTIAL_SHAPES if shape.search(text)]
    if FENCE.search(text):
        found.append("a fenced block: that is where a pasted body goes")
    for url in URL.findall(text):
        url = url.rstrip(".,;:")
        if not url.startswith(ALLOWED_URL_PREFIXES):
            found.append(f"a URL outside this repository and its docs site: {url}")
    for match in HOST.finditer(URL.sub("", text)):
        if match.group(0).lower() not in ALLOWED_HOSTS:
            found.append(f"a hostname: {match.group(0)}")
    return found


def split_issue(name: str, text: str) -> Tuple[Optional[str], str, List[str]]:
    """(title, body, layout problems); a non-issue template has no title."""
    if not name.endswith("-issue.tmpl"):
        return None, text, []
    lines = text.split("\n")
    if len(lines) < 3 or not lines[0].strip() or lines[1] != "":
        return (
            None,
            text,
            ["an issue template is its title, a blank line, then the body"],
        )
    return lines[0], "\n".join(lines[2:]), []


def opening_problems(text: str) -> List[str]:
    """The two-line rule (UX check V7) on the first two non-blank lines."""
    head = "\n".join([line for line in text.splitlines() if line.strip()][:2])
    verdicts = VERDICT.findall(head)
    found = []
    if not verdicts:
        found.append(
            "no verdict word (GREEN, RED, PASS, FAIL, ...) in the first two lines"
        )
    if WHAT_TO_DO not in head and not COUNT.search(head):
        found.append('neither "What to do" nor a count in the first two lines')
    if verdicts and verdicts[0] not in GREEN_VERDICTS and WHAT_TO_DO not in head:
        found.append('not green, and "What to do" is not in the first two lines')
    return found


def problems(name: str, text: str) -> List[str]:
    """Everything wrong with one template."""
    found = syntax_problems(text) + shape_problems(text)
    title, body, layout = split_issue(name, text)
    found += layout
    if title is not None and not VERDICT.search(title):
        found.append("the issue title has no verdict word")
    found += opening_problems(body)
    return found


def read(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


def placeholders(text: Optional[str]) -> Optional[FrozenSet[str]]:
    return None if text is None else frozenset(PLACEHOLDER.findall(text))


# ---------------------------------------------------------------------------
# The templates in this tree
# ---------------------------------------------------------------------------


def test_the_directory_holds_exactly_the_pinned_templates():
    """A template the test does not list would be posted unchecked; a missing
    one would make the parametrised checks below pass over nothing."""
    assert TEMPLATES_DIR.is_dir(), f"{TEMPLATES_DIR} is missing"
    present = sorted(path.name for path in TEMPLATES_DIR.iterdir())
    assert present == sorted([*TEMPLATES, README])


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_the_template_is_safe_to_publish(name):
    found = problems(name, read(name))
    assert not found, f"{name}:\n  " + "\n  ".join(found)


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_the_template_uses_exactly_its_placeholders(name):
    title, body, _ = split_issue(name, read(name))
    assert (placeholders(title), placeholders(body)) == TEMPLATES[name]


def test_every_placeholder_kind_is_one_the_plan_allows():
    assert set(PLACEHOLDERS) == {
        "date",
        "sha",
        "run_link",
        "check",
        "step",
        "status",
        "count",
        "seed",
        "duration",
        "guide_path",
        "step_number",
        "heading",
    }
    for kind, names in PLACEHOLDERS.items():
        for name in names:
            assert name == kind or name.startswith(kind + "_"), (kind, name)
            assert PLACEHOLDER.fullmatch("{" + name + "}"), name


def test_the_readme_is_safe_to_publish_and_documents_every_name_and_label():
    text = read(README)
    assert shape_problems(text) == []
    missing = [name for name in sorted(ALLOWED) if f"`{{{name}}}`" not in text]
    missing += [label for label in LABELS if f"`{label}`" not in text]
    assert not missing, f"not in {README}: {missing}"


def test_the_synthetic_issue_lists_the_eight_steps_in_order():
    _, body, _ = split_issue("synthetic-issue.tmpl", read("synthetic-issue.tmpl"))
    listed = re.findall(r"^([0-9]+)\. ([A-Z][a-z]+(?: [a-z]+)*):", body, re.M)
    assert listed == [(str(n), step) for n, step in enumerate(SYNTHETIC_STEPS, 1)]


def test_the_fuzz_issue_body_is_the_red_summary():
    title, body, _ = split_issue("fuzz-issue.tmpl", read("fuzz-issue.tmpl"))
    assert title == "API fuzzing is red"
    assert body == read("fuzz-red.tmpl")


# ---------------------------------------------------------------------------
# Each rule fires: a defect planted against a real template
# ---------------------------------------------------------------------------


def _add(line: str) -> Callable[[str], str]:
    return lambda text: text + "\n" + line + "\n"


def _move_what_to_do_down(text: str) -> str:
    """The "What to do" paragraph swapped with the one after it."""
    paragraphs = text.split("\n\n")
    index = next(i for i, p in enumerate(paragraphs) if p.startswith(WHAT_TO_DO))
    paragraphs[index], paragraphs[index + 1] = paragraphs[index + 1], paragraphs[index]
    return "\n\n".join(paragraphs)


def _replace(old: str, new: str) -> Callable[[str], str]:
    def plant(text: str) -> str:
        assert old in text, f"the plant's anchor {old!r} is gone"
        return text.replace(old, new)

    return plant


#: (id, template, plant, a fragment the problems must contain)
PLANTS = [
    (
        "workflow-expression",
        "synthetic-issue.tmpl",
        _add("Base URL: ${{ vars.PUBLIC_BASE_URL }}"),
        "dollar sign",
    ),
    ("real-e-mail", "synthetic-issue.tmpl", _add("Ask user@realdomain.io."), "e-mail"),
    ("what-to-do-moved", "synthetic-issue.tmpl", _move_what_to_do_down, WHAT_TO_DO),
    ("unknown-placeholder", "fuzz-red.tmpl", _add("Body: {response_body}"), "not one"),
    ("stray-brace", "fuzz-red.tmpl", _add('Body: {"assigned": true}'), "brace"),
    ("angle-placeholder", "docs-run-red.tmpl", _add("Experiment: <id>"), "angle"),
    ("printf", "docs-run-red.tmpl", _add("User: %(user)s"), "printf"),
    ("mention", "synthetic-recovered.tmpl", _add("cc @someone"), "mention"),
    (
        "uuid",
        "synthetic-recovered.tmpl",
        _add("Experiment 123e4567-e89b-12d3-a456-426614174000"),
        "UUID",
    ),
    ("long-number", "synthetic-recovered.tmpl", _add("User 12345678"), "digits"),
    (
        "api-key",
        "fuzz-green.tmpl",
        _add("Key: " + "ep" + "tk_" + "0" * 32),
        "API key prefix",
    ),
    ("key-prefix", "fuzz-green.tmpl", _add("sk" + "_live_" + "x"), "key prefix"),
    ("aws-key", "fuzz-green.tmpl", _add("AK" + "IA" + "X" * 16), "AWS"),
    ("github-token", "fuzz-green.tmpl", _add("gh" + "p_" + "x" * 8), "GitHub"),
    ("jwt", "fuzz-green.tmpl", _add("ey" + "J" + "x" * 20), "JSON web token"),
    ("bearer", "docs-guide-fail.tmpl", _add("Bearer " + "x" * 20), "bearer"),
    ("header", "docs-guide-fail.tmpl", _add("X-API-Key: x"), "header"),
    ("fence", "docs-guide-pass.tmpl", _add("```\nok\n```"), "fenced"),
    ("other-url", "docs-defect-issue.tmpl", _add("See https://example.net/x"), "URL"),
    ("hostname", "docs-defect-issue.tmpl", _add("On staging.example.net"), "hostname"),
    (
        "title-without-verdict",
        "synthetic-issue.tmpl",
        _replace("Synthetic check ({check}) is red\n", "Synthetic check ({check})\n"),
        "title",
    ),
    (
        "issue-without-blank-line",
        "docs-defect-issue.tmpl",
        _replace(" fails as written\n\n", " fails as written\n"),
        "blank line",
    ),
    (
        "no-verdict",
        "fuzz-green.tmpl",
        _replace("commit {sha}: GREEN", "commit {sha}"),
        "verdict",
    ),
    (
        "no-count-and-no-what-to-do",
        "docs-guide-pass.tmpl",
        _replace("all {count_steps} steps pass", "every step passes"),
        "neither",
    ),
    (
        "red-without-what-to-do",
        "docs-guide-fail.tmpl",
        _move_what_to_do_down,
        WHAT_TO_DO,
    ),
] + [
    (f"stem-{n}", "docs-guide-partial.tmpl", _add(f"x{stem}x"), "word stem")
    for n, stem in enumerate(BANNED_STEMS)
]


@pytest.mark.parametrize(
    "template, plant, fragment",
    [plant[1:] for plant in PLANTS],
    ids=[plant[0] for plant in PLANTS],
)
def test_the_rule_fires_on_a_planted_defect(template, plant, fragment):
    clean = read(template)
    assert problems(template, clean) == []
    found = problems(template, plant(clean))
    assert any(fragment in problem for problem in found), found


@pytest.mark.parametrize(
    "line",
    [
        "Sign in as admin@example.com.",
        "See https://github.com/getexperimently/experimently/blob/main/README.md",
        "See https://getexperimently.github.io/experimently/",
        "The pass named {check}, at 50% of the 8 steps.",
    ],
)
def test_what_public_text_may_say_passes(line):
    """The rules do not refuse the things a template legitimately says."""
    text = read("synthetic-recovered.tmpl") + "\n" + line + "\n"
    assert problems("synthetic-recovered.tmpl", text) == []
