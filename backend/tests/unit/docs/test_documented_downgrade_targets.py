"""No documented downgrade target silently crosses a column-dropping downgrade (#580).

The self-hosting migrations page, the rollback runbook and the Database
Migration workflow's help each name a revision id to downgrade to: the
``1ab99332f0ba`` re-run recipe (``downgrade a89544fb1075``, then ``upgrade
heads``) and the "undo the latest release's migration" example. A downgrade
to a fixed id unapplies every revision above it. So the day a new revision
lands on top of the documented target, the same command also runs the new
revision's ``downgrade()`` -- and if that drops a column, the recipe now
deletes stored data, while the page still says it "changes no data".

This asks alembic's own planner, with no database, which revisions each
documented target unapplies from the current heads, and reads each of those
revisions' ``downgrade()`` through ``ast`` for a ``drop_column`` call. A
crossing passes only when the part of the document that names the target
(its heading section, or for the workflow its line) also names the
column-dropping revision and says it drops: the recipe has to say so where an
operator reads it.

When this fails, fix the documents (the target, or a sentence naming the
revision and what its downgrade drops), never this file.
"""

from __future__ import annotations

import ast
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "backend" / "app" / "db" / "alembic.ini"
MIGRATIONS_PAGE = REPO_ROOT / "docs" / "self-hosting" / "migrations.md"
ROLLBACK_RUNBOOK = REPO_ROOT / "docs" / "deployment" / "rollback-runbook.md"
DB_MIGRATE = REPO_ROOT / ".github" / "workflows" / "db-migrate.yml"

#: A revision id named as a downgrade target: ``downgrade <id>`` (a shell
#: command), ``downgrade`` with target ``<id>`` (the workflow form), and
#: ``e.g. <id>`` (the help text and the runbook's Target bullet). The
#: quantifiers are bounded and the id shapes are the two this repository uses.
TARGET = re.compile(
    r"(?:\bdowngrade`?\s{1,4}(?:with\s{1,4}target\s{1,4})?|\be\.g\.\s{1,4})"
    r"`?(?P<rev>[0-9a-f]{12}|modules_\d{4}_[a-z0-9_]{1,64})\b"
)
_HEADING = re.compile(r"^#{1,6}\s")
_FENCE = re.compile(r"^\s*```")


@dataclass(frozen=True)
class Mention:
    """One documented target, and the text an operator reads around it."""

    source: str
    target: str
    context: str


def _markdown_sections(text: str) -> Iterator[str]:
    """The page split at its headings, ignoring ``#`` lines inside fences."""
    section: List[str] = []
    fenced = False
    for line in text.splitlines(keepends=True):
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced and _HEADING.match(line) and section:
            yield "".join(section)
            section = []
        section.append(line)
    if section:
        yield "".join(section)


def mentions(
    page: Optional[str] = None,
    runbook: Optional[str] = None,
    workflow: Optional[str] = None,
) -> List[Mention]:
    """Every documented downgrade target; a text argument replaces that file."""
    found: List[Mention] = []
    for name, path, text in (
        ("migrations.md", MIGRATIONS_PAGE, page),
        ("rollback-runbook.md", ROLLBACK_RUNBOOK, runbook),
    ):
        text = path.read_text(encoding="utf-8") if text is None else text
        for section in _markdown_sections(text):
            for match in TARGET.finditer(section):
                found.append(Mention(name, match.group("rev"), section))
    if workflow is None and DB_MIGRATE.is_file():
        workflow = DB_MIGRATE.read_text(encoding="utf-8")
    for line in (workflow or "").splitlines():
        for match in TARGET.finditer(line):
            found.append(Mention("db-migrate.yml", match.group("rev"), line))
    return found


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))


def drops_a_column(path: str) -> bool:
    """Whether the revision file's ``downgrade()`` calls ``drop_column``."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            return any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "drop_column"
                for call in ast.walk(node)
            )
    return False


def unapplied(script: ScriptDirectory, target: str) -> List[str]:
    """The revisions ``downgrade <target>`` unapplies from the current heads."""
    heads = tuple(script.revision_map.heads)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return [s.revision.revision for s in script._downgrade_revs(target, heads)]


def unannounced_crossings(
    found: List[Mention], script: Optional[ScriptDirectory] = None
) -> Dict[str, List[str]]:
    """``{"source: target": [column-dropping revisions it crosses unannounced]}``."""
    script = script or _script()
    known: Set[str] = {r.revision for r in script.walk_revisions()}
    problems: Dict[str, List[str]] = {}
    for mention in found:
        if mention.target not in known:
            # A placeholder such as ``ab1234567890``, or a modules id in a core
            # tree: there is nothing for alembic to plan.
            continue
        for revision in unapplied(script, mention.target):
            if not drops_a_column(script.get_revision(revision).path):
                continue
            context = mention.context.lower()
            if revision in mention.context and "drop" in context:
                continue
            crossed = problems.setdefault(f"{mention.source}: {mention.target}", [])
            if revision not in crossed:
                crossed.append(revision)
    return problems


def test_each_document_names_a_downgrade_target():
    """Without this, a reader that found nothing would pass every check."""
    sources = {m.source for m in mentions()}
    expected = {"migrations.md", "rollback-runbook.md"}
    if DB_MIGRATE.is_file():
        expected.add("db-migrate.yml")
    assert sources == expected, sources


def test_the_column_drop_reader_sees_drop_column():
    """Some revision on disk drops a column on downgrade; if none is seen, the
    reader is broken and every crossing would pass."""
    script = _script()
    assert any(drops_a_column(r.path) for r in script.walk_revisions())


#: ``a89544fb1075``'s downgrade drops a column, and a downgrade to its parent
#: unapplies it: a fixed control for the check below, on the real graph.
_DROPPING = "a89544fb1075"
_BELOW_IT = "271f03a31742"


def test_a_target_below_a_column_drop_is_refused():
    page = f"## Re-run\n\n```bash\nalembic downgrade {_BELOW_IT}\n```\n"
    found = [m for m in mentions(page=page) if m.source == "migrations.md"]
    assert [m.target for m in found] == [_BELOW_IT]
    assert _DROPPING in unannounced_crossings(found)[f"migrations.md: {_BELOW_IT}"]


def test_a_crossing_the_document_names_and_says_it_drops_passes():
    page = (
        f"## Re-run\n\nThis also runs {_DROPPING}'s downgrade, which drops "
        f"a column.\n\n```bash\nalembic downgrade {_BELOW_IT}\n```\n"
    )
    found = [m for m in mentions(page=page) if m.source == "migrations.md"]
    problems = unannounced_crossings(found)
    assert _DROPPING not in problems.get(f"migrations.md: {_BELOW_IT}", [])


def test_no_documented_target_crosses_a_column_dropping_downgrade_unannounced():
    problems = unannounced_crossings(mentions())
    assert problems == {}, (
        "A documented downgrade target now unapplies a revision whose "
        "downgrade() drops a column, and the document does not say so where it "
        "names the target. Fix the recipe or name the revision and what its "
        f"downgrade drops: {problems}"
    )
