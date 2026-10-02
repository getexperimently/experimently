"""The runbook the case-only email refusal points at (#343).

The core migration ``d12cbd384bbe`` refuses an upgrade while two accounts'
addresses differ only in letter case, and every one of its refusals ends with
``See docs/self-hosting/migrations.md#<anchor>``.  This pins, without a
database (it runs on a docs-only pull request):

* the anchor the migration prints is a heading of that page, slugified as
  mkdocs' ``toc`` extension does it, so the link an operator follows lands;
* the section's SQL steps are all there, labelled, in order, and say what the
  plan requires of them: the listing selects ``email`` (the record of each
  address as it was), the retire step builds ``retired-<id>@<domain>`` and its
  fallback ``r-<id>@<domain>``, no step deletes a user, and the prose states
  the 55- and 61-character domain limits.

Whether that SQL actually resolves a refused upgrade is run against PostgreSQL
by ``backend/tests/integration/database/test_users_email_lower_migration.py``,
which reads the blocks through :func:`sql_blocks` here.
"""

from __future__ import annotations

import pathlib
import re
import unicodedata

import pytest

pytestmark = [pytest.mark.unit]

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
PAGE = REPO_ROOT / "docs" / "self-hosting" / "migrations.md"
VERSIONS = REPO_ROOT / "backend" / "app" / "db" / "migrations" / "versions"

#: The labels (each block's first line) of the section's SQL steps, in order.
LIST = "-- List the accounts in each group"
COPY_ROLE = "-- Give the kept account the role of the one you retire"
RETIRE = "-- Retire the other account"
RETIRE_LONG_DOMAIN = "-- If the domain is longer than 55 characters"
CHECK = "-- Check that no group is left"
LABELS = [LIST, COPY_ROLE, RETIRE, RETIRE_LONG_DOMAIN, CHECK]

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_SQL_BLOCK = re.compile(r"^[ \t]*```sql\n(.*?)^[ \t]*```", re.M | re.S)


def slugify(title: str) -> str:
    """Python-Markdown's default ``toc`` slugify (mkdocs.yml sets no other)."""
    value = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def headings(text: str) -> list[tuple[int, str]]:
    """(level, title) of every heading outside a fenced block."""
    found, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        match = None if fenced else _HEADING.match(line)
        if match:
            found.append((len(match.group(1)), match.group(2)))
    return found


def refusal_anchor() -> str:
    """The ``#anchor`` every refusal of the migration ends with."""
    (link,) = set(
        re.findall(
            r"docs/self-hosting/migrations\.md#([a-z0-9-]+)",
            next(VERSIONS.glob("d12cbd384bbe_*.py")).read_text(encoding="utf-8"),
        )
    )
    return link


def section(text: str | None = None) -> str:
    """The page from the refusal's heading to the next heading of its level."""
    text = PAGE.read_text(encoding="utf-8") if text is None else text
    lines = text.splitlines(keepends=True)
    start = level = None
    for i in range(len(lines)):
        line = lines[i]
        match = _HEADING.match(line)
        if not match:
            continue
        if start is None and slugify(match.group(2)) == refusal_anchor():
            start, level = i, len(match.group(1))
        elif start is not None and len(match.group(1)) <= level:
            return "".join(lines[start:i])
    assert start is not None, f"no heading slugifies to {refusal_anchor()!r}"
    return "".join(lines[start:])


def sql_blocks(text: str | None = None) -> dict[str, str]:
    """The section's ```sql blocks, by their first-line label, dedented."""
    blocks = {}
    for body in _SQL_BLOCK.findall(section(text)):
        lines = body.splitlines()
        indent = min(len(line) - len(line.lstrip()) for line in lines if line.strip())
        sql = "\n".join(line[indent:] for line in lines).strip()
        label = sql.splitlines()[0]
        assert label not in blocks, f"two blocks are labelled {label!r}"
        blocks[label] = sql
    return blocks


@pytest.mark.regression
def test_the_refusals_anchor_is_a_heading_of_the_page():
    anchor = refusal_anchor()
    slugs = [slugify(title) for _, title in headings(PAGE.read_text("utf-8"))]
    assert anchor == "email-addresses-that-differ-only-in-case"
    assert anchor in slugs, f"{anchor!r} is not one of the page's anchors"


def test_the_slugify_matches_the_pages_existing_anchors():
    """The probe: an anchor other pages already link to slugifies as linked."""
    slugs = {slugify(title) for _, title in headings(PAGE.read_text("utf-8"))}
    assert "an-older-image-against-a-newer-database" in slugs
    assert slugify('Resolving "Multiple Heads" Errors') == (
        "resolving-multiple-heads-errors"
    )


def test_every_sql_step_is_there_in_order():
    assert list(sql_blocks()) == LABELS


def test_the_listing_selects_the_address_as_stored():
    listing = sql_blocks()[LIST]
    assert re.search(r"\bemail,", listing), listing
    assert "GROUP BY lower(email) HAVING count(*) > 1" in listing


def test_the_steps_build_the_retired_addresses_and_never_delete():
    blocks = sql_blocks()
    assert "'retired-' || id || '@' || split_part(email, '@', 2)" in blocks[RETIRE]
    assert (
        "'r-' || id || '@' || split_part(email, '@', 2)" in blocks[RETIRE_LONG_DOMAIN]
    )
    for label in (RETIRE, RETIRE_LONG_DOMAIN):
        assert "is_active = false" in blocks[label]
    for label, sql in blocks.items():
        assert not re.search(r"\bDELETE\b", sql, re.I), label
    assert "'<id to keep>'" in blocks[COPY_ROLE]
    assert "'<id to retire>'" in blocks[COPY_ROLE]


def test_the_domain_limits_and_the_warnings_are_stated():
    text = " ".join(section().split())
    assert "at most **55 characters**" in text
    assert "up to **61 characters**" in text
    assert "**Do not delete the account instead of retiring it.**" in text
    assert "**Do not build the index by hand.**" in text
    assert "Keep the account the person actually signs in with" in text
    assert "one tab-separated line" in text
    assert "last line" not in text


def test_a_renamed_heading_breaks_the_anchor():
    """The tamper, kept: the same page with the heading reworded has no anchor."""
    renamed = PAGE.read_text("utf-8").replace(
        "## Email addresses that differ only in case",
        "## Email addresses that differ in case",
    )
    slugs = [slugify(title) for _, title in headings(renamed)]
    assert refusal_anchor() not in slugs
    with pytest.raises(AssertionError, match="no heading slugifies"):
        section(renamed)
