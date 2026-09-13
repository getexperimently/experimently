"""The migration plan, written out: which heads exist and in what order they run.

``test_alembic_branch_order.py`` states the *properties* the two chains must
have (the branch descends from the revision it undoes, the label does not leak,
the branch point has one core child).  This file states the *answers*: the exact
head set and the exact sequence of revision ids ``alembic upgrade heads`` would
apply, for a full checkout and for a core one.

Both are worth having, because the properties are the ones somebody thought to
check and the plan is everything else.  Ordering here is action at a distance --
it is decided by ``down_revision``, ``branch_labels``, ``depends_on`` and
``alembic.ini``'s ``version_locations``, four things in three files, none of
which mentions the other -- and the last two review rounds each turned one of
them and moved the plan without meaning to:

* round 1 gave ``modules_0001_rbac`` ``down_revision = None`` plus a
  ``depends_on``, which collapsed the two heads into one recorded row, so a core
  image could not resolve ``alembic_version`` at all;
* round 2 removed the ``depends_on``, which made the branch an independent
  alembic *base* -- free to be scheduled anywhere, and scheduled early: it
  restored the two ``workspace_id`` foreign keys and ``a7b8c9d0e1f2`` then
  dropped them, on every deployment that had not taken the previous release.

Neither showed up as a failing assertion; both showed up as a paragraph in a
review. A diff of two lists would have said it in one line, which is what this
file is. When a revision is added, update the list -- and read the diff.

No database: this is the plan alembic builds from the files on disk.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "backend" / "app" / "db" / "alembic.ini"
CORE_VERSIONS = REPO_ROOT / "backend" / "app" / "db" / "migrations" / "versions"

pytestmark = pytest.mark.unit

#: The core chain's head: a marker revision, the second child of the branch
#: point, so that the core chain still has a head of its own.
CORE_HEAD = "b8c9d0e1f2a3"
#: The modules branch's head.
MODULES_HEAD = "modules_0001_rbac"
#: The core revision the branch must run *after*: it drops the two
#: ``workspace_id`` foreign keys that ``modules_0001_rbac`` puts back.
BRANCH_POINT = "a7b8c9d0e1f2"

#: Exactly what ``alembic upgrade heads`` applies, from base, on a **core**
#: checkout (no ``modules/``: alembic skips the version location it names and
#: sees one head).
CORE_PLAN = [
    "84a772608a6e",
    "ba93ceb4d658",
    "e45a2f9c8d21",
    "9734af8b92e1",
    "fce74a1b62d3",
    "1fd7a3fc10a0",
    "64e15548d39c",
    "a1b2c3d4e5f6",
    "e181583b4b24",
    "ep035_bayesian_cols",
    "ep036_split_url",
    "ep046_llm_experiments",
    "ep037_sso_config",
    "ep057_workspaces",
    "f1a2b3c4d5e6",
    "ep034_integration_configs",
    "6ea93af570f2",
    "a0ce135350af",
    "b1c2d3e4f5a6",
    "c2a9d3f1b7e4",
    "d4e5f6a7b8c9",
    "e5f6a7b8c9d0",
    "f6a7b8c9d0e1",
    "a7b8c9d0e1f2",
    "b8c9d0e1f2a3",
]

#: And on a **full** checkout: the same core chain with the modules branch
#: spliced in after the branch point -- after ``a7b8c9d0e1f2``, which is the
#: whole reason the edge exists, and before the core marker.
FULL_PLAN = [
    *CORE_PLAN[:-1],
    MODULES_HEAD,
    CORE_HEAD,
]


def _script(version_locations=None) -> ScriptDirectory:
    config = Config(str(ALEMBIC_INI))
    if version_locations is not None:
        config.set_main_option("version_locations", version_locations)
    return ScriptDirectory.from_config(config)


def _plan(script: ScriptDirectory) -> list[str]:
    """The revision ids ``upgrade heads`` applies, in order, from an empty database."""
    return [step.revision.revision for step in script._upgrade_revs("heads", "base")]


# ---------------------------------------------------------------------------
# Core checkout
# ---------------------------------------------------------------------------
@pytest.mark.regression
def test_a_core_checkout_has_one_head_and_this_plan():
    script = _script(version_locations=str(CORE_VERSIONS))

    assert sorted(script.revision_map.heads) == [CORE_HEAD]
    assert _plan(script) == CORE_PLAN


# ---------------------------------------------------------------------------
# Full checkout
# ---------------------------------------------------------------------------
@pytest.mark.regression
@pytest.mark.modules
def test_a_full_checkout_has_two_heads_and_this_plan():
    script = _script()

    assert sorted(script.revision_map.heads) == sorted([CORE_HEAD, MODULES_HEAD])
    # `heads` resolves to _real_heads; a depends_on edge would drop one of them
    # and `stamp heads` would write a single row (review round 1).
    assert sorted(script.revision_map._real_heads) == sorted([CORE_HEAD, MODULES_HEAD])
    assert _plan(script) == FULL_PLAN


@pytest.mark.regression
@pytest.mark.modules
def test_the_branch_runs_after_the_revision_it_undoes():
    """Said again as an index comparison, so the failure names the ordering.

    ``test_a_full_checkout_has_two_heads_and_this_plan`` fails on this too, with
    a 26-line diff; this one fails with "restored before it was dropped".
    """
    plan = _plan(_script())

    assert plan.index(MODULES_HEAD) > plan.index(BRANCH_POINT), (
        f"{MODULES_HEAD} restores the two workspace foreign keys and "
        f"{BRANCH_POINT} drops them; scheduled this way round, one "
        "`alembic upgrade heads` leaves them gone with nothing left to "
        "re-apply"
    )


@pytest.mark.modules
def test_the_core_plan_is_the_full_plan_without_the_branch():
    """A core checkout applies the same core revisions, in the same order.

    The modules branch may add to the plan and may not reorder it: a core
    database and a full one have to reach the same core schema by the same
    steps, or the two profiles have drifted apart.
    """
    full = _plan(_script())
    core = _plan(_script(version_locations=str(CORE_VERSIONS)))

    assert [rev for rev in full if rev != MODULES_HEAD] == core


# ---------------------------------------------------------------------------
# Rolling the branch back
# ---------------------------------------------------------------------------
#: What the documentation tells an operator to type to unapply the branch.
UNAPPLY_MODULES_BRANCH = "modules@-1"

#: Every file that spells a rollback command for this branch.
ROLLBACK_DOCS = (
    REPO_ROOT / "docs" / "self-hosting" / "migrations.md",
    REPO_ROOT / "docs" / "development" / "database" / "migrations.md",
    REPO_ROOT / "modules" / "backend" / "app" / "db" / "migrations" / "README",
)


def _downgrade_plan(script: ScriptDirectory, target: str) -> list[str]:
    heads = tuple(script.revision_map.heads)
    return [step.revision.revision for step in script._downgrade_revs(target, heads)]


@pytest.mark.regression
@pytest.mark.modules
def test_unapplying_the_branch_is_one_revision_and_modules_at_base_is_all_of_them():
    """``modules@base`` stopped naming this branch when it stopped being a base.

    ``modules_0001_rbac`` is a child of ``a7b8c9d0e1f2`` now, and with a single
    tree root alembic cannot filter a downgrade by branch label: ``modules@base``
    resolves to the whole core chain to base.  Three documents still told
    operators to type it (review round 4, finding 4).
    """
    script = _script()

    assert _downgrade_plan(script, UNAPPLY_MODULES_BRANCH) == [MODULES_HEAD]
    assert len(_downgrade_plan(script, "modules@base")) == len(FULL_PLAN)


#: A command line, not a mention of one: the three documents all warn about
#: ``modules@base`` in prose now, and must not hand it to anybody to run.
_MODULES_AT_BASE_COMMAND = re.compile(
    r"(?m)^\s*(?:\$ ?)?(?:python -m )?alembic\b.*downgrade modules@base"
)


@pytest.mark.regression
@pytest.mark.modules
def test_no_document_tells_an_operator_to_downgrade_to_modules_at_base():
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in ROLLBACK_DOCS
        if _MODULES_AT_BASE_COMMAND.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], (
        "`alembic downgrade modules@base` drops every table in the schema; "
        f"use `downgrade {UNAPPLY_MODULES_BRANCH}`"
    )
